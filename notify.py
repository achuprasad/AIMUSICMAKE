"""E-mail notifications for new feedback.

Configuration comes ONLY from environment variables (or a private, git-ignored .env file
loaded by server.py). Recipient addresses and SMTP credentials are never sent to the
browser, never logged, and never committed. See docs/support-and-feedback.md.

    FEEDBACK_NOTIFY_TO      comma-separated recipient addresses (kept private)
    SMTP_HOST, SMTP_PORT    e.g. smtp.gmail.com / 465
    SMTP_SECURITY           ssl (port 465) | starttls (port 587) | none (only allowed for localhost testing)
    SMTP_USER, SMTP_PASSWORD   login; for Gmail use an "App password", never the account password
    SMTP_FROM               sender address (defaults to SMTP_USER)
    FEEDBACK_MAX_EMAILS_PER_HOUR   cap so nobody can flood the inbox (default 30)
"""
import logging
import os
import re
import smtplib
import ssl
import threading
import time
from collections import deque
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

log = logging.getLogger("notify")
ADDR_RE = re.compile(r"^[^@\s,;<>\"]{1,64}@[^@\s,;<>\"]{1,190}\.[A-Za-z]{2,24}$")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _one_line(s, limit):
    """Header-safe: no CR/LF or control characters (prevents e-mail header injection)."""
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(s or "")).strip()
    return s[:limit]


class MailerConfigError(Exception):
    pass


class Mailer:
    def __init__(self, host="", port=465, security="ssl", user="", password="", sender="", to=(),
                 max_per_hour=30, timeout=20):
        self.host, self.port, self.security = host.strip(), int(port), security.strip().lower()
        self.user, self.password = user.strip(), password
        self.sender = (sender or user).strip()
        self.to = [a.strip() for a in to if a and a.strip()]
        self.max_per_hour, self.timeout = int(max_per_hour), timeout
        self.sent: deque[float] = deque()
        self.lock = threading.Lock()
        if self.enabled:
            self._check()

    @classmethod
    def from_env(cls, env=None):
        e = os.environ if env is None else env
        return cls(host=e.get("SMTP_HOST", ""), port=e.get("SMTP_PORT", "465") or 465,
                   security=e.get("SMTP_SECURITY", "ssl") or "ssl", user=e.get("SMTP_USER", ""),
                   password=e.get("SMTP_PASSWORD", ""), sender=e.get("SMTP_FROM", ""),
                   to=e.get("FEEDBACK_NOTIFY_TO", "").replace(";", ",").split(","),
                   max_per_hour=e.get("FEEDBACK_MAX_EMAILS_PER_HOUR", "30") or 30)

    @property
    def enabled(self):
        # a login name without its password means "not set up yet": don't claim e-mail is on
        return bool(self.host and self.to and self.sender and (not self.user or self.password))

    def _check(self):
        bad = [a for a in [*self.to, self.sender] if not ADDR_RE.match(a)]
        if bad:
            raise MailerConfigError(f"{len(bad)} invalid e-mail address(es) in the mail settings")
        if self.security not in ("ssl", "starttls", "none"):
            raise MailerConfigError("SMTP_SECURITY must be ssl, starttls or none")
        if self.security == "none" and self.host not in LOCAL_HOSTS:
            raise MailerConfigError("Unencrypted SMTP is only allowed to localhost")

    def build(self, row):
        kind = {"feature": "Feature request", "suggestion": "Suggestion", "bug": "Bug report",
                "question": "Question"}.get(row.get("category"), "Feedback")
        msg = EmailMessage()
        msg["Subject"] = _one_line(f"[Local Audio Studio] {kind}: {row.get('title', '')}", 160)
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.to)
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="local-audio-studio")
        if row.get("email"):  # user gave consent and a validated address: reply goes straight to them
            msg["Reply-To"] = row["email"]
        diag = row.get("diagnostics") or {}
        lines = [
            f"Reference: {row.get('id')}",
            f"Received:  {row.get('created')}",
            f"Type:      {kind}",
            f"Area:      {row.get('tool')}",
            f"Rating:    {row.get('rating') or '-'} / 5",
            f"Reply to:  {row.get('email') or '(no e-mail given)'}",
            "",
            f"Title: {_one_line(row.get('title'), 200)}",
            "",
            str(row.get("message", "")),
            "",
            "--- technical details (sent with the user's permission) ---" if diag else "--- no technical details ---",
            *[f"{k}: {v}" for k, v in diag.items()],
        ]
        msg.set_content("\n".join(lines))  # plain text only: nothing in it can execute in a mail client
        return msg

    def _allow(self, now):
        with self.lock:
            while self.sent and now - self.sent[0] > 3600:
                self.sent.popleft()
            if len(self.sent) >= self.max_per_hour:
                return False
            self.sent.append(now)
            return True

    def send(self, row, now=None):
        """Send one notification. Returns 'sent', 'disabled' or 'capped'; raises on SMTP failure."""
        if not self.enabled:
            return "disabled"
        if not self._allow(time.monotonic() if now is None else now):
            log.warning("feedback e-mail cap reached; %s stored but not e-mailed", row.get("id"))
            return "capped"
        msg = self.build(row)
        ctx = ssl.create_default_context()
        server: smtplib.SMTP
        if self.security == "ssl":
            server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=ctx)
        else:
            server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        with server:
            if self.security == "starttls":
                server.starttls(context=ctx)
            if self.user and self.password:
                server.login(self.user, self.password)
            server.send_message(msg)
        return "sent"

    def send_in_background(self, row, on_done=None, retries=1, delay=5.0):
        """Never blocks the request; one retry on failure. Errors are logged without addresses or secrets."""
        def run():
            result = "failed"
            for attempt in range(retries + 1):
                try:
                    result = self.send(row)
                    break
                except Exception as e:  # noqa: BLE001 - mail failures must never break feedback
                    log.warning("feedback e-mail for %s failed (attempt %d): %s", row.get("id"), attempt + 1,
                                type(e).__name__)
                    if attempt < retries:
                        time.sleep(delay)
            if on_done:
                on_done(row, result)
        t = threading.Thread(target=run, daemon=True, name="feedback-mail")
        t.start()
        return t


def load_env_file(path):
    """Minimal .env reader (KEY=VALUE lines). Never overrides variables already set; returns keys loaded."""
    loaded: list[str] = []
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return loaded
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", k) and k not in os.environ:
            os.environ[k] = v
            loaded.append(k)
    return loaded
