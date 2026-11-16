# Changelog

## v2.7.1

- README reorganised around usage: what the tool does, how to run it, one table for every flag, an output example and the limitations.
- Performance notes refer to test clips as A–H; no test-material names or local folder paths remain in the repository.

## v2.7.0

- `--cuda` is a plain on/off switch for GPU decoding. `--hwaccel` (and the codec-based choice it carried) is gone.
- Software decoding stays the default; the report marks a GPU run `ok (GPU)` and a fallback `ok (software fallback)`.

## v2.6.0

- `--batch-seek N`: one ffmpeg process carries several seeks (4 with `--cuda`, 1 without), which amortises decoder start-up.
- `--cuda` defaults to 4 seeks and two parallel chunks; each input gets its own hwaccel flags.

## v2.4.0

- Optional GPU decoding behind `--cuda`, with automatic software fallback and a note in the report.
- `tools/bench_hw.py` compares software and GPU on your own files; `QVP_TEST_CUDA=1` adds a pixel-equality test.

## v2.3.0

- Frames are decoded in parallel: `workers = min(4, cpu/4, frames)` ffmpeg processes, each capped at `cpu/workers` threads. Measured 1.3–2.3× faster end to end.
- `--decode-workers N` overrides it (`1` = sequential, `0`/omitted = auto).
- The white border no longer costs a full-size copy per frame: the frame is pasted at an offset onto the white canvas.
- `docs/07-performance.md` records the profiler traces, the rejected options and the remaining decode cost.

## v2.2.0

- Sheets now land in `sheets/` instead of `output/`.
- Every sheet skips the first **and** the last second, so a fade-in or an end card does not become the first or last cell.
- Denser grid ladder with non-square grids: 2×2 (≤20 s), 3×2 (≤40 s), 3×3 (≤1 min), 4×3 (≤3 min), 4×4 (≤5 min), 5×4 (≤12 min), 5×5 beyond.
- Probing switched from moviepy to ffprobe: 70 ms per video instead of 1019 ms, so a 30-video folder plans in 2.3 s instead of 15.8 s.
- The run prints its version and the video count before probing instead of staying silent.
- `--frames` picks the first ladder step that holds the frames (4 → 2×2, 6 → 3×2, 10 → 4×3).

## v2.1.0

- The grid is chosen from the video length: 2×2 up to 5 minutes, 3×3 up to 20, 4×4 up to an hour, 5×5 beyond; the pixel budget can shrink it one step.
- `--frames N` now picks the smallest grid that holds N cells, instead of requiring a matching `--grid`.
- `qvp.bat` added: double-click, or drop a folder on it, and it runs with the defaults.
- `NUM_FRAMES` is gone; the grid decides how many frames a video gets.
- Repository renamed from `Batch-generate-video-quick-view-pictures` to `video-quick-view`.

## v2.0.0

- Rewritten as a planned pipeline: discover → plan (no writes) → render (per-file isolation) → report.
- Real CLI: paths, `--frames`, `--grid`, `--border`, `--color`, `--out`, `-R`, `-j`, `-f`, `-n`, `--log`, `-q`, `--time-format`, `--max-pixels`.
- Atomic output, skip-by-default, per-file status and exit codes.
- ffmpeg fast-seek extraction with a three-level fallback; 2.6× faster and ~3× less peak memory on 4K than v1.
- 49 automated tests, plus `docs/01`–`docs/05`.

## v1.1.0

- README rewritten in English and Chinese, `.gitignore`, and the script renamed from `qvp` to `qvp.py` (content unchanged).

## v1.0.0

- First public version: a 76-line script that walks its own folder and writes one collage per video.