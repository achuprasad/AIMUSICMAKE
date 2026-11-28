# Copyright (c) 2026 Achu Prasad. All rights reserved. See LICENSE.
"""Mixlumo - web server. Run: python server.py  ->  http://127.0.0.1:7860"""
# ruff: noqa: I001 - import order is deliberate: private settings (.env) must load before engine/feedback import
import os
import shutil
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import uvicorn
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import notify

ROOT = Path(__file__).resolve().parent
# Private settings (mail recipients, SMTP login) come from the environment or a git-ignored .env file.
# They are read here and never sent to the browser. Tests set AUDIO_STUDIO_NO_DOTENV=1.
if os.environ.get("AUDIO_STUDIO_NO_DOTENV") != "1":
    notify.load_env_file(ROOT / ".env")
    notify.load_env_file(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Mixlumo" / "settings.env")

import engine  # noqa: E402 - after the environment is loaded
import feedback  # noqa: E402
from gpu_worker import GpuWorker, WorkerCrashed  # noqa: E402
import voice_profiles  # noqa: E402
import voice_studio  # noqa: E402
from voice_engine import VoiceEngine, VoiceEngineError  # noqa: E402

UPLOADS = Path(os.environ.get("AUDIO_STUDIO_UPLOADS", engine.HOME / "uploads"))
MAX_UPLOAD = int(os.environ.get("AUDIO_STUDIO_MAX_UPLOAD_MB", "1024")) * 1024 * 1024
FILE_TOOLS = {"separate", "pitch", "analyze", "cut", "convert"}
MAX_JOBS_KEPT = 200
# Keep the last model on the GPU for back-to-back jobs, then give the GPU back.
IDLE_UNLOAD_S = float(os.environ.get("AUDIO_STUDIO_IDLE_UNLOAD_S", "300"))
# Web mode (Docker / server deployment): the browser runs on another machine, so features that act
# on the server's own desktop (opening Explorer on the output folder) are switched off.
WEB = os.environ.get("AUDIO_STUDIO_WEB") == "1"
# Localhost only by default. The Docker image sets AUDIO_STUDIO_HOST so its port can be published.
HOST = os.environ.get("AUDIO_STUDIO_HOST", "127.0.0.1")
_last_activity = [time.perf_counter()]
GPU_TOOLS = {"separate"}  # run in the worker process; everything else is CPU-only
VOICE_TOOLS = {"voice", "voice_profile"}  # Malayalam Voice Studio: run in the voice worker (its own environment)
worker = GpuWorker()
voice = VoiceEngine()
USER_ERRORS = (engine.UserError, WorkerCrashed, VoiceEngineError, voice_profiles.ProfileError)
# Importing this module must have no side effects on disk: a stray `import server` (tests, tools)
# once wiped a running instance's uploads mid-job. Cleanup happens only in clean_temp_files(),
# called at real start-up after confirming no other instance owns the port.
UPLOADS.mkdir(parents=True, exist_ok=True)


def clean_temp_files():
    """Delete leftovers from a previous run. Only call when this process is the sole server."""
    shutil.rmtree(UPLOADS, ignore_errors=True)
    shutil.rmtree(engine.OUT / ".work", ignore_errors=True)
    UPLOADS.mkdir(parents=True, exist_ok=True)


def port_in_use(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0

app = FastAPI(title="Mixlumo")

# ------------------------------------------------------------------ request guards
MAX_JSON_BODY = 64 * 1024
EXTRA_ORIGINS = {o.strip().rstrip("/") for o in os.environ.get("AUDIO_STUDIO_ALLOWED_ORIGINS", "").split(",") if o.strip()}


def same_origin(request):
    """Block cross-site writes (CSRF): another website must not be able to drive this app from a visitor's browser."""
    if request.headers.get("sec-fetch-site") == "cross-site":
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return True  # non-browser clients (curl, tests) send no Origin; browsers always send it on POST
    if origin == "null":
        return False  # sandboxed iframes, local HTML files, data: URLs
    if origin.rstrip("/") in EXTRA_ORIGINS:
        return True
    return urlparse(origin).netloc == request.headers.get("host")


@app.middleware("http")
async def guards(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if not same_origin(request):
            return JSONResponse({"detail": "Cross-site request blocked."}, status_code=403)
        if not request.url.path.startswith("/api/upload"):  # uploads have their own 1 GB streaming limit
            size = request.headers.get("content-length")
            if size is None and request.headers.get("transfer-encoding"):
                return JSONResponse({"detail": "Content-Length required."}, status_code=411)
            if size is not None and (not size.isdigit() or int(size) > MAX_JSON_BODY):
                return JSONResponse({"detail": "Request too large."}, status_code=413)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response

threading.stack_size(64 * 1024 * 1024)  # native audio/ML code needs more than Windows' 1 MB default
pool = ThreadPoolExecutor(max_workers=1)  # one GPU job at a time; others wait in line
pool.submit(lambda: None).result()  # create the worker thread now, with the large stack
threading.stack_size(0)
jobs: dict[str, dict] = {}
uploads: dict[str, str] = {}
lock = threading.Lock()


def file_url(path):
    rel = Path(path).resolve().relative_to(engine.OUT.resolve())
    return "/files/" + "/".join(quote(part) for part in rel.parts)


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/info")
def info():
    return {"device": engine.DEVICE, "gpu": engine.GPU_NAME, "output": str(engine.OUT), "formats": engine.FORMATS,
            "version": feedback.APP_VERSION,   # the desktop launcher only reuses a server of its own version
            "web": WEB}


@app.post("/api/upload")
def upload(file: UploadFile = File(...)):  # noqa: B008 - FastAPI's declared-dependency idiom
    # a plain def runs in FastAPI's thread pool, so writing a large upload never blocks
    # the event loop (which would freeze progress polling for running jobs)
    uid = uuid.uuid4().hex[:12]
    d = UPLOADS / uid
    d.mkdir()
    name = Path((file.filename or "audio").replace("\\", "/")).name[-80:] or "audio"
    dest = d / name
    size = 0
    with open(dest, "wb") as f:
        while chunk := file.file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD:
                f.close()
                shutil.rmtree(d, ignore_errors=True)
                raise HTTPException(413, f"File is larger than {MAX_UPLOAD // (1024 * 1024)} MB.")
            f.write(chunk)
    if size == 0:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, "The file is empty.")
    try:
        dur = engine.duration(dest)
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, f"'{name}' is not a readable audio file.") from None
    if dur <= 0:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, f"'{name}' contains no audio.")
    uploads[uid] = str(dest)
    return {"id": uid, "name": name, "duration": round(dur, 2), "size": size}


