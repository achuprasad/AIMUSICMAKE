"""Malayalam Voice Studio: profiles, validation, tones, planning and rendering. Rendering uses the real worker
process with its test-only stand-in synthesiser (no model, no GPU); the real model is checked by
scripts/voice_real_check.py."""
import json
import sys

import numpy as np
import pytest
import soundfile as sf

import engine
import voice_profiles as vp
import voice_studio as vs
import voice_tones as vt
from voice_engine import VoiceEngine

SR = 24000
ML = "ഇന്ന് നല്ല കാലാവസ്ഥയാണ്, നമുക്ക് പുറത്ത് നടക്കാൻ പോകാം."


def speechlike(seconds=5.0, level=0.2, sr=SR):
    t = np.arange(int(seconds * sr)) / sr
    return (level * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t))).astype(np.float32)


@pytest.fixture
def voices(tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "VOICES", tmp_path / "voices")
    return tmp_path / "voices"


@pytest.fixture
def client(voices):
    e = VoiceEngine(python=sys.executable, timeout=60)
    yield e
    e.stop()


def rec():
    seen = []
    return seen, lambda f, s: seen.append((f, s))


# ------------------------------------------------------------------ validation
class TestValidation:
    def test_transcript(self):
        assert vp.clean_transcript("  " + ML + "  \n") == ML
        for bad, msg in ((None, "exact words"), ("", "exact words"), ("Hello, how are you?", "Malayalam"),
                         ("അ" * 401, "too long")):
            with pytest.raises(vp.ProfileError, match=msg):
                vp.clean_transcript(bad)

    def test_name(self):
        assert vp.clean_name("  Achu\x00‎'s   voice ") == "Achu's voice"
        assert len(vp.clean_name("x" * 100)) == 40
        with pytest.raises(vp.ProfileError):
            vp.clean_name("\x01\x02")

    def test_good_reference(self):
        r = vp.check_reference(speechlike(5.0), SR)
        assert 4.5 <= r["seconds"] <= 5.1 and r["warnings"] == [] and r["clipped"] == 0

    @pytest.mark.parametrize("audio, msg", [
        (speechlike(1.0), "Only 1.0 s"),
        (speechlike(20.0), "too long"),
        (speechlike(5.0, level=0.003), "too quiet"),
        (np.clip(speechlike(5.0, level=3.0), -1, 1), "distorted"),
        (np.zeros(0, np.float32), "empty"),
        (np.full(SR * 5, np.nan, np.float32), "empty"),
    ])
    def test_bad_reference(self, audio, msg):
        with pytest.raises(vp.ProfileError, match=msg):
            vp.check_reference(audio, SR)

    def test_reference_warnings(self):
        silence = np.zeros(SR * 6, np.float32)
        r = vp.check_reference(np.concatenate([speechlike(2.5), silence]), SR)
        assert any("3-10 seconds" in w for w in r["warnings"]) and any("silence" in w for w in r["warnings"])


