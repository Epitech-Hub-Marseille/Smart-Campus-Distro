"""Git helpers shared by the product updater and the OS updater."""
import logging
import os
import subprocess
from pathlib import Path

from process import UpdateFailed

log = logging.getLogger("sc-update")

STATE_DIR = Path("/var/lib/sc-update")
DEPLOY_KEY_PATH = Path("/etc/sc-os/deploy-key")
KNOWN_HOSTS_PATH = STATE_DIR / "known_hosts"
BRANCH = "main"
SHORT_SHA_LENGTH = 12
GIT_TIMEOUT_SECONDS = 120


def git_env() -> dict:
    """Environment for every git call: never prompt, and use the deploy key if there is one.

    The deploy key lets a machine clone a private repository over ssh. The host key
    is trusted on first use because nobody is at the console to confirm it at boot.
    """
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if DEPLOY_KEY_PATH.is_file():
        env["GIT_SSH_COMMAND"] = (
            f"ssh -i {DEPLOY_KEY_PATH} -o IdentitiesOnly=yes "
            f"-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile={KNOWN_HOSTS_PATH}")
    return env


def git(repo_dir: Path, *args: str, check: bool = True) -> str:
    """Run git in repo_dir and return its output; "" on failure when check is False."""
    cmd = ["git", "-c", f"safe.directory={repo_dir}", "-C", str(repo_dir), *args]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, env=git_env(),
                             timeout=GIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        # A blackholed network must not hold the boot (and the kiosk) forever.
        raise UpdateFailed(f"git {' '.join(args)} timed out after {GIT_TIMEOUT_SECONDS}s")
    except OSError as exc:
        raise UpdateFailed(f"cannot run git: {exc}")
    if res.returncode != 0 and check:
        raise UpdateFailed(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout.strip() if res.returncode == 0 else ""


def clone(url: str, repo_dir: Path) -> None:
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        res = subprocess.run(["git", "clone", "--branch", BRANCH, url, str(repo_dir)],
                             capture_output=True, text=True, env=git_env(),
                             timeout=GIT_TIMEOUT_SECONDS * 5)
    except subprocess.TimeoutExpired:
        raise UpdateFailed(f"git clone of {url} timed out")
    if res.returncode != 0:
        raise UpdateFailed(f"git clone failed: {res.stderr.strip()}")


def latest_version(repo_dir: Path, allow_commit_id: bool = True) -> str:
    """Latest tag on origin/main; the short commit id of origin/main if it has no tag.

    The commit id fallback exists because a repository that does not tag its releases
    would otherwise never be installed. A commit id changes on every push to main, so
    such a machine follows main instead of releases. Callers that need a real version
    number (the OS packages) turn the fallback off and get "" instead.
    """
    git(repo_dir, "fetch", "--force", "--tags", "origin",
        f"+refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}")
    remote_branch = f"refs/remotes/origin/{BRANCH}"
    tag = git(repo_dir, "describe", "--tags", "--abbrev=0", remote_branch, check=False)
    if tag or not allow_commit_id:
        return tag
    return git(repo_dir, "rev-parse", f"--short={SHORT_SHA_LENGTH}", remote_branch, check=False)
