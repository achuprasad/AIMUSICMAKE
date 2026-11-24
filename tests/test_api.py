"""Integration tests for the HTTP API (server.py) via FastAPI's httpx TestClient."""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import engine
import server


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


def upload(client, path, name=None):
    with open(path, "rb") as f:
        return client.post("/api/upload", files={"file": (name or Path(path).name, f, "application/octet-stream")})


def wait(client, jid, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.1)
    raise TimeoutError(jid)


def run(client, tool, params):
    r = client.post("/api/jobs", json={"tool": tool, "params": params})
    assert r.status_code == 200, r.text
    return wait(client, r.json()["id"])


# ------------------------------------------------------------------ pages
def test_index_page(client):
    r = client.get("/")
    assert r.status_code == 200 and "Mixlumo" in r.text and "text/html" in r.headers["content-type"]


def test_info(client):
    j = client.get("/api/info").json()
    assert set(j) == {"device", "gpu", "output", "formats", "version", "web"}
    assert j["web"] is False  # desktop/dev default; only the Docker image sets AUDIO_STUDIO_WEB=1
    assert j["device"] in ("cuda", "cpu") and j["formats"] == engine.FORMATS
    import feedback
    assert j["version"] == feedback.APP_VERSION   # the launcher compares it before reusing a running app


def test_info_leaks_no_secrets(client):
    body = client.get("/api/info").text.lower()
    for word in ("token", "password", "secret", "api_key", "path\": \"c:\\\\windows"):
        assert word not in body


