# 0002 OS updates from the distro repository, tags per commit, Plymouth progress

## Context
Fixes to the OS packages (sc-os-core, sc-update, sc-kiosk, sc-plymouth-theme)
could only reach a deployed machine through a USB stick, because sc-update only
followed the product repository. Machines also showed nothing while an update
ran.

## Decision
- Every commit on main of this repository gets a release `v<major>.<minor>.<patch>`
  (`.github/workflows/release.yml`, `tools/next_version.py`) with the update ISO of
  each product attached. The tag is created by the release, after the tests and
  the ISO builds passed, so a failed build leaves no tag. One release per commit
  is noisy, and is accepted so that every version has its ISO. `<major>.<minor>` is the
  `VERSION` file, `<patch>` the number of commits since that file last changed.
  Counting commits, not tags, gives one number per commit even when several are
  pushed together, and bumping `VERSION` restarts at 0. Tests run before tagging.
- sc-update clones this repository to `/var/lib/sc-update/distro`, takes the latest
  release tag, and if it is newer (dpkg comparison, never a downgrade) builds the
  packages of the machine's product with `build-sc-os.sh` (version passed in
  `SC_VERSION`) and installs them with apt. Building on the machine keeps the
  update path equal to the image build path, with no package archive to host.
- The OS update runs before the product update, and a failure of one does not
  stop the other. The exit code is 1 if either failed.
- `sc-update --check` (every 6 hours, `sc-update-check.timer`) only looks and
  writes `/var/lib/sc-update/status.json`, so the machine knows when updates wait.
  Updates are applied at boot, before the kiosk starts.
- Progress goes to Plymouth with the commands the boot theme already listens to:
  update mode (orange bar), a percentage, `[ INFO ]` lines when a stage starts and
  `[  OK  ]` lines when it ends. The percentage is a weighted estimate: stages have
  fixed weights, and inside a stage the share of finished BuildKit steps, image
  pulls, built packages or apt "Setting up" lines is used. The total number of
  docker steps is unknown in advance, so that part is approximate and held below
  100% until the stage ends.

## Alternatives rejected
- An apt repository of prebuilt packages: needs hosting and package signing, which
  do not exist yet. It would be the better long-term answer.
- Tagging by hand or by tag count: a tag per push skips numbers when several
  commits are pushed together.
- Following main directly: a half-finished commit would reach every machine. Tags
  are made only after the tests pass.

## Trade-offs and risks
- Whoever can push to main of the distro repository gets root on every machine
  that follows it. Protect the branch (reviews, no force pushes). Tags are not
  signed yet, so a stolen GitHub account is enough. `os-update: false` in
  `/etc/sc-update/config.yaml` turns it off per machine.
- The machine needs network, `librsvg2-bin` and build time (a minute or two).
- No rollback of OS packages: a failed build leaves the installed ones alone, a
  failed install is left to dpkg, and the next boot tries again.
- A new boot splash or GRUB setting only applies after a reboot. Nothing reboots
  by itself, to avoid a reboot loop on a failing update.
- Machines installed before this change have no `os-repository-url`; they get it
  once from an update ISO (`build-sc-os.sh update-iso`).
