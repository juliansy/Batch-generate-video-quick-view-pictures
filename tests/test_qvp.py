"""Tests for qvp.py - pure logic first, then an end-to-end run on a real clip.

Run from the repository root::

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import _thread
import json
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import qvp  # noqa: E402

FFMPEG = (qvp.ffmpeg_candidates() or [None])[0]


def make_clip(path: Path, seconds: float = 4, size: str = "320x240", rate: int = 10) -> Path:
    assert FFMPEG, "ffmpeg is required for the integration tests"
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={seconds}:size={size}:rate={rate}",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def run_main(argv: list[str]) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = qvp.main(argv)
    return code, out.getvalue() + err.getvalue()


class PureLogicTests(unittest.TestCase):
    def test_parse_grid_accepts_common_separators(self):
        self.assertEqual(qvp.parse_grid("4x4"), (4, 4))
        self.assertEqual(qvp.parse_grid("4X4"), (4, 4))
        self.assertEqual(qvp.parse_grid("2*3"), (2, 3))
        self.assertEqual(qvp.parse_grid(" 2, 3 "), (2, 3))

    def test_parse_grid_rejects_nonsense(self):
        for bad in ("4", "0x4", "4x17", "axb", "-1x4"):
            with self.subTest(bad=bad), self.assertRaises(qvp.UsageError):
                qvp.parse_grid(bad)

    def test_sample_times_span_the_whole_video(self):
        times = qvp.sample_times(20.0, 4)
        self.assertEqual(len(times), 4)
        self.assertAlmostEqual(times[0], 1.0, places=3)  # a second in, not the fade
        self.assertAlmostEqual(times[-1], 19.0, places=3)  # a second before the end
        self.assertEqual(list(times), sorted(times))
        for moment in times:
            self.assertGreaterEqual(moment, 0)
            self.assertLess(moment, 20.0)

    def test_edge_inset_shrinks_for_short_clips(self):
        times = qvp.sample_times(2.0, 2)  # half the clip is too small an inset
        self.assertAlmostEqual(times[0], 0.5, places=3)
        self.assertAlmostEqual(times[-1], 1.5, places=3)

    def test_sample_times_single_frame_lands_in_the_middle(self):
        self.assertEqual(len(qvp.sample_times(10.0, 1)), 1)

    def test_sample_times_last_one_never_hits_the_end(self):
        times = qvp.sample_times(1.0, 16)
        self.assertLessEqual(times[-1], 0.95)

    def test_sample_times_respects_frame_rate(self):
        times = qvp.sample_times(0.3, 4, fps=10)
        self.assertLessEqual(times[-1], 0.16)
        self.assertTrue(all(moment >= 0 for moment in times))

    def test_sample_times_rejects_bad_input(self):
        with self.assertRaises(qvp.UsageError):
            qvp.sample_times(4.0, 0)
        with self.assertRaises(qvp.ProbeError):
            qvp.sample_times(0.0, 4)

    def test_timecode_styles(self):
        self.assertEqual(qvp.format_timecode(0), "00:00")
        self.assertEqual(qvp.format_timecode(26.25), "00:26")
        self.assertEqual(qvp.format_timecode(3661), "1:01:01")
        self.assertEqual(qvp.format_timecode(59.6), "01:00")  # rounds up
        self.assertEqual(qvp.format_timecode(3661, "hms"), "01:01:01")
        self.assertEqual(qvp.format_timecode(3661, "ms"), "61:01")

    def test_layout_geometry(self):
        layout = qvp.layout_for(1920, 1080, (4, 4), 2)
        self.assertEqual((layout.cell_w, layout.cell_h), (1924, 1084))
        self.assertEqual(layout.canvas, (7696, 4336))
        self.assertEqual(layout.cells, 16)
        self.assertEqual(layout.pixels, 7696 * 4336)

    def test_layout_rejects_empty_or_negative(self):
        with self.assertRaises(qvp.ProbeError):
            qvp.layout_for(0, 0, (4, 4), 2)
        with self.assertRaises(qvp.UsageError):
            qvp.layout_for(10, 10, (2, 2), -1)

    def test_output_name_and_font_size(self):
        self.assertEqual(qvp.output_name("clip"), "clip_collage.jpg")
        self.assertEqual(qvp.font_size_for(1920), 42)
        self.assertEqual(qvp.font_size_for(100), 12)
        self.assertEqual(qvp.font_size_for(10000), 96)

    def test_is_video(self):
        self.assertTrue(qvp.is_video(Path("a.MP4")))
        self.assertTrue(qvp.is_video(Path("a.webm")))
        self.assertFalse(qvp.is_video(Path("a.txt")))
        self.assertFalse(qvp.is_video(Path("a.mp4.txt")))

    def test_colour_validation(self):
        self.assertEqual(qvp.color_or_raise("red"), "red")
        self.assertEqual(qvp.color_or_raise("#00ff00"), "#00ff00")
        with self.assertRaises(qvp.UsageError):
            qvp.color_or_raise("not-a-colour")

    def test_short_error_keeps_one_line(self):
        message = qvp.short_error(
            RuntimeError("Error opening input files:\n moov atom not found\n xx.mp4: Invalid data")
        )
        self.assertNotIn("\n", message)
        self.assertIn("moov atom not found", message)
        self.assertLessEqual(len(message), 141)

    def test_display_width_counts_wide_characters(self):
        self.assertEqual(qvp.display_width("abc"), 3)
        self.assertEqual(qvp.display_width("文件"), 4)
        self.assertEqual(qvp.pad("文件", 6), "文件  ")

    def test_report_counts_statuses(self):
        results = [
            qvp.Result("a.mp4", "ok", "", 1.0, 4, grid="2x2", canvas=(10, 10)),
            qvp.Result("b.mp4", "skipped", "already exists"),
            qvp.Result("c.mp4", "failed", "cannot open video (boom)"),
        ]
        report = qvp.render_report(results, 2.5)
        self.assertIn("1 done, 1 skipped, 1 failed | 2.50s", report)
        self.assertIn("skipped: already exists", report)
        self.assertIn("failed: cannot open video (boom)", report)

    def test_option_validation(self):
        parser = qvp.build_parser()
        bad = [
            ["--frames", "0"],
            ["--border", "-1"],
            ["--jobs", "0"],
            ["--max-pixels", "10"],
            ["--font-size", "3"],
        ]
        for argv in bad:
            with self.subTest(argv=argv):
                args = parser.parse_args(argv)
                with self.assertRaises(qvp.UsageError):
                    qvp.options_from_args(args)

    def test_version_flag_exits_zero(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = qvp.main(["--version"])
        self.assertEqual(code, 0)
        self.assertIn(qvp.VERSION, out.getvalue())


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="qvp-discovery-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_finds_sorts_and_dedupes(self):
        (self.tmp / "b.mp4").write_bytes(b"")
        (self.tmp / "A.MP4").write_bytes(b"")
        (self.tmp / "notes.txt").write_bytes(b"")
        (self.tmp / "sub").mkdir()
        (self.tmp / "sub" / "c.mov").write_bytes(b"")
        (self.tmp / "sub" / "deck.pptx").write_bytes(b"")

        flat, missing = qvp.discover([self.tmp, self.tmp], recursive=False)
        self.assertEqual([p.name for p in flat], ["A.MP4", "b.mp4"])
        self.assertEqual(missing, [])

        deep, _ = qvp.discover([self.tmp], recursive=True)
        self.assertEqual([p.name for p in deep], ["A.MP4", "b.mp4", "c.mov"])

    def test_reports_missing_and_non_video_arguments(self):
        missing_file = self.tmp / "ghost"
        text_file = self.tmp / "readme.txt"
        text_file.write_text("x", encoding="utf-8")
        found, missing = qvp.discover([missing_file, text_file], recursive=False)
        self.assertEqual(found, [])
        self.assertEqual(missing, [missing_file, text_file])


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FFMPEG:
            raise unittest.SkipTest("ffmpeg not available")
        cls.base = Path(tempfile.mkdtemp(prefix="qvp-e2e-"))
        cls.clip = make_clip(cls.base / "src" / "clip.mp4", seconds=4)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def workdir(self, name: str) -> Path:
        folder = self.base / name
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        shutil.copy(self.clip, folder / "clip.mp4")
        return folder

    def test_renders_a_grid_of_the_expected_size(self):
        folder = self.workdir("basic")
        code, output = run_main([str(folder), "--frames", "4", "--grid", "2x2"])
        self.assertEqual(code, 0, output)
        sheet = folder / qvp.OUT_DIR_NAME / "clip_collage.jpg"
        self.assertTrue(sheet.exists(), output)
        from PIL import Image

        with Image.open(sheet) as image:
            self.assertEqual(image.size, (2 * (320 + 4), 2 * (240 + 4)))
            # 时间戳是红字描黑边：左上角应该有红色像素
            corner = image.crop((0, 0, 120, 60)).convert("RGB")
            reds = [p for p in corner.getdata() if p[0] > 180 and p[1] < 90 and p[2] < 90]
            self.assertGreater(len(reds), 20, "timecode was not drawn")
        self.assertEqual(list((folder / qvp.OUT_DIR_NAME).glob(".tmp-*")), [])

    def test_second_run_skips_and_force_rewrites(self):
        folder = self.workdir("skip")
        self.assertEqual(run_main([str(folder), "--frames", "4"])[0], 0)
        sheet = folder / qvp.OUT_DIR_NAME / "clip_collage.jpg"
        first = sheet.stat().st_mtime_ns
        code, output = run_main([str(folder), "--frames", "4", "--batch-seek", "1"])
        self.assertEqual(code, 0)
        self.assertIn("skipped: already exists", output)
        self.assertEqual(sheet.stat().st_mtime_ns, first)
        self.assertEqual(run_main([str(folder), "--frames", "4", "--force"])[0], 0)
        self.assertNotEqual(sheet.stat().st_mtime_ns, first)

    def test_dry_run_writes_nothing(self):
        folder = self.workdir("dry")
        code, output = run_main([str(folder), "--frames", "4", "-n"])
        self.assertEqual(code, 0)
        self.assertIn("would write", output)
        self.assertFalse((folder / qvp.OUT_DIR_NAME).exists())

    def test_bad_file_does_not_stop_the_batch(self):
        folder = self.workdir("bad")
        (folder / "aaa_broken.mp4").write_bytes(b"not a video at all")
        code, output = run_main([str(folder), "--frames", "4"])
        self.assertEqual(code, 1, output)
        self.assertTrue((folder / qvp.OUT_DIR_NAME / "clip_collage.jpg").exists())
        self.assertIn("failed: cannot open video", output)

    def test_frames_that_do_not_fit_the_grid_fail_loudly(self):
        folder = self.workdir("overflow")
        code, output = run_main([str(folder), "--frames", "9", "--grid", "2x2"])
        self.assertEqual(code, 1)
        self.assertIn("do not fit a 2x2 grid", output)

    def test_pixel_budget_is_enforced(self):
        folder = self.workdir("budget")
        code, output = run_main(
            [str(folder), "--frames", "4", "--grid", "16x16", "--max-pixels", "1000000"]
        )
        self.assertEqual(code, 1)
        self.assertIn("over the 1 MP limit", output)

    def test_recursive_finds_nested_videos(self):
        folder = self.workdir("recursive")
        nested = folder / "sub"
        nested.mkdir()
        shutil.copy(self.clip, nested / "deep.mp4")
        code, _ = run_main([str(folder), "--frames", "4"])
        self.assertEqual(code, 0)
        self.assertFalse((nested / qvp.OUT_DIR_NAME).exists())
        code, _ = run_main([str(folder), "--frames", "4", "-R"])
        self.assertEqual(code, 0)
        self.assertTrue((nested / qvp.OUT_DIR_NAME / "deep_collage.jpg").exists())

    def test_two_sources_with_the_same_name_skip_the_second(self):
        folder = self.workdir("collision")
        other = folder / "other"
        other.mkdir()
        shutil.copy(self.clip, other / "clip.mp4")
        out = folder / "shared"
        code, output = run_main([str(folder), str(other), "--frames", "4", "-o", str(out), "-R"])
        self.assertEqual(code, 0, output)
        self.assertIn("output name already used by clip.mp4", output)
        self.assertIn("1 done", output)
        self.assertIn("1 skipped", output)

    def test_same_stem_two_extensions_skips_instead_of_failing(self):
        folder = self.workdir("stemclash")
        (folder / "clip.mp4").unlink()
        shutil.copy(self.clip, folder / "talk.mp4")
        shutil.copy(self.clip, folder / "talk.mkv")
        code, output = run_main([str(folder), "--frames", "4"])
        self.assertEqual(code, 0, output)
        self.assertIn("skipped: output name already used by", output)
        self.assertEqual(
            sorted(p.name for p in (folder / qvp.OUT_DIR_NAME).iterdir()),
            ["talk_collage.jpg"],
        )

    def test_jobs_and_log(self):
        folder = self.workdir("jobs")
        shutil.copy(self.clip, folder / "clip2.mp4")
        log = folder / "run.log"
        code, output = run_main([str(folder), "--frames", "4", "-j", "2", "--log", str(log), "-q"])
        self.assertEqual(code, 0, output)
        self.assertTrue((folder / qvp.OUT_DIR_NAME / "clip2_collage.jpg").exists())
        self.assertIn("2 done", log.read_text(encoding="utf-8"))

    def test_unicode_file_name(self):
        folder = self.workdir("unicode")
        target = folder / "课程 01 🎬.mp4"
        shutil.copy(self.clip, target)
        code, output = run_main([str(target), "--frames", "4"])
        self.assertEqual(code, 0, output)
        self.assertTrue((folder / qvp.OUT_DIR_NAME / "课程 01 🎬_collage.jpg").exists())

    def test_missing_path_is_reported_as_a_bad_argument(self):
        code, output = run_main([str(self.base / "nope"), "-q"])
        self.assertEqual(code, 2)
        self.assertIn("no videos found", output)

    def test_empty_folder_is_not_an_error(self):
        folder = self.base / "empty-folder"
        folder.mkdir(exist_ok=True)
        code, output = run_main([str(folder), "-q"])
        self.assertEqual(code, 0)
        self.assertIn("no videos found", output)

    def test_broken_ffmpeg_flag_falls_back_instead_of_failing(self):
        folder = self.workdir("ffmpeg-fallback")
        code, output = run_main([str(folder), "--frames", "4", "--ffmpeg", r"Z:\nope\ffmpeg.exe"])
        self.assertEqual(code, 0, output)
        self.assertTrue((folder / qvp.OUT_DIR_NAME / "clip_collage.jpg").exists())

    def test_quiet_suppresses_progress_lines(self):
        folder = self.workdir("quiet")
        code, output = run_main([str(folder), "--frames", "4", "-q"])
        self.assertEqual(code, 0)
        self.assertNotIn("[1/1]", output)
        self.assertIn("1 done", output)

    def test_report_groups_ok_then_skipped_then_failed(self):
        folder = self.workdir("order")
        (folder / "aaa_broken.mp4").write_bytes(b"garbage")
        (folder / "mmm.mkv").write_bytes(b"garbage")
        (folder / "talk.mp4").write_bytes((folder / "clip.mp4").read_bytes())
        (folder / "talk.mkv").write_bytes((folder / "clip.mp4").read_bytes())
        code, output = run_main([str(folder), "--frames", "4"])
        self.assertEqual(code, 1)
        table = output[output.index("result") :]
        done = table.index("clip.mp4")
        skipped = table.index("skipped: output name already used by")
        failed = table.index("aaa_broken.mp4")
        self.assertLess(done, skipped, table)
        self.assertLess(skipped, failed, table)
        # every failure sits at the bottom, so the block can be copied in one go
        import re as _re

        rows = [line for line in table.splitlines() if _re.match(r"^\d+\s{2,}\S", line)]
        statuses = [
            "failed" if "failed:" in line else "skipped" if "skipped:" in line else "ok"
            for line in rows
        ]
        rank = {"ok": 0, "skipped": 1, "failed": 2}
        self.assertEqual(statuses, sorted(statuses, key=rank.get), rows)
        self.assertGreaterEqual(statuses.count("failed"), 2)

    def test_report_numbers_stay_in_discovery_order(self):
        folder = self.workdir("order2")
        (folder / "aaa_broken.mp4").write_bytes(b"garbage")
        code, output = run_main([str(folder), "--frames", "4"])
        self.assertEqual(code, 1)
        table = output[output.index("result") :]
        first_failed = next(line for line in table.splitlines() if "aaa_broken.mp4" in line)
        self.assertTrue(first_failed.startswith("1 "), first_failed)

    def test_unusable_font_fails_the_file_not_the_batch(self):
        folder = self.workdir("font")
        code, output = run_main([str(folder), "--frames", "4", "--font", r"Z:\nope\font.ttf"])
        self.assertEqual(code, 1)
        self.assertIn("cannot load font", output)

    def test_output_path_that_is_a_file_fails_cleanly(self):
        folder = self.workdir("out-is-file")
        blocker = folder / "not-a-folder"
        blocker.write_text("x", encoding="utf-8")
        code, output = run_main([str(folder), "--frames", "4", "-o", str(blocker)])
        self.assertEqual(code, 1)
        self.assertIn("cannot write output", output)

    def test_very_short_video_still_renders(self):
        folder = self.workdir("short")
        make_clip(folder / "tiny.mp4", seconds=0.3)
        code, output = run_main([str(folder / "tiny.mp4"), "--frames", "4"])
        self.assertEqual(code, 0, output)
        self.assertTrue((folder / qvp.OUT_DIR_NAME / "tiny_collage.jpg").exists())

    def test_hms_time_format(self):
        folder = self.workdir("hms")
        code, output = run_main([str(folder), "--frames", "4", "--time-format", "hms"])
        self.assertEqual(code, 0, output)
        self.assertTrue((folder / qvp.OUT_DIR_NAME / "clip_collage.jpg").exists())

    def test_invalid_grid_is_a_usage_error_not_a_traceback(self):
        code, output = run_main(["--grid", "4x4x4"])
        self.assertEqual(code, 2, output)
        self.assertIn("invalid grid", output)
        self.assertNotIn("Traceback", output)

    def test_short_grid_flag(self):
        folder = self.workdir("short-grid")
        code, output = run_main([str(folder), "--frames", "4", "-g", "2x2"])
        self.assertEqual(code, 0, output)

    def test_redirected_stdout_with_emoji_name(self):
        folder = self.workdir("emoji-redirect")
        shutil.copy(self.clip, folder / "课程 🎬.mp4")
        env = dict(os.environ, PYTHONIOENCODING="gbk", PYTHONUTF8="0")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "qvp.py"), str(folder), "--frames", "4"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_dry_run_with_log_writes_nothing(self):
        folder = self.workdir("dry-log")
        log = folder / "run.log"
        code, output = run_main([str(folder), "--frames", "4", "-n", "--log", str(log)])
        self.assertEqual(code, 0, output)
        self.assertFalse(log.exists())

    def test_same_folder_spelled_twice_is_processed_once(self):
        folder = self.workdir("twice")
        empty = self.base / "empty-twice"
        empty.mkdir(exist_ok=True)
        code, output = run_main([str(folder), str(folder) + os.sep, str(empty), "--frames", "4"])
        self.assertEqual(code, 0, output)
        self.assertIn("1 done", output)

    def test_frame_of_another_size_is_fitted_not_fatal(self):
        from PIL import Image as PILImage
        from unittest import mock

        folder = self.workdir("mismatch")
        with mock.patch.object(
            qvp, "grab_frame_ffmpeg", lambda *a, **k: PILImage.new("RGB", (10, 10), "blue")
        ):
            code, output = run_main([str(folder), "--frames", "4", "--batch-seek", "1"])
        self.assertEqual(code, 0, output)
        self.assertIn("1 done", output)

    def test_empty_report_does_not_crash(self):
        self.assertEqual(qvp.render_report([], 0.1), "nothing to report")

    def test_dry_run_summary_counts_planned(self):
        folder = self.workdir("dry-count")
        code, output = run_main([str(folder), "--frames", "4", "-n"])
        self.assertEqual(code, 0)
        self.assertIn("1 planned", output)
        self.assertIn("0 done", output)

    def test_no_temp_files_after_a_run(self):
        folder = self.workdir("temps")
        run_main([str(folder), "--frames", "4"])
        leftovers = list((folder / qvp.OUT_DIR_NAME).glob(".*.tmp-*"))
        self.assertEqual(leftovers, [])

    def test_cells_are_different_pictures(self):
        folder = self.workdir("cells")
        self.assertEqual(run_main([str(folder), "--frames", "4", "-g", "2x2"])[0], 0)
        from PIL import Image as PILImage

        from PIL import Image as PILImage

        with PILImage.open(folder / qvp.OUT_DIR_NAME / "clip_collage.jpg") as sheet:
            width, height = sheet.size
            cell_w, cell_h = width // 2, height // 2
            first = sheet.crop((0, 0, cell_w, cell_h)).resize((32, 32)).tobytes()
            second = sheet.crop((cell_w, 0, width, cell_h)).resize((32, 32)).tobytes()
        self.assertNotEqual(first, second)

    def test_auto_grid_picks_by_duration(self):
        cases = [
            (10, (2, 2)),
            (20, (2, 2)),
            (21, (3, 2)),
            (40, (3, 2)),
            (41, (3, 3)),
            (60, (3, 3)),
            (61, (4, 3)),
            (180, (4, 3)),
            (181, (4, 4)),
            (300, (4, 4)),
            (301, (5, 4)),
            (720, (5, 4)),
            (721, (5, 5)),
            (7200, (5, 5)),
        ]
        for duration, grid in cases:
            with self.subTest(duration=duration):
                self.assertEqual(qvp.auto_grid(duration, 1920, 1080, 2, 200_000_000), grid)

    def test_auto_grid_shrinks_to_fit_the_pixel_budget(self):
        # 4K: 5x5 is 208 MP - just over the 200 MP default, so it drops to 5x4 (166 MP)
        self.assertEqual(qvp.auto_grid(7200, 3840, 2160, 2, 200_000_000), (5, 4))
        self.assertEqual(qvp.auto_grid(7200, 3840, 2160, 2, 210_000_000), (5, 5))
        self.assertEqual(qvp.auto_grid(7200, 3840, 2160, 2, 170_000_000), (5, 4))
        self.assertEqual(qvp.auto_grid(7200, 3840, 2160, 2, 150_000_000), (4, 4))
        self.assertEqual(qvp.auto_grid(7200, 3840, 2160, 2, 110_000_000), (4, 3))

    def test_grid_for_frames(self):
        self.assertEqual(qvp.grid_for_frames(1), (2, 2))
        self.assertEqual(qvp.grid_for_frames(4), (2, 2))
        self.assertEqual(qvp.grid_for_frames(6), (3, 2))
        self.assertEqual(qvp.grid_for_frames(9), (3, 3))
        self.assertEqual(qvp.grid_for_frames(10), (4, 3))
        self.assertEqual(qvp.grid_for_frames(20), (5, 4))
        self.assertEqual(qvp.grid_for_frames(25), (5, 5))
        with self.assertRaises(qvp.UsageError):
            qvp.grid_for_frames(26)

    def test_prints_a_banner_before_rendering(self):
        folder = self.workdir("banner")
        code, output = run_main([str(folder)])
        self.assertEqual(code, 0, output)
        lines = [line for line in output.splitlines() if line.strip()]
        self.assertTrue(lines[0].startswith("qvp "), lines[:2])
        self.assertIn("sheets/", lines[1], lines[:2])

    def test_decode_plan_uses_cores_but_stays_bounded(self):
        workers, threads = qvp.decode_plan(25)
        self.assertGreaterEqual(workers, 1)
        self.assertLessEqual(workers, qvp.MAX_DECODE_WORKERS)
        # threads stays 0: ffmpeg picks its own count, which measured faster
        self.assertEqual(threads, 0)
        self.assertEqual(qvp.decode_plan(1), (1, 0))  # nothing to overlap
        self.assertEqual(qvp.decode_plan(25, requested=1), (1, 0))
        self.assertEqual(qvp.decode_plan(25, requested=2)[0], 2)
        self.assertEqual(qvp.decode_plan(3, requested=8)[0], 3)  # never more workers than frames

    def test_decode_workers_flag_changes_the_result_but_not_the_sheet(self):
        folder = self.workdir("workers")
        code, output = run_main([str(folder), "-f", "-g", "2x2", "--decode-workers", "2"])
        self.assertEqual(code, 0, output)
        from PIL import Image as PILImage

        with PILImage.open(folder / qvp.OUT_DIR_NAME / "clip_collage.jpg") as sheet:
            self.assertEqual(sheet.size, (2 * (320 + 4), 2 * (240 + 4)))

    def test_seeks_per_process_defaults(self):
        self.assertEqual(qvp.seeks_per_process("none", 0), 1)
        self.assertEqual(qvp.seeks_per_process("cuda", 0), qvp.DEFAULT_GPU_BATCH_SEEK)
        self.assertEqual(qvp.seeks_per_process("none", 3), 3)
        self.assertEqual(qvp.seeks_per_process("cuda", 1), 1)

    def test_bad_batch_seek_exits_2(self):
        self.assertEqual(qvp.main(["--batch-seek", "99", "."]), 2)

    def test_batched_and_per_frame_sheets_match(self):
        batched = self.workdir("batch-default")
        calls = []
        real = qvp.extract_chunk

        def counting(*args, **kwargs):
            frames = real(*args, **kwargs)
            calls.append(len(frames))
            return frames

        single_calls = []
        real_single = qvp.grab_frame_ffmpeg

        def counting_single(*args, **kwargs):
            single_calls.append(1)
            return real_single(*args, **kwargs)

        with (
            mock.patch.object(qvp, "extract_chunk", counting),
            mock.patch.object(qvp, "grab_frame_ffmpeg", counting_single),
        ):
            code, output = run_main(
                [str(batched), "-f", "-g", "3x3", "--frames", "9", "--batch-seek", "4"]
            )
        self.assertEqual(code, 0, output)
        self.assertGreaterEqual(sum(calls), 8, "most cells must come from batched chunks")
        self.assertLessEqual(len(single_calls), 1, "only a leftover cell may use a single grab")
        single = self.workdir("batch-one")
        code, output = run_main(
            [str(single), "-f", "-g", "3x3", "--frames", "9", "--batch-seek", "1"]
        )
        self.assertEqual(code, 0, output)

        import numpy as np
        from PIL import Image as PILImage

        left = PILImage.open(next((batched / qvp.OUT_DIR_NAME).glob("*.jpg"))).convert("RGB")
        right = PILImage.open(next((single / qvp.OUT_DIR_NAME).glob("*.jpg"))).convert("RGB")
        self.assertEqual(left.size, right.size)
        diff = np.abs(np.asarray(left, np.int16) - np.asarray(right, np.int16)).mean()
        self.assertLess(float(diff), 1.0, "batched and per-frame sheets should match")

    def test_hardware_modes_try_gpu_then_software(self):
        self.assertEqual(qvp.hardware_modes(False), ("none",))
        self.assertEqual(qvp.hardware_modes(True), ("cuda", "none"))

    def test_old_hwaccel_option_is_gone(self):
        self.assertEqual(qvp.main(["--hwaccel", "cuda", "."]), 2)

    def test_gpu_failure_falls_back_to_software(self):
        from unittest import mock

        original = qvp.grab_frame_ffmpeg

        def fake(
            video,
            moment,
            probe,
            binary,
            threads=0,
            hwaccel="none",
            prefer_normalize=False,
            hint=None,
        ):
            if hwaccel == "cuda":
                raise qvp.FrameError("no GPU here")
            return original(video, moment, probe, binary, threads, "none", prefer_normalize, hint)

        folder = self.workdir("fallback")
        with mock.patch.object(qvp, "grab_frame_ffmpeg", side_effect=fake):
            code, output = run_main([str(folder), "-f", "--cuda"])
        self.assertEqual(code, 0, output)
        self.assertIn("software fallback", output)

    def test_hardware_frame_matches_software(self):
        """Only when the machine really has CUDA and QVP_TEST_CUDA=1."""
        if os.environ.get("QVP_TEST_CUDA") != "1":
            self.skipTest("set QVP_TEST_CUDA=1 to run the GPU comparison")
        folder = self.workdir("gpu")
        code, output = run_main([str(folder), "-f", "-g", "2x2", "--cuda"])
        self.assertEqual(code, 0, output)
        self.assertIn("ok (GPU)", output)

        import numpy as np
        from PIL import Image as PILImage

        cpu_folder = self.workdir("gpu-cpu")
        code, output = run_main([str(cpu_folder), "-f", "-g", "2x2"])
        self.assertEqual(code, 0, output)
        gpu_sheet = PILImage.open(next((folder / qvp.OUT_DIR_NAME).glob("*.jpg"))).convert("RGB")
        cpu_sheet = PILImage.open(next((cpu_folder / qvp.OUT_DIR_NAME).glob("*.jpg"))).convert(
            "RGB"
        )
        self.assertEqual(gpu_sheet.size, cpu_sheet.size)
        diff = np.abs(np.asarray(gpu_sheet, np.int16) - np.asarray(cpu_sheet, np.int16)).mean()
        self.assertLess(float(diff), 3.0, "GPU and software frames differ too much")

    def test_bad_decode_workers_exits_2(self):
        code = qvp.main(["--decode-workers", "99", "."])
        self.assertEqual(code, 2)

    def test_auto_grid_is_used_end_to_end(self):
        folder = self.workdir("auto")
        code, output = run_main([str(folder)])
        self.assertEqual(code, 0, output)
        from PIL import Image as PILImage

        from PIL import Image as PILImage

        with PILImage.open(folder / qvp.OUT_DIR_NAME / "clip_collage.jpg") as sheet:
            self.assertEqual(sheet.size, (2 * (320 + 4), 2 * (240 + 4)))  # 4 s clip -> 2x2


class GridUnitTests(unittest.TestCase):
    def test_parse_grid_accepts_every_symbol_the_docs_use(self):
        for spelling in ("4x4", "4X4", "4*4", "4x4", "4\u00d74", "4 \u00d7 4", "4,4"):
            self.assertEqual(qvp.parse_grid(spelling), (4, 4), spelling)

    def test_portrait_ladder_boundaries(self):
        portrait = qvp.auto_grid(5.0, 1080, 1920, 2, qvp.MAX_PIXELS)
        self.assertEqual(portrait, (4, 1))
        portrait = qvp.auto_grid(6.0, 1080, 1920, 2, qvp.MAX_PIXELS)
        self.assertEqual(portrait, (4, 1))
        self.assertEqual(qvp.auto_grid(7.0, 1080, 1920, 2, qvp.MAX_PIXELS), (5, 1))
        self.assertEqual(qvp.auto_grid(12.0, 1080, 1920, 2, qvp.MAX_PIXELS), (6, 1))
        self.assertEqual(qvp.auto_grid(16.0, 1080, 1920, 2, qvp.MAX_PIXELS), (4, 2))
        self.assertEqual(qvp.auto_grid(25.0, 1080, 1920, 2, qvp.MAX_PIXELS), (5, 2))
        self.assertEqual(qvp.auto_grid(37.0, 1080, 1920, 2, qvp.MAX_PIXELS), (6, 2))
        self.assertEqual(qvp.auto_grid(40.0, 1080, 1920, 2, qvp.MAX_PIXELS), (7, 2))
        self.assertEqual(qvp.auto_grid(60.0, 1080, 1920, 2, qvp.MAX_PIXELS), (7, 2))
        self.assertEqual(qvp.auto_grid(120.0, 1080, 1920, 2, qvp.MAX_PIXELS), (8, 2))
        self.assertEqual(qvp.auto_grid(600.0, 1080, 1920, 2, qvp.MAX_PIXELS), (8, 3))

    def test_landscape_ladder_is_unchanged(self):
        self.assertEqual(qvp.auto_grid(10.0, 1920, 1080, 2, qvp.MAX_PIXELS), (2, 2))
        self.assertEqual(qvp.auto_grid(600.0, 1920, 1080, 2, qvp.MAX_PIXELS), (5, 4))

    def test_portrait_pixel_budget_steps_down(self):
        grid = qvp.auto_grid(600.0, 2160, 3840, 2, 150_000_000)
        self.assertEqual(grid, (8, 2))
        layout = qvp.layout_for(2160, 3840, grid, 2)
        self.assertLessEqual(layout.pixels, 150_000_000)
        tighter = qvp.auto_grid(600.0, 2160, 3840, 2, 50_000_000)
        self.assertLess(tighter[0] * tighter[1], grid[0] * grid[1])
        self.assertLessEqual(qvp.layout_for(2160, 3840, tighter, 2).pixels, 50_000_000)

    def test_fit_frame_letterboxes_and_keeps_colour(self):
        from PIL import Image as PILImage

        tall = PILImage.new("RGB", (100, 200), "red")
        fitted = qvp.fit_frame(tall, (400, 400))
        self.assertEqual(fitted.size, (400, 400))
        self.assertEqual(fitted.getpixel((10, 10)), (0, 0, 0))
        self.assertEqual(fitted.getpixel((200, 200)), (255, 0, 0))

    def test_seek_attempts_start_fast_and_end_accurate(self):
        attempts = qvp._seek_attempts(30.0)
        self.assertEqual(attempts[0], (30.0, None))
        self.assertEqual(attempts[-1], (None, 30.0))
        self.assertGreater(len(attempts), 2)


class MixedSizeEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FFMPEG:
            raise unittest.SkipTest("ffmpeg not available")
        cls.base = Path(tempfile.mkdtemp(prefix="qvp-mixed-"))
        small = make_clip(cls.base / "small.mp4", seconds=1.0, size="640x360")
        large = make_clip(cls.base / "large.mp4", seconds=1.0, size="1280x720")
        listing = cls.base / "list.txt"
        listing.write_text(
            f"file '{small.as_posix()}'\nfile '{large.as_posix()}'\n", encoding="utf-8"
        )
        cls.spliced = cls.base / "spliced.mp4"
        # Stream copy, not the concat filter: the filter re-scales everything to
        # one size, while a copy keeps the second stream at its own resolution -
        # which is what a downloader produces when it joins two differently
        # sized parts.
        done = subprocess.run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-c",
                "copy",
                str(cls.spliced),
            ],
            capture_output=True,
        )
        if done.returncode != 0:
            raise unittest.SkipTest("cannot splice a mixed-resolution clip")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def test_spliced_720p_and_1080p_renders(self):
        folder = self.base / "run"
        folder.mkdir(exist_ok=True)
        shutil.copy(self.spliced, folder / "spliced.mp4")
        code, output = run_main([str(folder), "--frames", "4", "-f"])
        self.assertEqual(code, 0, output)
        self.assertIn("1 done", output)
        sheet = folder / qvp.OUT_DIR_NAME / "spliced_collage.jpg"
        self.assertTrue(sheet.is_file())
        from PIL import Image as PILImage

        with PILImage.open(sheet) as image:
            width, height = image.size
        cols, rows = qvp.auto_grid(2.0, 640, 360, qvp.BORDER_SIZE, qvp.MAX_PIXELS)
        self.assertEqual(width, cols * (640 + 2 * qvp.BORDER_SIZE))
        self.assertEqual(height, rows * (360 + 2 * qvp.BORDER_SIZE))

    def test_transport_stream_renders(self):
        folder = self.base / "ts"
        folder.mkdir(exist_ok=True)
        ts = folder / "clip.ts"
        done = subprocess.run(
            [FFMPEG, "-v", "error", "-y", "-i", str(self.spliced), "-c", "copy", str(ts)],
            capture_output=True,
        )
        if done.returncode != 0 or not ts.is_file():
            raise unittest.SkipTest("cannot remux to MPEG-TS")
        code, output = run_main([str(folder), "--frames", "4", "-f"])
        self.assertEqual(code, 0, output)
        self.assertIn("1 done", output)


class OutputFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FFMPEG:
            raise unittest.SkipTest("ffmpeg not available")
        cls.base = Path(tempfile.mkdtemp(prefix="qvp-format-"))
        cls.clip = make_clip(cls.base / "src" / "clip.mp4", seconds=2)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def workdir(self, name: str) -> Path:
        folder = self.base / name
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        shutil.copy(self.clip, folder / "clip.mp4")
        return folder

    def test_default_output_is_jpeg(self):
        folder = self.workdir("jpeg")
        code, output = run_main([str(folder), "--frames", "4"])
        self.assertEqual(code, 0, output)
        self.assertTrue((folder / qvp.OUT_DIR_NAME / "clip_collage.jpg").is_file())

    def test_avif_output_has_its_own_extension(self):
        from PIL import features

        if not features.check("avif"):
            self.skipTest("Pillow was built without AVIF")
        folder = self.workdir("avif")
        code, output = run_main([str(folder), "--frames", "4", "--format", "avif"])
        self.assertEqual(code, 0, output)
        sheet = folder / qvp.OUT_DIR_NAME / "clip_collage.avif"
        self.assertTrue(sheet.is_file())
        with qvp.Image.open(sheet) as image:
            self.assertEqual(
                image.size, (2 * (320 + 2 * qvp.BORDER_SIZE), 2 * (240 + 2 * qvp.BORDER_SIZE))
            )

    def test_quality_flag_is_validated(self):
        folder = self.workdir("quality")
        code, output = run_main([str(folder), "--frames", "4", "--quality", "101"])
        self.assertEqual(code, 2)
        self.assertIn("--quality must be between", output)
        code, output = run_main([str(folder), "--frames", "4", "-q", "--quality", "70"])
        self.assertEqual(code, 0, output)

    def test_bigger_default_pixel_budget(self):
        self.assertEqual(qvp.MAX_PIXELS, 320_000_000)
        layout = qvp.layout_for(3840, 2160, (5, 5), qvp.BORDER_SIZE)
        self.assertLessEqual(layout.pixels, qvp.MAX_PIXELS)

    def test_output_name_takes_a_suffix(self):
        self.assertEqual(qvp.output_name("talk", ".avif"), "talk_collage.avif")
        self.assertEqual(qvp.output_name("talk"), "talk_collage.jpg")


class AuditFixTests(unittest.TestCase):
    def test_frames_above_twenty_five_need_an_explicit_grid(self):
        code, output = run_main(["--frames", "30", "-n"])
        self.assertEqual(code, 2)
        self.assertIn("needs an explicit --grid", output)

    def test_frames_above_twenty_five_work_with_a_grid(self):
        if not FFMPEG:
            self.skipTest("ffmpeg not available")
        folder = Path(tempfile.mkdtemp(prefix="qvp-frames30-"))
        try:
            make_clip(folder / "clip.mp4", seconds=3)
            code, output = run_main([str(folder), "--frames", "30", "-g", "6x5", "-f"])
            self.assertEqual(code, 0, output)
            self.assertIn("30", output)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_os_errors_are_english(self):
        import errno

        self.assertEqual(qvp.english_oserror(OSError(errno.EACCES, "refused")), "access denied")
        self.assertEqual(
            qvp.english_oserror(OSError(errno.ENOSPC, "vol")), "no space left on the disk"
        )
        self.assertEqual(qvp.english_oserror(OSError(9999, "custom text")), "custom text")

    def test_replace_with_retry_survives_a_short_lock(self):
        import errno
        from unittest import mock

        folder = Path(tempfile.mkdtemp(prefix="qvp-replace-"))
        try:
            source = folder / "a.tmp"
            target = folder / "a.jpg"
            source.write_text("x", encoding="utf-8")
            calls = {"n": 0}
            real = qvp.os.replace

            def flaky(src, dst):
                calls["n"] += 1
                if calls["n"] < 3:
                    raise PermissionError(errno.EACCES, "busy")
                return real(src, dst)

            with mock.patch.object(qvp.os, "replace", flaky):
                qvp.replace_with_retry(source, target)
            self.assertTrue(target.is_file())
            self.assertEqual(calls["n"], 3)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_probe_falls_back_to_the_next_ffprobe(self):
        from unittest import mock

        folder = Path(tempfile.mkdtemp(prefix="qvp-probe-"))
        try:
            clip = make_clip(folder / "clip.mp4", seconds=1)
            calls = []

            def fake(path, binary):
                calls.append(binary)
                if len(calls) == 1:
                    raise qvp.ProbeError("broken build")
                return qvp.Probe(320, 240, 1.0, 10.0, "h264")

            with (
                mock.patch.object(qvp, "_probe_ffprobe", fake),
                mock.patch.object(qvp, "ffprobe_candidates", lambda explicit=None: ["a", "b"]),
            ):
                probe = qvp.probe_video(clip)
            self.assertEqual(probe.width, 320)
            self.assertEqual(calls, ["a", "b"])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_stale_temps_are_removed_old_ones_kept(self):
        import os
        import time as _time

        folder = Path(tempfile.mkdtemp(prefix="qvp-stale-"))
        try:
            output = folder / "clip_collage.jpg"
            old = folder / ".clip_collage.jpg.tmp-1111-abcdef12"
            fresh = folder / ".clip_collage.jpg.tmp-2222-abcdef34"
            other = folder / ".talk_collage.jpg.tmp-3333-abcdef56"
            for item in (old, fresh, other):
                item.write_text("x", encoding="utf-8")
            two_hours = _time.time() - 7200
            os.utime(old, (two_hours, two_hours))
            os.utime(other, (two_hours, two_hours))
            qvp.clean_stale_temps(output)
            self.assertFalse(old.exists(), "this sheet's stale temp goes")
            self.assertFalse(other.exists(), "another sheet's stale temp goes too")
            self.assertTrue(fresh.exists(), "a recent temp is left alone")
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class SecondAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FFMPEG:
            raise unittest.SkipTest("ffmpeg not available")
        cls.base = Path(tempfile.mkdtemp(prefix="qvp-audit2-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def test_rotated_video_is_probed_upright(self):
        source = make_clip(self.base / "plain.mp4", seconds=1, size="320x180")
        rotated = self.base / "rotated.mp4"
        done = subprocess.run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-display_rotation",
                "90",
                "-i",
                str(source),
                "-c",
                "copy",
                str(rotated),
            ],
            capture_output=True,
        )
        if done.returncode != 0 or not rotated.is_file():
            self.skipTest("ffmpeg cannot set display rotation here")
        probe = qvp.probe_video(rotated)
        self.assertEqual((probe.width, probe.height), (180, 320))

    def test_rotated_video_renders_with_the_upright_grid(self):
        source = make_clip(self.base / "plain2.mp4", seconds=1, size="320x180")
        rotated = self.base / "rotated2.mp4"
        done = subprocess.run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-display_rotation",
                "90",
                "-i",
                str(source),
                "-c",
                "copy",
                str(rotated),
            ],
            capture_output=True,
        )
        if done.returncode != 0 or not rotated.is_file():
            self.skipTest("ffmpeg cannot set display rotation here")
        folder = self.base / "rot-run"
        folder.mkdir(exist_ok=True)
        shutil.copy(rotated, folder / "rotated2.mp4")
        code, output = run_main([str(folder), "-f", "--frames", "4"])
        self.assertEqual(code, 0, output)
        from PIL import Image as PILImage

        with PILImage.open(folder / qvp.OUT_DIR_NAME / "rotated2_collage.jpg") as sheet:
            cols, rows = qvp.grid_for_frames(4)  # --frames 4 overrides the ladder
            self.assertEqual(
                sheet.size, (cols * (180 + 2 * qvp.BORDER_SIZE), rows * (320 + 2 * qvp.BORDER_SIZE))
            )

    def test_run_tool_tracks_and_clears_processes(self):
        import sys as _sys

        code, out, err = qvp.run_tool([_sys.executable, "-c", "print('ok')"], 30)
        self.assertEqual(code, 0)
        self.assertIn(b"ok", out)
        self.assertEqual(qvp._RUNNING, set())

    def test_redirected_output_keeps_emoji_names(self):
        folder = self.base / "emoji-out"
        folder.mkdir(exist_ok=True)
        shutil.copy(make_clip(self.base / "emoji-src.mp4", seconds=1), folder / "🎬 clip.mp4")
        code, output = run_main([str(folder), "-f", "--frames", "4"])
        self.assertEqual(code, 0, output)
        self.assertIn("🎬 clip.mp4", output)

    def test_infinite_duration_is_rejected(self):
        with self.assertRaises(qvp.ProbeError):
            qvp.sample_times(float("inf"), 3)
        with self.assertRaises(qvp.ProbeError):
            qvp.sample_times(0.0, 3)

    def test_non_ascii_digits_are_not_a_grid(self):
        with self.assertRaises(qvp.UsageError):
            qvp.parse_grid("\u00b2x\u00b2")


class WorkerBudgetTests(unittest.TestCase):
    def test_jobs_share_the_budget_instead_of_multiplying_it(self):
        import os as _os

        cpu = _os.cpu_count() or 1
        total = max(1, min(qvp.MAX_DECODE_WORKERS, cpu // 4))
        self.assertEqual(qvp.worker_budget(1), total)
        self.assertEqual(qvp.worker_budget(4), max(1, total // 4))
        self.assertGreaterEqual(qvp.worker_budget(64), 1)

    def test_requested_budget_is_shared_too(self):
        self.assertEqual(qvp.worker_budget(1, requested=4), 4)
        self.assertEqual(qvp.worker_budget(4, requested=4), 1)
        self.assertEqual(qvp.worker_budget(2, requested=4), 2)


class InterruptTests(unittest.TestCase):
    def job(self, name: str) -> "qvp.Job":
        probe = qvp.Probe(320, 240, 1.0, 10.0, "h264")
        layout = qvp.layout_for(320, 240, (2, 2), qvp.BORDER_SIZE)
        return qvp.Job(Path(name), Path(name + ".jpg"), probe, layout, (0.2, 0.6, 0.9, 1.0))

    def test_interrupt_on_the_sequential_path_stops_children(self):
        from unittest import mock

        killed = []
        opts = qvp.Options(paths=[Path(".")], jobs=1, quiet=True)
        with (
            mock.patch.object(qvp, "render_job", side_effect=KeyboardInterrupt),
            mock.patch.object(qvp, "kill_running", lambda: killed.append(True)),
        ):
            with self.assertRaises(KeyboardInterrupt):
                qvp.render_all([self.job("a.mp4")], opts)
        self.assertEqual(killed, [True])

    def test_interrupt_on_the_parallel_path_stops_children(self):
        from unittest import mock

        killed = []
        opts = qvp.Options(paths=[Path(".")], jobs=2, quiet=True)
        with (
            mock.patch.object(qvp, "render_job", side_effect=KeyboardInterrupt),
            mock.patch.object(qvp, "kill_running", lambda: killed.append(True)),
        ):
            with self.assertRaises(KeyboardInterrupt):
                qvp.render_all([self.job("a.mp4"), self.job("b.mp4")], opts)
        self.assertEqual(killed, [True])


class ToolRunTests(unittest.TestCase):
    def test_run_tool_stops_when_the_user_interrupts(self):
        timer = threading.Timer(0.6, _thread.interrupt_main)
        timer.start()
        started = time.perf_counter()
        try:
            with self.assertRaises(KeyboardInterrupt):
                qvp.run_tool([sys.executable, "-c", "import time; time.sleep(5)"], 30)
        finally:
            timer.cancel()
        self.assertLess(
            time.perf_counter() - started, 3.0, "waited for the child instead of polling"
        )
        qvp.kill_running()
        self.assertEqual(len(qvp._RUNNING), 0, "the child was left registered")

    def test_a_queued_tool_does_not_start_after_the_interrupt(self):
        qvp.configure_decode_budget(1)
        started = []
        holder = threading.Thread(
            target=qvp.run_tool,
            args=([sys.executable, "-c", "import time; time.sleep(1.5)"], 30),
        )
        holder.start()
        time.sleep(0.4)
        qvp.kill_running()
        try:
            with self.assertRaises(qvp.FrameError):
                qvp.run_tool([sys.executable, "-c", "open('should_not_exist.txt','w')"], 30)
            self.assertFalse(Path("should_not_exist.txt").exists())
        finally:
            holder.join(10)
            started.clear()
        self.assertFalse(
            qvp._CANCELLED.is_set() is False, "the cancel flag should be set until the next run"
        )
        qvp.configure_decode_budget(qvp.decode_budget())

    def test_decode_budget_caps_concurrent_tools(self):
        live = {"now": 0, "peak": 0}
        guard = threading.Lock()

        class Stub:
            def __init__(self, command, **kwargs):
                self.done = False
                self.returncode = 0
                with guard:
                    live["now"] += 1
                    live["peak"] = max(live["peak"], live["now"])

            def communicate(self, timeout=None):
                time.sleep(0.05)
                self.finish()
                return b"", b""

            def kill(self):
                pass

            def finish(self):
                if not self.done:
                    self.done = True
                    with guard:
                        live["now"] -= 1

            def poll(self):
                return None

        qvp.configure_decode_budget(2)
        try:
            with mock.patch.object(qvp.subprocess, "Popen", Stub):
                threads = [
                    threading.Thread(target=qvp.run_tool, args=(["ffmpeg", "-version"], 10))
                    for _ in range(6)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(30)
        finally:
            qvp.configure_decode_budget(qvp.decode_budget())
        self.assertLessEqual(live["peak"], 2, "more decoders ran than the run allows")

    def test_one_video_with_jobs_four_still_gets_the_whole_budget(self):
        self.assertEqual(qvp.worker_budget(1), qvp.decode_budget())
        self.assertEqual(qvp.worker_budget(1, 4), 4)


class RotationMetadataTests(unittest.TestCase):
    def test_unreadable_rotation_counts_as_none(self):
        for raw in ("abc", "", None, object(), "inf", float("inf"), float("-inf"), 10**400):
            self.assertEqual(qvp._rotation_value(raw), 0, raw)
        self.assertEqual(qvp._rotation_value("90"), 90)
        self.assertEqual(qvp._rotation_value(270.0), 270)

    def test_rotation_comes_from_side_data_and_swaps_the_probe(self):
        folder = Path(tempfile.mkdtemp(prefix="qvp-rot-"))
        self.addCleanup(shutil.rmtree, folder, True)
        source = folder / "clip.mp4"
        make_clip(source, seconds=3)
        turned = folder / "turned.mp4"
        result = subprocess.run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-display_rotation",
                "90",
                "-i",
                str(source),
                "-c",
                "copy",
                str(turned),
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            self.skipTest("ffmpeg cannot write display rotation here")
        probe = qvp.probe_video(turned, FFMPEG)
        raw = json.loads(
            subprocess.run(
                [
                    qvp.ffprobe_candidates()[0],
                    "-v",
                    "error",
                    "-print_format",
                    "json",
                    "-show_streams",
                    "-show_entries",
                    "stream=width,height:stream_side_data=rotation",
                    str(turned),
                ],
                capture_output=True,
                text=True,
            ).stdout
        )["streams"][0]
        self.assertEqual((probe.width, probe.height), (int(raw["height"]), int(raw["width"])))


def _swap_for_rotation(stream: dict) -> tuple[int, int]:
    rotation = 0
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            rotation = qvp._rotation_value(side["rotation"])
    if not rotation:
        tags = {str(key).lower(): value for key, value in (stream.get("tags") or {}).items()}
        rotation = qvp._rotation_value(tags.get("rotate"))
    width, height = int(stream["width"]), int(stream["height"])
    if rotation % 180 == 90:
        return height, width
    return width, height


if __name__ == "__main__":
    unittest.main()
