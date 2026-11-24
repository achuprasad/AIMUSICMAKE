# One-time developer setup for Mixlumo (Windows 10/11).
#   .\scripts\setup.ps1                   Python env + dependencies + test browser
#   .\scripts\setup.ps1 -DownloadModels   also download the AI models (~1.7 GB) for offline use / builds
#   .\scripts\setup.ps1 -Cpu              force CPU-only PyTorch (no NVIDIA GPU)
# Prerequisites: Python 3.12 (py launcher), ffmpeg on PATH (winget install Gyan.FFmpeg).
# The env lives outside the repo (%USERPROFILE%\.audiostudio\venv) because Windows' 260-character
# path limit breaks PyTorch installs in deep folders.
param([switch]$DownloadModels, [switch]$Cpu)
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Env = "$env:USERPROFILE\.audiostudio\venv"
$Py = "$Env\Scripts\python.exe"
function Fail($m) { Write-Host "SETUP FAILED: $m" -ForegroundColor Red; exit 1 }

Write-Host "== Checking prerequisites ==" -ForegroundColor Cyan
& py -3.12 --version; if ($LASTEXITCODE -ne 0) { Fail "Python 3.12 not found (winget install Python.Python.3.12)" }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Fail "ffmpeg not on PATH (winget install Gyan.FFmpeg, then reopen the terminal)" }

# CUDA 11.8 wheels run on NVIDIA drivers >= 452 (CUDA minor-version compatibility); otherwise CPU
$index = "https://download.pytorch.org/whl/cpu"
if (-not $Cpu) {
    $drv = (& nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>$null | Select-Object -First 1)
    if ($drv) {
        $major = [int]($drv.Split(".")[0])
        if ($major -ge 452) { $index = "https://download.pytorch.org/whl/cu118" }
        Write-Host "NVIDIA driver $drv detected"
    } else { Write-Host "No NVIDIA GPU detected: installing CPU-only PyTorch (AI separation will be slow)" -ForegroundColor Yellow }
}
Write-Host "PyTorch index: $index"

if (-not (Test-Path $Py)) {
    Write-Host "== Creating Python environment at $Env ==" -ForegroundColor Cyan
    & py -3.12 -m venv $Env; if ($LASTEXITCODE -ne 0) { Fail "venv creation failed" }
}
& $Py -m pip install --upgrade pip -q
Write-Host "== Installing dependencies (first time: ~3 GB download) ==" -ForegroundColor Cyan
& $Py -m pip install --timeout 120 --retries 10 -r "$Root\requirements-dev.txt" --extra-index-url $index
if ($LASTEXITCODE -ne 0) { Fail "pip install failed" }
& $Py -m playwright install chromium
& $Py -c "import torch; print('torch', torch.__version__, 'CUDA available:', torch.cuda.is_available())"

if ($DownloadModels) {
    Write-Host "== Downloading AI models ==" -ForegroundColor Cyan
    Set-Location $Root   # so 'import engine' finds the project
    & $Py -c @"
import engine, logging
from pathlib import Path
from audio_separator.separator import Separator
from demucs.pretrained import get_model
engine.MODEL_DIR.mkdir(parents=True, exist_ok=True)
for key, (label, f) in engine.ROFORMER.items():
    print('model:', label); s = Separator(log_level=logging.WARNING, model_file_dir=str(engine.MODEL_DIR)); s.download_model_files(f)
for name in ('htdemucs', 'htdemucs_6s'):
    print('model:', name); get_model(name)
print('models ready in', engine.MODEL_DIR)
"@
    if ($LASTEXITCODE -ne 0) { Fail "model download failed" }
}
Write-Host "`nSetup complete. Next: .\scripts\run-dev.ps1  (app)   .\scripts\test.ps1  (tests)" -ForegroundColor Green
