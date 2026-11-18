"""Tests for qvp_online: the network-facing sibling of qvp.py.

The end-to-end cases serve a local file over HTTP with Range support, so the
seek path is exercised for real without touching the internet. The yt-dlp path
is exercised with a stub that prints the JSON yt-dlp prints.
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import qvp_online  # noqa: E402
from qvp_online import Source  # noqa: E402

FFMPEG = (qvp_online.qvp.ffmpeg_candidates() or [None])[0]
FFPROBE = (qvp_online.qvp.ffprobe_candidates() or [None])[0]


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    """Serves files with Range support, which ffmpeg needs for a fast seek."""

    def log_message(self, *args):  # keep the test output readable
        pass

    def do_GET(self):
        path = self.translate_path(self.path.split("?")[0])
        if not os.path.isfile(path):
            self.send_error(404)
            return
        size = os.path.getsize(path)
        match = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        start, end, status = 0, size - 1, 200
        if match:
            start = int(match.group(1) or 0)
            if match.group(2):
                end = min(int(match.group(2)), size - 1)
            status = 206
        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(path, "rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(65536, remaining))
                if not chunk:
                    return
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)


class OnlineTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FFMPEG or not FFPROBE:
            raise unittest.SkipTest("ffmpeg/ffprobe not available")
        cls.temp = Path(tempfile.mkdtemp(prefix="qvp-online-test-"))
        cls.clip = cls.temp / "clip.mp4"
        subprocess.run(
            [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x2b5d8c:s=640x360:d=40",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(cls.clip)],
            check=True,
        )
        handler = functools.partial(RangeHandler, directory=str(cls.temp))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.port}/clip.mp4"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        shutil.rmtree(cls.temp, ignore_errors=True)

    def workspace(self) -> Path:
        folder = Path(tempfile.mkdtemp(prefix="qvp-online-case-"))
        self.addCleanup(shutil.rmtree, folder, True)
        return folder

    def run_tool(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT / "qvp_online.py"), *arguments],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )


class UnitTests(unittest.TestCase):
    def test_safe_name_strips_media_suffix_and_illegal_characters(self):
        self.assertEqual(qvp_online.safe_name("talk.mp4"), "talk")
        self.assertEqual(qvp_online.safe_name('a/b:c*?"<>|d.mkv'), "a b c d")
        self.assertEqual(qvp_online.safe_name("   "), "video")
        self.assertLessEqual(len(qvp_online.safe_name("x" * 500)), 120)

    def test_headers_block_terminates_every_line_with_crlf(self):
        block = qvp_online.headers_block({"Referer": "https://example.test/", "User-Agent": "UA"})
        self.assertEqual(block, "Referer: https://example.test/\r\nUser-Agent: UA\r\n")
        self.assertTrue(block.endswith("\r\n"))

    def test_expired_markers(self):
        self.assertTrue(qvp_online.looks_expired("HTTP error 403 Forbidden"))
        self.assertTrue(qvp_online.looks_expired("Server returned 410 Gone"))
        self.assertFalse(qvp_online.looks_expired("moov atom not found"))

    def test_pick_format_prefers_video_only_within_height(self):
        info = {
            "formats": [
                {"format_id": "hls", "url": "https://x/master.m3u8", "protocol": "m3u8_native", "vcodec": "avc1"},
                {"format_id": "360", "url": "https://x/360.mp4", "protocol": "https", "vcodec": "avc1",
                 "acodec": "mp4a", "height": 360},
                {"format_id": "480v", "url": "https://x/480.mp4", "protocol": "https", "vcodec": "avc1",
                 "acodec": "none", "height": 480},
                {"format_id": "1080v", "url": "https://x/1080.mp4", "protocol": "https", "vcodec": "avc1",
                 "acodec": "none", "height": 1080},
            ]
        }
        self.assertEqual(qvp_online.pick_format(info, None, 720)["format_id"], "480v")
        self.assertEqual(qvp_online.pick_format(info, "360", 720)["format_id"], "360")
        with self.assertRaises(qvp_online.ResolveError):
            qvp_online.pick_format(info, "nope", 720)

    def test_pick_format_refuses_manifests_only(self):
        info = {"formats": [{"format_id": "1", "url": "https://x/a.m3u8", "protocol": "m3u8_native", "vcodec": "avc1"}]}
        with self.assertRaises(qvp_online.ResolveError):
            qvp_online.pick_format(info, None, 720)

    def test_source_from_info_adds_a_referer_for_bilibili(self):
        info = {
            "title": "示例标题",
            "duration": 100.0,
            "extractor_key": "BiliBili",
            "http_headers": {"User-Agent": "UA-from-site"},
            "formats": [],
        }
        chosen = {"url": "https://cdn/x.mp4", "width": 1280, "height": 720, "fps": 30, "vcodec": "avc1"}
        source = qvp_online.source_from_info(info, chosen, "fallback")
        self.assertEqual(source.headers["Referer"], "https://www.bilibili.com/")
        self.assertEqual(source.headers["User-Agent"], "UA-from-site")
        self.assertEqual((source.width, source.height), (1280, 720))
        self.assertAlmostEqual(source.duration, 100.0)
        self.assertEqual(source.safe_name, "示例标题")

    def test_source_from_info_rejects_incomplete_metadata(self):
        with self.assertRaises(qvp_online.ResolveError):
            qvp_online.source_from_info({"duration": 0}, {"url": "u", "width": 1, "height": 1}, "t")

    def test_split_command_keeps_quoted_paths(self):
        self.assertEqual(qvp_online.split_command('python "C:\\tools\\fake ytdlp.py"'), ["python", "C:\\tools\\fake ytdlp.py"])

    def test_frame_command_seeks_before_input_unless_accurate(self):
        source = Source("t", "https://x/a.mp4", 640, 360, 10.0, 30.0, headers={"Referer": "r"})
        fast = qvp_online.frame_command("ffmpeg", source, 5.0, accurate=False)
        slow = qvp_online.frame_command("ffmpeg", source, 5.0, accurate=True)
        self.assertLess(fast.index("-ss"), fast.index("-i"))
        self.assertGreater(slow.index("-ss"), slow.index("-i"))
        self.assertIn("Referer: r\r\n", fast)

    def test_frame_source_resolves_again_when_the_url_expires(self):
        source = Source("t", "https://x/a.mp4", 8, 4, 10.0, 30.0)
        calls = {"fetch": 0, "decide": 0}

        def decide(_url):
            calls["decide"] += 1
            return source

        def fake_fetch(_ffmpeg, _source, _moment, accurate=False):
            calls["fetch"] += 1
            if calls["fetch"] == 1:
                raise qvp_online.Expired("403")
            return b"\x00" * (8 * 4 * 3)

        args = mock.Mock(ffmpeg="ffmpeg", url="https://x/page")
        with mock.patch.object(qvp_online, "fetch_frame", fake_fetch):
            frames = qvp_online.FrameSource(args, decide, "https://x/page")
            payload = frames.frame(3.0)
        self.assertEqual(len(payload), 8 * 4 * 3)
        self.assertEqual(frames.resolves, 1, "a refused URL is resolved again immediately")

        calls["fetch"] = 0

        def always_expired(_ffmpeg, _source, _moment, accurate=False):
            calls["fetch"] += 1
            if calls["fetch"] <= 2:
                raise qvp_online.Expired("403")
            return b"\x01" * (8 * 4 * 3)

        with mock.patch.object(qvp_online, "fetch_frame", always_expired):
            frames = qvp_online.FrameSource(args, decide, "https://x/page")
            payload = frames.frame(3.0)
        self.assertEqual(frames.resolves, 1)
        self.assertEqual(len(payload), 8 * 4 * 3)


class EndToEndTests(OnlineTestCase):
    def test_direct_url_produces_a_sheet(self):
        out = self.workspace()
        result = self.run_tool("--direct", "-o", str(out), self.url)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        sheet = next(out.glob("*_collage.jpg"))
        self.assertGreater(sheet.stat().st_size, 1000)
        self.assertIn("3x2", result.stdout, "a 40 s clip should pick a 3x2 sheet")

    def test_dry_run_writes_nothing(self):
        out = self.workspace()
        result = self.run_tool("--direct", "-n", "-o", str(out), self.url)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(list(out.glob("*")), [])
        self.assertIn("would write", result.stdout)

    def test_existing_sheet_is_skipped_without_force(self):
        out = self.workspace()
        first = self.run_tool("--direct", "-o", str(out), self.url)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self.run_tool("--direct", "-o", str(out), self.url)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("skipped", second.stdout)

    def test_ytdlp_json_path_is_used(self):
        out = self.workspace()
        stub = out / "fake_ytdlp.py"
        payload = {
            "title": "stub title",
            "duration": 40.0,
            "extractor_key": "Generic",
            "http_headers": {"User-Agent": "stub-agent"},
            "formats": [
                {"format_id": "hls", "url": self.url.replace(".mp4", ".m3u8"), "protocol": "m3u8_native",
                 "vcodec": "avc1", "height": 360},
                {"format_id": "v360", "url": self.url, "protocol": "https", "vcodec": "avc1",
                 "acodec": "none", "width": 640, "height": 360, "fps": 30},
            ],
        }
        stub.write_text(
            "import json, sys\n" + f"print(json.dumps({payload!r}))\n", encoding="utf-8"
        )
        result = self.run_tool(
            "-o", str(out), "--yt-dlp", f'{sys.executable} "{stub}"', self.url
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        sheet = next(out.glob("*_collage.jpg"))
        self.assertIn("stub title", sheet.name)
        probe = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(sheet)],
            capture_output=True, text=True,
        )
        width, height = (int(part) for part in probe.stdout.strip().split(","))
        # 3x2 grid of 640x360 cells, 2 px border inside and outside each cell.
        self.assertEqual((width, height), (3 * 644, 2 * 364))

    def test_bad_url_fails_without_traceback(self):
        out = self.workspace()
        result = self.run_tool("--direct", "-o", str(out), f"http://127.0.0.1:{self.port}/missing.mp4")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("failed", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
