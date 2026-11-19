# sc-update

Smart Campus updater, packaged as a Debian package.

- `pkg/bin/sc-update/sc-update`: the Python updater (installs to /bin/sc-update/ (a path kept from the original layout))
- `pkg/lib/systemd/system/sc-update.service`: systemd unit (runs at boot, before plymouth-quit)
- `pkg/etc/sc-update/config.yaml`: default config (auto-update, conditional-update-autoreject-seconds)
- `pkg/DEBIAN/`: package control file and maintainer scripts

Build: `./build.sh` (needs dpkg-deb), then `sudo apt install ./sc-update_<version>_all.deb`.
Logs: `journalctl -u sc-update`.
