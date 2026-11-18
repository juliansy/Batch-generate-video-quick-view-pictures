#!/usr/bin/env python3
"""Quick-view sheets for online videos, without downloading them first.

This is the sibling of `qvp.py`: the local tool reads a file, this one reads a
URL. It asks `yt-dlp` for the direct stream URL, then lets ffmpeg seek inside
the remote stream and hand back one frame per sample point. With HTTP Range
support - which the large hosts have - a 25-cell sheet transfers a few tens of
megabytes instead of the whole video.

Two things differ from the local tool, and both are about the network:

* the direct URL is signed and expires (an hour or two). A frame that fails is
  retried with an exact seek first, and only then with a freshly resolved URL,
  so one expiry costs one extra resolve rather than the whole job.
* every frame pays a connection, a probe and a decode from the previous
  keyframe, so frames are fetched in parallel and `--frame-workers` controls how
  many. Few cells: seeking is cheaper than downloading. Many cells: see
  `docs/09-online.md` for the crossover.

Usage:
    python qvp_online.py "https://www.bilibili.com/video/BV..."
    python qvp_online.py -g 4x4 --frame-workers 6 URL1 URL2
    python qvp_online.py --cookies cookies.txt URL
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import qvp
from qvp import Probe, Result, short_error

VERSION = "1.0.0"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
DEFAULT_FRAME_WORKERS = 4
MAX_FRAME_WORKERS = 8
FRAME_TIMEOUT = 90.0
RESOLVE_TIMEOUT = 120.0
PROBE_TIMEOUT = 60.0
# Answers that mean "the signed URL stopped working", not "this frame is broken".
EXPIRED_MARKERS = ("403", "410", "401", "forbidden", "expired", "signature", "unauthorized")
DEFAULT_REFERER = {"bilibili": "https://www.bilibili.com/", "youtube": "https://www.youtube.com/"}


class OnlineError(RuntimeError):
    """Anything that stops one URL from producing a sheet."""


class ResolveError(OnlineError):
    """yt-dlp or the probe could not describe the media."""


class Expired(OnlineError):
    """The signed URL stopped working; resolve it again."""


@dataclass(frozen=True)
class Source:
    title: str
    url: str
    width: int
    height: int
    duration: float
    fps: float = 0.0
    codec: str = ""
    extractor: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def probe(self) -> Probe:
        return Probe(self.width, self.height, self.duration, self.fps, self.codec)

    @property
    def safe_name(self) -> str:
        return safe_name(self.title or Path(self.url).name or "video")


@dataclass(frozen=True)
class SheetSettings:
    """The two fields `qvp.save_sheet()` reads."""

    image_format: str = "jpeg"
    quality: int = 0


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def safe_name(title: str) -> str:
    """A file name that survives Windows, macOS and Linux, for any title."""
    lowered = title.lower()
    for suffix in qvp.VIDEO_SUFFIXES:
        if lowered.endswith(suffix):
            title = title[: -len(suffix)]
            break
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return (cleaned or "video")[:120]


def split_command(text: str) -> list[str]:
    """`--yt-dlp "python C:\\tools\\fake.py"` -> ['python', 'C:\\tools\\fake.py']."""
    return [part.strip('"') for part in shlex.split(text, posix=False) if part.strip('"').strip()]


def headers_block(headers: dict[str, str]) -> str:
    """ffmpeg's `-headers` wants CRLF after every line, including the last."""
    return "".join(f"{key}: {value}\r\n" for key, value in headers.items())


def looks_expired(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in EXPIRED_MARKERS)


def parse_rate(text: object) -> float:
    try:
        numerator, denominator = str(text).split("/")
        value = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError, TypeError):
        return 0.0
    return value if value > 0 else 0.0


