import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _start(port, gpu):
    tmp = Path(tempfile.mkdtemp(prefix="las-e2e-"))
    env = dict(os.environ, PORT=str(port), AUDIO_STUDIO_OUT=str(tmp / "out"),
               AUDIO_STUDIO_UPLOADS=str(tmp / "uploads"), AUDIO_STUDIO_FEEDBACK=str(tmp / "feedback.jsonl"),
               AUDIO_STUDIO_NO_DOTENV="1", PYTHONUNBUFFERED="1")
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "FEEDBACK_NOTIFY_TO"):
        env.pop(k, None)
    if not gpu:
        env["CUDA_VISIBLE_DEVICES"] = "-1"
    log = tmp / "server.log"  # a file, not a pipe: an unread pipe would eventually block the server
    proc = subprocess.Popen([sys.executable, str(ROOT / "server.py")], cwd=ROOT, env=env,
                            stdout=open(log, "w"), stderr=subprocess.STDOUT)  # noqa: SIM115
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            urllib.request.urlopen(url + "/api/info", timeout=1)  # noqa: S310 - fixed http://127.0.0.1 URL
            return proc, url
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError(log.read_text(errors="replace")) from None
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("server did not start")


@pytest.fixture(scope="session")
def app_url():
    proc, url = _start(7871, gpu=False)
    yield url
    proc.kill()


@pytest.fixture(scope="session")
def gpu_app_url():
    proc, url = _start(7872, gpu=True)
    yield url
    proc.kill()


@pytest.fixture
def errors(page):
    """Collects JS errors and console errors; tests assert it stays empty."""
    errs = []
    page.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    page.on("console", lambda m: m.type == "error" and errs.append(f"console: {m.text}"))
    return errs
