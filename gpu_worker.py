"""Runs AI separation in a separate process.

Why a process and not a thread: PyTorch keeps a CUDA context (~700 MB on a
GTX 1650) for the life of the process that used the GPU. Running models in a
worker that exits when idle gives *all* GPU memory back, and a driver crash or
out-of-memory error kills only the worker, never the web server.

Protocol (multiprocessing queues):
  parent -> worker: ("run", tool, params) | ("quit",)
  worker -> parent: ("progress", frac, stage) | ("done", result) | ("error", message, is_user_error)
"""
import multiprocessing as mp
import queue
import threading
import time
from typing import Any


def _worker_main(inq, outq):  # pragma: no cover - runs in the child process; exercised by tests/test_worker.py
    import engine  # imported here so the parent process never touches CUDA
    while True:
        msg = inq.get()
        if msg[0] == "quit":
            break
        _, tool, params = msg
        try:
            res = engine.TOOLS[tool](params, lambda f, s: outq.put(("progress", float(f), str(s))))
            outq.put(("done", res))
        except engine.UserError as e:
            outq.put(("error", str(e), True))
        except BaseException as e:  # noqa: BLE001 - report anything (incl. sys.exit from audio-separator)
            outq.put(("error", f"{type(e).__name__}: {e}", False))


class WorkerCrashed(Exception):
    pass


class GpuWorker:
    """One long-lived child process; started on demand, stopped to free the GPU."""

    def __init__(self, poll=0.25):
        self.ctx = mp.get_context("spawn")
        # Any: set together in _start(); every use is guarded by `alive` or follows _start()
        self.proc: Any = None
        self.inq: Any = None
        self.outq: Any = None
        self.poll = poll
        self.lock = threading.Lock()  # one job at a time

    @property
    def alive(self):
        return self.proc is not None and self.proc.is_alive()

    def _start(self):
        self.inq, self.outq = self.ctx.Queue(), self.ctx.Queue()
        self.proc = self.ctx.Process(target=_worker_main, args=(self.inq, self.outq), daemon=True,
                                     name="audio-studio-gpu-worker")
        self.proc.start()

    def run(self, tool, params, report, user_error=Exception):
        with self.lock:
            if not self.alive:
                report(0.01, "Starting AI engine...")
                self._start()
            self.inq.put(("run", tool, params))
            while True:
                try:
                    msg = self.outq.get(timeout=self.poll)
                except queue.Empty:
                    if not self.proc.is_alive():
                        code = self.proc.exitcode
                        self.proc = None
                        raise WorkerCrashed(f"The AI engine stopped unexpectedly (exit code {code}). "
                                            "Please try again.") from None
                    continue
                if msg[0] == "progress":
                    report(msg[1], msg[2])
                elif msg[0] == "done":
                    return msg[1]
                else:
                    raise (user_error if msg[2] else RuntimeError)(msg[1])

    def stop(self, timeout=15):
        """Exit the worker so the OS reclaims all of its GPU memory. Waits for a running job."""
        with self.lock:
            if not self.alive:
                self.proc = None
                return False
            self.inq.put(("quit",))
            self.proc.join(timeout)
            if self.proc.is_alive():
                self.proc.terminate()
                self.proc.join(5)
            self.proc = None
            return True

    def kill(self):
        """For tests: simulate a crash."""
        if self.alive:
            self.proc.kill()
            t = time.time()
            while self.proc.is_alive() and time.time() - t < 10:
                time.sleep(0.05)
