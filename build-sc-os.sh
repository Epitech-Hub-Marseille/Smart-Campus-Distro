#!/usr/bin/env bash
# build-sc-os.sh - build the Smart Campus Debian image for one product.
#
#   ./build-sc-os.sh products          list the products
#   ./build-sc-os.sh debs <product>    build the .deb packages into out/<product>/
#   ./build-sc-os.sh iso <product>     debs + live-build ISO (needs sudo and a Debian host)
#   ./build-sc-os.sh config <product>  debs + live-build tree only, in build/<product>/live
#   ./build-sc-os.sh clean             remove build/ and out/
#
# A product (products/<name>.conf) decides which repository is fetched and run
# with docker compose, and whether the machine boots into a kiosk screen.
# Without a product argument, SC_PRODUCT from sc-os.conf is used.
#
# Inputs (paths can be changed in sc-os.conf):
#   assets/plymouth/sc-boot.script  boot splash script
#   assets/plymouth/logo.svg        logo, rendered to logo.png (needs rsvg-convert)
#   assets/wallpaper.{png,jpg}      optional, kiosk background while the page loads
#   assets/chime.wav                optional, boot chime (the package is skipped without it)
#   assets/faculty-screen.env       optional, ships a ready SERVER_URL / SERVER_PUBLIC_KEY
#
# Packages produced:
#   sc-plymouth-theme  Plymouth theme "sc-boot", set as default
#   sc-boot-chime      plays chime.wav when the first sound card appears
#   sc-update          fetches the product repository and runs it with docker compose
#   sc-os-core         docker, product identity, first-boot provisioning, sc-os-setup
#   sc-kiosk           cage + Chromium on tty1 (products with a screen only)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="${SC_CONF:-$ROOT/sc-os.conf}"

# ---------------------------------------------------------------- defaults ---
OS_NAME="SC OS"
VERSION="0.1.0"
MAINTAINER="Smart Campus <admin@example.com>"
DIST="trixie"
ARCH="amd64"
SC_PRODUCT=""

ASSETS_DIR="$ROOT/assets"
PLYMOUTH_DIR="$ASSETS_DIR/plymouth"
WALLPAPER=""                       # auto-detect assets/wallpaper.{png,jpg,jpeg,webp}
CHIME="$ASSETS_DIR/chime.wav"

KIOSK_USER="kiosk"
CHROMIUM_EXTRA_FLAGS=""
CHIME_DEVICE="default"             # ALSA device, e.g. plughw:0,0 or hdmi:CARD=PCH,DEV=0
CHIME_VOLUME="70%"

REPO_URL=""                        # overrides PRODUCT_REPO_URL (for example an ssh URL)
EXTRA_PACKAGES=""                  # extra Debian packages for the image
INSTALLER="live"                   # live-build --debian-installer: none | live
BOOT_APPEND="quiet splash loglevel=3 rd.udev.log_level=3 vt.global_cursor_default=0"

# shellcheck source=/dev/null
[[ -f "$CONF" ]] && . "$CONF"

PRODUCT=""                         # set by load_product
BUILD=""
OUT=""

log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarn:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# put <path> [mode] - write stdin to path, creating parent dirs
put() { mkdir -p "$(dirname "$1")"; cat >"$1"; chmod "${2:-0644}" "$1"; }

