# Cloud team handover — AI Music Editor

**From:** product owner (Achu Prasad) · **Repository:** https://github.com/achuprasad/AIMUSICMAKE (public)
**Date:** 2026-11-23 · **Version:** 1.0.0 (local desktop release)

This document has two parts:
- **Part 1:** exactly what was built and verified, with evidence.
- **Part 2:** a copy-paste prompt for the cloud team or its AI assistant.

Everything in Part 1 is backed by tests or measurements in this repository; nothing is
aspirational. Items not done are listed as not done.

---

## Part 1 — What has been done

### 1.1 Product (working, tested)

A Windows app that runs AI audio processing **locally on the user's NVIDIA GPU**:

| Tool | Details | Verified by |
|---|---|---|
| Vocal remover / stem splitter | BS-RoFormer (default), Mel-Band RoFormer (2 stems); Demucs (2/4/6 stems) | `tests/test_gpu.py`, MUSDB18 benchmark |
| Live progress | Real % from the models' chunk loops, step tracker, ETA; never goes backwards | `test_progress_is_real`, GPU browser journey |
| Stem mixer | Synced playback of all stems, mute/solo/volume, seek, export mix | `tests/e2e/test_split_gpu.py` |
| Pitch & Tempo | Speed 0.5–2× (presets 0.75/1/1.25/1.5), *keep original pitch* (time-stretch) or tape mode, pitch ±12 st, **live preview** in the browser before rendering | unit + e2e |
| Key & BPM | Key, Camelot, BPM, confidence | unit (A major, 120 BPM) |
| Cutter / Joiner / Converter | Fades, crossfades, 5 formats; video files accepted | unit + e2e |
| File handling | Source preview player, Remove/Replace, 1 GB limit | e2e + API tests |

**Measured quality** (MUSDB18 test excerpts, 6 tracks, median SDR; full table in
`docs/audio-quality-benchmarks.md`):

| Model | Vocals | Instrumental | Speed on GTX 1650 |
|---|---|---|---|
| BS-RoFormer *fast* (default) | 12.48 dB | 16.29 dB | ≈ 0.65 s per s of audio |
| BS-RoFormer *best* | 12.54 dB | 16.36 dB | ≈ 2.4 s per s (2.8× slower for +0.06 dB → *fast* chosen as default) |
| Mel-Band RoFormer | 11.43 dB | 14.66 dB | |
| Demucs 4-stem | 9.32 dB | drums 7.07 · bass 11.08 · other 5.00 | ≈ 0.25 s per s |

All 43 objective acceptance checks pass (SDR thresholds, 44.1 kHz stereo, length ±1 sample,
zero clipping, GPU memory, monotonic progress).

### 1.2 Architecture (as built)

```
UI: static/index.html (vanilla JS, Web Audio, AudioWorklet pitch shifter for live preview)
 │  HTTP JSON, server bound to 127.0.0.1 only
server.py (FastAPI)
 ├─ uploads (validated by decoding, size-limited, server-generated names)
 ├─ job queue (1 worker thread, progress + ETA, job pruning)
 ├─ CPU tools run in-process: cut, join, pitch, analyze, convert, mix
 └─ GPU tool "separate" → gpu_worker.py (child process via multiprocessing "spawn")
       └─ engine.separate(): audio-separator (RoFormer) / Demucs on PyTorch CUDA
          · exits after 5 idle minutes → all GPU memory returned to the OS
          · crash in the worker → job error, server keeps running, next job restarts the worker
desktop.py: Windows launcher (server + Edge app window), bundles ffmpeg, models, Demucs weights
```

**Reuse for the cloud:** `engine.py` + `gpu_worker.py` have no UI or web dependencies, so they
are designed to become the cloud GPU worker unchanged. The worker protocol is
`("run", tool, params)` → `("progress", frac, stage)`* → `("done", result) | ("error", msg, is_user_error)`.

### 1.3 HTTP API (current, local)

| Method & path | Purpose |
|---|---|
| `GET /` | UI |
| `GET /api/info` | device, GPU name, output folder, formats |
| `POST /api/upload` (multipart `file`) | → `{id, name, duration, size}`; 400 unreadable/empty, 413 too large |
| `DELETE /api/uploads/{id}` | delete an upload |
| `POST /api/jobs` `{tool, params}` | tools: `separate`, `pitch`, `analyze`, `cut`, `join`, `convert`, `mix`; files are referenced by upload id only (`upload` / `uploads`) |
| `GET /api/jobs/{id}` | `status` (queued/running/done/error), `progress` 0–1, `stage`, `eta`, `result`, `error` |
| `POST /api/release-gpu` | stop the AI worker now (frees all GPU memory) |
| `POST /api/open-folder` | open the output folder in Explorer (desktop only) |
| `GET /files/...` | result files (output folder only) |

