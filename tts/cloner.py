"""Speak in the user's own voice with XTTS-v2 (zero-shot voice cloning, local GPU).

How it works:
  1. From your reference recording XTTS computes two things once:
       - a speaker embedding (512 numbers describing your timbre), and
       - "GPT conditioning latents" (32 vectors capturing your speaking style).
     We save both to voices/<id>/latents.pt so this is done only once.
  2. For each translation, XTTS's GPT predicts audio tokens for the text
     conditioned on those latents, and a HiFi-GAN decoder turns them into a
     24 kHz waveform - in the target language, with your voice.

Optional: requires `pip install -r requirements-voice.txt`.
Model licence: Coqui Public Model License (non-commercial use).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

import numpy as np

import config

# coqui's own config/cache files go here. NOTE: coqui 0.28 downloads the XTTS
# weights (1.75 GB) through Hugging Face into
# ~/.cache/huggingface/hub/models--tts-hub--XTTS-v2 - delete that to free the space.
os.environ.setdefault("TTS_HOME", str(config.MODELS_DIR))
# The user accepted the CPML (non-commercial) licence when choosing XTTS for this project.
os.environ.setdefault("COQUI_TOS_AGREED", "1")

XTTS_SR = 24_000
MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
# our language code -> XTTS language code
XTTS_LANGS = {"en": "en", "es": "es", "fr": "fr", "de": "de", "it": "it", "pt": "pt", "pl": "pl",
              "tr": "tr", "ru": "ru", "nl": "nl", "cs": "cs", "ar": "ar", "zh": "zh-cn", "ja": "ja",
              "hu": "hu", "ko": "ko", "hi": "hi"}

_model = None
_lock = threading.Lock()
_latents: dict[str, tuple] = {}


def available() -> bool:
    try:
        import TTS  # noqa: F401
        import torch
        return torch.cuda.is_available()
    except Exception:  # noqa: BLE001
        return False


def supports(language: str) -> bool:
    return language in XTTS_LANGS


def is_loaded() -> bool:
    return _model is not None


# ----------------------------------------------------------------------------- model
def load():
    global _model
    with _lock:
        if _model is None:
            import torch
            from TTS.api import TTS
            tts = TTS(MODEL_NAME, progress_bar=False).to("cuda" if torch.cuda.is_available() else "cpu")
            _model = tts.synthesizer.tts_model
    return _model


# ----------------------------------------------------------------------------- voices on disk
def voice_dir(voice_id: str) -> Path:
    if not voice_id.isalnum():
        raise ValueError("bad voice id")
    return config.VOICES_DIR / voice_id


def list_voices() -> list[dict]:
    out = []
    for meta in sorted(config.VOICES_DIR.glob("*/meta.json")):
        try:
            out.append(json.loads(meta.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    return out


def voice_name(voice_id: str) -> str:
    try:
        return json.loads((voice_dir(voice_id) / "meta.json").read_text(encoding="utf-8"))["name"]
    except Exception:  # noqa: BLE001
        return "My voice"


def delete_voice(voice_id: str) -> None:
    _latents.pop(voice_id, None)
    shutil.rmtree(voice_dir(voice_id), ignore_errors=True)


def save_reference(audio_24k: np.ndarray, name: str, meta: dict) -> str:
    """Store the cleaned reference recording and its metadata; returns the new voice id."""
    from scipy.io import wavfile
    voice_id = uuid.uuid4().hex[:10]
    d = voice_dir(voice_id)
    d.mkdir(parents=True)
    wavfile.write(d / "reference.wav", XTTS_SR, (np.clip(audio_24k, -1, 1) * 32767).astype(np.int16))
    meta = {"id": voice_id, "name": name, "created": time.strftime("%Y-%m-%d %H:%M"), **meta}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return voice_id


# ----------------------------------------------------------------------------- cloning
def compute_latents(voice_id: str) -> dict:
    """Run XTTS's speaker encoders on the reference audio (done once per voice)."""
    import torch
    from scipy.io import wavfile

    model = load()
    sr, pcm = wavfile.read(voice_dir(voice_id) / "reference.wav")
    audio = torch.from_numpy(pcm.astype(np.float32) / 32768.0).unsqueeze(0)  # (1, samples)
    t0 = time.perf_counter()
    with _lock, torch.inference_mode():
        # same steps as Xtts.get_conditioning_latents, but fed our own audio tensor
        gpt_latent = model.get_gpt_cond_latents(audio.to(model.device), sr, length=30, chunk_length=6)
        speaker_emb = model.get_speaker_embedding(audio.to(model.device), sr)  # resamples to 16 kHz itself
    torch.save({"gpt": gpt_latent.cpu(), "spk": speaker_emb.cpu()}, voice_dir(voice_id) / "latents.pt")
    _latents[voice_id] = (gpt_latent, speaker_emb)
    return {"ms": round((time.perf_counter() - t0) * 1000),
            "gpt_latent_shape": list(gpt_latent.shape), "speaker_embedding_size": int(speaker_emb.numel())}


