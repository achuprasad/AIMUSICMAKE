# Changelog

## Unreleased

### Added
- Help & Feedback page: feature requests, suggestions, bug reports, questions, rating, roadmap voting, FAQ, "your submissions"; e-mail to the owners (private addresses, SMTP over TLS, hourly cap); GitHub issue forms and "Send via GitHub" for the offline app.
- App-wide request guards: same-origin check on every write request, 64 KB JSON limit, security headers.

## 1.0.0 — 2026-11-23 (first release)

### Added
- AI vocal removal and stem separation: BS-RoFormer, Mel-Band RoFormer, Demucs 2/4/6 stems.
- Live progress (%, current step, ETA) driven by the models' own chunk loops.
- Stem mixer: synced playback, mute/solo/volume, waveform seek, export mix.
- Pitch & Tempo with Speed presets, *Keep original pitch* (time-stretch or tape mode), live preview.
- Key & BPM finder with Camelot code; Cutter with fades; Joiner with crossfade; Converter.
- Source preview player on every tool; Remove and Replace for uploaded files.
- AI engine in a separate process: crash isolation and full GPU memory release after 5 idle minutes.
- Windows desktop app: offline .exe (bundled ffmpeg and models), Setup.exe, portable ZIP.
- Quality gate (`run_tests.ps1`), GitHub Actions CI, MUSDB18 objective quality benchmark.

### Fixed (found by testing; each has a regression test)
See progress.md, "Defects found by testing", items 1–16.