Parameter allowlists and ranges are in `engine.py` (`choice()` / `number()` calls per tool).

### 1.4 Quality assurance

- **Quality gate** `run_tests.ps1 -Gpu` (also `scripts/test.ps1`). Last run: **VERDICT PASS**,
  nothing skipped: unit 101 · API/security 63 · Playwright e2e 23 × Chromium + 23 × Edge ·
  GPU 12 · GPU browser journey 1 · pip-audit clean · **backend coverage 98 %** (engine 99 %,
  server 99 %, gpu_worker 95 %). The desktop launcher tests (`tests/test_desktop.py`) were added after
  that run.
- Security tests: MIME spoofing, empty files, size limit, path traversal (filenames, static
  files, stem paths, folder opening), raw-path injection, localhost-only binding, no secret
  leakage, import has no side effects.
- 16 defects found by testing and fixed, each with a regression test (`progress.md`). They include
  a server crash on OGG export, a race that wiped a live job's upload, a division by zero in ETA,
  filenames cut at the first dot, and GPU memory not being released.
- CI: `.github/workflows/ci.yml` (lint, mypy, unit, API, coverage ≥ 85 %, Playwright, pip-audit,
  Gitleaks) on GitHub-hosted Linux runners with CPU PyTorch. **It has not run on GitHub yet**
  (first push pending). GPU tests cannot run on hosted runners (no GPU).

### 1.5 Windows desktop app

- `scripts/build-windows.ps1` → PyInstaller offline bundle → smoke test of the built exe on a
  simulated fresh profile → portable ZIP → Inno Setup installer (per-user, no admin rights).
- Details, install/uninstall/troubleshooting: `docs/windows-build.md`.
- Build results: see `progress.md` → "Windows build".

### 1.6 Repository contents

`README.md`, `LICENSE` (proprietary), `THIRD_PARTY_NOTICES.md`, `SECURITY.md`,
`CONTRIBUTING.md`, `CHANGELOG.md`, `.gitignore`, `.env.example` (no secrets exist),
`requirements.txt` / `requirements-dev.txt` / `requirements-lock.txt`, `scripts/` (setup,
run-dev, test, build, build-windows, smoke test), `docs/` (technical assessment, testing
strategy, test cases, audio benchmarks, Windows build, this handover), `progress.md`.

### 1.7 Not done (honest list)

| Not done | Notes |
|---|---|
| Cloud backend, database, object storage, cloud GPU | **Cloud team scope** |
| Accounts, auth, MFA, roles | Cloud team scope (proposal in technical-assessment §4/§8) |
| Freemium quotas, Razorpay payments, subscriptions | Cloud team scope; must be enforced server-side |
| Browser-side processing of light edits | Today light edits run on the local server |
| Multi-track timeline, undo/redo, projects, autosave | Planned (P2) |
| Noise removal, mastering, LUFS normalisation, export presets, video tools, NL assistant, SFX library | Planned (P1–P3), see technical-assessment §3 |
| Job cancellation and timeouts | Needed before any cloud use |
| Auto-updater, code signing | Planned |
| Firefox testing | Blocked on the dev PC (missing VC++ runtime) |

### 1.8 Open risks the cloud team must know

1. **PyTorch 2.5.1 / CVE-2025-32434.** Upgrade to ≥ 2.6 in the cloud image (cloud GPUs have
   modern drivers, so use a CUDA 12 build). Re-run `tests/test_gpu.py` and the benchmark after
   upgrading.
2. **Licences.** The bundled ffmpeg is a GPL build; the RoFormer weights' licence is unclear
   (THIRD_PARTY_NOTICES.md). Resolve both before any paid launch.
3. **Local security model.** The current security relies on 127.0.0.1 binding. A public API needs
   auth, per-user authorization, rate limits, CORS/CSRF, headers, isolated workers with resource
   limits and no network, private storage, signed URLs, and secrets management.
4. **Cost driver.** GPU time: ≈ 60–100 s on a T4-class GPU per 4-minute song (estimate from local
   measurements; verify on the chosen GPU). Quotas are required to stay within ₹0–₹5,000/month.

---

## Part 2 — Prompt for the cloud team (copy everything inside the box)

