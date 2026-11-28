# syntax=docker/dockerfile:1.7
# Mixlumo web app: FastAPI backend + browser UI in one container.
#
#   CPU image (default):  docker build -t mixlumo .
#   NVIDIA GPU image:     docker build -t mixlumo:gpu --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu118 .
#   Run:                  docker run -p 7860:7860 -v mixlumo-data:/data mixlumo      (GPU: add --gpus all)
#
# Three stages keep the final image small:
#   ffmpeg   - a static ffmpeg/ffprobe build (about 80 MB, against about 400 MB for Debian's ffmpeg and its libraries)
#   builder  - compilers + pip install into a virtualenv; none of this is shipped
#   runtime  - slim Python + the virtualenv + ffmpeg + the app code, running as a non-root user
# The AI models (~1.7 GB) are not in the image: they download on first use into the /data volume.

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- ffmpeg
FROM mwader/static-ffmpeg:7.1 AS ffmpeg

# ---------------------------------------------------------------- builder
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder
# CPU wheels by default. cu118 runs on NVIDIA drivers >= 452 (see scripts/setup.ps1).
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY requirements.txt /tmp/requirements.txt
# PyTorch first, from its own index, so the resolver can never swap in the multi-GB CUDA 12 build from PyPI.
RUN TORCH_PINS=$(grep -E '^(torch|torchaudio)==' /tmp/requirements.txt) \
 && pip install --index-url "$TORCH_INDEX" $TORCH_PINS \
 && pip install -r /tmp/requirements.txt \
 && find /opt/venv/lib -depth -type d \( -name '__pycache__' -o -name 'tests' \) -exec rm -rf {} + \
 && python -c "import torch, torchaudio, demucs, audio_separator, librosa, fastapi; print('torch', torch.__version__)"

# ---------------------------------------------------------------- runtime
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="Mixlumo" \
      org.opencontainers.image.description="AI vocal remover, stem splitter and music editor (web)"

# libgomp: OpenMP runtime used by PyTorch/ONNX Runtime/scikit-learn on CPU
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 --shell /usr/sbin/nologin mixlumo \
 && mkdir -p /data && chown mixlumo:mixlumo /data

COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/
COPY --from=builder /opt/venv /opt/venv

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AUDIO_STUDIO_WEB=1 \
    AUDIO_STUDIO_HOST=0.0.0.0 \
    AUDIO_STUDIO_NO_DOTENV=1 \
    PORT=7860 \
    HOME=/home/mixlumo \
    AUDIO_STUDIO_OUT=/data/outputs \
    AUDIO_STUDIO_UPLOADS=/data/uploads \
    AUDIO_STUDIO_MODELS=/data/models \
    AUDIO_STUDIO_FEEDBACK=/data/feedback.jsonl \
    TORCH_HOME=/data/models/torch \
    NUMBA_CACHE_DIR=/tmp/numba

WORKDIR /app
COPY --chown=root:root engine.py gpu_worker.py server.py feedback.py notify.py ./
# server.py imports the Voice Studio modules; the studio itself is refused in web mode (no accounts)
COPY --chown=root:root voice_engine.py voice_studio.py voice_profiles.py voice_tones.py story_script.py voice_worker.py ./
COPY --chown=root:root static ./static

USER mixlumo
VOLUME ["/data"]
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/info', timeout=4)" || exit 1

CMD ["python", "server.py"]
