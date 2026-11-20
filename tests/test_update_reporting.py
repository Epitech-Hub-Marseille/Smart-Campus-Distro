"""Tests for Plymouth reporting, progress estimates and the OS update logic.

Run: python3 -m unittest discover -s tests
"""
import importlib.machinery
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "packages/sc-update/pkg/bin/sc-update"
sys.path.insert(0, str(PACKAGE_DIR))
sys.dont_write_bytecode = True

import gitrepo  # noqa: E402
import os_update  # noqa: E402
import plymouth_report  # noqa: E402
from gitrepo import UpdateFailed  # noqa: E402
from plymouth_report import Plymouth, StepCounter, UpdateProgress  # noqa: E402


def load_updater():
    loader = importlib.machinery.SourceFileLoader("sc_update_main", str(PACKAGE_DIR / "sc-update"))
    spec = importlib.util.spec_from_loader("sc_update_main", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FakePlymouth:
    """Records what would be sent to Plymouth."""

    def __init__(self):
        self.calls = []

    def message(self, text):
        self.calls.append(("message", text))

    def status(self, text):
        self.calls.append(("status", text))

    def progress(self, percent):
        self.calls.append(("progress", percent))

    def percents(self):
        return [value for kind, value in self.calls if kind == "progress"]


class PlymouthCommandsTest(unittest.TestCase):
    def setUp(self):
        self.plymouth = Plymouth()
        self.plymouth.exe = "/usr/bin/plymouth"
        self.plymouth._is_active = True
        patcher = mock.patch.object(plymouth_report.subprocess, "run")
        self.run = patcher.start()
        self.run.return_value.returncode = 0
        self.addCleanup(patcher.stop)

    def sent(self):
        return [call.args[0][1:] for call in self.run.call_args_list]

    def test_update_mode_and_progress_use_the_commands_the_theme_listens_to(self):
        self.plymouth.start_updates()
        self.plymouth.progress(40)
        self.plymouth.status("Done")
        self.plymouth.finish_updates()
        self.assertEqual(self.sent(), [
            ["change-mode", "--updates"],
            ["system-update", "--progress=40"],
            ["update", "--status=Done"],
            ["change-mode", "--boot-up"],
        ])

    def test_progress_only_goes_up(self):
        for percent in (10, 10, 5, 30):
            self.plymouth.progress(percent)
        self.assertEqual(self.sent(), [["system-update", "--progress=10"],
                                       ["system-update", "--progress=30"]])

    def test_nothing_is_sent_when_plymouth_is_not_running(self):
        self.plymouth._is_active = False
        self.plymouth.start_updates()
        self.plymouth.progress(50)
        self.plymouth.message("x")
        self.run.assert_not_called()


class UpdateProgressTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakePlymouth()
        self.progress = UpdateProgress(self.fake, [("a", 25), ("b", 75)])

    def test_percent_follows_finished_stages_and_the_running_one(self):
        self.progress.start("a", "first")
        self.assertEqual(self.progress.percent(), 0)
        self.progress.finish("first done")
        self.assertEqual(self.progress.percent(), 25)
        self.progress.start("b", "second")
        self.progress.set_fraction(0.5)
        self.assertEqual(self.progress.percent(), 62)

    def test_finishing_every_stage_reaches_one_hundred(self):
        for name in ("a", "b"):
            self.progress.start(name, name)
            self.progress.finish(name)
        self.assertEqual(self.fake.percents()[-1], 100)

    def test_fraction_is_kept_between_zero_and_one(self):
        self.progress.start("a", "first")
        self.progress.set_fraction(7)
        self.assertEqual(self.progress.percent(), 25)

    def test_a_finished_stage_is_reported_as_a_status_line(self):
        self.progress.start("a", "first")
        self.progress.finish("first done")
        self.assertIn(("status", "first done"), self.fake.calls)


class StepCounterTest(unittest.TestCase):
    def test_buildkit_steps_count_when_they_are_done(self):
        counter = StepCounter()
        for line in ("#1 [internal] load build definition", "#2 [build 1/3] FROM node",
                     "#1 DONE 0.1s", "#3 [build 2/3] RUN npm ci", "#2 CACHED"):
            counter.feed(line)
        self.assertEqual(counter.fraction(), 2 / 3)

    def test_estimate_is_held_below_one_hundred_percent(self):
        counter = StepCounter()
        counter.feed("#1 [a 1/1] RUN x")
        counter.feed("#1 DONE 1s")
        self.assertLess(counter.fraction(), 1.0)

    def test_image_pulls_are_counted(self):
        counter = StepCounter()
        counter.feed(" mongo Pulling")
        counter.feed(" redis Pulling")
        counter.feed(" mongo Pulled")
        self.assertEqual(counter.fraction(), 0.5)

    def test_apt_progress_uses_the_known_number_of_packages(self):
        counter = StepCounter(expected=4)
        counter.feed("Setting up sc-update (0.1.7) ...")
        counter.feed("Setting up sc-os-core (0.1.7) ...")
        self.assertEqual(counter.fraction(), 0.5)

    def test_built_packages_are_counted_through_colour_codes(self):
        counter = StepCounter(expected=4)
        counter.feed("\x1b[1;36m==>\x1b[0m built out/faculty-screen/sc-kiosk_0.1.7_all.deb")
        self.assertEqual(counter.fraction(), 0.25)

    def test_no_output_means_no_progress(self):
        self.assertEqual(StepCounter().fraction(), 0.0)


class OsUpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.origin = root / "origin"
        self.origin.mkdir()
        self.git(self.origin, "init", "-q", "-b", "main")
        self.git(self.origin, "commit", "-q", "--allow-empty", "-m", "first")
        for target, name, value in ((os_update, "OS_REPO_DIR", root / "distro"),
                                    (gitrepo, "STATE_DIR", root / "state")):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def git(cwd, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       cwd=cwd, check=True, capture_output=True)

    def test_latest_release_is_the_newest_vx_y_z_tag_without_the_v(self):
        self.git(self.origin, "tag", "v0.1.1")
        self.git(self.origin, "commit", "-q", "--allow-empty", "-m", "second")
        self.git(self.origin, "tag", "v0.1.2")
        self.assertEqual(os_update.latest_release(str(self.origin)), "0.1.2")

    def test_a_tag_that_is_not_a_release_is_ignored(self):
        self.git(self.origin, "tag", "experiment")
        self.assertEqual(os_update.latest_release(str(self.origin)), "")

    def test_an_untagged_repository_gives_no_release(self):
        self.assertEqual(os_update.latest_release(str(self.origin)), "")

    def test_no_update_when_the_installed_version_is_current(self):
        self.git(self.origin, "tag", "v0.1.2")
        with mock.patch.object(os_update, "installed_version", return_value="0.1.2"):
            self.assertIsNone(os_update.pending_release(str(self.origin)))

    def test_update_when_the_installed_version_is_older(self):
        self.git(self.origin, "tag", "v0.1.10")
        with mock.patch.object(os_update, "installed_version", return_value="0.1.9"):
            self.assertEqual(os_update.pending_release(str(self.origin)), "0.1.10")

    def test_a_machine_is_never_downgraded(self):
        self.git(self.origin, "tag", "v0.1.2")
        with mock.patch.object(os_update, "installed_version", return_value="0.2.0"):
            self.assertIsNone(os_update.pending_release(str(self.origin)))

    def test_product_name_is_read_from_the_product_file(self):
        path = Path(self.tmp.name) / "product"
        path.write_text('PRODUCT=faculty-screen\n')
        with mock.patch.object(os_update, "PRODUCT_FILE", path):
            self.assertEqual(os_update.read_product(), "faculty-screen")


class UpdateOrchestrationTest(unittest.TestCase):
    def setUp(self):
        self.updater = load_updater()
        self.fake = FakePlymouth()
        self.fake.start_updates = lambda: self.fake.calls.append(("start", None))
        self.fake.finish_updates = lambda: self.fake.calls.append(("finish", None))
        patcher = mock.patch.object(self.updater, "ply", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_stages_only_include_what_will_run(self):
        names = lambda os_on, product_on: [n for n, _ in self.updater.update_stages(os_on, product_on)]
        self.assertEqual(names(True, False), ["os-build", "os-install"])
        self.assertEqual(names(False, True), ["product-checkout", "product-containers"])
        self.assertEqual(len(names(True, True)), 4)

    def test_a_failed_system_update_does_not_stop_the_product_update(self):
        product_ran = []
        with mock.patch.object(self.updater, "apply_os_update", side_effect=UpdateFailed("build broke")), \
             mock.patch.object(self.updater, "apply_update", side_effect=lambda *a: product_ran.append(True)):
            code = self.updater.apply_updates(
                {}, True, {"latest": "0.1.2"}, True, {"latest": "v2"})
        self.assertEqual(code, 1)
        self.assertEqual(product_ran, [True])

    def test_the_update_bar_is_always_closed(self):
        with mock.patch.object(self.updater, "apply_update", side_effect=UpdateFailed("x")):
            self.updater.apply_updates({}, False, None, True, {"latest": "v2"})
        self.assertEqual(self.fake.calls[0][0], "start")
        self.assertEqual(self.fake.calls[-1][0], "finish")

    def test_check_writes_the_status_file_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = Path(tmp) / "status.json"
            cfg = {"required-files": [], "os-repository-url": None, "os-update": True}
            with mock.patch.object(self.updater, "STATUS_PATH", status), \
                 mock.patch.object(self.updater, "STATE_DIR", Path(tmp)), \
                 mock.patch.object(self.updater, "load_config", return_value=cfg), \
                 mock.patch.object(self.updater, "ensure_repo"), \
                 mock.patch.object(self.updater, "read_version", return_value="v1"), \
                 mock.patch.object(self.updater, "latest_version", return_value="v2"), \
                 mock.patch.object(self.updater, "apply_updates") as apply_updates:
                self.assertEqual(self.updater.run(check_only=True), 0)
            apply_updates.assert_not_called()
            written = json.loads(status.read_text())
        self.assertIsNone(written["os"])
        self.assertTrue(written["product"]["update-available"])
        self.assertEqual(written["product"]["latest"], "v2")


if __name__ == "__main__":
    unittest.main()