# ---------------------------------------------------------------- products ---
list_products() {
  local file
  for file in "$ROOT"/products/*.conf; do basename "$file" .conf; done
}

# load_product <name> - read products/<name>.conf and set the build paths.
load_product() {
  local name="${1:-$SC_PRODUCT}"
  [[ -n "$name" ]] || die "no product given. Available: $(list_products | tr '\n' ' ')"
  [[ -f "$ROOT/products/$name.conf" ]] || die "unknown product '$name'. Available: $(list_products | tr '\n' ' ')"
  PRODUCT_KIOSK_URL=""
  # shellcheck source=/dev/null
  . "$ROOT/products/$name.conf"
  PRODUCT="$name"
  REPO_URL="${REPO_URL:-$PRODUCT_REPO_URL}"
  BUILD="$ROOT/build/$PRODUCT"
  OUT="$ROOT/out/$PRODUCT"
}

has_screen() { [[ "$PRODUCT_HAS_SCREEN" == yes ]]; }
has_chime()  { [[ -f "$CHIME" ]]; }

# ----------------------------------------------------------------- checks ----
# Sets WALLPAPER to the first wallpaper found, or leaves it empty (it is optional).
find_wallpaper() {
  if [[ -n "$WALLPAPER" ]]; then [[ -f "$WALLPAPER" ]] || die "WALLPAPER not found: $WALLPAPER"; return; fi
  local ext
  for ext in png jpg jpeg webp; do
    [[ -f "$ASSETS_DIR/wallpaper.$ext" ]] && { WALLPAPER="$ASSETS_DIR/wallpaper.$ext"; return; }
  done
  return 0  # no wallpaper is fine: without it the loop's last test would fail under set -e
}

check_inputs() {
  command -v dpkg-deb >/dev/null || die "dpkg-deb not found (apt install dpkg-dev)"
  command -v rsvg-convert >/dev/null || die "rsvg-convert not found (apt install librsvg2-bin)"
  command -v python3 >/dev/null || die "python3 not found"
  [[ -f "$PLYMOUTH_DIR/sc-boot.script" ]] || die "missing $PLYMOUTH_DIR/sc-boot.script"
  [[ -f "$PLYMOUTH_DIR/logo.svg" ]] || die "missing $PLYMOUTH_DIR/logo.svg"
  find_wallpaper
  has_chime || warn "no chime at $CHIME: sc-boot-chime is skipped"
  if has_screen && [[ -z "$WALLPAPER" ]]; then
    warn "no wallpaper: the kiosk shows a plain dark background while the page loads"
  fi
}

# common DEBIAN/control writer: ctl <pkgdir> <name> <depends> <description> [extra-fields]
ctl() {
  local size
  size=$(du -sk --exclude=DEBIAN "$1" | cut -f1)
  put "$1/DEBIAN/control" <<EOF
Package: $2
Version: $VERSION
Architecture: all
Maintainer: $MAINTAINER
Installed-Size: $size
Depends: $3
Section: misc
Priority: optional
${5:+$5
}Description: $4
EOF
}

build_deb() {
  mkdir -p "$OUT"
  local f="$OUT/${1##*/}_${VERSION}_all.deb"
  dpkg-deb --root-owner-group -Zxz --build "$1" "$f" >/dev/null
  log "built ${f#"$ROOT"/}"
}

# ------------------------------------------------------- sc-plymouth-theme ---
# Colours of the progress bars drawn by sc-boot.script: track, boot, update.
BAR_TRACK_COLOR="#2a2a33"
BAR_BOOT_COLOR="#00a86b"
BAR_UPDATE_COLOR="#ff8c00"

