# Mixlumo (c) 2026 Achu Prasad. All rights reserved.
"""Pitch & Tempo: does the live preview sound like the downloaded file?

    python scripts/compare_preview.py              all cases, printed report
    FX_TONE=110 python scripts/compare_preview.py  same, with a low steady note

Plays a synthetic test signal through the real page in Chromium, records exactly what the live preview
sends to the speakers, renders the same settings on the server, and compares: pitch (steady tone),
speed (noise onset), echo timing and levels (tone burst), tone colour in 9 octave bands and level
(noise burst), hiss floor (silence), loudness and peak. tests/e2e/test_ui.py uses the same functions.
"""
import base64
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
SR = 44100
TONE_HZ = float(os.environ.get("FX_TONE", "440"))
T_BURST, T_NOISE0, T_NOISE1, T_TONE, T_END = 0.5, 3.5, 5.0, 9.5, 11.5
BANDS = [63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

CASES = [
    ("Lo-fi 60", {"lofiOn": True, "lofiAmt": 60}),
    ("Echo 300 ms / 35 % / 35 %", {"echoOn": True, "echoDelay": 300, "echoFb": 35, "echoMix": 35}),
    ("Preset: Slowed + Echo", {"preset": "slowed"}),
    ("Preset: Lo-fi chill", {"preset": "chill"}),
    ("Speed 1.25x keep key, +3 st", {"tp": 125, "st": 3}),
    ("Key +3 st only", {"st": 3}),
    ("Key -5 st, speed 0.9x keep key", {"tp": 90, "st": -5}),
    ("Key +12 st", {"st": 12}),
    ("Key -12 st", {"st": -12}),
]


def make_signal(path, tone_hz=TONE_HZ):
    """Tone burst (echo, level), noise burst (tone colour, speed), silence (hiss), steady tone (pitch)."""
    x = np.zeros(int(T_END * SR), np.float32)
    t = np.arange(int(0.2 * SR)) / SR
    fade = np.minimum(1, np.minimum(t, t[::-1]) / 0.005)
    x[int(T_BURST * SR):int(T_BURST * SR) + len(t)] = 0.5 * np.sin(2 * np.pi * 440 * t) * fade
    a, b = int(T_NOISE0 * SR), int(T_NOISE1 * SR)
    x[a:b] = np.random.default_rng(1).standard_normal(b - a).astype(np.float32) * 0.1
    tt = np.arange(SR) / SR
    fade = np.minimum(1, np.minimum(tt, tt[::-1]) / 0.01)
    x[int(T_TONE * SR):int(T_TONE * SR) + SR] = 0.3 * np.sin(2 * np.pi * tone_hz * tt) * fade
    sf.write(path, np.stack([x, x], 1), SR, subtype="FLOAT")


# records the preview's real output (after level, plus the echo path); the speakers get the same mix
CAPTURE_JS = """async (tailMs) => {
  const sp = SRC.pitch, ctx = sp.ctx, n = sp.fx.nodes, a = sp.audio;
  a.pause(); a.currentTime = 0;
  await new Promise(r => setTimeout(r, 3000));          // let any earlier echo die away
  const tap = ctx.createGain(); n.level.connect(tap); n.wet.connect(tap);
  const proc = ctx.createScriptProcessor(4096, 1, 1), bufs = [];
  proc.onaudioprocess = e => bufs.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  tap.connect(proc); proc.connect(ctx.destination);   // its output stays silent; only keeps it running
  await a.play();
  await new Promise(r => a.addEventListener("ended", r, {once: true}));
  await new Promise(r => setTimeout(r, tailMs));
  proc.disconnect(); tap.disconnect();
  const len = bufs.reduce((s, b) => s + b.length, 0), out = new Float32Array(len);
  let o = 0; for (const b of bufs) { out.set(b, o); o += b.length; }
  const u8 = new Uint8Array(out.buffer); let s = "";
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return {sr: ctx.sampleRate, b64: btoa(s)};
}"""

RENDER_JS = """async (params) => {
  const r = await fetch("/api/jobs", {method: "POST", headers: {"Content-Type": "application/json"},
                                       body: JSON.stringify({tool: "pitch", params})});
  const {id} = await r.json();
  let j; for (;;) { j = await (await fetch(`/api/jobs/${id}`)).json();
                    if (j.status === "done" || j.status === "error") break; await new Promise(r => setTimeout(r, 200)); }
  if (j.status !== "done") return {error: j.error};
  const f = j.result.files[0];
  const buf = new Uint8Array(await (await fetch(f.url)).arrayBuffer()); let s = "";
  for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return {name: f.name, b64: btoa(s)};
}"""


def apply_ui(page, c):
    """Sets the controls like a person would and returns the parameters the page sends to the server."""
    page.click('#fxPresets button[data-v="reset"]')
    if "preset" in c:
        page.click(f'#fxPresets button[data-v="{c["preset"]}"]')
    if "tp" in c:
        page.locator("#tp").fill(str(c["tp"]))
    if "st" in c:
        page.locator("#st").fill(str(c["st"]))
    if c.get("lofiOn"):
        page.check("#lofiOn")
        page.locator("#lofiAmt").fill(str(c["lofiAmt"]))
    if c.get("echoOn"):
        page.check("#echoOn")
        for k, sel in (("echoDelay", "#echoDelay"), ("echoFb", "#echoFb"), ("echoMix", "#echoMix")):
            page.locator(sel).fill(str(c[k]))
    return page.evaluate("""() => { const fx = fxSettings();
      return {upload: SOURCES.pitch.id, semitones: +$("#st").value, tempo: +$("#tp").value,
              keep_pitch: $("#keepPitch").checked,
              lofi: fx.lofi, echo_delay: +$("#echoDelay").value, echo_feedback: +$("#echoFb").value,
              echo_mix: fx.echo ? fx.echo.mix : 0, format: "wav"}; }""")


def capture_and_render(page, params):
    """Returns (preview samples, preview rate, downloaded samples, file rate, file name), mono."""
    live = page.evaluate(CAPTURE_JS, 3000)
    rend = page.evaluate(RENDER_JS, params)
    if "error" in rend:
        raise RuntimeError(rend["error"])
    xr, srr = sf.read(io.BytesIO(base64.b64decode(rend["b64"])), dtype="float32")
    xl = np.frombuffer(base64.b64decode(live["b64"]), np.float32)
    return xl, live["sr"], (xr.mean(1) if xr.ndim == 2 else xr), srr, rend["name"]


def _env(x, sr, ms=5):
    w = max(1, int(sr * ms / 1000))
    return np.sqrt(np.convolve(x * x, np.ones(w) / w, mode="same"))


def _db(v):
    return 20 * np.log10(v + 1e-12)


def measure(x, sr, p):
    speed = p["tempo"] / 100
    env = _env(x, sr)
    t0 = int(np.argmax(env > 0.1 * env.max()))                                       # dry burst onset
    burst = int(0.2 / speed * sr)
    dry_peak = env[t0:t0 + burst].max()
    ts = t0 + int((T_TONE - T_BURST) / speed * sr)
    seg = x[ts + int(0.1 * sr):ts + int((1.0 / speed - 0.1) * sr)]
    f = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 1 << 20))
    k = int(np.argmax(f))
    a_, b_, c_ = np.log(f[k - 1:k + 2] + 1e-12)
    out = {"pitch_hz": (k + 0.5 * (a_ - c_) / (a_ - 2 * b_ + c_)) * sr / (1 << 20),   # interpolated peak
           "tone_rms_dbfs": _db(np.sqrt(np.mean(seg ** 2)))}
    if p["echo_mix"] > 0:
        d, taps = p["echo_delay"] / 1000, []
        on_dry = t0 - int(0.02 * sr) + int(np.argmax(env[t0 - int(0.02 * sr):] > 0.5 * dry_peak))
        for k in (1, 2, 3):
            lo = t0 + int(k * d * sr) - int(0.03 * sr)
            hi = lo + burst + int(0.06 * sr)
            if hi < len(env):
                m = env[lo:hi].max()
                taps.append(((lo + int(np.argmax(env[lo:hi] > 0.5 * m)) - on_dry) / sr, _db(m / dry_peak)))
        out["echo_taps"] = taps
    n0, n1 = t0 + int((T_NOISE0 - T_BURST) / speed * sr), t0 + int((T_NOISE1 - T_BURST) / speed * sr)
    nz = x[n0 + int(0.05 * sr):n1 - int(0.05 * sr)]
    w = env[n0 - int(0.2 * sr):n0 + int(0.2 * sr)]
    out["noise_onset_s"] = (n0 - int(0.2 * sr) + int(np.argmax(w > 0.3 * env[n0:n1].max())) - t0) / sr
    spec, fr = np.abs(np.fft.rfft(nz * np.hanning(len(nz)))) ** 2, np.fft.rfftfreq(len(nz), 1 / sr)
    e = [spec[(fr >= b / 1.414) & (fr < b * 1.414)].mean() for b in BANDS]
    out["bands_db"] = [10 * np.log10(v / e[4]) for v in e]
    out["noise_rms_dbfs"] = _db(np.sqrt(np.mean(nz ** 2)))
    tail = x[n1 + int(2.2 * sr):n1 + int(3.2 * sr)]
    out["floor_dbfs"] = _db(np.sqrt(np.mean(tail ** 2))) if len(tail) > sr // 2 else None
    out["peak"] = float(np.abs(x).max())
    return out


