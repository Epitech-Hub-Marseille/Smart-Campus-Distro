"""Running external commands for the updaters."""
import logging
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("sc-update")


class UpdateFailed(Exception):
    """A real failure (as opposed to a cancelled update)."""


def run_streamed(cmd: list[str], cwd: Optional[Path] = None,
                 extra_env: Optional[dict] = None,
                 on_line: Optional[Callable[[str], None]] = None) -> None:
    """Run a command, stream its output into the journal and hand each line to on_line."""
    log.info("$ %s", " ".join(cmd))
    env = {**os.environ, **(extra_env or {})}
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace")
    except OSError as exc:
        raise UpdateFailed(f"cannot run {cmd[0]}: {exc}")
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            log.info("  %s", line)
            if on_line:
                on_line(line)
    returncode = proc.wait()
    if returncode != 0:
        raise UpdateFailed(f"`{' '.join(cmd)}` exited with status {returncode}")
