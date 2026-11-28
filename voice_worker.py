# Copyright (c) 2026 Achu Prasad. All rights reserved. See LICENSE.
"""Malayalam voice worker: runs OmniVoice (k2-fsa) in its own Python environment (the voice environment,
`~/.audiostudio/tts-venv`), separate from the separation engine's environment, so their PyTorch versions can
never conflict.

Protocol: the parent writes one JSON object per line on stdin and reads replies on stdout. Every reply line
starts with MARK; anything else printed by libraries goes to stderr. Commands:

    {"cmd": "ping"} / {"cmd": "echo", "text": ...}
    {"cmd": "make_profile", "ref": <wav path>, "text": <exact transcript>, "out": <.pt path>}
    {"cmd": "generate", "items": [{"text", "out", "profile"?, "instruct"?, "speed"?, "steps"?, "seed"?}, ...]}
    {"cmd": "quit"}

Replies: {"event": "progress", ...} while working, then exactly one {"done": true, "ok": bool, ...}.
The worker exits when stdin closes (the app quit or crashed) or after IDLE seconds without a command.

Model licences: OmniVoice weights CC-BY-NC (non-commercial); its audio tokenizer is under the Boson Higgs
Audio 2 Community License. See docs/voice-studio.md.
"""
import json
import os
import sys
import threading
import time
import traceback

MARK = "@@mixlumo@@ "
MODEL_ID = os.environ.get("MIXLUMO_VOICE_MODEL", "k2-fsa/OmniVoice")
IDLE = float(os.environ.get("MIXLUMO_VOICE_IDLE_S", "300"))
FAKE = os.environ.get("MIXLUMO_VOICE_FAKE") == "1"       # test-only stand-in synthesiser (no model, no GPU)
SR = 24000
# The worker runs with python -I, which ignores PYTHONIOENCODING: set UTF-8 explicitly, or Malayalam text from the
# app arrives garbled on Windows (cp1252) and the transcript of a voice profile is silently wrong.
for _s in (sys.stdin, sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="strict" if _s is sys.stdin else "replace")
_out = sys.stdout
sys.stdout = sys.stderr                                  # keep library prints out of the protocol channel


def send(obj):
    _out.write(MARK + json.dumps(obj, ensure_ascii=False) + "\n")
    _out.flush()


class UserError(Exception):
    """A problem the user can fix (bad reference audio, missing file); shown as is."""


