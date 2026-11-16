"""Compare sequential and parallel frame decoding on real files.

    python tools/bench_decode.py "D:\\Videos\\a.mp4" "D:\\Videos\\b.mp4"

Each file is rendered twice (--decode-workers 1, then auto) into a temporary
folder, and the wall clock is printed side by side. Frames go through the
normal render path, so the numbers include everything the user would see.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import qvp  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    videos = [Path(argument) for argument in sys.argv[1:]]
    with tempfile.TemporaryDirectory(prefix="qvp-bench-") as folder:
        print(f"{'file':<44} {'serial':>8} {'parallel':>9} {'speedup':>8}  grid")
        for index, video in enumerate(videos, 1):
            out = Path(folder) / f"case{index}"
            timings = {}
            grid = ""
            for workers in (1, 0):
                started = time.perf_counter()
                code = qvp.main(["--force", "-q", "-o", str(out), "--decode-workers", str(workers), str(video)])
                timings[workers] = time.perf_counter() - started
                if code not in (0, 1):
                    print(f"{video.name[:44]:<44} failed with rc={code}")
                    break
                if not grid:
                    sheet = next(out.glob("*_collage.jpg"), None)
                    if sheet is not None:
                        with __import__("PIL.Image", fromlist=["Image"]).open(sheet) as image:
                            width, height = image.size
                            grid = f"{width}x{height}"
            if len(timings) == 2:
                serial, parallel = timings[1], timings[0]
                print(
                    f"{video.name[:44]:<44} {serial:7.2f}s {parallel:8.2f}s "
                    f"{serial / parallel:7.2f}x  {grid}"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