````text
You are the cloud engineering team (or an AI engineering assistant working for it) taking over
the cloud side of the "AI Music Editor" product.

REPOSITORY: https://github.com/achuprasad/AIMUSICMAKE (public). Read these first, in order:
README.md, docs/CLOUD_HANDOVER.md, docs/technical-assessment.md, progress.md, SECURITY.md,
THIRD_PARTY_NOTICES.md, docs/testing-strategy.md.

WHAT ALREADY EXISTS (verified, do not rebuild):
- engine.py: audio/AI processing (BS-RoFormer, Mel-Band RoFormer, Demucs 2/4/6 stems; pitch/tempo,
  key/BPM, cut, join, convert, mix) with strict input validation and real progress callbacks.
- gpu_worker.py: runs AI jobs in a child process (crash isolation, frees all GPU memory when it exits).
- server.py: FastAPI API (upload, job queue, progress/ETA, file serving) — LOCAL ONLY, bound to
  127.0.0.1, no auth.
- static/index.html: complete UI, including live preview and the stem mixer.
- desktop.py + packaging/: offline Windows app (.exe, installer). Stays a separate local product.
- Tests: 210 automated test cases (UI tests run in 2 browsers) + MUSDB18 objective quality
  benchmark (43 checks); quality gate PASS
  (98 % backend coverage). Keep them passing.

PRODUCT DECISIONS YOU MUST PRESERVE (change only with the owner's written approval):
- Hybrid processing: light edits in the browser, expensive AI on cloud GPUs.
- Freemium, global market, start small and scale gradually.
- Budget ₹0–₹5,000 per month at launch. Prefer free tiers and open source. No always-on GPU.
- Payments: Razorpay.
- The local Windows app keeps working offline with the user's own GPU.

YOUR SCOPE:
1. Cloud GPU worker: package engine.py + gpu_worker.py in a container for a serverless,
   per-second-billed GPU (e.g. Modal or RunPod Serverless). Upgrade PyTorch to >= 2.6 (CUDA 12
   build) to fix CVE-2025-32434, then re-run tests/test_gpu.py and benchmarks/audio_quality.py on
   the cloud GPU and record the results. Add job cancellation, timeouts and retries with idempotency.
2. Cloud API: evolve server.py into a multi-user API: authentication (Argon2id or a managed auth
   provider with email verification and MFA), per-user authorization on every upload, job and
   file (no IDOR), Pydantic request schemas, rate limiting, CORS allowlist, CSRF where cookies
   are used, security headers, safe error messages.
3. Storage: private object storage (e.g. Cloudflare R2), server-generated keys, expiring signed
   upload/download URLs, automatic deletion of uploads and results after a retention period.
4. Database + queue: Postgres (e.g. Neon/Supabase free tier) for users, projects, jobs, usage;
   a Postgres-backed job queue unless there's a clear reason for Redis.
5. Freemium: configurable quotas (AI jobs per day, max duration, max file size, export limits)
   enforced ONLY on the backend; usage tracking per user; Razorpay subscriptions with webhook
   signature verification and idempotent processing; never store card data.
6. Media-processing security: isolated workers, CPU/memory/time limits, no outbound network,
   non-root containers, patched ffmpeg (use an LGPL build or comply with the GPL), file-signature
   allowlist.
7. Environments: dev, staging, production. Secrets in a secrets manager or platform env vars,
   never in git. Least-privilege IAM, TLS everywhere, backups with a tested restore,
   logging/monitoring (free tiers such as Sentry, UptimeRobot), cost monitoring with alerts.
8. CI/CD: extend .github/workflows/ci.yml (it has never run yet; make it green first), add
   Semgrep, Trivy for container images, an OWASP ZAP baseline against staging, protected
   main branch, and a deploy workflow to staging. Production deploys need manual approval.
9. Licences: confirm the RoFormer weights' licence for commercial use, or replace the models.

RULES:
- Inspect the code before changing it; preserve working behaviour; keep or extend the tests,
  never weaken them. A feature is done only when its tests pass.
- Itemise the monthly cost of every service you add, separating free-tier and realistic costs.
- Do not create paid resources, push to main, or deploy to production without the owner's
  explicit approval.
- Never commit secrets. Run Gitleaks and pip-audit before every release.
- Report honestly: what passed, what failed, what is not done. Do not claim anything works
  without having run it.

FIRST DELIVERABLE (before writing code): a short plan covering the providers chosen and why, the
monthly cost estimate (free tier vs ~1,000 active users), the API changes, the worker container
design, the security controls and the migration steps. Wait for the owner's approval.
````
