#!/usr/bin/env bash
# Build only the native browser package. Runs in a disposable Arch container,
# with no repository signing key and without compiling the Nodalix kernel/ISO.
set -euo pipefail
[[ ${NODALIX_CI_CONTAINER:-} == 1 ]] || { echo 'CI container required' >&2; exit 1; }
pacman -Syu --noconfirm
pacman -S --needed --noconfirm base-devel git rust cargo pkgconf gtk4 webkitgtk-6.0 \
  libsoup3 libsecret zstd python python-yaml

python3 -m unittest discover -s tests -p 'test_brujula*.py' -v

install -d -m 755 dist/brujula-work dist/brujula-package
cp packaging/nodalix-brujula/PKGBUILD dist/brujula-work/PKGBUILD
useradd -m browser-builder
chown -R browser-builder:browser-builder dist/brujula-work dist/brujula-package

runuser -u browser-builder -- bash -c '
  set -euo pipefail
  cd /src/dist/brujula-work
  export PKGDEST=/src/dist/brujula-package
  makepkg -f --noconfirm --nodeps --cleanbuild
'

shopt -s nullglob
candidates=(dist/brujula-package/nodalix-brujula-*.pkg.tar.zst)
[[ ${#candidates[@]} == 1 ]] || { echo 'Expected exactly one native Brújula package' >&2; exit 1; }
candidate=${candidates[0]}
read -r name version < <(pacman -Qp -- "$candidate")
[[ "$name" == nodalix-brujula ]] || exit 1
expected=$(sed -n 's/^pkgver=//p' packaging/nodalix-brujula/PKGBUILD)
[[ "$version" == "$expected"-* ]] || { echo 'Package version mismatch' >&2; exit 1; }
python3 - "$expected" <<'PY'
import json, sys
data = json.load(open("release/components.json", encoding="utf-8"))
browser = next(row for row in data["components"] if row["id"] == "brujula")
assert browser["version"] == sys.argv[1] and browser["package"] == "nodalix-brujula"
PY
for owned in usr/bin/brujula usr/share/applications/dev.danielmiguelt.Brujula.desktop \
  usr/share/icons/hicolor/scalable/apps/dev.danielmiguelt.Brujula.svg \
  etc/xdg/gnome-mimeapps.list; do
  bsdtar -tf "$candidate" | grep -Fxq "$owned" || { echo "Missing $owned" >&2; exit 1; }
done
(cd dist/brujula-package && sha256sum ./*.pkg.tar.zst > SHA256SUMS)
echo "Independently compiled native Brújula package: $candidate"
