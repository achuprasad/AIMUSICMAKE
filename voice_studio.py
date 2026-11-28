# Copyright (c) 2026 Achu Prasad. All rights reserved. See LICENSE.
"""Malayalam Voice Studio: turns a script (one sentence, a paragraph, or a story with tags) into speech.

Pipeline per job:
  1. validate the request and parse the script (story_script) into speech / pause / laugh steps;
  2. make sure every voice used exists (built-in voices are designed once, then frozen as profiles);
  3. generate each line with the voice worker (OmniVoice): the line's voice, the sample for its tone if the voice
     has one, otherwise the neutral sample at the tone's speed; every line has a fixed seed;
  4. shape each line (tone shaping when there is no tone sample, effects such as the monster voice, global pitch
     and volume) with the existing audio engine, then join lines and pauses into one file.
Lines are kept as separate files, so a single line can be regenerated (new seed) and the story re-joined.
"""
import json
import os
import shutil
import time
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf

import engine
import story_script as ss
import voice_profiles as vp
import voice_tones as vt
from voice_engine import VoiceEngineError

SR = 24000
MAX_SCRIPT = 20000
MAX_LINES = 300
QUALITY = {"fast": 16, "best": 32}
LAUGH_TEXT = {"giggle": "[laughter] ഹി ഹി ഹി.", "laugh": "[laughter] ഹ ഹ ഹ ഹ.",
              "big": "[laughter] ഹ ഹ ഹ ഹ ഹ ഹ! [laughter] ഹ ഹ ഹ!"}
DISCLOSURE = "AI-generated speech (Mixlumo Voice Studio)."


# ------------------------------------------------------------------ request
def _voice_id(v, what):
    if not isinstance(v, str) or not (vp.ID_RE.match(v) or v in vp.BUILTIN):
        raise engine.UserError(f"Choose a valid voice for {what}.")
    return v


def read_request(p):
    if not isinstance(p, dict):
        raise engine.UserError("Invalid request.")
    script = p.get("script")
    if not isinstance(script, str) or not script.strip():
        raise engine.UserError("Type some Malayalam text first.")
    if len(script) > MAX_SCRIPT:
        raise engine.UserError(f"The text is too long ({len(script):,} characters; the limit is {MAX_SCRIPT:,}). Split it.")
    body = ss.TAG_RE.sub(" ", script)
    if any(c.isalpha() for c in body) and vp.malayalam_ratio(body) < 0.5:
        raise engine.UserError("This studio speaks Malayalam only: write the text in Malayalam script.")
    voice = _voice_id(p.get("voice", "builtin-female-adult"), "the narrator")
    cast = p.get("cast") or {}
    if not isinstance(cast, dict) or len(cast) > 20:
        raise engine.UserError("Invalid character voices.")
    cast = {str(k)[:40]: _voice_id(v, f"'{k}'") for k, v in cast.items()}
    tone = engine.choice(p, "tone", list(vt.TONES), "neutral")
    return {
        "script": script, "voice": voice, "cast": cast, "tone": tone,
        "intensity": engine.number(p, "intensity", 0, 100, 60),
        "speed": engine.number(p, "speed", 0.5, 2.0, 1.0),
        "pitch": engine.number(p, "pitch", -6, 6, 0),
        "volume": engine.number(p, "volume", -12, 6, 0),
        "pause": engine.number(p, "pause", 0.25, 3.0, 1.0),
        "quality": engine.choice(p, "quality", list(QUALITY), "fast"),
        "format": engine.choice(p, "format", engine.FORMATS, "wav"),
        "seed": int(engine.number(p, "seed", 0, 2**31 - 1, 1234)),
    }


