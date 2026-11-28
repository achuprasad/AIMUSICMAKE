# Copyright (c) 2026 Achu Prasad. All rights reserved. See LICENSE.
"""Malayalam story scripts with inline expression tags -> a list of performance steps.

Input is plain text like:

    കേരളത്തിലെ ... ഗ്രാമമായ പുഞ്ചക്കരയിൽ, ...           (narration)
    [excited] ഒരു കൂറ്റൻ ഡ്രാഗൺ ആയിരുന്നു!               (narration with an emotion)
    [angrily] രാമേട്ടൻ: "എന്താടാ ഇത്? ..."               (a named character speaking)
    [dragon voice] "ഗ്ര്ര്ര്ര്... എനിക്ക് ഭക്ഷണം വേണം!"  (a voice effect)
    [dramatic pause]                                      (an event on its own line)
    [ giggles ]                                           (a non-verbal sound)

Each step is one of:
    {"kind": "speech", "text", "speaker", "emotion", "effect", "pause_after"}
    {"kind": "pause", "seconds"}
    {"kind": "laugh", "style"}

Tags are never spoken. Unknown tags are reported in `warnings` and ignored. Emojis are removed. This module
is model-independent: a TTS adapter turns `emotion` into whatever its model understands (a description for
Indic Parler-TTS, an inline tag for Maya), and `effect` is applied afterwards with the existing audio engine.
"""
import re
import unicodedata

# tag (lowercase, spaces collapsed) -> (category, value)
EMOTIONS = {
    "neutral": "neutral", "calm": "calm", "happy": "happy", "happily": "happy", "excited": "excited",
    "excitedly": "excited", "angry": "angry", "angrily": "angry", "sad": "sad", "sadly": "sad", "crying": "crying",
    "fearful": "fearful", "scared": "fearful", "afraid": "fearful", "surprised": "surprised", "shocked": "surprised",
    "confused": "confused", "proudly": "proud", "proud": "proud", "confident": "confident", "deadpan": "deadpan",
    "sarcastic": "sarcastic", "sarcastically": "sarcastic", "romantic": "romantic", "dramatically": "dramatic",
    "dramatic": "dramatic", "whispers": "whisper", "whispering": "whisper", "whisper": "whisper",
}
EFFECTS = {"dragon voice": "monster", "monster voice": "monster", "robot voice": "robot", "echo": "echo",
           "radio voice": "radio", "phone voice": "radio"}
PAUSES = {"dramatic pause": 1.2, "pause": 0.7, "long pause": 1.5, "short pause": 0.35, "beat": 0.5}
LAUGHS = {"giggles": "giggle", "giggle": "giggle", "laughs": "laugh", "laughing": "laugh", "laugh": "laugh",
          "bursts into laughter": "big", "chuckles": "giggle"}
# Non-verbal sounds the voice model performs itself (OmniVoice tags). They stay inside the line's text, in order.
SOUNDS = {"sigh": "[sigh]", "sighs": "[sigh]", "laughter": "[laughter]", "gasp": "[surprise-ah]", "gasps": "[surprise-ah]",
          "surprise": "[surprise-oh]", "wow": "[surprise-wa]", "hmm": "[dissatisfaction-hnn]", "huh": "[question-ah]"}
SOUND_WORDS = {"[sigh]": "ഹാ…", "[laughter]": "ഹ ഹ ഹ!", "[surprise-ah]": "ആ!", "[surprise-oh]": "ഓ!", "[surprise-wa]": "വാ!",
               "[dissatisfaction-hnn]": "ഹ്മ്മ്…", "[question-ah]": "ആ?"}

TAG_RE = re.compile(r"\[\s*([^\[\]]{1,40}?)\s*\]")
# a speaker label at the start of a line: up to 3 words, then ':' or ':-', not containing quotes or sentence marks
SPEAKER_RE = re.compile(r"^\s*([^\s\"“”:?!.,][^\"“”:?!.]{0,40}?)\s*:\s*-?\s*(?=[\"“]|\S)")
QUOTE_RE = re.compile(r"^[\"“](.*)[\"”]$", re.S)
MAX_LINE_CHARS = 600


