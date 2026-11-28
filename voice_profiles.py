# Copyright (c) 2026 Achu Prasad. All rights reserved. See LICENSE.
"""Malayalam voice profiles: validation of reference recordings and transcripts, consent records, storage.

A profile is a folder VOICES/<id>/ with meta.json and one encoded voice prompt per tone (tones/<tone>.pt, made
by the voice worker). The original recording is not kept: it is deleted once encoded, unless the user asks to
keep it. Ids are random hex; every path is built from a validated id, never from user text.
"""
import json
import os
import re
import shutil
import time
import unicodedata
import uuid
from pathlib import Path

import numpy as np

VOICES = Path(os.environ.get("AUDIO_STUDIO_VOICES", Path.home() / ".audiostudio" / "voices"))
ID_RE = re.compile(r"^[0-9a-f]{12}$")
BUILTIN_RE = re.compile(r"^builtin-[a-z0-9-]{2,40}$")
CONSENT_TEXT = ("I confirm this is my own voice, or the speaker has given me explicit permission to clone it, "
                "and I will not use it to impersonate or deceive anyone.")
MIN_S, IDEAL_MIN_S, IDEAL_MAX_S, MAX_S = 2.0, 3.0, 10.0, 15.0

# Built-in voices: designed once from these attributes (OmniVoice voice design), then frozen as a profile so the
# same voice is used for every line. They are synthetic, not real people.
BUILTIN = {
    "builtin-female-young": {"name": "Female, young", "instruct": "female, young adult, moderate pitch"},
    "builtin-female-adult": {"name": "Female, adult", "instruct": "female, middle-aged, moderate pitch"},
    "builtin-female-elder": {"name": "Female, elderly", "instruct": "female, elderly, low pitch"},
    "builtin-male-young": {"name": "Male, young", "instruct": "male, young adult, moderate pitch"},
    "builtin-male-adult": {"name": "Male, adult (deep)", "instruct": "male, middle-aged, low pitch"},
    "builtin-male-elder": {"name": "Male, elderly", "instruct": "male, elderly, low pitch"},
    "builtin-child": {"name": "Child", "instruct": "child, high pitch"},
}
BUILTIN_SAMPLE_TEXT = "നമസ്കാരം, ഇന്ന് നമുക്ക് ഒരു രസകരമായ കഥ കേൾക്കാം."   # "Hello, let's listen to a fun story today."


class ProfileError(Exception):
    """A problem the user can fix; the message is shown as is."""


# ------------------------------------------------------------------ validation
def malayalam_ratio(text):
    letters = [c for c in text if unicodedata.category(c)[0] in "LM"]
    return sum("ഀ" <= c <= "ൿ" for c in letters) / len(letters) if letters else 0.0


def clean_transcript(text):
    """The exact Malayalam words spoken in the reference recording."""
    if not isinstance(text, str):
        raise ProfileError("Type the exact words spoken in the recording.")
    text = " ".join(unicodedata.normalize("NFC", text).split())
    if len(text) < 2:
        raise ProfileError("Type the exact words spoken in the recording.")
    if len(text) > 400:
        raise ProfileError("The transcript is too long: use a 3-10 second recording of one or two sentences.")
    if malayalam_ratio(text) < 0.6:
        raise ProfileError("The transcript must be in Malayalam script (this studio is Malayalam only).")
    return text


def clean_name(name):
    if not isinstance(name, str):
        raise ProfileError("Give the voice a name.")
    name = "".join(c for c in unicodedata.normalize("NFC", name) if unicodedata.category(c)[0] != "C")
    name = " ".join(name.split())[:40]
    if not name:
        raise ProfileError("Give the voice a name.")
    return name


def check_reference(audio, sr):
    """Quality checks for a reference recording (mono float array). Returns a report; raises ProfileError for
    recordings that can't work. `seconds` counts speech only (long silences removed)."""
    x = np.asarray(audio, np.float32).reshape(-1)
    if x.size == 0 or not np.isfinite(x).all():
        raise ProfileError("The recording is empty or damaged.")
    frame = max(1, int(sr * 0.02))
    n = len(x) // frame
    rms = np.sqrt((x[: n * frame].reshape(n, frame) ** 2).mean(1)) if n else np.array([0.0])
    voiced = rms > max(1e-4, rms.max() * 0.05)          # relative: quiet speech is found, then reported as quiet
    speech_s = round(float(voiced.sum()) * frame / sr, 2)
    speech = x[: n * frame][np.repeat(voiced, frame)]
    level = float(20 * np.log10(np.sqrt(np.mean(speech ** 2)) + 1e-9)) if speech.size else -120.0
    clipped = float((np.abs(x) >= 0.99).mean())
    warnings = []
    if speech_s < MIN_S:
        raise ProfileError(f"Only {speech_s:.1f} s of speech: record 3-10 seconds of one person speaking.")
    if speech_s > MAX_S:
        raise ProfileError(f"{speech_s:.0f} s of speech is too long: trim it to 3-10 seconds (one or two sentences).")
    if level < -45:
        raise ProfileError("The recording is too quiet. Move closer to the microphone and record again.")
    if clipped > 0.01:
        raise ProfileError("The recording is distorted (too loud). Lower the microphone volume and record again.")
    if speech_s < IDEAL_MIN_S or speech_s > IDEAL_MAX_S:
        warnings.append(f"{speech_s:.1f} s of speech; 3-10 seconds works best.")
    if level < -32:
        warnings.append("The recording is quite quiet; a louder, closer recording clones better.")
    if clipped > 0.001:
        warnings.append("A few loud peaks are distorted.")
    if len(x) / sr - speech_s > 4:
        warnings.append("There is a lot of silence; it is removed automatically.")
    return {"seconds": speech_s, "level_dbfs": round(level, 1), "clipped": round(clipped, 4), "warnings": warnings}


