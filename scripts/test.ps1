# Run the quality gate. Same switches as run_tests.ps1:
#   .\scripts\test.ps1              lint, types, unit, integration, e2e (Chromium + Edge), security, build, coverage
#   .\scripts\test.ps1 -Gpu         + GPU tests (needs an NVIDIA GPU; the open app is asked to free it first)
#   .\scripts\test.ps1 -Benchmark   + MUSDB18 audio-quality benchmark (needs testdata, see docs/testing-strategy.md)
param([switch]$Gpu, [switch]$Benchmark)
& (Join-Path (Split-Path -Parent $PSScriptRoot) "run_tests.ps1") -Gpu:$Gpu -Benchmark:$Benchmark
exit $LASTEXITCODE
