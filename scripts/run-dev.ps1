# Start the app for development: server on http://127.0.0.1:7860 + browser.
#   .\scripts\run-dev.ps1             server + open browser
#   .\scripts\run-dev.ps1 -Desktop    run through the desktop launcher (own window, like the .exe)
#   .\scripts\run-dev.ps1 -Port 7861
# There is no separate frontend build: the UI is static\index.html, served by the backend.
param([switch]$Desktop, [int]$Port = 7860)
$Root = Split-Path -Parent $PSScriptRoot
$Py = "$env:USERPROFILE\.audiostudio\venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { Write-Host "Run .\scripts\setup.ps1 first." -ForegroundColor Red; exit 1 }
Set-Location $Root
if ($Desktop) { & $Py desktop.py --port $Port; exit $LASTEXITCODE }
$env:PORT = "$Port"
Start-Job -ScriptBlock { param($p) Start-Sleep 4; Start-Process "http://127.0.0.1:$p" } -ArgumentList $Port | Out-Null
& $Py server.py
