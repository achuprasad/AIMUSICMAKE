# PyInstaller spec for the offline Windows app.  Built by scripts\build-windows.ps1 (do not run by hand).
# Inputs from environment (set by the build script):
#   LAS_FFMPEG       path to ffmpeg.exe to bundle
#   LAS_MODELS       folder with RoFormer .ckpt/.yaml + download_checks.json
#   LAS_TORCH_HOME   folder containing hub/checkpoints/*.th (Demucs)
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller

datas = [(str(ROOT / "static"), "static")]
binaries = []
hiddenimports = ["server", "engine", "gpu_worker", "notify", "feedback", "uvicorn.logging", "uvicorn.loops.auto",
                 "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
                 "python_multipart", "multipart"]

# Packages that load data files, plugins or submodules dynamically
for pkg in ["demucs", "audio_separator", "librosa", "soundfile", "rotary_embedding_torch", "beartype",
            "ml_collections", "julius", "einops", "samplerate", "resampy", "onnxruntime", "diffq",
            "audioread", "lazy_loader", "soxr", "numba", "llvmlite", "fastapi", "starlette"]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:  # a missing optional package must not break the build
        print(f"collect_all({pkg}) skipped: {e}")

# Offline resources
datas += [(os.environ["LAS_FFMPEG"], "bundled/bin")]
datas += [(os.environ["LAS_MODELS"], "bundled/models")]
datas += [(os.environ["LAS_TORCH_HOME"], "bundled/torch_home")]

# Big packages in the dev environment that the app never uses
excludes = ["gradio", "gradio_client", "playwright", "pytest", "_pytest", "mypy", "ruff", "IPython", "jupyter",
            "notebook", "tkinter", "matplotlib", "pip_audit", "coverage", "PyInstaller"]

a = Analysis(  # noqa: F821
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Mixlumo",
    icon=str(ROOT / "packaging" / "icon.ico"),
    console=False,          # windowed app; output goes to %LOCALAPPDATA%\Mixlumo\logs\app.log
    upx=False,              # UPX corrupts CUDA DLLs and triggers antivirus false positives
    version=str(ROOT / "packaging" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Mixlumo", upx=False)  # noqa: F821
