"""Audio front-end: decode -> clean -> detect speech -> trim.

Every ASR system has a front-end like this. Whisper expects 16 kHz mono float
audio; real microphone input is messy (DC offset, rumble, quiet levels, long
silences that make Whisper hallucinate). This module fixes those, and reports
measurements so the UI can show what happened.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, asdict

import numpy as np
from scipy.signal import butter, sosfilt, sosfreqz, welch

import config

SR = config.SAMPLE_RATE


class NoSpeechError(Exception):
    """Raised when the recording contains no detectable speech."""


@dataclass
class AudioReport:
    input_seconds: float
    speech_seconds: float
    speech_ratio: float      # fraction of frames classified as speech
    noise_floor_db: float    # loudness of the quietest frames (background)
    speech_level_db: float   # typical loudness of speech frames
    snr_db: float            # speech level minus noise floor
    gain_db: float           # how much we amplified during normalisation
    clipped: bool            # input hit full scale (distortion likely)

    def to_dict(self) -> dict:
        return {k: round(v, 2) if isinstance(v, float) else v for k, v in asdict(self).items()}


# ---------------------------------------------------------------- decoding
def decode(data: bytes, sr: int = SR) -> np.ndarray:
    """Decode any audio format (webm/opus from the browser, wav, mp3...) to mono float32 at `sr` Hz."""
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
           "-i", "pipe:0", "-ac", "1", "-ar", str(sr), "-f", "f32le", "pipe:1"]
    proc = subprocess.run(cmd, input=data, capture_output=True)
    if proc.returncode != 0:
        raise ValueError(f"Could not decode audio: {proc.stderr.decode(errors='ignore')[:200]}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def decode_file(path: str, sr: int = SR) -> np.ndarray:
    """Like decode() but from a file on disk - needed for MP4/MOV videos, whose index is
    often at the END of the file, so ffmpeg can't read them through a pipe."""
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
           "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "pipe:1"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise ValueError(f"Could not decode audio: {proc.stderr.decode(errors='ignore')[:200]}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


# ---------------------------------------------------------------- cleaning
def remove_dc(x: np.ndarray) -> np.ndarray:
    return x - np.mean(x)


def highpass(x: np.ndarray, cutoff: float = config.HIGHPASS_HZ, sr: int = SR) -> np.ndarray:
    """4th-order Butterworth high-pass: removes rumble/hum below speech range."""
    sos = butter(4, cutoff, btype="highpass", fs=sr, output="sos")
    return sosfilt(sos, x).astype(np.float32)


def normalize(x: np.ndarray, target_dbfs: float = config.TARGET_PEAK_DBFS,
              max_gain_db: float = 30.0) -> tuple[np.ndarray, float]:
    """Peak-normalise, but never boost more than max_gain_db (would just amplify noise)."""
    peak = float(np.max(np.abs(x))) or 1e-9
    gain_db = min(target_dbfs - 20 * np.log10(peak), max_gain_db)
    return (x * 10 ** (gain_db / 20)).astype(np.float32), gain_db


# ---------------------------------------------------------------- VAD
def frame_energies_db(x: np.ndarray, frame_ms: int = config.VAD_FRAME_MS) -> np.ndarray:
    n = int(SR * frame_ms / 1000)
    frames = len(x) // n
    if frames == 0:
        return np.array([-100.0])
    rms = np.sqrt(np.mean(x[: frames * n].reshape(frames, n) ** 2, axis=1))
    return 20 * np.log10(rms + 1e-10)


