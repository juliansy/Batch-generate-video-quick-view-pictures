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

**Download:** [latest release](https://github.com/juliansy/video-quick-view/releases/latest) — `qvp.py`, `qvp.bat`, both READMEs and the license.

## What it does

- Reads every video it finds: `.mp4` `.m4v` `.mov` `.avi` `.mkv` `.webm` `.flv` `.wmv` `.mpg` `.mpeg` `.ts` `.m2ts`.
- Picks the grid from the length: **2×2 → 3×2 → 3×3 → 4×3 → 4×4 → 5×4 → 5×5**.
- Stamps each frame with its timecode (`00:26`, or `1:01:05` past an hour).
- Saves `sheets/<name>_collage.jpg`.
- Skips sheets that already exist, and says why a file was skipped or failed.

## Layout

```text
D:\Videos\
├── qvp.py              the script
├── lecture-01.mp4      a video it will read
├── talk-02.mp4         another one
└── sheets\             created on the first run
    ├── lecture-01_collage.jpg
    └── talk-02_collage.jpg
```

With no arguments it reads its own folder; pass a folder or files to work elsewhere.

## Requirements

- Python 3.9 or newer
- `pip install "moviepy>=2" pillow`

ffmpeg is optional: a system copy is used when present (about 2× faster), otherwise the one bundled with moviepy.

## Usage

Double-click **`qvp.bat`**, or drop a folder on it. From a terminal:

```text
python qvp.py                        # videos next to the script
python qvp.py D:\Videos              # one folder
python qvp.py D:\Videos -R -j 4      # subfolders too, four at a time
python qvp.py -n D:\Videos           # plan only, write nothing
python qvp.py -g 4x4 D:\Videos       # fixed grid instead of auto
```

### Options

| Option | Default | Meaning |
| --- | --- | --- |
| `-o, --out DIR` | `<video folder>/sheets` | where sheets go |
| `--frames N` | one per cell | frames per video; picks the smallest grid that holds them |
| `-g, --grid CxR` | `auto` | columns × rows, or `auto` from the length |
| `-b, --border PX` | 2 | white border around each frame |
| `-c, --color C` | `red` | timecode colour |
| `--font PATH` | auto | font file for the timecode |
| `--font-size PX` | auto | timecode size, scaled to the cell |
| `--time-format auto\|hms\|ms` | auto | `00:26`, `00:00:26`, `26:00` |
| `-R, --recursive` | off | include subfolders |
| `-j, --jobs N` | 1 | videos to render at once |
| `--cuda` | off | decode frames on the GPU; falls back to software |
| `--batch-seek N` | 4 with `--cuda`, else 1 | seeks carried by one ffmpeg process |
| `--decode-workers N` | auto | ffmpeg processes pulling frames in parallel |
| `-f, --force` | off | overwrite existing sheets |
| `-n, --dry-run` | off | analyse only |
| `--max-pixels N` | 200,000,000 | refuse larger canvases |
| `--ffmpeg PATH` | auto | ffmpeg to try first |
| `--log FILE` | — | append a run log |
| `-q, --quiet` | off | summary line only |
| `-V, --version` | — | print the version |

Exit codes: `0` ok, `1` some file failed, `2` bad arguments, `130` interrupted.

## Output

```text
[1/2] lecture-01.mp4 … ok
#  file            grid  frames  canvas     time    result
-  --------------  ----  ------  ---------  ------  ------
1  lecture-01.mp4  4x4   16      7696x4336  3.81s   ok
2  talk-02.mp4     2x2   4       648x488    3.27s   ok

2 done, 0 skipped, 0 failed in 7.7s
```

`canvas` is the JPEG size, `time` is how long that file took. Console output is English only.

## Auto grid

| Length | Grid | Cells | Seconds per cell |
| --- | --- | --- | --- |
| up to 20 s | 2 × 2 | 4 | 5 |
| up to 40 s | 3 × 2 | 6 | 7 |
| up to 1 min | 3 × 3 | 9 | 7 |
| up to 3 min | 4 × 3 | 12 | 15 |
| up to 5 min | 4 × 4 | 16 | 19 |
| up to 12 min | 5 × 4 | 20 | 36 |
| over 12 min | 5 × 5 | 25 | 72+ |

Dense early, flatter later. A 4K 5×5 is 208 MP, over the default budget, so it steps down to 5×4. Details in [`docs/06-auto-grid.md`](docs/06-auto-grid.md).

## GPU decoding

`--cuda` decodes through ffmpeg's CUDA hwaccel and falls back to software; the report marks `ok (GPU)` or `ok (software fallback)`. It is off by default and gains depend on GPU, driver, ffmpeg build and codec — measure with `tools/bench_hw.py` before relying on it. Keep `--batch-seek` at its default (4 with `--cuda`); on small cards a batch of eight 4K inputs can reach ~3.5 GB of VRAM.

## Safety

- Inputs are only read. Sheets are written to a temp file, verified, then swapped in atomically.
- One broken video does not stop the batch: it is reported as `failed`, the rest continue, exit code `1`.
- Existing sheets are skipped unless `--force`.
- Nothing is deleted.

## Limitations

- Frames are taken at fixed intervals, not on scene changes.
- One image per video at source resolution: 4×4 of 4K is ~133 MP and needs ~0.7 GB RAM.
- The first and last second are skipped.
- Seeking costs time: each frame decodes from the previous keyframe, so 4K sheets take seconds even in parallel.
- Only the picture is used; audio, subtitles and cover art are ignored.

## Notes

Design, review and measurement documents behind the defaults (written in Chinese): [`docs/01`](docs/01-decomposition.md)–[`docs/07`](docs/07-performance.md).

## License

MIT — see [LICENSE](LICENSE).
