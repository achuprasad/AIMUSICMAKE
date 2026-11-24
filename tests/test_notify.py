"""E-mail notification tests. A real SMTP conversation runs against a local test server (aiosmtpd);
no message ever leaves this machine."""
import logging
import os
import socket

import pytest

import notify

TO = ["owner.one@example.com", "owner.two@example.org"]
ROW = {"id": "FB-1234ABCD", "created": "2026-11-24T10:00:00", "category": "bug", "tool": "split",
       "title": "Crash when splitting", "message": "It stopped at 92 %.\nSecond line.", "rating": 4,
       "email": "fan@example.com", "diagnostics": {"app_version": "1.0.0", "gpu": "GTX 1650"}}


def mailer(**kw):
    cfg = {"host": "127.0.0.1", "port": 2525, "security": "none", "sender": "bot@example.com", "to": TO}
    cfg.update(kw)
    return notify.Mailer(**cfg)


class TestConfig:
    def test_disabled_without_settings(self):
        m = notify.Mailer.from_env({})
        assert not m.enabled and m.send(ROW) == "disabled"

    def test_from_env(self):
        m = notify.Mailer.from_env({"SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "587", "SMTP_SECURITY": "starttls",
                                    "SMTP_USER": "bot@example.com", "SMTP_PASSWORD": "pw",
                                    "FEEDBACK_NOTIFY_TO": "owner.one@example.com; owner.two@example.org"})
        assert m.enabled and m.to == TO and m.sender == "bot@example.com" and m.port == 587

    @pytest.mark.parametrize("kw", [{"to": ["not-an-address"]}, {"sender": "x@y"}, {"security": "tls13"},
                                    {"host": "smtp.gmail.com", "security": "none"},
                                    {"to": ["a@example.com\nBcc: b@example.com"]}])
    def test_bad_config_rejected(self, kw):
        with pytest.raises(notify.MailerConfigError):
            mailer(**kw)


class TestMessage:
    def test_plain_text_with_everything_needed(self):
        msg = mailer().build(ROW)
        assert msg.get_content_type() == "text/plain" and not msg.is_multipart()
        assert msg["Subject"] == "[Mixlumo] Bug report: Crash when splitting"
        assert msg["To"] == ", ".join(TO) and msg["Reply-To"] == "fan@example.com"
        text = msg.get_content()
        for part in ("FB-1234ABCD", "It stopped at 92 %.", "Second line.", "gpu: GTX 1650", "4 / 5"):
            assert part in text

    def test_no_reply_to_without_email(self):
        assert mailer().build({**ROW, "email": None})["Reply-To"] is None

    def test_header_injection_through_title_is_impossible(self):
        msg = mailer().build({**ROW, "title": "Hi\r\nBcc: victim@example.com\r\nX-Evil: 1"})
        raw = msg.as_string()
        assert "\nBcc:" not in raw and "\nX-Evil:" not in raw
        assert "\n" not in msg["Subject"]

    def test_hourly_cap(self, monkeypatch):
        m = mailer(max_per_hour=2)
        monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
        assert [m.send(ROW, now=t) for t in (0, 1, 2)] == ["sent", "sent", "capped"]
        assert m.send(ROW, now=3601) == "sent"  # window has moved on


class FakeSMTP:
    log: list = []

    def __init__(self, host, port, timeout=None, context=None):
        FakeSMTP.log.append(("connect", host, port, "ssl" if context else "plain"))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        FakeSMTP.log.append(("starttls", context is not None))

    def login(self, user, password):
        FakeSMTP.log.append(("login", user, password))

    def send_message(self, msg):
        FakeSMTP.log.append(("send", msg["To"]))


