# Contributing to Smart Campus Distro

Thank you for helping. This repository builds the Debian images (one ISO per product) that run Smart Campus machines:
the central server and the Faculty screen. On first boot a machine clones its product repository and runs it with docker
compose; on later boots it checks for a new release and updates.

## Before you start

- Open or pick an issue first for anything larger than a typo. Past decisions are recorded in `docs/decisions/`; add one
  when you make a choice others will wonder about.
- Images update deployed machines, so a mistake here can reach many of them. Keep changes small and reversible.

## Set up

Build on a Debian 13 host (`apt install live-build dpkg-dev librsvg2-bin python3`; live-build 20250505 or newer, see the README).

```bash
./build-sc-os.sh products                # list products
./build-sc-os.sh debs faculty-screen     # only the packages
./build-sc-os.sh iso central-server      # full ISO in out/central-server/
```

Local settings live in `sc-os.conf` and are not committed.

## Check your work

- The Python tests in `tests/` pass: `python3 -m unittest discover tests` (or `pytest tests`).
- Build the packages for the product you changed. For anything that changes boot, provisioning or the updater, boot the
  ISO in a VM and say what you tested and what you could not (real hardware, a deployed machine).
- Shell: quote variables, use `set -eu`, and keep scripts idempotent, because they run again on every boot.
- Never put keys, tokens or passwords in an image, a script or a package. The gateway key and the settings file are
  created on the machine at first boot.

Allowed commit scopes: `build`, `products`, `updater`, `provision`, `tests`, `docs`, `deps`.

## Commits and pull requests

- Branch from `main`: `<type>/<short-kebab-description>`, for example `feat/live-announcement`. Never push to `main` directly.
- [Conventional Commits](https://www.conventionalcommits.org/) for every commit and PR title: `<type>(<scope>): <subject>`. Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`. Subject in the imperative, lowercase start, no trailing period, 72 characters at most.
- One logical change per commit. Do not mix a refactor with a behaviour change.
- Explain *why* in the body when it is not obvious. Link issues with `Closes #12` or `Refs #7`.
- A PR says what changed and why, how you verified it, and what you could not verify (sound, real hardware, a browser). Keep it small enough to review.
- `main` is protected: a PR needs one approving review.

## Security

Never commit secrets: `.env` files, private keys, certificates, tokens. Only `.env.example` is tracked. Never log or return passwords, hashes, session tokens or key material. To report a vulnerability, do not open a public issue: use the repository's **Security** tab (private vulnerability reporting) or contact a maintainer privately.

## Licence of your contribution

This project is released under the [PolyForm Noncommercial License 1.0.0](LICENSE). By opening a pull request you agree that your contribution is licensed under the same terms.

## Conduct

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

