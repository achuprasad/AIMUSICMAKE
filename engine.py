"""Audio processing engine for Local Audio Studio.

Every tool takes (params, report) where report(fraction 0..1, stage text)
is called as work progresses, and returns a result dict.
"""
import gc
import io
import logging
import os
import re
import subprocess
import time
import types
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
import torch
import tqdm as _tqdm

HOME = Path.home() / ".audiostudio"
MODEL_DIR = Path(os.environ.get("AUDIO_STUDIO_MODELS", HOME / "models"))  # the desktop app points this at its bundled models
OUT = Path(os.environ.get("AUDIO_STUDIO_OUT", Path.home() / "Music" / "Local Audio Studio"))
OUT.mkdir(parents=True, exist_ok=True)
SR = 44100
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def gpu_name():
    """GPU name via nvidia-smi, so asking does not reserve GPU memory (a CUDA context costs ~300 MB)."""
    if DEVICE != "cuda":
        return "CPU"
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True,
                             check=False, text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.stdout.strip().splitlines()[0] or "NVIDIA GPU"
    except Exception:
        return "NVIDIA GPU"


GPU_NAME = gpu_name()
FORMATS = ["wav", "mp3", "flac", "ogg", "m4a"]

ROFORMER = {
    "bs_roformer": ("BS-RoFormer", "model_bs_roformer_ep_317_sdr_12.9755.ckpt"),
    "mel_roformer": ("Mel-Band RoFormer", "model_mel_band_roformer_ep_3005_sdr_11.4360.ckpt"),
}
# speed mode -> RoFormer overlap, Demucs (shifts, overlap)
SPEED = {"fast": (2, 0, 0.1), "balanced": (4, 1, 0.25), "best": (8, 2, 0.25)}


class UserError(Exception):
    """An error whose message is shown to the user as-is."""


def choice(p, key, allowed, default):
    v = p.get(key, default)
    if v not in allowed:
        raise UserError(f"Invalid {key}: {v!r}. Allowed: {', '.join(map(str, allowed))}.")
    return v


def number(p, key, lo, hi, default):
    try:
        v = float(p.get(key, default))
    except (TypeError, ValueError):
        raise UserError(f"{key} must be a number.") from None
    if not (lo <= v <= hi) or np.isnan(v):
        raise UserError(f"{key} must be between {lo:g} and {hi:g}.")
    return v


# ------------------------------------------------------------------ progress
class _Progress:
    """Turns tqdm loops inside Demucs / audio-separator into percentages."""
    report = None      # callback(fraction, stage)
    lo, hi = 0.0, 1.0  # range of the overall bar this stage covers
    passes, done = 1, 0
    stage = ""

    @classmethod
    def begin(cls, report, lo, hi, passes, stage):
        cls.report, cls.lo, cls.hi, cls.passes, cls.done, cls.stage = report, lo, hi, max(1, passes), -1, stage

    @classmethod
    def end(cls):
        cls.report = None


class _HookedTqdm(_tqdm.tqdm):
    def __init__(self, *a, **k):
        k.update(disable=False, file=io.StringIO(), mininterval=0, miniters=1)
        super().__init__(*a, **k)
        _Progress.done += 1

    def update(self, n=1):
        r = super().update(n)
        P = _Progress
        if P.report and self.total:
            frac = min(1.0, (P.done + self.n / self.total) / P.passes)
            P.report(P.lo + (P.hi - P.lo) * frac, P.stage)
        return r


def _install_hooks():
    import demucs.apply
    demucs.apply.tqdm = types.SimpleNamespace(tqdm=_HookedTqdm)
    try:
        from audio_separator.separator.architectures import mdxc_separator
        mdxc_separator.tqdm = _HookedTqdm
    except Exception:
        pass


_install_hooks()


# ------------------------------------------------------------------ audio I/O
def load_audio(path, sr=SR, mono=False):
    """Decode anything ffmpeg understands to float32 (channels, samples)."""
    ch = 1 if mono else 2
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le",
           "-acodec", "pcm_f32le", "-ac", str(ch), "-ar", str(sr), "-"]
    p = subprocess.run(cmd, capture_output=True, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if p.returncode or not p.stdout:
        raise UserError(f"Could not read '{Path(path).name}'. Is it an audio or video file?")
    return np.frombuffer(p.stdout, dtype=np.float32).reshape(-1, ch).T.copy()


def save_audio(audio, path, sr=SR, fmt="wav"):
    audio = np.clip(np.atleast_2d(audio), -1.0, 1.0)
    # append, never with_suffix(): names like "song (1.25x speed)" contain dots that are not extensions
    path = Path(f"{path}.{fmt}")
    if fmt in ("wav", "flac"):
        sf.write(path, audio.T, sr)
    else:
        # lossy formats go through ffmpeg; libsndfile's Vorbis encoder overflows
        # the stack of Windows worker threads
        tmp = path.with_suffix(".tmp.wav")
        sf.write(tmp, audio.T, sr)
        codec = {"mp3": ["-b:a", "320k"], "ogg": ["-c:a", "libvorbis", "-q:a", "7"],
                 "m4a": ["-c:a", "aac", "-b:a", "256k"]}[fmt]
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), *codec, str(path)], check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        tmp.unlink()
    return path