pkg_plymouth() {
  local P="$BUILD/pkg/sc-plymouth-theme" T
  T="$P/usr/share/plymouth/themes/sc-boot"
  mkdir -p "$T"
  cp "$PLYMOUTH_DIR/sc-boot.script" "$T/sc-boot.script"
  # Plymouth cannot read SVG, so the logo is rasterised at build time.
  rsvg-convert --width 512 --height 512 "$PLYMOUTH_DIR/logo.svg" --output "$T/logo.png"
  python3 -I "$ROOT/tools/solid-png.py" "$T/bar_bg.png" "$BAR_TRACK_COLOR"
  python3 -I "$ROOT/tools/solid-png.py" "$T/bar_fg.png" "$BAR_BOOT_COLOR"
  python3 -I "$ROOT/tools/solid-png.py" "$T/bar_update.png" "$BAR_UPDATE_COLOR"
  put "$T/sc-boot.plymouth" <<THEME
[Plymouth Theme]
Name=sc-boot
Description=$OS_NAME boot splash
ModuleName=script

[script]
ImageDir=/usr/share/plymouth/themes/sc-boot
ScriptFile=/usr/share/plymouth/themes/sc-boot/sc-boot.script
THEME
  find "$T" -type d -exec chmod 0755 {} +
  find "$T" -type f -exec chmod 0644 {} +

  put "$P/DEBIAN/postinst" 0755 <<'EOF'
#!/bin/sh
set -e
THEME=/usr/share/plymouth/themes/sc-boot/sc-boot.plymouth
if [ "$1" = configure ]; then
  update-alternatives --install /usr/share/plymouth/themes/default.plymouth \
    default.plymouth "$THEME" 200
  update-alternatives --set default.plymouth "$THEME" || true
  mkdir -p /etc/plymouth
  if [ -f /etc/plymouth/plymouthd.conf ] && grep -q '^Theme=' /etc/plymouth/plymouthd.conf; then
    sed -i 's/^Theme=.*/Theme=sc-boot/' /etc/plymouth/plymouthd.conf
  else
    printf '[Daemon]\nTheme=sc-boot\nShowDelay=0\nDeviceTimeout=8\n' > /etc/plymouth/plymouthd.conf
  fi
  if command -v update-initramfs >/dev/null 2>&1 && ls /boot/initrd.img-* >/dev/null 2>&1; then
    update-initramfs -u -k all || true
  fi
fi
exit 0
EOF
  put "$P/DEBIAN/postrm" 0755 <<'EOF'
#!/bin/sh
set -e
if [ "$1" = remove ] || [ "$1" = purge ]; then
  update-alternatives --remove default.plymouth \
    /usr/share/plymouth/themes/sc-boot/sc-boot.plymouth 2>/dev/null || true
  [ -f /etc/plymouth/plymouthd.conf ] && sed -i '/^Theme=sc-boot$/d' /etc/plymouth/plymouthd.conf || true
fi
exit 0
EOF
  ctl "$P" sc-plymouth-theme "plymouth, plymouth-label, initramfs-tools" \
    "$OS_NAME boot splash (Plymouth theme sc-boot)"
  build_deb "$P"
}

# ----------------------------------------------------------- sc-boot-chime ---
pkg_chime() {
  local P="$BUILD/pkg/sc-boot-chime"
  install -Dm0644 "$CHIME" "$P/usr/share/sc-boot-chime/chime.wav"

  put "$P/etc/default/sc-boot-chime" <<EOF
# Boot chime settings
ENABLED=yes
# ALSA device (aplay -L lists them). Early in boot nothing like PipeWire is
# running yet, so this talks to the hardware directly.
DEVICE="$CHIME_DEVICE"
# Mixer volume applied to Master/PCM/Speaker/Headphone before playing ("" = leave)
VOLUME="$CHIME_VOLUME"
EOF
  echo /etc/default/sc-boot-chime | put "$P/DEBIAN/conffiles"

  put "$P/usr/libexec/sc-boot-chime/play" 0755 <<'EOF'
#!/bin/sh
# Play the boot chime once. Started by udev when the first sound card appears.
ENABLED=yes DEVICE=default VOLUME=70%
[ -r /etc/default/sc-boot-chime ] && . /etc/default/sc-boot-chime
[ "$ENABLED" = yes ] || exit 0
for kv in $(cat /proc/cmdline); do [ "$kv" = sc.nochime ] && exit 0; done

if [ -n "$VOLUME" ]; then
  for ctl in Master PCM Speaker Headphone; do
    amixer -q sset "$ctl" "$VOLUME" unmute >/dev/null 2>&1 || true
  done
fi
exec aplay -q -D "$DEVICE" /usr/share/sc-boot-chime/chime.wav
EOF

  # Udev pulls the service in the moment card0 exists — the earliest point
  # the root fs can play audio. RemainAfterExit makes it once per boot.
  put "$P/usr/lib/udev/rules.d/90-sc-boot-chime.rules" <<'EOF'
ACTION=="add", SUBSYSTEM=="sound", KERNEL=="card0", TAG+="systemd", ENV{SYSTEMD_WANTS}+="sc-boot-chime.service"
EOF
  put "$P/usr/lib/systemd/system/sc-boot-chime.service" <<'EOF'
[Unit]
Description=Boot chime
DefaultDependencies=no
After=local-fs.target alsa-restore.service
Conflicts=shutdown.target
Before=shutdown.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/libexec/sc-boot-chime/play
TimeoutStartSec=15
EOF
  ctl "$P" sc-boot-chime "alsa-utils, udev" "$OS_NAME boot chime"
  build_deb "$P"
}

