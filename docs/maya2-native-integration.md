# Maya 2 Native for the Malayalam Voice Studio: integration assessment

Status: **assessment only; nothing implemented yet.** Sources (read 2026-11-25):
[model card](https://huggingface.co/maya-research/maya2-native),
[repository](https://github.com/MayaResearch/maya2-native) and both LICENSE files. Anything marked
"not documented" was not found there and must be verified before relying on it.

## Licence

| Item | Finding |
|---|---|
| Weights and engine | **Apache-2.0** (standard text, no extra clauses, no gated access) |
| Commercial use | Allowed; self-hosting needs no Maya API key |
| Upstream parts | Qwen3-1.7B-Base (Apache-2.0), Kyutai Mimi codec (**CC-BY-4.0: attribution required**), SpeechBrain ECAPA-TDNN (Apache-2.0). Keep their notices. |
| Voice cloning | No licence restriction. Policy: clone only voices you own or have explicit permission to use; disclose synthetic speech; no impersonation, fraud or bypassing voice authentication |
| Watermark | None ("This release does not add an audio watermark") |

This is a clear licence, unlike Lyric Voice (see `lyric-license-review.md`, commercial terms unconfirmed).

## Model

- Qwen3-1.7B-based backbone plus a ~555M depth decoder: about 2.5B unique parameters, ~5.0 GB BF16 weights.
- Codec: Kyutai Mimi (32 codebooks, 12.5 frames/s). Output: 24 kHz mono.
- Languages: as bn en gu hi kn ml mr or pa ta te. **Malayalam = `lang="ml"`.** Malayalam CER 3.75–4.20 % (vendor scores).
- Built-in voices trained on Malayalam (≥ 1 h): Ahana, Vaidehi, Malini, Charvi, Jahnavi (female); Anirban, Nakul, Vasant, Siddhant, Satvik (male). Synthetic personas, not real people.

## API (as documented)

```python
from maya3 import Maya3TTS
tts = Maya3TTS.from_pretrained("maya-research/maya2-native", max_seats=1)
audio = tts.generate("…", lang="ml", voice="Ahana", normalize=True)          # float32, 24 kHz mono
for pcm in tts.stream("…", lang="ml", voice="Ahana", normalize=True): ...      # int16 chunks
tts.register_voice("my_voice", ref_audio="ref.wav", ref_text="<exact transcript>", lang="ml")
tts.close()
```

- Cloning: 3–10 s clean single-speaker reference plus its exact transcript. Modes `icl_spk` (default),
  `icl`, `spk` (embedding only, no transcript). Clones are approximate; no cloning benchmark published.
- Built-in HTTP/WebSocket server (`python -m maya3.server`): `/v1/audio/speech`, `/v1/tts/stream`
  (cancellation supported), `/v1/voices`, `/health`. **No authentication**, so it must never be exposed directly.
- Emotion: only `[laughs] [sighs] [whispers] [sad] [excited]` are documented, as "best effort". No full
  tag list, no intensity control, no speaking-rate or pitch controls.

## Hardware and software requirements

| Requirement | Maya 2 Native | This PC |
|---|---|---|
| OS | Linux | Windows 11 (WSL2 Ubuntu is installed) |
| GPU driver | CUDA 12.8 (driver 570 or newer) | driver 457.34 = CUDA 11.1 |
| GPU memory | 8 GB minimum; single-seat **peak ≈ 9.2 GB** + CUDA context; 12 GB+ recommended | GeForce GTX 1650, **4 GB** |
| CPU inference | Not supported or documented | n/a |
| PyTorch | torch 2.8.0 + cu128, triton 3.4.0, transformers 5.6.2, speechbrain 1.1.2 | Mixlumo uses torch 2.5.1 + cu118 |

**Conclusion: the model cannot run on this PC.** The GPU has less than half the memory the engine needs,
the driver is too old, and the engine is Linux-only. A driver update and WSL2 would fix the OS and driver
gaps but not the 4 GB memory limit. Quantized community builds exist (3 listed on Hugging Face) but are
undocumented, and the custom CUDA-graph engine targets BF16, which the GTX 1650 (Turing) lacks in hardware.

Its dependencies also conflict with Mixlumo's (torch 2.8/cu128 vs 2.5.1/cu118), so it must run in a
**separate environment or separate service** in any case, never inside Mixlumo's Python environment.

## Options

1. **Rented Linux GPU (12–24 GB), on demand.** Run the official `maya3` server behind an authenticated
   proxy; Mixlumo calls it over HTTPS. Needs a paid cloud account (owner's decision).
2. **Free notebook GPUs (Kaggle/Colab T4 16 GB)** for evaluation only: enough memory, but T4 has no
   hardware BF16, so the engine may not run; not usable as a service backend.
3. **A PC or server with a 12 GB+ NVIDIA GPU** running Linux or WSL2.

## Step 1 (chosen): evaluate on a free Kaggle GPU

`notebooks/maya2_malayalam_eval.ipynb` runs the **real** model and records results; nothing is simulated.

| Section | What it measures |
|---|---|
| Load | Whether the engine runs on a T4 at all. It tries the official settings, then progressively safer ones: no Triton fusions, then no CUDA graphs, then FP32 depth decoder. The backbone is fixed to BF16 in the engine and the T4 has no BF16 hardware. Records load time and GPU memory. |
| Voices | Malayalam with all 10 built-in voices trained on Malayalam: real-time factor, time to first audio, clipping, silence, NaN checks |
| Text | Greeting, paragraph, numbers (normaliser), a one-word sentence (identity drift) |
| Emotion | 5 documented tags and 3 undocumented ones, each clip with and without the tag, for listening |
| Streaming | Chunk timing and time to first chunk |
| Cloning | `icl_spk`, `icl` and `spk` modes from a **synthetic** reference (built-in voice Malini). ECAPA speaker similarity of each clone to Malini against the other voices. An optional cell clones your own voice, only with `I_CONSENT = True`. |

How to run it:
1. Sign in at kaggle.com and verify your phone number (Settings): Kaggle requires it for GPUs and internet.
2. Click **Create → New Notebook**, then **File → Import Notebook** and upload `maya2_malayalam_eval.ipynb`.
3. In the right-hand panel, under **Session options**, set **Accelerator: GPU T4 x2** and **Internet: On**.
4. Click **Run All**. It takes about 30–60 minutes: installing, a ~6 GB model download, then about 70 clips. The free quota is about 30 GPU hours a week.
5. If the load cell reports a crash mentioning *CUDA error* or *illegal memory access*: restart the session, set `START_AT` to the next attempt number, and run all again.
6. Download `maya_eval.zip` from the **Output** section and send it back. It holds `results.json` and all the clips.

Even if no setting works, the zip records why. That is a valid result, and it means a 12 GB+ BF16 GPU is needed
(option 1 or 3).

## Results: Kaggle Tesla T4 (16 GB), 2026-11-26

Real model, official settings (`max_seats=1`), torch 2.8.0+cu128, `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.
Raw data: `results.json` in the run's `maya_eval.zip`.

| Measure | Result |
|---|---|
| Runs on a T4 (no hardware BF16)? | **Yes**, with the official settings; no fallback needed |
| Load time (weights cached) | 94 s |
| GPU memory | 6.05 GB after load, **8.58 GB peak** |
| Speed | real-time factor **0.59** (median of 61 clips; range 0.57–0.77), i.e. about 1.7× faster than real time |
| Time to first audio | **0.13 s** (median); streaming first chunk 0.14 s, a 9 s paragraph streamed in about 5 s |
| Output health | 61/61 clips OK: no errors, no NaN, no clipping, no clip more than 50 % silent; levels −24 to −26 dBFS |
| Voices | All 10 Malayalam-trained voices produced audio at the same speed |
| Very short text ("ശരി.") | 0.6 s clip, works; the slowest real-time factor (0.75) |
| Emotion tags | Every tag changed the audio measurably. `[whispers]` was 6–8 dB quieter, as expected. Tagged clips ran 0.3–2.4 s longer. Undocumented tags (`[angry] [crying] [happy]`) also changed the audio, so they may be **spoken aloud** rather than acted. **Listening is needed** to tell. |
| Cloning (synthetic 3.7 s reference) | Speaker similarity to the reference: 0.58–0.72. The clone was closest to the reference voice in 5 of 9 tests and best on longer text (paragraph 0.70–0.72). On short sentences it drifted towards a similar built-in voice. This matches the vendor's "approximate" claim. |

Notes:
- The first T4 run ran out of memory at 13.3 GB with the same settings. The difference was the CUDA allocator
  setting and a fresh process, so **`expandable_segments:True` is required** on 16 GB cards.
- Not yet assessed: Malayalam pronunciation and naturalness, whether emotion tags sound right, and
  cloning of a real voice. These need a native Malayalam listener.

Whichever is chosen, the Voice Studio talks to the model through a provider interface, so the UI, API,
security, profiles, validation and audio post-processing can be built and tested independently. Tests
that need the real model run only where the model is available. They are reported as **not run**
elsewhere, never faked.

## Decision (2026-11-28)

The Voice Studio was built on **OmniVoice (k2-fsa)** instead. It runs on this PC's 4 GB GTX 1650 (about 2 GB of GPU
memory), supports Malayalam and voice cloning, and needs no rented GPU. Maya 2 Native needs about 8.6 GB and a Linux
GPU server; it remains an option for a future cloud version with a commercial-friendly licence (Apache-2.0), which
OmniVoice's weights (CC-BY-NC) are not. See `docs/voice-studio.md`.
