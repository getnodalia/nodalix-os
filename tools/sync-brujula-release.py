#!/usr/bin/env python3
"""Track stable Brújula releases without coupling browser versions to Nodalix OS.

This script updates only the pinned upstream commit and the browser component.
The resulting changes must pass CI and review before the signed repo is published.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "getnodalia/brujula"
API = f"https://api.github.com/repos/{REPO}"
VERSION_RE = re.compile(r"^(?:v)?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SHA_RE = re.compile(r"^[a-f0-9]{40}$")
PKGBUILD = ROOT / "packaging/nodalix-brujula/PKGBUILD"
COMPONENTS = ROOT / "release/components.json"


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Nodalix-Brujula-Release-Sync",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError(f"unexpected GitHub response from {url}")
    return result


def version_key(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"not a stable semantic version: {value!r}")
    return tuple(int(v) for v in match.groups())


def release_commit(tag: str) -> str:
    if VERSION_RE.fullmatch(tag) is None or not tag.startswith("v"):
        raise ValueError("release tag must be vMAJOR.MINOR.PATCH")
    data = fetch_json(f"{API}/git/ref/tags/{tag}")
    if data.get("ref") != f"refs/tags/{tag}":
        raise ValueError("tag reference mismatch")
    target = data.get("object", {})
    for _ in range(3):
        typ, sha = target.get("type"), target.get("sha", "")
        if not SHA_RE.fullmatch(sha):
            raise ValueError("invalid Git object id")
        if typ == "commit":
            return sha
        if typ != "tag":
            raise ValueError(f"unexpected tag object: {typ}")
        target = fetch_json(f"{API}/git/tags/{sha}").get("object", {})
    raise ValueError("too many nested annotated tags")


def sync_files(version: str, commit: str, pkg_path: Path, components_path: Path) -> bool:
    if not SHA_RE.fullmatch(commit):
        raise ValueError("commit must be an immutable, full Git SHA")
    incoming = version_key(version)
    original = pkg_path.read_text(encoding="utf-8")
    version_match = re.search(r"^pkgver=(\d+\.\d+\.\d+)$", original, re.M)
    pin_match = re.search(r"^_brujula_commit=([0-9a-f]{40})$", original, re.M)
    if version_match is None or pin_match is None:
        raise ValueError("Brújula PKGBUILD lacks its version or exact commit pin")
    installed = version_key(version_match.group(1))
    if incoming <= installed:
        return False
    if "git+https://github.com/getnodalia/brujula.git#commit=$_brujula_commit" not in original:
        raise ValueError("refusing to update an unexpected Brújula source")
    data = json.loads(components_path.read_text(encoding="utf-8"))
    rows = [x for x in data["components"] if x.get("id") == "brujula"]
    if len(rows) != 1 or rows[0].get("package") != "nodalix-brujula":
        raise ValueError("expected a single managed Brújula component")
    if version_key(rows[0]["version"]) != installed:
        raise ValueError("manifest and PKGBUILD versions disagree")
    version_plain = ".".join(map(str, incoming))
    replacement = original.replace(f"pkgver={version_match.group(1)}", f"pkgver={version_plain}", 1)
    replacement = replacement.replace(f"_brujula_commit={pin_match.group(1)}", f"_brujula_commit={commit}", 1)
    component = components_path.read_text(encoding="utf-8")
    # Preserve formatting and avoid changing other versions in the release manifest.
    pattern = r'("id": "brujula",[\s\S]*?"version": ")' + re.escape(rows[0]["version"]) + r'(")'
    updated, changes = re.subn(pattern, lambda m: m.group(1) + version_plain + m.group(2), component, count=1)
    if changes != 1:
        raise ValueError("could not update Brújula version in the manifest")
    pkg_path.write_text(replacement, encoding="utf-8")
    components_path.write_text(updated, encoding="utf-8")
    return True


def main() -> None:
    release = fetch_json(f"{API}/releases/latest")
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("latest release is not stable")
    tag = str(release.get("tag_name", ""))
    version_key(tag)
    commit = release_commit(tag)
    updated = sync_files(tag, commit, PKGBUILD, COMPONENTS)
    print(f"Brújula {tag} @ {commit}: {'updated' if updated else 'already current'}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"version={tag.removeprefix('v')}\n")
            f.write(f"updated={str(updated).lower()}\n")


if __name__ == "__main__":
    main()
