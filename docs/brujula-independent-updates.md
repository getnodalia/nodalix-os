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

## Version flow

1. The scheduled `sync-brujula.yml` checks the latest **stable** GitHub
   release of `getnodalia/brujula`. It resolves the tag to an immutable
   commit (including annotated tags) and changes only the browser PKGBUILD
   and `release/components.json` if the version increases.
2. The job proposes a PR and dispatches the existing CI on the PR branch.
   Review is still required; automation must not turn unreviewed upstream
   code into a privileged signed system package. On repositories that prevent
   Actions-created PRs, enable that permission or use the manual path below.
3. Once merged, successful **main** CI produces a complete package set. The
   `publish-repo.yml` workflow detects that the main commit changed the
   Brújula package, checks the candidate's repository, SHA, branch and
   successful status, and publishes the whole signed `[nodalix]` pacman
   repository through the protected `nodalix-repo-signing` environment.
   This requires the existing signing key/environment and GitHub Pages to be
   correctly configured. Do not disable repository signatures to work around
   missing credentials or PGP errors.
4. Machines then receive the updated `nodalix-brujula` through the usual
   **full system upgrade**, with no new Nodalix ISO, VERSION bump or release
   tag needed. The next Nodalix OS release continues to include the current
   browser version in its component manifest.

The manual `Publish pacman repository` workflow remains available if automatic
publication is blocked, with the id of a successful **main push** CI run.

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