def pick_format(info: dict, selector: str | None, max_height: int) -> dict:
    """Prefer a video-only stream: frames do not need audio, and it is smaller."""
    formats = [item for item in info.get("formats") or [] if item.get("url")]
    if not formats:
        raise ResolveError("the site returned no downloadable format")
    if selector:
        for item in formats:
            if str(item.get("format_id")) == selector.strip():
                return item
        raise ResolveError(f"no format with id {selector!r}")

    usable = [
        item
        for item in formats
        if str(item.get("protocol", "https")) in ("http", "https")
        and str(item.get("vcodec", "none")) not in ("none", "")
    ]
    if not usable:
        raise ResolveError("every format is a manifest (HLS/DASH) ffmpeg cannot seek in")
    within = [item for item in usable if 0 < int(item.get("height") or 0) <= max_height] or usable
    video_only = [item for item in within if str(item.get("acodec", "none")) == "none"]
    pool = video_only or within
    return max(pool, key=lambda item: (int(item.get("height") or 0), int(item.get("tbr") or 0)))


def source_from_info(info: dict, chosen: dict, fallback_title: str) -> Source:
    width = int(chosen.get("width") or info.get("width") or 0)
    height = int(chosen.get("height") or info.get("height") or 0)
    duration = float(info.get("duration") or chosen.get("duration") or 0.0)
    if width <= 0 or height <= 0:
        raise ResolveError("the response did not include the picture size")
    if duration <= 0:
        raise ResolveError("the response did not include the duration")

    headers = {str(k): str(v) for k, v in (info.get("http_headers") or {}).items()}
    headers.update({str(k): str(v) for k, v in (chosen.get("http_headers") or {}).items()})
    headers.setdefault("User-Agent", DEFAULT_USER_AGENT)
    extractor = str(info.get("extractor_key") or info.get("extractor") or "").lower()
    for key, referer in DEFAULT_REFERER.items():
        if key in extractor:
            headers.setdefault("Referer", referer)
            break
    return Source(
        title=str(info.get("title") or fallback_title),
        url=str(chosen["url"]),
        width=width,
        height=height,
        duration=duration,
        fps=parse_rate(chosen.get("fps") or info.get("fps")),
        codec=str(chosen.get("vcodec") or ""),
        extractor=extractor,
        headers=headers,
    )


# --------------------------------------------------------------------------
# resolving
# --------------------------------------------------------------------------


