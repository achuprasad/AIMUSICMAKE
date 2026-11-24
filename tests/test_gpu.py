"""GPU worker tests: real AI-model inference on the local GPU.

Skipped automatically when there is no CUDA GPU or another process is using it.
"""
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import torch

import engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
import metrics as M  # noqa: E402

pytestmark = [pytest.mark.gpu, pytest.mark.slow]
TRACKS = M.musdb_tracks(n=2)
needs_data = pytest.mark.skipif(not TRACKS, reason="MUSDB18 test data not downloaded")


@pytest.fixture(scope="module")
def songs(tmp_root):
    out = []
    for tr in TRACKS:
        ref = M.load_track(tr)
        p = tmp_root / (tr.name.replace(".stem.mp4", "") + ".wav")
        sf.write(p, ref["mixture"].T, M.SR)
        out.append((p, ref))
    return out


@pytest.fixture(autouse=True)
def release_gpu():
    yield
    engine.free_gpu()


def separate(path, **opts):
    prog = []
    torch.cuda.reset_peak_memory_stats()
    res = engine.separate({"file": str(path), "format": "wav", **opts}, lambda f, s: prog.append((f, s)))
    return res, prog, torch.cuda.max_memory_allocated() / 2 ** 20


def stems(res):
    return {f["key"]: sf.read(f["path"], always_2d=True)[0].T for f in res["files"]}


@needs_data
@pytest.mark.parametrize("opts", [
    {"engine": "bs_roformer", "speed": "fast"},
    {"engine": "mel_roformer", "speed": "fast"},
    {"engine": "demucs", "stems": 2, "speed": "fast"},
])
def test_two_stem_engines(songs, opts):
    path, ref = songs[0]
    res, _, gpu_mb = separate(path, **opts)
    out = stems(res)
    assert set(out) == {"vocals", "instrumental"}
    n = ref["mixture"].shape[1]
    for k, x in out.items():
        assert x.shape == (2, n), f"{k}: shape {x.shape} != (2, {n})"
        assert sf.info(next(f["path"] for f in res["files"] if f["key"] == k)).samplerate == 44100
        assert M.clipped_samples(x) == 0
    # stems should add back up to the mixture (energy-preserving separation)
    assert M.sdr(ref["mixture"], out["vocals"] + out["instrumental"]) > 15
    assert M.sdr(ref["vocals"], out["vocals"]) > 4
    assert gpu_mb < 3800


@needs_data
@pytest.mark.parametrize("n", [4, 6])
def test_demucs_multistem(songs, n):
    path, ref = songs[0]
    res, _, _ = separate(path, engine="demucs", stems=n, speed="fast")
    out = stems(res)
    expect = {"vocals", "drums", "bass", "other"} | ({"guitar", "piano"} if n == 6 else set())
    assert set(out) == expect
    assert M.sdr(ref["drums"], out["drums"]) > 3


@needs_data
@pytest.mark.parametrize("opts", [{"engine": "bs_roformer", "speed": "balanced"},
                                  {"engine": "demucs", "stems": 4, "speed": "best"}])
def test_progress_is_real(songs, opts):
    """The core UX promise: a live percentage, not a spinner."""
    path, _ = songs[1]
    _, prog, _ = separate(path, **opts)
    fracs = [f for f, _ in prog]
    work = [f for f in fracs if 0.10 <= f <= 0.92]
    assert fracs == sorted(fracs), "progress went backwards"
    assert len(set(work)) >= 3, f"too few progress steps during inference: {work}"
    assert max(work) >= 0.9, "inference progress never reached the end of its range"
    assert any("Saving" in s for _, s in prog)


@needs_data
def test_gpu_memory_is_released_between_engines(songs):
    path, _ = songs[0]
    separate(path, engine="bs_roformer", speed="fast")
    engine.free_gpu()
    assert torch.cuda.memory_allocated() / 2 ** 20 < 50
    # switching to a second big model must not run out of memory (regression)
    separate(path, engine="mel_roformer", speed="fast")
    separate(path, engine="demucs", stems=4, speed="fast")
    engine.free_gpu()
    assert torch.cuda.memory_allocated() / 2 ** 20 < 50


@needs_data
def test_speed_setting_changes_overlap(songs):
    path, _ = songs[0]
    separate(path, engine="bs_roformer", speed="fast")
    assert engine._seps["bs_roformer"].model_instance.overlap == engine.SPEED["fast"][0]
    separate(path, engine="bs_roformer", speed="best")
    assert engine._seps["bs_roformer"].model_instance.overlap == engine.SPEED["best"][0]


def _gpu_pids_and_used():
    import subprocess
    pids = subprocess.run(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
                          capture_output=True, text=True, check=False).stdout.split()
    used = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                          capture_output=True, text=True, check=False).stdout.split()[0]
    return {int(p) for p in pids if p.isdigit()}, int(used)


@needs_data
def test_worker_process_returns_all_gpu_memory(songs):
    """Regression: an in-process model left ~700 MB of CUDA context behind after 'release'."""
    import time

    from gpu_worker import GpuWorker
    path, _ = songs[0]
    engine.free_gpu()
    w = GpuWorker()
    try:
        w.run("separate", {"file": str(path), "engine": "bs_roformer", "speed": "fast", "format": "wav"},
              lambda f, s: None, user_error=engine.UserError)
        pids, used_busy = _gpu_pids_and_used()
        assert w.proc.pid in pids, "separation should run on the GPU inside the worker"
        pid = w.proc.pid
    finally:
        w.stop()
    time.sleep(2)
    pids, used_after = _gpu_pids_and_used()
    assert pid not in pids, "the worker must be gone from the GPU after stop()"
    assert used_busy - used_after > 500, f"GPU memory not returned: {used_busy} -> {used_after} MiB"


def test_silence_in_silence_out(tmp_path):
    p = engine.save_audio(np.zeros((2, engine.SR * 3), np.float32), tmp_path / "silence", fmt="wav")
    res, _, _ = separate(p, engine="demucs", stems=2, speed="fast")
    for x in stems(res).values():
        assert np.abs(x).max() < 1e-3


def test_pure_tone_is_not_distorted(tmp_path):
    t = np.arange(engine.SR * 4) / engine.SR
    p = engine.save_audio(np.stack([0.3 * np.sin(2 * np.pi * 440 * t)] * 2).astype(np.float32), tmp_path / "t", fmt="wav")
    res, _, _ = separate(p, engine="bs_roformer", speed="fast")
    out = stems(res)
    total = out["vocals"] + out["instrumental"]
    assert M.thd_percent(total[0, engine.SR:], 440) < 1.0
