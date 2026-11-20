# Brújula: independent, signed browser updates

Brújula is included by default in Nodalix OS, but its version **does not follow
the Nodalix OS VERSION**. The upstream browser can publish security releases
between OS releases.

## Distribution policy

- The installed application is the native `nodalix-brujula` pacman package.
  `nodalix-release` depends on this name. Never remove it to install a second
  copy, and never use `pacman -Rdd` to bypass the dependency.
- The package compiles the exact **Git commit** of a stable
  `getnodalia/brujula` release. The Git object id secures the VCS checkout;
  a moving tag or branch must not be used. The resulting binary package and
  pacman repository are signed with the Nodalix repository key.
- The browser uses the **system WebKitGTK package** and system GTK libraries;
  critical WebKit patches must arrive through normal package updates. An
  AppImage may be appropriate on other distros but is not how Nodalix's
  system-managed browser should be upgraded.
- An in-browser update notice for a managed installation must lead to the
  package manager, **not** download and overwrite a root-owned binary.
- NXPM's Nodalia AppImage catalogue hides Brújula if the native package is
  installed, and refuses a duplicate install/update. It still permits removing
  a pre-existing NXPM AppImage.

## Version flow — browser-only CI

1. The scheduled `sync-brujula.yml` checks stable `getnodalia/brujula`
   releases, resolves the immutable Git commit, and opens a reviewable PR.
   The bot dispatches `brujula-package.yml` on its branch; no full Nodalix
   kernel, GNOME package set, migrations or ISO build is needed for this check.
2. `brujula-package.yml` builds **only** `nodalix-brujula` in an unprivileged
   `makepkg` process inside a disposable Arch container. It checks the pinned
   source/version, package files, desktop integration, manifest and browser
   unit tests. Pull requests have **no access to the signing key**.
3. Once reviewed and merged into `main`, the browser workflow runs again.
   The signing job requires the current reviewed `main` SHA and the existing
   `nodalix-repo-signing` protected environment. It downloads the **currently
   published** `[nodalix]` repository from GitHub Pages, verifies the signed
   database and **every existing package's detached PGP signature and SHA-256**
   with the pinned Nodalix public key, rejects missing packages and downgrades,
   and replaces only `nodalix-brujula`. The existing repository publisher
   then re-signs the complete package set and deploys it to Pages. Publication
   is serialized with full Nodalix repository publication.
4. Machines get the updated native browser via normal `pacman -Syu`.
   Nodalix OS `VERSION`, the kernel and the ISO **do not change**. WebKitGTK
   security patches remain the responsibility of the distro package manager.

The full Nodalix OS `CI` skips **main pushes** that change only the Brújula
PKGBUILD and its component version; it continues to validate all other OS
changes and pull requests. The full-repository `publish-repo.yml` remains
a **manual** workflow for a successful, current main-branch CI candidate and
is no longer triggered just because Brújula changed. This prevents a full
CI candidate from republishing an older browser over an independent release.

### Manual first run (Brújula 0.10.0)

The workflow file must be merged into `main` first. Then open
**Actions → Build and publish Brújula independently → Run workflow → main**.
This creates and validates Brújula 0.10.0 from the pinned source and publishes
the signed package. It does **not** need a `candidate_run` or an ISO build.
It needs the previously established working Pages repository and signing
environment. After the successful deploy, verify:

```fish
sudo pacman -Sy
sudo pacman -Si nodalix-brujula
```

Do not use `pacman -Sy` as an excuse for a partial upgrade; install upgrades
with `sudo pacman -Syu` after reviewing the proposed full transaction.

**Tradeoff:** GitHub Pages replaces the complete site on each deployment. The
independent pipeline therefore downloads and verifies the existing package set
(about 700 MB currently) and re-uploads it intact alongside the new browser.
It avoids building the OS, but not the network bandwidth of Pages publication.
If the published repository is unavailable, unsigned, incomplete or over the
size budget, the deployment fails closed without touching the live site.

## Check or recover a Nodalix computer (fish)

```fish
pacman -Q nodalix-brujula
sudo pacman -Si nodalix-brujula
sudo pacman -Syu
pacman -Q nodalix-brujula
```

Only run the upgrade after trusted keyrings and synchronized databases work.
Errors such as `unknown CachyOS key` / `invalid database (PGP signature)`
must be diagnosed and resolved first; **do not** set `SigLevel = Never`,
delete keyrings or use `--overwrite '*'` as a workaround.

If you have a *separate, older* NXPM AppImage, remove that duplicate from the
Applications library after checking which launcher it uses. Do not delete
Brújula's user profile, history or passwords.

## Release checklist

- [ ] Upstream stable tag points to the reviewed commit and updates the
      package version and component manifest in lockstep
- [ ] Unit tests and `cargo build --locked --release -p brujula` pass
- [ ] Pacman dependency resolution and `nodalix-release` remain intact
- [ ] Signed repository was published with the correct key fingerprint
- [ ] `sudo pacman -Syu` upgrades from previous package and the default
      GNOME browser desktop file still opens the new binary
- [ ] WebKitGTK receives security fixes from the system repositories
