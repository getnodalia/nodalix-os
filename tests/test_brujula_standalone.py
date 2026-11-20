"""Offline regression tests for browser-only signed pacman publishing."""
import importlib.util
import io
from pathlib import Path
import tarfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "signed_baseline", ROOT / "tools/ci-fetch-signed-repo.py"
)
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)


def signed_database(entries):
    blob = io.BytesIO()
    with tarfile.open(fileobj=blob, mode="w:gz") as archive:
        for name, filename in entries:
            description = (
                f"%FILENAME%\n{filename}\n\n%NAME%\n{name}\n\n"
                f"%VERSION%\n0.7.0-1\n\n%CSIZE%\n1024\n\n"
                f"%SHA256SUM%\n{'a' * 64}\n\n"
            ).encode()
            member = tarfile.TarInfo(f"{name}-0.7.0-1/desc")
            member.size = len(description)
            archive.addfile(member, io.BytesIO(description))
    return blob.getvalue()


COMPLETE = [
    ("nodalix-keyring", "nodalix-keyring-0.7.0-1-any.pkg.tar.zst"),
    ("nodalix-release", "nodalix-release-0.7.0-1-any.pkg.tar.zst"),
    ("linux-nodalix", "linux-nodalix-0.7.0-1-x86_64.pkg.tar.zst"),
    ("nodalix-brujula", "nodalix-brujula-0.7.0-1-x86_64.pkg.tar.zst"),
]


class SignedBaselineTests(unittest.TestCase):
    def test_complete_pacman_database_is_accepted(self):
        entries = baseline.parse_database(signed_database(COMPLETE))
        self.assertEqual(len(entries), 4)
        self.assertEqual({r["name"] for r in entries}, {name for name, _ in COMPLETE})

    def test_incomplete_repository_cannot_be_republished(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            baseline.parse_database(signed_database(COMPLETE[:-1]))

    def test_path_traversal_is_rejected_before_fetch(self):
        entries = COMPLETE[:-1] + [("nodalix-brujula", "../malicious.pkg.tar.zst")]
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            baseline.parse_database(signed_database(entries))

    def test_duplicate_pacman_packages_cannot_be_published(self):
        entries = COMPLETE + [("nodalix-brujula", "nodalix-brujula-0.8.0-1-x86_64.pkg.tar.zst")]
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            baseline.parse_database(signed_database(entries))

    def test_corrupt_database_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Invalid"):
            baseline.parse_database(b"not a pacman database")


class StandaloneWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load(
            (ROOT / ".github/workflows/brujula-package.yml").read_text()
        )
        cls.text = (ROOT / ".github/workflows/brujula-package.yml").read_text()
        cls.triggers = cls.workflow.get("on", cls.workflow.get(True))

    def test_browser_only_main_push_and_manual_dispatch(self):
        self.assertEqual(
            set(self.triggers), {"push", "pull_request", "workflow_dispatch"}
        )
        self.assertIn("packaging/nodalix-brujula/PKGBUILD", self.triggers["push"]["paths"])
        self.assertEqual(self.triggers["push"]["branches"], ["main"])

    def test_main_ci_skips_standalone_browser_commits(self):
        ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
        triggers = ci.get("on", ci.get(True))
        self.assertIn("packaging/nodalix-brujula/PKGBUILD", triggers["push"]["paths-ignore"])
        self.assertIn("release/components.json", triggers["push"]["paths-ignore"])

    def test_only_deploy_receives_pages_permissions(self):
        for name, job in self.workflow["jobs"].items():
            perms = job.get("permissions", {})
            self.assertEqual(
                perms.get("pages") == "write" or perms.get("id-token") == "write",
                name == "deploy",
            )

    def test_only_main_signs_with_protected_key(self):
        build, sign = self.workflow["jobs"]["build"], self.workflow["jobs"]["sign"]
        self.assertNotIn("environment", build)
        self.assertEqual(sign["environment"], "nodalix-repo-signing")
        self.assertIn("github.ref == 'refs/heads/main'", sign["if"])
        self.assertIn("secrets.NODALIX_REPO_GPG_KEY", self.text)
        self.assertIn("publish-pacman-repo", self.text)
        self.assertIn("tools/ci-publish-brujula.sh", self.text)
        self.assertNotIn("tools/ci-build-iso.sh", self.text)
        self.assertNotIn("tools/ci-build-gnome.sh", self.text)

    def test_previously_published_packages_are_verified_and_preserved(self):
        builder = (ROOT / "tools/ci-publish-brujula.sh").read_text()
        fetch = (ROOT / "tools/ci-fetch-signed-repo.py").read_text()
        self.assertIn("ci-fetch-signed-repo.py", builder)
        self.assertIn("ci-publish-repo.sh", builder)
        self.assertIn("vercmp", builder)
        self.assertIn('EXPECTED_KEY = "3DE029728CDE1828E18B437930D356AC0F6AB1CF"', fetch)
        self.assertIn('gpg(["--verify", str(signature), str(database)]', fetch)
        self.assertIn('gpg(["--verify", str(detached), str(package)]', fetch)

    def test_upstream_sync_dispatches_targeted_ci(self):
        sync = (ROOT / ".github/workflows/sync-brujula.yml").read_text()
        self.assertIn('gh workflow run brujula-package.yml --ref "$branch"', sync)
        self.assertNotIn('gh workflow run ci.yml --ref "$branch"', sync)


if __name__ == "__main__":
    unittest.main()