# ------------------------------------------------------------------ profiles
class TestProfiles:
    def test_consent_is_required(self, voices):
        for c in (None, False, "yes", 1):
            with pytest.raises(vp.ProfileError, match="permission"):
                vp.new_profile("Me", c)
        assert not voices.exists() or not any(voices.iterdir())

    def test_create_rename_list_delete(self, voices):
        m = vp.new_profile("Achu", True)
        assert vp.ID_RE.match(m["id"]) and m["consent"]["statement"] == vp.CONSENT_TEXT
        assert vp.rename(m["id"], "Achu (studio)")["name"] == "Achu (studio)"
        ids = [p["id"] for p in vp.list_profiles()]
        assert m["id"] in ids and set(vp.BUILTIN) <= set(ids)
        assert "consent" not in next(p for p in vp.list_profiles() if p["id"] == m["id"])   # no internals exposed
        (voices / m["id"] / "tones" / "neutral.pt").write_bytes(b"voiceprint")
        assert vp.delete(m["id"]) and not (voices / m["id"]).exists()
        with pytest.raises(vp.ProfileError, match="not found"):
            vp.get(m["id"])

    @pytest.mark.parametrize("bad", ["../../etc", "..", "builtin-../x", "ABCDEF123456", "a" * 12 + "/..", "", None, 5])
    def test_ids_are_validated(self, voices, bad):
        with pytest.raises(vp.ProfileError):
            vp.get(bad)
        with pytest.raises(vp.ProfileError):
            vp.delete(bad)

    def test_unknown_tone_path(self, voices):
        m = vp.new_profile("A", True)
        with pytest.raises(vp.ProfileError, match="Unknown tone"):
            vp.tone_path(m["id"], "../../x")

    def test_builtins_cannot_be_renamed(self, voices):
        vp.ensure_builtin_record("builtin-male-adult")
        with pytest.raises(vp.ProfileError):
            vp.rename("builtin-male-adult", "x")

    def test_best_tone(self):
        meta = {"name": "A", "tones": {"neutral": {}, "angry": {}}}
        assert vp.best_tone(meta, "angry") == ("angry", True)
        assert vp.best_tone(meta, "sad") == ("neutral", False)
        with pytest.raises(vp.ProfileError, match="no samples"):
            vp.best_tone({"name": "A", "tones": {}}, "sad")

    def test_neutral_is_removed_last(self, voices):
        m = vp.new_profile("A", True)
        for t in ("neutral", "angry"):
            vp.tone_path(m["id"], t).write_bytes(b"x")
            vp.record_tone(m["id"], t, ML, {"seconds": 4})
        with pytest.raises(vp.ProfileError, match="neutral"):
            vp.remove_tone(m["id"], "neutral")
        assert "angry" not in vp.remove_tone(m["id"], "angry")["tones"]


# ------------------------------------------------------------------ tones
class TestTones:
    def test_thirteen_presets_first(self):
        keys = [t["key"] for t in vt.listing()]
        assert keys[:13] == vt.MAIN_TONES and len(set(keys)) == len(keys)
        assert all(vt.TONES[k]["ml"] for k in keys)

    def test_speed(self):
        assert vt.speed_for("excited") == pytest.approx(1.14)
        assert vt.speed_for("sad", intensity=0) == 1.0
        assert vt.speed_for("sad", exact=True) == 1.0
        assert vt.speed_for("sad", intensity=100) < vt.speed_for("sad", intensity=60) < 1.0

    def test_exact_lines_are_left_as_spoken(self):
        w = speechlike(1.0)
        assert np.array_equal(vt.shape(w, SR, "angry", exact=True), w)
        assert np.array_equal(vt.shape(w, SR, "angry", intensity=0), w)

    def test_shaping_changes_level_and_stays_safe(self):
        w = speechlike(2.0, level=0.2)
        rms = lambda y: float(np.sqrt(np.mean(np.square(y))))  # noqa: E731
        assert rms(vt.shape(w, SR, "whisper")) < rms(w) * 0.5
        loud = vt.shape(w, SR, "angry", intensity=100)
        assert rms(loud) > rms(w) and np.abs(loud).max() <= 0.98 + 1e-6
        for k in vt.TONES:
            y = vt.shape(w, SR, k, pitch_shift=lambda y, st: y)
            assert len(y) == len(w) and np.isfinite(y).all()


