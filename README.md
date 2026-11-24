# Local Audio Studio (AI Music Editor)

AI vocal remover, stem splitter and audio toolkit for Windows. Today it runs **entirely on the
user's PC** and uses the local NVIDIA GPU. It is the working core of the planned AI Music Editor
(browser + cloud GPU, freemium); see [docs/technical-assessment.md](docs/technical-assessment.md)
and [docs/CLOUD_HANDOVER.md](docs/CLOUD_HANDOVER.md).

## Features (implemented and tested)

| Tool | What it does |
|---|---|
| **Vocal Remover / Stem Splitter** | BS-RoFormer and Mel-Band RoFormer (vocals + instrumental), Demucs (2 / 4 / 6 stems: vocals, drums, bass, other, guitar, piano). Live progress %, ETA, synced stem mixer (mute / solo / volume), export mix |
| **Pitch & Tempo** | Speed 0.5×–2× with or without keeping pitch (tape mode), pitch ±12 semitones, live preview before rendering |
| **Key & BPM Finder** | Key, Camelot code, BPM (half/double), confidence |
| **Cutter** | Waveform range selection, fade in/out |
| **Joiner** | Reorder tracks, crossfade |
| **Converter** | Any audio/video file → WAV, MP3, FLAC, OGG, M4A |
| **Help & Feedback** | Feature requests, suggestions, bug reports, questions; roadmap voting; FAQ. New messages are e-mailed to the owners when configured (addresses stay private): [docs/support-and-feedback.md](docs/support-and-feedback.md) |

Measured quality (MUSDB18, median SDR): BS-RoFormer vocals **12.5 dB**, instrumental **16.3 dB**.
See [docs/audio-quality-benchmarks.md](docs/audio-quality-benchmarks.md).

## For users: install the Windows app

1. Get `LocalAudioStudio-Setup-<version>.exe` **and** its `.bin` files (the installer is split
   because it's over 2 GB) from the release, all in one folder.
2. Run the `.exe`. No administrator rights are needed; it installs to
   `%LOCALAPPDATA%\Programs\Local Audio Studio`.
3. Start **Local Audio Studio** from the Start menu. Results are saved to `Music\Local Audio Studio`.

Requirements: Windows 10/11 64-bit, about 8 GB free disk. An NVIDIA GPU is strongly recommended;
it also works on CPU, but much slower. Full guide, uninstalling and troubleshooting:
[docs/windows-build.md](docs/windows-build.md).

## For developers

```powershell
.\scripts\setup.ps1 -DownloadModels   # one time: Python env (outside the repo), dependencies, models
.\scripts\run-dev.ps1                 # app at http://127.0.0.1:7860 (or -Desktop for the app window)
.\scripts\test.ps1                    # quality gate (lint, types, unit, API, e2e, security, coverage)
.\scripts\test.ps1 -Gpu               # + real-GPU tests (needed for a PASS verdict)
.\scripts\build.ps1                   # gate + offline .exe + portable ZIP + Setup.exe
```

Prerequisites: Windows 10/11, Python 3.12, ffmpeg (`winget install Gyan.FFmpeg`), Inno Setup 6
for the installer (`winget install JRSoftware.InnoSetup --scope user`).

## Architecture (current)

```
Browser / app window (static/index.html: Web Audio, AudioWorklet live preview)
        │ HTTP JSON (127.0.0.1 only)
server.py (FastAPI) ── job queue ── CPU tools in-process (cut, join, pitch, key/BPM, convert, mix)
        │ multiprocessing queue
gpu_worker.py (child process) ── engine.separate() ── PyTorch CUDA (RoFormer, Demucs)
desktop.py  ─ Windows launcher: starts the server, opens an Edge app window, bundles ffmpeg + models
```

| Path | Purpose |
|---|---|
| `engine.py` | Audio/AI processing, validation, progress hooks |
| `gpu_worker.py` | AI jobs in a child process: crash isolation, full GPU release when idle |
| `server.py` | HTTP API, uploads, job queue, file serving |
| `desktop.py` | Windows desktop launcher (entry point of the .exe) |
| `static/index.html` | The whole UI |
| `tests/` | pytest + Playwright tests |
| `benchmarks/` | Objective audio-quality benchmark |
| `packaging/` | PyInstaller spec, Inno Setup script, icon |
| `scripts/` | setup / run / test / build scripts |
| `docs/` | Assessment, testing, benchmarks, Windows build, cloud handover |

## Status and limitations

Read [progress.md](progress.md) for the full test report and defect log. Main open items:
no accounts, payments or cloud backend yet (planned); PyTorch 2.5.1 CVE-2025-32434 (upgrade
planned); no job cancel button yet; Firefox not yet tested on the dev PC.

## License

Source-available, all rights reserved: the code is public to read, not licensed for reuse (see [LICENSE](LICENSE)). Third-party components and AI models
have their own licences: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Check them before
commercial distribution.
