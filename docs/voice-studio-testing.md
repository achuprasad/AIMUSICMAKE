# Voice Studio testing

Two kinds of tests, so the fast suite never needs the 3 GB model or a GPU, and the real model is still checked:

| Suite | Engine | Where | Runs in |
|---|---|---|---|
| Automated tests (unit, API, browser) | The real worker **process** and pipe protocol, with its **test-only stand-in synthesiser** (`MIXLUMO_VOICE_FAKE=1`, set only in `tests/conftest.py`). It makes tones, not speech. | Any PC, CI | `run_tests.ps1` stages 3, 4, 5 |
| Real-model check | Real OmniVoice on the GPU | A PC with the voice environment | `python scripts\voice_real_check.py` |

The stand-in mode exists only for tests. It is switched on by an environment variable the app never sets, and the
page shows "Test mode (stand-in voice)" when it is on.

## Automated tests

| File | Covers |
|---|---|
| `tests/test_story_script.py` | Script parsing: tones, characters (`Name: "…"`), quoted lines, effects, pauses, laughs, in-line sounds (`[sighs]` → `[sigh]`), sound-only lines, unknown tags (never spoken), emoji removal, ZWJ/ZWNJ kept, numbers to Malayalam words, long-line warning, empty input |
| `tests/test_voice_engine.py` | Worker process: **Malayalam survives the pipe unchanged** (regression for a Windows encoding bug), ping, profile, generation with progress, user errors, crash mid-job then recovery, restart after an idle death, stop, not-installed message |
| `tests/test_voice_studio.py` | Validation (transcript Malayalam-only and length; names; reference recordings: too short, too long, too quiet, distorted, empty, NaN, warnings); profiles (consent required, create/rename/list/delete, id and path-traversal attempts, built-ins protected, best tone, neutral removed last); tones (13 presets first, speed scaling, real-tone lines untouched, shaping bounded and finite); requests (12 invalid requests); story plans (cast, default tone, pause scaling, numbers, effects, seeds); rendering (built-ins designed once and frozen, real whisper, approximate angry, progress, plan file); regenerate (only that line changes); cancel; own voice with a tone sample (real tone); a failing line retried then left silent with a warning |
| `tests/test_voice_api.py` | HTTP: status, built-ins listed without internals, full clone lifecycle (consent, English refused, tone sample, rename, delete, **recording deleted after learning**), malicious ids, built-ins protected, upload required, **rate limit (429)**, speak and regenerate, regenerate needs a finished job, a client-sent folder path is ignored, English refused, cancel, cross-site requests blocked (403), GPU release stops the voice engine |
| `tests/e2e/test_voice_ui.py` | Browser (Chromium and Edge): page, tone list, licences, tone hints, tag insertion, character detection, speak a story, play a line, real/approximate badges, regenerate, English error, add/rename/delete a voice (consent gate), phone width |
| `tests/e2e/test_ui.py` | The Voice page is also in the existing responsive (375/768/1440 px) and accessible-names checks |

## Real-model results (this PC: GeForce GTX 1650 4 GB, driver 457.34, 2026-11-28)

`scripts\voice_real_check.py`: **all 11 checks passed**.
- Model load 16 s (warm), 1.9 GB GPU, fp32 maths chosen automatically.
- Voice design 3.6 s of speech in 10.6 s (Best quality). Profile 1.7 s.
- Cloned plain, colloquial, laughter and sigh lines and a slower line: 13.9 s of speech in 35 s, **2.5× the speech
  length** at Fast quality.

Example story through the app, real model: 11 steps (10 spoken lines and a pause), **42 s of audio in 101 s**, no
errors, no warnings. Covered: narrator, two characters, monster effect, real whisper, two laughs.

Found and fixed during these runs:
1. **Malayalam garbled on its way to the worker** (`python -I` ignores `PYTHONIOENCODING`, so Windows used cp1252).
   The worker now sets UTF-8 itself. Pipe round-trip test added.
2. **A bare `[laughter]` gives no audio.** Sound-only lines now get a short Malayalam sound. A failing line is retried
   once, then left silent with a warning, so a story never fails because of one line. Test added.
3. **The voice profile encoder ran out of GPU memory on 4 GB.** Profiles are now encoded on the CPU (one-off, 1.6 s).
4. **fp16 maths is 5× slower than fp32 on the GTX 1650.** Weights stay fp16, maths runs in fp32: 4.6× faster.
5. **Two voice jobs in the same second shared an output folder.** Fixed and tested.

## Not covered automatically

- **Malayalam pronunciation, naturalness and how convincing each tone sounds:** needs a native listener. Listen to
  the clips in `Music\Mixlumo\voice-tests\`.
- **Cloning a real person's voice:** tested only with synthetic voices. Try it with your own voice (with consent).
- **The packaged EXE with the voice engine:** the EXE ships `voice_worker.py` and uses the voice environment installed
  by `setup-voice.ps1`. That combination should be checked after the next build.
