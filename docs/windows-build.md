# Windows app: build, install, uninstall, update, troubleshoot

## What the Windows app is

An **offline** desktop app. Everything ships inside it (Python, PyTorch CUDA 11.8, ffmpeg, the
BS-RoFormer / Mel-Band RoFormer / Demucs models), so it needs no internet and no other installs.

- `LocalAudioStudio.exe` starts the local server and opens the UI in its own window (Microsoft
  Edge app mode; Edge is part of Windows 10/11). Closing the window stops everything.
- AI separation uses the NVIDIA GPU when one is present (driver ≥ 452), otherwise the CPU (slow).
- Results go to `%USERPROFILE%\Music\Local Audio Studio`. Logs go to
  `%LOCALAPPDATA%\LocalAudioStudio\logs\app.log`.

## Build (developer PC)

Prerequisites: `.\scripts\setup.ps1 -DownloadModels` done; ffmpeg on PATH; Inno Setup 6
(`winget install JRSoftware.InnoSetup --scope user`). About 20 GB free disk during the build.

```powershell
.\scripts\build.ps1                    # quality gate (GPU stages included) + build; for releases
.\scripts\build-windows.ps1            # build only
.\scripts\build-windows.ps1 -SkipInstaller -OutDir D:\out
```

Steps the build performs (and fails loudly on):
1. Checks the model files, Demucs checkpoints and ffmpeg exist; stages only the needed files.
2. PyInstaller (`packaging/LocalAudioStudio.spec`) → `%LOCALAPPDATA%\LocalAudioStudioBuild\dist\LocalAudioStudio\`
   (kept outside the repo because it is ~5 GB).
3. **Smoke test of the built exe** (`scripts/smoke_test_exe.py`): runs it with an empty user
   profile and no ffmpeg on PATH, then converts, pitch-shifts, analyses and separates with
   BS-RoFormer and Demucs on the GPU, and checks nothing was downloaded.
4. Portable ZIP and the Inno Setup installer (`packaging/installer.iss`).
5. Writes `SHA256SUMS.txt` next to the outputs.

Default output folder: `%USERPROFILE%\Documents\LocalAudioStudio-Release\`:

| File | Use |
|---|---|
| `LocalAudioStudio-Setup-<ver>.exe` + `LocalAudioStudio-Setup-<ver>-*.bin` | Installer (~2.6 GB in total). Keep all files in one folder; the `.bin` slices hold the compressed app |
| `LocalAudioStudio-<ver>-portable.zip` | Portable version: unzip anywhere, run `LocalAudioStudio\LocalAudioStudio.exe` |
| `SHA256SUMS.txt` | Checksums to verify downloads |

GitHub Releases accept files up to 2 GiB each. The installer slices are capped at 2.0 GB
(`DiskSliceSize=2000000000`), so the Setup `.exe` and its `.bin` files can be attached to a
release as they are. The portable ZIP (~3.6 GB) is **over** that limit: share it another way
(USB, cloud drive), or leave it out of GitHub releases.

## Install

1. Put the Setup `.exe` and all its `.bin` files in one folder and run the `.exe`.
2. Windows SmartScreen may say "Windows protected your PC" because the installer is not
   code-signed yet. Click **More info → Run anyway** (only for installers from a trusted source).
3. No administrator rights are needed: it installs per user to
   `%LOCALAPPDATA%\Programs\Local Audio Studio`, with a Start-menu entry and an optional desktop shortcut.

Silent install (IT / testing): `LocalAudioStudio-Setup-1.0.0.exe /VERYSILENT /CURRENTUSER`

## Uninstall

*Settings → Apps → Installed apps → Local Audio Studio → Uninstall*, or Start menu →
*Uninstall Local Audio Studio*. This removes the program, logs and window profile.
**Your songs in `Music\Local Audio Studio` are kept.**

Silent: `"%LOCALAPPDATA%\Programs\Local Audio Studio\unins000.exe" /VERYSILENT`

## Update

Install the newer Setup over the existing one (same AppId); settings and results are kept.
There is no automatic updater yet; it's planned (see docs/technical-assessment.md §6).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Window doesn't open / closes at once | Look at `%LOCALAPPDATA%\LocalAudioStudio\logs\app.log` |
| "Port 7860 is used by another program" | Close the other program, or run `LocalAudioStudio.exe --port 7861` |
| Separation is very slow | No usable NVIDIA GPU: check `nvidia-smi`; update the GPU driver |
| "AI engine stopped unexpectedly" | GPU driver reset or out of memory. Try again; close other GPU apps; use Demucs or the *Fast* speed |
| Out of GPU memory on 2–4 GB cards | Close games/other AI apps; the app frees GPU memory after 5 idle minutes |
| Antivirus quarantines files | False positive on unsigned PyInstaller apps; restore and allow-list the install folder; code signing (planned) fixes this |
| Edge not installed | The app opens your default browser instead; close the console/program to stop it |
