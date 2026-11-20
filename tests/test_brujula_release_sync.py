"""Offline tests for the independent browser-release synchronization."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "tools/sync-brujula-release.py"
SPEC = importlib.util.spec_from_file_location("sync_brujula", SCRIPT)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)
PIN = "a" * 40
NEW_PIN = "b" * 40


class BrujulaReleaseSyncTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        root = Path(self.work.name)
        self.pkg = root / "PKGBUILD"
        self.pkg.write_text(
            "pkgname=nodalix-brujula\npkgver=0.10.0\n_brujula_commit=" + PIN
            + "\nsource=(\"brujula::git+https://github.com/getnodalia/brujula.git#commit=$_brujula_commit\")\n",
            encoding="utf-8",
        )
        self.components = root / "components.json"
        self.components.write_text(json.dumps({"components": [
            {"id": "brujula", "package": "nodalix-brujula", "version": "0.10.0"},
            {"id": "updater", "package": "nodalix-updater", "version": "0.6.1"},
        ]}, indent=2), encoding="utf-8")

    def test_upgrade_changes_only_browser(self):
        self.assertTrue(sync.sync_files("v0.11.0", NEW_PIN, self.pkg, self.components))
        self.assertIn("pkgver=0.11.0", self.pkg.read_text())
        self.assertIn(f"_brujula_commit={NEW_PIN}", self.pkg.read_text())
        components = json.loads(self.components.read_text())["components"]
        self.assertEqual(components[0]["version"], "0.11.0")
        self.assertEqual(components[1]["version"], "0.6.1")

    def test_no_downgrade_or_duplicate_change(self):
        previous = self.pkg.read_text()
        self.assertFalse(sync.sync_files("v0.9.5", NEW_PIN, self.pkg, self.components))
        self.assertFalse(sync.sync_files("v0.10.0", NEW_PIN, self.pkg, self.components))
        self.assertEqual(self.pkg.read_text(), previous)

    def test_reject_prerelease_and_bad_commit(self):
        with self.assertRaises(ValueError):
            sync.version_key("v0.11.0-beta.1")
        with self.assertRaises(ValueError):
            sync.sync_files("v0.11.0", "main", self.pkg, self.components)

    def test_resolves_annotated_tag_to_commit(self):
        with patch.object(sync, "fetch_json", side_effect=[
            {"ref": "refs/tags/v0.11.0", "object": {"type": "tag", "sha": "c" * 40}},
            {"object": {"type": "commit", "sha": NEW_PIN}},
        ]):
            self.assertEqual(sync.release_commit("v0.11.0"), NEW_PIN)


if __name__ == "__main__":
    unittest.main()
