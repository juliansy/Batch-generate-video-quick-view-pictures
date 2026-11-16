"""Compare software and GPU decoding on your machine.

    python tools/bench_hw.py "D:\\Videos\\a.mp4" ["D:\\Videos\\b.mp4" ...]

Each file is rendered twice (default, then ``--cuda``) into a temporary
folder. Frame extraction runs through the normal render path.

Expect large differences per codec: on the machine this was written on, CUDA
lost on VP9 and H.264 but won on AV1 once seeks were batched. Do not read a
single number as a general rule - check the codec column.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QVP = ROOT / "qvp.py"


def codec_of(video: Path) -> str:
    done = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True,
    )
    return (done.stdout or "?").strip() or "?"


def has_cuda() -> bool:
    try:
        done = subprocess.run(["ffmpeg", "-hide_banner", "-hwaccels"], capture_output=True, text=True, timeout=20)
    except OSError:
        return False
    return done.returncode == 0 and "cuda" in done.stdout.split()


def render(video: Path, out: Path, extra: list[str]) -> tuple[float, int, str]:
    started = time.perf_counter()
    done = subprocess.run(
        [sys.executable, str(QVP), "-f", "-o", str(out), *extra, str(video)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    elapsed = time.perf_counter() - started
    note = ""
    for line in done.stdout.splitlines():
        if line.startswith("1  ") and "ok" in line:
            note = line.split("ok", 1)[1].strip(" ()") or "cpu"
    return elapsed, done.returncode, note


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    if not has_cuda():
        print("this ffmpeg has no CUDA support; nothing to compare")
        return 1
    print(f"{'file':<38} {'codec':<6} {'off':>8} {'cuda':>8}  cuda used")
    with tempfile.TemporaryDirectory(prefix="qvp-hw-") as folder:
        for index, argument in enumerate(sys.argv[1:], 1):
            video = Path(argument)
            times = {}
            note = ""
            for label, extra in (("off", []), ("on", ["--cuda"])):
                times[label], code, used = render(video, Path(folder) / f"{index}-{label}", extra)
                if code not in (0, 1):
                    times[label] = float("nan")
                if label == "on":
                    note = used
            print(
                f"{video.name[:38]:<38} {codec_of(video):<6} {times['off']:7.2f}s "
                f"{times['on']:7.2f}s  {note}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
