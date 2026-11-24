"""Unit tests for the model wrappers using stand-in models (CPU, milliseconds).

Real inference is covered by tests/test_gpu.py. These tests cover the wrapper
logic around it, especially the error paths the GPU rarely hits: out-of-memory
fallback to CPU, sys.exit() from audio-separator, file naming, caching.
"""
import types

import numpy as np
import pytest
import soundfile as sf
import torch

import engine
from engine import UserError

SOURCES4 = ["drums", "bass", "other", "vocals"]


class FakeDemucs:
    def __init__(self, sources=SOURCES4, n_models=1):
        self.sources = sources
        self.models = [object()] * n_models
        self.devices = []

    def eval(self):
        return self

    def to(self, dev):
        self.devices.append(dev)
        return self


def make_apply(oom_on=()):
    """apply_model stand-in: splits the mix equally into sources and reports progress like Demucs."""
    calls = []

    def apply_model(model, mix, device, shifts, split, overlap, progress):
        calls.append({"device": device, "shifts": shifts, "overlap": overlap})
        if device in oom_on:
            raise torch.cuda.OutOfMemoryError("fake OOM")
        for _ in range(len(model.models) * max(1, shifts)):
            for _ in engine._HookedTqdm(range(4)):
                pass
        n = len(model.sources)
        return (mix / n).unsqueeze(1).repeat(1, n, 1, 1)
    apply_model.calls = calls
    return apply_model


@pytest.fixture
def demucs_env(monkeypatch):
    import demucs.apply
    import demucs.pretrained
    engine._demucs.clear()
    loaded = []

    def install(model=None, oom_on=()):
        m = model or FakeDemucs()
        fake = make_apply(oom_on)
        monkeypatch.setattr(demucs.apply, "apply_model", fake)
        monkeypatch.setattr(demucs.pretrained, "get_model", lambda name: loaded.append(name) or m)
        return m, fake, loaded
    yield install
    engine._demucs.clear()


class Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, f, s):
        self.calls.append((f, s))


# ------------------------------------------------------------------ Demucs wrapper
def test_demucs_four_stems(demucs_env, fixtures):
    model, fake, loaded = demucs_env()
    r = Rec()
    stems = engine._run_demucs(str(fixtures["tone_wav"]), 4, "fast", r)
    assert set(stems) == set(SOURCES4) and loaded == ["htdemucs"]
    mix = engine.load_audio(fixtures["tone_wav"])
    assert np.allclose(sum(stems.values()), mix, atol=1e-4), "stems must reconstruct the mix (denormalised)"
    fr = [f for f, _ in r.calls]
    assert fr == sorted(fr) and max(fr) <= 0.92 + 1e-9
    assert any(0.1 < f < 0.92 for f in fr)
    assert fake.calls[0]["shifts"] == engine.SPEED["fast"][1] and fake.calls[0]["overlap"] == engine.SPEED["fast"][2]


def test_demucs_six_stem_model_name(demucs_env, fixtures):
    _, _, loaded = demucs_env(FakeDemucs(SOURCES4 + ["guitar", "piano"]))
    stems = engine._run_demucs(str(fixtures["tone_wav"]), 6, "fast", Rec())
    assert loaded == ["htdemucs_6s"] and {"guitar", "piano"} <= set(stems)


def test_demucs_model_is_cached(demucs_env, fixtures):
    _, _, loaded = demucs_env()
    engine._run_demucs(str(fixtures["tone_wav"]), 4, "fast", Rec())
    engine._run_demucs(str(fixtures["tone_wav"]), 4, "fast", Rec())
    assert loaded == ["htdemucs"]


def test_demucs_progress_spans_all_passes(demucs_env, fixtures):
    """A bag of 2 models x 2 shifts = 4 passes must map onto one 10%..92% bar, not restart 4 times."""
    demucs_env(FakeDemucs(n_models=2))
    r = Rec()
    engine._run_demucs(str(fixtures["tone_wav"]), 4, "best", r)
    fr = [f for f, s in r.calls if s.startswith("Splitting")]
    assert fr == sorted(fr) and len(fr) == 2 * 2 * 4
    assert abs(fr[-1] - 0.92) < 1e-9 and fr[0] < 0.2


