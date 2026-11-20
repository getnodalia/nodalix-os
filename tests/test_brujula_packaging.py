import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKGBUILD = (ROOT / "packaging/nodalix-brujula/PKGBUILD").read_text(encoding="utf-8")


class BrujulaPackagingTests(unittest.TestCase):
    def test_source_is_pinned_to_a_git_commit(self):
        commit = re.search(r"^_brujula_commit=([0-9a-f]{40})$", PKGBUILD, re.M)
        self.assertTrue(commit, "the source must be pinned to a full commit")
        self.assertIn("#commit=$_brujula_commit", PKGBUILD)
        self.assertIn("git+https://github.com/getnodalia/brujula.git", PKGBUILD)
        # In makepkg, VCS sources are integrity-checked by the pinned Git commit,
        # not by a non-reproducible archive SHA-256.
        self.assertIn("sha256sums=('SKIP')", PKGBUILD)
        self.assertNotIn("#tag=", PKGBUILD)
        self.assertNotIn("#branch=", PKGBUILD)

    def test_version_matches_component_manifest(self):
        import json

        version = re.search(r"^pkgver=([0-9]+\.[0-9]+\.[0-9]+)$", PKGBUILD, re.M)
        self.assertIsNotNone(version)
        rows = json.loads((ROOT / "release/components.json").read_text(encoding="utf-8"))["components"]
        browser = next(row for row in rows if row["id"] == "brujula")
        self.assertEqual(browser["version"], version.group(1))

    def test_it_replaces_the_unpinned_upstream_package(self):
        self.assertIn("conflicts=('brujula')", PKGBUILD)
        self.assertIn("replaces=('brujula')", PKGBUILD)
        self.assertIn("provides=('brujula' 'webbrowser')", PKGBUILD)

    def test_it_is_the_default_browser(self):
        for kind in ("text/html", "x-scheme-handler/http", "x-scheme-handler/https"):
            self.assertIn(f"{kind}=dev.danielmiguelt.Brujula.desktop", PKGBUILD)
        self.assertIn("/etc/xdg/gnome-mimeapps.list", PKGBUILD)

    def test_the_build_script_builds_it_into_the_release_set(self):
        script = (ROOT / "tools/build-packages.sh").read_text(encoding="utf-8")
        self.assertIn('makepkg_one "$brujula_dir"', script)
        self.assertIn('brujula_dir="$workdir/nodalix-brujula"', script)


if __name__ == "__main__":
    unittest.main()
