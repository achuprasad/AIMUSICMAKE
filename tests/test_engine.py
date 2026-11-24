"""Unit tests for engine.py (CPU only, no AI models)."""
import numpy as np
import pytest
import soundfile as sf

import engine
from engine import UserError

SR = engine.SR


class Rec:
    """Records progress callbacks."""
    def __init__(self):
        self.calls = []

    def __call__(self, frac, stage):
        self.calls.append((frac, stage))

    @property
    def fracs(self):
        return [c[0] for c in self.calls]


def info(path):
    i = sf.info(str(path)) if str(path).endswith((".wav", ".flac", ".ogg")) else None
    a = engine.load_audio(path)
    return a, i


def dominant_freq(x, sr=SR):
    x = x[: sr * 2] * np.hanning(min(len(x), sr * 2))
    spec = np.abs(np.fft.rfft(x))
    return np.fft.rfftfreq(len(x), 1 / sr)[spec.argmax()]


# ------------------------------------------------------------------ I/O
class TestLoadAudio:
    def test_stereo_wav(self, fixtures):
        a = engine.load_audio(fixtures["tone_wav"])
        assert a.dtype == np.float32 and a.shape[0] == 2
        assert abs(a.shape[1] / SR - 5.0) < 0.01

    def test_mp3_decodes_with_correct_duration(self, fixtures):
        a = engine.load_audio(fixtures["tone_mp3"])
        assert abs(a.shape[1] / SR - 5.0) < 0.06

    def test_mono_22k_is_resampled_and_upmixed(self, fixtures):
        a = engine.load_audio(fixtures["mono_flac"])
        assert a.shape[0] == 2 and abs(a.shape[1] / SR - 3.0) < 0.01
        assert np.allclose(a[0], a[1])
        assert abs(dominant_freq(a[0]) - 440) < 2

    def test_audio_track_from_video(self, fixtures):
        a = engine.load_audio(fixtures["video_mp4"])
        assert abs(a.shape[1] / SR - 3.0) < 0.1
        assert abs(dominant_freq(a[0]) - 330) < 2

    def test_mono_flag(self, fixtures):
        assert engine.load_audio(fixtures["tone_wav"], sr=8000, mono=True).shape[0] == 1

    @pytest.mark.parametrize("key", ["spoofed_mp3", "png_as_wav", "empty"])
    def test_invalid_files_raise_user_error(self, fixtures, key):
        with pytest.raises(UserError):
            engine.load_audio(fixtures[key])

    def test_missing_file(self, tmp_path):
        with pytest.raises(UserError):
            engine.load_audio(tmp_path / "nope.wav")


class TestSaveAudio:
    @pytest.mark.parametrize("fmt", engine.FORMATS)
    def test_every_format_roundtrips(self, tmp_path, fmt):
        t = np.arange(SR * 2) / SR
        x = np.stack([0.5 * np.sin(2 * np.pi * 440 * t)] * 2).astype(np.float32)
        p = engine.save_audio(x, tmp_path / "out", fmt=fmt)
        assert p.suffix == "." + fmt and p.exists() and p.stat().st_size > 1000
        assert not list(tmp_path.glob("*.tmp.wav")), "temporary file left behind"
        back = engine.load_audio(p)
        assert back.shape[0] == 2
        assert abs(back.shape[1] / SR - 2.0) < 0.06  # lossy codecs add a few ms of padding
        assert abs(dominant_freq(back[0]) - 440) < 2

    @pytest.mark.parametrize("fmt", ["wav", "mp3"])
    def test_dots_in_names_are_kept(self, tmp_path, fmt):
        """Regression: 'song (1.25x speed)' was saved as 'song (1.mp3' (with_suffix ate the name)."""
        p = engine.save_audio(np.zeros((2, SR), np.float32), tmp_path / "song (1.25x speed, +2.5 st)", fmt=fmt)
        assert p.name == f"song (1.25x speed, +2.5 st).{fmt}" and p.exists()

    def test_wav_is_44k_stereo(self, tmp_path):
        p = engine.save_audio(np.zeros((2, SR), np.float32), tmp_path / "x", fmt="wav")
        i = sf.info(str(p))
        assert (i.samplerate, i.channels) == (44100, 2)

    def test_clipping_is_prevented(self, tmp_path):
        x = np.full((2, SR), 3.0, np.float32)
        p = engine.save_audio(x, tmp_path / "loud", fmt="wav")
        y, _ = sf.read(str(p))
        assert np.abs(y).max() <= 1.0

    def test_mono_array_is_accepted(self, tmp_path):
        p = engine.save_audio(np.zeros(SR, np.float32), tmp_path / "m", fmt="flac")
        assert sf.info(str(p)).channels == 1


