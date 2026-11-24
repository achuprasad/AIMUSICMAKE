"""Smoke test for the frozen Windows app.  Usage: python scripts/smoke_test_exe.py <path to LocalAudioStudio.exe>

Runs the exe as if on a fresh PC: empty user profile, no ffmpeg on PATH, temporary
folders. Passes only if the bundled ffmpeg, models and Demucs weights are used and
real jobs (CPU tools and GPU separation in the worker process) succeed.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

PORT = 7875
URL = f"http://127.0.0.1:{PORT}"


def call(method, path, body=None, files=None, timeout=30):
    if files:
        boundary = "----lasboundary"
        name, data = files
        payload = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                   f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(URL + path, data=payload, method=method,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    else:
        req = urllib.request.Request(URL + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - local test server
        return json.loads(r.read())


def run_job(tool, params, timeout=900):
    jid = call("POST", "/api/jobs", {"tool": tool, "params": params})["id"]
    t, seen = time.time(), set()
    while time.time() - t < timeout:
        j = call("GET", f"/api/jobs/{jid}")
        seen.add(round(j["progress"], 2))
        if j["status"] in ("done", "error"):
            return j, seen
        time.sleep(0.5)
    raise TimeoutError(tool)


def main(exe):
    tmp = Path(tempfile.mkdtemp(prefix="las-smoke-"))
    profile = tmp / "profile"
    profile.mkdir()
    env = dict(os.environ)
    # a fresh PC: empty profile, no ffmpeg on PATH, nothing from the dev environment
    env.update(USERPROFILE=str(profile), LOCALAPPDATA=str(profile / "AppData" / "Local"),
               AUDIO_STUDIO_OUT=str(tmp / "out"), AUDIO_STUDIO_UPLOADS=str(tmp / "uploads"),
               AUDIO_STUDIO_FEEDBACK=str(tmp / "feedback.jsonl"))
    for k in ("AUDIO_STUDIO_MODELS", "TORCH_HOME", "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
        env.pop(k, None)
    env["PATH"] = os.pathsep.join(p for p in env["PATH"].split(os.pathsep)
                                  if "ffmpeg" not in p.lower() and not (Path(p) / "ffmpeg.exe").exists())
    proc = subprocess.Popen([exe, "--server-only", "--port", str(PORT)], env=env)
    results, ok = [], True

    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        results.append(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")
        print(results[-1], flush=True)

    try:
        t = time.time()
        info = None
        while time.time() - t < 180:
            try:
                info = call("GET", "/api/info", timeout=2)
                break
            except Exception:
                if proc.poll() is not None:
                    break
                time.sleep(1)
        check("exe starts and serves the API", info, f"in {time.time() - t:.0f}s, device={info and info['device']}")
        if not info:
            return 1
        check("UI page is served", b"Local Audio Studio" in urllib.request.urlopen(URL, timeout=10).read())  # noqa: S310

        sr = 44100
        tt = np.arange(sr * 8) / sr
        tone = np.stack([0.3 * np.sin(2 * np.pi * 220 * tt) + 0.2 * np.sin(2 * np.pi * 330 * tt)] * 2).T
        src = tmp / "smoke tone.wav"
        sf.write(src, tone, sr)
        up = call("POST", "/api/upload", files=(src.name, src.read_bytes()))
        check("upload + decode (bundled ffmpeg)", abs(up["duration"] - 8) < 0.1, f"duration={up['duration']}")

        for tool, params, expect in [
            ("convert", {"format": "mp3"}, ".mp3"),
            ("convert", {"format": "ogg"}, ".ogg"),
            ("pitch", {"semitones": 2, "tempo": 125, "format": "wav"}, ".wav"),
            ("analyze", {}, None),
            ("separate", {"engine": "bs_roformer", "speed": "fast", "format": "wav"}, "vocals"),
            ("separate", {"engine": "demucs", "stems": 4, "speed": "fast", "format": "mp3"}, "drums"),
        ]:
            j, seen = run_job(tool, {"upload": up["id"], **params})
            label = f"{tool} {params.get('engine', params.get('format', ''))}"
            if j["status"] != "done":
                check(label, False, j.get("error", ""))
                continue
            if tool == "analyze":
                check(label, j["result"]["analysis"]["key"] != "", j["result"]["analysis"]["key"])
            else:
                names = [f["name"] for f in j["result"]["files"]]
                check(label, any(expect in n for n in names), f"{names} progress steps={len(seen)} in {j['elapsed']}s")

        leaked = [p for p in (profile / ".audiostudio" / "models", profile / ".cache" / "torch") if p.exists()]
        check("no model downloads (everything came from the bundle)", not leaked, str(leaked))
        log = profile / "AppData" / "Local" / "LocalAudioStudio" / "logs" / "app.log"
        check("log file written", log.exists(), str(log))
    finally:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
    print("\nSMOKE TEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