def _get_latents(voice_id: str):
    if voice_id not in _latents:
        import torch
        path = voice_dir(voice_id) / "latents.pt"
        if not path.exists():
            compute_latents(voice_id)
        else:
            data = torch.load(path, map_location="cpu")
            model = load()
            _latents[voice_id] = (data["gpt"].to(model.device), data["spk"].to(model.device))
    return _latents[voice_id]


# ----------------------------------------------------------------------------- number spelling
# XTTS turns digits into words with the num2words library, which has no Hindi or
# Chinese support (it crashes on "42"). For those languages we spell numbers ourselves.
HI_0_99 = (
    "शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस "
    "बीस इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस "
    "पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस "
    "सैंतालीस अड़तालीस उनचास पचास इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ "
    "इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर "
    "पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी "
    "सत्तासी अट्ठासी नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पंचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे"
).split()
assert len(HI_0_99) == 100


def hindi_number(n: int) -> str:
    """Indian numbering: करोड़ (10^7), लाख (10^5), हज़ार, सौ, then 0-99 from the table."""
    if n < 100:
        return HI_0_99[n]
    parts = []
    for value, word in ((10**7, "करोड़"), (10**5, "लाख"), (1000, "हज़ार"), (100, "सौ")):
        if n >= value:
            parts.append(f"{hindi_number(n // value)} {word}")
            n %= value
    if n:
        parts.append(HI_0_99[n])
    return " ".join(parts)


ZH_DIGITS = "零一二三四五六七八九"


def _zh_group(g: int) -> str:  # 1..9999
    out, zero = "", False
    for unit, div in (("千", 1000), ("百", 100), ("十", 10), ("", 1)):
        d = g // div % 10
        if d == 0:
            zero = zero or bool(out)
        else:
            if zero:
                out += "零"
                zero = False
            out += ZH_DIGITS[d] + unit
    return out


def chinese_number(n: int) -> str:
    """Groups of 4 digits joined by 万/亿, with 零 marking skipped places (105 = 一百零五)."""
    if n == 0:
        return "零"
    groups = []
    while n:
        groups.append(n % 10000)
        n //= 10000
    out, gap = "", False
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if g == 0:
            gap = gap or bool(out)
            continue
        if out and (gap or g < 1000):
            out += "零"
        out += _zh_group(g) + ["", "万", "亿", "万亿"][i]
        gap = False
    return out[1:] if out.startswith("一十") else out  # 12 = 十二, not 一十二


_NUM_RE = re.compile(r"\d+(?:,\d{2,3})*(?:\.\d+)?")


def spell_numbers(text: str, language: str) -> str:
    if language not in ("hi", "zh"):
        return text
    text = text.translate(str.maketrans("०१२३४५६७८९", "0123456789"))  # Devanagari digits too
    to_words = hindi_number if language == "hi" else chinese_number
    point = " दशमलव " if language == "hi" else "点"
    joiner = " " if language == "hi" else ""

    def repl(m: re.Match) -> str:
        whole, _, frac = m.group(0).replace(",", "").partition(".")
        words = to_words(int(whole))
        if frac:
            words += point + joiner.join(to_words(int(d)) for d in frac)
        return f" {words} " if language == "hi" else words

    return re.sub(r"\s+", " ", _NUM_RE.sub(repl, text)).strip()


def similarity(voice_id: str, wav_path: Path) -> float:
    """Cosine similarity between the speaker embeddings of your recording and a generated file.

    Uses the same speaker encoder XTTS clones with. Measured on this setup:
    reference vs itself 1.00, clones 0.42-0.51 (lower across languages),
    different real speakers 0.10-0.19. So >= 0.35 means "clearly your voice print".
    """
    import torch
    from scipy.io import wavfile

    model = load()
    _, ref_emb = _get_latents(voice_id)
    sr, pcm = wavfile.read(wav_path)
    audio = torch.from_numpy(pcm.astype(np.float32) / 32768.0).unsqueeze(0)
    with _lock, torch.inference_mode():
        out_emb = model.get_speaker_embedding(audio.to(model.device), sr)
    return round(float(torch.nn.functional.cosine_similarity(ref_emb.flatten(), out_emb.flatten(), dim=0)), 3)


def synthesize(text: str, language: str, voice_id: str, rate: int = 0) -> Path:
    import torch
    from scipy.io import wavfile

    model = load()
    gpt_latent, speaker_emb = _get_latents(voice_id)
    text = spell_numbers(text, language)
    with _lock, torch.inference_mode():
        out = model.inference(
            text, XTTS_LANGS[language], gpt_latent, speaker_emb,
            temperature=0.7, speed=max(0.5, min(2.0, 1 + rate / 100)), enable_text_splitting=True,
        )
    wav = np.asarray(out["wav"], dtype=np.float32)
    path = config.OUTPUT_DIR / f"{uuid.uuid4().hex[:12]}_{language}_me.wav"
    wavfile.write(path, XTTS_SR, (np.clip(wav, -1, 1) * 32767).astype(np.int16))
    return path
