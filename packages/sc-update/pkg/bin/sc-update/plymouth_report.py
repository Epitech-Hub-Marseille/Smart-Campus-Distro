"""Reports update progress to Plymouth (the orange "Installing updates" bar).

The boot theme (assets/plymouth/sc-boot.script) understands:
  plymouth change-mode --updates      switch the bar to update mode (orange)
  plymouth system-update --progress=N set the bar to N percent
  plymouth display-message --text=T   a line marked [ INFO ] in the log column
  plymouth update --status=T          a line marked [  OK  ] in the log column
Every call does nothing when Plymouth is not running (late in the boot, or on a
machine without a splash), so callers never need to check.
"""
import logging
import re
import shutil
import subprocess
from typing import Optional

log = logging.getLogger("sc-update")

PLYMOUTH_TIMEOUT_SECONDS = 5


class Plymouth:
    def __init__(self) -> None:
        self.exe = shutil.which("plymouth")
        self._is_active: Optional[bool] = None
        self._shown: Optional[str] = None
        self._last_percent = -1

    def active(self) -> bool:
        """True when the Plymouth daemon answers. Asked once: it does not come back after quitting."""
        if self._is_active is None:
            self._is_active = bool(self.exe) and self._run("--ping")
        return self._is_active

    def _run(self, *args: str) -> bool:
        try:
            return subprocess.run(
                [self.exe, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=PLYMOUTH_TIMEOUT_SECONDS).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def message(self, text: str) -> None:
        """Show text as the current message (an [ INFO ] line)."""
        if not self.active():
            return
        if self._shown:
            self._run("hide-message", f"--text={self._shown}")
        self._run("display-message", f"--text={text}")
        self._shown = text

    def status(self, text: str) -> None:
        """Add a finished step to the log column (an [  OK  ] line)."""
        if self.active():
            self._run("update", f"--status={text}")

    def start_updates(self) -> None:
        if self.active():
            self._last_percent = -1
            self._run("change-mode", "--updates")

    def progress(self, percent: int) -> None:
        """Set the update bar. Only increasing values are sent: each call starts a process."""
        if percent <= self._last_percent or not self.active():
            return
        self._last_percent = percent
        self._run("system-update", f"--progress={percent}")

    def finish_updates(self) -> None:
        if self.active():
            self._run("change-mode", "--boot-up")


class UpdateProgress:
    """Turns the stages of an update into one percentage for the bar.

    Each stage has a weight; the bar is the share of finished weight plus the
    finished fraction of the running stage. It never goes backwards.
    """

    def __init__(self, plymouth: Plymouth, stages: list[tuple[str, int]]) -> None:
        self.plymouth = plymouth
        self.weights = dict(stages)
        self.total = sum(self.weights.values()) or 1
        self.finished: set[str] = set()
        self.current: Optional[str] = None
        self.fraction = 0.0

    def percent(self) -> int:
        done = sum(self.weights[name] for name in self.finished)
        if self.current is not None:
            done += self.weights[self.current] * self.fraction
        return int(100 * done / self.total)

    def start(self, stage: str, label: str) -> None:
        self.current, self.fraction = stage, 0.0
        log.info(label)
        self.plymouth.message(f"Smart Campus: {label}")
        self.plymouth.progress(self.percent())

    def set_fraction(self, fraction: float) -> None:
        self.fraction = min(max(fraction, 0.0), 1.0)
        self.plymouth.progress(self.percent())

    def finish(self, label: str) -> None:
        if self.current is not None:
            self.finished.add(self.current)
        self.current, self.fraction = None, 0.0
        log.info(label)
        self.plymouth.status(label)
        self.plymouth.progress(self.percent())


class StepCounter:
    """Estimates progress from the output of docker (BuildKit plain) and apt.

    The total number of steps is not known in advance, so the estimate is the share
    of steps seen so far that are finished. It is held below 100% until the caller
    says the command is over, because steps keep appearing while it runs.
    """

    MAX_BEFORE_DONE = 0.95
    # BuildKit: "#12 [build 3/8] RUN npm ci" announces a step, "#12 DONE 1.2s" ends it,
    # "#12 CACHED" is both. Compose: " mongo Pulling" then " mongo Pulled".
    _BUILD_STEP = re.compile(r"^#(\d+) \[")
    _BUILD_DONE = re.compile(r"^#(\d+) (?:DONE|CACHED)\b")
    _PULL_START = re.compile(r"^\s*(\S+)\s+Pulling\s*$")
    _PULL_END = re.compile(r"^\s*(\S+)\s+Pulled\s*$")
    _APT_SETUP = re.compile(r"^Setting up (\S+)")
    # build-sc-os.sh: "==> built out/faculty-screen/sc-kiosk_0.1.7_all.deb" (colour codes around ==>)
    _PACKAGE_BUILT = re.compile(r"built \S+\.deb")
    _COLOUR_CODES = re.compile(r"\x1b\[[0-9;]*m")

    def __init__(self, expected: int = 0) -> None:
        """expected: known number of units (apt packages); 0 when unknown (docker)."""
        self.expected = expected
        self.seen: set[str] = set()
        self.done: set[str] = set()

    def feed(self, line: str) -> None:
        line = self._COLOUR_CODES.sub("", line)
        if match := self._PACKAGE_BUILT.search(line):
            self.seen.add(match[0])
            self.done.add(match[0])
        elif match := self._BUILD_STEP.match(line):
            self.seen.add(f"step{match[1]}")
        elif match := self._BUILD_DONE.match(line):
            self.seen.add(f"step{match[1]}")
            self.done.add(f"step{match[1]}")
        elif match := self._PULL_START.match(line):
            self.seen.add(f"pull {match[1]}")
        elif match := self._PULL_END.match(line):
            self.seen.add(f"pull {match[1]}")
            self.done.add(f"pull {match[1]}")
        elif match := self._APT_SETUP.match(line):
            self.seen.add(match[1])
            self.done.add(match[1])

    def fraction(self) -> float:
        total = self.expected or len(self.seen)
        if total == 0:
            return 0.0
        return min(len(self.done) / total, self.MAX_BEFORE_DONE)
