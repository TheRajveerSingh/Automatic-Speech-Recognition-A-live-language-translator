"""Text-to-speech dispatcher.

Voice ids:
    "edge:<ShortName>"  - Microsoft Edge neural voice (free, needs internet)
    "clone:<voice_id>"  - the user's own cloned voice (XTTS-v2, local GPU)
"""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path

import edge_tts

import config

_edge_cache: list[dict] | None = None


async def edge_voices() -> list[dict]:
    global _edge_cache
    if _edge_cache is None:
        _edge_cache = await edge_tts.list_voices()
    return _edge_cache


def _pretty(short_name: str) -> str:
    # "hi-IN-MadhurNeural" -> "Madhur",  "en-US-AndrewMultilingualNeural" -> "Andrew Multilingual"
    core = short_name.split("-", 2)[-1].replace("Neural", "")
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", core)


async def voices_for(language: str) -> list[dict]:
    out = []
    for v in await edge_voices():
        loc = v["Locale"]
        if not loc.startswith(language + "-") or loc == "zh-HK":
            continue
        out.append({
            "id": f"edge:{v['ShortName']}", "name": _pretty(v["ShortName"]),
            "gender": v["Gender"], "locale": loc, "engine": "edge",
            "default": v["ShortName"] == config.LANGUAGES[language]["voice"],
        })
    main_locale = config.LANGUAGES[language]["voice"].rsplit("-", 1)[0]  # e.g. "hi-IN"
    out.sort(key=lambda v: (not v["default"], v["locale"] != main_locale, v["locale"], v["gender"], v["name"]))
    return out


async def synthesize(text: str, language: str, voice: str | None = None,
                     rate: int = 0, pitch: int = 0) -> tuple[Path, dict]:
    voice = voice or f"edge:{config.LANGUAGES[language]['voice']}"
    engine, _, name = voice.partition(":")

    fallback, reason = False, None
    if engine == "clone":
        from tts import cloner  # imported lazily: needs the optional voice packages
        if not (config.VOICES_DIR / name / "reference.wav").exists():
            reason = "that saved voice was deleted - pick another one"
        elif cloner.supports(language):
            try:
                path = await asyncio.to_thread(cloner.synthesize, text, language, name, rate)
                return path, {"engine": "XTTS-v2 (your voice)", "voice": cloner.voice_name(name)}
            except Exception as e:  # noqa: BLE001 - never lose the audio: fall back to a neural voice
                print(f"[tts] own-voice synthesis failed, falling back: {e!r}")
                reason = f"your voice failed ({type(e).__name__}: {e})"[:200]
        else:
            reason = "your voice doesn't support this language"
        name = config.LANGUAGES[language]["voice"]
        fallback = True

    path = config.OUTPUT_DIR / f"{uuid.uuid4().hex[:12]}_{language}.mp3"
    await edge_tts.Communicate(text, name, rate=f"{rate:+d}%", pitch=f"{pitch:+d}Hz").save(str(path))
    return path, {"engine": "Edge neural TTS", "voice": _pretty(name), "fallback": fallback, "fallback_reason": reason}