# ------------------------------------------------------------------ requests and plans
class TestPlan:
    def test_request_defaults(self):
        r = vs.read_request({"script": ML})
        assert r["voice"] == "builtin-female-adult" and r["tone"] == "neutral" and r["quality"] == "fast"

    @pytest.mark.parametrize("p, msg", [
        ({}, "Type some Malayalam"),
        ({"script": "   "}, "Type some Malayalam"),
        ({"script": "Hello world, this is English."}, "Malayalam only"),
        ({"script": "അ" * 20001}, "too long"),
        ({"script": ML, "voice": "../../x"}, "valid voice"),
        ({"script": ML, "cast": {"രാമേട്ടൻ": "nope"}}, "valid voice"),
        ({"script": ML, "cast": "x"}, "character voices"),
        ({"script": ML, "tone": "furious"}, "Invalid tone"),
        ({"script": ML, "intensity": 101}, "intensity"),
        ({"script": ML, "speed": "fast"}, "speed must be a number"),
        ({"script": ML, "format": "exe"}, "Invalid format"),
        ("not a dict", "Invalid request"),
    ])
    def test_bad_requests(self, p, msg):
        with pytest.raises(engine.UserError, match=msg):
            vs.read_request(p)

    def test_story_plan(self):
        story = ("[angrily] രാമേട്ടൻ: \"എന്താടാ ഇത്?\"\n[dramatic pause]\n[ giggles ]\n"
                 "കടയിലെ 10 രൂപയുടെ കടം.\n[dragon voice] \"ഗ്ര്ര്... ഭക്ഷണം!\"")
        req = vs.read_request({"script": story, "voice": "builtin-female-adult", "tone": "happy", "pause": 2.0,
                               "cast": {"രാമേട്ടൻ": "builtin-male-adult"}})
        lines, warnings = vs.build_plan(req)
        assert warnings == []
        ram, pause, laugh, num, dragon = lines
        assert ram["voice"] == "builtin-male-adult" and ram["tone"] == "angry"
        assert pause == {"kind": "pause", "seconds": 2.4}
        assert laugh["text"].startswith("[laughter] ") and laugh["voice"] == "builtin-female-adult"
        assert num["text"].startswith("കടയിലെ പത്ത് രൂപയുടെ") and num["tone"] == "happy"   # default tone for plain lines
        assert dragon["effect"] == "monster" and len({ln.get("seed") for ln in lines if "seed" in ln}) == 4

    def test_tags_only(self):
        with pytest.raises(engine.UserError, match="nothing to say"):
            vs.build_plan(vs.read_request({"script": "[dramatic pause]\n[ഹ]"}))


# ------------------------------------------------------------------ rendering (real worker, stand-in synthesiser)
STORY = "അവന്റെ പേര് തീപ്പൊരി!\n[whispers] പക്ഷേ ഇന്നും ഒരു രഹസ്യമുണ്ട്...\n[angrily] രാമേട്ടൻ: \"എന്താടാ ഇത്?\"\n[laughs]"


