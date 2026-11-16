"""Profile one render: phase timers + cProfile hotspots.

    python tools/bench_profile.py "D:\\Videos\\clip.mp4" [-o out] [--decode-workers 1]

Phase timers wrap the functions that dominate a render, so the table splits
"decode" (ffmpeg subprocess) from "save" (JPEG encode) and so on. cProfile's
tottime then shows whether anything in Python is worth fixing at all.
"""

from __future__ import annotations

import cProfile
import io
import pstats
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import qvp  # noqa: E402
from PIL import Image  # noqa: E402

TIMERS: dict[str, float] = {}


def tick(name: str, seconds: float) -> None:
    TIMERS[name] = TIMERS.get(name, 0.0) + seconds


def wrap(module, name: str, label: str) -> None:
    original = getattr(module, name)

    def wrapper(*args, **kwargs):
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            tick(label, time.perf_counter() - started)

    setattr(module, name, wrapper)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    video = Path(sys.argv[1])
    extra = sys.argv[2:]

    wrap(qvp, "probe_video", "probe")
    wrap(qvp, "grab_frame_ffmpeg", "decode")
    wrap(qvp, "stamp", "stamp")
    save = Image.Image.save

    def timed_save(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return save(self, *args, **kwargs)
        finally:
            tick("save", time.perf_counter() - started)

    Image.Image.save = timed_save

    profiler = cProfile.Profile()
    started = time.perf_counter()
    profiler.enable()
    code = qvp.main(["--force", *extra, str(video)])
    profiler.disable()
    total = time.perf_counter() - started

    print(f"\nrc={code}  wall={total:.2f}s")
    print("\nphase timers (wall; parallel decode counts every worker):")
    for name, seconds in sorted(TIMERS.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<10} {seconds:8.3f}s  {seconds / total * 100:5.1f}%")
    other = total - sum(TIMERS.values())
    print(f"  {'(other)':<10} {other:8.3f}s  {other / total * 100:5.1f}%")

    buffer = io.StringIO()
    stats = pstats.Stats(profiler, stream=buffer)
    stats.sort_stats("tottime").print_stats(15)
    print("\ncProfile by tottime:")
    for line in buffer.getvalue().splitlines():
        if line.strip():
            print(line[:150])
    return code


if __name__ == "__main__":
    sys.exit(main())
