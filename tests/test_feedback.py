"""Feedback, roadmap votes, request guards and privacy of the notification addresses."""
import json
import threading

import pytest
from fastapi.testclient import TestClient

import feedback
import notify
import server
from feedback import FeedbackError

CLIENT = "test-client-0001"
SECRET_TO = ["owner.one@example.com", "owner.two@example.org"]


def body(**kw):
    b = {"category": "feature", "tool": "general", "title": "Add noise removal",
         "message": "Please add noise removal for podcasts.", "client": CLIENT}
    b.update(kw)
    return b


@pytest.fixture(autouse=True)
def fresh_state(tmp_path, monkeypatch):
    """Each test gets its own store, fresh rate limits and e-mail switched off."""
    monkeypatch.setattr(server, "feedback_store", feedback.LocalStore(tmp_path / "fb.jsonl"))
    monkeypatch.setattr(server, "feedback_limiter", feedback.RateLimiter(5, 600))
    monkeypatch.setattr(server, "ip_limiter", feedback.RateLimiter(20, 600))
    monkeypatch.setattr(server, "vote_limiter", feedback.RateLimiter(60, 600))
    monkeypatch.setattr(server, "mailer", notify.Mailer())


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


# ------------------------------------------------------------------ validation (unit)
class TestValidate:
    def test_minimal_valid(self):
        r = feedback.validate(body())
        assert r["category"] == "feature" and r["email"] is None and r["diagnostics"] == {}

    @pytest.mark.parametrize("cat", list(feedback.CATEGORIES))
    def test_every_category(self, cat):
        assert feedback.validate(body(category=cat))["category"] == cat

    @pytest.mark.parametrize("bad", [
        {"category": "spam"}, {"tool": "../etc"}, {"title": "ab"}, {"title": "x" * 121},
        {"message": "too short"}, {"message": "x" * 5001}, {"title": 123}, {"client": "bad id!"},
        {"client": ""}, {"rating": 6}, {"rating": 0}, {"rating": True}, {"rating": "5"}, {"diagnostics": "x"},
    ])
    def test_rejects(self, bad):
        with pytest.raises(FeedbackError):
            feedback.validate(body(**bad))

    def test_not_a_dict(self):
        with pytest.raises(FeedbackError):
            feedback.validate(["x"])

    def test_control_characters_are_stripped(self):
        r = feedback.validate(body(title="Hi\x00\x07 there\x1b", message="line1\r\nline2\x00 ok ok"))
        assert r["title"] == "Hi there" and r["message"] == "line1\nline2 ok ok"

    def test_email_needs_consent(self):
        with pytest.raises(FeedbackError, match="consent"):
            feedback.validate(body(email="me@example.com"))
        assert feedback.validate(body(email="me@example.com", contact_consent=True))["email"] == "me@example.com"

    @pytest.mark.parametrize("email", ["not-an-email", "a@b", "me@example.com\nBcc: victim@example.com",
                                       "me@example.com,other@example.com", "<me@example.com>", "x" * 300 + "@a.com"])
    def test_bad_or_injected_email(self, email):
        with pytest.raises(FeedbackError):
            feedback.validate(body(email=email, contact_consent=True))

    def test_diagnostics_allowlist_and_truncation(self):
        r = feedback.validate(body(diagnostics={"user_agent": "U" * 999, "gpu": "GTX", "path": "C:/secret",
                                                "cookie": "abc"}))
        assert set(r["diagnostics"]) == {"user_agent", "gpu"} and len(r["diagnostics"]["user_agent"]) == 300


def test_rate_limiter_window():
    rl = feedback.RateLimiter(limit=2, window=10)
    rl.hit("k", now=0)
    rl.hit("k", now=1)
    with pytest.raises(feedback.RateLimited):
        rl.hit("k", now=2)
    rl.hit("other", now=2)  # independent keys
    rl.hit("k", now=11)     # window passed


