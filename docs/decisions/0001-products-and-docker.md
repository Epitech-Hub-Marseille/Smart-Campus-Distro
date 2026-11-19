# 0001 Products, repositories fetched at runtime, docker

## Context
Smart Campus has several products (central server, faculty screen, door unit)
that live in separate repositories and release on their own. The machines must
install the right one and stay up to date without rebuilding the OS image.

## Decision
- One ISO per product, chosen at build time (`products/<name>.conf`). The product
  is written to `/etc/sc-os/product`.
- The image carries no application code. `sc-update` clones the product
  repository on first boot and follows the latest tag of `main`, then runs the
  repository's own docker compose file. Releasing a product is pushing a tag.
- Per-machine data stays outside the checkout (`/etc/sc-os`, `/var/lib/sc-os`),
  so `git checkout --force` during an update cannot remove it.
- The checkout is `/opt/smart-campus`. The original `/bin/smart-campus` is a
  symlink into `/usr/bin` on Debian and is not a place for mutable data.
- A repository without tags is followed by commit id, so it installs at all.
  Cost: every push to `main` of such a repository is deployed.
- The central server key is a compose secret overridden to
  `/var/lib/sc-os/server-key.pem` (`products/central-server.override.yml`),
  owned by uid 1000 because the container runs as `node`. The key is never
  regenerated: losing it means re-provisioning every device.
- The faculty screen waits for `sc-os-setup` (`required-files` in the updater
  config). The server key is trusted only after the operator compares its
  fingerprint, as the agent's own documentation requires.

## Alternatives rejected
- One universal ISO choosing the product at boot: the kiosk packages would be on
  the server too, and the choice would need an interactive first boot.
- Baking the compose files into the image: every release would need a new ISO.
- Pulling prebuilt registry images: the repositories build from source and
  publish none.

## Trade-offs
- First boot needs network and builds images on the machine (slow, can fail
  offline). A failed update restores the previous revision.
- The kiosk starts after `sc-update` finishes, so Plymouth can show the update
  progress. A very slow first build keeps the screen on the splash.
- A repository on GitHub that is private needs a deploy key on each machine.