def test_demucs_gpu_out_of_memory_falls_back_to_cpu(demucs_env, fixtures, monkeypatch):
    monkeypatch.setattr(engine, "DEVICE", "cuda")
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)
    model, fake, _ = demucs_env(oom_on=("cuda",))
    r = Rec()
    stems = engine._run_demucs(str(fixtures["tone_wav"]), 4, "fast", r)
    assert [c["device"] for c in fake.calls] == ["cuda", "cpu"]
    assert any("(on CPU)" in s for _, s in r.calls)
    assert "cpu" in model.devices and set(stems) == set(SOURCES4)


def test_demucs_fails_cleanly_when_no_device_works(demucs_env, fixtures, monkeypatch):
    monkeypatch.setattr(engine, "DEVICE", "cuda")
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)
    demucs_env(oom_on=("cuda", "cpu"))
    with pytest.raises(UserError, match="could not run"):
        engine._run_demucs(str(fixtures["tone_wav"]), 4, "fast", Rec())


def test_separate_demucs_two_stem_sums_instrumental(demucs_env, fixtures):
    demucs_env()
    r = Rec()
    res = engine.separate({"file": str(fixtures["tone_wav"]), "engine": "demucs", "stems": 2, "format": "wav"}, r)
    keys = [f["key"] for f in res["files"]]
    assert keys == ["vocals", "instrumental"]
    v, _ = sf.read(res["files"][0]["path"])
    i, _ = sf.read(res["files"][1]["path"])
    assert np.allclose(i, 3 * v, atol=2e-4)  # 3 non-vocal stems of equal share
    assert any(s.startswith("Saving") for _, s in r.calls)
    assert [f for f, _ in r.calls] == sorted(f for f, _ in r.calls)


def test_separate_demucs_orders_stems(demucs_env, fixtures):
    demucs_env()
    res = engine.separate({"file": str(fixtures["tone_wav"]), "engine": "demucs", "stems": 4, "format": "flac"}, Rec())
    assert [f["key"] for f in res["files"]] == ["vocals", "drums", "bass", "other"]
    assert all(f["path"].endswith(".flac") for f in res["files"])


# ------------------------------------------------------------------ RoFormer wrapper
class FakeSeparator:
    instances = []
    fail_load = None
    fail_sep = None
    absolute = False

    def __init__(self, **kw):
        self.kw = kw
        self.model_instance = types.SimpleNamespace(overlap=None)
        FakeSeparator.instances.append(self)

    def load_model(self, model_filename):
        self.model_file = model_filename
        if FakeSeparator.fail_load:
            raise FakeSeparator.fail_load

    def separate(self, path):
        if FakeSeparator.fail_sep:
            raise FakeSeparator.fail_sep
        for _ in engine._HookedTqdm(range(5)):
            pass
        a = engine.load_audio(path)
        out = engine.Path(self.kw["output_dir"])
        names = []
        for label, gain in (("Vocals", 0.25), ("Instrumental", 0.75)):
            p = out / f"song_({label})_{self.model_file}.wav"
            sf.write(p, (a * gain).T, engine.SR)
            names.append(str(p) if FakeSeparator.absolute else p.name)
        return names


@pytest.fixture
def roformer_env(monkeypatch, tmp_path):
    import audio_separator.separator as asep
    monkeypatch.setattr(asep, "Separator", FakeSeparator)
    monkeypatch.setattr(engine, "MODEL_DIR", tmp_path / "models")
    FakeSeparator.instances, FakeSeparator.fail_load, FakeSeparator.fail_sep, FakeSeparator.absolute = [], None, None, False
    engine._seps.clear()
    yield FakeSeparator
    engine._seps.clear()


@pytest.mark.parametrize("absolute", [False, True])
def test_roformer_outputs_and_cleanup(roformer_env, fixtures, absolute):
    roformer_env.absolute = absolute
    r = Rec()
    stems = engine._roformer(str(fixtures["tone_wav"]), "bs_roformer", "balanced", r)
    assert set(stems) == {"vocals", "instrumental"}
    mix = engine.load_audio(fixtures["tone_wav"])
    assert np.allclose(stems["vocals"] + stems["instrumental"], mix, atol=1e-3)
    assert not list((engine.OUT / ".work").glob("*.wav")), "temporary model outputs must be deleted"
    assert roformer_env.instances[0].model_file == engine.ROFORMER["bs_roformer"][1]
    assert roformer_env.instances[0].model_instance.overlap == engine.SPEED["balanced"][0]
    fr = [f for f, _ in r.calls]
    assert fr == sorted(fr) and len([f for f in fr if 0.1 < f <= 0.92]) >= 3


def test_roformer_first_run_says_downloading(roformer_env, fixtures):
    r = Rec()
    engine._roformer(str(fixtures["tone_wav"]), "mel_roformer", "fast", r)
    assert r.calls[0][1].startswith("Downloading Mel-Band RoFormer")


