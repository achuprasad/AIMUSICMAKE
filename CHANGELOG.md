# Changelog

## 1.1.0 — 2026-11-24

### Changed
- **New name: Mixlumo** (was "Local Audio Studio"). App window title, EXE (`Mixlumo.exe`), installer
  (`Mixlumo-Setup-1.1.0.exe`), Start-menu entry and results folder (`Music\Mixlumo`). The installer keeps
  the same ID, so 1.1.0 installs over 1.0.0. Search-engine and sharing tags added to the page.

### Added
- Themes: Light, Dark and Auto (follows Windows), seven accent colours plus any custom colour; remembered
  per browser; text contrast meets WCAG AA in every theme/accent combination (tested).
- Copyright notice (© 2026 Achu Prasad. All rights reserved.) in the app, source files, EXE properties and
  installer.
- Help & Feedback page: feature requests, suggestions, bug reports, questions, rating, roadmap voting, FAQ, "your submissions"; e-mail to the owners (private addresses, SMTP over TLS, hourly cap); GitHub issue forms and "Send via GitHub" for the offline app.
- App-wide request guards: same-origin check on every write request, 64 KB JSON limit, security headers.

### Fixed
- The AI worker now exits when the app is killed or crashes (orphaned workers used to keep GPU memory).

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