def peaks(path, n=600):
    """Waveform overview: n values 0..1."""
    try:
        y = load_audio(path, sr=8000, mono=True)[0]
    except UserError:  # extremely short files can decode to nothing at 8 kHz
        return [0.0] * n
    if not len(y):
        return [0.0] * n
    y = np.abs(y[: len(y) // n * n].reshape(n, -1)).max(axis=1) if len(y) >= n else np.abs(y)
    m = float(y.max()) or 1.0
    return [round(float(v) / m, 3) for v in y]


def duration(path):
    try:
        return float(librosa.get_duration(path=str(path)))
    except Exception:
        return load_audio(path, sr=8000, mono=True).shape[1] / 8000


def job_dir(src, tag):
    name = re.sub(r"[^\w\- ]", "_", Path(src).stem)[:40].strip() or "audio"
    d = OUT / f"{name} - {tag} {time.strftime('%Y-%m-%d %H%M%S')}"
    d.mkdir(parents=True, exist_ok=True)
    return d, name


def _result(d, items):
    return {"folder": str(d), "files": [{"key": k, "label": k.replace("_", " ").title(), "path": str(p)}
                                        for k, p in items]}


# ------------------------------------------------------------------ models
_demucs: dict = {}
_seps: dict = {}


def free_gpu():
    _seps.clear()
    for m in _demucs.values():
        m.to("cpu")
    gc.collect()
    if DEVICE == "cuda":
        torch.cuda.empty_cache()


def models_loaded():
    """True while a separation model may be occupying GPU memory."""
    if _seps:
        return True
    for m in _demucs.values():
        try:
            if next(m.parameters()).device.type != "cpu":
                return True
        except (AttributeError, StopIteration, TypeError):
            pass
    return False


def _roformer(path, key, speed, report):
    from audio_separator.separator import Separator
    label, model_file = ROFORMER[key]
    tmp = OUT / ".work"
    tmp.mkdir(exist_ok=True)
    if key not in _seps:
        free_gpu()
        first = not (MODEL_DIR / model_file).exists()
        report(0.04, f"Downloading {label} model (one time only)..." if first else f"Loading {label} model...")
        try:
            sep = Separator(log_level=logging.WARNING, output_dir=str(tmp), model_file_dir=str(MODEL_DIR),
                            output_format="WAV")
            sep.load_model(model_filename=model_file)
        except BaseException as e:  # audio-separator calls sys.exit() on errors
            free_gpu()
            raise UserError(f"Could not load the {label} model: {e}") from None
        _seps[key] = sep
    sep = _seps[key]
    sep.model_instance.overlap = SPEED[speed][0]
    _Progress.begin(report, 0.10, 0.92, 1, f"Extracting vocals with {label}")
    try:
        outs = sep.separate(str(path))
    except BaseException as e:
        free_gpu()
        raise UserError(f"Separation failed: {e}") from None
    finally:
        _Progress.end()
    stems = {}
    for f in outs:
        p = Path(f) if Path(f).is_absolute() else tmp / f
        stems["vocals" if "(vocals)" in p.name.lower() else "instrumental"] = load_audio(p)
        p.unlink()
    return stems


def _run_demucs(path, stems_n, speed, report):
    from demucs.apply import apply_model
    from demucs.pretrained import get_model
    report(0.02, "Reading audio...")
    audio = load_audio(path)
    name = "htdemucs_6s" if stems_n == 6 else "htdemucs"
    free_gpu()
    if name not in _demucs:
        report(0.05, "Loading Demucs model...")
        m = get_model(name)
        m.eval()
        _demucs[name] = m
    model = _demucs[name]
    _, shifts, overlap = SPEED[speed]
    wav = torch.from_numpy(audio)
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    wav = (wav - mean) / std
    passes = len(getattr(model, "models", [model])) * max(1, shifts)
    for dev in ([DEVICE, "cpu"] if DEVICE == "cuda" else ["cpu"]):
        _Progress.begin(report, 0.10, 0.92, passes,
                        f"Splitting into {stems_n} stems" + (" (on CPU)" if dev == "cpu" else ""))
        try:
            model.to(dev)
            with torch.no_grad():
                out = apply_model(model, wav[None], device=dev, shifts=shifts, split=True,
                                  overlap=overlap, progress=True)[0]
            break
        except torch.cuda.OutOfMemoryError:
            free_gpu()
        finally:
            _Progress.end()
    else:
        raise UserError("Demucs could not run on this device.")
    stems = (out * std + mean).cpu().numpy()
    return {n: stems[i] for i, n in enumerate(model.sources)}


# ------------------------------------------------------------------ tools
def separate(p, report):
    path = p["file"]
    engine = choice(p, "engine", [*ROFORMER, "demucs"], "bs_roformer")
    speed = choice(p, "speed", list(SPEED), "fast")
    fmt = choice(p, "format", FORMATS, "wav")
    stems_n = int(choice(p, "stems", [2, 4, 6], 2)) if engine == "demucs" else 2
    if engine in ROFORMER:
        stems = _roformer(path, engine, speed, report)
    else:
        stems = _run_demucs(path, stems_n, speed, report)
        if stems_n == 2:
            stems = {"vocals": stems["vocals"],
                     "instrumental": sum(v for k, v in stems.items() if k != "vocals")}
    d, name = job_dir(path, "stems")
    order = ["vocals", "instrumental", "drums", "bass", "guitar", "piano", "other"]
    items = []
    for i, k in enumerate([k for k in order if k in stems]):
        report(0.92 + 0.08 * i / len(stems), f"Saving {k}...")
        items.append((k, save_audio(stems[k], d / f"{name} - {k}", fmt=fmt)))
    return _result(d, items)


def mix(p, report):
    files, vols = p.get("files") or {}, p.get("volumes") or {}
    fmt = choice(p, "format", FORMATS, "mp3")
    if not isinstance(files, dict) or not isinstance(vols, dict) or not files:
        raise UserError("No stems to mix.")
    vols = {k: number(vols, k, 0, 200, 100) for k in files}
    out = None
    folder: Path = OUT
    keys = [k for k in files if vols[k] > 0]
    if not keys:
        raise UserError("All stems are muted.")
    for i, k in enumerate(keys):
        report(0.8 * i / len(keys), f"Mixing {k}...")
        path = Path(str(files[k])).resolve()
        if OUT.resolve() not in path.parents or not path.is_file():
            raise UserError("Invalid stem file.")
        folder = path.parent
        a = load_audio(path) * (vols[k] / 100.0)
        out = a if out is None else out[:, :a.shape[1]] + a[:, :out.shape[1]]
    report(0.9, "Saving mix...")
    return _result(folder, [("custom_mix", save_audio(out, folder / f"custom mix {time.strftime('%H%M%S')}", fmt=fmt))])


def pitch_tempo(p, report):
    path, fmt = p["file"], choice(p, "format", FORMATS, "wav")
    st, tempo = number(p, "semitones", -24, 24, 0), number(p, "tempo", 25, 400, 100)
    keep_pitch = choice(p, "keep_pitch", [True, False], True)
    report(0.05, "Reading audio...")
    audio = load_audio(path)
    rate = tempo / 100.0
    chans = []
    for i, ch in enumerate(audio):
        report(0.1 + 0.8 * i / len(audio), f"Processing channel {i + 1} of {len(audio)}...")
        y = librosa.effects.pitch_shift(ch, sr=SR, n_steps=st) if st else ch
        if rate != 1:
            if keep_pitch:  # time-stretch: speed changes, key stays
                y = librosa.effects.time_stretch(y, rate=rate)
            else:  # tape-style: play faster/slower, so pitch moves with speed
                y = librosa.resample(y, orig_sr=round(SR * rate), target_sr=SR)
        chans.append(y)
    report(0.92, "Saving...")
    d, name = job_dir(path, "pitch")
    label = f"{rate:g}x speed{'' if keep_pitch else ' tape'}, {st:+g} st"
    return _result(d, [("result", save_audio(np.stack(chans), d / f"{name} ({label})", fmt=fmt))])


MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
CAMELOT = {"major": ["8B", "3B", "10B", "5B", "12B", "7B", "2B", "9B", "4B", "11B", "6B", "1B"],
           "minor": ["5A", "12A", "7A", "2A", "9A", "4A", "11A", "6A", "1A", "8A", "3A", "10A"]}


def analyze(p, report):
    report(0.05, "Reading audio...")
    y = load_audio(p["file"], sr=22050, mono=True)[0]
    report(0.3, "Detecting tempo...")
    tempo, beats = librosa.beat.beat_track(y=y, sr=22050)
    bpm = float(np.atleast_1d(tempo)[0])
    if len(beats) >= 8:
        # librosa's tempo is quantised to a coarse grid (~2%); the average beat spacing is exact
        t = librosa.frames_to_time(beats, sr=22050)
        bpm = 60.0 * (len(t) - 1) / (t[-1] - t[0])
    report(0.6, "Detecting key...")
    chroma = librosa.feature.chroma_cqt(y=librosa.effects.harmonic(y), sr=22050).mean(axis=1)
    if not np.isfinite(chroma).all() or chroma.std() < 1e-6:
        chroma = np.zeros(12)
    with np.errstate(invalid="ignore", divide="ignore"):
        scores = sorted(((np.nan_to_num(np.corrcoef(chroma, np.roll(prof, i))[0, 1], nan=-1.0), i, mode)
                         for i in range(12) for prof, mode in ((MAJOR, "major"), (MINOR, "minor"))), reverse=True)
    (s1, i1, m1), (s2, i2, m2) = scores[0], scores[1]
    conf = max(0.0, min(1.0, (s1 - s2) * 8 + 0.5)) if s1 > 0 else 0.0
    if conf == 0:  # no tonal content (e.g. pure percussion)
        return {"analysis": {"key": "No clear key", "camelot": "—", "alt_key": "—", "bpm": round(bpm, 1),
                             "half": round(bpm / 2, 1), "double": round(bpm * 2, 1), "confidence": 0,
                             "duration": round(len(y) / 22050, 1)}}
    return {"analysis": {"key": f"{NOTES[i1]} {m1}", "camelot": CAMELOT[m1][i1], "alt_key": f"{NOTES[i2]} {m2}",
                         "bpm": round(bpm, 1), "half": round(bpm / 2, 1), "double": round(bpm * 2, 1),
                         "confidence": round(conf * 100), "duration": round(len(y) / 22050, 1)}}


def cut(p, report):
    path, fmt = p["file"], choice(p, "format", FORMATS, "mp3")
    start, end = number(p, "start", 0, 1e6, 0), number(p, "end", 0, 1e6, 0)
    fi, fo = number(p, "fade_in", 0, 60, 0), number(p, "fade_out", 0, 60, 0)
    report(0.1, "Reading audio...")
    audio = load_audio(path)
    total = audio.shape[1] / SR
    end = total if end <= 0 or end > total else end
    if start >= end:
        raise UserError(f"Start must be before end (the file is {total:.1f}s long).")
    seg = audio[:, int(start * SR):int(end * SR)].copy()
    for secs, first in ((fi, True), (fo, False)):
        n = min(int(secs * SR), seg.shape[1])
        if n:
            ramp = np.linspace(0, 1, n, dtype=np.float32)
            if first:
                seg[:, :n] *= ramp
            else:
                seg[:, -n:] *= ramp[::-1]
    report(0.8, "Saving...")
    d, name = job_dir(path, "cut")
    return _result(d, [("result", save_audio(seg, d / f"{name} [{start:g}-{end:g}s]", fmt=fmt))])


def join(p, report):
    paths, fmt = p.get("files") or [], choice(p, "format", FORMATS, "mp3")
    cf = number(p, "crossfade", 0, 30, 0)
    if len(paths) < 2:
        raise UserError("Add at least two files to join.")
    n = int(cf * SR)
    out = None
    for i, path in enumerate(paths):
        report(0.85 * i / len(paths), f"Adding file {i + 1} of {len(paths)}...")
        nxt = load_audio(path)
        if out is None:
            out = nxt
            continue
        k = min(n, out.shape[1], nxt.shape[1])
        if k:
            ramp = np.linspace(0, 1, k, dtype=np.float32)
            out = np.concatenate([out[:, :-k], out[:, -k:] * ramp[::-1] + nxt[:, :k] * ramp, nxt[:, k:]], axis=1)
        else:
            out = np.concatenate([out, nxt], axis=1)
    report(0.9, "Saving...")
    d, _ = job_dir(paths[0], "joined")
    return _result(d, [("result", save_audio(out, d / "joined", fmt=fmt))])


def convert(p, report):
    path, fmt = p["file"], choice(p, "format", FORMATS, "mp3")
    report(0.2, "Converting...")
    d, name = job_dir(path, "convert")
    return _result(d, [("result", save_audio(load_audio(path), d / name, fmt=fmt))])


TOOLS = {"separate": separate, "mix": mix, "pitch": pitch_tempo, "analyze": analyze,
         "cut": cut, "join": join, "convert": convert}
