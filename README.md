<div align="center">

<br>

[简体中文](README.zh-CN.md) · **English**

<br>

</div>

<div align="center">

![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-4C566A)
![moviepy](https://img.shields.io/badge/moviepy-2.x-2EA043)
![License](https://img.shields.io/badge/license-MIT-green)
[![Release](https://img.shields.io/github/v/release/juliansy/video-quick-view?color=orange&label=release)](https://github.com/juliansy/video-quick-view/releases)
![Stars](https://img.shields.io/github/stars/juliansy/video-quick-view?color=yellow)

</div>

# Batch Video Quick View

One contact sheet per video: evenly spaced frames stamped with their timecode. Enough to recognise a file without opening a player.

**Download:** [latest release](https://github.com/juliansy/video-quick-view/releases/latest) — `qvp.py`, `qvp.bat`, `requirements.txt`, both READMEs and the license.

## What it does

- Reads every video it finds: `.mp4` `.m4v` `.mov` `.avi` `.mkv` `.webm` `.flv` `.wmv` `.mpg` `.mpeg` `.ts` `.m2ts`.
- Picks the grid from the length and shape: a landscape ladder **2x2 → 3x2 → 3x3 → 4x3 → 4x4 → 5x4 → 5x5**, a portrait one **4x1 → 8x3**.
- Honours the rotation flag phones write, so vertical clips come out upright.
- Stamps each frame with its timecode (`00:26`, or `1:01:05` past an hour).
- Saves `sheets/<name>_collage.jpg`.
- Skips sheets that already exist, and says why a file was skipped or failed.

### Format and size

JPEG is the default: every viewer, browser and chat window opens it. Sheets are written at quality 82 with full-resolution chroma, which keeps the thin red timecode crisp instead of smearing it into the background.

`--format avif` writes the same sheet in about a third of the bytes (166 MP: 12 MB JPEG vs 4 MB AVIF) for a slower encode. AVIF needs a recent viewer: Windows 11 Photos, Chrome, Edge, Firefox and macOS Preview open it; Windows 10 needs the free AVIF extension from the Store.

Memory is the real cost, and it is measured, not estimated: a 100 MP sheet peaked at 1.1 GB and a 208 MP one at 2.2 GB, about 11 bytes per pixel (canvas, encoder buffer and the frames in flight). `--jobs 4` keeps four of those alive at once. `--max-pixels` (default 320,000,000) is the guard; on a small machine lower it, use `-j 1`, and lower `--decode-workers` so fewer frames are in flight.

## Layout

```text
D:\Videos\
├── qvp.py                          the script
├── lecture-01.mp4                  a video it will read
├── talk-02.mp4                     another one
└── sheets\                         created on the first run
    ├── lecture-01_collage.jpg      the sheet made from lecture-01.mp4
    └── talk-02_collage.jpg         the sheet made from talk-02.mp4
```

With no arguments it reads its own folder; pass a folder or files to work elsewhere.

## Requirements

- Python 3.9 or newer
- `pip install "moviepy>=2" pillow` (AVIF output needs Pillow 11.3 or newer; JPEG works on older)
- ffmpeg is recommended: `winget install Gyan.FFmpeg`, or any build on `PATH`

ffmpeg is optional: a system copy is used when present (about 2× faster), otherwise the one bundled with moviepy.

## Usage

Double-click **`qvp.bat`**, or drop a folder on it. From a terminal:

```text
python qvp.py                             # videos next to the script
python qvp.py "D:\Videos"                 # one folder
python qvp.py "D:\Videos" -R -j 4         # subfolders too, four at a time
python qvp.py -n "D:\Videos"              # plan only, write nothing
python qvp.py -g 4x4 "D:\Videos"          # fixed grid instead of auto
```

### Options

| Option | Default | Meaning |
| --- | --- | --- |
| `-o, --out DIR` | `<video folder>/sheets` | where sheets go |
| `--frames N` | one per cell | frames per video; picks the smallest grid that holds them (up to 25 - more needs an explicit `--grid`) |
| `-g, --grid CxR` | `auto` | columns x rows (`4x4`, `4*4`, `4×4`, `4,4` all work), or `auto` |
| `-b, --border PX` | 2 | white border around each frame |
| `-c, --color C` | `red` | timecode colour |
| `--font PATH` | auto | font file for the timecode |
| `--font-size PX` | auto | timecode size, scaled to the cell |
| `--time-format auto\|hms\|ms` | auto | `auto`: `00:26` (adds the hour when needed); `hms`: always `00:00:26`; `ms`: total minutes, so `3661 s` is `61:01` |
| `-R, --recursive` | off | include subfolders |
| `-j, --jobs N` | 1 | videos to render at once |
| `--cuda` | off | decode frames on the GPU; falls back to software |
| `--batch-seek N` | 4 with `--cuda`, else 1 | seeks carried by one ffmpeg process |
| `--decode-workers N` | auto (~cpu/4) | decode processes for the whole run, shared by `-j` |
| `-f, --force` | off | overwrite existing sheets |
| `-n, --dry-run` | off | analyse only |
| `--max-pixels N` | 320,000,000 | refuse larger canvases (peak RAM is ~11 bytes per pixel) |
| `--format jpeg\|avif` | `jpeg` | sheet format; AVIF is about a third of the size, slower to write |
| `--quality 1-100` | 82 jpeg / 60 avif | encoder quality |
| `--ffmpeg PATH` | auto | ffmpeg to try first |
| `--log FILE` | — | append a run log |
| `-q, --quiet` | off | summary line only |
| `-V, --version` | — | print the version |

Exit codes: `0` everything ok or skipped (an existing folder with no videos also exits `0`; a path that does not exist is only a warning while other inputs remain), `1` at least one file failed, `2` bad arguments, no usable input at all, or no ffmpeg/moviepy, `130` interrupted.

## Output

```text
qvp 2.10.0
2 video(s) | grid auto | sheets/ next to each video
[1/2] lecture-01.mp4 … ok
[2/2] talk-02.mp4 … ok
#  file            grid  frames  canvas     time   result
-  --------------  ----  ------  ---------  -----  ------
1  lecture-01.mp4  4x3   12      5136x2172  1.21s  ok
2  talk-02.mp4     2x2   4       2568x1448  0.40s  ok

2 done, 0 skipped, 0 failed | 1.85s
```

`canvas` is the sheet size in pixels, `time` is how long that file took. Labels and error text are English; a message coming from the video itself is passed through as ffmpeg phrased it.

## Online videos

`qvp_online.py` is the same sheet, built from a URL instead of a file. It asks [yt-dlp](https://github.com/yt-dlp/yt-dlp) for the direct stream URL and lets ffmpeg seek inside the remote stream, so it never downloads the whole video.

```bat
python qvp_online.py "https://www.bilibili.com/video/BV..."
python qvp_online.py -g 4x4 --frame-workers 6 URL1 URL2
```

It needs `yt-dlp` next to `ffmpeg`, and it sends the `Referer`/`User-Agent` a CDN expects. Signed URLs expire after an hour or two; the script resolves again instead of failing the job. Cost per frame is roughly bitrate x keyframe interval, so few cells on a low-bitrate stream is where this wins - [`docs/09`](docs/09-online.md) has the numbers, the flags and the cases where downloading a small copy is cheaper.

## Auto grid

| Length | Grid | Cells | Seconds per cell |
| --- | --- | --- | --- |
| up to 20 s | 2x2 | 4 | 5 |
| up to 40 s | 3x2 | 6 | 7 |
| up to 1 min | 3x3 | 9 | 7 |
| up to 3 min | 4x3 | 12 | 15 |
| up to 5 min | 4x4 | 16 | 19 |
| up to 12 min | 5x4 | 20 | 36 |
| over 12 min | 5x5 | 25 | 29–72+ |

Portrait (taller than wide — short vertical video packs more per second, so the
cells stay tall and the rows come slowly):

| Length | Grid | Cells |
| --- | --- | --- |
| up to 6 s | 4x1 | 4 |
| up to 10 s | 5x1 | 5 |
| up to 15 s | 6x1 | 6 |
| up to 20 s | 4x2 | 8 |
| up to 28 s | 5x2 | 10 |
| up to 38 s | 6x2 | 12 |
| up to 1 min | 7x2 | 14 |
| up to 3 min | 8x2 | 16 |
| over 3 min | 8x3 | 24 |

Dense early, flatter later; a portrait sheet is chosen with one size comparison, no extra probe. A 4K 5x5 is 208 MP and fits the default 320 MP budget; a bigger canvas steps down rung by rung until it fits. Details in [`docs/06-auto-grid.md`](docs/06-auto-grid.md).

## GPU decoding

`--cuda` decodes through ffmpeg's CUDA hwaccel and falls back to software; the report marks `ok (GPU)` or `ok (software fallback)`. It is off by default and gains depend on GPU, driver, ffmpeg build and codec — measure with `tools/bench_hw.py` before relying on it. Keep `--batch-seek` at its default (4 with `--cuda`); on small cards a batch of eight 4K inputs can reach ~3.5 GB of VRAM.

## Safety

- Inputs are only read. Sheets are written to a temp file, checked (JPEG is decoded once at 1/8 size; AVIF is only checked at the container level), then swapped in atomically.
- One broken video does not stop the batch: it is reported as `failed`, the rest continue, exit code `1`.
- Existing sheets are skipped unless `--force`.
- The only files removed are its own `.tmp-*` leftovers, and only when they are over an hour old.

## Limitations

- Frames are taken at fixed intervals, not on scene changes.
- One image per video at source resolution: 4x4 of 4K is ~133 MP and needs ~1.4 GB RAM; `--format avif` shrinks the file, not the memory.
- The first and last second are skipped; clips under 4 s use a quarter of their length instead.
- Seeking costs time: each frame decodes from the previous keyframe, so 4K sheets take seconds even in parallel.
- Only the picture is used; audio, subtitles and cover art are ignored.
- A file spliced out of parts with different sizes (720p then 1080p) is fitted into the cell the probe reported, scaled and padded, never stretched.
- Some MPEG-TS captures return nothing for a fast seek near the tail; the frame is retried with a slower accurate seek, so the file works but takes a little longer.
- Rotation comes from the container display matrix. A bare `rotate` tag that ffmpeg itself ignores is not applied, so such a file keeps the orientation ffmpeg decodes.
- Two files with the same stem (`talk.mp4`, `talk.mkv`) share one sheet name: the one that sorts first (`talk.mkv`) is rendered and the other is skipped, so rename one if you need both.

## Notes

Before publishing, run `python tools\release_check.py` (and `tools\make_package.py` for the archive); the gate and the human checklist are described in [`docs/08`](docs/08-release.md).

Design, review and measurement notes, in Chinese: [`docs/06`](docs/06-auto-grid.md) and [`docs/07`](docs/07-performance.md) describe the current defaults; `docs/01`-`docs/05` are records from the v1 to v2 rewrite and are kept for the reasoning, not as a description of today's code.

## License

MIT — see [LICENSE](LICENSE).