def build_plan(req):
    steps, warnings = ss.parse(req["script"])
    lines = []
    for i, s in enumerate(steps):
        if s["kind"] == "pause":
            lines.append({"kind": "pause", "seconds": s["seconds"] * req["pause"]})
            continue
        if s["kind"] == "laugh":
            lines.append({"kind": "speech", "text": LAUGH_TEXT[s["style"]], "voice": req["voice"], "tone": "neutral",
                          "effect": None, "pause_after": 0.3 * req["pause"], "seed": req["seed"] + i, "label": "laugh"})
            continue
        tone = s["emotion"] if s["emotion"] != "neutral" else req["tone"]
        voice = req["cast"].get(s["speaker"]) or req["voice"]       # unnamed quoted lines use cast["voice"] if set
        text = ss.numbers_to_words(s["text"], warnings)
        pause = (s["pause_after"] + vt.extra_pause(tone, req["intensity"])) * req["pause"]
        lines.append({"kind": "speech", "text": text, "voice": voice, "tone": tone, "effect": s.get("effect"),
                      "pause_after": pause, "seed": req["seed"] + i, "speaker": s["speaker"]})
    if not any(x["kind"] == "speech" for x in lines):
        raise engine.UserError("There is nothing to say: the text only has tags.")
    if sum(x["kind"] == "speech" for x in lines) > MAX_LINES:
        raise engine.UserError(f"More than {MAX_LINES} lines: split the story into parts.")
    return lines, warnings


# ------------------------------------------------------------------ voices
def ensure_voice(vid, client, report=None):
    """Built-in voices are designed once (OmniVoice voice design, fixed seed), then frozen as a profile. Built-ins
    also get a real whisper sample (whisper is a native voice-design style)."""
    if vid not in vp.BUILTIN:
        meta = vp.get(vid)
        if not meta.get("tones"):
            raise engine.UserError(f"The voice '{meta['name']}' has no samples yet. Add a recording first.")
        return meta
    meta = vp.ensure_builtin_record(vid)
    work = vp.VOICES / vid / "work"
    work.mkdir(exist_ok=True)
    for tone, extra in (("neutral", ""), ("whisper", ", whisper")):
        if tone in meta["tones"]:
            continue
        if report:
            report(0.03, f"Preparing the built-in voice '{meta['name']}' (first use only)...")
        sample = str(work / f"{tone}.wav")
        client.call("generate", items=[{"text": vp.BUILTIN_SAMPLE_TEXT, "out": sample, "seed": 7,
                                        "instruct": vp.BUILTIN[vid]["instruct"] + extra, "steps": 32}])
        client.call("make_profile", ref=sample, text=vp.BUILTIN_SAMPLE_TEXT, out=str(vp.tone_path(vid, tone)))
        vp.record_tone(vid, tone, vp.BUILTIN_SAMPLE_TEXT, {"seconds": None})
        meta = vp.get(vid)
    shutil.rmtree(work, ignore_errors=True)
    return meta


# ------------------------------------------------------------------ audio
def _effect(w, effect):
    if effect == "monster":
        y = engine.pitch_shift(w, -5, sr=SR)
        y = np.tanh(2.2 * y) / np.tanh(2.2)
        return engine.echo(y, 120, 35, 30, sr=SR)[0]
    if effect == "robot":
        n = np.arange(len(w)) / SR
        return w * (0.6 + 0.4 * np.sin(2 * np.pi * 50 * n))
    if effect == "echo":
        return engine.echo(w, 280, 40, 35, sr=SR)[0]
    if effect == "radio":
        from scipy.signal import butter, sosfilt
        return np.tanh(1.5 * sosfilt(butter(4, [300, 3400], btype="bandpass", fs=SR, output="sos"), w))
    return w


def _shape_line(w, line, req, exact):
    def shift(y, st):
        return engine.pitch_shift(y, st, sr=SR)
    y = vt.shape(w, SR, line["tone"], req["intensity"], exact=exact, pitch_shift=shift)
    y = _effect(y, line.get("effect"))
    if req["pitch"]:
        y = engine.pitch_shift(y, req["pitch"], sr=SR)
    y = np.asarray(y, np.float32) * (10 ** (req["volume"] / 20))
    peak = float(np.abs(y).max()) if y.size else 0.0
    return y * (0.98 / peak) if peak > 0.98 else y


def _join(lines, folder):
    parts = [np.zeros(int(0.2 * SR), np.float32)]
    for i, ln in enumerate(lines):
        if ln["kind"] == "pause":
            parts.append(np.zeros(int(ln["seconds"] * SR), np.float32))
            continue
        w, _ = sf.read(folder / "lines" / f"{i:03d}.wav", dtype="float32")
        parts += [w, np.zeros(int(ln["pause_after"] * SR), np.float32)]
    return np.concatenate(parts)