def run_ytdlp(command: list[str], url: str) -> dict:
    line = [*command, "--ignore-config", "--no-warnings", "--no-playlist", "-J", url]
    try:
        result = subprocess.run(
            line,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=RESOLVE_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise ResolveError(f"cannot run {command[0]!r}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ResolveError(f"yt-dlp did not answer within {RESOLVE_TIMEOUT:.0f}s") from exc
    if result.returncode != 0:
        lines = [line for line in (result.stderr or "").strip().splitlines() if line.strip()]
        detail = lines[-1] if lines else f"exit code {result.returncode}"
        raise ResolveError(f"yt-dlp: {short_error(RuntimeError(detail), 160)}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ResolveError(f"yt-dlp returned something that is not JSON ({exc})") from exc


def probe_direct(ffprobe: list[str], url: str, headers: dict[str, str]) -> Source:
    command = [*ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
    if headers:
        command += ["-headers", headers_block(headers)]
    command.append(url)
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=PROBE_TIMEOUT
        )
    except subprocess.TimeoutExpired as exc:
        raise ResolveError("ffprobe did not answer in time") from exc
    except FileNotFoundError as exc:
        raise ResolveError(f"cannot run ffprobe: {exc}") from exc
    if result.returncode != 0:
        raise ResolveError(f"ffprobe: {short_error(RuntimeError(result.stderr.strip()), 160)}")

    payload = json.loads(result.stdout or "{}")
    video = next(
        (stream for stream in payload.get("streams") or [] if stream.get("codec_type") == "video"), None
    )
    if not video:
        raise ResolveError("this URL has no video stream")
    duration = float((payload.get("format") or {}).get("duration") or video.get("duration") or 0.0)
    if duration <= 0 or int(video.get("width") or 0) <= 0:
        raise ResolveError("ffprobe could not read the duration or the picture size")
    return Source(
        title=Path(url.split("?")[0]).name or "online video",
        url=url,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        duration=duration,
        fps=parse_rate(video.get("avg_frame_rate")),
        codec=str(video.get("codec_name") or ""),
        headers=headers,
    )


def resolve(args: argparse.Namespace, ffprobe: list[str], url: str) -> Source:
    if args.direct:
        headers = {}
        if args.user_agent:
            headers["User-Agent"] = args.user_agent
        if args.referer:
            headers["Referer"] = args.referer
        return probe_direct(ffprobe, url, headers)

    command = split_command(args.yt_dlp)
    for flag, value in (
        ("--cookies", args.cookies),
        ("--user-agent", args.user_agent),
        ("--referer", args.referer),
    ):
        if value:
            command += [flag, value]
    info = run_ytdlp(command, url)
    source = source_from_info(info, pick_format(info, args.format_id, args.max_height), url)
    overrides = {}
    if args.user_agent:
        overrides["User-Agent"] = args.user_agent
    if args.referer:
        overrides["Referer"] = args.referer
    if overrides:
        source = dataclasses.replace(source, headers={**source.headers, **overrides})
    return source


# --------------------------------------------------------------------------
# frames
# --------------------------------------------------------------------------


def frame_command(ffmpeg: str, source: Source, moment: float, accurate: bool) -> list[str]:
    """`-ss` before `-i` seeks fast; after `-i` it decodes to the exact frame."""
    command = [ffmpeg, "-nostdin", "-v", "error"]
    if source.headers:
        command += ["-headers", headers_block(source.headers)]
    command += ["-user_agent", source.headers.get("User-Agent", DEFAULT_USER_AGENT)]
    if accurate:
        command += ["-i", source.url, "-ss", f"{moment:.3f}"]
    else:
        command += ["-ss", f"{moment:.3f}", "-i", source.url]
    return [*command, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]


def fetch_frame(ffmpeg: str, source: Source, moment: float, accurate: bool = False) -> bytes:
    expected = source.width * source.height * 3
    try:
        result = subprocess.run(
            frame_command(ffmpeg, source, moment, accurate), capture_output=True, timeout=FRAME_TIMEOUT
        )
    except subprocess.TimeoutExpired as exc:
        raise Expired(f"no answer for {moment:.1f}s within {FRAME_TIMEOUT:.0f}s") from exc
    if len(result.stdout) == expected:
        return result.stdout
    stderr = result.stderr.decode("utf-8", "replace")
    if looks_expired(stderr):
        raise Expired("the stream URL was refused (403 or expired)")
    reason = short_error(RuntimeError(stderr.strip() or f"exit code {result.returncode}"), 120)
    raise OnlineError(f"frame at {moment:.1f}s: {reason}")


class FrameSource:
    """Frames for one URL; re-resolves the signed URL when it stops working."""

    def __init__(self, args: argparse.Namespace, decide, url: str) -> None:
        self.args = args
        self.decide = decide
        self.url = url
        self.source = decide(url)
        self.lock = threading.Lock()
        self.resolves = 0
        self.accurate_retries = 0

    def refresh(self) -> None:
        with self.lock:
            self.resolves += 1
            self.source = self.decide(self.url)

    def frame(self, moment: float) -> bytes:
        try:
            return fetch_frame(self.args.ffmpeg, self.source, moment)
        except Expired:
            # A refused URL does not get better with a slower seek.
            self.refresh()
            return self.fetch_after_refresh(moment)
        except OnlineError:
            # A failed fast seek is usually an open GOP; the exact seek reads
            # forward from the previous keyframe and lands.
            with self.lock:
                self.accurate_retries += 1
            try:
                return fetch_frame(self.args.ffmpeg, self.source, moment, accurate=True)
            except Expired:
                self.refresh()
                return self.fetch_after_refresh(moment)
            except OnlineError:
                self.refresh()
                return fetch_frame(self.args.ffmpeg, self.source, moment, accurate=True)

    def fetch_after_refresh(self, moment: float) -> bytes:
        try:
            return fetch_frame(self.args.ffmpeg, self.source, moment)
        except OnlineError:
            return fetch_frame(self.args.ffmpeg, self.source, moment, accurate=True)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def render(args: argparse.Namespace, ffprobe: list[str], url: str) -> Result:
    started = time.perf_counter()
    name = url
    temp: Path | None = None
    try:
        source = resolve(args, ffprobe, url)
        name = source.title
        grid = args.grid or qvp.auto_grid(
            source.duration, source.width, source.height, args.border, args.max_pixels
        )
        layout = qvp.layout_for(source.width, source.height, grid, args.border)
        count = args.frames or layout.cells
        if count > layout.cells:
            raise OnlineError(f"{count} frames do not fit a {layout.cols}x{layout.rows} grid")
        times = qvp.sample_times(source.duration, count, source.fps)
        output = args.out_dir / f"{source.safe_name}_collage{args.suffix}"

        if args.dry_run:
            return Result(
                name=name,
                status="planned",
                reason=f"{layout.cols}x{layout.rows}, {len(times)} frames, {source.width}x{source.height}",
                frames=len(times),
                grid=f"{layout.cols}x{layout.rows}",
                canvas=layout.canvas,
                output=output,
            )
        if output.exists() and not args.force:
            return Result(
                name=name,
                status="skipped",
                reason="already exists (use --force to overwrite)",
                output=output,
            )

        frames = FrameSource(args, lambda target: resolve(args, ffprobe, target), url)
        raw_frames: dict[int, bytes] = {}

        def fetch(index: int) -> None:
            raw_frames[index] = frames.frame(times[index])

        workers = max(1, min(args.frame_workers, len(times)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="frame") as pool:
            for future in [pool.submit(fetch, index) for index in range(len(times))]:
                future.result()

        canvas = qvp.Image.new("RGB", layout.canvas, "white")
        font = qvp.load_font(args.font_size or qvp.font_size_for(layout.cell_w), args.font)
        for index, moment in enumerate(times):
            image = qvp.Image.frombytes("RGB", (source.width, source.height), raw_frames[index])
            if image.size != (layout.cell_w - 2 * layout.border, layout.cell_h - 2 * layout.border):
                image = qvp.fit_frame(image, (layout.cell_w - 2 * layout.border, layout.cell_h - 2 * layout.border))
            qvp.stamp(image, qvp.format_timecode(moment, args.time_format), args.color, font, layout.border)
            x = (index % layout.cols) * layout.cell_w
            y = (index // layout.cols) * layout.cell_h
            canvas.paste(image, (x + layout.border, y + layout.border))

        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_name(f".{output.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
        qvp.save_sheet(canvas, temp, SheetSettings(args.image_format, args.quality))
        qvp.verify_image(temp, layout.canvas)
        os.replace(temp, output)
        temp = None

        notes = []
        if frames.resolves:
            notes.append(f"url refreshed {frames.resolves}x")
        if frames.accurate_retries:
            notes.append(f"{frames.accurate_retries} exact seek(s)")
        return Result(
            name=name,
            status="ok",
            note=", ".join(notes),
            elapsed=round(time.perf_counter() - started, 2),
            frames=len(times),
            grid=f"{layout.cols}x{layout.rows}",
            canvas=layout.canvas,
            output=output,
        )
    except (OnlineError, qvp.UsageError, qvp.ProbeError, OSError, ValueError) as exc:
        if temp is not None and temp.exists():
            temp.unlink(missing_ok=True)
        return Result(
            name=name,
            status="failed",
            reason=short_error(exc, 160),
            elapsed=round(time.perf_counter() - started, 2),
        )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qvp_online",
        description="quick-view sheets for online videos (yt-dlp + ffmpeg remote seek)",
    )
    parser.add_argument("urls", nargs="+", metavar="URL", help="video page or direct media URL")
    parser.add_argument("-o", "--out", type=Path, help=f"output folder (default: ./{qvp.OUT_DIR_NAME})")
    parser.add_argument("-g", "--grid", help="columns x rows (4x4, 4*4, 4,4), or auto")
    parser.add_argument("--frames", type=int, help="frames per sheet (default: one per cell)")
    parser.add_argument("-b", "--border", type=int, default=qvp.BORDER_SIZE, help="white border in pixels (default: 2)")
    parser.add_argument("-c", "--color", default=qvp.TEXT_COLOR, help="timecode colour (default: red)")
    parser.add_argument("--font", help="font file for the timecode")
    parser.add_argument("--font-size", type=int, help="timecode size in pixels (default: scaled to the cell)")
    parser.add_argument("--time-format", default="auto", choices=["auto", "hms", "ms"], help="timecode style")
    parser.add_argument("--max-pixels", type=int, default=qvp.MAX_PIXELS, help="refuse larger canvases")
    parser.add_argument("--format", dest="image_format", default="jpeg", choices=["jpeg", "avif"], help="sheet format")
    parser.add_argument("--quality", type=int, default=0, help="encoder quality 1-100 (default: 82 jpeg, 60 avif)")
    parser.add_argument(
        "--frame-workers",
        type=int,
        default=DEFAULT_FRAME_WORKERS,
        help=f"frames fetched in parallel, per URL (default: {DEFAULT_FRAME_WORKERS}, max {MAX_FRAME_WORKERS})",
    )
    parser.add_argument("--max-height", type=int, default=1080, help="prefer a format at or below this height")
    parser.add_argument("-f", "--format-id", help="explicit yt-dlp format id")
    parser.add_argument("--yt-dlp", default="yt-dlp", help="yt-dlp command (default: yt-dlp on PATH)")
    parser.add_argument("--ffmpeg", help="ffmpeg to use (default: first one found)")
    parser.add_argument("--ffprobe", help="ffprobe to use (default: first one found)")
    parser.add_argument("--cookies", help="cookies.txt for sites that need a login")
    parser.add_argument("--user-agent", help="override the User-Agent sent to the host")
    parser.add_argument("--referer", help="override the Referer sent to the host")
    parser.add_argument("--direct", action="store_true", help="treat the URL as a direct media file (skip yt-dlp)")
    parser.add_argument("--force", action="store_true", help="overwrite existing sheets")
    parser.add_argument("-n", "--dry-run", action="store_true", help="resolve and plan only")
    parser.add_argument("-q", "--quiet", action="store_true", help="summary line only")
    parser.add_argument("-V", "--version", action="version", version=f"qvp_online {VERSION}")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    args = build_parser().parse_args(argv)
    try:
        args.color = qvp.color_or_raise(args.color)
        args.grid = qvp.parse_grid(args.grid) if args.grid else None
    except qvp.UsageError as exc:
        print(f"qvp_online: {exc}", file=sys.stderr)
        return 2
    args.frame_workers = max(1, min(args.frame_workers, MAX_FRAME_WORKERS))
    args.out_dir = (args.out or Path.cwd() / qvp.OUT_DIR_NAME).resolve()
    args.suffix = ".avif" if args.image_format == "avif" else ".jpg"

    args.ffmpeg = args.ffmpeg or (qvp.ffmpeg_candidates() or [None])[0]
    if not args.ffmpeg:
        print("qvp_online: no ffmpeg found - install it or pass --ffmpeg", file=sys.stderr)
        return 2
    ffprobe = [args.ffprobe] if args.ffprobe else qvp.ffprobe_candidates()
    if not ffprobe:
        print("qvp_online: no ffprobe found - install it or pass --ffprobe", file=sys.stderr)
        return 2

    started = time.perf_counter()
    results: list[Result] = []
    for index, url in enumerate(args.urls, 1):
        if not args.quiet:
            print(f"[{index}/{len(args.urls)}] {url} ... ", end="", flush=True)
        result = render(args, ffprobe, url)
        if not args.quiet:
            print(result.status)
        results.append(result)
    print(qvp.render_report(results, time.perf_counter() - started))
    return 1 if any(result.status == "failed" for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
