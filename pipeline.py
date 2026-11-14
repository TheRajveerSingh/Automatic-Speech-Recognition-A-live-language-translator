"""Runs the stages in order and reports progress after each one.

    audio bytes -> [preprocess] -> [recognize] -> [translate] -> [speak]

Each stage yields event dicts, which the server streams to the browser so the
UI can light up each step and draw the "Under the hood" visualisations.

Terminal test:  python pipeline.py path/to/audio.wav hi
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

import config
from asr.audio import NoSpeechError, decode, envelope, preprocess
from asr.transcriber import Transcriber
from translation.translator import translate_stream
from tts.speaker import synthesize

transcriber = Transcriber()  # shared: the Whisper model loads once


def _event(stage: str, status: str, t0: float | None = None, **data) -> dict:
    ev = {"stage": stage, "status": status, **data}
    if t0 is not None:
        ev["ms"] = round((time.perf_counter() - t0) * 1000)
    return ev


async def speak(text: str, target: str, voice: str | None, rate: int, pitch: int) -> AsyncIterator[dict]:
    yield _event("speak", "running")
    t0 = time.perf_counter()
    try:
        path, info = await synthesize(text, target, voice, rate, pitch)
        samples = await asyncio.to_thread(decode, path.read_bytes())
    except Exception as e:  # noqa: BLE001
        yield _event("speak", "error", t0, error=f"Speech synthesis failed: {e}")
        return
    yield _event("speak", "done", t0, audio_url=f"/outputs/{path.name}", **info,
                 rate=rate, pitch=pitch, characters=len(text),
                 duration=round(len(samples) / 16000, 2), envelope=envelope(samples, 500))


async def translate_and_speak(text: str, source: str, target: str, voice: str | None = None,
                              rate: int = 0, pitch: int = 0) -> AsyncIterator[dict]:
    yield _event("translate", "running")
    t0 = time.perf_counter()
    final = None
    try:
        async for ev in translate_stream(text, source, target):
            if ev.get("done"):
                final = ev
            else:
                yield _event("translate", "token", delta=ev["delta"])
    except Exception as e:  # noqa: BLE001
        yield _event("translate", "error", t0, error=f"Translation failed: {e}. Is Ollama running?")
        return
    yield _event("translate", "done", t0, source=source, target=target, input=text, **final)

    async for ev in speak(final["text"], target, voice, rate, pitch):
        yield ev


async def run(audio: bytes, target: str, source: str | None = None, voice: str | None = None,
              rate: int = 0, pitch: int = 0) -> AsyncIterator[dict]:
    yield _event("preprocess", "running")
    t0 = time.perf_counter()
    try:
        clean, report, viz = await asyncio.to_thread(preprocess, audio)
    except (NoSpeechError, ValueError) as e:
        yield _event("preprocess", "error", t0, error=str(e))
        return
    yield _event("preprocess", "done", t0, report=report.to_dict(), viz=viz)

    yield _event("recognize", "running")
    t0 = time.perf_counter()
    mel = await asyncio.to_thread(transcriber.mel_visualization, clean)
    mel_ms = round((time.perf_counter() - t0) * 1000)
    yield _event("features", "done", mel=mel, ms=mel_ms)
    result = await asyncio.to_thread(transcriber.transcribe, clean, source)
    if not result["text"]:
        yield _event("recognize", "error", t0, error="Whisper heard no words.")
        return
    yield _event("recognize", "done", t0, **result)

    async for ev in translate_and_speak(result["text"], result["language"], target, voice, rate, pitch):
        yield ev


async def conversation_turn(audio: bytes, lang_a: str, lang_b: str, side: str = "auto",
                            voice_a: str | None = None, voice_b: str | None = None,
                            rate: int = 0) -> AsyncIterator[dict]:
    """One turn of a two-person conversation.

    side = "a" / "b" (push-to-talk: we know who spoke) or "auto" (hands-free:
    Whisper decides which of the two languages it heard). The words are then
    translated into the OTHER person's language and spoken with the speaker's
    chosen voice (e.g. your cloned voice speaking Spanish).
    """
    t_start = time.perf_counter()
    yield _event("listen", "running")
    t0 = time.perf_counter()
    try:
        clean, report, _ = await asyncio.to_thread(preprocess, audio)
    except (NoSpeechError, ValueError) as e:
        yield _event("listen", "error", t0, error=str(e))
        return
    yield _event("listen", "done", t0, seconds=report.speech_seconds, snr_db=report.snr_db)

    if side in ("a", "b"):
        src = lang_a if side == "a" else lang_b
        yield _event("detect", "done", language=src, side=side, method="push-to-talk", ms=0)
    else:
        t0 = time.perf_counter()
        det = await asyncio.to_thread(transcriber.detect_between, clean, [lang_a, lang_b])
        src = det["language"]
        side = "a" if src == lang_a else "b"
        yield _event("detect", "done", t0, side=side, method="auto", **det)
    tgt = lang_b if side == "a" else lang_a
    voice = voice_a if side == "a" else voice_b

    yield _event("recognize", "running")
    t0 = time.perf_counter()
    result = await asyncio.to_thread(transcriber.transcribe, clean, src)
    if not result["text"]:
        yield _event("recognize", "error", t0, error="No words recognised.")
        return
    yield _event("recognize", "done", t0, text=result["text"], language=src, confidence=result["confidence"],
                 words=result["words"])

    async for ev in translate_and_speak(result["text"], src, tgt, voice, rate, 0):
        if ev["stage"] == "speak" and ev["status"] == "done":
            ev["total_ms"] = round((time.perf_counter() - t_start) * 1000)
            ev.pop("envelope", None)
        yield ev


async def _iterate_in_thread(make_generator) -> AsyncIterator:
    """Run a blocking generator (Whisper decoding) in a worker thread, yielding items as they come."""
    loop, queue, done = asyncio.get_running_loop(), asyncio.Queue(), object()

    def work():
        try:
            for item in make_generator():
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except Exception as e:  # noqa: BLE001 - re-raised in the async side
            loop.call_soon_threadsafe(queue.put_nowait, e)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, done)

    future = loop.run_in_executor(None, work)
    while (item := await queue.get()) is not done:
        if isinstance(item, Exception):
            raise item
        yield item
    await future


MAX_SUMMARY_SECONDS = 3 * 3600


async def summarize_recording(path: str, language: str | None = None, summary_lang: str = "same",
                              speak_summary: bool = False, voice: str | None = None) -> AsyncIterator[dict]:
    """Long recording -> streamed transcript -> map-reduce summary (-> spoken TL;DR)."""
    from asr.audio import SR, decode_file, highpass, normalize, remove_dc
    from summarize import summarizer as sm

    yield _event("prepare", "running")
    t0 = time.perf_counter()
    try:
        raw = await asyncio.to_thread(decode_file, path)
    except ValueError as e:
        yield _event("prepare", "error", t0, error=str(e))
        return
    duration = len(raw) / SR
    if duration < 2:
        yield _event("prepare", "error", t0, error="The recording is shorter than 2 seconds.")
        return
    if duration > MAX_SUMMARY_SECONDS:
        yield _event("prepare", "error", t0, error="Recordings longer than 3 hours aren't supported.")
        return
    # clean, but DON'T trim silence: timestamps must match the original file for chapter jumps
    audio, gain = await asyncio.to_thread(lambda: normalize(highpass(remove_dc(raw))))
    yield _event("prepare", "done", t0, duration=round(duration, 1), gain_db=round(float(gain), 1))

    yield _event("transcribe", "running")
    t0 = time.perf_counter()
    segments, info = [], {}
    try:
        async for item in _iterate_in_thread(lambda: transcriber.transcribe_stream(audio, language)):
            if item["type"] == "info":
                info = item
                yield _event("transcribe", "info", **item)
            else:
                segments.append(item)
                elapsed = time.perf_counter() - t0
                yield _event("transcribe", "progress", segment=item, pct=round(min(1.0, item["end"] / duration), 4),
                             elapsed_s=round(elapsed, 1))
    except Exception as e:  # noqa: BLE001
        yield _event("transcribe", "error", t0, error=f"Transcription failed: {e}")
        return
    if not segments:
        yield _event("transcribe", "error", t0, error="No speech was found in the recording.")
        return
    elapsed = time.perf_counter() - t0
    words = sum(len(s["text"].split()) for s in segments)
    yield _event("transcribe", "done", t0, segments=segments, words=words, language=info.get("language"),
                 language_probability=info.get("language_probability"), speed_x=round(duration / max(elapsed, 1e-6), 1),
                 speech_duration=info.get("speech_duration"))

    out_lang = info.get("language") if summary_lang == "same" else summary_lang
    lang_name = config.LANGUAGES.get(out_lang, {}).get("name", out_lang)
    chunk_words = sm.chunk_size_for(words)
    chunks = sm.chunk_segments(segments, chunk_words)
    yield _event("summarize", "running", chunks=len(chunks), chunk_words=chunk_words, language=out_lang)
    t0 = time.perf_counter()
    parts = []
    try:
        for i, c in enumerate(chunks, 1):
            system, user = sm.map_prompt(lang_name, i, len(chunks), c)
            res, stats = await sm.ask_json(system, user, sm.MAP_SCHEMA)
            part = {"start": c["start"], "end": c["end"], "words": c["words"], "title": res.get("title", "").strip(),
                    "notes": res.get("notes", []), "action_items": res.get("action_items", []), "stats": stats}
            parts.append(part)
            yield _event("summarize", "map", i=i, n=len(chunks), part=part)
        system, user = sm.reduce_prompt(lang_name, parts)
        final, stats = await sm.ask_json(system, user, sm.REDUCE_SCHEMA)
    except Exception as e:  # noqa: BLE001
        yield _event("summarize", "error", t0, error=f"Summarising failed: {e}. Is Ollama running?")
        return
    yield _event("summarize", "done", t0, language=out_lang, tldr=final.get("tldr", ""),
                 key_points=final.get("key_points", []), action_items=final.get("action_items", []),
                 chapters=[{"start": p["start"], "title": p["title"]} for p in parts], parts=parts,
                 reduce_stats=stats, reduce_input_words=len(user.split()), transcript_words=words)

    if speak_summary and final.get("tldr") and out_lang in config.LANGUAGES:
        async for ev in speak(final["tldr"], out_lang, voice, 0, 0):
            ev.pop("envelope", None)
            yield ev


ENROLL_TEST_TEXT = {"en": "Hi! This is my cloned voice. Pretty cool, right?",
                    "hi": "नमस्ते! यह मेरी क्लोन की हुई आवाज़ है। कमाल है, है ना?"}


def _clean_reference(audio: bytes, trim: list[float]):
    """Reference audio for XTTS: our front-end (DC, high-pass, normalise, VAD trim) at 24 kHz."""
    from asr.audio import highpass, normalize, remove_dc
    from tts.cloner import XTTS_SR
    raw = decode(audio, XTTS_SR)
    x, _ = normalize(highpass(remove_dc(raw), sr=XTTS_SR))
    return x[int(trim[0] * XTTS_SR): int(trim[1] * XTTS_SR)]


async def enroll(audio: bytes, name: str, lang: str, script_text: str) -> AsyncIterator[dict]:
    """Quality-check a voice sample with our ASR, then build an XTTS voice profile."""
    from tts import cloner
    from tts.enroll import assess

    yield _event("analyse", "running")
    t0 = time.perf_counter()
    try:
        clean, report, viz = await asyncio.to_thread(preprocess, audio)
    except (NoSpeechError, ValueError) as e:
        yield _event("analyse", "error", t0, error=str(e))
        return
    yield _event("analyse", "done", t0, report=report.to_dict())

    yield _event("check", "running")
    t0 = time.perf_counter()
    result = await asyncio.to_thread(transcriber.transcribe, clean, lang)
    verdict = assess(report.to_dict(), script_text, result["text"], lang)
    yield _event("check", "done", t0, transcript=result["text"], **verdict)
    if not verdict["ok"]:
        yield _event("complete", "error", error="The recording didn't pass the checks - see the red items and try again.")
        return

    yield _event("profile", "running", first_time=not cloner.is_loaded())
    t0 = time.perf_counter()
    voice_id = None
    try:
        ref = await asyncio.to_thread(_clean_reference, audio, viz["trim"])
        voice_id = cloner.save_reference(ref, name, {
            "script_lang": lang, "seconds": round(len(ref) / cloner.XTTS_SR, 1),
            "snr_db": report.snr_db, "accuracy": verdict["accuracy"]})
        info = await asyncio.to_thread(cloner.compute_latents, voice_id)
    except Exception as e:  # noqa: BLE001
        if voice_id:
            cloner.delete_voice(voice_id)  # don't leave a half-built voice behind
        yield _event("profile", "error", t0, error=f"Building the voice failed: {e}")
        return
    yield _event("profile", "done", t0, voice_id=voice_id, **info)

    yield _event("test", "running")
    t0 = time.perf_counter()
    try:
        path = await asyncio.to_thread(cloner.synthesize, ENROLL_TEST_TEXT.get(lang, ENROLL_TEST_TEXT["en"]),
                                       lang, voice_id)
        sim = await asyncio.to_thread(cloner.similarity, voice_id, path)
    except Exception as e:  # noqa: BLE001
        cloner.delete_voice(voice_id)
        yield _event("test", "error", t0, error=f"Test synthesis failed: {e}")
        return
    yield _event("test", "done", t0, audio_url=f"/outputs/{path.name}", similarity=sim)
    yield _event("complete", "done", voice={"id": f"clone:{voice_id}", "name": name})


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 3:
        sys.exit("usage: python pipeline.py <audio file> <target language code>")

    async def main():
        data = open(sys.argv[1], "rb").read()
        async for ev in run(data, sys.argv[2]):
            if ev["status"] == "token":
                continue
            for k in ("words", "segments", "viz", "mel", "envelope", "system_prompt"):
                ev.pop(k, None)
            print(json.dumps(ev, ensure_ascii=False))

    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