@app.delete("/api/uploads/{uid}")
def delete_upload(uid: str):
    path = uploads.pop(uid, None)
    if not path:
        raise HTTPException(404, "Upload not found")
    shutil.rmtree(Path(path).parent, ignore_errors=True)
    return {"ok": True}


def _resolve(tool, p):
    """Validate the request shape and swap upload ids for file paths."""
    if not isinstance(p, dict):
        raise HTTPException(400, "params must be an object")
    p = dict(p)
    p.pop("file", None)  # clients may only refer to uploads, never to raw paths
    if tool in FILE_TOOLS:
        if "upload" not in p:
            raise HTTPException(400, "Missing 'upload'. Upload a file first.")
        p["file"] = uploads.get(str(p.pop("upload"))) or _missing()
    if tool == "voice_profile":
        if "upload" not in p:
            raise HTTPException(400, "Missing 'upload'. Record or upload the voice sample first.")
        p["file"] = uploads.get(str(p.pop("upload"))) or _missing()
    if tool == "voice":
        p.pop("previous", None)                                  # only the server sets this
        if "regenerate" in p:
            prev = jobs.get(str(p.pop("regenerate")))
            if not prev or prev.get("tool") != "voice" or prev.get("status") != "done":
                raise HTTPException(400, "Generate the speech first, then regenerate a line.")
            p["previous"] = prev["result"]["folder"]             # a server-side path, never one from the client
    if tool == "join":
        ids = p.pop("uploads", None)
        if not isinstance(ids, list):
            raise HTTPException(400, "Missing 'uploads' list.")
        p["files"] = [uploads.get(str(u)) or _missing() for u in ids]
    return p


def _missing():
    raise HTTPException(400, "Uploaded file not found. Please upload it again.")