class Engine:
    def __init__(self):
        self.model = None
        self.info = {"fake": FAKE}
        self._prompts = {}

    # ------------------------------------------------------------------ loading
    def load(self):
        if self.model is not None or FAKE:
            return
        os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        import torch
        from omnivoice import OmniVoice
        t = time.time()
        cuda = torch.cuda.is_available()
        self.model = OmniVoice.from_pretrained(MODEL_ID, device_map="cuda:0" if cuda else "cpu",
                                               dtype=torch.float16 if cuda else torch.float32)
        self.info.update(device=torch.cuda.get_device_name(0) if cuda else "CPU", load_seconds=round(time.time() - t, 1),
                         fp32_math=False)
        if cuda and self._fp32_faster(torch):
            self._use_fp32_math(torch)
            self.info["fp32_math"] = True
        self.info["gpu_gb"] = round(torch.cuda.memory_allocated() / 2**30, 2) if cuda else 0

    @staticmethod
    def _fp32_faster(torch):
        """Some GPUs without tensor cores (e.g. GTX 1650) run fp16 matmuls far slower than fp32."""
        def speed(dt):
            a = torch.randn(2048, 2048, device="cuda", dtype=dt)
            a @ a
            torch.cuda.synchronize()
            t = time.time()
            for _ in range(5):
                a @ a
            torch.cuda.synchronize()
            return time.time() - t
        return speed(torch.float16) > 1.5 * speed(torch.float32)

    def _use_fp32_math(self, torch):
        """Keep fp16 weights (memory) but compute every Linear in fp32 (measured 4.6x faster on a GTX 1650)."""
        import torch.nn.functional as F

        def fwd(mod, x):
            b = mod.bias.float() if mod.bias is not None else None
            return F.linear(x.float(), mod.weight.float(), b).to(x.dtype)
        for name, mod in self.model.named_modules():
            if isinstance(mod, torch.nn.Linear) and not name.startswith("audio_tokenizer"):
                mod.forward = fwd.__get__(mod, torch.nn.Linear)

    # ------------------------------------------------------------------ voice profiles
    def make_profile(self, ref, text, out):
        if not os.path.isfile(ref):
            raise UserError("Reference recording not found.")
        if not text or not text.strip():
            raise UserError("The exact words spoken in the recording are required.")
        t = time.time()
        if FAKE:
            import numpy as np
            np.save(out + ".npy", np.zeros(4))
            os.replace(out + ".npy", out)
            return {"seconds": round(time.time() - t, 2)}
        self.load()
        import torch
        dev = next(self.model.audio_tokenizer.parameters()).device
        # The tokenizer's encoder doesn't fit next to the model on a 4 GB GPU, and a profile is made once:
        # encode on the CPU, then move it back for decoding during generation.
        self.model.audio_tokenizer.to("cpu")
        if dev.type == "cuda":
            torch.cuda.empty_cache()
        try:
            prompt = self.model.create_voice_clone_prompt(ref_audio=ref, ref_text=text.strip())
        except ValueError as e:
            raise UserError(f"Can't use this recording: {e}") from None
        finally:
            self.model.audio_tokenizer.to(dev)
        tmp = out + ".tmp"
        prompt.save(tmp)
        os.replace(tmp, out)
        frames = int(prompt.ref_audio_tokens.shape[-1])
        hop = getattr(self.model.audio_tokenizer.config, "hop_length", 960)
        return {"seconds": round(time.time() - t, 2), "voice_seconds": round(frames * hop / SR, 2)}

    def _prompt(self, path):
        from omnivoice import VoiceClonePrompt
        key = (path, os.path.getmtime(path))
        if key not in self._prompts:
            self._prompts = {k: v for k, v in self._prompts.items() if k[0] != path}
            self._prompts[key] = VoiceClonePrompt.load(path)
        return self._prompts[key]

    # ------------------------------------------------------------------ speech
    def generate(self, items, progress):
        import numpy as np
        import soundfile as sf
        results = []
        for i, it in enumerate(items):
            text = str(it.get("text", "")).strip()
            if not text:
                raise UserError(f"Line {i + 1} is empty.")
            t = time.time()
            if FAKE:
                if text == "__crash__":           # test hook (fake mode only): simulate a hard crash mid-job
                    os._exit(3)
                if "__nosound__" in text:         # test hook (fake mode only): the model returns no audio
                    raise UserError(f"The voice model returned no sound for: {text[:60]}")
                n = int(SR * (0.25 + 0.06 * len(text) / max(float(it.get("speed") or 1.0), 0.1)))
                tt = np.arange(n) / SR
                tone = np.sin(2 * np.pi * (170 + 7 * (len(text) % 9)) * tt)
                w = (0.2 * tone * np.sin(np.pi * tt / tt[-1])).astype(np.float32)
            else:
                self.load()
                import torch
                kw = {"text": text, "language": "ml", "num_step": int(it.get("steps") or 16)}
                if it.get("speed"):
                    kw["speed"] = float(it["speed"])
                if it.get("profile"):
                    kw["voice_clone_prompt"] = self._prompt(it["profile"])
                elif it.get("instruct"):
                    kw["instruct"] = str(it["instruct"])
                if it.get("seed") is not None:
                    torch.manual_seed(int(it["seed"]))
                try:
                    w = np.asarray(self.model.generate(**kw)[0], np.float32).reshape(-1)
                except torch.OutOfMemoryError:
                    torch.cuda.empty_cache()
                    raise UserError("The GPU ran out of memory. Close other GPU apps (games, browsers with video) "
                                    "or split very long lines, then try again.") from None
            if len(w) == 0:
                raise UserError(f"The voice model returned no sound for: {text[:60]}")
            if not np.isfinite(w).all():
                raise RuntimeError(f"line {i + 1}: the model returned invalid audio")
            tmp = it["out"] + ".tmp.wav"
            sf.write(tmp, w, SR, subtype="PCM_16")
            os.replace(tmp, it["out"])
            r = {"index": i, "out": it["out"], "audio_s": round(len(w) / SR, 2), "seconds": round(time.time() - t, 2)}
            results.append(r)
            progress({"event": "progress", **r, "total": len(items)})
        return {"items": results}


def _watch_idle(last):
    while True:
        time.sleep(5)
        if time.time() - last[0] > IDLE:
            os._exit(0)


def main():
    eng = Engine()
    last = [time.time()]
    threading.Thread(target=_watch_idle, args=(last,), daemon=True).start()
    for raw in sys.stdin:                      # ends when the parent closes the pipe or dies
        line = raw.strip()
        if not line:
            continue
        last[0] = time.time()
        try:
            msg = json.loads(line)
            cmd = msg.get("cmd")
            if cmd == "quit":
                send({"done": True, "ok": True})
                return
            if cmd == "ping":
                res = {"info": eng.info, "loaded": eng.model is not None}
            elif cmd == "echo":                # lets tests check Malayalam survives the pipe unchanged
                res = {"text": msg.get("text", "")}
            elif cmd == "load":
                eng.load()
                res = {"info": eng.info}
            elif cmd == "make_profile":
                res = eng.make_profile(msg["ref"], msg.get("text", ""), msg["out"])
            elif cmd == "generate":
                res = eng.generate(msg["items"], send)
            else:
                raise UserError(f"unknown command {cmd!r}")
            send({"done": True, "ok": True, **res})
        except UserError as e:
            send({"done": True, "ok": False, "user": True, "error": str(e)})
        except Exception as e:
            traceback.print_exc()
            send({"done": True, "ok": False, "user": False, "error": f"{type(e).__name__}: {e}"[:800]})
        last[0] = time.time()


if __name__ == "__main__":
    main()
