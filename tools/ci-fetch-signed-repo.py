#!/usr/bin/env python3
"""Mirror a published Nodalix pacman repository only after verifying its signatures.

The baseline must remain complete: GitHub Pages deployments replace the entire site.
This script is deliberately read-only with respect to the remote repository.
"""
from __future__ import annotations

import hashlib
import io
from contextlib import closing
from http.client import HTTPSConnection
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import quote

REPO_HOST = "getnodalia.github.io"
REPO_PREFIX = "/nodalix-os/x86_64/"
OUTPUT_DIR = Path("dist/published-packages")
EXPECTED_KEY = "3DE029728CDE1828E18B437930D356AC0F6AB1CF"
PUBLIC_KEY = Path("packaging/nodalix-keyring/nodalix-repo-key.pgp")
BUDGET = 900 * 1024 * 1024
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+@-]*\.pkg\.tar\.zst$")
SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")


def parse_database(blob: bytes) -> list[dict[str, str | int]]:
    """Read and strictly validate the signed pacman DB without extracting it."""
    entries = []
    seen_names, seen_files = set(), set()
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
            for member in archive:
                if not member.isfile() or not member.name.endswith("/desc"):
                    continue
                if member.size > 65536 or len(entries) >= 200:
                    raise ValueError("Repository database has oversized or too many entries")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("Unreadable repository entry")
                body = stream.read().decode("utf-8")
                fields = dict(re.findall(
                    r"%([A-Z0-9_]+)%\n(.*?)(?=\n%[A-Z0-9_]+%\n|\Z)",
                    body, re.DOTALL,
                ))
                for required in ("FILENAME", "NAME", "VERSION", "CSIZE", "SHA256SUM"):
                    if required not in fields or not fields[required].strip():
                        raise ValueError(f"Missing {required} in repository entry")
                filename = fields["FILENAME"].strip()
                name, version = fields["NAME"].strip(), fields["VERSION"].strip()
                digest = fields["SHA256SUM"].strip().lower()
                size_text = fields["CSIZE"].strip()
                if not NAME.fullmatch(filename) or not re.fullmatch(r"[A-Za-z0-9@._+-]+", name):
                    raise ValueError("Unsafe package filename or name")
                if not SHA256.fullmatch(digest) or not size_text.isdecimal():
                    raise ValueError("Invalid package checksum or size")
                size = int(size_text)
                if not 0 < size <= BUDGET or any(c in version for c in "\r\n\t/"):
                    raise ValueError("Invalid package version or size")
                if name in seen_names or filename in seen_files:
                    raise ValueError("Duplicate package name or filename")
                seen_names.add(name)
                seen_files.add(filename)
                entries.append({
                    "filename": filename, "name": name, "version": version,
                    "sha256": digest, "size": size,
                })
    except (tarfile.TarError, UnicodeError, OSError) as exc:
        raise ValueError("Invalid signed repository database") from exc

    required = {"nodalix-keyring", "nodalix-release", "linux-nodalix", "nodalix-brujula"}
    if not required.issubset(seen_names):
        raise ValueError("Published repository is incomplete")
    if sum(int(row["size"]) for row in entries) >= BUDGET:
        raise ValueError("Published repository exceeds GitHub Pages budget")
    return sorted(entries, key=lambda row: str(row["filename"]))


def fetch(filename: str, destination: Path, limit: int, allowed_root: Path) -> None:
    """Get an exact repository file from the pinned TLS host without redirects.

    Both the domain and destination directory are fixed by this script. Only
    simple signed package filenames or the two database objects are allowed.
    """
    if not (
        filename in {"nodalix.db", "nodalix.db.sig"}
        or NAME.fullmatch(filename)
        or (filename.endswith(".sig") and NAME.fullmatch(filename[:-4]))
    ):
        raise ValueError("Unexpected repository object name")
    if not 0 < limit <= BUDGET:
        raise ValueError("Invalid download limit")

    # The target must be inside the two private, known output roots. Opening
    # in exclusive mode prevents overwrites, including existing symlink paths.
    if destination.parent.resolve(strict=True) != allowed_root.resolve(strict=True):
        raise ValueError("Unexpected output path")
    if destination.is_symlink():
        raise ValueError("Refusing to write through a symlink")

    with closing(HTTPSConnection(REPO_HOST, timeout=180)) as connection:
        connection.request(
            "GET", REPO_PREFIX + quote(filename, safe=""),
            headers={"User-Agent": "Nodalix-signed-repository-publisher"},
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f"Repository returned HTTP {response.status} for {filename}")

        # Never follow redirects. The TCP/TLS connection always targets our
        # pinned GitHub Pages hostname and certificate verification is on.
        with destination.open("xb") as output:
            count = 0
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > limit:
                    raise ValueError(f"Repository object exceeds its size limit: {filename}")
                output.write(chunk)


def gpg(args: list[str], env: dict[str, str]) -> str:
    process = subprocess.run(
        ["gpg", "--batch", *args], env=env, capture_output=True, text=True, check=True
    )
    return process.stdout


def main() -> None:
    if len(sys.argv) != 1:
        raise SystemExit("Usage: ci-fetch-signed-repo.py")
    output = OUTPUT_DIR
    # A clean output directory is mandatory. Do not traverse symlinks or
    # reuse artifacts from previous jobs.
    output.mkdir(parents=True, exist_ok=False)

    with tempfile.TemporaryDirectory(prefix="nodalix-repo-") as directory:
        work = Path(directory)
        os.chmod(work, 0o700)
        env = {**os.environ, "GNUPGHOME": directory}
        gpg(["--import", str(PUBLIC_KEY)], env)
        fingerprint = next(
            (line.split(":")[9] for line in gpg(
                ["--with-colons", "--fingerprint", "--list-keys"], env
            ).splitlines() if line.startswith("fpr:")), None
        )
        if fingerprint != EXPECTED_KEY:
            raise ValueError("Public signing key does not match the pinned Nodalix key")

        database = work / "nodalix.db"
        signature = work / "nodalix.db.sig"
        fetch("nodalix.db", database, 8 * 1024 * 1024, work)
        fetch("nodalix.db.sig", signature, 32768, work)
        gpg(["--verify", str(signature), str(database)], env)
        entries = parse_database(database.read_bytes())

        for index, row in enumerate(entries, 1):
            filename = str(row["filename"])
            package = output / filename
            fetch(filename, package, int(row["size"]), output)
            if package.stat().st_size != row["size"]:
                raise ValueError(f"Package size mismatch: {filename}")
            with package.open("rb") as file:
                digest = hashlib.file_digest(file, "sha256").hexdigest()
            if digest != row["sha256"]:
                raise ValueError(f"Package checksum mismatch: {filename}")
            detached = work / (filename + ".sig")
            fetch(filename + ".sig", detached, 32768, work)
            gpg(["--verify", str(detached), str(package)], env)
            print(f"Verified {index}/{len(entries)}: {filename}", flush=True)

    print(f"Complete signed baseline verified: {len(entries)} packages")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Refusing to publish incomplete or untrusted repository: {exc}") from exc
