# Malayalam Voice Studio

Type Malayalam, hear it spoken: tones, characters, sound effects, and your own (consented) cloned voice.
Malayalam only (`ml`). Personal, non-commercial use (model licence, below).

## Using it

1. **Malayalam Voice** in the sidebar.
2. Type or paste Malayalam (up to 20,000 characters), or **Load example story**.
3. Pick the **narrator voice** and a default **tone**. Characters written as `Name: "…"` are listed automatically,
   each with its own voice.
4. **Speak.** Each line can be played on its own and **regenerated** (a new take) without redoing the rest.
5. Download the story (WAV, MP3, FLAC, OGG, M4A). It is saved under `Music\Mixlumo\Malayalam voice - voice <date>`.
   Use the Cutter, Joiner, Pitch & Tempo (lo-fi, echo) and Converter on it like any other audio.

### Script tags

| Tag | Effect |
|---|---|
| `[happy]` `[angry]`/`[angrily]` `[sad]` `[crying]` `[excited]` `[fearful]` `[calm]` `[romantic]` `[whispers]` `[sarcastic]` `[confident]` `[surprised]` | The line's tone (13 presets) |
| `[dramatically]` `[deadpan]` `[confused]` `[proudly]` | Extra story tones |
| `[laughs]` `[giggles]` `[bursts into laughter]` | A laugh (OmniVoice `[laughter]`, with a short "ഹ ഹ ഹ") |
| `[sighs]` `[gasps]` `[hmm]` | Sounds the voice performs (OmniVoice non-verbal tags) |
| `[pause]` `[short pause]` `[dramatic pause]` | Silence (scaled by the Pauses slider) |
| `[dragon voice]` `[robot voice]` `[echo]` `[radio voice]` | Effects applied after speaking |
| `Name: "…"` | A character line, in that character's voice |
| `"…"` | Another character (the "Other quoted lines" voice) |

Unknown tags are skipped with a warning and never read aloud. Emojis are removed. The numbers 0–10, 20, 50 and 100
are read as Malayalam words; write other numbers as words.

### Tones: what is real and what is approximate

The voice model, OmniVoice, has **no emotion switch**. The studio is honest about this, and each line in the result
says which way it was made:

| Badge | How the tone is made | Quality |
|---|---|---|
| **real tone** | The voice has its **own sample recorded in that tone**. OmniVoice copies the delivery of the sample. | Genuinely spoken in that tone |
| **approximate** | No sample for that tone: the normal voice is spoken at the tone's speed, then shaped (pitch, level; a little growl for angry, tremble for crying/fear, softness for whisper, warmth for romantic) | An approximation |

- **Whisper is real for built-in voices**: OmniVoice's voice design has a native whisper style, and each built-in
  voice gets a whisper sample when first used.
- **For real tones with your own voice**, add one 3–10 s sample per tone under *My voices*, with *Tone of this sample*
  set to, for example, *Angry*.
- *Tone intensity* (0–100) scales the shaping. It does not change a real-tone line, which is spoken as recorded.

### Voices

- **Built-in voices** (Female young/adult/elderly, Male young/adult/elderly, Child) are designed once with OmniVoice
  voice design and then frozen, so a character keeps the same voice in every line. They are synthetic, not real people.
- **Your own voice**: *My voices → Add a voice*. Record in the app (microphone) or upload 3–10 seconds of one person
  speaking Malayalam clearly. Type the **exact** words spoken, confirm consent, then *Learn this voice*. Clones are
  approximate: a clean, close recording with an exact transcript works best.

## Hardware and speed (measured)

| | GeForce GTX 1650 (4 GB), this PC |
|---|---|
| GPU memory | about 2.0–2.1 GB (model 1.9 GB) |
| Speed, Fast (16 steps) | about **2.1× the speech length** (6.5 s for 3.1 s of speech); whole example story: 42 s of audio in 101 s |
| Speed, Best (32 steps) | about 4.2× the speech length |
| First use | about 20 s model load; each built-in voice takes about 40 s to prepare, once |
| Making a voice profile | about 1.6 s (on the CPU) |

Notes:
- The GTX 1650 has no tensor cores and runs half-precision matrix maths about 5× slower than full precision. The voice
  worker measures this at start-up and keeps fp16 weights but computes in fp32 (4.6× faster, same memory).