# ------------------------------------------------------------------ storage
def _dir(pid):
    if not isinstance(pid, str) or not (ID_RE.match(pid) or pid in BUILTIN):
        raise ProfileError("Voice not found.")
    return VOICES / pid


def tone_path(pid, tone):
    from voice_tones import TONES
    if tone not in TONES:
        raise ProfileError("Unknown tone.")
    return _dir(pid) / "tones" / f"{tone}.pt"


def _read(pid):
    p = _dir(pid) / "meta.json"
    if not p.is_file():
        raise ProfileError("Voice not found.")
    return json.loads(p.read_text(encoding="utf-8"))


def _write(pid, meta):
    d = _dir(pid)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "meta.json.tmp"
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, d / "meta.json")


def public(meta):
    """What the browser may see (no paths)."""
    return {k: meta.get(k) for k in ("id", "name", "builtin", "created", "tones", "consent_at")}


def list_profiles():
    out = []
    if VOICES.is_dir():
        for d in sorted(VOICES.iterdir()):
            if (ID_RE.match(d.name) or d.name in BUILTIN) and (d / "meta.json").is_file():
                try:
                    out.append(public(_read(d.name)))
                except (OSError, ValueError):
                    continue
    have = {p["id"] for p in out}
    for bid, b in BUILTIN.items():                       # built-ins that aren't made yet are listed too
        if bid not in have:
            out.append({"id": bid, "name": b["name"], "builtin": True, "created": None, "tones": {}, "ready": False})
    return out


def new_profile(name, consent):
    """Create the record for a user voice. The caller then makes tones/<tone>.pt with the voice worker."""
    if consent is not True:
        raise ProfileError("Please confirm you have the speaker's permission before cloning a voice.")
    pid = uuid.uuid4().hex[:12]
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    meta = {"id": pid, "name": clean_name(name), "builtin": False, "created": now, "tones": {},
            "consent": {"confirmed": True, "statement": CONSENT_TEXT}, "consent_at": now}
    _write(pid, meta)
    (_dir(pid) / "tones").mkdir(exist_ok=True)
    return meta


def ensure_builtin_record(bid):
    if bid not in BUILTIN:
        raise ProfileError("Voice not found.")
    try:
        return _read(bid)
    except ProfileError:
        meta = {"id": bid, "name": BUILTIN[bid]["name"], "builtin": True, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                "tones": {}, "instruct": BUILTIN[bid]["instruct"]}
        _write(bid, meta)
        (_dir(bid) / "tones").mkdir(exist_ok=True)
        return meta


def get(pid):
    return _read(pid)


def record_tone(pid, tone, transcript, report):
    """After the worker wrote tones/<tone>.pt: remember it (with what was said and how good the recording was)."""
    meta = _read(pid)
    if not tone_path(pid, tone).is_file():
        raise ProfileError("The voice sample could not be saved.")
    meta["tones"][tone] = {"transcript": transcript, "seconds": report.get("seconds"),
                           "added": time.strftime("%Y-%m-%d %H:%M:%S")}
    _write(pid, meta)
    return public(meta)


def remove_tone(pid, tone):
    meta = _read(pid)
    if tone == "neutral" and len(meta["tones"]) > 1:
        raise ProfileError("Remove the other tones first; the neutral sample is the voice itself.")
    tone_path(pid, tone).unlink(missing_ok=True)
    meta["tones"].pop(tone, None)
    _write(pid, meta)
    return public(meta)


def rename(pid, name):
    meta = _read(pid)
    if meta.get("builtin"):
        raise ProfileError("Built-in voices can't be renamed.")
    meta["name"] = clean_name(name)
    _write(pid, meta)
    return public(meta)


def delete(pid):
    """Remove the voice and everything stored for it (encoded samples, records)."""
    d = _dir(pid)
    if not d.is_dir():
        raise ProfileError("Voice not found.")
    for f in d.rglob("*"):                             # overwrite before deleting: these are voice prints
        if f.is_file():
            try:
                with open(f, "r+b") as fh:
                    fh.write(b"\0" * f.stat().st_size)
            except OSError:
                pass
    shutil.rmtree(d)
    return True


def best_tone(meta, tone):
    """The sample to use for a line in `tone`: that tone's own sample if recorded, else the neutral one.
    Returns (tone_used, exact) where exact says whether the tone has its own sample."""
    tones = meta.get("tones", {})
    if tone in tones:
        return tone, True
    if "neutral" in tones:
        return "neutral", False
    if tones:
        return next(iter(tones)), False
    raise ProfileError(f"The voice '{meta.get('name')}' has no samples yet.")
