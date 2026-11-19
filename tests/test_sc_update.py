"""Tests for the product-related behaviour of sc-update.

Run: python3 -m unittest discover -s tests
"""
import importlib.machinery
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / "packages/sc-update/pkg/bin/sc-update/sc-update"


def load_updater():
    loader = importlib.machinery.SourceFileLoader("sc_update", str(SCRIPT))
    spec = importlib.util.spec_from_loader("sc_update", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def run_git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True)


class LatestVersionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.origin = root / "origin"
        self.origin.mkdir()
        run_git(self.origin, "init", "-q", "-b", "main")
        run_git(self.origin, "commit", "-q", "--allow-empty", "-m", "first")
        self.clone = root / "clone"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.clone)], check=True)
        self.updater = load_updater()
        patcher = mock.patch.object(self.updater, "REPO_DIR", self.clone)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_returns_latest_tag_when_main_is_tagged(self):
        run_git(self.origin, "tag", "v1")
        self.assertEqual(self.updater.latest_version(), "v1")

    def test_falls_back_to_commit_id_when_main_has_no_tag(self):
        head = subprocess.run(
            ["git", "rev-parse", f"--short={self.updater.SHORT_SHA_LENGTH}", "HEAD"],
            cwd=self.origin, capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(self.updater.latest_version(), head)


class ConfigTest(unittest.TestCase):
    def load(self, text: str) -> dict:
        updater = load_updater()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(text)
            with mock.patch.object(updater, "CONFIG_PATH", path):
                return updater.load_config()

    def test_reads_product_keys(self):
        cfg = self.load(
            "compose-env-file: /etc/sc-os/x.env\n"
            "compose-overrides: [/a.yml]\n"
            "required-files: [/b]\n")
        self.assertEqual(cfg["compose-env-file"], "/etc/sc-os/x.env")
        self.assertEqual(cfg["compose-overrides"], [Path("/a.yml")])
        self.assertEqual(cfg["required-files"], [Path("/b")])

    def test_product_keys_default_to_empty(self):
        cfg = self.load("auto-update: true\n")
        self.assertIsNone(cfg["compose-env-file"])
        self.assertEqual(cfg["required-files"], [])


class RunWaitsForSetupTest(unittest.TestCase):
    def test_missing_required_file_is_not_a_failure_and_skips_the_update(self):
        updater = load_updater()
        cfg = {"required-files": [Path("/nonexistent/sc-os.env")]}
        with mock.patch.object(updater, "load_config", return_value=cfg), \
             mock.patch.object(updater, "ensure_repo"), \
             mock.patch.object(updater, "latest_version") as latest:
            self.assertEqual(updater.run(), 0)
            latest.assert_not_called()


if __name__ == "__main__":
    unittest.main()
