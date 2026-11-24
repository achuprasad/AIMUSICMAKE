# Installer test: silent install -> verify files, shortcuts, uninstall entry -> smoke test the
# installed exe -> silent uninstall -> verify removal.
#   .\scripts\test-installer.ps1 -Setup "<path>\LocalAudioStudio-Setup-1.0.0.exe"
param([Parameter(Mandatory)][string]$Setup)
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Py = "$env:USERPROFILE\.audiostudio\venv\Scripts\python.exe"
$Dir = Join-Path $env:LOCALAPPDATA "Programs\Local Audio Studio TEST"
$results = @(); $ok = $true
function Check($name, $cond, $detail = "") {
    $script:ok = $script:ok -and [bool]$cond
    $line = "{0}  {1}  {2}" -f ($(if ($cond) { "PASS" } else { "FAIL" }), $name, $detail)
    $script:results += $line; Write-Host $line
}
$uninstKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{8F3B9C2E-6A1D-4E7B-9C55-2D4A7E1B3F90}_is1"

# ---- install ----------------------------------------------------------------------------
$t = Get-Date
$p = Start-Process -FilePath $Setup -ArgumentList "/VERYSILENT", "/CURRENTUSER", "/SUPPRESSMSGBOXES", "/NORESTART",
     "/DIR=`"$Dir`"", "/TASKS=desktopicon", "/LOG=`"$env:TEMP\las-install.log`"" -Wait -PassThru
Check "silent install exits 0" ($p.ExitCode -eq 0) ("exit {0} in {1:N0}s" -f $p.ExitCode, ((Get-Date) - $t).TotalSeconds)
Check "exe installed" (Test-Path "$Dir\LocalAudioStudio.exe")
Check "bundled ffmpeg installed" (Test-Path "$Dir\_internal\bundled\bin\ffmpeg.exe")
Check "bundled models installed" ((Get-ChildItem "$Dir\_internal\bundled\models\*.ckpt" -ErrorAction SilentlyContinue).Count -eq 2)
$startMenu = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Local Audio Studio\Local Audio Studio.lnk"
Check "Start-menu shortcut" (Test-Path $startMenu)
$desktopLnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "Local Audio Studio.lnk"
Check "desktop shortcut" (Test-Path $desktopLnk)
$reg = Get-ItemProperty $uninstKey -ErrorAction SilentlyContinue
# Inno Setup registers the name as "<AppName> <version>" (AppVerName), the usual Windows convention
Check "registered in Apps & features (per-user)" ($reg -and $reg.DisplayName -eq "Local Audio Studio 1.0.0" -and $reg.DisplayVersion -eq "1.0.0") "'$($reg.DisplayName)' v$($reg.DisplayVersion)"
$sig = (Get-Item "$Dir\LocalAudioStudio.exe").VersionInfo
Check "exe version info" ($sig.ProductName -eq "Local Audio Studio" -and $sig.ProductVersion -eq "1.0.0") "$($sig.ProductName) $($sig.ProductVersion)"

# ---- run the installed app -----------------------------------------------------------------
& $Py "$Root\scripts\smoke_test_exe.py" "$Dir\LocalAudioStudio.exe"
Check "installed app smoke test" ($LASTEXITCODE -eq 0)

# ---- uninstall ------------------------------------------------------------------------------
$t = Get-Date
$p = Start-Process -FilePath "$Dir\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
Start-Sleep -Seconds 3   # the uninstaller finishes deleting itself in a helper process
Check "silent uninstall exits 0" ($p.ExitCode -eq 0) ("in {0:N0}s" -f ((Get-Date) - $t).TotalSeconds)
Check "program folder removed" (-not (Test-Path "$Dir\LocalAudioStudio.exe"))
Check "Start-menu shortcut removed" (-not (Test-Path $startMenu))
Check "desktop shortcut removed" (-not (Test-Path $desktopLnk))
Check "uninstall entry removed" (-not (Test-Path $uninstKey))
Check "user's songs folder kept" (Test-Path "$env:USERPROFILE\Music\Local Audio Studio")

Write-Host "`nINSTALLER TEST $(if ($ok) { 'PASSED' } else { 'FAILED' })"
if ($ok) { exit 0 } else { exit 1 }
