"""Tests for the GPU worker process (real child processes, CPU tools so no GPU is needed)."""
import threading
import time

import pytest

import engine
from gpu_worker import GpuWorker, WorkerCrashed


@pytest.fixture
def worker():
    w = GpuWorker(poll=0.1)
    yield w
    w.stop()


def test_runs_a_job_and_streams_progress(worker, fixtures):
    seen = []
    res = worker.run("convert", {"file": str(fixtures["tone_wav"]), "format": "flac"},
                     lambda f, s: seen.append((f, s)), user_error=engine.UserError)
    assert res["files"][0]["path"].endswith(".flac")
    assert seen[0][1] == "Starting AI engine..." and any(s == "Converting..." for _, s in seen)
    assert worker.alive


def test_worker_is_reused_between_jobs(worker, fixtures):
    worker.run("convert", {"file": str(fixtures["tone_wav"]), "format": "wav"}, lambda f, s: None)
    pid = worker.proc.pid
    worker.run("convert", {"file": str(fixtures["tone_wav"]), "format": "wav"}, lambda f, s: None)
    assert worker.proc.pid == pid


def test_user_error_keeps_its_type(worker, fixtures):
    with pytest.raises(engine.UserError, match="Start must be before end"):
        worker.run("cut", {"file": str(fixtures["tone_wav"]), "start": 4, "end": 1}, lambda f, s: None,
                   user_error=engine.UserError)
    assert worker.alive  # a bad request must not kill the worker


def test_unexpected_error_becomes_runtime_error(worker):
    with pytest.raises(RuntimeError, match="KeyError"):
        worker.run("convert", {}, lambda f, s: None, user_error=engine.UserError)


def test_stop_ends_the_process(worker, fixtures):
    worker.run("convert", {"file": str(fixtures["tone_wav"]), "format": "wav"}, lambda f, s: None)
    proc = worker.proc
    assert worker.stop() is True
    assert not proc.is_alive() and not worker.alive
    assert worker.stop() is False


def test_crash_mid_job_is_reported_and_next_job_recovers(worker, fixtures):
    long = {"file": str(fixtures["a_major"]), "semitones": 3, "tempo": 80, "format": "wav"}
    errors = []

    def job():
        try:
            worker.run("pitch", long, lambda f, s: None)
        except WorkerCrashed as e:
            errors.append(e)
    t = threading.Thread(target=job)
    t.start()
    for _ in range(200):  # wait until the child is up and working
        if worker.alive:
            break
        time.sleep(0.05)
    time.sleep(1.0)
    worker.kill()
    t.join(30)
    assert errors and "stopped unexpectedly" in str(errors[0])
    res = worker.run("convert", {"file": str(fixtures["tone_wav"]), "format": "wav"}, lambda f, s: None)
    assert res["files"][0]["path"].endswith(".wav")


def _alive(pid):
    import subprocess
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False).stdout
    return str(pid) in out


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="uses tasklist")
def test_worker_exits_when_parent_is_killed(tmp_path):
    """Regression: a killed app left its AI worker running, holding ~1.5 GB of GPU memory forever."""
    import os
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(__file__))
    script = tmp_path / "parent.py"
    script.write_text(
        "import sys, time\n"
        f"sys.path.insert(0, {root!r})\n"
        "from gpu_worker import GpuWorker\n"
        "if __name__ == '__main__':\n"
        "    w = GpuWorker()\n"
        "    w._start()\n"
        "    print(w.proc.pid, flush=True)\n"
        "    time.sleep(300)\n", encoding="utf-8")
    parent = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True,
                              env=dict(os.environ, CUDA_VISIBLE_DEVICES="-1"))
    child = int(parent.stdout.readline())
    time.sleep(3)  # let the worker finish starting up
    assert _alive(child)
    parent.kill()  # hard kill, like Task Manager: no cleanup code runs in the parent
    parent.wait(10)
    for _ in range(100):
        if not _alive(child):
            break
        time.sleep(0.1)
    assert not _alive(child), "orphaned worker still running after its parent was killed"


def test_parent_never_initialises_cuda():
    """The web server must not hold a CUDA context; only the worker may."""
    import torch

    import server  # noqa: F401
    assert not torch.cuda.is_initialized()
