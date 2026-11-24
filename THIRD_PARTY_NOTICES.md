# Third-party notices

The app is built on open-source software and pretrained models. Licences below are as
understood at the time of writing; **verify each before commercial release**. Items marked ⚠
need legal review before selling or distributing the app.

## Software bundled in the Windows app

| Component | Licence | Notes |
|---|---|---|
| Python 3.12 | PSF License | |
| PyTorch / torchaudio 2.5.1 | BSD-3-Clause | CUDA/cuDNN runtime DLLs ship under the NVIDIA EULA (redistributable) |
| Demucs 4.0.1 (Meta) | MIT | |
| audio-separator 0.48.0 | MIT | |
| FastAPI, Starlette, Uvicorn | MIT / BSD-3 | |
| librosa | ISC | |
| NumPy, SciPy, soundfile, numba | BSD-3 | |
| ONNX Runtime | MIT | |
| ⚠ **FFmpeg 9.0.2 "full" build (gyan.dev)** | **GPL-3.0** (built with `--enable-gpl`) | Distributing a GPL build obliges you to offer the corresponding source. For a closed-source commercial product, switch to an **LGPL build** (and avoid GPL-only libraries such as x264) or comply with the GPL. |

## AI model weights

| Model | Source | Licence |
|---|---|---|
| HT-Demucs / HT-Demucs 6s | Meta (facebookresearch/demucs) | MIT (repository licence) |
| ⚠ BS-RoFormer `model_bs_roformer_ep_317_sdr_12.9755` | viperx, distributed via the UVR / audio-separator model list | Not clearly stated. **Get written confirmation before commercial use.** |
| ⚠ Mel-Band RoFormer `model_mel_band_roformer_ep_3005_sdr_11.4360` | viperx, same source | Not clearly stated. Same as above |

## Test data (not distributed)

MUSDB18 7-second excerpts (Zenodo 3270814) are used for quality benchmarks only. They are
licensed for **research and non-commercial use**, are downloaded to the developer's PC, and are
never committed or shipped.