def _run(jid, tool, params):
    job = jobs[jid]

    def report(frac, stage):
        # Progress display must never be able to fail a job.
        frac = max(job["progress"], min(0.999, float(frac)))
        now = time.perf_counter()  # monotonic, high resolution (time.time() ticks every ~15 ms on Windows)
        with lock:
            job.update(progress=frac, stage=stage, status="running")
            if not job.get("work_start") and frac >= 0.10:
                job["work_start"], job["work_frac"] = now, frac
            ws = job.get("work_start")
            elapsed = now - ws if ws else 0.0
            done = frac - job.get("work_frac", frac)
            # Two updates in the same instant used to divide by zero and kill the job.
            if ws and done > 0.02 and elapsed > 0.05:
                job["eta"] = round((1 - frac) * elapsed / done)

    job["started"] = time.time()
    if job.get("cancel"):
        job.update(status="error", error="Cancelled.")
        return
    report(0.0, "Starting...")
    try:
        if tool in GPU_TOOLS:
            voice.stop()             # a 4 GB GPU holds one model at a time: give the voice engine's memory back
            res = worker.run(tool, params, report, user_error=engine.UserError)
        elif tool in VOICE_TOOLS:
            worker.stop()            # and the other way round
            if tool == "voice":
                res = voice_studio.render(params, report, voice, previous=params.get("previous"),
                                          cancelled=lambda: bool(job.get("cancel")))
            else:
                try:
                    res = voice_studio.make_profile_job(params, report, voice, params["file"])
                finally:                 # a voice recording is not kept: remove the uploaded copy now
                    up = Path(params["file"]).parent
                    for k in [k for k, v in uploads.items() if Path(v).parent == up]:
                        uploads.pop(k, None)
                    shutil.rmtree(up, ignore_errors=True)
        else:
            res = engine.TOOLS[tool](params, report)
        for ln in (res.get("voice") or {}).get("lines", []):
            lp = voice_studio.line_file(res["folder"], ln["index"]) if ln["kind"] == "speech" else None
            ln["url"] = file_url(lp) if lp else None
        for f in res.get("files", []):
            f["url"] = file_url(f["path"])
            f["name"] = Path(f["path"]).name
            f["peaks"] = engine.peaks(f["path"])
            f["size"] = Path(f["path"]).stat().st_size
        job.update(status="done", progress=1.0, stage="Done", result=res, eta=0,
                   elapsed=round(time.time() - job["started"], 1))
    except USER_ERRORS as e:
        job.update(status="error", error=str(e))
    except Exception as e:
        traceback.print_exc()
        job.update(status="error", error=f"{type(e).__name__}: {e}")
    finally:
        _last_activity[0] = time.perf_counter()


def _busy():
    return any(j["status"] in ("queued", "running") for j in jobs.values())


def release_if_idle(now=None):
    """Unload models once the app has been idle for IDLE_UNLOAD_S. Returns True if it unloaded."""
    now = time.perf_counter() if now is None else now
    if _busy() or not worker.alive or now - _last_activity[0] < IDLE_UNLOAD_S:
        return False
    return worker.stop()  # the worker process exits, so the OS reclaims all of its GPU memory


def _idle_watcher():  # pragma: no cover - timing loop; release_if_idle() is unit-tested
    while True:
        time.sleep(15)
        try:
            release_if_idle()
        except Exception:
            traceback.print_exc()


@app.post("/api/release-gpu")
def release_gpu():
    """Free all GPU memory now (waits for a running job first). Used by the test runner and other GPU apps."""
    return {"released": worker.stop() | voice.stop()}


@app.post("/api/jobs")
def create_job(body: dict, request: Request):
    tool = body.get("tool")
    if tool not in engine.TOOLS and tool not in VOICE_TOOLS:
        raise HTTPException(400, "Unknown tool")
    if tool in VOICE_TOOLS and WEB:
        _voice_web_block()
    if tool == "voice_profile":                  # counted before validation, so bad requests are limited too
        try:
            clone_limiter.hit(_client_key(request, "voice"))
        except feedback.RateLimited as e:
            raise HTTPException(429, str(e)) from None
    params = _resolve(tool, body.get("params", {}))
    finished = [k for k, j in jobs.items() if j["status"] in ("done", "error")]
    for k in finished[: max(0, len(jobs) - MAX_JOBS_KEPT)]:
        jobs.pop(k, None)
    jid = uuid.uuid4().hex[:12]
    jobs[jid] = {"id": jid, "tool": tool, "status": "queued", "progress": 0.0,
                 "stage": "Waiting for the previous job to finish...", "eta": None, "created": time.time()}
    pool.submit(_run, jid, tool, params)
    return {"id": jid}


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str):
    """Stop a waiting job, or a running voice job after its current line."""
    job = jobs.get(jid)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] not in ("queued", "running"):
        return {"cancelled": False}
    if job["status"] == "running" and job["tool"] not in VOICE_TOOLS:
        raise HTTPException(409, "This job can't be stopped part-way.")
    job["cancel"] = True
    return {"cancelled": True}


