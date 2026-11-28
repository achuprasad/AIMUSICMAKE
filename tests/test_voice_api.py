"""HTTP API of the Malayalam Voice Studio (server.py), with the voice worker's test-only stand-in synthesiser."""
import time

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import server
import voice_profiles as vp

ML = "ഇന്ന് നല്ല കാലാവസ്ഥയാണ്, നമുക്ക് പുറത്ത് നടക്കാൻ പോകാം."


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c
    server.voice.stop()


@pytest.fixture
def speech_wav(tmp_path):
    t = np.arange(24000 * 5) / 24000
    p = tmp_path / "my voice.wav"
    sf.write(p, (0.2 * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t))).astype(np.float32), 24000)
    return p


def upload(client, path):
    with open(path, "rb") as f:
        return client.post("/api/upload", files={"file": (path.name, f, "application/octet-stream")}).json()["id"]


def run(client, tool, params, timeout=120):
    r = client.post("/api/jobs", json={"tool": tool, "params": params})
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    t = time.time()
    while time.time() - t < timeout:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.1)
    raise TimeoutError(jid)


def test_status(client):
    s = client.get("/api/voice/status").json()
    assert s["installed"] and s["language"] == "ml" and s["consent_text"] == vp.CONSENT_TEXT
    assert any("CC-BY-NC" in x for x in s["licences"])


def test_builtin_voices_are_listed(client):
    items = client.get("/api/voice/profiles").json()["items"]
    assert set(vp.BUILTIN) <= {p["id"] for p in items}
    assert all("instruct" not in p and "consent" not in p for p in items)       # internals are not exposed


def test_clone_voice_lifecycle(client, speech_wav):
    server.clone_limiter.events.clear()
    # consent is required
    j = run(client, "voice_profile", {"upload": upload(client, speech_wav), "name": "Me", "transcript": ML})
    assert j["status"] == "error" and "permission" in j["error"]
    # English transcript refused (Malayalam only)
    j = run(client, "voice_profile", {"upload": upload(client, speech_wav), "name": "Me", "transcript": "hello there",
                                      "consent": True})
    assert j["status"] == "error" and "Malayalam" in j["error"]
    up = upload(client, speech_wav)
    j = run(client, "voice_profile", {"upload": up, "name": "Me", "transcript": ML, "consent": True})
    assert j["status"] == "done", j.get("error")
    pid = j["result"]["profile"]["id"]
    assert client.delete(f"/api/uploads/{up}").status_code == 404                # the recording is not kept
    assert not (vp.VOICES / pid / "ref.wav").exists()
    assert "path" not in str(j["result"]["profile"]) and str(vp.VOICES) not in str(j["result"])   # no server paths
    j = run(client, "voice_profile", {"upload": upload(client, speech_wav), "profile": pid, "tone": "sad",
                                      "transcript": ML})
    assert j["status"] == "done" and set(j["result"]["profile"]["tones"]) == {"neutral", "sad"}
    assert client.patch(f"/api/voice/profiles/{pid}", json={"name": "My voice"}).json()["name"] == "My voice"
    assert client.delete(f"/api/voice/profiles/{pid}/tones/sad").json()["tones"].keys() == {"neutral"}
    assert client.delete(f"/api/voice/profiles/{pid}").json() == {"ok": True}
    assert client.get(f"/api/voice/profiles/{pid}").status_code == 404


@pytest.mark.parametrize("pid", ["..%2F..%2Fwindows", "builtin-..", "0123456789ab", "x" * 200])
def test_unknown_or_malicious_ids(client, pid):
    assert client.get(f"/api/voice/profiles/{pid}").status_code in (400, 404)
    assert client.delete(f"/api/voice/profiles/{pid}").status_code in (400, 404)
    assert client.patch(f"/api/voice/profiles/{pid}", json={"name": "x"}).status_code in (400, 404)


def test_builtins_are_protected(client):
    assert client.delete("/api/voice/profiles/builtin-child").status_code == 400
    assert client.delete("/api/voice/profiles/builtin-child/tones/neutral").status_code == 400


def test_profile_job_needs_an_upload(client):
    r = client.post("/api/jobs", json={"tool": "voice_profile", "params": {"name": "x", "consent": True}})
    assert r.status_code == 400
    r = client.post("/api/jobs", json={"tool": "voice_profile", "params": {"upload": "nope", "consent": True}})
    assert r.status_code == 400