def detect_speech(db: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Energy VAD with an adaptive threshold.

    noise floor = 10th percentile of frame energy (the quiet parts),
    threshold   = noise floor + 10 dB (but at least -55 dBFS),
    then a 'hangover' keeps short gaps between words marked as speech.
    """
    # Ignore digitally-silent frames (exact zeros from codecs/TTS): they'd drag
    # the noise estimate to -200 dB. Real mic noise is always above -90 dB.
    audible = db[db > -90]
    noise = float(np.percentile(audible, 10)) if audible.size else -90.0
    threshold = max(noise + 10.0, -55.0)
    speech = db > threshold
    # hangover: fill gaps shorter than ~200 ms
    hang = max(1, 200 // config.VAD_FRAME_MS)
    idx = np.flatnonzero(speech)
    for a, b in zip(idx[:-1], idx[1:]):
        if 1 < b - a <= hang:
            speech[a:b] = True
    return speech, noise, threshold


# ---------------------------------------------------------------- visualisation data
def envelope(x: np.ndarray, buckets: int = 600) -> dict:
    """Min/max per bucket - enough to draw a waveform without sending every sample."""
    n = max(1, len(x) // buckets)
    usable = x[: (len(x) // n) * n].reshape(-1, n)
    return {"min": np.round(usable.min(axis=1), 3).tolist(), "max": np.round(usable.max(axis=1), 3).tolist()}


VIZ_FREQS = np.geomspace(20, 8000, 120)


def avg_spectrum_db(x: np.ndarray) -> list[float]:
    """Average power spectrum (Welch's method), sampled on a log frequency axis."""
    f, p = welch(x, fs=SR, nperseg=1024)
    return np.round(10 * np.log10(np.interp(VIZ_FREQS, f, p) + 1e-12), 1).tolist()


def filter_response_db() -> list[float]:
    sos = butter(4, config.HIGHPASS_HZ, btype="highpass", fs=SR, output="sos")
    _, h = sosfreqz(sos, worN=VIZ_FREQS, fs=SR)
    return np.round(20 * np.log10(np.abs(h) + 1e-12), 1).tolist()


# ---------------------------------------------------------------- pipeline
def preprocess(data: bytes) -> tuple[np.ndarray, AudioReport, dict]:
    raw = decode(data)
    if len(raw) < SR * 0.3:
        raise NoSpeechError("Recording is shorter than 0.3 s.")
    clipped = bool(np.mean(np.abs(raw) > 0.99) > 0.001)

    dc_offset = float(np.mean(raw))
    filtered = highpass(remove_dc(raw))
    peak_before = float(np.max(np.abs(filtered)))
    x, gain_db = normalize(filtered)

    db = frame_energies_db(x)
    speech, noise_db, threshold_db = detect_speech(db)
    if not speech.any():
        raise NoSpeechError("No speech detected - try speaking closer to the mic.")

    # Trim leading/trailing silence, keeping some padding around the speech.
    n = int(SR * config.VAD_FRAME_MS / 1000)
    pad = int(SR * config.VAD_PAD_MS / 1000)
    idx = np.flatnonzero(speech)
    start = max(0, idx[0] * n - pad)
    end = min(len(x), (idx[-1] + 1) * n + pad)
    trimmed = x[start:end]

    speech_level = float(np.median(db[speech]))
    report = AudioReport(
        input_seconds=len(raw) / SR,
        speech_seconds=len(trimmed) / SR,
        speech_ratio=float(speech.mean()),
        noise_floor_db=noise_db,
        speech_level_db=speech_level,
        snr_db=speech_level - noise_db,
        gain_db=float(gain_db),
        clipped=clipped,
    )
    viz = {
        "duration": len(raw) / SR,
        "raw": envelope(raw),
        "clean": envelope(x),
        "frame_ms": config.VAD_FRAME_MS,
        "frame_db": np.round(np.maximum(db, -100), 1).tolist(),
        "speech": speech.astype(int).tolist(),
        "noise_db": round(noise_db, 2),
        "threshold_db": round(threshold_db, 2),
        "trim": [round(float(start) / SR, 3), round(float(end) / SR, 3)],
        "freqs": np.round(VIZ_FREQS, 1).tolist(),
        "spectrum_before": avg_spectrum_db(raw),
        "spectrum_after": avg_spectrum_db(filtered),
        "filter_db": filter_response_db(),
        "highpass_hz": config.HIGHPASS_HZ,
        "dc_offset": round(dc_offset, 5),
        "peak_before": round(peak_before, 4),
        "peak_after": round(float(np.max(np.abs(x))), 4),
        "speech_frames": int(speech.sum()),
        "total_frames": int(len(speech)),
    }
    return trimmed, report, viz
