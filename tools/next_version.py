#!/usr/bin/env python3
"""Print the version of the current commit: <major>.<minor>.<patch>.

<major>.<minor> is the content of the VERSION file. <patch> is the number of
commits since the commit that last changed that file, so every commit on main
gets the next number and bumping VERSION restarts the count at 0.

Run it from the repository root, with the whole history available.
"""
import re
import subprocess
import sys
from pathlib import Path

VERSION_FILE = "VERSION"
MAJOR_MINOR_PATTERN = re.compile(r"^\d+\.\d+$")


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"next_version: git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def read_major_minor() -> str:
    path = Path(VERSION_FILE)
    if not path.is_file():
        sys.exit(f"next_version: {VERSION_FILE} not found, run from the repository root")
    value = path.read_text().strip()
    if not MAJOR_MINOR_PATTERN.match(value):
        sys.exit(f"next_version: {VERSION_FILE} must hold <major>.<minor> (for example 0.1), got {value!r}")
    return value


def commits_since_version_change() -> int:
    base = git("log", "-1", "--format=%H", "--", VERSION_FILE)
    if not base:
        sys.exit(f"next_version: {VERSION_FILE} is not committed yet")
    return int(git("rev-list", "--count", f"{base}..HEAD"))


def main() -> int:
    print(f"{read_major_minor()}.{commits_since_version_change()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