def test_peaks(fixtures):
    pk = engine.peaks(fixtures["tone_wav"], n=300)
    assert len(pk) == 300 and max(pk) == 1.0 and min(pk) >= 0


def test_peaks_short_file(tmp_path):
    p = engine.save_audio(np.ones((2, 100), np.float32) * 0.5, tmp_path / "s", fmt="wav")
    assert 0 < len(engine.peaks(p, n=600)) <= 600


def test_duration(fixtures):
    assert abs(engine.duration(fixtures["tone_wav"]) - 5) < 0.01
    assert abs(engine.duration(fixtures["video_mp4"]) - 3) < 0.1


def test_job_dir_sanitises_names(tmp_root):
    d, name = engine.job_dir("C:/x/../we<i>rd:na*me?.mp3", "cut")
    assert d.parent == engine.OUT and d.exists()
    assert not set('<>:*?"|') & set(name)


# ------------------------------------------------------------------ validation
class TestValidation:
    def test_choice_default_and_valid(self):
        assert engine.choice({}, "format", engine.FORMATS, "wav") == "wav"
        assert engine.choice({"format": "mp3"}, "format", engine.FORMATS, "wav") == "mp3"

    @pytest.mark.parametrize("bad", ["../../evil", "exe", "", None, "WAV"])
    def test_choice_rejects(self, bad):
        with pytest.raises(UserError):
            engine.choice({"format": bad}, "format", engine.FORMATS, "wav")

    @pytest.mark.parametrize("v,ok", [(0, True), ("5", True), (-1, False), (11, False), ("x", False),
                                      (None, False), (float("nan"), False)])
    def test_number(self, v, ok):
        if ok:
            assert engine.number({"n": v}, "n", 0, 10, 0) == float(v)
        else:
            with pytest.raises(UserError):
                engine.number({"n": v}, "n", 0, 10, 0)