def test_roformer_existing_model_says_loading(roformer_env, fixtures):
    engine.MODEL_DIR.mkdir(parents=True)
    (engine.MODEL_DIR / engine.ROFORMER["bs_roformer"][1]).write_bytes(b"x")
    r = Rec()
    engine._roformer(str(fixtures["tone_wav"]), "bs_roformer", "fast", r)
    assert r.calls[0][1] == "Loading BS-RoFormer model..."


def test_roformer_is_cached_and_speed_changes_without_reload(roformer_env, fixtures):
    engine._roformer(str(fixtures["tone_wav"]), "bs_roformer", "fast", Rec())
    engine._roformer(str(fixtures["tone_wav"]), "bs_roformer", "best", Rec())
    assert len(roformer_env.instances) == 1
    assert roformer_env.instances[0].model_instance.overlap == engine.SPEED["best"][0]


def test_switching_models_unloads_the_previous_one(roformer_env, fixtures):
    engine._roformer(str(fixtures["tone_wav"]), "bs_roformer", "fast", Rec())
    engine._roformer(str(fixtures["tone_wav"]), "mel_roformer", "fast", Rec())
    assert list(engine._seps) == ["mel_roformer"]


@pytest.mark.parametrize("exc", [SystemExit(1), RuntimeError("corrupt checkpoint")])
def test_roformer_load_failure_becomes_user_error(roformer_env, fixtures, exc):
    roformer_env.fail_load = exc
    with pytest.raises(UserError, match="Could not load the BS-RoFormer model"):
        engine._roformer(str(fixtures["tone_wav"]), "bs_roformer", "fast", Rec())
    assert not engine._seps


@pytest.mark.parametrize("exc", [SystemExit(1), torch.cuda.OutOfMemoryError("fake")])
def test_roformer_separation_failure_becomes_user_error(roformer_env, fixtures, exc):
    engine._roformer(str(fixtures["tone_wav"]), "bs_roformer", "fast", Rec())
    roformer_env.fail_sep = exc
    with pytest.raises(UserError, match="Separation failed"):
        engine._roformer(str(fixtures["tone_wav"]), "bs_roformer", "fast", Rec())
    assert not engine._seps, "a failed model must be unloaded so the next job starts clean"
    assert engine._Progress.report is None, "progress hook must be released after a failure"


def test_separate_roformer_end_to_end(roformer_env, fixtures):
    res = engine.separate({"file": str(fixtures["tone_wav"]), "format": "mp3"}, Rec())
    assert [f["key"] for f in res["files"]] == ["vocals", "instrumental"]
    assert roformer_env.instances[0].model_instance.overlap == engine.SPEED["fast"][0]  # default speed


# ------------------------------------------------------------------ misc
def test_gpu_name_cpu(monkeypatch):
    monkeypatch.setattr(engine, "DEVICE", "cpu")
    assert engine.gpu_name() == "CPU"


def test_gpu_name_from_nvidia_smi(monkeypatch):
    monkeypatch.setattr(engine, "DEVICE", "cuda")
    monkeypatch.setattr(engine.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout="GeForce Test\n"))
    assert engine.gpu_name() == "GeForce Test"


def test_gpu_name_when_nvidia_smi_missing(monkeypatch):
    monkeypatch.setattr(engine, "DEVICE", "cuda")

    def boom(*a, **k):
        raise FileNotFoundError("nvidia-smi")
    monkeypatch.setattr(engine.subprocess, "run", boom)
    assert engine.gpu_name() == "NVIDIA GPU"


def test_models_loaded_reports_state():
    engine._seps.clear()
    engine._demucs.clear()
    try:
        assert engine.models_loaded() is False
        engine._demucs["cpu_model"] = torch.nn.Linear(2, 2)  # parameters on CPU
        assert engine.models_loaded() is False
        engine._demucs["fake"] = FakeDemucs()  # no parameters(): ignored safely
        assert engine.models_loaded() is False
        engine._seps["bs_roformer"] = object()
        assert engine.models_loaded() is True
    finally:
        engine._seps.clear()
        engine._demucs.clear()


def test_free_gpu_moves_demucs_to_cpu():
    m = FakeDemucs()
    engine._demucs["x"] = m
    engine._seps["y"] = object()
    try:
        engine.free_gpu()
        assert m.devices == ["cpu"] and not engine._seps
    finally:
        engine._demucs.clear()
