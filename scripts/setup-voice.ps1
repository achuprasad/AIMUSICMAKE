# Copyright (c) 2026 Achu Prasad. All rights reserved. See LICENSE.
# One-time setup of the Malayalam voice engine (OmniVoice) for Mixlumo's Voice Studio.
#   .\scripts\setup-voice.ps1                 install the voice environment and download the model (~3.5 GB disk)
#   .\scripts\setup-voice.ps1 -Cpu            CPU-only PyTorch (no NVIDIA GPU; speech is much slower)
#   .\scripts\setup-voice.ps1 -SkipModel      don't download the model now (it downloads on first use)
#
# The voice engine gets its OWN environment (%USERPROFILE%\.audiostudio\tts-venv), separate from Mixlumo's, so its
# PyTorch / transformers versions can never break the vocal remover. Versions are pinned and locked:
#   torch 2.7.1 + CUDA 11.8  (works with NVIDIA drivers >= 452, incl. older GTX cards; newer pip packages must not
#                             upgrade it, which silently broke an earlier install)
#   OmniVoice @ 4d5ed0f       (k2-fsa/OmniVoice, the commit Mixlumo was tested with)
#
# Model licences (shown in the app too): OmniVoice code Apache-2.0; OmniVoice MODEL WEIGHTS CC-BY-NC 4.0
# (personal, non-commercial use); its audio tokenizer: Boson Higgs Audio 2 Community License (attribution required;
# >100,000 annual users needs a licence from Boson AI).
param([switch]$Cpu, [switch]$SkipModel)
$ErrorActionPreference = "Continue"
$Home_ = "$env:USERPROFILE\.audiostudio"
$Env = "$Home_\tts-venv"
$Py = "$Env\Scripts\python.exe"
$Lock = "$Home_\tts-constraints.txt"
$OmniVoice = "git+https://github.com/k2-fsa/OmniVoice@4d5ed0f"
function Fail($m) { Write-Host "VOICE SETUP FAILED: $m" -ForegroundColor Red; exit 1 }

Write-Host "Malayalam voice engine setup" -ForegroundColor Cyan
Write-Host "The voice model (OmniVoice) is licensed for PERSONAL, NON-COMMERCIAL use (CC-BY-NC 4.0)." -ForegroundColor Yellow
Write-Host "Only clone voices you own or have the speaker's permission to use." -ForegroundColor Yellow

& py -3.12 --version; if ($LASTEXITCODE -ne 0) { Fail "Python 3.12 not found (winget install Python.Python.3.12)" }
& git --version | Out-Null; if ($LASTEXITCODE -ne 0) { Fail "git not found (winget install Git.Git)" }
$free = [math]::Round((Get-PSDrive ($env:USERPROFILE.Substring(0, 1))).Free / 1GB, 1)
if ($free -lt 8) { Fail "only $free GB free on the system drive; the voice engine needs about 8 GB during setup" }

$index = "https://download.pytorch.org/whl/cpu"; $torch = "torch==2.7.1"; $audio = "torchaudio==2.7.1"
if (-not $Cpu) {
    $drv = (& nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>$null | Select-Object -First 1)
    if ($drv -and [int]($drv.Split(".")[0]) -ge 452) {
        $index = "https://download.pytorch.org/whl/cu118"; $torch = "torch==2.7.1+cu118"; $audio = "torchaudio==2.7.1+cu118"
        Write-Host "NVIDIA driver ${drv}: GPU voice generation"
    } else { Write-Host "No suitable NVIDIA GPU: CPU voice generation (slow)" -ForegroundColor Yellow }
}

if (-not (Test-Path $Py)) {
    Write-Host "== Creating the voice environment ==" -ForegroundColor Cyan
    & py -3.12 -m venv $Env; if ($LASTEXITCODE -ne 0) { Fail "could not create $Env" }
}
"$torch`n$audio`n" | Set-Content $Lock -Encoding ascii
& $Py -m pip install -q --upgrade pip
Write-Host "== PyTorch ($torch) ==" -ForegroundColor Cyan
& $Py -m pip install -q $torch $audio --index-url $index; if ($LASTEXITCODE -ne 0) { Fail "PyTorch install failed" }
Write-Host "== OmniVoice ==" -ForegroundColor Cyan
& $Py -m pip install -q --no-deps $OmniVoice; if ($LASTEXITCODE -ne 0) { Fail "OmniVoice install failed" }
& $Py -m pip install -q "transformers>=5.3.0" accelerate pydub soundfile librosa huggingface_hub numpy -c $Lock
if ($LASTEXITCODE -ne 0) { Fail "dependency install failed" }

Write-Host "== Checking ==" -ForegroundColor Cyan
& $Py -c "import torch, transformers, omnivoice; print('torch', torch.__version__, '| CUDA', torch.cuda.is_available(), '| transformers', transformers.__version__)"
if ($LASTEXITCODE -ne 0) { Fail "the voice environment does not import" }
$tv = & $Py -c "import torch; print(torch.__version__)"
if ($tv -notlike "2.7.1*") { Fail "PyTorch was changed to $tv by another package; rerun this script" }

if (-not $SkipModel) {
    Write-Host "== Downloading the model (~3.1 GB, first time only) ==" -ForegroundColor Cyan
    & $Py -c "from huggingface_hub import snapshot_download; snapshot_download('k2-fsa/OmniVoice')"
    if ($LASTEXITCODE -ne 0) { Fail "model download failed (check the internet connection, then rerun)" }
}
Write-Host "`nVoice engine ready. Open Mixlumo > Malayalam Voice." -ForegroundColor Green
