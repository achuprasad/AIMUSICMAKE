# Security policy

## Reporting a vulnerability

Please **do not open a public issue**. Report privately through GitHub's
*Security → Report a vulnerability* (private advisory) on this repository. Include steps to
reproduce, the affected version and the impact. You'll get an acknowledgement within 7 days.

## Current security model (v1.0, desktop / local)

- The server listens **only on 127.0.0.1**, so other machines cannot reach it (tested).
- No accounts, passwords, payment data or secrets exist in the app or the repository.
- Uploads: 1 GB limit, content verified by decoding (spoofed files rejected), server-generated
  storage names, original filenames stripped of paths (tested against traversal).
- Every option is validated against an allowlist or numeric range; raw file paths from clients
  are never accepted.
- Output files are only served from the output folder; path traversal is tested.
- AI inference runs in a separate process; a crash there cannot take down the server.
- Automated checks: ruff with bandit (`S`) rules, mypy, pip-audit, Gitleaks (CI).

## Known issues

| Issue | Severity | Status |
|---|---|---|
| PyTorch 2.5.1 affected by CVE-2025-32434 (`torch.load` with a malicious checkpoint) | Medium locally / high in cloud | Models are loaded only from fixed sources. Upgrade to PyTorch ≥ 2.6 planned (needs NVIDIA driver ≥ 520 for CUDA 12, or the CUDA 11.8 build of 2.6/2.7) |
| ffmpeg and CPU tools run without CPU/memory/time limits | Medium | Needed before any server deployment |
| No HTTP security headers (CSP, HSTS) | Low locally | Needed before any server deployment |

## Before any internet-facing deployment

The local security model does **not** carry over to a cloud service. Authentication,
authorization (per-user ownership), rate limiting, CORS/CSRF, security headers, isolated media
workers with resource limits and no outbound network, private storage with signed URLs, and
secrets management are all required. See docs/technical-assessment.md §4.
