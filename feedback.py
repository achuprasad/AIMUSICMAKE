"""User feedback, suggestions, bug reports and roadmap votes.

Storage is behind a small interface so the web deployment can swap the local
JSON-lines file for a database without touching the API or UI (see
docs/support-and-feedback.md).

Security notes:
- every field is length-limited and stripped of control characters;
- text is stored verbatim and must always be rendered as text, never as HTML;
- e-mail is stored only when the user ticks consent;
- per-client rate limiting limits spam;
- diagnostics are an allowlist of harmless fields; never files or paths.
"""
import json
import os
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

APP_VERSION = "1.0.0"

CATEGORIES = {
    "feature": "Feature request",
    "suggestion": "Suggestion",
    "bug": "Bug report",
    "question": "Question",
}
TOOLS = ["general", "split", "pitch", "analyze", "cut", "join", "convert", "desktop-app", "website"]

# Planned features users can vote on (from docs/technical-assessment.md §3)
ROADMAP = [
    {"id": "noise-removal", "title": "Noise removal & voice enhancement",
     "description": "Clean up background noise, hum and echo in voice recordings."},
    {"id": "timeline-editor", "title": "Multi-track timeline editor",
     "description": "Arrange clips on tracks, split, drag and drop, zoom, with undo and redo."},
    {"id": "export-presets", "title": "Export presets for YouTube, Reels & TikTok",
     "description": "One click to the right format and loudness (LUFS) for each platform."},
    {"id": "loudness", "title": "Loudness normalisation & clipping check",
     "description": "Make tracks equally loud and warn about distortion before export."},
    {"id": "silence-removal", "title": "Automatic silence removal",
     "description": "Cut dead air from podcasts and voice-overs automatically."},
    {"id": "video-sync", "title": "Video tools: sync music to video beats",
     "description": "Beat-matched cuts, background-music ducking under speech."},
    {"id": "mastering", "title": "AI mastering",
     "description": "EQ, compression and loudness suggestions for a finished sound."},
    {"id": "sfx-library", "title": "Sound-effects & music library",
     "description": "Royalty-free whooshes, transitions, ambiences and intros."},
    {"id": "assistant", "title": "Natural-language assistant",
     "description": "Type what you want (\"remove vocals and fade out the end\") and it does it."},
    {"id": "cloud-projects", "title": "Accounts & cloud projects",
     "description": "Use it in any browser, save projects online, continue on another device."},
]
ROADMAP_IDS = {r["id"] for r in ROADMAP}

LIMITS = {"title": (3, 120), "message": (10, 5000)}
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")
CLIENT_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
DIAG_KEYS = {"app_version": 20, "user_agent": 300, "screen": 20, "device": 10, "gpu": 80, "page": 30}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class FeedbackError(Exception):
    """Invalid input; the message is safe to show to the user."""


class RateLimited(Exception):
    pass


def clean_text(value, field, required=True):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise FeedbackError(f"{field} must be text.")
    value = _CONTROL.sub("", value).replace("\r\n", "\n").strip()
    lo, hi = LIMITS[field]
    if not value and not required:
        return ""
    if not (lo <= len(value) <= hi):
        raise FeedbackError(f"{field.capitalize()} must be {lo}-{hi} characters.")
    return value


def clean_client(value):
    if not isinstance(value, str) or not CLIENT_RE.match(value):
        raise FeedbackError("Invalid client id.")
    return value


def validate(body):
    """Return a clean feedback record (without id/time) or raise FeedbackError."""
    if not isinstance(body, dict):
        raise FeedbackError("Invalid request.")
    category = body.get("category")
    if category not in CATEGORIES:
        raise FeedbackError(f"Category must be one of: {', '.join(CATEGORIES)}.")
    tool = body.get("tool", "general")
    if tool not in TOOLS:
        raise FeedbackError("Unknown tool.")
    rec = {"category": category, "tool": tool,
           "title": clean_text(body.get("title"), "title"),
           "message": clean_text(body.get("message"), "message"),
           "client": clean_client(body.get("client")), "email": None, "rating": None, "diagnostics": {}}
    email, consent = body.get("email"), body.get("contact_consent") is True
    if email:
        if not consent:
            raise FeedbackError("Tick the consent box if you want us to contact you by e-mail.")
        if not isinstance(email, str) or not EMAIL_RE.match(email.strip()):
            raise FeedbackError("That e-mail address doesn't look valid.")
        rec["email"] = email.strip()
    rating = body.get("rating")
    if rating not in (None, ""):
        if not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5:
            raise FeedbackError("Rating must be 1-5.")
        rec["rating"] = rating
    diag = body.get("diagnostics") or {}
    if not isinstance(diag, dict):
        raise FeedbackError("Invalid diagnostics.")
    rec["diagnostics"] = {k: _CONTROL.sub("", str(v))[:DIAG_KEYS[k]] for k, v in diag.items() if k in DIAG_KEYS}
    return rec


class RateLimiter:
    """At most `limit` events per `window` seconds per key (in memory; the web version should use the DB/edge)."""

    def __init__(self, limit=5, window=600):
        self.limit, self.window = limit, window
        self.events = defaultdict(deque)
        self.lock = threading.Lock()

    def hit(self, key, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            q = self.events[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                raise RateLimited(f"Too many submissions. Please try again in {int(self.window - (now - q[0])) + 1} s.")
            q.append(now)


class LocalStore:
    """Append-only JSON-lines file. Fine for the desktop app; replace with a DB for the web."""

    mode = "local"

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def _append(self, row):
        with self.lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _rows(self):
        if not self.path.exists():
            return []
        out = []
        with self.lock, open(self.path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # a damaged line must not break the page
        return out

    def add_feedback(self, rec):
        row = {"type": "feedback", "id": "FB-" + uuid.uuid4().hex[:8].upper(),
               "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "status": "received", **rec}
        self._append(row)
        return row

    def add_event(self, row):
        """Audit trail entries (e.g. e-mail delivery result). Contains no addresses or secrets."""
        self._append({**row, "created": time.strftime("%Y-%m-%dT%H:%M:%S")})

    def list_feedback(self, client, limit=20):
        rows = [r for r in self._rows() if r.get("type") == "feedback" and r.get("client") == client]
        return rows[::-1][:limit]

    def set_vote(self, item, client, on):
        self._append({"type": "vote", "item": item, "client": client, "on": bool(on),
                      "created": time.strftime("%Y-%m-%dT%H:%M:%S")})

    def votes(self):
        """Latest vote per (item, client) wins, so voting is idempotent and can be undone."""
        state = {}
        for r in self._rows():
            if r.get("type") == "vote":
                state[(r["item"], r["client"])] = r["on"]
        return state


def default_store():
    p = os.environ.get("AUDIO_STUDIO_FEEDBACK", str(Path.home() / ".audiostudio" / "feedback.jsonl"))
    return LocalStore(p)


def roadmap_with_votes(store, client):
    state = store.votes()
    out = []
    for r in ROADMAP:
        count = sum(1 for (item, _), on in state.items() if item == r["id"] and on)
        out.append({**r, "votes": count, "voted": bool(state.get((r["id"], client)))})
    return out
