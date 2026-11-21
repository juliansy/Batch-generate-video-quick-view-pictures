"""Temp hygiene: the frame directory must not outlive the run, and stale ones get swept.

These exist because %TEMP% had grown 5 GB of `qvp-*` folders: `rmtree(...,
ignore_errors=True)` swallowed the failures, and a killed run had nobody to
clean up after it.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import qvp  # noqa: E402


class RemoveTreeTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="qvp-frames-test-"))
        self.addCleanup(lambda: qvp.remove_tree(self.folder))

    def test_removes_a_tree_with_files(self):
        (self.folder / "a.bmp").write_bytes(b"x" * 1024)
        (self.folder / "sub").mkdir()
        (self.folder / "sub" / "b.bmp").write_bytes(b"y")
        qvp.remove_tree(self.folder)
        self.assertFalse(self.folder.exists())

    def test_missing_folder_is_not_an_error(self):
        qvp.remove_tree(self.folder / "nope")  # must not raise

    def test_says_something_when_it_cannot_delete(self):
        target = self.folder / "locked.bmp"
        target.write_bytes(b"z")
        handle = open(target, "rb")
        self.addCleanup(handle.close)
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            qvp.remove_tree(self.folder, attempts=2)
        self.assertIn("could not remove temporary files", stderr.getvalue())
        self.assertTrue(self.folder.exists())


class SweepTests(unittest.TestCase):
    def test_old_frame_dirs_are_swept_and_fresh_ones_survive(self):
        temp_root = Path(tempfile.gettempdir())
        old = Path(tempfile.mkdtemp(prefix=qvp.FRAME_PREFIX + "sweep-"))
        fresh = Path(tempfile.mkdtemp(prefix=qvp.FRAME_PREFIX + "keep-"))
        self.addCleanup(lambda: qvp.remove_tree(fresh))
        (old / "frame.bmp").write_bytes(b"x")
        stale = time.time() - 7200
        os.utime(old, (stale, stale))

        removed = qvp.sweep_frame_dirs()

        self.assertGreaterEqual(removed, 1)
        self.assertFalse(old.exists(), "a two-hour-old frame directory should be gone")
        self.assertTrue(fresh.exists(), "a directory from this run must survive")
        self.assertTrue(str(fresh).startswith(str(temp_root)))


if __name__ == "__main__":
    unittest.main()
