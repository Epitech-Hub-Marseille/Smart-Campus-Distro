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
```

Settings live in `sc-os.conf` (bash syntax, not
committed). Useful keys: `VERSION`, `REPO_URL` (for example an ssh URL for a
private repository), `EXTRA_PACKAGES`, `INSTALLER` (`live` installs to disk,
`none` is a live-only ISO).

Assets: `assets/plymouth/` (boot script and logo). Optional: `assets/wallpaper.png`,
`assets/chime.wav`, and `assets/faculty-screen.env` to ship a ready server address
and key to every screen.

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
server. Run `sudo sc-os-setup` on the machine (Ctrl+Alt+F2 on a kiosk), enter the
server address, and confirm the fingerprint against the console. The updater is
waiting for `/etc/sc-os/faculty-screen.env` and starts as soon as it exists. The
screen then shows its own fingerprint to approve in the console.

After editing a settings file, run `sudo sc-os-apply`.

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
