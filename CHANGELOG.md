# Changelog

## v2.9.7

- Rotation is read from the container display matrix only. The tag fallback added in v2.9.6 never ran - ffprobe was never asked for `stream_tags` - so it was dead code guarded by a test that re-implemented it. Both are gone, and a bare `rotate` tag that ffmpeg ignores is now a documented limitation instead of a claim.
- `_rotation_value` also survives `inf` and integers too large for a float; both used to escape the probe and could still abort a batch.
- Ctrl-C now stops queued work: a decode waiting for its semaphore slot raises instead of starting a fresh ffmpeg after the interrupt.
- `decode_budget()` no longer takes an ignored `jobs` argument, and `qvp.py` and the tests are formatted at 100 columns.

Note: v2.9.2 and v2.9.5 were internal builds folded into v2.9.3 and v2.9.6; neither was tagged, which is why the release list skips them.

## v2.9.6

- Ctrl-C now ends a running ffmpeg instead of waiting for its timeout: the wait in the main thread is a short poll, so an interrupt is noticed at once and the child is killed.
- A container with unreadable rotation metadata (`rotate: "abc"`) is decoded normally instead of aborting the whole batch with a `ValueError`; the tag lookup is also case-insensitive, so MKV's `ROTATE` is honoured.
- The decode budget is a run-wide semaphore: `-j 16` no longer starts sixteen decoders, and one video with `-j 4` gets the whole budget instead of a quarter of it.
- The batch-seek test now asserts that the batched decoder really ran, instead of passing with it disabled.
- `--time-format` help shows a real example (`3661 s` is `61:01`).

## v2.9.5

- Stale temp files of every sheet in a folder are cleaned on the single folder scan again; the scan had been narrowed to the current sheet, so other sheets' leftovers survived.
- Ctrl-C also stops ffmpeg on the default single-job path, and an interrupted run no longer waits for its worker pool before exiting.
- README: the sample transcript is from this version, `--frames` documents its 25-frame limit, the 4K 4x4 memory figure matches the measured 11 bytes per pixel, and the exit-code line explains when a missing path is only a warning.
- docs/07 (declared current) now matches the code on threads, test count and the 208 MP memory peak; the grid spelling list has `4×4` back.
- `requirements.txt` says that Pillow 11.3 is only needed for `--format avif`.

## v2.9.4

- After the first frame that needs scaling (a file spliced out of differently sized parts), the rest of that file goes straight to the scaling decoder instead of decoding every high-resolution frame twice.
- The "same folder spelled twice" test uses a temp folder instead of the working directory, so it cannot touch whatever is in the current directory when the suite runs.

## v2.9.3

- Rotation metadata is honoured: a clip tagged 90 degrees is probed upright and its cells match the decoded frames, instead of being transposed inside a landscape cell.
- Ctrl-C stops the ffmpeg processes that are running; it no longer waits for a 120 s or 25 min timeout per child.
- `-j` shares one decode budget instead of multiplying it, so four parallel videos no longer start sixteen decoders.
- `--frames` above 25 asks for an explicit `--grid` instead of failing per file; a path that does not exist exits `2`; `--quality` help no longer claims the wrong default.
- Redirected output is UTF-8, so emoji file names survive a pipe or a log file.
- AVIF sheets are verified by header only, the stale-temp scan runs once per folder, and the batched decode path is covered by tests.

## v2.9.1

- Documentation only: the READMEs describe the current encoder settings instead of comparing them with older ones, the pixel budget in the docs matches the 320 MP default, example commands quote their paths, and the folder tree explains every file.

## v2.9.0

- JPEG sheets are written at quality 82 with 4:4:4 chroma and progressive coding: the red timecode stays crisp (average red error 7 instead of 34) and the file is about the same size as before.
- `--format avif` writes the same sheet in roughly a third of the bytes (166 MP: 12 MB JPEG vs 4 MB AVIF); the encode takes a few seconds longer.
- `--quality 1-100` overrides the encoder quality.
- The default `--max-pixels` budget is 320,000,000, so a 4K 5x5 sheet (208 MP) is no longer refused. The docs now state the memory cost: about 3 bytes per pixel for the canvas.

## v2.8.0

- The report lists finished files first, then skipped, then failed, each keeping its discovery number, so the failed lines sit together and can be copied in one block.
- Frames that come back empty are retried with a slower accurate seek: MPEG-TS captures that failed with `Missing reference picture` now render. Healthy files keep the fast path.
- Files spliced out of differently sized parts (720p then 1080p) are scaled into the cell and padded instead of failing with `frame ... does not match the probed ...`.
- Portrait videos get their own ladder, from `4x1` for 6 s clips to `8x3` beyond 3 minutes; detected with one size comparison, no extra probe.
- Grids accept `4x4`, `4X4`, `4*4`, `4×4` and `4,4`; the docs and the report use `4x4` everywhere.

## v2.7.3

- Two videos with the same stem (`a.mp4`, `a.mkv`) now share one sheet: the first renders, the second is skipped with the reason, and the exit code stays `0`.
- The summary line separates counts from elapsed time: `1 done, 1 skipped, 0 failed | 0.78s`.

## v2.7.2

- License changed from GPL-3.0 to MIT.

## v2.7.1

- README condensed and reorganised around usage: what the tool does, how to run it, one table for every flag, an output example and the limitations.
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