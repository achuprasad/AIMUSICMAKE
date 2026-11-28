"""Unit tests for story_script.py (Malayalam story scripts with expression tags)."""
import pytest

import story_script as ss

STORY = """കേരളത്തിലെ മനോഹരമായ ഒരു കൊച്ചു ഗ്രാമമായ പുഞ്ചക്കരയിൽ, ഒരു ദിവസം രാവിലെ ആകാശത്തുനിന്ന് എന്തോ വലിയൊരു സാധനം താഴേക്ക് പറന്നുവന്നു.

[dramatically] അത് ഒരു ഹെലികോപ്റ്ററായിരുന്നില്ല... വിമാനവുമായിരുന്നില്ല...

[excited] ഒരു കൂറ്റൻ ഡ്രാഗൺ ആയിരുന്നു!

[dragon voice] "ഗ്ര്ര്ര്ര്... എനിക്ക് ഭക്ഷണം വേണം!"

[angrily] രാമേട്ടൻ: "എന്താടാ ഇത്? രാവിലെ തന്നെ ഗ്യാസ് സിലിണ്ടർ പൊട്ടിയ പോലെ ഒരു ശബ്ദം!"

[deadpan] രാമേട്ടൻ: "എടാ മോനേ... നീ ഇവിടെ വന്നത് ചായ കുടിക്കാനാണോ, അതോ എന്റെ കട കത്തിക്കാനാണോ?"

[ giggles ]

ഒരാൾ ചോദിച്ചു:

"ഇതിനെ പിടിക്കാൻ വനംവകുപ്പിനെ വിളിക്കണോ?"

[whispers] പക്ഷേ ഇന്നും ഒരു രഹസ്യമുണ്ട്...

രാമേട്ടന്റെ കടയിലെ 10 രൂപയുടെ കടം ചോദിക്കുന്ന ആ പഴയ കണക്കുപുസ്തകത്തെയാണ്!

[dramatic pause]

[bursts into laughter] 🤣
"""


def speech(steps):
    return [s for s in steps if s["kind"] == "speech"]


def test_story_is_parsed_into_steps():
    steps, warnings = ss.parse(STORY)
    assert warnings == []
    sp = speech(steps)
    assert sp[0]["speaker"] == "narrator" and sp[0]["emotion"] == "neutral" and sp[0]["effect"] is None
    assert sp[1]["emotion"] == "dramatic" and sp[1]["pause_after"] == 0.6          # ends with "..."
    assert sp[2]["emotion"] == "excited" and sp[2]["text"] == "ഒരു കൂറ്റൻ ഡ്രാഗൺ ആയിരുന്നു!"


def test_tags_and_emoji_are_never_spoken():
    steps, _ = ss.parse(STORY)
    for s in speech(steps):
        assert "[" not in s["text"] and "]" not in s["text"] and "🤣" not in s["text"]


def test_effect_and_quotes():
    sp = speech(ss.parse(STORY)[0])
    dragon = next(s for s in sp if s["effect"] == "monster")
    assert dragon["text"] == "ഗ്ര്ര്ര്ര്... എനിക്ക് ഭക്ഷണം വേണം!" and dragon["speaker"] == "voice"


def test_named_speaker_and_emotion():
    sp = speech(ss.parse(STORY)[0])
    ram = [s for s in sp if s["speaker"] == "രാമേട്ടൻ"]
    assert [s["emotion"] for s in ram] == ["angry", "deadpan"]
    assert ram[0]["text"].startswith("എന്താടാ ഇത്?") and not ram[0]["text"].startswith('"')


def test_a_narration_line_ending_with_colon_is_not_a_speaker():
    sp = speech(ss.parse(STORY)[0])
    asked = next(s for s in sp if s["text"].startswith("ഒരാൾ"))
    assert asked["speaker"] == "narrator" and asked["text"] == "ഒരാൾ ചോദിച്ചു:"
    nxt = sp[sp.index(asked) + 1]
    assert nxt["speaker"] == "voice" and nxt["text"] == "ഇതിനെ പിടിക്കാൻ വനംവകുപ്പിനെ വിളിക്കണോ?"


def test_events_on_their_own_line():
    steps, _ = ss.parse(STORY)
    kinds = [(s["kind"], s.get("style") or s.get("seconds")) for s in steps if s["kind"] != "speech"]
    assert kinds == [("laugh", "giggle"), ("pause", 1.2), ("laugh", "big")]


def test_whisper_is_an_emotion():
    sp = speech(ss.parse(STORY)[0])
    assert any(s["emotion"] == "whisper" for s in sp)


def test_unknown_tags_are_reported_not_spoken():
    steps, warnings = ss.parse("[sings loudly] നമസ്കാരം\n[???]\n")
    assert speech(steps)[0]["text"] == "നമസ്കാരം" and speech(steps)[0]["emotion"] == "neutral"
    assert any("sings loudly" in w for w in warnings) and any("???" in w for w in warnings)


def test_tag_case_spacing_and_underscores():
    steps, w = ss.parse("[ Dramatic_Pause ]\n[ANGRILY] എന്ത്?")
    assert w == [] and steps[0] == {"kind": "pause", "seconds": 1.2} and steps[1]["emotion"] == "angry"


def test_laugh_after_text_on_same_line():
    steps, _ = ss.parse("അത് കേട്ട് എല്ലാവരും ചിരിച്ചു [laughs]")
    assert steps[0]["kind"] == "speech" and steps[0]["text"] == "അത് കേട്ട് എല്ലാവരും ചിരിച്ചു"
    assert steps[1] == {"kind": "laugh", "style": "laugh"}


def test_model_sound_tags_stay_inside_the_line():
    steps, w = ss.parse("[sighs] ഇന്ന് വളരെ ക്ഷീണിച്ചു.\n[gasps] അയ്യോ!\n[sigh]\n[angrily] [hmm] എന്താ ഇത്?")
    sp = speech(steps)
    assert w == []
    assert sp[0]["text"] == "[sigh] ഇന്ന് വളരെ ക്ഷീണിച്ചു."
    assert sp[1]["text"] == "[surprise-ah] അയ്യോ!"
    assert sp[2]["text"] == "[sigh] ഹാ…"                             # a sound alone gets a word to perform
    assert sp[3]["text"] == "[dissatisfaction-hnn] എന്താ ഇത്?" and sp[3]["emotion"] == "angry"


def test_malayalam_joiners_are_kept_and_text_normalised():
    s = "ഇൻ‍ഡ്യ"                           # ZWJ inside a word must survive
    steps, _ = ss.parse(s)
    assert "‍" in steps[0]["text"]


def test_numbers_to_words():
    w = []
    assert ss.numbers_to_words("10 രൂപയുടെ കടം", w) == "പത്ത് രൂപയുടെ കടം" and w == []
    assert ss.numbers_to_words("250 രൂപ", w) == "250 രൂപ" and "250" in w[0]
    assert ss.numbers_to_words("7:30", []) == "ഏഴ്:30"        # only standalone known numbers are converted


def test_empty_and_bad_input():
    assert ss.parse("") == ([], [])
    assert ss.parse("\n\n  \n") == ([], [])
    with pytest.raises(ValueError):
        ss.parse(None)


def test_very_long_line_is_reported():
    _, w = ss.parse("അ" * 700)
    assert any("longer than" in x for x in w)
