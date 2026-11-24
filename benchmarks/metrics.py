"""Objective audio-quality metrics for source separation.

SDR follows the MDX-challenge definition (global, no BSS-eval distortion filter):
    SDR = 10 log10( sum(s^2) / sum((s - s_hat)^2) )
Leakage projects an estimate onto the true target and the true interferer
(least squares) and reports how loud the interferer is relative to the target.
"""
import subprocess
from pathlib import Path

import numpy as np

SR = 44100
EPS = 1e-10
STREAMS = {"mixture": 0, "drums": 1, "bass": 2, "other": 3, "vocals": 4}


def load_stem(path, stream, sr=SR):
    """Decode one audio stream of a MUSDB .stem.mp4 to float32 (2, n)."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-map", f"0:a:{stream}", "-f", "f32le",
           "-acodec", "pcm_f32le", "-ac", "2", "-ar", str(sr), "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).T.copy()


def load_track(path):
    t = {k: load_stem(path, i) for k, i in STREAMS.items()}
    n = min(v.shape[1] for v in t.values())
    t = {k: v[:, :n] for k, v in t.items()}
    t["accompaniment"] = t["drums"] + t["bass"] + t["other"]
    return t


def align(ref, est):
    n = min(ref.shape[-1], est.shape[-1])
    return ref[..., :n].astype(np.float64), est[..., :n].astype(np.float64)


def sdr(ref, est):
    ref, est = align(ref, est)
    return float(10 * np.log10((np.sum(ref ** 2) + EPS) / (np.sum((ref - est) ** 2) + EPS)))


def has_energy(x, thresh_db=-50):
    return 10 * np.log10(np.mean(np.asarray(x, np.float64) ** 2) + EPS) > thresh_db


def leakage_db(est, target, interferer):
    """Interferer level inside `est`, relative to the target level inside it (dB, lower is better)."""
    est, target = align(target, est)[1], align(target, est)[0]
    interferer = interferer[..., : est.shape[-1]].astype(np.float64)
    A = np.stack([target.ravel(), interferer.ravel()], axis=1)
    (a, b), *_ = np.linalg.lstsq(A, est.ravel(), rcond=None)
    t_energy = np.sum((a * target) ** 2)
    i_energy = np.sum((b * interferer) ** 2)
    return float(10 * np.log10((i_energy + EPS) / (t_energy + EPS)))


def clipped_samples(x, level=0.999):
    return int(np.sum(np.abs(x) >= level))


def thd_percent(x, f0, sr=SR):
    """Total harmonic distortion of a pure tone (first 5 harmonics)."""
    x = np.asarray(x, np.float64)
    x = x[: sr] * np.hanning(min(len(x), sr))
    spec = np.abs(np.fft.rfft(x))
    freqs = np.fft.rfftfreq(len(x), 1 / sr)

    def peak(f):
        i = np.argmin(np.abs(freqs - f))
        return spec[max(0, i - 3): i + 4].max()
    fund = peak(f0)
    harm = np.sqrt(sum(peak(f0 * k) ** 2 for k in range(2, 6) if f0 * k < sr / 2))
    return float(100 * harm / (fund + EPS))


def musdb_tracks(root=None, n=None):
    root = Path(root or Path.home() / ".audiostudio" / "testdata" / "musdb7" / "test")
    tracks = sorted(root.glob("*.stem.mp4"))
    return tracks[:n] if n else tracks
