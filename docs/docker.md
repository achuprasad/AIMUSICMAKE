# Running Mixlumo as a web app in Docker

The same FastAPI backend and browser UI as the Windows app, packaged as a Linux container. Users
open it in any browser; uploads, AI processing and results stay on the server running the container.

## Quick start

```bash
docker compose up -d --build            # CPU image
# or, on a host with an NVIDIA GPU:
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

Open <http://localhost:7860>. The first vocal-removal job downloads its model (one time, about
600 MB for BS-RoFormer, 80 MB per Demucs model) into the `mixlumo-data` volume.

Without Compose:

```bash
docker build -t mixlumo:cpu .
docker run -d -p 7860:7860 -v mixlumo-data:/data --name mixlumo mixlumo:cpu

docker build -t mixlumo:gpu --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu118 .
docker run -d --gpus all -p 7860:7860 -v mixlumo-data:/data --name mixlumo mixlumo:gpu
```

GPU requirements: an NVIDIA driver ≥ 452 on the host and the NVIDIA Container Toolkit. On Windows,
Docker Desktop with the WSL 2 backend and a current NVIDIA driver provides both. The CUDA libraries
come inside the PyTorch wheels, so the image does not need a CUDA base image.

## Image layout (multi-stage build)

| Stage | Contents | Shipped? |
|---|---|---|
| `ffmpeg` | Static `ffmpeg` + `ffprobe` (`mwader/static-ffmpeg`) | only the two binaries |
| `builder` | `python:3.12-slim` + compilers; installs `requirements.txt` into `/opt/venv` (PyTorch from its own index first) | only `/opt/venv` |
| `runtime` | `python:3.12-slim` + `libgomp1` + venv + ffmpeg + app code | yes |

What keeps it small: no compilers, apt lists, pip cache, `__pycache__` or package test suites in the
final image; a static ffmpeg instead of Debian's (~80 MB against ~400 MB with libraries); models in the
volume instead of the image; `.dockerignore` sends only the app files to the build. The CPU image is
much smaller than the GPU one, because the CUDA build of PyTorch alone is about 2.5 GB.

## Data and settings

Everything that changes lives in the `/data` volume:

| Path | Contents |
|---|---|
| `/data/models` | RoFormer models; `/data/models/torch` holds the Demucs weights |
| `/data/outputs` | Results (served at `/files/...`) |
| `/data/uploads` | Uploads; cleared at each container start |
| `/data/feedback.jsonl` | Help & Feedback messages |

Settings are environment variables (see `.env.example`). Compose reads an optional `.env` file next
to `docker-compose.yml`; with `docker run`, use `--env-file .env`. The image sets:

| Variable | Value in the image | Meaning |
|---|---|---|
| `AUDIO_STUDIO_WEB` | `1` | Web mode: no "Open folder" buttons; `/api/open-folder` returns 404 |
| `AUDIO_STUDIO_HOST` | `0.0.0.0` | Listen on all interfaces inside the container (the app's default is `127.0.0.1`) |
| `PORT` | `7860` | Port inside the container. Compose's `PORT` changes the host port only |

The container runs as an unprivileged user (uid 10001) and has a health check on `/api/info`.

## Before exposing it to the internet

The app was built as a single-user local tool. In a shared deployment, bear in mind:

- **No accounts.** Anyone who can reach the port can use the GPU, and anyone who knows or guesses a
  result URL under `/files/` can download it. Put it behind a reverse proxy with authentication
  (and HTTPS), or keep it on a private network.
- **Results are never deleted.** `/data/outputs` grows until you clean it.
- **One job at a time.** Jobs from all users share one queue.
- Behind a proxy on a different host name, the proxy must pass the original `Host` header, or list
  the public origin in `AUDIO_STUDIO_ALLOWED_ORIGINS`, because the cross-site write check compares
  `Origin` with `Host`.
- Set the upload limit (`AUDIO_STUDIO_MAX_UPLOAD_MB`, default 1024) to match the proxy's body limit.
