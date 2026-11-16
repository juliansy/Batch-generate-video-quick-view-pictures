<div align="center">

<br>

[简体中文](README.zh-CN.md) · **English**

<br>

</div>

<div align="center">

![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-4C566A)
![moviepy](https://img.shields.io/badge/moviepy-2.x-2EA043)
![License](https://img.shields.io/badge/license-GPL--3.0-blue)
[![Release](https://img.shields.io/github/v/release/juliansy/video-quick-view?color=orange&label=release)](https://github.com/juliansy/video-quick-view/releases)
![Stars](https://img.shields.io/github/stars/juliansy/video-quick-view?color=yellow)

</div>

# Batch Video Quick View

Point it at a folder of videos and get one contact sheet per video: a grid of evenly spaced frames, each stamped with its timecode. Enough to tell what a file is without opening a player.

**Download:** [latest release](https://github.com/juliansy/video-quick-view/releases/latest) — a zip with `qvp.py`, both READMEs and the license.

## What it does

- Finds every video you point at: `.mp4` `.m4v` `.mov` `.avi` `.mkv` `.webm` `.flv` `.wmv` `.mpg` `.mpeg` `.ts` `.m2ts`.
- Picks the grid from the length: **2×2 → 3×2 → 3×3 → 4×3 → 4×4 → 5×4 → 5×5**, denser early and levelling off later.
- Stamps each frame with its timecode (`00:26`, or `1:01:05` past an hour) in red with a dark outline.
- Glues them into that grid with a white border and saves `sheets/<name>_collage.jpg`.
- Skips work it has already done, and tells you why each file was skipped or failed.

## What a folder looks like

```text
D:\Videos\
├── qvp.py              the script
├── lecture-01.mp4      a video it will read
├── talk-02.mp4         another one
└── sheets\             created on the first run
    ├── lecture-01_collage.jpg
    └── talk-02_collage.jpg
```

With no arguments the script reads its own folder, so the videos have to sit next to `qvp.py`. Pass a folder (or several files) to work somewhere else.

## Requirements

- Python 3.9 or newer
- Two packages:

```text
pip install "moviepy>=2" pillow
```

- FFmpeg: a system `ffmpeg` is used when present (roughly 2× faster); otherwise the copy bundled with moviepy is used. Nothing extra to install.

## How to use

Double-click **`qvp.bat`**, or drop a folder on it. It runs `qvp.py` with the defaults and pauses so the window stays open.

From a terminal:

```text
python qvp.py                        # videos next to the script
python qvp.py D:\Videos              # one folder
python qvp.py D:\Videos\a.mp4        # a single file
python qvp.py D:\Videos -R -j 4      # subfolders too, four at a time
python qvp.py -n D:\Videos           # show the plan, write nothing
python qvp.py -g 4x4 D:\Videos       # force one grid instead of auto
```

### Options

| Option | Default | Meaning |
| --- | --- | --- |
| `-o, --out DIR` | `<video folder>/sheets` | where the sheets go |
| `--frames N` | one per cell | frames per video; picks the smallest grid that holds them |
| `-g, --grid CxR` | `auto` | columns × rows, or `auto` to pick from the length |
| `-b, --border PX` | 2 | white border around every frame |
| `-c, --color C` | `red` | timecode colour |
| `--font PATH` | auto | font file for the timecode |
| `--font-size PX` | auto | timecode size (scaled to the cell by default) |
| `--time-format auto\|hms\|ms` | auto | `00:26`, `00:00:26`, `26:00` |
| `-R, --recursive` | off | include subfolders |
| `-j, --jobs N` | 1 | render N videos at once |
| `--decode-workers N` | auto | ffmpeg processes pulling frames in parallel; `1` = sequential, `0` = pick from the core count |
| `--cuda` | off | decode frames on the GPU; falls back to software |
| `--batch-seek N` | 4 on GPU, 1 on CPU | timestamps carried by one ffmpeg process; batching amortises decoder start-up |
| `-f, --force` | off | overwrite existing sheets |
| `-n, --dry-run` | off | analyse only |
| `--max-pixels N` | 200,000,000 | refuse canvases above this size |
| `--ffmpeg PATH` | auto | ffmpeg to try first |
| `--log FILE` | — | append a run log |
| `-q, --quiet` | off | only the summary line |
| `-V, --version` | — | print the version |

Exit codes: `0` all done or skipped, `1` at least one failure, `2` bad arguments, `130` interrupted.

### Output

```text
[1/2] lecture-01.mp4 … ok
#  file            grid  frames  canvas     time    result
-  --------------  ----  ------  ---------  ------  ------
1  lecture-01.mp4  4x4   16      7696x4336  3.81s   ok
2  talk-02.mp4     2x2   4       648x488    3.27s   ok

2 done, 0 skipped, 0 failed in 7.7s
```

`canvas` is the size of the JPEG, `time` is how long that file took. A second run over the same folder reports `skipped: already exists (use --force to overwrite)`.

Console output is English only.

### Auto grid

Four cells are enough for a two-minute clip and far too few for two hours, so the grid follows the length:

| Length | Grid | Cells | Seconds per cell |
| --- | --- | --- | --- |
| up to 20 s | 2 × 2 | 4 | 5 |
| up to 40 s | 3 × 2 | 6 | 7 |
| up to 1 min | 3 × 3 | 9 | 7 |
| up to 3 min | 4 × 3 | 12 | 15 |
| up to 5 min | 4 × 4 | 16 | 19 |
| up to 12 min | 5 × 4 | 20 | 36 |
| over 12 min | 5 × 5 | 25 | 72+ |

Density grows quickly at the start (a 40 s clip already gets 6 cells) and slowly later, because a short video changes what it shows more often. A 4K 5×5 is 208 MP, over the default budget, so it steps down to 5×4; the rule is "pick from the ladder, then step down until it fits". The reasoning is in [`docs/06-auto-grid.md`](docs/06-auto-grid.md).

### GPU decoding

`--cuda` decodes frames through ffmpeg's CUDA hwaccel and falls back to software automatically; the report marks the result `ok (GPU)` or `ok (software fallback)`. It is off by default.

Gains vary with the GPU, the driver, the ffmpeg build and the codec: some setups see a clear win, others none or worse. Measure on your own files before relying on it:

```text
python tools/bench_hw.py "D:\Videos\clip.mp4"
```

Keep `--batch-seek` at its default (4 with `--cuda`), because one ffmpeg process per frame pays the CUDA context setup for every frame. On small cards watch VRAM: a batch of eight 4K inputs can approach 3.5 GB.

## Safety

- Inputs are only read. The sheet is written to a temp file, reopened and checked, then swapped in with an atomic replace.
- One broken video does not stop the batch: it is reported as `failed` with a reason, the rest keep going, exit code is `1`.
- Existing sheets are skipped unless you pass `--force`.
- Nothing is deleted, ever.

## Limitations

- Frames are taken at fixed intervals, not on scene changes: a long still shot can repeat in several cells.
- One image per video at source resolution. 4 × 4 of 1080p is a ~33 MP JPEG and 5 × 4 is ~42 MP; 4 × 4 of 4K is ~133 MP and needs ~0.7 GB of RAM. `--max-pixels` refuses anything bigger than 200 MP.
- The first and the last second are skipped, so a fade-in or end card is not the first or last cell — unless the video is black there anyway.
- Frames are found by seeking: each seek decodes from the previous keyframe up to the wanted moment, which is why a 4K sheet takes seconds even with parallel workers. `--batch-seek` and `--decode-workers` trade memory for speed.
- Only the picture is used. Audio, subtitles and cover art are ignored.

## Project docs

Design, review and measurement notes, kept for anyone who wants the reasoning behind the defaults (written in Chinese):

- [docs/01-decomposition.md](docs/01-decomposition.md) - the earlier script, line by line
- [docs/02-review.md](docs/02-review.md) - its defects, with evidence
- [docs/03-design.md](docs/03-design.md) - the current flow, and why
- [docs/04-code-review.md](docs/04-code-review.md) - a review of the implementation
- [docs/05-test-report.md](docs/05-test-report.md) - test results, timings and memory
- [docs/06-auto-grid.md](docs/06-auto-grid.md) - why 2×2 / 3×3 / 4×4 / 5×5, with measured data
- [docs/07-performance.md](docs/07-performance.md) - profiler traces, optimisations, rejected ideas, GPU measurements

## Tests

```text
python -m unittest discover -s tests -v
```

## License

GPL-3.0 — see [LICENSE](LICENSE).
