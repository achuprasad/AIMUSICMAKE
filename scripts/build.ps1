# Verify and build everything for a release:
#   1. full quality gate (must PASS, GPU stages included)
#   2. offline Windows app + portable ZIP + Setup.exe (scripts\build-windows.ps1, includes an exe smoke test)
#   .\scripts\build.ps1 -SkipTests   build only (not for releases)
param([string]$Version = "1.0.0", [switch]$SkipTests)
$Here = $PSScriptRoot
if (-not $SkipTests) {
    & "$Here\test.ps1" -Gpu
    if ($LASTEXITCODE -ne 0) { Write-Host "Quality gate did not PASS - build stopped." -ForegroundColor Red; exit 1 }
}
& "$Here\build-windows.ps1" -Version $Version
exit $LASTEXITCODE
