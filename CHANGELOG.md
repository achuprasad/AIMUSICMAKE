# Changelog

## Unreleased

### Fixed
- Opening Mixlumo while an **older** Mixlumo was still running showed the old one (it reused whatever
  Mixlumo answered on port 7860), so after an update you could still be using the previous version.
  The app now reports its version, and the launcher only reuses a running copy of the same version;
  otherwise it starts its own on the next free port.

## 1.2.1 — 2026-11-24

### Fixed
- **Key changes and keep-key speed changes lost loudness** in the downloaded file, worst on notes that
  follow silence (most songs start with some): up to −23 dB at +12 semitones, −6 dB at 0.6×. The time
  stretch now uses a phase-locked vocoder; notes keep their level within 0.1 dB and their exact pitch.
- **Live preview now matches the downloaded file** (measured with `scripts/compare_preview.py`):
  - Lo-fi tone colour: the preview used gentler filters (and Web Audio reads filter Q in dB); now the
    same Butterworth filters as the file, within 0.1 dB per octave band.
  - Lo-fi level: the preview was about 5 dB louder; it now measures the same level as the file.
  - Lo-fi hiss and crackle: same kind and level of noise as the file; bit-crush after the noise in both.
  - Live key shift was up to 25 cents out of tune (crossfade between out-of-phase taps); it now aligns
    each crossfade to the waveform and matches the file to within 0.5 cents, down to 55 Hz.
- New browser test: the "Lo-fi chill" preset's live preview and download must match in pitch, speed,
  echo timing and level, tone colour, loudness and hiss.

## 1.2.0 — 2026-11-24

### Added
- Pitch & Tempo: **Lo-fi** (warm filtering, tape saturation, bit-crush, soft vinyl hiss and crackle;
  amount 5–100) and **Echo** (delay 50–1000 ms, repeats, echo volume). Both are heard live in the preview
  and rendered into the downloaded file. Presets: "Lo-fi chill", "Slowed + Echo", "Reset".

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
