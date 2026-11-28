# Copyright (c) 2026 Achu Prasad. All rights reserved. See LICENSE.
"""Client for voice_worker.py: starts it with the voice environment's Python (a separate venv, so its PyTorch
never conflicts with the separation engine's), sends commands, relays progress, and detects crashes."""
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

MARK = "@@mixlumo@@ "
HOME = Path(os.environ.get("AUDIO_STUDIO_HOME", Path.home() / ".audiostudio"))


def default_python():
    env = os.environ.get("AUDIO_STUDIO_VOICE_PYTHON")
    if env:
        return Path(env)
    venv = HOME / "tts-venv"
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def worker_script():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "voice_worker.py"


class VoiceEngineError(Exception):
    """Raised with a message that can be shown to the user."""


class VoiceEngine:
    def __init__(self, python=None, script=None, timeout=1800):
        self.python = Path(python) if python else default_python()
        self.script = Path(script) if script else worker_script()
        self.timeout = timeout
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self._q: queue.Queue = queue.Queue()

    @property
    def installed(self):
        return self.python.is_file() and self.script.is_file()

    @property
    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def _start(self):
        if not self.installed:
            raise VoiceEngineError("The Malayalam voice engine is not installed. Run scripts\\setup-voice.ps1 "
                                   "(see docs/voice-studio.md).")
        log = HOME / "logs"
        log.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._q = queue.Queue()
        self.proc = subprocess.Popen([str(self.python), "-I", str(self.script)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=open(log / "voice-worker.log", "a", encoding="utf-8"),  # noqa: SIM115
                                     text=True, encoding="utf-8", env=env, creationflags=flags)
        threading.Thread(target=self._reader, args=(self.proc, self._q), daemon=True).start()

    @staticmethod
    def _reader(proc, q):
        for line in proc.stdout:
            if line.startswith(MARK):
                try:
                    q.put(json.loads(line[len(MARK):]))
                except ValueError:
                    pass
        q.put(None)                                              # end of stream: the worker exited

    def call(self, cmd, on_event=None, timeout=None, **args):
        """Send one command; returns the final reply dict. Raises VoiceEngineError on failure."""
        with self.lock:
            if not self.alive:
                self._start()
            proc = self.proc
            if proc is None or proc.stdin is None:
                raise VoiceEngineError("The voice engine could not be started.")
            try:
                proc.stdin.write(json.dumps({"cmd": cmd, **args}, ensure_ascii=False) + "\n")
                proc.stdin.flush()
            except OSError:
                self.proc = None
                raise VoiceEngineError("The voice engine stopped unexpectedly. Please try again.") from None
            while True:
                try:
                    msg = self._q.get(timeout=timeout or self.timeout)
                except queue.Empty:
                    self._kill()
                    raise VoiceEngineError("The voice engine took too long and was stopped. Try a shorter text.") from None
                if msg is None:
                    code = self.proc.poll() if self.proc else None
                    self.proc = None
                    raise VoiceEngineError(f"The voice engine stopped unexpectedly (exit code {code}). "
                                           "Please try again; see logs/voice-worker.log.")
                if msg.get("done"):
                    if not msg.get("ok"):
                        raise VoiceEngineError(msg.get("error") if msg.get("user") else
                                               f"Voice engine error: {msg.get('error')}")
                    return msg
                if on_event:
                    on_event(msg)

    def _kill(self):
        if self.proc is not None:
            try:
                self.proc.kill()
                self.proc.wait(10)
            except OSError:
                pass
        self.proc = None

    def stop(self):
        """Quit the worker so the OS reclaims all of its GPU memory. Waits for a running command."""
        with self.lock:
            proc = self.proc
            if proc is None or proc.poll() is not None or proc.stdin is None:
                self.proc = None
                return False
            try:
                proc.stdin.write('{"cmd": "quit"}\n')
                proc.stdin.flush()
                proc.wait(15)
            except (OSError, subprocess.TimeoutExpired):
                self._kill()
            self.proc = None
            return True
