# Voice cloning: consent, privacy and security

Mixlumo is a local, single-user desktop app (server bound to 127.0.0.1). This page covers what the Voice Studio
does to protect voices, and what a web/cloud deployment must add.

## Consent

- A new voice can't be created without ticking the consent statement: *"I confirm this is my own voice, or the speaker
  has given me explicit permission to clone it, and I will not use it to impersonate or deceive anyone."* The server
  enforces it (`consent` must be exactly `true`), not only the page.
- The statement and the time are stored with the voice (`meta.json`). They are never sent to the page.
- The app never claims a clone is exact. Clones are described as approximate.
- Every result says *"AI-generated speech (Mixlumo Voice Studio)."*. Users should disclose synthetic speech to
  listeners, as the model licences also require.
- No public sharing: voices and results stay on the PC.

## What is stored

| Item | Where | Kept? |
|---|---|---|
| Reference recording | Uploaded to a temporary folder, then decoded and checked | **Deleted** as soon as the job ends, whether it succeeded or failed (the voice folder keeps a copy only if `keep_recording` is set) |
| Encoded voice prompt (`tones/<tone>.pt`, about 8 KB) | `%USERPROFILE%\.audiostudio\voices\<id>\` | Until the voice is deleted |
| Transcript of each sample, consent record, name | `meta.json` in the same folder | Until the voice is deleted |
| Generated speech | `Music\Mixlumo\Malayalam voice - voice <date>\` | The user's files |

Deleting a voice overwrites its files with zeros, then removes the folder. Removing one tone deletes that tone's
file. The voice folder is inside the user's profile, so Windows account permissions protect it.

**Not done (documented gap):** voice prompts are not encrypted at rest beyond Windows account permissions. On a shared
or cloud machine, encrypt the voices folder (BitLocker or EFS), or add application-level encryption (Windows DPAPI)
before storing voices for other people.

## Input validation (server side)

- **Ids:** profile ids must match `^[0-9a-f]{12}$` or be a known built-in id. Every path is built from a validated id,
  never from user text. Tests try `../`, URL-encoded traversal, built-in look-alikes and oversized ids.
- **Folders:** regenerate refers to a previous result by **job id**. The server looks up its folder; a client-sent
  `previous` path is discarded.
- **Uploads:** the existing upload checks (size limit, empty files, files that don't decode as audio, spoofed
  extensions). Each recording is then checked for 2–15 s of speech, level and clipping.
- **Transcripts:** NFC-normalised, 2–400 characters, at least 60 % Malayalam script.
- **Names:** control characters removed, 40 characters at most.
- **Scripts:** at most 20,000 characters and 300 lines, Malayalam only. Tags are parsed and never spoken; unknown
  tags are reported.
- **Settings:** every number is range-checked (speed 0.5–2, pitch ±6, volume −12…+6 dB, intensity 0–100,
  pauses 25–300 %), and every choice (tone, quality, format, voice) comes from a fixed list.
- **Output:** user text is always inserted into the page escaped. Names and transcripts can't inject HTML.

## Abuse limits

- Voice cloning: 20 samples per 10 minutes per client (HTTP 429 after that).
- Generation runs in the single job queue, one job at a time, and can be cancelled.
- Cross-site requests are blocked for every writing endpoint (same-origin check; `Origin: null` is refused). Request
  bodies are limited to 64 KB.

## Process isolation

- The voice model runs in its own process, from its own Python environment, started with `python -I` (isolated: no
  user site-packages, no current-directory imports).
- The worker only accepts commands on stdin from Mixlumo. It exits when Mixlumo exits (stdin closes) or after 5 idle
  minutes. Crashes are reported and the next job starts a fresh worker.
- Model files come from Hugging Face (`k2-fsa/OmniVoice`); the engine code is pinned to a commit.

## Audit trail

- Deleting a voice writes `voice profile <id> deleted` to the app log (the id only: no names, transcripts or audio).
- Consent is recorded per voice.
- Generated results keep a `plan.json` with the script and settings, next to the audio.

## For a web or cloud deployment (not done here)

**Today the Voice Studio is switched off in the web version** (`AUDIO_STUDIO_WEB=1`, the Docker image). Every voice
endpoint and voice job returns 403 on the server, and the page explains that it is desktop-only. Reason: the web
version has no user accounts, so anyone who can reach it could clone voices or delete them. Tested in
`tests/test_voice_api.py::test_web_mode_disables_the_voice_studio`.

The desktop app has no user accounts. Before exposing the Voice Studio to other people:

1. **Authentication and per-user authorisation** on every `/api/voice/*` and job endpoint. Profiles and results must
   be scoped to their owner. Today all profiles on the PC belong to its one user.
2. **Encryption at rest** for voice prompts and recordings, with keys per user.
3. **Stronger consent:** for example, a spoken consent phrase in the reference recording, checked automatically.
   Keep records for disputes.
4. **Rate limits per account**, and abuse reporting.
5. **Licence:** the OmniVoice model weights are **CC-BY-NC (non-commercial)**. A commercial service needs a different
   model or a licence. The Boson AI tokenizer licence requires attribution and has a 100,000-annual-user threshold.