class TestRender:
    def test_render_story(self, client, voices):
        seen, report = rec()
        res = vs.render({"script": STORY, "voice": "builtin-female-adult", "format": "wav",
                         "cast": {"രാമേട്ടൻ": "builtin-male-adult"}}, report, client)
        out = res["files"][0]["path"]
        w, sr = sf.read(out)
        assert sr == SR and abs(len(w) / sr - res["voice"]["seconds"]) < 0.05
        lines = res["voice"]["lines"]
        assert [ln["kind"] for ln in lines] == ["speech"] * 4
        assert lines[1]["tone"] == "whisper" and lines[1]["tone_sample"] == "exact"     # built-ins have a real whisper
        assert lines[2]["tone"] == "angry" and lines[2]["tone_sample"] == "shaped"
        assert res["voice"]["disclosure"].startswith("AI-generated")
        for vid in ("builtin-female-adult", "builtin-male-adult"):                       # designed once, then frozen
            assert set(vp.get(vid)["tones"]) == {"neutral", "whisper"}
        assert not (voices / "builtin-female-adult" / "work").exists()
        fracs = [f for f, _ in seen]
        assert fracs == sorted(fracs) and any("Line 4 of 4" in s for _, s in seen)
        plan = json.loads((engine.Path(res["folder"]) / "plan.json").read_text(encoding="utf-8"))
        assert len(plan["lines"]) == 4 and not list(engine.Path(res["folder"]).glob("lines/*.raw.wav"))

    def test_regenerate_one_line(self, client, voices):
        res = vs.render({"script": STORY}, rec()[1], client)
        folder = engine.Path(res["folder"])
        before = {p.name: p.read_bytes() for p in (folder / "lines").glob("*.wav")}
        plan0 = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
        vs.render({"lines": [2]}, rec()[1], client, previous=str(folder))
        after = {p.name: p.read_bytes() for p in (folder / "lines").glob("*.wav")}
        plan1 = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
        assert [n for n in before if before[n] != after[n]] in ([], ["002.wav"])         # only line 2 may change
        assert plan1["lines"][2]["seed"] != plan0["lines"][2]["seed"]
        assert [ln["seed"] for i, ln in enumerate(plan1["lines"]) if i != 2] == \
               [ln["seed"] for i, ln in enumerate(plan0["lines"]) if i != 2]
        for bad in ([], [99], ["1"], None):
            with pytest.raises(engine.UserError):
                vs.render({"lines": bad}, rec()[1], client, previous=str(folder))

    def test_cancel(self, client, voices):
        with pytest.raises(Exception, match="Stopped"):
            vs.render({"script": STORY}, rec()[1], client, cancelled=lambda: True)

    def test_user_voice_with_tone_sample(self, client, voices, tmp_path):
        ref = tmp_path / "me.wav"
        sf.write(ref, speechlike(5.0), SR)
        with pytest.raises(vp.ProfileError, match="permission"):
            vs.make_profile_job({"name": "Me", "transcript": ML}, rec()[1], client, str(ref))
        r = vs.make_profile_job({"name": "Me", "transcript": ML, "consent": True}, rec()[1], client, str(ref))
        pid = r["profile"]["id"]
        assert r["profile"]["tones"]["neutral"]["transcript"] == ML and r["quality"]["warnings"] == []
        assert not (voices / pid / "ref.wav").exists()                     # the recording itself is not kept
        r2 = vs.make_profile_job({"profile": pid, "tone": "angry", "transcript": ML}, rec()[1], client, str(ref))
        assert set(r2["profile"]["tones"]) == {"neutral", "angry"}
        res = vs.render({"script": "[angrily] എന്താടാ ഇത്?\nശരി.", "voice": pid}, rec()[1], client)
        lines = res["voice"]["lines"]
        assert lines[0]["tone_sample"] == "exact" and lines[1]["tone_sample"] == "exact"

    def test_profile_job_rules(self, client, voices, tmp_path):
        ref = tmp_path / "me.wav"
        sf.write(ref, speechlike(5.0), SR)
        with pytest.raises(engine.UserError, match="neutral"):
            vs.make_profile_job({"name": "Me", "transcript": ML, "consent": True, "tone": "sad"}, rec()[1], client, str(ref))
        with pytest.raises(engine.UserError, match="built-in"):
            vs.make_profile_job({"profile": "builtin-child", "transcript": ML}, rec()[1], client, str(ref))
        short = tmp_path / "short.wav"
        sf.write(short, speechlike(1.0), SR)
        with pytest.raises(vp.ProfileError, match="Only"):
            vs.make_profile_job({"name": "Me", "transcript": ML, "consent": True}, rec()[1], client, str(short))
        assert all(p["builtin"] for p in vp.list_profiles())                     # nothing half-made left behind

    def test_a_line_that_fails_is_retried_then_left_silent(self, client, voices):
        res = vs.render({"script": "ശരി.\n__nosound__ ശരി.\nനന്ദി."}, rec()[1], client)
        v = res["voice"]
        assert any("Line 2 could not be spoken" in w for w in v["warnings"])
        assert [ln["kind"] for ln in v["lines"]] == ["speech"] * 3 and v["seconds"] > 0
        w, _ = sf.read(engine.Path(res["folder"]) / "lines" / "001.wav")
        assert np.abs(w).max() == 0                                          # left silent, story still complete

    def test_voice_without_samples(self, client, voices):
        m = vp.new_profile("Empty", True)
        with pytest.raises(engine.UserError, match="no samples"):
            vs.render({"script": ML, "voice": m["id"]}, rec()[1], client)

    def test_status(self, client):
        s = vs.status(client)
        assert s["installed"] and s["language"] == "ml" and len(s["tones"]) == len(vt.TONES)
        assert any("CC-BY-NC" in x for x in s["licences"]) and any("Boson AI" in x for x in s["licences"])
