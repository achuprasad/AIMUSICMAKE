# Copyright (c) 2026 Achu Prasad. All rights reserved. See LICENSE.
"""Tones for the Malayalam Voice Studio and how each one is produced.

OmniVoice has no emotion switch. A tone is produced in one of two ways, and the UI says which:
  1. exact:  the voice has its own sample recorded in that tone (an angry sample for angry lines, ...). OmniVoice
             copies the delivery of the sample, so the emotion is genuinely spoken.
  2. shaped: no sample for that tone. The neutral voice is generated at the tone's speed (a model parameter), then
             shaped afterwards: pitch, level, and per tone a little colour (growl, tremble, softness, warmth).
             This is an approximation of the emotion, not a performance of it.
Whisper is native for built-in voices (OmniVoice voice design has a whisper style), so built-ins get a real
whisper sample. Non-verbal sounds ([laughter], [sigh], [surprise-ah], ...) are OmniVoice features and are
handled in the script, not here.

Intensity 0-100 scales the shaping (60 = the recipes below; 100 = 1.67x; 0 = neutral).
"""
from typing import Any

import numpy as np

# key: label (English, Malayalam), speed factor (model), pitch (semitones), level (dB), extras
TONES: dict[str, dict[str, Any]] = {
    "neutral":   {"en": "Neutral",   "ml": "സാധാരണ",        "speed": 1.00, "pitch": 0.0,  "gain": 0.0},
    "happy":     {"en": "Happy",     "ml": "സന്തോഷം",       "speed": 1.06, "pitch": 1.0,  "gain": 1.0, "bright": 0.3},
    "excited":   {"en": "Excited",   "ml": "ആവേശം",         "speed": 1.14, "pitch": 2.0,  "gain": 2.0, "bright": 0.5},
    "angry":     {"en": "Angry",     "ml": "ദേഷ്യം",          "speed": 1.08, "pitch": 0.5,  "gain": 3.0, "drive": 0.6},
    "sad":       {"en": "Sad",       "ml": "ദുഃഖം",           "speed": 0.88, "pitch": -1.0, "gain": -2.0, "dark": 0.4},
    "crying":    {"en": "Crying",    "ml": "കരച്ചിൽ",         "speed": 0.85, "pitch": -0.5, "gain": -3.0,
                  "tremolo": (5.5, 0.25), "dark": 0.3},
    "fearful":   {"en": "Fearful",   "ml": "ഭയം",            "speed": 1.05, "pitch": 1.5,  "gain": -1.0,
                  "tremolo": (7.0, 0.15)},
    "calm":      {"en": "Calm",      "ml": "ശാന്തം",           "speed": 0.92, "pitch": -0.5, "gain": -1.0, "dark": 0.2},
    "romantic":  {"en": "Romantic",  "ml": "പ്രണയം",          "speed": 0.90, "pitch": -0.5, "gain": -2.0, "dark": 0.5},
    "whisper":   {"en": "Whispering", "ml": "മന്ത്രിക്കൽ","speed": 0.95, "pitch": 0.0,  "gain": -8.0, "airy": 1.0},
    "sarcastic": {"en": "Sarcastic", "ml": "പരിഹാസം",        "speed": 0.94, "pitch": -0.5, "gain": 0.0},
    "confident": {"en": "Confident", "ml": "ആത്മവിശ്വാസം",   "speed": 1.00, "pitch": -0.5, "gain": 2.0},
    "surprised": {"en": "Surprised", "ml": "അത്ഭുതം",         "speed": 1.04, "pitch": 2.0,  "gain": 1.0, "bright": 0.3},
    "dramatic":  {"en": "Dramatic",  "ml": "നാടകീയം",        "speed": 0.85, "pitch": -0.5, "gain": 0.0, "pause": 0.4},
    "deadpan":   {"en": "Deadpan",   "ml": "നിർവികാരം",       "speed": 0.92, "pitch": -1.0, "gain": -1.0},
    "confused":  {"en": "Confused",  "ml": "ആശയക്കുഴപ്പം",    "speed": 0.90, "pitch": 0.5,  "gain": -1.0},
    "proud":     {"en": "Proud",     "ml": "അഭിമാനം",         "speed": 0.98, "pitch": -0.3, "gain": 2.0},
}
MAIN_TONES = ["neutral", "happy", "angry", "sad", "crying", "excited", "fearful", "calm", "romantic", "whisper",
              "sarcastic", "confident", "surprised"]          # the 13 presets; the rest come from story tags


def scale(intensity):
    """0..100 -> multiplier for the shaping (60 = 1.0)."""
    return max(0.0, min(100.0, float(intensity))) / 60.0


def speed_for(tone, intensity=60, exact=False):
    """The model's speed factor for a line in this tone (no change when the tone has its own sample)."""
    if exact:
        return 1.0
    return 1.0 + (TONES.get(tone, TONES["neutral"])["speed"] - 1.0) * scale(intensity)


def shape(w, sr, tone, intensity=60, exact=False, pitch_shift=None):
    """Post-shaping of one generated line (mono float). `pitch_shift(w, semitones)` comes from the audio engine
    (phase-locked, keeps length). Exact-tone lines are left as spoken."""
    t = TONES.get(tone, TONES["neutral"])
    k = 0.0 if exact else scale(intensity)
    y = np.asarray(w, np.float32)
    if k == 0.0 or y.size == 0:
        return y
    if t["pitch"] and pitch_shift is not None:
        y = np.asarray(pitch_shift(y, t["pitch"] * k), np.float32)
    if t.get("drive"):
        d = 1.0 + 2.0 * t["drive"] * k
        y = np.tanh(d * y) / np.tanh(d)
    if t.get("tremolo"):
        rate, depth = t["tremolo"]
        n = np.arange(len(y)) / sr
        y = y * (1.0 - min(0.9, depth * k) * (0.5 + 0.5 * np.sin(2 * np.pi * rate * n)))
    for key, btype, cutoff in (("dark", "lowpass", 5000.0), ("bright", "highpass", 180.0), ("airy", "highpass", 350.0)):
        if t.get(key):
            from scipy.signal import butter, sosfilt
            amt = min(1.0, t[key] * k)
            filt = sosfilt(butter(2, cutoff, btype=btype, fs=sr, output="sos"), y)
            y = ((1 - amt) * y + amt * filt).astype(np.float32)
    gain = 10 ** (t["gain"] * k / 20)
    y = y * gain
    peak = float(np.abs(y).max())
    return (y * (0.98 / peak) if peak > 0.98 else y).astype(np.float32)


def extra_pause(tone, intensity=60):
    return TONES.get(tone, {}).get("pause", 0.0) * scale(intensity)


def listing():
    """For the UI: the tone list with labels, main presets first."""
    keys = MAIN_TONES + [k for k in TONES if k not in MAIN_TONES]
    return [{"key": k, "en": TONES[k]["en"], "ml": TONES[k]["ml"], "main": k in MAIN_TONES} for k in keys]