@pytest.mark.parametrize("security,factory", [("ssl", "SMTP_SSL"), ("starttls", "SMTP")])
def test_encrypted_connection_and_login(monkeypatch, security, factory):
    FakeSMTP.log = []
    monkeypatch.setattr(notify.smtplib, factory, FakeSMTP)
    m = mailer(host="smtp.gmail.com", port=465, security=security, user="bot@example.com", password="app-pw")
    assert m.send(ROW) == "sent"
    steps = [e[0] for e in FakeSMTP.log]
    assert steps == (["connect", "login", "send"] if security == "ssl" else ["connect", "starttls", "login", "send"])
    assert ("login", "bot@example.com", "app-pw") in FakeSMTP.log


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_real_smtp_conversation_with_local_test_server():
    from aiosmtpd.controller import Controller
    from aiosmtpd.handlers import Sink

    got = []

    class Capture(Sink):
        async def handle_DATA(self, server, session, envelope):
            got.append((envelope.mail_from, list(envelope.rcpt_tos), envelope.content.decode()))
            return "250 OK"

    port = _free_port()
    ctl = Controller(Capture(), hostname="127.0.0.1", port=port)
    ctl.start()
    try:
        assert mailer(port=port).send(ROW) == "sent"
    finally:
        ctl.stop()
    assert len(got) == 1
    mail_from, rcpts, content = got[0]
    assert mail_from == "bot@example.com" and sorted(rcpts) == sorted(TO)  # both owners receive it
    assert "Crash when splitting" in content and "FB-1234ABCD" in content


def test_background_send_retries_then_reports(monkeypatch, caplog):
    m = mailer(user="bot@example.com", password="super-secret-pw")
    attempts = []

    def flaky(row, now=None):
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError(f"connection refused while talking to {m.to[0]} with {m.password}")
        return "sent"
    monkeypatch.setattr(m, "send", flaky)
    done = []
    with caplog.at_level(logging.WARNING, logger="notify"):
        m.send_in_background(ROW, on_done=lambda r, res: done.append(res), delay=0.01).join(5)
    assert done == ["sent"] and len(attempts) == 2
    assert "super-secret-pw" not in caplog.text and TO[0] not in caplog.text  # logs never leak secrets


def test_background_send_gives_up_without_crashing(monkeypatch):
    m = mailer()
    monkeypatch.setattr(m, "send", lambda row, now=None: (_ for _ in ()).throw(TimeoutError()))
    done = []
    m.send_in_background(ROW, on_done=lambda r, res: done.append(res), retries=1, delay=0.01).join(5)
    assert done == ["failed"]


class TestEnvFile:
    def test_loads_without_overriding(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "already-set")
        monkeypatch.delenv("FEEDBACK_NOTIFY_TO", raising=False)
        monkeypatch.delenv("SMTP_PORT", raising=False)
        p = tmp_path / ".env"
        p.write_text('# comment\nSMTP_HOST=from-file\nFEEDBACK_NOTIFY_TO="a@example.com,b@example.com"\n'
                     "bad key=1\nlowercase=2\nSMTP_PORT=587\n", encoding="utf-8")
        loaded = notify.load_env_file(p)
        assert sorted(loaded) == ["FEEDBACK_NOTIFY_TO", "SMTP_PORT"]
        assert os.environ["SMTP_HOST"] == "already-set" and os.environ["FEEDBACK_NOTIFY_TO"] == "a@example.com,b@example.com"

    def test_missing_file(self, tmp_path):
        assert notify.load_env_file(tmp_path / "nope.env") == []


def test_secrets_are_never_committed():
    """The private .env must be git-ignored; the public .env.example must hold no address or credential."""
    import re
    root = os.path.dirname(os.path.dirname(__file__))
    gi = open(os.path.join(root, ".gitignore"), encoding="utf-8").read().splitlines()
    assert ".env" in gi
    example = open(os.path.join(root, ".env.example"), encoding="utf-8").read()
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", example), "no e-mail addresses in the public template"
    for line in example.splitlines():
        if line.startswith(("SMTP_PASSWORD=", "SMTP_USER=", "SMTP_FROM=", "FEEDBACK_NOTIFY_TO=")):
            assert line.split("=", 1)[1].strip() == "", line