def report(results):
    for r in results:
        L, R = r["live"], r["render"]
        print(f"\n=== {r['case']} ===   file: {r['file']}")
        cents = 1200 * np.log2(L["pitch_hz"] / R["pitch_hz"])
        print(f"  pitch           preview {L['pitch_hz']:8.2f} Hz   download {R['pitch_hz']:8.2f} Hz   ({cents:+.1f} cents)")
        print(f"  speed           noise starts at {L['noise_onset_s']:.3f} s / {R['noise_onset_s']:.3f} s")
        for k, (a, b) in enumerate(zip(L.get("echo_taps", []), R.get("echo_taps", []), strict=False), 1):
            print(f"  echo {k}          preview {a[0]*1000:5.0f} ms {a[1]:6.1f} dB"
                  f"   download {b[0]*1000:5.0f} ms {b[1]:6.1f} dB")
        names = [str(b) if b < 1000 else f"{b // 1000}k" for b in BANDS]
        print("  tone colour     " + " ".join(f"{n:>6}" for n in names) + "  (dB vs 1 kHz)")
        print("        preview   " + " ".join(f"{v:6.1f}" for v in L["bands_db"]))
        print("       download   " + " ".join(f"{v:6.1f}" for v in R["bands_db"]))
        print(f"  loudness        tone {L['tone_rms_dbfs']:6.1f} / {R['tone_rms_dbfs']:6.1f} dBFS"
              f"   noise {L['noise_rms_dbfs']:6.1f} / {R['noise_rms_dbfs']:6.1f} dBFS"
              f"   peak {L['peak']:.3f} / {R['peak']:.3f}")
        fl, fr = L["floor_dbfs"], R["floor_dbfs"]
        if fl is not None and fr is not None and max(fl, fr) > -120:
            print(f"  hiss floor      {L['floor_dbfs']:6.1f} / {R['floor_dbfs']:6.1f} dBFS")


