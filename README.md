# SmartCampus-Distro

Debian image builder for Smart Campus machines. One ISO per product. On first
boot the machine clones the product repository from GitHub and runs it with
docker compose; on every later boot it checks for a new release and updates.

| Product | Repository | Boots into |
| --- | --- | --- |
| `central-server` | SmartCampus-CentralServer | headless, console on port 3000 |
| `faculty-screen` | SmartCampus-FacultyScreens | cage + Chromium kiosk on tty1 |

The door unit is an Android app, so it has no image here.

## Build

On a Debian 13 host: `apt install live-build dpkg-dev librsvg2-bin python3`.

live-build must be 20250505 or newer (`lb --version`). Ubuntu and older Debian ship
versions that cannot build trixie (Ubuntu's 3.0~a57 is from 2014). On those, install
the Debian 13 package:

```sh
sudo apt install debootstrap debian-archive-keyring gnupg
curl -LO https://deb.debian.org/debian/pool/main/l/live-build/live-build_20250505+deb13u1_all.deb
sudo apt install ./live-build_20250505+deb13u1_all.deb
```


```sh
./build-sc-os.sh products
./build-sc-os.sh debs faculty-screen    # only the packages, in out/faculty-screen/
./build-sc-os.sh iso central-server     # ISO in out/central-server/
./build-sc-os.sh update-iso faculty-screen   # small ISO to update a machine already deployed
```

Settings live in `sc-os.conf` (bash syntax, not
committed). Useful keys: `VERSION`, `REPO_URL` (for example an ssh URL for a
private repository), `EXTRA_PACKAGES`, `INSTALLER` (`live` installs to disk,
`none` is a live-only ISO).

Assets: `assets/plymouth/` (boot script and logo). Optional: `assets/wallpaper.png`,
`assets/chime.wav`, and `assets/faculty-screen.env` to ship a ready server address
and key to every screen.

`update-iso` bundles the packages with an `install.sh`. Mount it on the machine
(`sudo mount -o ro /dev/sr0 /mnt`), run `sudo sh /mnt/install.sh` and reboot. The
updater only follows the product repository, so OS-level fixes reach a deployed
machine this way. Each commit has a new version, so a build is always newer than the last. The same ISOs are attached to every GitHub release.

## Install and first boot

Install the ISO to disk. The central server stores its database in a docker
volume, so a live-only boot loses it at every reboot.

1. `sc-os-provision` runs before the updater. For the central server it creates
   the gateway key in `/var/lib/sc-os/server-key.pem` and the settings file
   `/etc/sc-os/central-server.env` with a random first admin password.
2. `sc-update` clones the repository to `/opt/smart-campus`, checks out the latest
   tag of `main` (the latest commit when the repository has no tags), then runs
   `docker compose up -d --build` with `restart: always`.
3. The central server is ready on `http://<hostname>:3000`. Read the admin login in
   `/etc/sc-os/central-server.env` (root only).

A faculty screen cannot start alone: it needs the address and public key of a
server. When `/etc/sc-os/faculty-screen.env` is missing, `sc-os-setup.service`
asks on tty1 at boot, before the updater and the kiosk start. Enter the server
address and confirm the fingerprint against the console. A wrong answer or an
unreachable server asks again. The updater then runs and the kiosk starts, and
the screen shows its own fingerprint to approve in the console.

To configure a screen again without a shell, edit the boot entry and add
`sc.setup` to the kernel command line. With a shell, run `sudo sc-os-setup`.

Maintenance shell: the kiosk owns tty1. If Ctrl+Alt+F3 does not switch to a
console (some hypervisors and remote consoles grab that combination), edit the
boot entry and add `systemd.unit=multi-user.target`. The kiosk does not start,
and Ctrl+Alt+F2 then gives a login prompt.

After editing a settings file, run `sudo sc-os-apply`.

## Updates

`sc-update` keeps two things current and shows the progress on the Plymouth
splash (orange bar, percentage and a line per stage):

- **The product**: the latest tag (or commit, if untagged) of the product
  repository, rebuilt and started with docker compose.
- **The OS packages**: the latest release tag of this repository, built on the
  machine with `build-sc-os.sh` and installed with apt. A failure of one update
  does not stop the other.

Both run at boot, before the kiosk. `sc-update --check` only looks, and a timer runs
it every 6 hours. Read the result with `cat /var/lib/sc-update/status.json`, or
`sudo sc-update --check` to see it in the journal. `os-update: false` in
`/etc/sc-update/config.yaml` stops a machine following this repository. Read the
risks in [docs/decisions/0002-os-updates-and-versioning.md](docs/decisions/0002-os-updates-and-versioning.md).

### Versions

Every commit pushed to `main` gets a release `v<major>.<minor>.<patch>` from
`.github/workflows/release.yml`, with the update ISO of each product attached
(plus `SHA256SUMS`). The workflow runs the tests and builds the ISOs first, and the tag
is only created with the release, so a failed build leaves nothing behind. `<major>.<minor>` is the `VERSION` file; `<patch>` is the
number of commits since that file last changed. Local builds use the same rule, so
`./build-sc-os.sh` on a commit gives the version its release will have (set
`VERSION` in `sc-os.conf` or `SC_VERSION` to override). To start a new minor version, edit
`VERSION` (for example `0.2`): the next commit is `v0.2.0`. A product repository can
use the same workflow by copying `.github/workflows/release.yml`, `tools/next_version.py`
and a `VERSION` file.

## Private repositories

Use an ssh URL (`REPO_URL` at build time, or `repository-url` in
`/etc/sc-update/config.yaml`) and put a read-only deploy key in
`/etc/sc-os/deploy-key` with mode 0600.

## Known limits

- Default login of the live image is `user` / `live`. Change it after installing.
- The first boot needs network and several minutes to pull and build images.
- Not tested end to end: no Debian host with live-build was available when this was
  written. `debs` and `config` builds and the updater tests were run.
- The updater tests: `python3 -m unittest discover -s tests`.

Why it is built this way: [docs/decisions/0001-products-and-docker.md](docs/decisions/0001-products-and-docker.md).

## License

Released under the [PolyForm Noncommercial License 1.0.0](LICENSE). You may use, modify and share the
software for any noncommercial purpose; commercial use, including selling it, is not permitted.
This is a source-available license, not an open-source one.
