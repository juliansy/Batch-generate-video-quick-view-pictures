"""Tests for the aria2 JSON-RPC source.

A local fake RPC server returns the payloads aria2 returns, so the grouping and
filtering logic is exercised without an aria2 install.
"""

from __future__ import annotations

import http.server
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import qvp  # noqa: E402

FFMPEG = (qvp.ffmpeg_candidates() or [None])[0]
FFPROBE = (qvp.ffprobe_candidates() or [None])[0]


class FakeAria2(http.server.BaseHTTPRequestHandler):
    statuses: list[dict] = []
    secret: str | None = None
    calls: list[str] = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        method = payload.get("method")
        params = payload.get("params") or []
        FakeAria2.calls.append(method)
        if FakeAria2.secret is not None:
            if not params or params[0] != f"token:{FakeAria2.secret}":
                return self.reply({"jsonrpc": "2.0", "id": "qvp", "error": {"code": 1, "message": "Unauthorized"}})
        if method == "aria2.tellStopped":
            return self.reply({"jsonrpc": "2.0", "id": "qvp", "result": FakeAria2.statuses})
        if method == "aria2.tellStatus":
            gid = params[-2] if len(params) >= 2 else ""
            for status in FakeAria2.statuses:
                if status["gid"] == gid:
                    return self.reply({"jsonrpc": "2.0", "id": "qvp", "result": status})
            return self.reply({"jsonrpc": "2.0", "id": "qvp", "error": {"code": 3, "message": "GID not found"}})
        return self.reply({"jsonrpc": "2.0", "id": "qvp", "error": {"code": -32601, "message": "no such method"}})

    def reply(self, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FakeServerMixin:
    @classmethod
    def start_server(cls) -> None:
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeAria2)
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_address[1]}/jsonrpc"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def stop_server(cls) -> None:
        cls.server.shutdown()


class FilteringTests(unittest.TestCase, FakeServerMixin):
    @classmethod
    def setUpClass(cls):
        cls.start_server()

    @classmethod
    def tearDownClass(cls):
        cls.stop_server()

    def setUp(self):
        FakeAria2.secret = None
        FakeAria2.calls.clear()
        self.temp = Path(tempfile.mkdtemp(prefix="qvp-aria2-case-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        video = self.temp / "talk.mp4"
        audio = self.temp / "talk.m4a"
        cover = self.temp / "talk.jpg"
        for path in (video, audio, cover):
            path.write_bytes(b"x")
        FakeAria2.statuses = [
            {"gid": "0" * 16, "status": "complete", "dir": str(self.temp),
             "files": [{"path": str(video)}, {"path": str(audio)}, {"path": str(cover)}]},
            {"gid": "1" * 16, "status": "error", "dir": str(self.temp), "files": [{"path": str(video)}]},
            {"gid": "2" * 16, "status": "complete", "dir": str(self.temp), "files": [{"path": str(audio)}]},
        ]

    def test_only_completed_video_files_are_taken(self):
        found = qvp.aria2_videos(self.endpoint, None, None, 100)
        self.assertEqual([path.name for path in found], ["talk.mp4"])

    def test_duplicates_are_dropped(self):
        video = self.temp / "talk.mp4"
        FakeAria2.statuses.append(
            {"gid": "3" * 16, "status": "complete", "dir": str(self.temp), "files": [{"path": str(video)}]}
        )
        found = qvp.aria2_videos(self.endpoint, None, None, 100)
        self.assertEqual(len(found), 1)

    def test_gid_lookup(self):
        found = qvp.aria2_videos(self.endpoint, None, "0" * 16, 100)
        self.assertEqual([path.name for path in found], ["talk.mp4"])

    def test_secret_is_sent_and_enforced(self):
        FakeAria2.secret = "s3cret"
        with self.assertRaises(qvp.UsageError):
            qvp.aria2_videos(self.endpoint, None, None, 100)
        found = qvp.aria2_videos(self.endpoint, "s3cret", None, 100)
        self.assertEqual(len(found), 1)

    def test_unreachable_endpoint_becomes_a_usage_error(self):
        with self.assertRaises(qvp.UsageError) as raised:
            qvp.aria2_videos("http://127.0.0.1:9/jsonrpc", None, None, 10)
        self.assertIn("cannot reach aria2", str(raised.exception))

    def test_bad_gid_is_rejected_by_the_cli(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "qvp.py"), "--aria2", self.endpoint, "--aria2-gid", "not-a-gid"],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("16 character hex gid", result.stderr)


class EndToEndTests(unittest.TestCase, FakeServerMixin):
    @classmethod
    def setUpClass(cls):
        if not FFMPEG or not FFPROBE:
            raise unittest.SkipTest("ffmpeg/ffprobe not available")
        cls.start_server()
        cls.temp = Path(tempfile.mkdtemp(prefix="qvp-aria2-e2e-"))
        cls.video = cls.temp / "clip.mp4"
        subprocess.run(
            [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x223344:s=640x360:d=24",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(cls.video)],
            check=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.stop_server()
        shutil.rmtree(cls.temp, ignore_errors=True)

    def setUp(self):
        FakeAria2.secret = None
        FakeAria2.statuses = [
            {"gid": "a" * 16, "status": "complete", "dir": str(self.temp),
             "files": [{"path": str(self.video)}, {"path": str(self.temp / "clip.m4a")}]},
        ]

    def run_tool(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT / "qvp.py"), *arguments],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180,
        )

    def out_dir(self) -> Path:
        folder = Path(tempfile.mkdtemp(prefix="qvp-aria2-out-"))
        self.addCleanup(shutil.rmtree, folder, True)
        return folder

    def test_dry_run_lists_the_aria2_video_and_writes_nothing(self):
        out = self.out_dir()
        result = self.run_tool("--aria2", self.endpoint, "-n", "-o", str(out))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("from aria2", result.stdout)
        self.assertIn("would write", result.stdout)
        self.assertEqual(list(out.glob("*")), [])
        self.assertIn("aria2.tellStopped", FakeAria2.calls)

    def test_real_render_of_an_aria2_video(self):
        out = self.out_dir()
        result = self.run_tool("--aria2", self.endpoint, "-o", str(out), "-g", "2x2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(list(out.glob("*_collage.jpg"))), 1)

    def test_gid_mode(self):
        out = self.out_dir()
        result = self.run_tool("--aria2-gid", "a" * 16, "--aria2", self.endpoint, "-o", str(out), "-g", "2x2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("aria2.tellStatus", FakeAria2.calls)

    def test_hook_mode_reads_the_gid_aria2_appends(self):
        out = self.out_dir()
        result = self.run_tool(
            "--aria2-hook", "--aria2", self.endpoint, "-o", str(out), "-g", "2x2",
            "a" * 16, "2", str(self.video),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("aria2.tellStatus", FakeAria2.calls)

    def test_unreachable_aria2_exits_two_without_a_traceback(self):
        result = self.run_tool("--aria2", "http://127.0.0.1:9/jsonrpc")
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot reach aria2", result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
