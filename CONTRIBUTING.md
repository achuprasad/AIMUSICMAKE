# Contributing

## Branches

- `main`: release-ready; protected, merged only through reviewed pull requests with green CI.
- `develop`: integration branch.
- `feature/<short-name>` for new work, `fix/<short-name>` for bug fixes, branched from `develop`.

## Workflow

1. `.\scripts\setup.ps1` once.
2. Write the test with the change (see docs/testing-strategy.md). Bugs get a regression test that
   fails before the fix.
3. `.\scripts\test.ps1` must report **PASS** (add `-Gpu` for anything touching `engine.py`,
   `gpu_worker.py` or separation). Do not weaken or delete tests to get a pass.
4. Open a PR into `develop`. CI (lint, types, unit, API, e2e, coverage ≥ 85 %, pip-audit,
   Gitleaks) must pass.
5. Update docs (`README.md`, `progress.md`, `CHANGELOG.md`) when behaviour changes.

## Rules

- Never commit secrets, `.env`, audio files, model weights or build output (see `.gitignore`).
- Never force-push shared branches.
- Keep the server bound to `127.0.0.1` unless a reviewed security design says otherwise.
- New dependencies: pin the version and check the licence (THIRD_PARTY_NOTICES.md).
