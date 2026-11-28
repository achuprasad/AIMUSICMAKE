"""voice_engine.py <-> voice_worker.py: the real worker process and pipe protocol, with the worker's test-only
stand-in synthesiser (MIXLUMO_VOICE_FAKE=1), so no model or GPU is needed. The real model is covered by
scripts/voice_real_check.py (run on a PC with the voice environment)."""
import os
import sys

import pytest
import soundfile as sf

import voice_engine as ve

ML = "എന്താടാ ഇത്? രാവിലെ തന്നെ ഗ്യാസ് സിലിണ്ടർ പൊട്ടിയ പോലെ ഒരു ശബ്ദം! ഇൻ‍ഡ്യ"


@pytest.fixture
def eng(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXLUMO_VOICE_FAKE", "1")
    monkeypatch.setenv("AUDIO_STUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(ve, "HOME", tmp_path / "home")
    e = ve.VoiceEngine(python=sys.executable, timeout=60)
    yield e
    e.stop()


def test_malayalam_survives_the_pipe_unchanged(eng):
    """Regression: the worker runs with python -I, which ignored PYTHONIOENCODING, so Malayalam arrived garbled."""
    assert eng.call("echo", text=ML)["text"] == ML


def test_ping_reports_fake_mode(eng):
    r = eng.call("ping")
    assert r["ok"] and r["info"]["fake"] is True and r["loaded"] is False


def test_profile_and_generation(eng, tmp_path):
    ref = tmp_path / "ref.wav"
    sf.write(ref, [0.0] * 24000, 24000)
    prof = str(tmp_path / "v.pt")
    assert eng.call("make_profile", ref=str(ref), text="നമസ്കാരം", out=prof)["ok"]
    assert os.path.isfile(prof)
    events = []
    items = [{"text": ML, "out": str(tmp_path / "a.wav"), "profile": prof},
             {"text": "ശരി", "out": str(tmp_path / "b.wav"), "speed": 1.5}]
    r = eng.call("generate", items=items, on_event=events.append)
    assert [e["index"] for e in events] == [0, 1] and all(e["total"] == 2 for e in events)
    for it in r["items"]:
        w, sr = sf.read(it["out"])
        assert sr == 24000 and len(w) / sr == pytest.approx(it["audio_s"], abs=0.01) and abs(w).max() > 0.05
    assert not list(tmp_path.glob("*.tmp.wav"))                      # written atomically


@pytest.mark.parametrize("args, msg", [
    ({"ref": "missing.wav", "text": "x"}, "not found"),
    ({"ref": __file__, "text": "  "}, "exact words"),
])
def test_profile_errors_are_user_messages(eng, tmp_path, args, msg):
    with pytest.raises(ve.VoiceEngineError, match=msg):
        eng.call("make_profile", out=str(tmp_path / "v.pt"), **args)


def test_empty_line_is_a_user_error(eng, tmp_path):
    with pytest.raises(ve.VoiceEngineError, match="Line 1 is empty"):
        eng.call("generate", items=[{"text": " ", "out": str(tmp_path / "x.wav")}])


def test_crash_mid_job_is_reported_and_next_call_recovers(eng, tmp_path):
    with pytest.raises(ve.VoiceEngineError, match="stopped unexpectedly"):
        eng.call("generate", items=[{"text": "__crash__", "out": str(tmp_path / "x.wav")}])
    assert eng.call("ping")["ok"]                                   # the next call starts a fresh worker


def test_worker_that_died_while_idle_is_restarted_silently(eng):
    eng.call("ping")
    eng.proc.kill()
    eng.proc.wait(10)
    assert eng.call("ping")["ok"]


def test_stop_ends_the_process(eng):
    eng.call("ping")
    proc = eng.proc
    assert eng.stop() is True and proc.poll() is not None and not eng.alive
    assert eng.stop() is False


def test_not_installed_message(tmp_path):
    e = ve.VoiceEngine(python=tmp_path / "nope" / "python.exe")
    assert not e.installed
    with pytest.raises(ve.VoiceEngineError, match="not installed"):
        e.call("ping")


def test_unknown_command(eng):
    with pytest.raises(ve.VoiceEngineError, match="unknown command"):
        eng.call("dance")
