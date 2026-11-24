# Copyright (c) 2026 Achu Prasad. All rights reserved. See LICENSE.
"""Windows desktop entry point for Mixlumo.

Starts the local server in the background and opens the UI in its own window
(Microsoft Edge "app mode": no address bar or tabs; Edge ships with Windows 10/11).
Closing the window stops the server and the AI engine.

    Mixlumo.exe                 normal start
    Mixlumo.exe --server-only   no window (used by automated tests)
    Mixlumo.exe --port 7861     use another port
"""
import argparse
import json
import multiprocessing
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "Mixlumo"
DEFAULT_PORT = 7860


def bundle_dir():
    """Folder holding bundled resources (PyInstaller's _internal folder when frozen)."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def data_dir():
    """Per-user writable folder for logs and the window profile."""
    d = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Mixlumo"
    d.mkdir(parents=True, exist_ok=True)
    return d


def configure_environment(base):
    """Point the engine at bundled ffmpeg and models so the app works offline. Returns what was set."""
    set_ = {}
    bundled = base / "bundled"
    if (bundled / "bin" / "ffmpeg.exe").exists():
        os.environ["PATH"] = str(bundled / "bin") + os.pathsep + os.environ.get("PATH", "")
        set_["ffmpeg"] = str(bundled / "bin" / "ffmpeg.exe")
    if (bundled / "models").is_dir():
        os.environ.setdefault("AUDIO_STUDIO_MODELS", str(bundled / "models"))
        set_["models"] = os.environ["AUDIO_STUDIO_MODELS"]
    if (bundled / "torch_home").is_dir():
        os.environ.setdefault("TORCH_HOME", str(bundled / "torch_home"))
        set_["torch_home"] = os.environ["TORCH_HOME"]
    return set_


def redirect_output(log_dir):
    """A windowed .exe has no console: send output to a log file instead of losing it (or crashing on None)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log = open(log_dir / "app.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives for the whole process
    if sys.stdout is None or getattr(sys, "frozen", False):
        sys.stdout = log
    if sys.stderr is None or getattr(sys, "frozen", False):
        sys.stderr = log
    print(f"\n==== {APP_NAME} started {time.strftime('%Y-%m-%d %H:%M:%S')} ====", flush=True)
    return log


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def running_version(url, timeout=2):
    """Version of the Mixlumo server at url: None if it isn't Mixlumo, "" if it is but older than 1.2.1."""
    try:
        with urllib.request.urlopen(url + "/api/info", timeout=timeout) as r:  # noqa: S310 - fixed http://127.0.0.1 URL
            info = json.loads(r.read()) if r.status == 200 else {}
    except Exception:
        return None
    return str(info.get("version", "")) if isinstance(info, dict) and "formats" in info else None


def is_our_app(url, timeout=2):
    return running_version(url, timeout) is not None


def choose_port(port, version, tries=20):
    """Decide what to do when starting: ("reuse", port) shows an already running Mixlumo of this version;
    ("start", port) starts a server. A different (e.g. older) Mixlumo on the port is never reused, so an
    update can't silently show the old version; we start our own on the next free port instead.
    ("busy", port): the port belongs to another program."""
    if not port_in_use(port):
        return "start", port
    running = running_version(f"http://127.0.0.1:{port}")
    if running is None:
        return "busy", port
    if running == version:
        return "reuse", port
    for p in range(port + 1, port + 1 + tries):
        if not port_in_use(p):
            print(f"Mixlumo {running or '(older)'} is already running on port {port}; "
                  f"starting {version} on port {p}.", flush=True)
            return "start", p
    return "busy", port


def wait_until_ready(url, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        if is_our_app(url, timeout=1):
            return True
        time.sleep(0.3)
    return False


def find_edge():
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return shutil.which("msedge")


def open_window(url, profile_dir):
    """Open the app window and block until the user closes it. Falls back to the default browser."""
    edge = find_edge()
    if edge:
        # A dedicated profile makes Edge start its own process for this window, so wait() returns on close.
        proc = subprocess.Popen([edge, f"--app={url}", f"--user-data-dir={profile_dir}", "--no-first-run",
                                 "--no-default-browser-check", "--window-size=1400,900"])
        proc.wait()
        return "edge"
    webbrowser.open(url)
    print("Microsoft Edge not found: opened the default browser. Close this program to stop the server.", flush=True)
    while True:  # pragma: no cover - only on PCs without Edge
        time.sleep(3600)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="Mixlumo")
    ap.add_argument("--server-only", action="store_true", help="run without opening a window")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", DEFAULT_PORT)))
    args = ap.parse_args(argv)
    from feedback import APP_VERSION  # small module, no heavy imports

    action, port = choose_port(args.port, APP_VERSION)
    url = f"http://127.0.0.1:{port}"
    if action == "reuse":
        if args.server_only:
            print(f"Mixlumo {APP_VERSION} is already running at {url}", file=sys.stderr)
            return 2
        open_window(url, data_dir() / "window-profile")  # this version is already running: just show it
        return 0
    if action == "busy":
        print(f"Port {args.port} is used by another program. Try: Mixlumo.exe --port {args.port + 1}",
              file=sys.stderr)
        return 2

    redirect_output(data_dir() / "logs")
    print("Bundled resources:", configure_environment(bundle_dir()), flush=True)

    import server  # imported after the environment is configured
    srv = server.create_server(port)
    t = threading.Thread(target=srv.run, daemon=True, name="web-server")
    t.start()
    if not wait_until_ready(url):
        print("Server did not start within 120 s; see the log above.", flush=True)
        return 1
    print(f"Ready at {url}", flush=True)
    try:
        if args.server_only:
            while t.is_alive():
                t.join(1)
        else:
            open_window(url, data_dir() / "window-profile")
    finally:
        srv.should_exit = True
        server.shutdown()
        t.join(10)
        print("Stopped.", flush=True)
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()  # required: the AI worker is a spawned child of the frozen .exe
    sys.exit(main())
