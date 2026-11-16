"""qvp.py - batch video quick view sheets.

For every video it finds, cut a fixed number of frames, stamp each one with its
timecode, and glue them into one grid image, so a folder of videos can be
browsed at a glance.

Quick start::

    python qvp.py                       # every video next to this script
    python qvp.py D:\\Videos             # every video in a folder
    python qvp.py D:\\Videos -R -j 4     # subfolders too, four at a time
    python qvp.py -n D:\\Videos          # show the plan, write nothing

The script is a single file on purpose: drop it next to the videos and run it.
Inside, it is split into layers so each one can be tested on its own:

    defaults -> data model -> pure helpers -> discovery -> plan -> render
             -> report -> CLI

Exit codes: 0 all ok or skipped, 1 at least one failure, 2 bad arguments,
130 interrupted.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import shutil
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid
import warnings
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageColor, ImageDraw, ImageFont

# Sheets are opened only after we wrote them ourselves, so Pillow's
# decompression-bomb guard would just warn on legitimate 4K canvases.
Image.MAX_IMAGE_PIXELS = None

# --------------------------------------------------------------------------
# Defaults - editing these still works, the command line overrides them.
# --------------------------------------------------------------------------

# (longest duration in seconds, grid) - picked by auto_grid() below.
# Density grows fast at the start and then levels off, because a 40 s clip has
# far more to show per second than a 40 min one.
GRID_PRESETS = (
    (20, (2, 2)),
    (40, (3, 2)),
    (60, (3, 3)),
    (180, (4, 3)),
    (300, (4, 4)),
    (720, (5, 4)),
    (None, (5, 5)),
)
OUT_DIR_NAME = "sheets"   # where sheets go, next to each video
EDGE_INSET = 1.0          # seconds skipped at both ends (fades, slates, end cards)
MAX_DECODE_WORKERS = 4    # ffmpeg processes pulling frames in parallel
DEFAULT_BATCH_SEEK = 1    # timestamps per ffmpeg process on the CPU (1 = per frame)
DEFAULT_GPU_BATCH_SEEK = 4  # GPU: batching amortises the CUDA context, 4 fits 4 GB VRAM
GPU_CHUNK_WORKERS = 2     # concurrent GPU processes: more than this starts swapping VRAM
BORDER_SIZE = 2          # white border around every frame, in pixels
TEXT_COLOR = "red"       # timecode colour

VERSION = "2.7.2"
JPEG_QUALITY = 85
MAX_PIXELS = 200_000_000  # refuse to build a canvas bigger than this

VIDEO_SUFFIXES = frozenset(
    {".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".mpg", ".mpeg", ".ts", ".m2ts"}
)

FONT_CANDIDATES = (
    "arial.ttf",
    "segoeui.ttf",
    "DejaVuSans.ttf",
    "LiberationSans-Regular.ttf",
    "Helvetica.ttc",
    "PingFang.ttc",
    "msyh.ttc",
    "NotoSansCJK-Regular.ttc",
)


# --------------------------------------------------------------------------
# Errors and data model
# --------------------------------------------------------------------------


class UsageError(Exception):
    """Bad arguments - maps to exit code 2."""


class ProbeError(Exception):
    """A video cannot be opened or has no usable duration."""


class FrameError(Exception):
    """A single frame could not be decoded."""


@dataclass(frozen=True)
class Probe:
    width: int
    height: int
    duration: float
    fps: float
    codec: str = ""


@dataclass(frozen=True)
class Layout:
    cols: int
    rows: int
    border: int
    cell_w: int
    cell_h: int

    @property
    def cells(self) -> int:
        return self.cols * self.rows

    @property
    def canvas(self) -> tuple[int, int]:
        return (self.cols * self.cell_w, self.rows * self.cell_h)

    @property
    def pixels(self) -> int:
        width, height = self.canvas
        return width * height


@dataclass(frozen=True)
class Job:
    video: Path
    output: Path
    probe: Probe
    layout: Layout
    times: tuple[float, ...]

    @property
    def name(self) -> str:
        return self.video.name


@dataclass
class Result:
    name: str
    status: str            # ok | skipped | failed | planned
    reason: str = ""
    elapsed: float = 0.0
    frames: int = 0
    grid: str = "-"
    canvas: tuple[int, int] | None = None
    output: Path | None = None
    note: str = ""


@dataclass
class Options:
    paths: list[Path]
    out_dir: Path | None = None
    frames: int | None = None
    grid: tuple[int, int] | None = None
    border: int = BORDER_SIZE
    color: str = TEXT_COLOR
    font: str | None = None
    font_size: int | None = None
    ffmpeg: str | None = None
    time_format: str = "auto"
    recursive: bool = False
    jobs: int = 1
    decode_workers: int = 0
    batch_seek: int = 0
    cuda: bool = False
    force: bool = False
    dry_run: bool = False
    max_pixels: int = MAX_PIXELS
    log: Path | None = None
    quiet: bool = False

    def frame_count(self, cells: int) -> int:
        return self.frames if self.frames is not None else cells


# --------------------------------------------------------------------------
# Pure helpers - no I/O, no globals mutated, easy to unit test
# --------------------------------------------------------------------------


def grid_arg(text: str) -> tuple[int, int] | None:
    """argparse adapter: `auto` means "decide per video", else parse COLUMNSxROWS."""
    if text.strip().lower() == "auto":
        return None
    try:
        return parse_grid(text)
    except UsageError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parse_grid(text: str) -> tuple[int, int]:
    """Parse `4x4`, `4X4`, `4*4` or `4,4` into (cols, rows)."""
    cleaned = text.strip().lower().replace("*", "x").replace(",", "x")
    parts = cleaned.split("x")
    if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
        raise UsageError(f"invalid grid {text!r}: expected COLUMNSxROWS, e.g. 4x4")
    cols, rows = (int(p) for p in parts)
    if not (1 <= cols <= 16 and 1 <= rows <= 16):
        raise UsageError(f"invalid grid {text!r}: each side must be between 1 and 16")
    return cols, rows


def sample_times(duration: float, count: int, fps: float = 0.0) -> tuple[float, ...]:
    """Evenly spaced timestamps, one EDGE_INSET away from both ends.

    Both ends are trimmed by the same amount: the opening often holds a logo or
    a fade-in and the tail an end card, and neither is worth a cell. For clips
    shorter than four seconds the inset shrinks with the clip.
    """
    if count < 1:
        raise UsageError("frame count must be at least 1")
    if not duration or duration <= 0 or math.isnan(duration):
        raise ProbeError("video has no usable duration")
    decay = 1.5 / fps if fps and fps > 0 else 0.05
    edge = min(EDGE_INSET, duration / 4)
    last = duration - max(edge, decay)
    first = edge
    if last <= first:  # pathological durations: use the whole clip
        first, last = 0.0, max(duration - decay, 0.0)
    if count == 1:
        return ((first + last) / 2,)
    step = (last - first) / (count - 1)
    return tuple(first + i * step for i in range(count))


def format_timecode(seconds: float, style: str = "auto") -> str:
    """Round to the nearest second and format as a timecode."""
    total = max(0, int(math.floor(seconds + 0.5)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if style == "hms":
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    if style == "ms":
        return f"{hours * 60 + minutes:02d}:{secs:02d}"
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def grid_for_frames(count: int) -> tuple[int, int]:
    """Smallest grid from the ladder that can hold `count` frames."""
    for _, shape in GRID_PRESETS:
        if shape[0] * shape[1] >= count:
            return shape
    raise UsageError("more than 25 frames do not fit in a 5x5 grid")


def auto_grid(duration: float, width: int, height: int, border: int, max_pixels: int) -> tuple[int, int]:
    """Pick a grid from the duration ladder, then step down until it fits.

    The ladder keeps the sheet dense early (a 40 s clip already gets 6 cells)
    because a short video changes what it shows more often; long films add cells
    slowly. The pixel budget wins over the table when a 4K 5x5 would not fit.
    """
    shapes = [shape for _, shape in GRID_PRESETS]
    index = next(
        (i for i, (limit, _) in enumerate(GRID_PRESETS) if limit is None or duration <= limit),
        len(shapes) - 1,
    )
    while index > 0:
        cols, rows = shapes[index]
        layout = Layout(cols, rows, border, width + 2 * border, height + 2 * border)
        if layout.pixels <= max_pixels:
            break
        index -= 1
    return shapes[index]


def layout_for(width: int, height: int, grid: tuple[int, int], border: int) -> Layout:
    if width <= 0 or height <= 0:
        raise ProbeError("video reports an empty picture")
    if border < 0:
        raise UsageError("border cannot be negative")
    return Layout(grid[0], grid[1], border, width + 2 * border, height + 2 * border)


def output_name(stem: str) -> str:
    return f"{stem}_collage.jpg"


def font_size_for(cell_width: int) -> int:
    return max(12, min(96, round(cell_width * 0.022)))


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_SUFFIXES


def color_or_raise(spec: str) -> str:
    try:
        ImageColor.getrgb(spec)
    except ValueError as exc:
        raise UsageError(f"invalid colour {spec!r}") from exc
    return spec


def short_error(exc: BaseException, limit: int = 120) -> str:
    """One readable line out of a moviepy/ffmpeg exception, without paths."""
    text = " ".join(str(exc).replace("\r", " ").replace("\n", " ").split())
    text = re.sub(r"[A-Za-z]:\\[^\s\"']+", "<file>", text)
    for fragment in ("Error opening input files:", "Error opening input file", "Traceback (most recent call last)"):
        if fragment in text:
            text = text.split(fragment)[-1]
    text = text.strip(" :-")
    return text[:limit] + ("…" if len(text) > limit else "")


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def iter_videos(folder: Path, recursive: bool) -> Iterable[Path]:
    if not recursive:
        for path in folder.glob("*"):
            if path.is_file() and is_video(path):
                yield path
        return
    for root, _dirs, files in os.walk(folder, followlinks=False):
        for name in files:
            path = Path(root) / name
            if is_video(path):
                yield path


def discover(targets: Sequence[Path], recursive: bool) -> tuple[list[Path], list[Path]]:
    """Expand files and folders into a sorted, de-duplicated video list."""
    found: dict[str, Path] = {}
    missing: list[Path] = []
    for target in targets:
        if target.is_dir():
            for video in iter_videos(target, recursive):
                found[os.path.normcase(str(video.resolve()))] = video
        elif target.is_file():
            if is_video(target):
                found[os.path.normcase(str(target.resolve()))] = target
            else:
                missing.append(target)
        else:
            missing.append(target)
    videos = sorted(found.values(), key=lambda p: (p.name.lower(), str(p).lower()))
    return videos, missing


# --------------------------------------------------------------------------
# Probing
# --------------------------------------------------------------------------


@contextmanager
def quiet_moviepy():
    """moviepy prints ffmpeg banners, warnings and (2.1.1) its whole info dict.

    Both streams are swallowed while a clip is opened so the report stays the
    only thing on screen.
    """
    with warnings.catch_warnings(), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        warnings.simplefilter("ignore")
        yield


def ffprobe_candidates(ffmpeg: str | None = None) -> list[str]:
    """ffprobe binaries to try: next to the chosen ffmpeg, then on PATH."""
    found: list[str] = []
    if ffmpeg:
        sibling = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if sibling.is_file():
            found.append(str(sibling))
    on_path = shutil.which("ffprobe")
    if on_path:
        found.append(on_path)
    return found


def _rate(text: str) -> float:
    """'30/1' -> 30.0, 'N/A' -> 0.0."""
    try:
        numerator, _, denominator = text.partition("/")
        value = float(numerator) / float(denominator or 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0
    return value if math.isfinite(value) and value > 0 else 0.0


def _probe_ffprobe(path: Path, binary: str) -> Probe:
    command = [
        binary,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name,avg_frame_rate,r_frame_rate:format=duration",
        "-of", "json",
        str(path),
    ]
    extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        done = subprocess.run(command, capture_output=True, check=False, timeout=60, **extra)
    except subprocess.TimeoutExpired as exc:
        raise ProbeError("ffprobe took too long (60 s)") from exc
    except OSError as exc:
        raise ProbeError(f"cannot run ffprobe ({exc})") from exc
    if done.returncode != 0 or not done.stdout.strip():
        message = short_error(done.stderr.decode("utf-8", "replace")) or "cannot read video"
        raise ProbeError(message)
    try:
        data = json.loads(done.stdout.decode("utf-8", "replace"))
    except ValueError as exc:
        raise ProbeError("ffprobe returned unreadable JSON") from exc
    streams = data.get("streams") or []
    if not streams:
        raise ProbeError("no video stream")
    stream = streams[0]
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    codec = str(stream.get("codec_name") or "")
    fps = _rate(stream.get("avg_frame_rate") or "") or _rate(stream.get("r_frame_rate") or "")
    duration = float((data.get("format") or {}).get("duration") or 0.0)
    if duration <= 0 or not math.isfinite(duration):
        raise ProbeError("video has no usable duration")
    if width <= 0 or height <= 0:
        raise ProbeError("video reports an empty picture")
    return Probe(width, height, duration, fps, codec)


def _probe_moviepy(path: Path) -> Probe:
    try:
        from moviepy import VideoFileClip  # lazy: keeps --version and tests fast
        with quiet_moviepy(), VideoFileClip(str(path)) as clip:
            duration = float(clip.duration or 0.0)
            width, height = clip.size
            fps = float(clip.fps or 0.0)
    except ImportError as exc:
        raise ProbeError("moviepy 2.x is required (pip install 'moviepy>=2')") from exc
    except Exception as exc:  # moviepy raises a zoo of types; all mean "cannot open"
        raise ProbeError(short_error(exc)) from exc
    if duration <= 0 or math.isnan(duration):
        raise ProbeError("video has no usable duration")
    return Probe(width, height, duration, fps)


def probe_video(path: Path, ffmpeg: str | None = None) -> Probe:
    """ffprobe first (70 ms vs 1 s for moviepy), moviepy only when it is absent."""
    for binary in ffprobe_candidates(ffmpeg):
        return _probe_ffprobe(path, binary)
    return _probe_moviepy(path)


def ffmpeg_candidates(explicit: str | None = None) -> list[str]:
    """Possible ffmpeg binaries, best first: explicit, system, moviepy's copy.

    A system ffmpeg is preferred because the build bundled with imageio decodes
    some codecs several times slower (measured 4x on AV1). If the first choice
    cannot decode the file, the renderer retries with the next one.
    """
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    found = shutil.which("ffmpeg")
    if found:
        candidates.append(found)
    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        bundled = None
    if bundled:
        candidates.append(bundled)
    unique: list[str] = []
    seen = set()
    for candidate in candidates:
        key = os.path.normcase(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def grab_frame_ffmpeg(
    video: Path, moment: float, probe: Probe, binary: str, threads: int = 0, hwaccel: str = "none"
) -> Image.Image:
    """Decode one frame at `moment` with a fast accurate seek, as raw RGB.

    `threads` caps ffmpeg's own decoder threads; when several processes run at
    once, letting each grab all cores just makes them fight over them.
    `hwaccel="cuda"` decodes on the GPU and downloads the frame as 24-bit BGR,
    which Pillow reads through its "BGR" raw mode.
    """
    on_gpu = hwaccel == "cuda"
    command = [
        binary,
        "-v", "error",
        "-nostdin",
        *(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"] if on_gpu else []),
        *(["-threads", str(threads)] if threads > 0 else []),
        "-ss", f"{moment:.3f}",
        "-i", str(video),
        "-frames:v", "1",
        *(["-vf", "hwdownload,format=nv12,format=bgr24"] if on_gpu else []),
        "-f", "rawvideo",
        "-pix_fmt", "bgr24" if on_gpu else "rgb24",
        "pipe:1",
    ]
    extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        done = subprocess.run(command, capture_output=True, check=False, timeout=120, **extra)
    except subprocess.TimeoutExpired as exc:
        raise FrameError("ffmpeg took too long (120 s) to produce one frame") from exc
    except OSError as exc:
        raise FrameError(f"cannot run ffmpeg ({exc})") from exc
    expected = probe.width * probe.height * 3
    if done.returncode != 0 or len(done.stdout) != expected:
        message = short_error(done.stderr.decode("utf-8", "replace")) or "no picture returned"
        raise FrameError(message)
    if on_gpu:
        return Image.frombytes("RGB", (probe.width, probe.height), done.stdout, "raw", "BGR", 0, 1)
    return Image.frombytes("RGB", (probe.width, probe.height), done.stdout)


def decode_plan(frame_count: int, requested: int = 0) -> tuple[int, int]:
    """(processes, threads each) for pulling frames.

    Decoding one frame means seeking to the previous keyframe and decoding
    forward, so a single ffmpeg process leaves most cores idle. Two to four
    processes overlap that work; each one then gets a slice of the cores.
    """
    cpu = os.cpu_count() or 1
    if requested > 0:
        workers = min(requested, max(1, frame_count))
    else:
        workers = min(MAX_DECODE_WORKERS, max(1, cpu // 4), max(1, frame_count))
    if workers < 2:
        return 1, 0
    return workers, max(1, cpu // workers)


def hardware_modes(use_cuda: bool) -> tuple[str, ...]:
    """Decoders to try, best first: the GPU one when asked, then software."""
    return ("cuda", "none") if use_cuda else ("none",)


def seeks_per_process(mode: str, requested: int = 0) -> int:
    """How many timestamps one ffmpeg process should carry.

    Opening a decoder costs more than decoding a frame, so carrying several
    seeks per process amortises it. GPU decoding also allocates VRAM per input,
    which is why it gets a smaller default.
    """
    if requested > 0:
        return max(1, requested)
    return DEFAULT_BATCH_SEEK if mode == "none" else DEFAULT_GPU_BATCH_SEEK


def batched_command(
    video: Path, times: Sequence[float], outputs: Sequence[Path], binary: str,
    threads: int = 0, hwaccel: str = "none",
) -> list[str]:
    """One ffmpeg process, one seek per input, one BMP per input."""
    on_gpu = hwaccel == "cuda"
    command: list[str] = [binary, "-v", "error", "-nostdin", "-y"]
    for moment in times:
        if on_gpu:
            command += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        if threads > 0:
            command += ["-threads", str(threads)]
        command += ["-ss", f"{moment:.3f}", "-i", str(video)]
    for index, output in enumerate(outputs):
        command += ["-map", f"{index}:v:0", "-frames:v", "1"]
        if on_gpu:
            command += ["-vf", "hwdownload,format=nv12,format=bgr24"]
        command += [str(output)]
    return command


def extract_chunk(
    job: "Job", times: Sequence[float], folder: Path, binary: str,
    threads: int, hwaccel: str,
) -> list[Path]:
    """Run one batched ffmpeg and return the BMP files it wrote, in order."""
    folder.mkdir(parents=True, exist_ok=True)
    outputs = [folder / f"f{index:03d}.bmp" for index in range(len(times))]
    command = batched_command(job.video, times, outputs, binary, threads, hwaccel)
    extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    budget = max(120, int(len(times) * 60))
    try:
        done = subprocess.run(command, capture_output=True, check=False, timeout=budget, **extra)
    except subprocess.TimeoutExpired as exc:
        raise FrameError(f"ffmpeg took too long ({budget} s) to fetch {len(times)} frames") from exc
    except OSError as exc:
        raise FrameError(f"cannot run ffmpeg ({exc})") from exc
    missing = [path for path in outputs if not path.is_file() or path.stat().st_size == 0]
    if done.returncode != 0 or missing:
        message = short_error(done.stderr.decode("utf-8", "replace")) or "no picture returned"
        raise FrameError(message)
    return outputs


def load_bmp(path: Path) -> Image.Image:
    with Image.open(path) as image:
        frame = image.convert("RGB")
        frame.load()
    path.unlink(missing_ok=True)
    return frame


@contextmanager
def frame_source(
    job: "Job",
    candidates: Sequence[str],
    workers: int = 0,
    use_cuda: bool = False,
    used: dict[str, str] | None = None,
    batch_seek: int = 0,
):
    """Yield an iterator of RGB frames, in input order.

    The first frame decides which ffmpeg binary and which decoder (GPU or CPU)
    works for this file. After that frames come either one process per frame
    (when `batch_seek` is 1) or `seeks_per_process()` timestamps per process,
    which amortises decoder start-up. Without any ffmpeg binary the moviepy
    reader is used instead (slower, still correct).
    """
    first = None
    chosen = None
    mode = "none"
    for attempt in hardware_modes(use_cuda):
        for binary in candidates:
            try:
                first = grab_frame_ffmpeg(job.video, job.times[0], job.probe, binary, hwaccel=attempt)
            except FrameError:
                continue
            chosen, mode = binary, attempt
            break
        if chosen is not None:
            break

    if first is None or chosen is None:
        from moviepy import VideoFileClip

        with quiet_moviepy(), VideoFileClip(str(job.video)) as clip:
            yield (Image.fromarray(clip.get_frame(moment)) for moment in job.times)
        return

    if used is not None:
        used["mode"] = mode
    back = max(0.05, 2.0 / job.probe.fps) if job.probe.fps > 0 else 0.2
    state = {"mode": mode, "binary": chosen}
    total = len(job.times)
    per_process = seeks_per_process(mode, batch_seek)

    def single(index: int, moment: float) -> Image.Image:
        cap = 0
        active = state["mode"]
        try:
            return grab_frame_ffmpeg(job.video, moment, job.probe, state["binary"], cap, active)
        except FrameError:
            if active == "cuda":
                state["mode"] = "none"
                if used is not None:
                    used["mode"] = "none"
                return grab_frame_ffmpeg(job.video, moment, job.probe, state["binary"], cap, "none")
            if moment <= back:
                raise
            return grab_frame_ffmpeg(job.video, moment - back, job.probe, state["binary"], cap, "none")

    def chunk_frames(chunk: Sequence[float], folder: Path, threads: int) -> list[Image.Image]:
        try:
            paths = extract_chunk(job, chunk, folder, state["binary"], threads, state["mode"])
        except FrameError:
            if state["mode"] != "cuda":
                raise
            state["mode"] = "none"  # GPU refused a chunk: keep going on the CPU
            if used is not None:
                used["mode"] = "none"
            paths = extract_chunk(job, chunk, folder, state["binary"], threads, "none")
        return [load_bmp(path) for path in paths]

    workdir = Path(tempfile.mkdtemp(prefix="qvp-frames-"))
    try:
        if per_process <= 1 or total <= 1:
            pool_size, _threads = decode_plan(total - 1, workers) if total > 1 else (1, 0)
            pool = ThreadPoolExecutor(max_workers=pool_size) if pool_size > 1 else None
            futures: dict[int, Future[Image.Image]] = {}
            submitted = 1

            def keep_full(index: int) -> None:
                nonlocal submitted
                if pool is None:
                    return
                limit = min(total, index + pool_size + 1)
                while submitted < limit:
                    futures[submitted] = pool.submit(single, submitted, job.times[submitted])
                    submitted += 1

            keep_full(0)

            def sequential():
                yield first
                for index in range(1, total):
                    future = futures.pop(index, None)
                    if future is not None:
                        image = future.result()
                        keep_full(index)
                    else:
                        image = single(index, job.times[index])
                    yield image

            try:
                yield sequential()
            finally:
                if pool is not None:
                    pool.shutdown(wait=True, cancel_futures=True)
            return

        chunks = [job.times[start:start + per_process] for start in range(0, total, per_process)]
        if state["mode"] == "cuda" and workers == 0:
            chunk_workers = min(GPU_CHUNK_WORKERS, len(chunks))
        else:
            chunk_workers = decode_plan(len(chunks), workers)[0]

        def chunked():
            pool = ThreadPoolExecutor(max_workers=min(chunk_workers, len(chunks)))
            futures = {
                index: pool.submit(chunk_frames, chunk, workdir / f"c{index}", 0)
                for index, chunk in enumerate(chunks)
            }
            try:
                for index in range(len(chunks)):
                    for image in futures[index].result():
                        yield image
            finally:
                pool.shutdown(wait=True, cancel_futures=True)

        try:
            yield chunked()
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# --------------------------------------------------------------------------
# Plan stage - computes everything, writes nothing
# --------------------------------------------------------------------------


def output_for(video: Path, out_dir: Path | None) -> Path:
    folder = out_dir if out_dir is not None else video.parent / OUT_DIR_NAME
    return folder / output_name(video.stem)


def plan_job(video: Path, opts: Options) -> Job | Result:
    """Return a Job to render, or a Result explaining why it will not be."""
    output = output_for(video, opts.out_dir)
    if output.exists() and not opts.force:
        return Result(video.name, "skipped", "already exists (use --force to overwrite)", output=output)

    try:
        probe = probe_video(video, opts.ffmpeg)
        if opts.grid:
            grid = opts.grid
        elif opts.frames is not None:
            grid = grid_for_frames(opts.frames)
        else:
            grid = auto_grid(probe.duration, probe.width, probe.height, opts.border, opts.max_pixels)
        layout = layout_for(probe.width, probe.height, grid, opts.border)
        wanted = opts.frame_count(layout.cells)
        if wanted > layout.cells:
            return Result(
                video.name,
                "failed",
                f"{wanted} frames do not fit a {layout.cols}x{layout.rows} grid ({layout.cells} cells)",
                output=output,
            )
        if layout.pixels > opts.max_pixels:
            return Result(
                video.name,
                "failed",
                f"canvas {layout.canvas[0]}x{layout.canvas[1]} is {layout.pixels / 1e6:.0f} MP, "
                f"over the {opts.max_pixels / 1e6:.0f} MP limit",
                output=output,
            )
        times = sample_times(probe.duration, wanted, probe.fps)
    except ProbeError as exc:
        return Result(video.name, "failed", f"cannot open video ({exc})", output=output)
    except UsageError as exc:
        return Result(video.name, "failed", str(exc), output=output)
    return Job(video, output, probe, layout, times)


def plan_all(videos: Sequence[Path], opts: Options) -> list[Job | Result]:
    """Plan every video and flag two jobs that would write the same file."""
    items: list[Job | Result] = []
    seen: dict[str, str] = {}
    for video in videos:
        item = plan_job(video, opts)
        if isinstance(item, Job):
            key = os.path.normcase(str(item.output.resolve()))
            if key in seen:
                items.append(
                    Result(video.name, "failed", f"output name clashes with {seen[key]}", output=item.output)
                )
                continue
            seen[key] = str(video)
        items.append(item)
    return items


# --------------------------------------------------------------------------
# Render stage
# --------------------------------------------------------------------------


def load_font(size: int, prefer: str | None = None) -> ImageFont.ImageFont:
    if prefer:
        try:
            return ImageFont.truetype(prefer, size)
        except OSError as exc:
            raise UsageError(f"cannot load font {prefer!r}: {exc}") from exc
    for candidate in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 9.2
    except TypeError:
        return ImageFont.load_default()


def stamp(image: Image.Image, text: str, color: str, font: ImageFont.ImageFont, border: int) -> None:
    """Draw the timecode with a dark outline so it reads on any picture."""
    draw = ImageDraw.Draw(image)
    size = getattr(font, "size", 14) or 14
    pad = max(2, size // 8)
    stroke = max(1, size // 12)
    draw.text(
        (border + pad, border + pad),
        text,
        fill=color,
        font=font,
        stroke_width=stroke,
        stroke_fill="black",
    )


def render_job(job: Job, opts: Options) -> Result:
    started = time.perf_counter()
    layout = job.layout
    canvas_size = layout.canvas
    tmp = job.output.with_name(f".{job.output.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    clean_stale_temps(job.output)
    canvas = None
    try:
        job.output.parent.mkdir(parents=True, exist_ok=True)
        canvas = Image.new("RGB", canvas_size, "white")
        size = opts.font_size or font_size_for(layout.cell_w)
        font = load_font(size, opts.font)
        used: dict[str, str] = {}
        with frame_source(
            job, ffmpeg_candidates(opts.ffmpeg), opts.decode_workers, opts.cuda, used,
            opts.batch_seek,
        ) as frames:
            for index, (moment, image) in enumerate(zip(job.times, frames)):
                if image.size != (job.probe.width, job.probe.height):
                    raise FrameError(
                        f"frame {image.size[0]}x{image.size[1]} does not match the "
                        f"probed {job.probe.width}x{job.probe.height}"
                    )
                if image.mode != "RGB":
                    image = image.convert("RGB")
                stamp(image, format_timecode(moment, opts.time_format), opts.color, font, layout.border)
                # Pasting the frame straight onto the white canvas leaves the
                # border showing, without building a copy of the cell first.
                canvas.paste(
                    image,
                    (
                        (index % layout.cols) * layout.cell_w + layout.border,
                        (index // layout.cols) * layout.cell_h + layout.border,
                    ),
                )
        canvas.save(tmp, format="JPEG", quality=JPEG_QUALITY)
        verify_image(tmp, canvas_size)
        os.replace(tmp, job.output)
    except UsageError as exc:
        return finish_failure(job, tmp, started, str(exc))
    except ValueError as exc:
        return finish_failure(job, tmp, started, f"output check failed ({exc})")
    except FrameError as exc:
        return finish_failure(job, tmp, started, f"cannot decode a frame ({exc})")
    except ProbeError as exc:
        return finish_failure(job, tmp, started, f"cannot open video ({exc})")
    except OSError as exc:
        return finish_failure(job, tmp, started, f"cannot write output ({exc.strerror or exc})")
    except Exception as exc:  # decoding, memory, anything else: isolate this file
        return finish_failure(job, tmp, started, f"render failed ({short_error(exc)})")
    finally:
        if canvas is not None:
            canvas.close()
        tmp.unlink(missing_ok=True)  # no-op after os.replace; cleans up on Ctrl-C
    note = ""
    if opts.cuda:
        note = "GPU" if used.get("mode") == "cuda" else "software fallback"
    return Result(
        job.name,
        "ok",
        "",
        round(time.perf_counter() - started, 2),
        len(job.times),
        f"{layout.cols}x{layout.rows}",
        canvas_size,
        job.output,
        note,
    )


def clean_stale_temps(output: Path, max_age: float = 3600.0) -> None:
    """Remove temp files left behind by a killed run (older than an hour)."""
    now = time.time()
    try:
        for item in output.parent.iterdir():
            if not item.name.startswith(f".{output.name}.tmp-"):
                continue
            try:
                if now - item.stat().st_mtime > max_age:
                    item.unlink(missing_ok=True)
            except OSError:
                continue
    except OSError:
        return


def finish_failure(job: Job, tmp: Path, started: float, reason: str) -> Result:
    return Result(
        job.name, "failed", reason, round(time.perf_counter() - started, 2), 0, "-", None, job.output
    )


def verify_image(path: Path, expected: tuple[int, int]) -> None:
    """Header check plus a 1/8 decode: proves the file is readable without
    decoding the whole 33 MP (or 133 MP) sheet back into memory."""
    with Image.open(path) as probe:
        if probe.size != expected:
            raise ValueError(f"unexpected size {probe.size[0]}x{probe.size[1]}")
        if probe.mode != "RGB":
            raise ValueError(f"unexpected mode {probe.mode}")
        probe.draft("RGB", (max(1, probe.size[0] // 8), max(1, probe.size[1] // 8)))
        probe.load()


def render_all(items: Sequence[Job | Result], opts: Options) -> list[Result]:
    """Render every planned job; one Result per item, in input order."""
    if opts.dry_run:
        return [
            Result(
                item.name,
                "planned",
                "",
                0.0,
                len(item.times),
                f"{item.layout.cols}x{item.layout.rows}",
                item.layout.canvas,
                item.output,
            )
            if isinstance(item, Job)
            else item
            for item in items
        ]
    planned = [(index, item) for index, item in enumerate(items) if isinstance(item, Job)]
    if not planned:
        return [item for item in items if isinstance(item, Result)]

    rendered: dict[int, Result] = {}
    if opts.jobs > 1 and len(planned) > 1:
        pool = ThreadPoolExecutor(max_workers=opts.jobs)
        futures = [pool.submit(render_job, job, opts) for _, job in planned]
        try:
            for (index, _), future in zip(planned, futures):
                rendered[index] = future.result()
                if not opts.quiet:
                    print(f"[{rendered[index].status}] {items[index].name}")
        except KeyboardInterrupt:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        finally:
            pool.shutdown(wait=True)
    else:
        for position, (index, job) in enumerate(planned, 1):
            if not opts.quiet:
                print(f"[{position}/{len(planned)}] {job.name} … ", end="", flush=True)
            result = render_job(job, opts)
            rendered[index] = result
            if not opts.quiet:
                print(result.status)
    return [
        rendered[index] if isinstance(item, Job) else item
        for index, item in enumerate(items)
    ]


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))



def describe(result: Result) -> str:
    if result.status == "ok":
        return f"ok ({result.note})" if result.note else "ok"
    if result.status == "planned":
        return "would write"
    if result.status == "skipped":
        return f"skipped: {result.reason}"
    return f"failed: {result.reason}"


def render_report(results: Sequence[Result], elapsed: float) -> str:
    headers = ("#", "file", "grid", "frames", "canvas", "time", "result")
    rows = []
    for index, result in enumerate(results, 1):
        canvas = f"{result.canvas[0]}x{result.canvas[1]}" if result.canvas else "-"
        rows.append(
            (
                str(index),
                result.name,
                result.grid,
                str(result.frames) if result.frames else "-",
                canvas,
                f"{result.elapsed:.2f}s" if result.elapsed else "-",
                describe(result),
            )
        )
    if not rows:
        return "nothing to report"
    widths = [max(display_width(headers[i]), *(display_width(row[i]) for row in rows)) for i in range(len(headers))]
    lines = ["  ".join(pad(headers[i], widths[i]) for i in range(len(headers))).rstrip()]
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        lines.append("  ".join(pad(row[i], widths[i]) for i in range(len(headers))).rstrip())
    done = sum(1 for r in results if r.status == "ok")
    planned = sum(1 for r in results if r.status == "planned")
    skipped = sum(1 for r in results if r.status == "skipped")
    failed = sum(1 for r in results if r.status == "failed")
    parts = [f"{done} done"]
    if planned:
        parts.append(f"{planned} planned")
    parts += [f"{skipped} skipped", f"{failed} failed"]
    lines.append("")
    lines.append(", ".join(parts) + f" in {elapsed:.2f}s")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qvp.py",
        description="Turn videos into grids of timecoded frames.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="*", type=Path, help="files or folders (default: next to this script)")
    parser.add_argument("-o", "--out", type=Path, help=f"output folder (default: <video folder>/{OUT_DIR_NAME})")
    parser.add_argument("--frames", type=int, help="frames per video (default: one per grid cell)")
    parser.add_argument(
        "-g", "--grid", type=grid_arg, default=None,
        help="grid as COLUMNSxROWS, or auto to pick from the duration ladder "
             "(2x2/3x2/3x3/4x3/4x4/5x4/5x5, default: auto)",
    )
    parser.add_argument("-b", "--border", type=int, default=BORDER_SIZE, help="white border in pixels (default: 2)")
    parser.add_argument("-c", "--color", default=TEXT_COLOR, help="timecode colour (default: red)")
    parser.add_argument("--font", help="font file to use")
    parser.add_argument("--ffmpeg", help="ffmpeg to try first (falls back to system, then moviepy's copy)")
    parser.add_argument("--font-size", type=int, help="timecode size in pixels (default: scaled to the cell)")
    parser.add_argument(
        "--time-format",
        choices=("auto", "hms", "ms"),
        default="auto",
        help="timecode style: auto (00:26 / 1:01:05), hms (00:00:26), ms (minutes:seconds, 26:00)",
    )
    parser.add_argument("-R", "--recursive", action="store_true", help="also look in subfolders")
    parser.add_argument("-j", "--jobs", type=int, default=1, help="videos to render at once (default: 1)")
    parser.add_argument(
        "--cuda",
        action="store_true",
        help="decode frames on the GPU; gains depend on GPU, driver and codec",
    )
    parser.add_argument(
        "--batch-seek",
        type=int,
        default=0,
        help="timestamps carried by one ffmpeg process, 0 = auto (4 with --cuda, 1 without), 1 = one process per frame",
    )
    parser.add_argument(
        "--decode-workers",
        type=int,
        default=0,
        help="ffmpeg processes decoding frames in parallel, 0 = auto, 1 = sequential (default: 0)",
    )
    parser.add_argument("-f", "--force", action="store_true", help="overwrite existing sheets")
    parser.add_argument("-n", "--dry-run", action="store_true", help="print the plan, write nothing")
    parser.add_argument("--max-pixels", type=int, default=MAX_PIXELS, help="canvas pixel budget")
    parser.add_argument("--log", type=Path, help="append a run log to this file")
    parser.add_argument("-q", "--quiet", action="store_true", help="only print the summary line")
    parser.add_argument("-V", "--version", action="version", version=f"qvp {VERSION}")
    return parser


def options_from_args(args: argparse.Namespace) -> Options:
    if args.frames is not None and not 1 <= args.frames <= 256:
        raise UsageError("--frames must be between 1 and 256")
    if not 0 <= args.border <= 64:
        raise UsageError("--border must be between 0 and 64")
    if not 0 <= args.batch_seek <= 25:
        raise UsageError("--batch-seek must be between 0 and 25")
    if not 0 <= args.decode_workers <= 16:
        raise UsageError("--decode-workers must be between 0 and 16")
    if not 1 <= args.jobs <= 16:
        raise UsageError("--jobs must be between 1 and 16")
    if args.max_pixels < 1_000_000:
        raise UsageError("--max-pixels must be at least 1,000,000")
    if args.font_size is not None and not 6 <= args.font_size <= 400:
        raise UsageError("--font-size must be between 6 and 400")
    color_or_raise(args.color)
    paths = args.paths or [Path(__file__).resolve().parent]
    frames = args.frames
    return Options(
        paths=list(paths),
        out_dir=args.out,
        frames=frames,
        grid=args.grid,
        border=args.border,
        color=args.color,
        font=args.font,
        font_size=args.font_size,
        ffmpeg=args.ffmpeg,
        time_format=args.time_format,
        recursive=args.recursive,
        jobs=args.jobs,
        decode_workers=args.decode_workers,
        batch_seek=args.batch_seek,
        cuda=args.cuda,
        force=args.force,
        dry_run=args.dry_run,
        max_pixels=args.max_pixels,
        log=args.log,
        quiet=args.quiet,
    )


def write_log(path: Path, lines: Sequence[str]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            for line in lines:
                handle.write(line + "\n")
    except OSError as exc:
        print(f"warning: cannot write log {path}: {exc}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # redirected consoles use cp936/gbk
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (ValueError, OSError):
                pass
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help/--version exit 0, bad arguments exit 2
        return int(exc.code or 0)
    try:
        opts = options_from_args(args)
    except UsageError as exc:
        print(f"qvp: {exc}", file=sys.stderr)
        return 2

    if not opts.quiet:
        print(f"qvp {VERSION}", flush=True)  # say something before the first ffprobe

    started = time.perf_counter()
    videos, missing = discover(opts.paths, opts.recursive)
    for path in missing:
        print(f"warning: not found or not a video: {path}", file=sys.stderr)
    if not videos:
        print("no videos found")
        return 0

    if not opts.quiet:
        where = str(opts.out_dir) if opts.out_dir else f"{OUT_DIR_NAME}/ next to each video"
        grid = f"{opts.grid[0]}x{opts.grid[1]}" if opts.grid else "auto"
        print(f"{len(videos)} video(s) | grid {grid} | {where}", flush=True)

    if not ffmpeg_candidates(opts.ffmpeg):
        try:
            import moviepy  # noqa: F401
        except ImportError:
            print(
                "qvp: no ffmpeg found and moviepy is missing - install ffmpeg "
                "or 'pip install moviepy>=2'",
                file=sys.stderr,
            )
            return 2

    items = plan_all(videos, opts)
    results = render_all(items, opts)
    elapsed = time.perf_counter() - started
    report = render_report(results, elapsed)
    if not opts.quiet:
        print(report)
    else:
        print(report.splitlines()[-1])
    if opts.log and not opts.dry_run:  # --dry-run means write nothing
        write_log(opts.log, [report] + [f"{describe(r)}  {r.output or ''}".rstrip() for r in results])
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        sys.exit(130)