@app.get("/api/jobs/{jid}")
def job_status(jid: str):
    job = jobs.get(jid)
    if not job:
        raise HTTPException(404, "Job not found")
    out = {k: job.get(k) for k in ("id", "tool", "status", "progress", "stage", "eta", "error", "result", "elapsed")}
    out["elapsed_now"] = round(time.time() - job.get("started", time.time()), 1)
    return out


# ------------------------------------------------------------------ support & feedback
GITHUB_ISSUES = os.environ.get("AUDIO_STUDIO_ISSUES_URL", "https://github.com/achuprasad/AIMUSICMAKE/issues/new")
feedback_store = feedback.default_store()
feedback_limiter = feedback.RateLimiter(limit=5, window=600)   # 5 messages per 10 min per client
ip_limiter = feedback.RateLimiter(limit=20, window=600)         # and 20 per 10 min per IP (client ids are free to change)
vote_limiter = feedback.RateLimiter(limit=60, window=600)
try:
    mailer = notify.Mailer.from_env()
except notify.MailerConfigError as e:  # bad settings must not stop the app; feedback is still stored
    print(f"Feedback e-mail disabled: {e}", flush=True)
    mailer = notify.Mailer()


def _mail_done(row, result):
    feedback_store.add_event({"type": "notify", "id": row["id"], "result": result})


def _client_key(request, client):
    return f"{request.client.host if request.client else '?'}|{client}"


@app.get("/api/support")
def support_info():
    # "delivery" says whether the team is e-mailed; the addresses themselves are never exposed
    return {"mode": feedback_store.mode, "delivery": "email" if mailer.enabled else "local",
            "version": feedback.APP_VERSION, "github_issues": GITHUB_ISSUES,
            "categories": feedback.CATEGORIES, "tools": feedback.TOOLS}


