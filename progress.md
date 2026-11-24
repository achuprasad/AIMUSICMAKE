# Progress — Local Audio Studio

## Phase 2: professional UI, live progress, speed and quality assurance (2026-11-23)

### Delivered
- New FastAPI server (`server.py`) and single-page UI (`static/index.html`) replacing the Gradio prototype.
- Live extraction progress: real percentage from the models' own chunk loops, current step, elapsed time, ETA and a 4-step tracker.
- Stem mixer: synced playback of all stems, mute / solo / volume per stem, waveform seek, export mix.
- Tools: vocal remover / stem splitter (BS-RoFormer, Mel-Band RoFormer, Demucs 2/4/6), pitch & tempo, key & BPM (with Camelot), cutter with waveform selection, joiner with crossfade and reordering, converter.
- Speed: default switched to *Fast* after the benchmark showed it is within 0.06 dB of *Max* and 2.8× faster.
- Quality gate `run_tests.ps1` (lint, types, unit, integration, e2e × 2 browsers, security, build, GPU, coverage, benchmark).

## Testing report — gate run 2026-11-23 22:20

Command: `.\run_tests.ps1 -Gpu` · **Verdict: PASS** (exit code 0). The benchmark ran separately at 21:44 (`benchmarks/audio_quality.py --tracks 6`).

| Stage | Executed | Passed | Failed | Skipped |
|---|---|---|---|---|
| 1 Lint (ruff, incl. bandit `S` rules) | ✔ | clean | 0 | — |
| 2 Type check (mypy) | ✔ | clean | 0 | — |
| 3 Unit tests | 88 | 88 | 0 | 0 |
| 4 Integration, security & load tests | 53 | 53 | 0 | 0 |
| 5 Frontend e2e — Chromium | 18 | 18 | 0 | 0 |
| 5 Frontend e2e — Microsoft Edge | 18 | 18 | 0 | 0 |
| 6 Dependency audit (pip-audit) | ✔ | no known vulnerabilities | 0 | torch/torchaudio not auditable (see D1) |
| 7 Build verification | ✔ | ✔ | 0 | — |
| 8 GPU model tests | 11 | 11 | 0 | 0 |
| 8 GPU browser journey | 1 | 1 | 0 | 0 |
| 9 Coverage gate (≥ 85 %) | ✔ | 99 % | — | — |
| Audio-quality benchmark | 43 checks | 43 | 0 | 0 |
| **Total test executions** | **189** | **189** | **0** | **0** |

171 distinct test cases (the 18 UI cases run in both browsers). Catalogue: `docs/test-cases.md`.

### Coverage (engine + server, branch coverage, all stages combined)

| File | Statements | Missed | Branches | Coverage |
|---|---|---|---|---|
| engine.py | 315 | 3 | 64 | 99 % |
| server.py | 158 | 0 | 36 | 99 % |
| **Total** | 473 | 3 | 100 | **99 %** |