# ---------------------------------------------------------------- sc-update ---
# The updater package comes from packages/sc-update; only its config differs per product.
write_update_config() {
  local product_override="$ROOT/products/$PRODUCT.override.yml"
  {
    cat <<YAML
# sc-update configuration for the product "$PRODUCT" (written by build-sc-os.sh)
auto-update: true
conditional-update-autoreject-seconds: 15
repository-url: $REPO_URL
compose-env-file: /etc/sc-os/$PRODUCT.env
required-files:
  - /etc/sc-os/$PRODUCT.env
YAML
    if [[ -f "$product_override" ]]; then
      printf 'compose-overrides:\n  - /usr/lib/sc-os/%s.override.yml\n' "$PRODUCT"
    fi
  } >"$1"
}

pkg_update() {
  local P="$BUILD/pkg/sc-update"
  cp -a "$ROOT/packages/sc-update/pkg" "$P"
  write_update_config "$P/etc/sc-update/config.yaml"
  sed -i "s/^Version: .*/Version: $VERSION/" "$P/DEBIAN/control"
  find "$P" -type d -exec chmod 0755 {} +
  chmod 0755 "$P"/DEBIAN/{postinst,prerm,postrm} "$P/bin/sc-update/sc-update"
  chmod 0644 "$P"/DEBIAN/{control,conffiles} "$P/etc/sc-update/config.yaml" \
    "$P/lib/systemd/system/sc-update.service"
  build_deb "$P"
}