@app.post("/api/feedback", status_code=201)
def submit_feedback(body: dict, request: Request):
    try:
        rec = feedback.validate(body)
        ip_limiter.hit(request.client.host if request.client else "?")
        feedback_limiter.hit(_client_key(request, rec["client"]))
    except feedback.FeedbackError as e:
        raise HTTPException(400, str(e)) from None
    except feedback.RateLimited as e:
        raise HTTPException(429, str(e)) from None
    delivery = "email" if mailer.enabled else "local"
    if isinstance(body, dict) and body.get("website"):  # honeypot field humans never see: silently drop bots
        return {"id": "FB-" + uuid.uuid4().hex[:8].upper(), "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "status": "received", "mode": feedback_store.mode, "delivery": delivery}
    row = feedback_store.add_feedback(rec)  # stored first: a mail failure can never lose feedback
    if mailer.enabled:
        mailer.send_in_background(row, on_done=_mail_done)
    return {"id": row["id"], "created": row["created"], "status": row["status"], "mode": feedback_store.mode,
            "delivery": delivery}


@app.get("/api/feedback")
def my_feedback(client: str):
    try:
        client = feedback.clean_client(client)
    except feedback.FeedbackError as e:
        raise HTTPException(400, str(e)) from None
    keep = ("id", "created", "status", "category", "tool", "title", "message", "rating")
    return {"items": [{k: r.get(k) for k in keep} for r in feedback_store.list_feedback(client)]}


@app.get("/api/support/roadmap")
def roadmap(client: str = ""):
    client = client if feedback.CLIENT_RE.match(client or "") else ""
    return {"items": feedback.roadmap_with_votes(feedback_store, client)}


@app.post("/api/support/roadmap/{item}/vote")
def vote(item: str, body: dict, request: Request):
    if item not in feedback.ROADMAP_IDS:
        raise HTTPException(404, "Unknown roadmap item")
    try:
        client = feedback.clean_client(body.get("client"))
        vote_limiter.hit(_client_key(request, client))
    except feedback.FeedbackError as e:
        raise HTTPException(400, str(e)) from None
    except feedback.RateLimited as e:
        raise HTTPException(429, str(e)) from None
    feedback_store.set_vote(item, client, body.get("on", True) is True)
    return next(r for r in feedback.roadmap_with_votes(feedback_store, client) if r["id"] == item)


@app.post("/api/open-folder")
def open_folder(body: dict):
    if WEB:
        raise HTTPException(404, "Not available in the web version. Use Download instead.")
    p = Path(body.get("path") or engine.OUT).resolve()
    if p != engine.OUT.resolve() and engine.OUT.resolve() not in p.parents:
        raise HTTPException(400, "Not an output folder")
    if sys.platform == "win32":
        os.startfile(p)  # noqa: S606 - opens Explorer on a folder already validated to be inside OUT
    return {"ok": True}


# ------------------------------------------------------------------ Malayalam Voice Studio
clone_limiter = feedback.RateLimiter(limit=20, window=600)      # voice samples per 10 min
VOICE_WEB_MSG = ("The Malayalam Voice Studio is available in the desktop app only: the web version has no user "
                 "accounts, so voices and voice cloning can't be kept private there.")


def _voice_web_block():
    """Web mode has no accounts: anyone who can reach the server could clone voices or delete them. Until per-user
    authorisation exists (docs/voice-cloning-security.md), every voice action is refused server-side."""
    raise HTTPException(403, VOICE_WEB_MSG)


def _voice_call(fn, *args):
    try:
        return fn(*args)
    except voice_profiles.ProfileError as e:
        raise HTTPException(404 if "not found" in str(e) else 400, str(e)) from None


@app.get("/api/voice/status")
def voice_status():
    if WEB:
        return {"installed": False, "available": False, "reason": VOICE_WEB_MSG, "tones": [], "licences": [],
                "language": "ml", "disclosure": voice_studio.DISCLOSURE, "consent_text": voice_profiles.CONSENT_TEXT}
    return {**voice_studio.status(voice), "available": True}


@app.get("/api/voice/profiles")
def voice_profiles_list():
    if WEB:
        _voice_web_block()
    return {"items": voice_profiles.list_profiles()}


@app.get("/api/voice/profiles/{pid}")
def voice_profile_get(pid: str):
    if WEB:
        _voice_web_block()
    return voice_profiles.public(_voice_call(voice_profiles.get, pid))


@app.patch("/api/voice/profiles/{pid}")
def voice_profile_rename(pid: str, body: dict):
    if WEB:
        _voice_web_block()
    return _voice_call(voice_profiles.rename, pid, body.get("name"))


@app.delete("/api/voice/profiles/{pid}")
def voice_profile_delete(pid: str):
    if WEB:
        _voice_web_block()
    if pid in voice_profiles.BUILTIN:
        raise HTTPException(400, "Built-in voices can't be deleted.")
    _voice_call(voice_profiles.delete, pid)
    print(f"voice profile {pid} deleted", flush=True)          # audit trail: the id only, never names or audio
    return {"ok": True}


@app.delete("/api/voice/profiles/{pid}/tones/{tone}")
def voice_tone_delete(pid: str, tone: str):
    if WEB:
        _voice_web_block()
    if pid in voice_profiles.BUILTIN:
        raise HTTPException(400, "Built-in voices are fixed.")
    return _voice_call(voice_profiles.remove_tone, pid, tone)


app.mount("/files", StaticFiles(directory=engine.OUT), name="files")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

def create_server(port):  # pragma: no cover - startup wiring; exercised by the e2e suite and desktop smoke test
    """Prepare a uvicorn server for this app. Caller runs it (blocking .run() or in a thread)."""
    clean_temp_files()
    threading.Thread(target=_idle_watcher, daemon=True).start()
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning")
    return uvicorn.Server(config)


def shutdown():  # pragma: no cover - called by the desktop launcher on exit
    worker.stop(timeout=5)
    voice.stop()


if __name__ == "__main__":  # pragma: no cover - entry point; exercised by the e2e suite in a subprocess
    port = int(os.environ.get("PORT", "7860"))
    if port_in_use(port):
        sys.exit(f"Mixlumo is already running at http://127.0.0.1:{port} - open that instead.")
    print(f"Mixlumo running at http://{HOST}:{port}  ({engine.GPU_NAME})", flush=True)
    create_server(port).run()
