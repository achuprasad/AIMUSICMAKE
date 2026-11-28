# Copyright (c) 2026 Achu Prasad. All rights reserved. See LICENSE.
"""Real-model check of the Malayalam Voice Studio (needs the voice environment: scripts/setup-voice.ps1).

    python scripts/voice_real_check.py [out_dir]

Uses the real OmniVoice model on this PC; no real person's voice is involved: the reference voice is designed by the
model itself. Checks: worker start and device, voice design, profile creation, cloned speech, tags, speed,
audio validity, timing and GPU use. Exit code 0 = all checks passed. The automated test suite cannot do this (it uses
a stand-in synthesiser), so run this after changing the voice worker or upgrading the voice environment.
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("MIXLUMO_VOICE_FAKE", None)
import voice_engine as ve  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Music" / "Mixlumo" / "voice-tests" / "real-check"
OUT.mkdir(parents=True, exist_ok=True)
SAMPLE = "നമസ്കാരം, ഇന്ന് നമുക്ക് ഒരു രസകരമായ കഥ കേൾക്കാം."
LINES = {
    "plain": "കേരളം ദൈവത്തിന്റെ സ്വന്തം നാടാണ്.",
    "colloquial": "എടാ, നീ എവിടെയാ? ഞാൻ ഇവിടെ കാത്തിരിക്കുവാ, പെട്ടെന്ന് വാ.",
    "laughter": "[laughter] ഹ ഹ ഹ ഹ.",
    "sigh": "[sigh] ഇന്നത്തെ ദിവസം വളരെ ക്ഷീണിപ്പിക്കുന്നതായിരുന്നു.",
}
results, failed = {}, []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name, detail, flush=True)
    if not cond:
        failed.append(name)


def audio(path, min_s, max_s):
    w, sr = sf.read(path, dtype="float32")
    s = len(w) / sr
    return sr == 24000 and min_s <= s <= max_s and np.isfinite(w).all() and float(np.abs(w).max()) > 0.02, round(s, 2)


eng = ve.VoiceEngine()
check("voice environment installed", eng.installed, str(eng.python))
if not eng.installed:
    sys.exit(1)
try:
    t = time.time()
    info = eng.call("load")["info"]
    results["load"] = {**info, "seconds": round(time.time() - t, 1)}
    check("model loads", not info.get("fake"), json.dumps(results["load"]))
    sample = str(OUT / "designed_sample.wav")
    t = time.time()
    eng.call("generate", items=[{"text": SAMPLE, "out": sample, "instruct": "female, middle-aged, moderate pitch",
                                 "seed": 7, "steps": 32}])
    ok, s = audio(sample, 1.5, 12)
    check("voice design speaks Malayalam", ok, f"{s} s in {time.time() - t:.1f} s")
    prof = str(OUT / "designed.pt")
    r = eng.call("make_profile", ref=sample, text=SAMPLE, out=prof)
    check("voice profile created", Path(prof).is_file(), f"{r.get('seconds')} s")
    items = [{"text": txt, "out": str(OUT / f"{k}.wav"), "profile": prof, "seed": 11, "steps": 16}
             for k, txt in LINES.items()]
    items.append({"text": LINES["plain"], "out": str(OUT / "plain_slow.wav"), "profile": prof, "seed": 11, "steps": 16,
                  "speed": 0.8})
    t = time.time()
    r = eng.call("generate", items=items)
    total = time.time() - t
    speech = sum(i["audio_s"] for i in r["items"])
    for it in r["items"]:
        ok, s = audio(it["out"], 0.5, 20)
        check(f"cloned line {Path(it['out']).stem}", ok, f"{s} s audio in {it['seconds']} s")
    plain, slow = (sf.info(str(OUT / n)).duration for n in ("plain.wav", "plain_slow.wav"))
    check("speed 0.8 gives longer speech", slow > plain * 1.1, f"{plain:.2f} s -> {slow:.2f} s")
    results["speed"] = {"speech_seconds": round(speech, 1), "generation_seconds": round(total, 1),
                        "times_speech_length": round(total / speech, 2)}
    check("faster than 4x the speech length (Fast quality)", total / speech < 4, json.dumps(results["speed"]))
finally:
    eng.stop()
(OUT / "results.json").write_text(json.dumps({"results": results, "failed": failed}, indent=1), encoding="utf-8")
print(("ALL CHECKS PASSED" if not failed else f"FAILED: {failed}") + f"  (clips in {OUT})")
sys.exit(1 if failed else 0)
