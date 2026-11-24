"""Unit tests for the desktop launcher (desktop.py). The built .exe itself is tested by scripts/smoke_test_exe.py."""
import os
import socket
import sys
from pathlib import Path

import pytest

import desktop


@pytest.fixture
def clean_env(monkeypatch):
    for k in ("AUDIO_STUDIO_MODELS", "TORCH_HOME"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))


def test_configure_environment_uses_bundled_resources(tmp_path, clean_env):
    (tmp_path / "bundled" / "bin").mkdir(parents=True)
    (tmp_path / "bundled" / "bin" / "ffmpeg.exe").write_bytes(b"")
    (tmp_path / "bundled" / "models").mkdir()
    (tmp_path / "bundled" / "torch_home").mkdir()
    got = desktop.configure_environment(tmp_path)
    assert set(got) == {"ffmpeg", "models", "torch_home"}
    assert os.environ["PATH"].split(os.pathsep)[0] == str(tmp_path / "bundled" / "bin")  # bundled ffmpeg wins
    assert os.environ["AUDIO_STUDIO_MODELS"] == str(tmp_path / "bundled" / "models")
    assert os.environ["TORCH_HOME"] == str(tmp_path / "bundled" / "torch_home")


def test_configure_environment_without_bundle_changes_nothing(tmp_path, clean_env):
    path_before = os.environ["PATH"]
    assert desktop.configure_environment(tmp_path) == {}
    assert os.environ["PATH"] == path_before and "AUDIO_STUDIO_MODELS" not in os.environ


def test_user_override_of_models_is_respected(tmp_path, clean_env, monkeypatch):
    (tmp_path / "bundled" / "models").mkdir(parents=True)
    monkeypatch.setenv("AUDIO_STUDIO_MODELS", "D:/my-models")
    desktop.configure_environment(tmp_path)
    assert os.environ["AUDIO_STUDIO_MODELS"] == "D:/my-models"


def test_data_dir_is_per_user(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert desktop.data_dir() == tmp_path / "Mixlumo" and desktop.data_dir().is_dir()


def test_bundle_dir_frozen_and_source(monkeypatch, tmp_path):
    assert desktop.bundle_dir() == Path(desktop.__file__).resolve().parent
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert desktop.bundle_dir() == tmp_path


def test_redirect_output_writes_log(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    log = desktop.redirect_output(tmp_path / "logs")
    print("hello from the test")
    log.flush()
    text = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert "Mixlumo started" in text and "hello from the test" in text
    log.close()


def test_port_detection_and_foreign_app():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        assert desktop.port_in_use(port)
        assert desktop.is_our_app(f"http://127.0.0.1:{port}", timeout=0.5) is False  # not our API
    assert not desktop.port_in_use(port)


def test_refuses_port_used_by_another_program(capsys):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        assert desktop.main(["--server-only", "--port", str(port)]) == 2
    assert "used by another program" in capsys.readouterr().err


class _FakeMixlumo:
    """A tiny HTTP server answering /api/info like a running Mixlumo of a given version."""

    def __init__(self, info):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        body = json.dumps(info).encode()

        class H(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server API
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.srv.shutdown()
        self.srv.server_close()


def test_same_version_already_running_is_reused():
    with _FakeMixlumo({"formats": ["wav"], "version": "9.9.9"}) as f:
        assert desktop.running_version(f"http://127.0.0.1:{f.port}") == "9.9.9"
        assert desktop.choose_port(f.port, "9.9.9") == ("reuse", f.port)


@pytest.mark.parametrize("info", [{"formats": ["wav"], "version": "1.2.0"}, {"formats": ["wav"]}])
def test_other_or_older_version_is_never_reused(info, capsys):
    """Regression: an old Mixlumo (here 1.1.0, which reports no version) left running on the port was
    shown instead of the newly installed app, so the user tested old code."""
    with _FakeMixlumo(info) as f:
        action, port = desktop.choose_port(f.port, "9.9.9")
        assert action == "start" and port != f.port and not desktop.port_in_use(port)
    assert "starting 9.9.9 on port" in capsys.readouterr().out


def test_free_port_is_started_and_foreign_port_is_busy():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert desktop.choose_port(port, "1.0") == ("start", port)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        p = s.getsockname()[1]
        assert desktop.choose_port(p, "1.0") == ("busy", p)


def test_wait_until_ready_times_out_quickly():
    assert desktop.wait_until_ready("http://127.0.0.1:9", timeout=0.5) is False


def test_find_edge_returns_existing_path_or_none():
    edge = desktop.find_edge()
    assert edge is None or Path(edge).exists()