# ------------------------------------------------------------------ job
def render(params, report, client, previous=None, cancelled=lambda: False):
    """The 'voice' tool. `previous` = folder of an earlier result to regenerate `params['lines']` in."""
    if previous:
        folder = Path(previous)
        saved = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
        req, lines, warnings = saved["request"], saved["lines"], saved.get("warnings", [])
        todo = params.get("lines")
        if not isinstance(todo, list) or not todo or not all(isinstance(i, int) and 0 <= i < len(lines) for i in todo):
            raise engine.UserError("Choose the lines to regenerate.")
        for i in todo:
            if lines[i]["kind"] != "speech":
                raise engine.UserError("Only spoken lines can be regenerated.")
            lines[i]["seed"] = int(lines[i]["seed"]) + 1009        # a new take of that line only
        todo = sorted(set(todo))
    else:
        req = read_request(params)
        lines, warnings = build_plan(req)
        folder, _ = engine.job_dir("Malayalam voice", "voice")
        if (folder / "lines").exists():                         # two jobs in the same second: keep them apart
            folder = Path(f"{folder} {uuid.uuid4().hex[:4]}")
            folder.mkdir()
        (folder / "lines").mkdir()
        todo = [i for i, ln in enumerate(lines) if ln["kind"] == "speech"]

    report(0.02, "Preparing voices...")
    metas = {v: ensure_voice(v, client, report) for v in {lines[i]["voice"] for i in todo}}
    items, exact = [], {}
    for i in todo:
        ln = lines[i]
        meta = metas[ln["voice"]]
        tone_used, is_exact = vp.best_tone(meta, ln["tone"])
        exact[i] = is_exact
        items.append({"text": ln["text"], "out": str(folder / "lines" / f"{i:03d}.raw.wav"),
                      "profile": str(vp.tone_path(ln["voice"], tone_used)), "seed": ln["seed"],
                      "speed": round(req["speed"] * vt.speed_for(ln["tone"], req["intensity"], is_exact), 3),
                      "steps": QUALITY[req["quality"]]})
        ln["tone_sample"] = "exact" if is_exact else "shaped"
    report(0.05, f"Speaking {len(items)} line{'s' if len(items) != 1 else ''}...")
    t0 = time.time()
    done = [0]

    def progress(ev):
        done[0] += 1
        left = len(items) - done[0]
        per = (time.time() - t0) / done[0]
        report(0.05 + 0.85 * done[0] / len(items), f"Line {done[0]} of {len(items)} spoken"
               + (f" (about {int(per * left)} s left)" if left else ""))
        if cancelled():
            raise VoiceEngineError("Stopped.")

    # one line per call keeps cancel responsive and memory flat on 4 GB GPUs
    for i, it in zip(todo, items, strict=True):
        if cancelled():
            raise engine.UserError("Stopped.")
        try:
            client.call("generate", items=[it], on_event=progress)
        except VoiceEngineError as e:
            if "Stopped" in str(e) or "stopped unexpectedly" in str(e) or "not installed" in str(e):
                raise
            try:                                                    # one retry, a different take
                client.call("generate", items=[{**it, "seed": int(it["seed"]) + 7919}], on_event=progress)
            except VoiceEngineError as e2:
                if "Stopped" in str(e2) or "stopped unexpectedly" in str(e2):
                    raise
                sf.write(it["out"], np.zeros(int(0.3 * SR), np.float32), SR, subtype="PCM_16")
                warnings.append(f"Line {i + 1} could not be spoken and was left silent ({e2}). "
                                "Try Regenerate, or reword it.")
                lines[i]["failed"] = True
                progress({})
    report(0.92, "Shaping tones and joining lines...")
    for i in todo:
        raw = folder / "lines" / f"{i:03d}.raw.wav"
        w, _ = sf.read(raw, dtype="float32")
        y = _shape_line(w, lines[i], req, exact[i])
        sf.write(folder / "lines" / f"{i:03d}.wav", y, SR, subtype="PCM_16")
        lines[i]["seconds"] = round(len(y) / SR, 2)
        raw.unlink()
    (folder / "plan.json").write_text(json.dumps({"request": req, "lines": lines, "warnings": warnings},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    full = _join(lines, folder)
    for old in folder.glob("Malayalam voice.*"):
        old.unlink()
    out = engine.save_audio(full, folder / "Malayalam voice", sr=SR, fmt=req["format"])
    report(0.99, "Done")
    res = engine._result(folder, [("voice", out)])
    res["voice"] = {
        "seconds": round(len(full) / SR, 1), "warnings": warnings, "disclosure": DISCLOSURE,
        "lines": [{"index": i, "kind": ln["kind"], "text": ln.get("text"), "tone": ln.get("tone"),
                   "voice": ln.get("voice"), "speaker": ln.get("speaker"), "effect": ln.get("effect"),
                   "tone_sample": ln.get("tone_sample"), "seconds": ln.get("seconds")}
                  for i, ln in enumerate(lines)],
    }
    return res


def line_file(folder, index):
    """Path of one rendered line inside a result folder (index validated by the caller)."""
    p = Path(folder) / "lines" / f"{int(index):03d}.wav"
    return p if p.is_file() else None


def make_profile_job(params, report, client, upload_path):
    """The 'voice_profile' tool: validate a reference recording + transcript and encode it as a tone sample of a
    new or existing voice. The recording itself is deleted afterwards unless `keep_recording` is true."""
    tone = engine.choice(params, "tone", list(vt.TONES), "neutral")
    transcript = vp.clean_transcript(params.get("transcript"))
    audio = engine.load_audio(upload_path, sr=SR, mono=True)[0]
    report(0.1, "Checking the recording...")
    quality = vp.check_reference(audio, SR)
    if params.get("profile"):
        pid = _voice_id(params["profile"], "this sample")
        if pid in vp.BUILTIN:
            raise engine.UserError("Add samples to your own voices; built-in voices are fixed.")
        meta = vp.get(pid)
        if tone != "neutral" and "neutral" not in meta["tones"]:
            raise engine.UserError("Add the voice's normal (neutral) sample first.")
    else:
        if tone != "neutral":
            raise engine.UserError("A new voice starts with its normal (neutral) sample.")
        meta = vp.new_profile(params.get("name"), params.get("consent"))
    pid = meta["id"]
    ref = vp.VOICES / pid / "ref.wav"
    sf.write(ref, audio, SR, subtype="PCM_16")
    report(0.3, "Learning the voice...")
    try:
        client.call("make_profile", ref=str(ref), text=transcript, out=str(vp.tone_path(pid, tone)))
    except Exception:
        if not params.get("profile"):
            vp.delete(pid)                           # don't leave an empty voice behind
        raise
    finally:
        if not params.get("keep_recording"):
            ref.unlink(missing_ok=True)
    out = vp.record_tone(pid, tone, transcript, quality)
    report(0.99, "Done")
    return {"files": [], "profile": out, "quality": quality}


def disk_free_gb(path):
    try:
        return round(shutil.disk_usage(path).free / 2**30, 1)
    except OSError:
        return None


def status(client):
    """For the page header: is the engine installed, which device, licence notices."""
    return {
        "installed": client.installed, "running": client.alive,
        "voices_dir_free_gb": disk_free_gb(vp.VOICES.parent if vp.VOICES.parent.exists() else Path.home()),
        "language": "ml",
        "tones": vt.listing(),
        "licences": [
            "Voice model: OmniVoice by k2-fsa (code Apache-2.0; model weights CC-BY-NC 4.0: personal, non-commercial use).",
            "Built with Higgs Materials licensed from Boson AI USA, Inc., Copyright Boson AI USA, Inc., All Rights Reserved "
            "and Meta Llama 3 licensed under the Meta Llama 3 Community License, Copyright Meta Platforms, Inc., "
            "All Rights Reserved.",
        ],
        "disclosure": DISCLOSURE, "consent_text": vp.CONSENT_TEXT,
        "fake": os.environ.get("MIXLUMO_VOICE_FAKE") == "1",
    }
