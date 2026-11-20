"""Offline regression tests for authenticated historical release metadata."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "historical_upgrades", ROOT / "tools/ci-upgrade-history.py"
)
upgrade = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(upgrade)


class AuthenticatedHistoryTests(unittest.TestCase):
    def test_historical_release_index_is_loaded_from_json_file(self):
        with tempfile.TemporaryDirectory() as temp:
            index = Path(temp) / "releases.json"
            releases = [{"tag_name": "v0.6.0", "assets": [], "draft": False}]
            index.write_text(json.dumps(releases), encoding="utf-8")
            self.assertEqual(upgrade.load_releases(index), releases)

    def test_missing_index_does_not_fall_back_to_unauthenticated_api(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileNotFoundError):
                upgrade.load_releases(Path(temp) / "missing.json")

    def test_invalid_index_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            index = Path(temp) / "releases.json"
            index.write_text('{"message": "API rate limit exceeded"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON list"):
                upgrade.load_releases(index)

    def test_ci_downloads_metadata_outside_unprivileged_container(self):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        )
        history = workflow["jobs"]["upgrade-history"]["steps"]
        metadata = next(
            step for step in history
            if step.get("name") == "Fetch historical releases with read-only GitHub token"
        )
        test = next(
            step for step in history
            if step.get("name") == "Upgrade every published earlier release with real pacman"
        )
        self.assertEqual(metadata["env"]["GH_TOKEN"], "${{ github.token }}")
        self.assertIn('gh api "repos/$GITHUB_REPOSITORY/releases?per_page=100"', metadata["run"])
        self.assertNotIn("GH_TOKEN", test["run"])
        self.assertNotIn(" -e GH_TOKEN", test["run"])
        self.assertIn("tools/ci-upgrade-history.py", test["run"])


if __name__ == "__main__":
    unittest.main()
