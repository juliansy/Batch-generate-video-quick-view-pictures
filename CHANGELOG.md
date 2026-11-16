# Changelog

## v2.7.1

- Documentation pass for readers who have never seen this repo: the README explains what the tool does, how to run it and what the flags change, instead of describing the development setup.
- Privacy scrub: test-material names, local folder paths and machine-specific commentary were removed from the docs; performance notes now label clips A-H.
- Old releases and history were rebuilt for the same reason (nothing else changed in the code).

## v2.7.0

- GPU decoding is a plain switch again: `--cuda` on, default off. The `auto` policy keyed on AV1/HEVC was fitted to one machine and is gone.
- The README no longer makes any claim about whether the GPU is faster; it states the mechanism, one sentence about the local observation, and points at `docs/07-performance.md` for the measurements.
- `docs/07-performance.md` keeps the raw numbers, GPU utilisation and open questions from a single test machine.

## v2.6.0

- `--batch-seek N`: one ffmpeg process can carry several seeks (default 4 on the GPU, 1 on the CPU), amortising decoder start-up; each input needs its own `-hwaccel` flags, which is what makes batched CUDA work at all.
- `--hwaccel auto` now picks the GPU only for **AV1 and HEVC** — the codecs where the CPU decoder is the bottleneck on this machine; `--hwaccel cuda` still forces it.
- GPU numbers corrected and scoped: per-frame CUDA was slower in 6 of 8 4K clips, but batched CUDA was fastest in 7 of 8, and end to end 4K AV1 went from 13.7 s to 8.7 s (1.57×). No general claim is made now; the machine, driver, codecs and sample sizes are stated.
- `docs/07-performance.md` carries the raw measurements, GPU utilisation (9–47%) and the open questions (driver version, feeding strategy, 10-bit path).

## v2.4.0

- `--hwaccel none|cuda|auto` (advanced): decode frames on the GPU through `-hwaccel cuda -hwaccel_output_format cuda` + `hwdownload`, with automatic software fallback and an `ok (GPU)` / `ok (software fallback)` note in the report.
- Measured on four clips: GPU decoding is 0.45–0.93× the software speed, because one CUDA context per frame costs more than the frame. Off by default; documented with numbers in the README and `docs/07-performance.md`.
- `tools/bench_hw.py` reproduces the comparison on your own machine; `QVP_TEST_CUDA=1` runs the GPU/software pixel-equality test.

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