# ------------------------------------------------------------- sc-os-core ---
pkg_core() {
  local P="$BUILD/pkg/sc-os-core" product_override="$ROOT/products/$PRODUCT.override.yml"
  cp -a "$ROOT/packages/sc-os-core/pkg" "$P"
  echo "PRODUCT=$PRODUCT" | put "$P/etc/sc-os/product"
  if [[ -f "$product_override" ]]; then
    install -Dm0644 "$product_override" "$P/usr/lib/sc-os/$PRODUCT.override.yml"
  fi
  if [[ "$PRODUCT" == faculty-screen && -f "$ASSETS_DIR/faculty-screen.env" ]]; then
    install -Dm0640 "$ASSETS_DIR/faculty-screen.env" "$P/etc/sc-os/faculty-screen.env"
  fi
  find "$P" -type d -exec chmod 0755 {} +
  chmod 0755 "$P/DEBIAN/postinst" "$P"/usr/sbin/* "$P/usr/libexec/sc-os/provision"
  ctl "$P" sc-os-core "docker.io, docker-compose, openssl, python3, curl, sc-update (= $VERSION)" \
    "$OS_NAME core for the $PRODUCT_TITLE (docker, provisioning, setup)"
  build_deb "$P"
}

# ---------------------------------------------------------------- sc-kiosk ---
pkg_kiosk() {
  local P="$BUILD/pkg/sc-kiosk" WP_NAME=""
  if [[ -n "$WALLPAPER" ]]; then
    WP_NAME="default.${WALLPAPER##*.}"
    install -Dm0644 "$WALLPAPER" "$P/usr/share/backgrounds/sc/$WP_NAME"
  fi

  put "$P/etc/sc-kiosk/kiosk.conf" <<EOF
# Kiosk session settings (sourced by /usr/libexec/sc-kiosk/session)
URL="$PRODUCT_KIOSK_URL"
WALLPAPER="${WP_NAME:+/usr/share/backgrounds/sc/$WP_NAME}"
CHROMIUM_FLAGS="$CHROMIUM_EXTRA_FLAGS"
EOF
  echo /etc/sc-kiosk/kiosk.conf | put "$P/DEBIAN/conffiles"

  # Loading page: wallpaper fills the screen until the app answers, then
  # Chromium navigates to it. Avoids a white flash / error page at boot.
  put "$P/usr/share/sc-kiosk/splash.html" <<'EOF'
<!doctype html>
<html><head><meta charset="utf-8"><title>Starting…</title>
<style>
  html,body{margin:0;height:100%;background:#05080f center/cover no-repeat;cursor:none;overflow:hidden}
  .dot{position:fixed;left:50%;bottom:9vh;width:10px;height:10px;margin-left:-5px;border-radius:50%;
       background:#fff;opacity:.6;animation:p 1.4s ease-in-out infinite}
  @keyframes p{50%{opacity:.15;transform:scale(.6)}}
</style></head>
<body><div class="dot"></div>
<script>
  const q = new URLSearchParams(location.search);
  const target = q.get("url") || "http://127.0.0.1:3000/";
  if (q.get("wp")) document.body.style.backgroundImage = `url("file://${q.get("wp")}")`;
  async function poll() {
    try { await fetch(target, { mode: "no-cors", cache: "no-store" }); location.replace(target); }
    catch { setTimeout(poll, 500); }
  }
  poll();
</script></body></html>
EOF

  put "$P/usr/libexec/sc-kiosk/session" 0755 <<'EOF'
#!/bin/sh
# Kiosk session: cage (single-app Wayland compositor) running Chromium.
URL=http://127.0.0.1:3000/ WALLPAPER= CHROMIUM_FLAGS=
[ -r /etc/sc-kiosk/kiosk.conf ] && . /etc/sc-kiosk/kiosk.conf

PROFILE="$HOME/.config/chromium"
# Never show "Chromium didn't shut down correctly".
if [ -f "$PROFILE/Default/Preferences" ]; then
  sed -i 's/"exit_type":"[^"]*"/"exit_type":"Normal"/; s/"exited_cleanly":false/"exited_cleanly":true/' \
    "$PROFILE/Default/Preferences"
fi

enc() { printf '%s' "$1" | sed 's/%/%25/g; s/&/%26/g; s/?/%3F/g; s/#/%23/g; s/ /%20/g; s/=/%3D/g'; }
START="file:///usr/share/sc-kiosk/splash.html?url=$(enc "$URL")&wp=$(enc "$WALLPAPER")"

# shellcheck disable=SC2086
exec cage -d -s -- chromium \
  --ozone-platform=wayland \
  --kiosk --start-fullscreen \
  --noerrdialogs --disable-infobars --no-first-run --no-default-browser-check \
  --disable-session-crashed-bubble --disable-features=Translate,MediaRouter \
  --password-store=basic --check-for-update-interval=31536000 \
  --autoplay-policy=no-user-gesture-required \
  --allow-file-access-from-files \
  --overscroll-history-navigation=0 --disable-pinch \
  $CHROMIUM_FLAGS \
  "$START"
EOF

  # Runs on tty1 in a real logind session (PAMName) so cage gets DRM/input.
  # Plymouth is told to quit keeping the last frame, so the splash hands over
  # straight to the wallpaper page.
  put "$P/usr/lib/systemd/system/sc-kiosk.service" <<EOF
[Unit]
Description=Kiosk session (cage + Chromium)
After=systemd-user-sessions.service plymouth-start.service sc-update.service systemd-logind.service
Conflicts=getty@tty1.service plymouth-quit.service
OnFailure=plymouth-quit.service

[Service]
User=$KIOSK_USER
PAMName=login
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=yes
StandardInput=tty-fail
StandardOutput=journal
StandardError=journal
UtmpIdentifier=tty1
UtmpMode=user
Environment=XDG_SESSION_TYPE=wayland
ExecStartPre=-+/usr/bin/plymouth quit --retain-splash
ExecStart=/usr/libexec/sc-kiosk/session
Restart=always
RestartSec=2

[Install]
WantedBy=graphical.target
Alias=display-manager.service
EOF

  put "$P/DEBIAN/postinst" 0755 <<EOF
#!/bin/sh
set -e
if [ "\$1" = configure ]; then
  if ! getent passwd $KIOSK_USER >/dev/null; then
    useradd --system --create-home --home-dir /var/lib/sc-kiosk \\
      --shell /usr/sbin/nologin --comment "Kiosk session" $KIOSK_USER
  fi
  for g in video render input audio; do
    getent group \$g >/dev/null && usermod -aG \$g $KIOSK_USER || true
  done
  systemctl set-default graphical.target >/dev/null 2>&1 || true
  systemctl enable sc-kiosk.service >/dev/null 2>&1 || true
fi
exit 0
EOF
  put "$P/DEBIAN/prerm" 0755 <<'EOF'
#!/bin/sh
set -e
if [ "$1" = remove ]; then
  systemctl disable sc-kiosk.service >/dev/null 2>&1 || true
fi
exit 0
EOF
  ctl "$P" sc-kiosk "cage, chromium, libpam-systemd, passwd" \
    "$OS_NAME kiosk session (cage + Chromium on tty1)" \
    "Recommends: fonts-dejavu-core, libgl1-mesa-dri"
  build_deb "$P"
}

# ----------------------------------------------------------------- debs -----
cmd_debs() {
  check_inputs
  rm -rf "$BUILD/pkg" "$OUT"
  mkdir -p "$BUILD/pkg" "$OUT"
  pkg_plymouth
  if has_chime; then pkg_chime; fi
  pkg_update
  pkg_core
  if has_screen; then pkg_kiosk; fi
}

# --------------------------------------------------------------- live-build ---
# Debian packages installed in the image, one per line.
image_packages() {
  cat <<EOF
live-boot
live-config
live-config-systemd
systemd-sysv
systemd-timesyncd
dbus
libpam-systemd
systemd-resolved
ca-certificates
git
openssh-client
python3
python3-yaml
plymouth
plymouth-label
alsa-utils
firmware-linux
firmware-sof-signed
sc-plymouth-theme
sc-update
sc-os-core
EOF
  if has_chime; then echo sc-boot-chime; fi
  if has_screen; then
    printf '%s\n' cage chromium fonts-dejavu-core libgl1-mesa-dri libegl-mesa0 sc-kiosk
  fi
  tr ' ' '\n' <<<"$PRODUCT_PACKAGES $EXTRA_PACKAGES"
}

write_chroot_hook() {
  put "$1" 0755 <<'EOF'
#!/bin/sh
set -e
# Branding on top of Debian's os-release (keeps Debian's file intact as a base).
if [ -f /etc/os-release.sc ]; then
  { cat /etc/os-release.sc; grep -vE '^(NAME|VERSION|ID|ID_LIKE|PRETTY_NAME)=' /usr/lib/os-release; } > /etc/os-release.new
  rm -f /etc/os-release; mv /etc/os-release.new /etc/os-release; rm /etc/os-release.sc
fi
systemctl enable systemd-networkd.service systemd-resolved.service systemd-timesyncd.service
systemctl enable docker.service sc-os-provision.service sc-update.service
EOF
  if has_screen; then
    cat >>"$1" <<'EOF'
systemctl enable sc-kiosk.service
systemctl set-default graphical.target
# No console on tty1 behind the kiosk; keep tty2+ for maintenance (Ctrl+Alt+F2).
systemctl mask getty@tty1.service
EOF
  fi
  cat >>"$1" <<'EOF'
# Make sure the initrd carries the sc-boot theme.
update-initramfs -u -k all || true
EOF
}

write_live_config() {
  local L="$BUILD/live" hostname="sc-$PRODUCT"
  # config/ is fully generated here: drop leftovers of earlier runs and options.
  rm -rf "$L/config"
  mkdir -p "$L/config/packages.chroot"
  cp "$OUT"/sc-*_"${VERSION}"_all.deb "$L/config/packages.chroot/"

  image_packages | put "$L/config/package-lists/sc-os.list.chroot"

  # live-build's own security entry breaks on some versions: they ask for the
  # pre-bullseye suite "<dist>/updates", which does not exist for trixie
  # ("does not have a Release file"). It is switched off in lbconfig.sh and the
  # real suite is shipped as an apt source of the installed system instead, so
  # machines get security updates at their first apt upgrade. The build itself
  # does not use it: an extra live-build archive made it call gpg, which the
  # minimal chroot does not have.
  put "$L/config/includes.chroot/etc/apt/sources.list.d/security.sources" <<SOURCES
Types: deb
URIs: http://security.debian.org/debian-security
Suites: $DIST-security
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp
SOURCES

  put "$L/config/includes.chroot/etc/hostname" <<<"$hostname"
  put "$L/config/includes.chroot/etc/systemd/network/80-wired-dhcp.network" <<'EOF'
[Match]
Type=ether
Name=en* eth*

[Network]
DHCP=yes
EOF
  put "$L/config/includes.chroot/etc/os-release.sc" <<EOF
NAME="$OS_NAME"
VERSION="$VERSION"
ID=sc-os
ID_LIKE=debian
PRETTY_NAME="$OS_NAME $PRODUCT_TITLE $VERSION ($DIST)"
EOF
  write_chroot_hook "$L/config/hooks/live/0100-sc-os.hook.chroot"

  cat >"$L/lbconfig.sh" <<EOF
#!/bin/sh
set -e
lb config noauto \\
  --mode debian \\
  --distribution "$DIST" \\
  --architectures "$ARCH" \\
  --archive-areas "main contrib non-free non-free-firmware" \\
  --binary-images iso-hybrid \\
  --debian-installer "$INSTALLER" \\
  --apt-recommends false \\
  --security false \\
  --iso-application "$OS_NAME $PRODUCT_TITLE" \\
  --iso-volume "$(tr 'a-z -' 'A-Z__' <<<"SC-$PRODUCT")" \\
  --iso-publisher "$MAINTAINER" \\
  --bootappend-live "boot=live components noautologin hostname=$hostname $BOOT_APPEND" \\
  --memtest none
EOF
  chmod 0755 "$L/lbconfig.sh"
}

# live-build 3.x (2014) cannot build trixie: it asks for the "trixie/updates"
# suite, lacks options used here and fails inside the chroot. Debian 13 ships
# 20250505, so any date-style version from 2023 on is accepted.
MIN_LIVE_BUILD_VERSION=20230000

check_live_build_version() {
  local version
  version="$(lb --version 2>/dev/null | head -1)"
  [[ "$version" =~ ^[0-9]{8} && "${version:0:8}" -ge "$MIN_LIVE_BUILD_VERSION" ]] ||
    die "live-build '$version' is too old for $DIST. Install the Debian 13 version (20250505 or newer), see README"
}

cmd_iso() {
  command -v lb >/dev/null || die "live-build not found (Debian host: apt install live-build)"
  check_live_build_version
  cmd_debs
  write_live_config
  local SUDO=""; [[ $EUID -eq 0 ]] || SUDO="sudo"
  log "running live-build in build/$PRODUCT/live (this takes a while)"
  (
    cd "$BUILD/live"
    $SUDO lb clean --purge >/dev/null 2>&1 || true
    $SUDO ./lbconfig.sh
    $SUDO lb build
  )
  local iso name
  iso=$(ls -t "$BUILD"/live/*.iso 2>/dev/null | head -1) || true
  [[ -n "$iso" ]] || die "live-build finished without an ISO; see build/$PRODUCT/live/build.log"
  name="$(tr ' A-Z' '-a-z' <<<"$OS_NAME")-$PRODUCT-$VERSION-$ARCH.iso"
  $SUDO cp "$iso" "$OUT/$name"
  $SUDO chown "$(id -u):$(id -g)" "$OUT/$name"
  log "ISO ready: out/$PRODUCT/$name"
}

cmd_clean() {
  local SUDO="" live
  [[ $EUID -eq 0 ]] || SUDO="sudo"
  for live in "$ROOT"/build/*/live; do
    [[ -d "$live" ]] && (cd "$live" && $SUDO lb clean --purge >/dev/null 2>&1 || true)
  done
  $SUDO rm -rf "$ROOT/build" "$ROOT/out"
  log "cleaned"
}

usage() {
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}

case "${1:-}" in
  products) list_products ;;
  debs)     load_product "${2:-}"; cmd_debs ;;
  iso)      load_product "${2:-}"; cmd_iso ;;
  config)   load_product "${2:-}"; cmd_debs; write_live_config; log "live-build tree in build/$PRODUCT/live" ;;
  clean)    cmd_clean ;;
  *)        usage ;;
esac