# ------------------------------------------------------------------ tools
class TestCut:
    def test_duration_and_fades(self, fixtures):
        r = Rec()
        res = engine.cut({"file": str(fixtures["tone_wav"]), "start": 1, "end": 3.5, "fade_in": 0.5,
                          "fade_out": 0.5, "format": "wav"}, r)
        p = res["files"][0]["path"]
        y, sr = sf.read(p)
        assert sr == SR and y.shape[1] == 2
        assert abs(len(y) / SR - 2.5) < 0.001
        level = np.abs(engine.load_audio(fixtures["tone_wav"])).max()  # ffmpeg tones are ~0.088 after upmix
        mid = np.abs(y[len(y) // 2 - 500: len(y) // 2 + 500]).max()
        assert abs(mid - level) < 0.01 * level + 1e-3  # untouched in the middle
        assert np.abs(y[:50]).max() < 0.02 * level and np.abs(y[-50:]).max() < 0.02 * level  # faded to ~0
        assert r.fracs == sorted(r.fracs)

    def test_end_zero_means_to_the_end(self, fixtures):
        res = engine.cut({"file": str(fixtures["tone_wav"]), "start": 4, "end": 0, "format": "wav"}, Rec())
        assert abs(sf.info(res["files"][0]["path"]).duration - 1.0) < 0.001

    def test_end_past_length_is_clamped(self, fixtures):
        res = engine.cut({"file": str(fixtures["tone_wav"]), "start": 0, "end": 999, "format": "wav"}, Rec())
        assert abs(sf.info(res["files"][0]["path"]).duration - 5.0) < 0.001

    def test_start_after_end_fails(self, fixtures):
        with pytest.raises(UserError, match="Start must be before end"):
            engine.cut({"file": str(fixtures["tone_wav"]), "start": 4, "end": 2}, Rec())

    def test_bad_format_fails(self, fixtures):
        with pytest.raises(UserError):
            engine.cut({"file": str(fixtures["tone_wav"]), "format": "../x"}, Rec())


class TestJoin:
    def test_plain_concatenation(self, fixtures):
        res = engine.join({"files": [str(fixtures["tone_wav"])] * 2, "format": "wav"}, Rec())
        assert abs(sf.info(res["files"][0]["path"]).duration - 10.0) < 0.001

    def test_crossfade_shortens_by_overlap(self, fixtures):
        res = engine.join({"files": [str(fixtures["tone_wav"])] * 3, "crossfade": 1, "format": "wav"}, Rec())
        assert abs(sf.info(res["files"][0]["path"]).duration - 13.0) < 0.001

    def test_mixed_formats(self, fixtures):
        res = engine.join({"files": [str(fixtures["tone_mp3"]), str(fixtures["mono_flac"]),
                                     str(fixtures["video_mp4"])], "format": "flac"}, Rec())
        assert abs(sf.info(res["files"][0]["path"]).duration - 11.0) < 0.15

    def test_needs_two_files(self, fixtures):
        with pytest.raises(UserError):
            engine.join({"files": [str(fixtures["tone_wav"])]}, Rec())


class TestPitchTempo:
    def test_octave_up_doubles_frequency(self, fixtures):
        res = engine.pitch_tempo({"file": str(fixtures["tone_wav"]), "semitones": 12, "format": "wav"}, Rec())
        y, _ = sf.read(res["files"][0]["path"])
        assert abs(dominant_freq(y[:, 0]) - 880) < 5
        assert abs(len(y) / SR - 5.0) < 0.01  # duration unchanged

    def test_double_tempo_halves_duration_keeps_pitch(self, fixtures):
        res = engine.pitch_tempo({"file": str(fixtures["tone_wav"]), "tempo": 200, "format": "wav"}, Rec())
        y, _ = sf.read(res["files"][0]["path"])
        assert abs(len(y) / SR - 2.5) < 0.02
        assert abs(dominant_freq(y[:, 0]) - 440) < 5

    def test_tape_mode_speed_also_moves_pitch(self, fixtures):
        res = engine.pitch_tempo({"file": str(fixtures["tone_wav"]), "tempo": 200, "keep_pitch": False,
                                  "format": "wav"}, Rec())
        y, _ = sf.read(res["files"][0]["path"])
        assert abs(len(y) / SR - 2.5) < 0.01
        assert abs(dominant_freq(y[:, 0]) - 880) < 5  # an octave up, like a tape at double speed
        assert "tape" in res["files"][0]["path"]

    def test_tape_mode_slow_down(self, fixtures):
        res = engine.pitch_tempo({"file": str(fixtures["tone_wav"]), "tempo": 75, "keep_pitch": False,
                                  "format": "wav"}, Rec())
        y, _ = sf.read(res["files"][0]["path"])
        assert abs(len(y) / SR - 5 / 0.75) < 0.01
        assert abs(dominant_freq(y[:, 0]) - 330) < 3

    def test_keep_pitch_must_be_boolean(self, fixtures):
        with pytest.raises(UserError):
            engine.pitch_tempo({"file": str(fixtures["tone_wav"]), "keep_pitch": "maybe"}, Rec())

    def test_no_change_is_identity_length(self, fixtures):
        res = engine.pitch_tempo({"file": str(fixtures["tone_wav"]), "format": "wav"}, Rec())
        assert abs(sf.info(res["files"][0]["path"]).duration - 5.0) < 0.001

    @pytest.mark.parametrize("params", [{"tempo": 0}, {"tempo": 1000}, {"semitones": 99}])
    def test_out_of_range(self, fixtures, params):
        with pytest.raises(UserError):
            engine.pitch_tempo({"file": str(fixtures["tone_wav"]), **params}, Rec())


def centroid(x, sr=SR):
    """Spectral centroid in Hz: lower = darker / more muffled."""
    spec = np.abs(np.fft.rfft(np.asarray(x, np.float64)))
    f = np.fft.rfftfreq(len(x), 1 / sr)
    return float((spec * f).sum() / spec.sum())


class TestEffects:
    @pytest.fixture
    def bright(self):
        rng = np.random.default_rng(1)
        return (rng.standard_normal((2, SR * 2)) * 0.2).astype(np.float32)  # white noise: full spectrum

    def test_lofi_darkens_and_keeps_level_and_length(self, bright):
        out = engine.lofi(bright, 80)
        assert out.shape == bright.shape
        assert centroid(out[0]) < 0.45 * centroid(bright[0])          # clearly muffled
        assert np.abs(out).max() <= 1.0
        assert abs(np.abs(out).max() - np.abs(bright).max()) < 0.05    # level kept

    def test_lofi_strength_scales(self, bright):
        assert centroid(engine.lofi(bright, 90)[0]) < centroid(engine.lofi(bright, 30)[0])

    def test_lofi_is_deterministic_and_zero_is_off(self, bright):
        assert np.array_equal(engine.lofi(bright, 60), engine.lofi(bright, 60))
        assert engine.lofi(bright, 0) is bright

    def test_lofi_reduces_bit_depth(self):
        t = np.arange(SR) / SR
        x = np.stack([0.5 * np.sin(2 * np.pi * 220 * t)] * 2).astype(np.float32)
        out = engine.lofi(x, 100)
        # full lo-fi bit-crushes to 9 bits: at most 2*2^9+1 distinct sample values (16-bit audio has ~65,000)
        assert len(np.unique(out[0])) <= 2 * 2 ** 9 + 1
        assert len(np.unique(engine.lofi(x, 20)[0])) > 2 * 2 ** 9 + 1  # light lo-fi keeps finer resolution

    def test_echo_repeats_at_the_right_time_and_level(self):
        x = np.zeros((2, SR), np.float32)
        x[:, 100] = 0.5                                                # one click
        out = engine.echo(x, delay_ms=250, feedback=50, mix=60)
        d = int(0.25 * SR)
        assert out.shape[1] > x.shape[1]                               # tail added for the echoes to ring out
        for k, expected in [(1, 0.5 * 0.6), (2, 0.5 * 0.6 * 0.5), (3, 0.5 * 0.6 * 0.25)]:
            assert abs(out[0, 100 + k * d] - expected) < 1e-6
        assert out[0, 100] == pytest.approx(0.5)                       # original untouched

    def test_echo_single_repeat_without_feedback(self):
        x = np.zeros((1, SR), np.float32)
        x[0, 0] = 0.5
        out = engine.echo(x, delay_ms=100, feedback=0, mix=50)
        d = int(0.1 * SR)
        assert out.shape[1] == SR + d and out[0, d] == pytest.approx(0.25) and np.count_nonzero(out) == 2

    def test_echo_mix_zero_is_off_and_never_clips(self, bright):
        assert engine.echo(bright, 300, 50, 0) is bright
        loud = np.full((2, SR), 0.9, np.float32)
        assert np.abs(engine.echo(loud, 100, 80, 100)).max() <= 0.98 + 1e-6

    def test_echo_tail_is_capped(self):
        x = np.zeros((1, SR), np.float32)
        out = engine.echo(x + 0.1, delay_ms=1500, feedback=85, mix=100)
        assert out.shape[1] <= SR + int(8.0 * SR) + 1

    def test_pitch_tool_with_lofi_and_echo(self, fixtures):
        res = engine.pitch_tempo({"file": str(fixtures["tone_wav"]), "lofi": 60, "echo_delay": 200, "echo_feedback": 30,
                                  "echo_mix": 40, "format": "wav"}, Rec())
        f = res["files"][0]["path"]
        assert "lofi 60" in f and "echo 200ms" in f
        y, sr = sf.read(f)
        assert sr == SR and y.shape[1] == 2 and len(y) / SR > 5.0       # echo tail added
        assert np.abs(y).max() <= 1.0

    def test_effects_only_without_speed_or_pitch_change(self, fixtures):
        res = engine.pitch_tempo({"file": str(fixtures["tone_wav"]), "lofi": 40, "format": "wav"}, Rec())
        assert abs(sf.info(res["files"][0]["path"]).duration - 5.0) < 0.001  # lo-fi alone keeps the length

    @pytest.mark.parametrize("params", [{"lofi": 101}, {"lofi": -1}, {"echo_delay": 10, "echo_mix": 50},
                                        {"echo_delay": 2000, "echo_mix": 50}, {"echo_feedback": 95, "echo_mix": 50},
                                        {"echo_mix": 150}, {"lofi": "lots"}])
    def test_effect_values_are_validated(self, fixtures, params):
        with pytest.raises(UserError):
            engine.pitch_tempo({"file": str(fixtures["tone_wav"]), **params}, Rec())


class TestAnalyze:
    def test_key_of_a_major_triad(self, fixtures):
        a = engine.analyze({"file": str(fixtures["a_major"])}, Rec())["analysis"]
        assert a["key"] == "A major" and a["camelot"] == "11B"
        assert abs(a["duration"] - 12) < 0.1

    def test_bpm_of_120_click_track(self, fixtures):
        a = engine.analyze({"file": str(fixtures["click_120"])}, Rec())["analysis"]
        # beat trackers may lock onto half/double time; any of those is acceptable
        assert any(abs(a[k] - 120) <= 2 for k in ("bpm", "half", "double")), a

    def test_percussion_reports_no_key_without_nan(self, fixtures):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            a = engine.analyze({"file": str(fixtures["click_120"])}, Rec())["analysis"]
        assert a["key"] in ("No clear key",) or a["confidence"] < 60, a

    def test_camelot_table_is_complete(self):
        for mode in ("major", "minor"):
            codes = engine.CAMELOT[mode]
            assert len(set(codes)) == 12


class TestConvert:
    @pytest.mark.parametrize("fmt", ["flac", "mp3", "m4a"])
    def test_convert(self, fixtures, fmt):
        res = engine.convert({"file": str(fixtures["video_mp4"]), "format": fmt}, Rec())
        p = res["files"][0]["path"]
        assert p.endswith("." + fmt)
        assert abs(engine.duration(p) - 3.0) < 0.15


class TestMix:
    @pytest.fixture
    def stems(self, tmp_root):
        d = engine.OUT / "mixstems"
        d.mkdir(parents=True, exist_ok=True)
        t = np.arange(SR) / SR
        a = engine.save_audio(np.stack([0.3 * np.sin(2 * np.pi * 220 * t)] * 2).astype(np.float32), d / "a", fmt="wav")
        b = engine.save_audio(np.stack([0.3 * np.sin(2 * np.pi * 660 * t)] * 2).astype(np.float32), d / "b", fmt="wav")
        return {"vocals": str(a), "drums": str(b)}

    def test_volumes_are_applied(self, stems):
        res = engine.mix({"files": stems, "volumes": {"vocals": 100, "drums": 0}, "format": "wav"}, Rec())
        y, _ = sf.read(res["files"][0]["path"])
        assert abs(dominant_freq(y[:, 0]) - 220) < 3
        assert abs(np.abs(y).max() - 0.3) < 0.02

    def test_all_muted(self, stems):
        with pytest.raises(UserError, match="muted"):
            engine.mix({"files": stems, "volumes": {"vocals": 0, "drums": 0}}, Rec())

    def test_path_outside_output_is_rejected(self, stems, fixtures):
        bad = dict(stems, vocals=str(fixtures["tone_wav"]))
        with pytest.raises(UserError, match="Invalid stem"):
            engine.mix({"files": bad, "volumes": {"vocals": 100, "drums": 100}}, Rec())

    def test_traversal_path_is_rejected(self, stems):
        bad = {"vocals": str(engine.OUT / ".." / ".." / "Windows" / "win.ini")}
        with pytest.raises(UserError):
            engine.mix({"files": bad, "volumes": {"vocals": 100}}, Rec())

    def test_bad_input_shapes(self):
        for p in ({}, {"files": [], "volumes": {}}, {"files": "x", "volumes": {}}):
            with pytest.raises(UserError):
                engine.mix(p, Rec())


def test_separate_rejects_bad_options(fixtures):
    for p in ({"engine": "evil"}, {"speed": "ludicrous"}, {"format": "exe"},
              {"engine": "demucs", "stems": 5}):
        with pytest.raises(UserError):
            engine.separate({"file": str(fixtures["tone_wav"]), **p}, Rec())


def test_progress_hook_maps_tqdm_to_range():
    seen = []
    engine._Progress.begin(lambda f, s: seen.append(f), 0.1, 0.9, 2, "x")
    try:
        for _ in engine._HookedTqdm(range(4)):
            pass
        for _ in engine._HookedTqdm(range(4)):
            pass
    finally:
        engine._Progress.end()
    assert seen == sorted(seen)
    assert abs(seen[0] - (0.1 + 0.8 * 0.125)) < 1e-9  # 1/4 of pass 1 of 2
    assert abs(seen[-1] - 0.9) < 1e-9
    assert len(seen) == 8


def test_progress_hook_silent_when_inactive():
    for _ in engine._HookedTqdm(range(3)):
        pass  # no callback registered: must not fail


def test_hooks_are_installed():
    import demucs.apply
    from audio_separator.separator.architectures import mdxc_separator
    assert demucs.apply.tqdm.tqdm is engine._HookedTqdm
    assert mdxc_separator.tqdm is engine._HookedTqdm
