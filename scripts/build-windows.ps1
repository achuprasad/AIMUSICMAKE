# Builds the offline Windows app (folder with Mixlumo.exe) and the Setup.exe installer.
#   .\scripts\build-windows.ps1                       full build: app folder + portable ZIP + installer
#   .\scripts\build-windows.ps1 -SkipInstaller        app folder + ZIP only
#   .\scripts\build-windows.ps1 -OutDir D:\release    choose where results go
# Prerequisites: .\scripts\setup.ps1 has been run (Python env, models), Inno Setup 6 for the installer.
param(
    [string]$OutDir = "$env:USERPROFILE\Documents\Mixlumo-Release",
    [string]$Version = "1.2.0",
    [switch]$SkipInstaller,
    [switch]$SkipZip
)
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Py = "$env:USERPROFILE\.audiostudio\venv\Scripts\python.exe"
$Work = "$env:LOCALAPPDATA\MixlumoBuild"   # outside the repo: build output is ~5 GB
function Fail($msg) { Write-Host "BUILD FAILED: $msg" -ForegroundColor Red; exit 1 }

# ---- 1. inputs -------------------------------------------------------------------------------
if (-not (Test-Path $Py)) { Fail "Python environment missing. Run .\scripts\setup.ps1 first." }
$ffmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
if (-not $ffmpeg) { Fail "ffmpeg not found on PATH (winget install Gyan.FFmpeg)" }
$models = "$env:USERPROFILE\.audiostudio\models"
$torchHome = "$env:USERPROFILE\.cache\torch"
$needModels = "model_bs_roformer_ep_317_sdr_12.9755.ckpt", "model_bs_roformer_ep_317_sdr_12.9755.yaml",
              "model_mel_band_roformer_ep_3005_sdr_11.4360.ckpt", "model_mel_band_roformer_ep_3005_sdr_11.4360.yaml",
              "download_checks.json"
foreach ($m in $needModels) { if (-not (Test-Path "$models\$m")) { Fail "model file missing: $models\$m (run .\scripts\setup.ps1 -DownloadModels)" } }
$demucs = Get-ChildItem "$torchHome\hub\checkpoints\*.th" -ErrorAction SilentlyContinue
if ($demucs.Count -lt 2) { Fail "Demucs checkpoints missing in $torchHome\hub\checkpoints (run .\scripts\setup.ps1 -DownloadModels)" }

# Stage only the files we need (the models folder may contain extras)
$stage = "$Work\stage"
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$stage\models", "$stage\torch_home\hub\checkpoints" | Out-Null
foreach ($m in $needModels) { Copy-Item "$models\$m" "$stage\models\" }
$demucs | Copy-Item -Destination "$stage\torch_home\hub\checkpoints\"
$env:LAS_FFMPEG = $ffmpeg; $env:LAS_MODELS = "$stage\models"; $env:LAS_TORCH_HOME = "$stage\torch_home"

# ---- 2. PyInstaller ------------------------------------------------------------------------------
Write-Host "== PyInstaller (10-20 minutes) ==" -ForegroundColor Cyan
& $Py -m PyInstaller --noconfirm --clean --log-level WARN --distpath "$Work\dist" --workpath "$Work\work" `
    "$Root\packaging\Mixlumo.spec"
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller exited with $LASTEXITCODE" }
$App = "$Work\dist\Mixlumo"
if (-not (Test-Path "$App\Mixlumo.exe")) { Fail "Mixlumo.exe was not produced" }
$size = [math]::Round((Get-ChildItem $App -Recurse -File | Measure-Object Length -Sum).Sum / 1GB, 2)
Write-Host "App folder: $App ($size GB)"

# ---- 3. smoke test the frozen app (server only, offline resources, no window) ---------------------
Write-Host "== Smoke test ==" -ForegroundColor Cyan
& $Py "$Root\scripts\smoke_test_exe.py" "$App\Mixlumo.exe"
if ($LASTEXITCODE -ne 0) { Fail "smoke test of the built exe failed" }

New-Item -ItemType Directory -Force $OutDir | Out-Null
# ---- 4. portable ZIP -------------------------------------------------------------------------------
if (-not $SkipZip) {
    Write-Host "== Portable ZIP ==" -ForegroundColor Cyan
    $zip = "$OutDir\Mixlumo-$Version-portable.zip"
    Remove-Item $zip -ErrorAction SilentlyContinue
    & tar.exe -a -c -f $zip -C "$Work\dist" Mixlumo
    if ($LASTEXITCODE -ne 0) { Fail "ZIP creation failed" }
}
# ---- 5. installer ------------------------------------------------------------------------------
if (-not $SkipInstaller) {
    Write-Host "== Inno Setup installer ==" -ForegroundColor Cyan
    $iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
            Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) { Fail "Inno Setup 6 not found (winget install JRSoftware.InnoSetup --scope user)" }
    Copy-Item "$Root\packaging\icon.ico" "$Work\icon.ico" -Force
    Copy-Item "$Root\packaging\installer.iss" "$Work\installer.iss" -Force
    & $iscc /Q "/DAppVersion=$Version" "/DSourceDir=$App" "/DOutputDir=$OutDir" "$Work\installer.iss"
    if ($LASTEXITCODE -ne 0) { Fail "Inno Setup exited with $LASTEXITCODE" }
}
Write-Host "`n== Build outputs in $OutDir ==" -ForegroundColor Green
Get-ChildItem $OutDir | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB)}} | Format-Table -AutoSize
Get-ChildItem $OutDir -File | Get-FileHash -Algorithm SHA256 | ForEach-Object { "$($_.Hash)  $(Split-Path $_.Path -Leaf)" } |
    Set-Content "$OutDir\SHA256SUMS.txt" -Encoding ascii
exit 0
