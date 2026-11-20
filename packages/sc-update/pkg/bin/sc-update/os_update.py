"""Updates the Smart Campus OS packages (sc-os-core, sc-update, sc-kiosk, ...).

The packages come from the distro repository (this project), not from an apt
archive: the machine clones it, takes the latest release tag (vX.Y.Z, created for
every commit on main by .github/workflows/tag.yml), builds the packages with
build-sc-os.sh and installs them with apt.

Security: whoever can push to main of that repository can run code as root on every
machine that follows it. Keep the repository protected, and set os-update to false
in /etc/sc-update/config.yaml on machines that must not follow it.
"""
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

from gitrepo import STATE_DIR, clone, git, latest_version
from process import UpdateFailed, run_streamed

log = logging.getLogger("sc-update")

OS_REPO_DIR = STATE_DIR / "distro"
PRODUCT_FILE = Path("/etc/sc-os/product")
CORE_PACKAGE = "sc-os-core"
# Release tags made by the pipeline: v0.1.7. The leading v is not part of the package version.
RELEASE_TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")
# The machine's own build settings must not leak into a build made for an update.
NO_LOCAL_CONFIG = "/nonexistent/sc-os.conf"


def read_product() -> str:
    """The product this machine runs ("faculty-screen", ...), from /etc/sc-os/product."""
    try:
        for line in PRODUCT_FILE.read_text().splitlines():
            if line.startswith("PRODUCT="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError as exc:
        raise UpdateFailed(f"cannot read {PRODUCT_FILE}: {exc}")
    raise UpdateFailed(f"no PRODUCT= line in {PRODUCT_FILE}")


def installed_version() -> str:
    """Version of the installed sc-os-core package, or "" when it is not installed."""
    res = subprocess.run(["dpkg-query", "-W", "-f=${Version}", CORE_PACKAGE],
                         capture_output=True, text=True)
    return res.stdout.strip() if res.returncode == 0 else ""


def is_newer(candidate: str, installed: str) -> bool:
    """Debian version comparison, so that a machine is never downgraded."""
    if not installed:
        return True
    res = subprocess.run(["dpkg", "--compare-versions", candidate, "gt", installed])
    return res.returncode == 0


def latest_release(url: str) -> str:
    """Version of the newest release tag on main ("0.1.7"), or "" when there is none."""
    if not (OS_REPO_DIR / ".git").exists():
        clone(url, OS_REPO_DIR)
    tag = latest_version(OS_REPO_DIR, allow_commit_id=False)
    match = RELEASE_TAG.match(tag)
    if not match:
        if tag:
            log.warning("latest tag %r is not a release tag (vX.Y.Z), ignored", tag)
        return ""
    return match[1]


def pending_release(url: str) -> Optional[str]:
    """The release to install, or None when the machine is up to date."""
    latest = latest_release(url)
    if latest and is_newer(latest, installed_version()):
        return latest
    return None


def build_packages(version: str, on_line: Callable[[str], None]) -> list[Path]:
    """Check out the release and build the packages of this machine's product."""
    product = read_product()
    git(OS_REPO_DIR, "checkout", "--force", "--detach", f"v{version}")
    run_streamed(["./build-sc-os.sh", "debs", product], cwd=OS_REPO_DIR,
                 extra_env={"SC_VERSION": version, "SC_CONF": NO_LOCAL_CONFIG},
                 on_line=on_line)
    packages = sorted((OS_REPO_DIR / "out" / product).glob(f"*_{version}_all.deb"))
    if not packages:
        raise UpdateFailed(f"the build produced no package for version {version}")
    return packages


def install_packages(packages: list[Path], on_line: Callable[[str], None]) -> None:
    # --force-confold: keep the machine's own settings files, never ask at boot.
    run_streamed(
        ["apt-get", "install", "-y", "--no-install-recommends",
         "-o", "Dpkg::Options::=--force-confold", *[str(p) for p in packages]],
        extra_env={"DEBIAN_FRONTEND": "noninteractive"}, on_line=on_line)
