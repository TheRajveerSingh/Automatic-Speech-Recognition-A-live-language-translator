"""Log-Mel spectrogram - the exact input Whisper's neural network sees.

We re-implement it step by step (instead of calling a library) so that every
intermediate result can be shown in the UI, then verify our numbers match
faster-whisper's own extractor.

    audio (16 kHz) -> pad -> frames of 400 samples (25 ms) every 160 (10 ms)
    -> Hann window -> FFT -> power spectrum (201 bins, 0-8 kHz)
    -> Mel filterbank (n_mels triangles) -> log10 -> clamp to 8 decades
    -> scale to roughly [-1, 1]
"""

from __future__ import annotations

import base64

import numpy as np
from faster_whisper.feature_extractor import FeatureExtractor

SR, N_FFT, HOP = 16_000, 400, 160
_filters: dict[int, np.ndarray] = {}


def mel_filters(n_mels: int) -> np.ndarray:
    """(n_mels, 201) matrix of triangular filters, spaced on the Mel (pitch-perception) scale."""
    if n_mels not in _filters:
        _filters[n_mels] = FeatureExtractor.get_mel_filters(SR, N_FFT, n_mels).astype(np.float32)
    return _filters[n_mels]


def compute(audio: np.ndarray, n_mels: int) -> dict:
    """Return the log-Mel spectrogram and every intermediate step."""
    x = np.pad(audio.astype(np.float32), (0, HOP))               # 1. Whisper pads 10 ms
    padded = np.pad(x, N_FFT // 2, mode="reflect")                # 2. centre the first frame
    n_frames = 1 + (len(padded) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    window = np.hanning(N_FFT + 1)[:-1].astype(np.float32)        # 3. periodic Hann window
    frames = padded[idx] * window                                 # (T, 400)
    power = np.abs(np.fft.rfft(frames, axis=1)) ** 2              # 4. FFT -> power (T, 201)
    power = power[:-1]                                            #    Whisper drops last frame
    frames = frames[:-1]
    mel = mel_filters(n_mels) @ power.T                           # 5. (n_mels, T)
    log = np.log10(np.maximum(mel, 1e-10))                        # 6. log compression
    floor = log.max() - 8.0
    log = np.maximum(log, floor)                                  # 7. keep 8 decades (80 dB)
    log = (log + 4.0) / 4.0                                       # 8. scale for the network
    return {"log_mel": log.astype(np.float32), "frames": frames, "power": power,
            "mel": mel, "window": window, "clamp_floor": float(floor)}


# ------------------------------------------------------------------ for the UI
def _quantize(a: np.ndarray) -> tuple[str, float, float]:
    lo, hi = float(a.min()), float(a.max())
    q = np.round((a - lo) / ((hi - lo) or 1) * 255).astype(np.uint8)
    return base64.b64encode(q.tobytes()).decode(), round(lo, 3), round(hi, 3)


def _pool_time(a: np.ndarray, max_cols: int) -> np.ndarray:
    """Max-pool along time so long recordings still fit the screen."""
    t = a.shape[1]
    if t <= max_cols:
        return a
    k = int(np.ceil(t / max_cols))
    pad = (-t) % k
    a = np.pad(a, ((0, 0), (0, pad)), mode="edge")
    return a.reshape(a.shape[0], -1, k).max(axis=2)


def visualize(audio: np.ndarray, n_mels: int, reference: np.ndarray | None = None) -> dict:
    f = compute(audio, n_mels)
    log = f["log_mel"]
    T = log.shape[1]

    # The loudest frame - we show its full journey through the steps.
    k = int(np.argmax(f["power"].sum(axis=1)))
    power_db = 10 * np.log10(f["power"][k] + 1e-10)
    mel_db = 10 * np.log10(f["mel"][:, k] + 1e-10)

    spec, lo, hi = _quantize(_pool_time(log, 900))
    filt, _, _ = _quantize(mel_filters(n_mels))
    out = {
        "n_mels": n_mels, "frames": T, "hop_ms": HOP / SR * 1000, "win_ms": N_FFT / SR * 1000,
        "n_fft": N_FFT, "fft_bins": N_FFT // 2 + 1, "samples": int(len(audio)),
        "spectrogram": {"data": spec, "rows": n_mels, "cols": _pool_time(log, 900).shape[1], "min": lo, "max": hi},
        "filters": {"data": filt, "rows": n_mels, "cols": N_FFT // 2 + 1},
        "clamp_floor": round(f["clamp_floor"], 3),
        "example": {
            "frame": k, "time_s": round(k * HOP / SR, 2),
            "samples": np.round(f["frames"][k][::4], 4).tolist(),       # windowed waveform (100 pts)
            "window": np.round(f["window"][::4], 3).tolist(),
            "power_db": np.round(power_db, 1).tolist(),                 # 201 FFT bins
            "mel_db": np.round(mel_db, 1).tolist(),                     # n_mels values
            "log_mel": np.round(log[:, k], 3).tolist(),                 # final network input
        },
        "padded_to_frames": 3000,  # Whisper always looks at a 30 s window
    }
    if reference is not None:  # proof that our implementation equals Whisper's
        n = min(reference.shape[1], T)
        out["max_abs_diff_vs_whisper"] = float(np.abs(reference[:, :n] - log[:, :n]).max())
    return out