def test_importing_server_never_deletes_files(tmp_path):
    """Regression: `import server` used to wipe the uploads folder of a running instance mid-job."""
    import subprocess
    import sys
    up, out = tmp_path / "uploads", tmp_path / "out"
    (up / "abc").mkdir(parents=True)
    (up / "abc" / "song.mp3").write_bytes(b"in use")
    (out / ".work").mkdir(parents=True)
    (out / ".work" / "stem.wav").write_bytes(b"in use")
    env = dict(__import__("os").environ, AUDIO_STUDIO_UPLOADS=str(up), AUDIO_STUDIO_OUT=str(out),
               CUDA_VISIBLE_DEVICES="-1")
    r = subprocess.run([sys.executable, "-c", "import server"], cwd=Path(server.__file__).parent, env=env,
                       capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr[-500:]
    assert (up / "abc" / "song.mp3").exists() and (out / ".work" / "stem.wav").exists()


def test_clean_temp_files_only_on_explicit_call(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "UPLOADS", tmp_path / "u")
    (tmp_path / "u" / "x").mkdir(parents=True)
    server.clean_temp_files()
    assert server.UPLOADS.exists() and not any(server.UPLOADS.iterdir())


def test_second_instance_detects_port_in_use():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        assert server.port_in_use(port)
    assert not server.port_in_use(port)


def test_server_only_listens_on_localhost():
    src = Path(server.__file__).read_text(encoding="utf-8")
    assert 'os.environ.get("AUDIO_STUDIO_HOST", "127.0.0.1")' in src and "host=HOST" in src
    assert "0.0.0.0" not in src  # noqa: S104 - asserting it is NOT used; only the Docker image opts in
    if "AUDIO_STUDIO_HOST" not in os.environ:
        assert server.HOST == "127.0.0.1"


def test_web_mode_disables_open_folder(client, monkeypatch):
    opened = []
    monkeypatch.setattr(server.os, "startfile", opened.append, raising=False)
    monkeypatch.setattr(server.sys, "platform", "win32")
    monkeypatch.setattr(server, "WEB", True)
    assert client.get("/api/info").json()["web"] is True
    assert client.post("/api/open-folder", json={}).status_code == 404 and not opened


# ------------------------------------------------------------------ uploads
class TestUpload:
    def test_valid_audio(self, client, fixtures):
        r = upload(client, fixtures["tone_mp3"])
        assert r.status_code == 200
        j = r.json()
        assert len(j["id"]) == 12 and j["name"] == "tone.mp3" and abs(j["duration"] - 5) < 0.1 and j["size"] > 0
        assert Path(server.uploads[j["id"]]).is_relative_to(server.UPLOADS)

    def test_video_is_accepted(self, client, fixtures):
        assert upload(client, fixtures["video_mp4"]).status_code == 200

    @pytest.mark.parametrize("key", ["spoofed_mp3", "png_as_wav"])
    def test_mime_spoofing_is_rejected(self, client, fixtures, key):
        r = upload(client, fixtures[key])
        assert r.status_code == 400 and "not a readable audio file" in r.json()["detail"]
        assert not any(Path(p).name == fixtures[key].name for p in server.uploads.values())

    def test_empty_file(self, client, fixtures):
        r = upload(client, fixtures["empty"])
        assert r.status_code == 400 and "empty" in r.json()["detail"]

    def test_size_limit(self, client, fixtures, monkeypatch):
        monkeypatch.setattr(server, "MAX_UPLOAD", 10_000)
        before = set(server.UPLOADS.iterdir())
        r = upload(client, fixtures["tone_wav"])  # ~880 KB
        assert r.status_code == 413
        assert set(server.UPLOADS.iterdir()) == before, "rejected upload left files behind"

    @pytest.mark.parametrize("evil", ["../../evil.wav", "..\\..\\evil.wav", "C:\\Windows\\evil.wav", "/etc/evil.wav"])
    def test_path_traversal_filename_is_neutralised(self, client, fixtures, evil):
        r = upload(client, fixtures["tone_wav"], name=evil)
        assert r.status_code == 200
        stored = Path(server.uploads[r.json()["id"]]).resolve()
        assert stored.name == "evil.wav" and server.UPLOADS.resolve() in stored.parents

    def test_zero_length_audio_is_rejected(self, client, fixtures, monkeypatch):
        monkeypatch.setattr(engine, "duration", lambda p: 0.0)
        r = upload(client, fixtures["tone_wav"])
        assert r.status_code == 400 and "contains no audio" in r.json()["detail"]

    def test_missing_file_field(self, client):
        assert client.post("/api/upload").status_code == 422

    def test_delete_upload(self, client, fixtures):
        uid = upload(client, fixtures["tone_wav"]).json()["id"]
        folder = Path(server.uploads[uid]).parent
        assert client.delete(f"/api/uploads/{uid}").status_code == 200
        assert not folder.exists() and uid not in server.uploads
        assert client.delete(f"/api/uploads/{uid}").status_code == 404


# ------------------------------------------------------------------ jobs
class TestJobs:
    def test_unknown_tool(self, client):
        assert client.post("/api/jobs", json={"tool": "rm -rf", "params": {}}).status_code == 400

    def test_missing_upload(self, client):
        r = client.post("/api/jobs", json={"tool": "cut", "params": {}})
        assert r.status_code == 400 and "upload" in r.json()["detail"].lower()

    def test_unknown_upload_id(self, client):
        assert client.post("/api/jobs", json={"tool": "cut", "params": {"upload": "nope"}}).status_code == 400

    def test_params_must_be_object(self, client):
        assert client.post("/api/jobs", json={"tool": "cut", "params": [1, 2]}).status_code == 400

    def test_raw_file_paths_cannot_be_injected(self, client, fixtures):
        r = client.post("/api/jobs", json={"tool": "convert", "params": {"file": str(fixtures["tone_wav"])}})
        assert r.status_code == 400  # 'file' is stripped; an upload id is required

    def test_join_requires_list(self, client):
        assert client.post("/api/jobs", json={"tool": "join", "params": {"uploads": "x"}}).status_code == 400

    def test_unknown_job(self, client):
        assert client.get("/api/jobs/doesnotexist").status_code == 404

    def test_full_lifecycle_cut(self, client, fixtures):
        uid = upload(client, fixtures["tone_wav"]).json()["id"]
        r = client.post("/api/jobs", json={"tool": "cut", "params": {"upload": uid, "start": 1, "end": 2, "format": "mp3"}})
        first = client.get(f"/api/jobs/{r.json()['id']}").json()
        assert first["status"] in ("queued", "running", "done")
        j = wait(client, r.json()["id"])
        assert j["status"] == "done" and j["progress"] == 1.0 and j["stage"] == "Done" and j["elapsed"] >= 0
        f = j["result"]["files"][0]
        assert f["name"].endswith(".mp3") and len(f["peaks"]) == 600 and f["size"] > 0
        dl = client.get(f["url"])
        assert dl.status_code == 200 and len(dl.content) == f["size"]

    @pytest.mark.parametrize("tool,params", [
        ("analyze", {}), ("pitch", {"semitones": -2, "format": "mp3"}),
        ("pitch", {"tempo": 85, "lofi": 55, "echo_delay": 350, "echo_feedback": 30, "echo_mix": 25, "format": "wav"}),
        ("convert", {"format": "ogg"}),
        ("cut", {"start": 0, "end": 1, "format": "flac"}),
    ])
    def test_every_file_tool(self, client, fixtures, tool, params):
        uid = upload(client, fixtures["a_major"]).json()["id"]
        j = run(client, tool, {"upload": uid, **params})
        assert j["status"] == "done", j.get("error")
        if tool == "analyze":
            assert j["result"]["analysis"]["key"] == "A major"
        else:
            assert client.get(j["result"]["files"][0]["url"]).status_code == 200

    @pytest.mark.parametrize("fmt", engine.FORMATS)
    def test_every_format_in_worker_thread(self, client, fixtures, fmt):
        """Regression: OGG encoding used to overflow the worker thread's stack and kill the server."""
        uid = upload(client, fixtures["tone_wav"]).json()["id"]
        j = run(client, "convert", {"upload": uid, "format": fmt})
        assert j["status"] == "done", j.get("error")
        assert j["result"]["files"][0]["name"].endswith("." + fmt)

    def test_join(self, client, fixtures):
        ids = [upload(client, fixtures[k]).json()["id"] for k in ("tone_wav", "tone_mp3")]
        j = run(client, "join", {"uploads": ids, "crossfade": 1, "format": "wav"})
        assert j["status"] == "done"
        assert abs(engine.duration(j["result"]["files"][0]["path"]) - 9) < 0.1

    def test_validation_error_is_reported_on_job(self, client, fixtures):
        uid = upload(client, fixtures["tone_wav"]).json()["id"]
        j = run(client, "cut", {"upload": uid, "start": 4, "end": 1})
        assert j["status"] == "error" and "Start must be before end" in j["error"]

    def test_unexpected_exception_is_reported(self, client, fixtures, monkeypatch):
        def boom(p, report):
            raise RuntimeError("kaboom")
        monkeypatch.setitem(engine.TOOLS, "convert", boom)
        uid = upload(client, fixtures["tone_wav"]).json()["id"]
        j = run(client, "convert", {"upload": uid})
        assert j["status"] == "error" and "kaboom" in j["error"]

    def test_mix_rejects_foreign_paths(self, client, fixtures):
        j = run(client, "mix", {"files": {"vocals": str(fixtures["tone_wav"])}, "volumes": {"vocals": 100}})
        assert j["status"] == "error" and "Invalid stem" in j["error"]

    def test_mix_from_real_stems(self, client, fixtures):
        uid = upload(client, fixtures["tone_wav"]).json()["id"]
        a = run(client, "convert", {"upload": uid, "format": "wav"})["result"]["files"][0]["path"]
        j = run(client, "mix", {"files": {"vocals": a}, "volumes": {"vocals": 50}, "format": "wav"})
        assert j["status"] == "done" and j["result"]["files"][0]["key"] == "custom_mix"

    def test_jobs_run_one_at_a_time_in_order(self, client, fixtures, monkeypatch):
        log, lock = [], threading.Lock()

        def slow(p, report):
            with lock:
                log.append(("start", p["n"]))
            for i in range(5):
                report(i / 5, "working")
                time.sleep(0.05)
            with lock:
                log.append(("end", p["n"]))
            return {"files": []}
        monkeypatch.setitem(engine.TOOLS, "mix", slow)
        ids = [client.post("/api/jobs", json={"tool": "mix", "params": {"n": n}}).json()["id"] for n in range(3)]
        queued = client.get(f"/api/jobs/{ids[2]}").json()
        assert queued["status"] in ("queued", "running")
        for jid in ids:
            assert wait(client, jid)["status"] == "done"
        assert log == [("start", 0), ("end", 0), ("start", 1), ("end", 1), ("start", 2), ("end", 2)]

    def test_progress_is_monotonic_and_has_eta(self, client, monkeypatch):
        def steady(p, report):
            for i in range(1, 30):
                report(i / 30, f"step {i}")
                time.sleep(0.03)
            return {"files": []}
        monkeypatch.setitem(engine.TOOLS, "mix", steady)
        jid = client.post("/api/jobs", json={"tool": "mix", "params": {}}).json()["id"]
        seen, etas = [], []
        while True:
            j = client.get(f"/api/jobs/{jid}").json()
            seen.append(j["progress"])
            if j["eta"] is not None:
                etas.append(j["eta"])
            if j["status"] == "done":
                break
            time.sleep(0.02)
        assert seen == sorted(seen) and seen[-1] == 1.0
        assert len(set(seen)) > 5, "progress should update many times"
        assert etas, "an ETA should be reported once work is under way"

    def test_instant_progress_updates_do_not_crash(self, client, monkeypatch):
        """Regression: two reports in the same clock tick divided by zero (found by the user in Pitch & Tempo)."""
        def instant(p, report):
            for f in (0.05, 0.1, 0.5, 0.9, 0.95):
                report(f, "fast")
            return {"files": []}
        monkeypatch.setitem(engine.TOOLS, "mix", instant)
        monkeypatch.setattr(server.time, "perf_counter", lambda: 1000.0)  # frozen clock = worst case
        for _ in range(5):
            jid = client.post("/api/jobs", json={"tool": "mix", "params": {}}).json()["id"]
            j = wait(client, jid)
            assert j["status"] == "done", j.get("error")

    def test_pitch_with_no_change_completes(self, client, fixtures):
        uid = upload(client, fixtures["tone_wav"]).json()["id"]
        for _ in range(3):
            j = run(client, "pitch", {"upload": uid, "semitones": 0, "tempo": 100, "format": "mp3"})
            assert j["status"] == "done", j.get("error")

    def test_progress_never_goes_backwards(self, client, monkeypatch):
        seen = []

        def jumpy(p, report):
            running = next(j for j in server.jobs.values() if j["status"] == "running")
            report(0.5, "a")
            seen.append(running["progress"])
            report(0.2, "b")  # e.g. a second model pass restarting its own bar
            seen.append(running["progress"])
            return {"files": []}
        monkeypatch.setitem(engine.TOOLS, "mix", jumpy)
        jid = client.post("/api/jobs", json={"tool": "mix", "params": {}}).json()["id"]
        assert wait(client, jid)["status"] == "done"
        assert seen == [0.5, 0.5]

    def test_finished_jobs_are_pruned(self, client, monkeypatch):
        monkeypatch.setattr(server, "MAX_JOBS_KEPT", 3)
        monkeypatch.setitem(engine.TOOLS, "mix", lambda p, r: {"files": []})
        ids = [client.post("/api/jobs", json={"tool": "mix", "params": {}}).json()["id"] for _ in range(6)]
        for jid in ids[-1:]:
            wait(client, jid)
        client.post("/api/jobs", json={"tool": "mix", "params": {}})
        assert len(server.jobs) <= 3 + 2


# ------------------------------------------------------------------ files & folders
class TestFiles:
    @pytest.mark.parametrize("url", ["/files/../server.py", "/files/..%2F..%2Fserver.py",
                                     "/files/%2e%2e/%2e%2e/server.py", "/static/../server.py"])
    def test_static_path_traversal(self, client, url):
        r = client.get(url)
        assert r.status_code in (400, 404) and "import" not in r.text

    def test_open_folder_outside_output_is_refused(self, client, monkeypatch):
        opened = []
        monkeypatch.setattr(server.os, "startfile", opened.append, raising=False)
        r = client.post("/api/open-folder", json={"path": "C:\\Windows"})
        assert r.status_code == 400 and not opened
        r = client.post("/api/open-folder", json={"path": str(engine.OUT / ".." / "..")})
        assert r.status_code == 400 and not opened

    def test_open_output_folder(self, client, monkeypatch):
        opened = []
        monkeypatch.setattr(server.os, "startfile", opened.append, raising=False)
        monkeypatch.setattr(server.sys, "platform", "win32")  # Explorer is only opened on Windows (CI runs Linux)
        assert client.post("/api/open-folder", json={}).status_code == 200
        assert Path(opened[0]).resolve() == engine.OUT.resolve()


# ------------------------------------------------------------------ GPU memory release
class FakeWorker:
    def __init__(self, alive=True):
        self.alive, self.stops = alive, 0

    def stop(self):
        self.stops += 1
        was, self.alive = self.alive, False
        return was


class TestGpuRelease:
    @pytest.fixture
    def fw(self, monkeypatch):
        w = FakeWorker()
        monkeypatch.setattr(server, "worker", w)
        monkeypatch.setattr(server, "IDLE_UNLOAD_S", 300)
        return w

    def test_release_endpoint(self, client, fw):
        r = client.post("/api/release-gpu")
        assert r.status_code == 200 and r.json() == {"released": True} and fw.stops == 1
        assert client.post("/api/release-gpu").json() == {"released": False}

    def test_idle_app_releases_gpu(self, fw, monkeypatch):
        monkeypatch.setattr(server, "_last_activity", [0.0])
        assert server.release_if_idle(now=301.0) is True and fw.stops == 1

    def test_recent_activity_keeps_model_warm(self, fw, monkeypatch):
        monkeypatch.setattr(server, "_last_activity", [0.0])
        assert server.release_if_idle(now=299.0) is False and fw.stops == 0

    def test_never_unloads_during_a_job(self, fw, monkeypatch):
        monkeypatch.setattr(server, "_last_activity", [0.0])
        monkeypatch.setitem(server.jobs, "busy", {"status": "running"})
        assert server.release_if_idle(now=10_000.0) is False and fw.stops == 0

    def test_nothing_to_release(self, fw, monkeypatch):
        fw.alive = False
        monkeypatch.setattr(server, "_last_activity", [0.0])
        assert server.release_if_idle(now=10_000.0) is False and fw.stops == 0

    def test_finishing_a_job_counts_as_activity(self, client, monkeypatch):
        monkeypatch.setitem(engine.TOOLS, "mix", lambda p, r: {"files": []})
        before = server._last_activity[0]
        wait(client, client.post("/api/jobs", json={"tool": "mix", "params": {}}).json()["id"])
        assert server._last_activity[0] > before

    def test_separation_goes_through_worker(self, client, fixtures, monkeypatch):
        seen = {}

        class W(FakeWorker):
            def run(self, tool, params, report, user_error=Exception):
                seen.update(tool=tool, params=params)
                report(0.5, "Extracting")
                return {"folder": str(engine.OUT), "files": []}
        monkeypatch.setattr(server, "worker", W())
        uid = upload(client, fixtures["tone_wav"]).json()["id"]
        j = run(client, "separate", {"upload": uid, "engine": "bs_roformer"})
        assert j["status"] == "done" and seen["tool"] == "separate"
        assert seen["params"]["file"].endswith("tone 440.wav")

    def test_worker_crash_is_reported_not_fatal(self, client, fixtures, monkeypatch):
        from gpu_worker import WorkerCrashed

        class W(FakeWorker):
            def run(self, *a, **k):
                raise WorkerCrashed("The AI engine stopped unexpectedly (exit code -9). Please try again.")
        monkeypatch.setattr(server, "worker", W())
        uid = upload(client, fixtures["tone_wav"]).json()["id"]
        j = run(client, "separate", {"upload": uid})
        assert j["status"] == "error" and "stopped unexpectedly" in j["error"]
        assert client.get("/api/info").status_code == 200  # server still alive


# ------------------------------------------------------------------ light load test
def test_concurrent_requests(client, fixtures):
    """Stand-in for a Locust run: the app serves one local user, so 50 parallel requests is ample."""
    def hit(i):
        t = time.perf_counter()
        r = client.get("/api/info") if i % 2 else upload(client, fixtures["tone_mp3"])
        return r.status_code, time.perf_counter() - t
    with ThreadPoolExecutor(10) as ex:
        res = list(ex.map(hit, range(50)))
    assert all(code == 200 for code, _ in res)
    lat = sorted(t for _, t in res)
    assert lat[int(len(lat) * 0.95)] < 5.0, f"p95 latency {lat[int(len(lat) * 0.95)]:.2f}s"
