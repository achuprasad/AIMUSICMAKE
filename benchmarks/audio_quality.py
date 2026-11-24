"""Audio-quality benchmark against MUSDB18 reference stems.

Usage:  python benchmarks/audio_quality.py [--tracks N]
Writes  docs/audio-quality-benchmarks.md  and  benchmarks/results.json

Runs the real engine (same code path as the app) on the MUSDB18 test split
(7-second excerpts, research licence), so the GPU must be otherwise idle.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))
os.environ.setdefault("AUDIO_STUDIO_OUT", tempfile.mkdtemp(prefix="las-bench-"))

import metrics as M  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402

import engine  # noqa: E402

CONFIGS = [
    ("BS-RoFormer", "fast", {"engine": "bs_roformer", "speed": "fast"}),
    ("BS-RoFormer", "balanced", {"engine": "bs_roformer", "speed": "balanced"}),
    ("BS-RoFormer", "best", {"engine": "bs_roformer", "speed": "best"}),
    ("Mel-Band RoFormer", "balanced", {"engine": "mel_roformer", "speed": "balanced"}),
    ("Demucs 2-stem", "balanced", {"engine": "demucs", "stems": 2, "speed": "balanced"}),
    ("Demucs 4-stem", "balanced", {"engine": "demucs", "stems": 4, "speed": "balanced"}),
]

# Acceptance criteria (median over tracks). Published MUSDB18 vocals SDR:
# BS-RoFormer ep317 11.8 dB, Mel-RoFormer ep3005 10.5 dB, HT-Demucs ~8-9 dB.
THRESHOLDS = {
    "BS-RoFormer": {"vocals": 8.0, "accompaniment": 13.0},
    "Mel-Band RoFormer": {"vocals": 7.0, "accompaniment": 12.0},
    "Demucs 2-stem": {"vocals": 6.0, "accompaniment": 11.0},
    "Demucs 4-stem": {"vocals": 6.0, "drums": 5.0, "bass": 3.0},
}
MAX_GPU_MB = 3800  # GTX 1650 has 4096 MB


def run_config(name, speed, opts, tracks, tmp):
    rows = []
    for tr in tracks:
        ref = M.load_track(tr)
        mix_path = tmp / (tr.stem.replace(".stem", "") + ".wav")
        if not mix_path.exists():
            sf.write(mix_path, ref["mixture"].T, M.SR)
        if engine.DEVICE == "cuda":
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
        progress: list[float] = []
        t = time.perf_counter()
        res = engine.separate({"file": str(mix_path), "format": "wav", **opts}, lambda f, s, _p=progress: _p.append(f))
        dt = time.perf_counter() - t
        gpu_mb = torch.cuda.max_memory_allocated() / 2 ** 20 if engine.DEVICE == "cuda" else 0
        dur_in = ref["mixture"].shape[1] / M.SR
        row = {"track": tr.name, "seconds": round(dt, 2), "rtf": round(dt / dur_in, 3), "gpu_mb": round(gpu_mb),
               "progress_updates": len(progress), "progress_monotonic": progress == sorted(progress), "stems": {}}
        for f in res["files"]:
            est, _ = sf.read(f["path"], always_2d=True)
            est = est.T
            info = sf.info(f["path"])
            k = "accompaniment" if f["key"] == "instrumental" else f["key"]
            s = {"sample_rate": info.samplerate, "channels": info.channels,
                 "len_diff_samples": int(est.shape[1] - ref["mixture"].shape[1]),
                 "clipped": M.clipped_samples(est), "peak": round(float(np.abs(est).max()), 3)}
            if k in ref and M.has_energy(ref[k]):
                s["sdr"] = round(M.sdr(ref[k], est), 2)
                if k in ("vocals", "accompaniment"):
                    other = "accompaniment" if k == "vocals" else "vocals"
                    if M.has_energy(ref[other]):
                        s["leakage_db"] = round(M.leakage_db(est, ref[k], ref[other]), 1)
            row["stems"][k] = s
        rows.append(row)
        print(f"  {name:18s} {speed:8s} {tr.name[:40]:40s} {dt:6.1f}s  " +
              "  ".join(f"{k}:{v.get('sdr', '-')}" for k, v in row["stems"].items()), flush=True)
    for d in Path(res["folder"]).parent.glob("*"):
        if d.is_dir():
            for f in d.glob("*"):
                f.unlink()
    return rows


def median(rows, stem, key):
    v = [r["stems"][stem][key] for r in rows if stem in r["stems"] and key in r["stems"][stem]]
    return (round(float(np.median(v)), 2), len(v)) if v else (None, 0)


def summarise(results):
    summary = []
    for name, speed, rows in results:
        stems = sorted({s for r in rows for s in r["stems"]})
        entry = {"model": name, "speed": speed, "tracks": len(rows),
                 "rtf_median": round(float(np.median([r["rtf"] for r in rows])), 3),
                 "seconds_per_minute_audio": round(60 * float(np.median([r["rtf"] for r in rows])), 1),
                 "gpu_mb_max": max(r["gpu_mb"] for r in rows),
                 "all_progress_monotonic": all(r["progress_monotonic"] for r in rows),
                 "min_progress_updates": min(r["progress_updates"] for r in rows),
                 "sample_rates": sorted({s["sample_rate"] for r in rows for s in r["stems"].values()}),
                 "channels": sorted({s["channels"] for r in rows for s in r["stems"].values()}),
                 "max_len_diff_samples": max(abs(s["len_diff_samples"]) for r in rows for s in r["stems"].values()),
                 "clipped_samples": sum(s["clipped"] for r in rows for s in r["stems"].values()),
                 "sdr": {}, "leakage": {}, "checks": {}}
        for s in stems:
            entry["sdr"][s] = median(rows, s, "sdr")
            lk = median(rows, s, "leakage_db")
            if lk[1]:
                entry["leakage"][s] = lk
        th = THRESHOLDS.get(name, {})
        for s, minimum in th.items():
            got = entry["sdr"].get(s, (None, 0))[0]
            entry["checks"][f"{s} SDR >= {minimum} dB"] = got is not None and got >= minimum
        entry["checks"][f"GPU memory <= {MAX_GPU_MB} MB"] = entry["gpu_mb_max"] <= MAX_GPU_MB
        entry["checks"]["44.1 kHz stereo output"] = entry["sample_rates"] == [44100] and entry["channels"] == [2]
        entry["checks"]["Output length = input length (±1 sample)"] = entry["max_len_diff_samples"] <= 1
        entry["checks"]["No clipped samples"] = entry["clipped_samples"] == 0
        entry["checks"]["Progress reported and monotonic"] = (
            entry["all_progress_monotonic"] and entry["min_progress_updates"] >= 3)
        summary.append(entry)
    return summary


def write_markdown(summary, tracks, path):
    def fmt(v):
        return "—" if v[0] is None else f"{v[0]:.2f}"
    L = ["# Audio quality benchmarks", "",
         f"_Generated by `benchmarks/audio_quality.py` on {time.strftime('%Y-%m-%d %H:%M')} · "
         f"device: {engine.GPU_NAME} · torch {torch.__version__}_", "",
         "## Method", "",
         f"- **Data:** MUSDB18 test split, 7-second excerpts (Zenodo record 3270814, research/non-commercial licence). "
         f"{len(tracks)} tracks: " + ", ".join(t.name.replace('.stem.mp4', '') for t in tracks) + ".",
         "- **Code path:** `engine.separate()`, the same function the app calls. Output is WAV.",
         "- **SDR:** MDX-challenge global SDR `10·log10(Σs² / Σ(s−ŝ)²)`, median across tracks (higher is better). "
         "Tracks whose reference stem is silent in the excerpt are excluded for that stem (n shows how many counted).",
         "- **Leakage:** least-squares projection of the estimate onto the true target and the true interferer; "
         "interferer level relative to target in dB (lower is better). For *vocals* it is instrument bleed; "
         "for *accompaniment* it is vocal bleed.",
         "- **Speed:** wall-clock seconds per minute of audio (median), including model inference and saving; "
         "the first-time model load is excluded by a warm-up.",
         "- **GPU memory:** peak PyTorch tensor allocation during the job (`torch.cuda.max_memory_allocated`). "
         "The process also holds the CUDA context and allocator cache, so `nvidia-smi` shows roughly 1–2 GB more.", "",
         "## Results", "",
         "| Model | Speed | Vocals SDR (n) | Accomp. SDR (n) | Drums | Bass | Other | Vocal-stem bleed "
         "| Instrumental-stem vocal bleed | s / min audio | Peak GPU MB |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in summary:
        s, lk = e["sdr"], e["leakage"]
        L.append(f"| {e['model']} | {e['speed']} | {fmt(s.get('vocals', (None, 0)))} ({s.get('vocals', (0, 0))[1]}) | "
                 f"{fmt(s.get('accompaniment', (None, 0)))} ({s.get('accompaniment', (0, 0))[1]}) | "
                 f"{fmt(s.get('drums', (None, 0)))} | {fmt(s.get('bass', (None, 0)))} | {fmt(s.get('other', (None, 0)))} | "
                 f"{fmt(lk.get('vocals', (None, 0)))} dB | {fmt(lk.get('accompaniment', (None, 0)))} dB | "
                 f"{e['seconds_per_minute_audio']} | {e['gpu_mb_max']} |")
    L += ["", "## Acceptance checks", "", "| Model | Speed | Check | Result |", "|---|---|---|---|"]
    fails = 0
    for e in summary:
        for c, ok in e["checks"].items():
            fails += not ok
            L.append(f"| {e['model']} | {e['speed']} | {c} | {'✅ pass' if ok else '❌ FAIL'} |")
    L += ["", f"**{sum(len(e['checks']) for e in summary) - fails} passed, {fails} failed.**", "",
          "## Notes", "",
          "- 7-second excerpts are short; full-song SDR is typically 0.5–1 dB higher because models use more context.",
          "- Thresholds sit 2–4 dB below published full-length MUSDB18 scores to allow for the short excerpts "
          "and the simplified SDR. A failure means a real regression, not noise.",
          "- Results are objective only; no listening test was used as an acceptance criterion."]
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracks", type=int, default=6)
    a = ap.parse_args()
    tracks = M.musdb_tracks(n=a.tracks)
    if not tracks:
        sys.exit("MUSDB18 test data not found in ~/.audiostudio/testdata/musdb7/test")
    tmp = Path(tempfile.mkdtemp(prefix="las-bench-mix-"))
    results = []
    for name, speed, opts in CONFIGS:
        print(f"== {name} / {speed}", flush=True)
        run_config(name, speed, opts, tracks[:1], tmp)  # warm-up: model download/load not timed
        results.append((name, speed, run_config(name, speed, opts, tracks, tmp)))
    engine.free_gpu()
    summary = summarise(results)
    (ROOT / "benchmarks" / "results.json").write_text(
        json.dumps({"summary": summary, "raw": [{"model": n, "speed": s, "rows": r} for n, s, r in results]}, indent=1),
        encoding="utf-8")
    fails = write_markdown(summary, tracks, ROOT / "docs" / "audio-quality-benchmarks.md")
    print(f"\nBenchmark finished: {fails} failed checks")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