def strip_emoji(s):
    """Remove emoji and other pictographic symbols; keep Malayalam (incl. ZWJ/ZWNJ) and punctuation."""
    out = []
    for ch in s:
        if ch in ("‌", "‍"):            # zero-width (non-)joiner are part of Malayalam spelling
            out.append(ch)
            continue
        cat = unicodedata.category(ch)
        if cat == "So" or ch in ("️", "︎") or 0x1F000 <= ord(ch) <= 0x1FAFF:
            continue
        out.append(ch)
    return "".join(out)


def _norm_tag(t):
    return " ".join(t.lower().replace("_", " ").split())


def parse(script, narrator="narrator"):
    """Returns (steps, warnings). Speech steps carry the speaker label as written (e.g. 'രാമേട്ടൻ') or
    `narrator`; quoted lines without a label get speaker 'voice' (an unnamed character)."""
    if not isinstance(script, str):
        raise ValueError("script must be text")
    steps, warnings = [], []
    text = unicodedata.normalize("NFC", script.replace("\r\n", "\n"))
    for lineno, raw in enumerate(text.split("\n"), 1):
        line = strip_emoji(raw).strip()
        if not line:
            continue
        emotion, effect, events, sounds = None, None, [], []
        for m in TAG_RE.finditer(line):
            tag = _norm_tag(m.group(1))
            if tag in EMOTIONS:
                emotion = EMOTIONS[tag]
            elif tag in EFFECTS:
                effect = EFFECTS[tag]
            elif tag in PAUSES:
                events.append({"kind": "pause", "seconds": PAUSES[tag]})
            elif tag in LAUGHS:
                events.append({"kind": "laugh", "style": LAUGHS[tag]})
            elif tag in SOUNDS:
                sounds.append(SOUNDS[tag])
            else:
                warnings.append(f"line {lineno}: unknown tag [{m.group(1).strip()}] ignored")
        body = " ".join(TAG_RE.sub(" ", line).split())
        if not body and sounds:            # e.g. "[sighs]" on its own line: the voice performs just the sound,
            body = " ".join(f"{t} {SOUND_WORDS.get(t, 'ഹാ…')}" for t in sounds)   # with a word (a bare tag says nothing)
            sounds = []
        if not body:                       # a line that is only tags: pauses / laughs
            steps.extend(events)
            if not events and (emotion or effect):
                warnings.append(f"line {lineno}: tag without text ignored")
            continue
        if len(body) > MAX_LINE_CHARS:
            warnings.append(f"line {lineno}: longer than {MAX_LINE_CHARS} characters; split it for best results")
        speaker = narrator
        sm = SPEAKER_RE.match(body)
        if sm and len(sm.group(1).split()) <= 3 and body[sm.end():].strip():
            speaker, body = sm.group(1).strip(), body[sm.end():].strip()
        q = QUOTE_RE.match(body)
        if q:
            body = q.group(1).strip()
            if speaker == narrator:
                speaker = "voice"
        if sounds:
            body = " ".join(sounds) + " " + body
        pause_after = 0.6 if body.endswith(("...", "…")) else 0.35
        steps.append({"kind": "speech", "text": body, "speaker": speaker, "emotion": emotion or "neutral",
                      "effect": effect, "pause_after": pause_after, "line": lineno})
        steps.extend(events)                # tags like "[giggles]" written after the text on the same line
    return steps, warnings


# Malayalam number words for small numbers, so digits are not skipped or read letter by letter.
_ML_NUM = {0: "പൂജ്യം", 1: "ഒന്ന്", 2: "രണ്ട്", 3: "മൂന്ന്", 4: "നാല്", 5: "അഞ്ച്", 6: "ആറ്", 7: "ഏഴ്",
           8: "എട്ട്", 9: "ഒമ്പത്", 10: "പത്ത്", 20: "ഇരുപത്", 50: "അമ്പത്", 100: "നൂറ്"}


def numbers_to_words(text, warnings=None):
    """Replace standalone digits that have a known Malayalam word; others are left as they are and reported."""
    def rep(m):
        n = int(m.group(0))
        if n in _ML_NUM:
            return _ML_NUM[n]
        if warnings is not None:
            warnings.append(f"number {n} left as digits: write it in words for reliable speech")
        return m.group(0)
    return re.sub(r"(?<![\d.])\d+(?![\d.])", rep, text)
