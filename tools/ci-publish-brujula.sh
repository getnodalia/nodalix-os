#!/usr/bin/env bash
# Update exactly Brújula while keeping EVERY previously published signed package.
# Run inside the protected signing job's ephemeral Arch container.
set -euo pipefail
[[ ${NODALIX_CI_CONTAINER:-} == 1 ]] || { echo 'CI container required' >&2; exit 1; }
pacman -Syu --noconfirm
pacman -S --needed --noconfirm python gnupg

shopt -s nullglob
candidates=(dist/brujula-package/nodalix-brujula-*.pkg.tar.zst)
[[ ${#candidates[@]} == 1 ]] || { echo 'Expected one candidate' >&2; exit 1; }
candidate=${candidates[0]}
(cd dist/brujula-package && sha256sum -c SHA256SUMS)
read -r new_name new_version < <(pacman -Qp -- "$candidate")
[[ $new_name == nodalix-brujula ]] || { echo 'Unexpected package' >&2; exit 1; }
expected=$(sed -n 's/^pkgver=//p' packaging/nodalix-brujula/PKGBUILD)
[[ "$new_version" == "$expected"-* ]] || { echo 'Unexpected Brújula version' >&2; exit 1; }

# The current pacman database and each existing package are independently
# checked against Nodalix's pinned public key before a replacement is allowed.
python3 tools/ci-fetch-signed-repo.py dist/published-packages
old=(dist/published-packages/nodalix-brujula-*.pkg.tar.zst)
[[ ${#old[@]} == 1 ]] || { echo 'Published repository must contain Brújula' >&2; exit 1; }
read -r old_name old_version < <(pacman -Qp -- "${old[0]}")
[[ $old_name == nodalix-brujula ]] || exit 1
(( $(vercmp "$new_version" "$old_version") >= 0 )) || {
  echo "Refusing browser downgrade from $old_version to $new_version" >&2; exit 1;
}

rm -f -- "${old[0]}"
cp -- "$candidate" dist/published-packages/
# ci-publish-repo.sh imports the private key only now, verifies its fingerprint,
# re-signs the complete package set and creates a signed database.
bash tools/ci-publish-repo.sh dist/published-packages dist/pages
echo "Signed Nodalix repository updated: Brújula $old_version -> $new_version"
