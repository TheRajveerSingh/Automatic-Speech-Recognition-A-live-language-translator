"""Our audio front-end (asr/audio.py), tested on synthetic signals with known answers."""

import io
import shutil

import numpy as np
import pytest
from scipy.io import wavfile

from asr.audio import (SR, NoSpeechError, detect_speech, frame_energies_db, highpass, normalize,
                       preprocess, remove_dc)

rng = np.random.default_rng(0)


def tone(seconds, freq=300.0, amp=0.3):
    t = np.arange(int(SR * seconds)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def noise(seconds, amp=0.003):
    return (amp * rng.standard_normal(int(SR * seconds))).astype(np.float32)


def test_remove_dc():
    x = tone(1) + 0.2
    assert abs(float(np.mean(remove_dc(x)))) < 1e-6


def test_highpass_removes_rumble_but_keeps_speech_band():
    rms = lambda a: float(np.sqrt(np.mean(a[SR // 2:] ** 2)))  # skip filter warm-up
    rumble, voice = tone(2, 30), tone(2, 300)
    assert rms(highpass(rumble)) < 0.05 * rms(rumble)   # 30 Hz: mostly gone
    assert rms(highpass(voice)) > 0.95 * rms(voice)     # 300 Hz: untouched


def test_normalize_reaches_target_peak():
    y, gain = normalize(tone(1, amp=0.1))
    assert abs(20 * np.log10(np.max(np.abs(y))) - (-1.0)) < 0.05
    assert gain > 0


def test_normalize_never_boosts_more_than_30_db():
    _, gain = normalize(noise(1, amp=1e-4))  # near-silence must not be blown up into loud noise
    assert gain == pytest.approx(30.0)


def test_vad_finds_the_speech_in_the_middle():
    x = np.concatenate([noise(1), tone(1) + noise(1), noise(1)])
    speech, noise_db, threshold = detect_speech(frame_energies_db(x))
    frames = len(speech)
    assert speech[frames // 3 + 2: 2 * frames // 3 - 2].all()   # the tone is speech
    assert not speech[:frames // 4].any()                     # leading noise is not
    assert threshold > noise_db


def test_vad_ignores_digital_silence_when_estimating_noise():
    # exact zeros (from codecs / TTS) once dragged the noise floor to -200 dB (bug)
    x = np.concatenate([np.zeros(SR, dtype=np.float32), noise(1), tone(1) + noise(1)])
    _, noise_db, _ = detect_speech(frame_energies_db(x))
    assert -70 < noise_db < -40


def to_wav_bytes(x):
    buf = io.BytesIO()
    wavfile.write(buf, SR, (x * 32767).astype(np.int16))
    return buf.getvalue()


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@needs_ffmpeg
def test_preprocess_trims_silence_and_reports():
    x = np.concatenate([noise(1.5), tone(2) + noise(2), noise(1.5)])
    clean, report, viz = preprocess(to_wav_bytes(x))
    assert report.input_seconds == pytest.approx(5.0, abs=0.05)
    assert 2.0 <= report.speech_seconds <= 3.0      # ~2 s of tone + 250 ms padding each side
    assert report.snr_db > 20
    assert not report.clipped
    assert viz["trim"][0] == pytest.approx(1.25, abs=0.1)


@needs_ffmpeg
def test_preprocess_rejects_recordings_without_speech():
    with pytest.raises(NoSpeechError):
        preprocess(to_wav_bytes(noise(2)))