def test_clone_rate_limit(client, speech_wav):
    server.clone_limiter.events.clear()
    ups = [upload(client, speech_wav) for _ in range(21)]      # each learned voice deletes its upload
    codes = [client.post("/api/jobs", json={"tool": "voice_profile", "params": {"upload": u, "transcript": ML}}).status_code
             for u in ups]
    assert codes[:20] == [200] * 20 and codes[20] == 429
    assert client.post("/api/jobs", json={"tool": "voice_profile", "params": {"upload": "nope"}}).status_code == 429
    server.clone_limiter.events.clear()


def test_speak_story_and_regenerate_a_line(client):
    j = run(client, "voice", {"script": "അവന്റെ പേര് തീപ്പൊരി!\n[angrily] രാമേട്ടൻ: \"എന്താടാ ഇത്?\"",
                              "cast": {"രാമേട്ടൻ": "builtin-male-adult"}, "format": "mp3"})
    assert j["status"] == "done", j.get("error")
    f = j["result"]["files"][0]
    assert f["name"].endswith(".mp3") and client.get(f["url"]).status_code == 200
    lines = j["result"]["voice"]["lines"]
    assert len(lines) == 2 and all(client.get(ln["url"]).status_code == 200 for ln in lines)
    r = run(client, "voice", {"regenerate": j["id"], "lines": [1]})
    assert r["status"] == "done" and r["result"]["folder"] == j["result"]["folder"]


def test_regenerate_needs_a_finished_voice_job(client):
    r = client.post("/api/jobs", json={"tool": "voice", "params": {"regenerate": "nope", "lines": [0]}})
    assert r.status_code == 400


def test_client_cannot_choose_the_folder(client, tmp_path):
    """'previous' is server-side only: a client-sent path is dropped and a normal new job runs."""
    j = run(client, "voice", {"script": "ശരി.", "previous": str(tmp_path), "lines": [0]})
    assert j["status"] == "done" and str(tmp_path) not in j["result"]["folder"]


def test_english_text_is_refused(client):
    j = run(client, "voice", {"script": "Hello, this should be Malayalam."})
    assert j["status"] == "error" and "Malayalam only" in j["error"]


def test_cancel(client):
    assert client.post("/api/jobs/nope/cancel").status_code == 404
    r = client.post("/api/jobs", json={"tool": "voice", "params": {"script": "\n".join(["ശരി."] * 40)}})
    jid = r.json()["id"]
    assert client.post(f"/api/jobs/{jid}/cancel").json() == {"cancelled": True}
    t = time.time()
    while client.get(f"/api/jobs/{jid}").json()["status"] not in ("done", "error") and time.time() - t < 60:
        time.sleep(0.1)
    j = client.get(f"/api/jobs/{jid}").json()
    assert j["status"] == "error" and ("Stopped" in j["error"] or "Cancelled" in j["error"])
    assert client.post(f"/api/jobs/{jid}/cancel").json() == {"cancelled": False}


def test_cross_site_requests_are_blocked(client):
    evil = {"Origin": "https://evil.example"}
    assert client.delete("/api/voice/profiles/0123456789ab", headers=evil).status_code == 403
    assert client.post("/api/jobs", json={"tool": "voice", "params": {"script": ML}}, headers=evil).status_code == 403


def test_web_mode_disables_the_voice_studio(client, monkeypatch):
    """The Docker web version has no accounts, so nobody may clone or delete voices through it."""
    monkeypatch.setattr(server, "WEB", True)
    s = client.get("/api/voice/status").json()
    assert s["available"] is False and "desktop app only" in s["reason"]
    assert client.get("/api/voice/profiles").status_code == 403
    assert client.delete("/api/voice/profiles/0123456789ab").status_code == 403
    assert client.patch("/api/voice/profiles/0123456789ab", json={"name": "x"}).status_code == 403
    for tool in ("voice", "voice_profile"):
        assert client.post("/api/jobs", json={"tool": tool, "params": {"script": ML}}).status_code == 403
    monkeypatch.setattr(server, "WEB", False)
    assert client.get("/api/voice/status").json()["available"] is True


def test_release_gpu_stops_the_voice_engine(client):
    run(client, "voice", {"script": "ശരി."})
    assert server.voice.alive
    assert client.post("/api/release-gpu").json()["released"] is True and not server.voice.alive