Uncovered: `engine.py` 112–113 (fallback if audio-separator's internals move), 156 (empty decode after a successful decode); `server.py` the non-Windows branch of "open folder". Frontend JavaScript has no line-coverage tool (no build step); its critical journeys are covered by e2e.

### Audio quality (median, MUSDB18 test excerpts, 6 tracks) — full table in `docs/audio-quality-benchmarks.md`

| Model | Vocals SDR | Accompaniment SDR | Vocal bleed in instrumental | s per min audio* |
|---|---|---|---|---|
| BS-RoFormer fast (default) | 12.48 dB | 16.29 dB | −30.1 dB | 93 |
| BS-RoFormer best | 12.54 dB | 16.36 dB | −30.1 dB | 261 |
| Mel-Band RoFormer | 11.43 dB | 14.66 dB | −26.7 dB | 99 |
| Demucs 4-stem | 9.32 dB | — | — | 15 |

\*Inflated on 7-second clips by chunk padding; a full 4.5-minute song measured about 2.4 s/s on *best*.

### Defects found by testing and fixed (each has a regression test)

| # | Defect | Severity | Found by | Regression test |
|---|---|---|---|---|
| 1 | Converting to OGG crashed the entire server (libsndfile stack overflow on a Windows worker thread) | Critical | API test | `test_every_format_in_worker_thread`, `test_convert_to_ogg` |
| 2 | `import server` deleted the uploads folder of a running instance (destroyed a live user job at 92 %) | Critical | Live incident during gate run | `test_importing_server_never_deletes_files` |
| 3 | Server start reserved ~300 MB GPU memory, slowing a running separation 13× | High | Observed during testing | engine uses `nvidia-smi` for the GPU name |
| 4 | Loading a second RoFormer model while the first was in GPU memory → out-of-memory | High | GPU smoke test | `test_gpu_memory_is_released_between_engines` |
| 5 | Large uploads blocked the event loop, freezing progress polling | Medium | ruff ASYNC230 | upload handler runs in thread pool |
| 6 | Cutter overwrote typed start/end times when the waveform finished decoding | Medium | Edge e2e | `test_job_failure_state` (Edge) |
| 7 | BPM ~2 % off (librosa's tempo grid) | Medium | Unit test | `test_bpm_of_120_click_track` |
| 8 | Key detection on non-tonal audio produced NaN and a bogus key | Low | Unit test warnings | `test_percussion_reports_no_key_without_nan` |
| 9 | Very short files crashed waveform generation after processing | Low | Unit test | `test_peaks_short_file` |
| 10 | 11 controls without accessible names; dropzone not keyboard-operable | Medium | a11y e2e | `test_every_control_has_an_accessible_name`, `test_keyboard_opens_file_picker` |
| 11 | No validation of options (`format` reached a file name) | Medium | Security review | `TestValidation`, `test_separate_rejects_bad_options` |
| 12 | setuptools 78.1.0 with 5 known CVEs in the environment | Low | pip-audit | pip-audit stage |
| 13 | Test runner reported all-skipped GPU stages as PASS | High (process) | Gate review | runner now reports SKIPPED / INCOMPLETE |
| 14 | ETA calculation divided by zero when two progress updates landed in the same 15 ms clock tick, failing fast jobs (seen as "ZeroDivisionError" in Pitch & Tempo) | High | **User**, during manual use | `test_instant_progress_updates_do_not_crash` (verified to fail on the old code) |
| 15 | Output names containing a dot were truncated: "song (1.25x speed…)" saved as "song (1.mp3" (`Path.with_suffix`) | Medium | e2e test of the new speed control | `TestSaveAudio::test_dots_in_names_are_kept` |

| 16 | After "releasing" the GPU, the server process kept ~700 MB of CUDA context, so another GPU program (and the GPU test suite) ran out of memory on the 4 GB card | High | Quality gate (GPU stage FAIL) | AI moved into a separate worker process that exits when idle: `test_worker_process_returns_all_gpu_memory`, `test_parent_never_initialises_cuda`, `test_crash_mid_job_is_reported_and_next_job_recovers` |

### Defect 17 (2026-11-24): orphaned AI worker held GPU memory after the app was killed
- **Found by:** quality gate GPU stage FAIL (3 of 12 tests: CUDA out of memory, "0 bytes free").
- **Cause:** when the server process is killed abruptly (Task Manager, crash, a test runner stopping it), its
  AI worker child kept running with ~0.8 GB of GPU memory each. Two such orphans (from 2026-11-23 22:56 and
  2026-11-24 08:20) filled the 4 GB card. The same would happen to a user whose app crashes.
- **Also found:** the local gate script had never run `test_desktop.py`, `test_feedback.py`, `test_notify.py`
  (my text-replace edit had silently not applied); CI on GitHub did run them. Fixed; the gate now runs 258
  unit + integration tests instead of 164.
- **Fix:** the worker watches its parent process and exits the moment the parent ends, however it ended.
- **Regression test:** `test_worker_exits_when_parent_is_killed` hard-kills a parent; verified to FAIL
  without the fix and PASS with it; 0 orphans after the full test run.

### Help & Feedback page (2026-11-24, user request)
- Feedback form, roadmap voting, FAQ, own submissions; e-mail to both owners via private `.env` (addresses never in code, responses, HTML or logs).
- Security: CSRF same-origin guard on all write endpoints, 64 KB body limit, security headers, rate limits, honeypot, hourly e-mail cap, header-injection-safe e-mail, XSS-safe rendering.
- Tests: `tests/test_feedback.py`, `tests/test_notify.py` (incl. a real SMTP conversation with a local test server), 6 new e-2-e tests (incl. an XSS attempt). End-to-end check with the real server and the private `.env`: one message delivered to exactly the two owner addresses, none visible to the browser.
- Defects found while building it (fixed before release): the title was copied raw into the e-mail body (header-looking lines); `Origin: null` was initially allowed in a draft of the guard; a draft secrets test flagged a hostname instead of addresses.
- Windows installer test (2026-11-24): **27/27 PASS**: install, files, shortcuts, Apps entry, version info, installed-app smoke test on GPU, uninstall, cleanup, songs kept. The released 1.0.0 installer was built **before** this page existed; the next build will include it.

### Feature changes after user feedback
- Remove / Replace buttons on every uploaded file (`test_replace_file`, `test_removing_file_deletes_upload`).
- Source preview player on every tool; live speed/pitch preview on Pitch & Tempo (`test_live_pitch_and_speed_preview` measures that the shifter outputs real audio).
- AI engine releases all GPU memory after 5 idle minutes; `/api/release-gpu` for other GPU apps and the test runner.

### Gate run 2026-11-23 22:57 (after the worker change): **VERDICT PASS**
Unit 101 · API 63 · e2e Chromium 23 · e2e Edge 23 · GPU 12 · GPU journey 1 · pip-audit clean ·
coverage 98 % (engine 99 %, server 99 %, gpu_worker 95 %). Nothing skipped.

### Earlier feature change after user feedback
- Pitch & Tempo: the "Tempo" slider is now **Speed** (0.50×–2.00×) with 0.75× / 1× / 1.25× / 1.5× presets, plus a **Keep original pitch** switch. Off means tape-style speed change, where the pitch moves with the speed; the hint shows by how many semitones. Tests: `test_tape_mode_speed_also_moves_pitch`, `test_tape_mode_slow_down`, `test_keep_pitch_must_be_boolean`, `test_speed_presets_and_keep_pitch`.

One test was corrected rather than the code: `TestCut::test_duration_and_fades` assumed a 0.3 peak, but ffmpeg test tones peak at 0.088. The assertion now compares against the measured source level and checks the fade just as strictly.

### Unresolved defects and known gaps

| ID | Item | Risk | Plan |
|---|---|---|---|
| D1 | PyTorch 2.5.1 is affected by CVE-2025-32434 (`torch.load` code execution via a malicious checkpoint); fixed in 2.6. pip-audit cannot check CUDA builds. | Medium. Models are fetched only from fixed official sources, but a tampered download would be dangerous. | Upgrade to torch 2.6/2.7 + cu118, then rerun the full gate and benchmark |
| D2 | Firefox e2e blocked: Playwright Firefox fails to start ("side-by-side configuration is incorrect": missing Visual C++ runtime) | Low (Chromium + Edge pass) | Install the Microsoft Visual C++ Redistributable, then add `--browser firefox` |
| D3 | No GPU job timeout or cancel button | Low | Add a cancel endpoint and button |
| D4 | The app keeps the last model in GPU memory between jobs (faster repeat jobs) | Info | GPU tests require the app to be closed; documented |
| D5 | Frontend JS has no line coverage metric | Low | Covered by e2e journeys |
| D6 | Not tested: Locust load, Redis/DB/auth/billing/object storage | N/A | Not part of this local architecture (see `docs/testing-strategy.md`) |

## Phase 1: prototype (2026-11-23)
- Installed Demucs + audio-separator (RoFormer) with CUDA 11.8 PyTorch to suit the 457.34 NVIDIA driver.
- Gradio prototype with all tools; smoke-tested on a synthetic clip. Replaced in phase 2.