- A 4 GB card holds one AI model at a time. Starting a voice job releases the vocal remover's model, and the other way
  round, automatically.
- Without an NVIDIA GPU it runs on the CPU, much slower.

## Setup

```powershell
.\scripts\setup-voice.ps1
```

- This creates a **separate** Python environment (`%USERPROFILE%\.audiostudio\tts-venv`) with PyTorch 2.7.1 + CUDA 11.8
  and OmniVoice (pinned commit `4d5ed0f`), then downloads the model (3.1 GB).
- Mixlumo's own environment is untouched: the two never share packages.
- Needs Python 3.12, git, about 8 GB free disk and an internet connection, once.
- The installed Mixlumo app finds the voice environment automatically. Without it, the page says the engine is not
  installed.

## Architecture

```
static/index.html (Malayalam Voice page)
  │  /api/jobs {tool: "voice" | "voice_profile"}, /api/voice/*
server.py ── same job queue as every tool (one job at a time); GPU hand-over between the voice and separation workers
  │
voice_studio.py ── request validation (Malayalam only), story_script.py parsing, voices, tones (voice_tones.py),
  │                 effects and joining with the existing audio engine (engine.py), regenerate, profile jobs
voice_profiles.py ── profiles, reference-audio and transcript validation, consent records, deletion
voice_engine.py ── starts voice_worker.py with the voice environment's Python; JSON lines over stdin/stdout
voice_worker.py ── OmniVoice, loaded once; exits when idle (5 min) or when Mixlumo exits
```

### API

| Endpoint | Purpose |
|---|---|
| `POST /api/jobs {"tool": "voice", "params": {...}}` | Speak a script. Params: `script`, `voice`, `cast` {name: voice}, `tone`, `intensity`, `speed`, `pitch`, `volume`, `pause`, `quality` (fast/best), `format`, `seed` |
| `POST /api/jobs {"tool": "voice", "params": {"regenerate": <job id>, "lines": [i]}}` | New take of a line of a finished result |
| `POST /api/jobs {"tool": "voice_profile", "params": {...}}` | Learn a voice or a tone sample. Params: `upload`, `transcript`, `tone`, and `name` + `consent: true` (new voice) or `profile` (existing voice). Rate limited: 20 per 10 minutes. |
| `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel` | Progress; stop (voice jobs stop after the current line) |
| `GET /api/voice/status` | Engine installed, tones, licence notices, consent text |
| `GET /api/voice/profiles`, `GET/PATCH/DELETE /api/voice/profiles/{id}`, `DELETE /api/voice/profiles/{id}/tones/{tone}` | Voice profiles |

## Licences

| Part | Licence |
|---|---|
| OmniVoice code (k2-fsa) | Apache-2.0 |
| **OmniVoice model weights** | **CC-BY-NC 4.0: non-commercial** (training data). Fine for personal use; not for a paid product. |
| Audio tokenizer (Boson AI Higgs Audio 2) | Boson Higgs Audio 2 Community License (Llama 3 based). Attribution shown in the app; over 100,000 annual users needs a licence from Boson AI. |

The required attribution is shown on the Voice Studio page. Every result carries the line "AI-generated speech
(Mixlumo Voice Studio)."

## Troubleshooting

| Message | Fix |
|---|---|
| "Voice engine not installed" | Run `scripts\setup-voice.ps1` |
| "The GPU ran out of memory" | Close games or browser tabs playing video. Split very long lines. |
| "Line N could not be spoken and was left silent" | *Regenerate* that line, or reword it (bare tags with no words give the model nothing to say) |
| Very slow | First use loads the model (~20 s) and creates built-in voices (once). Use *Fast* quality. |
| Logs | `%USERPROFILE%\.audiostudio\logs\voice-worker.log` |

## Limitations

- Emotions other than whisper are approximate unless the voice has a sample in that tone.
- Clones approximate the reference voice. Similarity depends on recording quality and the exact transcript.
- Only the numbers listed above are converted to words.
- One generation at a time. On a 4 GB GPU, speech is about 2× slower than real time.
- Slang and colloquial style come from the model's training. Fine-tuning (LoRA, supported by OmniVoice) is not part
  of this release.
