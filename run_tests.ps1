# Mixlumo - full quality gate (the local equivalent of a CI pipeline).
#   .\run_tests.ps1              lint, types, unit, integration, e2e, security, build, coverage
#   .\run_tests.ps1 -Gpu         + GPU model tests and the GPU browser journey (needed for a complete gate)
#   .\run_tests.ps1 -Benchmark   + audio-quality benchmark (writes docs\audio-quality-benchmarks.md)
# Verdict: PASS only if every stage passed and none was skipped. Do not ship otherwise.
param([switch]$Gpu, [switch]$Benchmark)

# Stages are judged by exit code. "Stop" would abort on any stderr warning in Windows PowerShell 5.1.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$V = "$env:USERPROFILE\.audiostudio\venv\Scripts"
$Py = "$V\python.exe"
$results = [ordered]@{}
$Cov = "--cov", "--cov-append", "--cov-report="
Remove-Item .coverage -ErrorAction SilentlyContinue

function Invoke-Stage($name, [scriptblock]$cmd) {
    Write-Host "`n=== $name ===" -ForegroundColor Cyan
    $out = & $cmd 2>&1 | ForEach-Object { "$_" }
    $out | Write-Host
    $text = $out -join "`n"
    if ($LASTEXITCODE -ne 0) { $status = "FAIL" }
    elseif ($text -match "(\d+) skipped" -and $text -notmatch "(\d+) passed") { $status = "SKIPPED" }  # never report an all-skipped stage as a pass
    else { $status = "PASS" }
    if ($text -match "(\d+) passed.*?(\d+) skipped") { $status = "PASS (with skips)" }
    $results[$name] = $status
}

$env:CUDA_VISIBLE_DEVICES = "-1"   # non-GPU stages must not touch the graphics card
Invoke-Stage "1 Lint (ruff)"             { & "$V\ruff.exe" check engine.py server.py gpu_worker.py desktop.py notify.py feedback.py voice_engine.py voice_worker.py voice_studio.py voice_profiles.py voice_tones.py story_script.py tests benchmarks scripts packaging }
Invoke-Stage "2 Type check (mypy)"       { & $Py -m mypy engine.py server.py gpu_worker.py desktop.py notify.py feedback.py voice_engine.py voice_studio.py voice_profiles.py voice_tones.py story_script.py benchmarks\metrics.py benchmarks\audio_quality.py }
Invoke-Stage "3 Unit tests"              { & $Py -m pytest tests\test_engine.py tests\test_engine_models.py tests\test_worker.py tests\test_desktop.py tests\test_story_script.py tests\test_voice_engine.py tests\test_voice_studio.py -q -p no:cacheprovider -rs @Cov }
Invoke-Stage "4 Integration tests"       { & $Py -m pytest tests\test_api.py tests\test_feedback.py tests\test_notify.py tests\test_voice_api.py -q -p no:cacheprovider -rs @Cov }
Invoke-Stage "5 Frontend e2e (Chromium)" { & $Py -m pytest tests\e2e\test_ui.py tests\e2e\test_theme.py tests\e2e\test_voice_ui.py -q -p no:cacheprovider -rs --browser chromium }
Invoke-Stage "5 Frontend e2e (Edge)"     { & $Py -m pytest tests\e2e\test_ui.py tests\e2e\test_theme.py tests\e2e\test_voice_ui.py -q -p no:cacheprovider -rs --browser chromium --browser-channel msedge }
Invoke-Stage "6 Security (pip-audit)"    { & $Py -m pip_audit --progress-spinner off }
Invoke-Stage "7 Build verification"      {
    # isolated folders: a build check must never touch the real app's uploads or output
    $tmp = Join-Path $env:TEMP ("las-build-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    $env:AUDIO_STUDIO_OUT = "$tmp\out"; $env:AUDIO_STUDIO_UPLOADS = "$tmp\uploads"
    & $Py -m compileall -q engine.py server.py gpu_worker.py desktop.py notify.py feedback.py
    if ($?) { & $Py -c "import server; print('server imports OK')" }
    Remove-Item Env:AUDIO_STUDIO_OUT, Env:AUDIO_STUDIO_UPLOADS
}
Remove-Item Env:CUDA_VISIBLE_DEVICES

if ($Gpu) {
    # If the app is open it may be keeping a model on the GPU: ask it to let go (waits for any running job).
    try {
        $r = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:7860/api/release-gpu" -TimeoutSec 3600
        Write-Host "Asked the running app to release the GPU (released: $($r.released))"
        Start-Sleep -Seconds 2
    } catch { Write-Host "App not running on :7860 (nothing to release)" }
    Invoke-Stage "8 GPU model tests"     { & $Py -m pytest tests\test_gpu.py -q -p no:cacheprovider -rs @Cov }
    Invoke-Stage "8 GPU browser journey" { & $Py -m pytest tests\e2e\test_split_gpu.py -q -p no:cacheprovider -rs --browser chromium }
} else {
    $results["8 GPU tests"] = "NOT RUN"
}
Invoke-Stage "9 Coverage >= 85% (backend)" { & $Py -m coverage report --fail-under=85 }
if ($Benchmark) {
    Invoke-Stage "10 Audio quality benchmark" { & $Py benchmarks\audio_quality.py --tracks 6 }
}

Write-Host "`n=== Summary ===" -ForegroundColor Cyan
$results.GetEnumerator() | ForEach-Object {
    $c = switch -Wildcard ($_.Value) { "PASS" { "Green" } "PASS (with skips)" { "Yellow" } "FAIL" { "Red" } default { "Yellow" } }
    Write-Host ("{0,-40} {1}" -f $_.Key, $_.Value) -ForegroundColor $c
}
$vals = @($results.Values)
if ($vals -contains "FAIL") { Write-Host "`nVERDICT: FAIL" -ForegroundColor Red; exit 1 }
if (($vals | Where-Object { $_ -ne "PASS" }).Count) { Write-Host "`nVERDICT: INCOMPLETE (stages skipped or not run)" -ForegroundColor Yellow; exit 2 }
Write-Host "`nVERDICT: PASS" -ForegroundColor Green; exit 0