# ------------------------------------------------------------------ storage (unit)
class TestStore:
    def test_own_submissions_only_newest_first(self, tmp_path):
        s = feedback.LocalStore(tmp_path / "f.jsonl")
        a = s.add_feedback(feedback.validate(body(title="first one")))
        s.add_feedback(feedback.validate(body(client="someone-else-01")))
        b = s.add_feedback(feedback.validate(body(title="second one")))
        assert [r["id"] for r in s.list_feedback(CLIENT)] == [b["id"], a["id"]]
        assert a["id"].startswith("FB-") and a["status"] == "received"

    def test_persists_and_survives_a_damaged_line(self, tmp_path):
        p = tmp_path / "f.jsonl"
        feedback.LocalStore(p).add_feedback(feedback.validate(body()))
        with open(p, "a", encoding="utf-8") as f:
            f.write("{not json\n")
        assert len(feedback.LocalStore(p).list_feedback(CLIENT)) == 1

    def test_votes_latest_wins(self, tmp_path):
        s = feedback.LocalStore(tmp_path / "f.jsonl")
        s.set_vote("noise-removal", CLIENT, True)
        s.set_vote("noise-removal", CLIENT, True)  # double click: still one vote
        s.set_vote("noise-removal", "client-two-0002", True)
        items = {i["id"]: i for i in feedback.roadmap_with_votes(s, CLIENT)}
        assert items["noise-removal"]["votes"] == 2 and items["noise-removal"]["voted"]
        s.set_vote("noise-removal", CLIENT, False)
        items = {i["id"]: i for i in feedback.roadmap_with_votes(s, CLIENT)}
        assert items["noise-removal"]["votes"] == 1 and not items["noise-removal"]["voted"]

    def test_concurrent_writes_do_not_corrupt(self, tmp_path):
        s = feedback.LocalStore(tmp_path / "f.jsonl")
        rec = feedback.validate(body())
        ts = [threading.Thread(target=lambda: [s.add_feedback(rec) for _ in range(10)]) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        lines = (tmp_path / "f.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 80 and all(json.loads(x)["type"] == "feedback" for x in lines)


# ------------------------------------------------------------------ API
class TestFeedbackApi:
    def test_submit_and_list_own(self, client):
        r = client.post("/api/feedback", json=body())
        assert r.status_code == 201
        j = r.json()
        assert j["id"].startswith("FB-") and j["delivery"] == "local"
        items = client.get("/api/feedback", params={"client": CLIENT}).json()["items"]
        assert [i["id"] for i in items] == [j["id"]]
        assert "client" not in items[0] and "email" not in items[0] and "diagnostics" not in items[0]
        assert client.get("/api/feedback", params={"client": "another-client-9"}).json()["items"] == []

    def test_validation_error(self, client):
        r = client.post("/api/feedback", json=body(message="short"))
        assert r.status_code == 400 and "characters" in r.json()["detail"]

    def test_list_requires_valid_client(self, client):
        assert client.get("/api/feedback", params={"client": "../x"}).status_code == 400

    def test_rate_limit_per_client(self, client):
        for _ in range(5):
            assert client.post("/api/feedback", json=body()).status_code == 201
        r = client.post("/api/feedback", json=body())
        assert r.status_code == 429 and "Too many" in r.json()["detail"]

    def test_rate_limit_per_ip_even_with_new_client_ids(self, client):
        codes = [client.post("/api/feedback", json=body(client=f"rotating-client-{i:04d}")).status_code
                 for i in range(21)]
        assert codes[:20] == [201] * 20 and codes[20] == 429

    def test_honeypot_drops_bots_silently(self, client, monkeypatch):
        sent = []
        monkeypatch.setattr(server.mailer, "send_in_background", lambda *a, **k: sent.append(a))
        r = client.post("/api/feedback", json=body(website="http://spam.example"))
        assert r.status_code == 201 and r.json()["id"].startswith("FB-")
        assert client.get("/api/feedback", params={"client": CLIENT}).json()["items"] == [] and not sent

    def test_script_payload_is_stored_as_plain_text(self, client):
        evil = '<img src=x onerror="alert(1)"> <script>alert(2)</script>'
        client.post("/api/feedback", json=body(title="XSS test title", message=evil))
        item = client.get("/api/feedback", params={"client": CLIENT}).json()["items"][0]
        assert item["message"] == evil  # stored verbatim; the UI renders it as text (see e2e XSS test)


class TestEmailDelivery:
    @pytest.fixture
    def mail(self, monkeypatch):
        m = notify.Mailer(host="smtp.example.com", port=465, security="ssl", user="bot@example.com",
                          password="app-password-123", to=SECRET_TO)
        calls = []
        monkeypatch.setattr(m, "send_in_background", lambda row, on_done=None: calls.append((row, on_done)))
        monkeypatch.setattr(server, "mailer", m)
        return calls

    def test_new_feedback_is_emailed(self, client, mail):
        r = client.post("/api/feedback", json=body(email="fan@example.com", contact_consent=True))
        assert r.status_code == 201 and r.json()["delivery"] == "email"
        row, on_done = mail[0]
        assert row["id"] == r.json()["id"] and row["email"] == "fan@example.com"
        on_done(row, "sent")  # the delivery result is recorded for auditing
        events = [json.loads(x) for x in server.feedback_store.path.read_text(encoding="utf-8").splitlines()]
        assert {"type": "notify", "id": row["id"], "result": "sent"}.items() <= events[-1].items()

    def test_recipient_addresses_never_reach_the_browser(self, client, mail):
        texts = [client.get("/api/support").text, client.get("/").text,
                 client.post("/api/feedback", json=body()).text,
                 client.get("/api/feedback", params={"client": CLIENT}).text,
                 client.get("/api/support/roadmap", params={"client": CLIENT}).text, client.get("/api/info").text]
        for t in texts:
            for secret in [*SECRET_TO, "app-password-123", "smtp.example.com", "bot@example.com"]:
                assert secret not in t
        assert client.get("/api/support").json()["delivery"] == "email"


class TestRoadmapApi:
    def test_list_and_vote(self, client):
        items = client.get("/api/support/roadmap", params={"client": CLIENT}).json()["items"]
        assert len(items) == len(feedback.ROADMAP) and all(i["votes"] == 0 for i in items)
        r = client.post("/api/support/roadmap/timeline-editor/vote", json={"client": CLIENT, "on": True}).json()
        assert r["votes"] == 1 and r["voted"] is True
        r = client.post("/api/support/roadmap/timeline-editor/vote", json={"client": CLIENT, "on": False}).json()
        assert r["votes"] == 0 and r["voted"] is False

    def test_unknown_item_and_bad_client(self, client):
        assert client.post("/api/support/roadmap/hack/vote", json={"client": CLIENT}).status_code == 404
        assert client.post("/api/support/roadmap/assistant/vote", json={"client": "x"}).status_code == 400

    def test_garbage_client_param_is_ignored(self, client):
        assert client.get("/api/support/roadmap", params={"client": "<script>"}).status_code == 200


# ------------------------------------------------------------------ request guards (whole app)
class TestGuards:
    @pytest.mark.parametrize("path,payload", [
        ("/api/feedback", body()), ("/api/jobs", {"tool": "mix", "params": {}}), ("/api/release-gpu", {}),
        ("/api/support/roadmap/assistant/vote", {"client": CLIENT}), ("/api/open-folder", {}),
    ])
    @pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Origin": "null"},
                                         {"Sec-Fetch-Site": "cross-site"}])
    def test_cross_site_writes_are_blocked(self, client, path, payload, headers):
        r = client.post(path, json=payload, headers=headers)
        assert r.status_code == 403 and "Cross-site" in r.json()["detail"]

    def test_same_origin_is_allowed(self, client):
        r = client.post("/api/feedback", json=body(),
                        headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"})
        assert r.status_code == 201

    def test_configured_extra_origin_is_allowed(self, client, monkeypatch):
        monkeypatch.setattr(server, "EXTRA_ORIGINS", {"https://app.example.com"})
        assert client.post("/api/feedback", json=body(), headers={"Origin": "https://app.example.com"}).status_code == 201

    def test_oversized_body_is_rejected(self, client):
        r = client.post("/api/feedback", content=b"{" + b" " * (70 * 1024) + b"}",
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 413

    def test_security_headers(self, client):
        h = client.get("/").headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"