def open_pitch_page(pw, url, src):
    br = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    page = br.new_page()
    page.goto(url)
    page.click('nav button[data-page="pitch"]')
    page.set_input_files('[data-drop="pitch"] input[type=file]', str(src))
    page.wait_for_selector('[data-drop="pitch"] .preview .play', timeout=20_000)
    page.click('[data-drop="pitch"] .preview .play')
    page.wait_for_function("SRC.pitch && SRC.pitch.fx && !SRC.pitch.audio.paused", timeout=10_000)
    return br, page


def main():
    from playwright.sync_api import sync_playwright
    spec = importlib.util.spec_from_file_location("e2econf", ROOT / "tests" / "e2e" / "conftest.py")
    conf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conf)
    tmp = Path(tempfile.mkdtemp(prefix="mixlumo-compare-"))
    src = tmp / "preview test signal.wav"
    make_signal(src)
    proc, url = conf._start(7891, gpu=False)
    results = []
    try:
        with sync_playwright() as pw:
            br, page = open_pitch_page(pw, url, src)
            for name, c in CASES:
                params = apply_ui(page, c)
                xl, srl, xr, srr, fname = capture_and_render(page, params)
                results.append({"case": name, "params": params, "file": fname,
                                "live": measure(xl, srl, params), "render": measure(xr, srr, params)})
                print("measured:", name, flush=True)
            br.close()
    finally:
        proc.kill()
    (tmp / "results.json").write_text(json.dumps(results, indent=1, default=float))
    report(results)
    print(f"\nraw results: {tmp / 'results.json'}")


if __name__ == "__main__":
    sys.exit(main())
