"""Tests for tools/next_version.py.

Run: python3 -m unittest discover -s tests
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "tools/next_version.py"


class NextVersionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       cwd=self.repo, check=True, capture_output=True)

    def commit(self, name: str) -> None:
        (self.repo / name).write_text(name)
        self.git("add", name)
        self.git("commit", "-q", "-m", name)

    def set_version(self, value: str) -> None:
        (self.repo / "VERSION").write_text(value + "\n")
        self.git("add", "VERSION")
        self.git("commit", "-q", "-m", f"version {value}")

    def next_version(self) -> subprocess.CompletedProcess:
        return subprocess.run(["python3", "-I", str(SCRIPT)], cwd=self.repo,
                              capture_output=True, text=True)

    def test_the_commit_that_sets_the_version_is_patch_zero(self):
        self.set_version("0.1")
        self.assertEqual(self.next_version().stdout.strip(), "0.1.0")

    def test_each_later_commit_adds_one(self):
        self.set_version("0.1")
        self.commit("a")
        self.commit("b")
        self.commit("c")
        self.assertEqual(self.next_version().stdout.strip(), "0.1.3")

    def test_changing_the_minor_restarts_the_count(self):
        self.set_version("0.1")
        self.commit("a")
        self.commit("b")
        self.set_version("0.2")
        self.assertEqual(self.next_version().stdout.strip(), "0.2.0")
        self.commit("c")
        self.assertEqual(self.next_version().stdout.strip(), "0.2.1")

    def test_rejects_a_malformed_version_file(self):
        self.set_version("0.1.5")
        result = self.next_version()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("<major>.<minor>", result.stderr)

    def test_fails_without_a_version_file(self):
        self.commit("a")
        self.assertNotEqual(self.next_version().returncode, 0)


if __name__ == "__main__":
    unittest.main()
