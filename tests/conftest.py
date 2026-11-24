"""Shared fixtures.

All test audio is synthesised with ffmpeg (no third-party recordings), and every
test writes to temporary folders: the user's real Music output and uploads are
never touched.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Must be set before engine/server are imported anywhere.
_TMP = Path(tempfile.mkdtemp(prefix="las-tests-"))
os.environ["AUDIO_STUDIO_OUT"] = str(_TMP / "out")
os.environ["AUDIO_STUDIO_UPLOADS"] = str(_TMP / "uploads")
os.environ["AUDIO_STUDIO_FEEDBACK"] = str(_TMP / "feedback.jsonl")
# never read the developer's private .env and never send real e-mail from tests
os.environ["AUDIO_STUDIO_NO_DOTENV"] = "1"
for _k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "FEEDBACK_NOTIFY_TO"):
    os.environ.pop(_k, None)

SR = 44100


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


@pytest.fixture(scope="session")
def tmp_root():
    return _TMP


@pytest.fixture(scope="session")
def fixtures(tmp_root):
    """Synthetic, legally clean audio fixtures."""
    d = tmp_root / "fixtures"
    d.mkdir(exist_ok=True)
    f = {}
    # 5 s stereo 440 Hz tone, 44.1 kHz WAV
    f["tone_wav"] = d / "tone 440.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=f=440:d=5:sample_rate=44100", "-ac", "2", f["tone_wav"])
    # same as MP3 and as 22.05 kHz mono FLAC (resampling + upmix)
    f["tone_mp3"] = d / "tone.mp3"
    ffmpeg("-i", f["tone_wav"], "-b:a", "192k", f["tone_mp3"])
    f["mono_flac"] = d / "mono22k.flac"
    ffmpeg("-f", "lavfi", "-i", "sine=f=440:d=3:sample_rate=22050", "-ac", "1", f["mono_flac"])
    # video file with an audio track
    f["video_mp4"] = d / "clip.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc=d=3:s=160x120", "-f", "lavfi", "-i", "sine=f=330:d=3",
           "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", f["video_mp4"])
    # A-major triad (A3, C#4, E4) for key detection
    f["a_major"] = d / "a major.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=f=220:d=12", "-f", "lavfi", "-i", "sine=f=277.18:d=12",
           "-f", "lavfi", "-i", "sine=f=329.63:d=12", "-filter_complex", "amix=inputs=3,aformat=channel_layouts=stereo",
           f["a_major"])
    # 120 BPM percussive clicks (short noise bursts every 0.5 s)
    f["click_120"] = d / "click120.wav"
    ffmpeg("-f", "lavfi", "-i",
           "aevalsrc='if(lt(mod(t\\,0.5)\\,0.02)\\,(random(0)*2-1)*0.9\\,0)':d=20:s=44100", "-ac", "2", f["click_120"])
    # broken / malicious inputs
    f["spoofed_mp3"] = d / "not audio.mp3"
    f["spoofed_mp3"].write_text("this is plain text pretending to be an mp3 " * 50)
    f["png_as_wav"] = d / "image.wav"
    f["png_as_wav"].write_bytes(b"\x89PNG\r\n\x1a\n" + os.urandom(4000))
    f["empty"] = d / "empty.wav"
    f["empty"].write_bytes(b"")
    return f


def pytest_collection_modifyitems(config, items):
    """GPU tests need CUDA and a GPU that no other process is using."""
    import torch
    reason = None
    if not torch.cuda.is_available():
        reason = "No CUDA GPU available"
    else:
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10).stdout
            if int(out.strip().splitlines()[0]) > 1200:
                reason = f"GPU busy: {out.strip()} MiB already in use by another process"
        except Exception:
            pass
    if reason:
        for it in items:
            if "gpu" in it.keywords:
                it.add_marker(pytest.mark.skip(reason=reason))
