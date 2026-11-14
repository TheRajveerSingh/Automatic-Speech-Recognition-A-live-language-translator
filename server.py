"""Web server: serves the UI and streams pipeline progress to it.

Run:  conda activate asr-translate
      python server.py          -> open http://localhost:8000
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import pipeline
from eval import evaluate_wer
from translation.translator import warm_up
from tts import cloner, enroll, speaker

state = {"asr_ready": False, "llm_ready": False, "error": None, "clone_available": False}


async def _warm():
    """Load Whisper + the Ollama model in the background so the first request is fast."""
    state["clone_available"] = await asyncio.to_thread(cloner.available)
    try:
        await asyncio.to_thread(pipeline.transcriber.load)
        state["asr_ready"] = True
        await warm_up()
        state["llm_ready"] = True
        # If you have a saved voice, load XTTS now (~30 s, in the background) so the
        # first sentence in your voice - e.g. in a conversation - isn't slow.
        if state["clone_available"] and cloner.list_voices():
            await asyncio.to_thread(cloner.load)
            print("[warm-up] XTTS voice cloning model ready")
    except Exception as e:  # noqa: BLE001
        state["error"] = str(e)
        print(f"[warm-up] {e}")


def clean_outputs() -> int:
    """Delete generated audio older than OUTPUT_MAX_AGE_HOURS; returns how many files went."""
    cutoff = time.time() - config.OUTPUT_MAX_AGE_HOURS * 3600
    removed = 0
    for f in config.OUTPUT_DIR.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass  # file in use (e.g. being played) - try again next round
    return removed


async def _cleanup_loop():
    while True:
        n = await asyncio.to_thread(clean_outputs)
        if n:
            print(f"[cleanup] removed {n} old file(s) from outputs/")
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [asyncio.create_task(_warm()), asyncio.create_task(_cleanup_loop())]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Voice Translator", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=config.ROOT / "static"), name="static")
app.mount("/outputs", StaticFiles(directory=config.OUTPUT_DIR), name="outputs")


def ndjson(events):
    """Stream each event as one JSON line; the browser reads them as they arrive."""
    async def gen():
        async for ev in events:
            yield json.dumps(ev, ensure_ascii=False) + "\n"
    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.get("/")
async def index():
    return FileResponse(config.ROOT / "static" / "index.html")


@app.get("/api/status")
async def status():
    return {
        **state,
        "device": pipeline.transcriber.device,
        "asr_model": config.WHISPER_MODEL,
        "llm_model": config.OLLAMA_MODEL,
    }


@app.get("/api/languages")
async def languages():
    return [{"code": c, "name": l["name"]} for c, l in config.LANGUAGES.items()]


@app.get("/api/voices")
async def voices(lang: str):
    if lang not in config.LANGUAGES:
        raise HTTPException(404, "unknown language")
    mine = []
    if state["clone_available"]:
        mine = [{"id": f"clone:{v['id']}", "name": v["name"], "engine": "clone",
                 "supported": cloner.supports(lang)} for v in cloner.list_voices()]
    return mine + await speaker.voices_for(lang)


# ------------------------------------------------------------------ conversation mode
@app.post("/api/talk")
async def talk(audio: UploadFile = File(...), lang_a: str = Form(...), lang_b: str = Form(...),
               side: str = Form("auto"), voice_a: str = Form(""), voice_b: str = Form(""), rate: int = Form(0)):
    if lang_a not in config.LANGUAGES or lang_b not in config.LANGUAGES or lang_a == lang_b:
        raise HTTPException(400, "pick two different languages")
    if side not in ("auto", "a", "b"):
        raise HTTPException(400, "side must be auto, a or b")
    data = await audio.read()
    return ndjson(pipeline.conversation_turn(data, lang_a, lang_b, side, voice_a or None, voice_b or None, rate))


# ------------------------------------------------------------------ long-recording summaries
@app.post("/api/summarize")
async def summarize(audio: UploadFile = File(...), language: str = Form("auto"), summary_lang: str = Form("same"),
                    speak: bool = Form(False), voice: str = Form("")):
    if summary_lang != "same" and summary_lang not in config.LANGUAGES:
        raise HTTPException(400, "unknown summary language")
    # save to a temp file: video containers (mp4/mov) can't be decoded from a pipe
    suffix = Path(audio.filename or "upload").suffix[:10] or ".bin"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=config.OUTPUT_DIR, prefix="_upload_")
    try:
        while chunk := await audio.read(1 << 20):
            tmp.write(chunk)
    finally:
        tmp.close()

    async def events():
        try:
            async for ev in pipeline.summarize_recording(tmp.name, None if language == "auto" else language,
                                                         summary_lang, speak, voice or None):
                yield ev
        finally:
            Path(tmp.name).unlink(missing_ok=True)
    return ndjson(events())


# ------------------------------------------------------------------ own-voice enrolment
@app.get("/api/voice-script")
async def voice_script(lang: str = "en", seed: int | None = None):
    if lang not in enroll.SCRIPT_LANGS:
        raise HTTPException(404, "no script for that language")
    return enroll.generate_script(lang, seed)


@app.get("/api/my-voices")
async def my_voices():
    return {"available": state["clone_available"], "voices": cloner.list_voices(),
            "languages": [config.LANGUAGES[c]["name"] for c in cloner.XTTS_LANGS if c in config.LANGUAGES]}


@app.delete("/api/my-voices/{voice_id}")
async def delete_my_voice(voice_id: str):
    cloner.delete_voice(voice_id)
    return {"ok": True}


# ------------------------------------------------------------------ accuracy benchmark
bench_state = {"running": False}


@app.get("/api/bench/prompts")
async def bench_prompts(lang: str = "en"):
    if lang not in evaluate_wer.PROMPTS:
        raise HTTPException(404, "no prompts for that language")
    ds = evaluate_wer.Dataset()
    return {"prompts": evaluate_wer.prompts_with_status(lang, ds), "stats": ds.stats(),
            "models": evaluate_wer.MODEL_INFO}


@app.post("/api/bench/record")
async def bench_record(audio: UploadFile = File(...), prompt_id: str = Form(...)):
    lang, _, num = prompt_id.partition("-")
    try:
        text = evaluate_wer.PROMPTS[lang][int(num) - 1]
    except (KeyError, ValueError, IndexError):
        raise HTTPException(404, "unknown prompt")
    data = await audio.read()
    try:
        item = await asyncio.to_thread(evaluate_wer.Dataset().add, prompt_id, text, lang, data, "webm")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return item


@app.delete("/api/bench/item/{item_id}")
async def bench_delete(item_id: str):
    evaluate_wer.Dataset().delete(item_id)
    return {"ok": True}


@app.get("/api/bench/audio/{item_id}")
async def bench_audio(item_id: str, dataset: str = "my-voice"):
    try:
        path = evaluate_wer.Dataset(dataset).audio_path(item_id)
    except ValueError:
        raise HTTPException(400, "bad dataset name")
    if not path or not path.exists():
        raise HTTPException(404, "not found")
    return FileResponse(path)


class BenchRunIn(BaseModel):
    models: list[str]
    compare_cleaning: bool = True


@app.post("/api/bench/run")
async def bench_run(body: BenchRunIn):
    models = [m for m in body.models if m in evaluate_wer.MODEL_INFO]
    if not models:
        raise HTTPException(400, "pick at least one model")
    if bench_state["running"]:
        raise HTTPException(409, "a benchmark is already running")
    loop, queue = asyncio.get_running_loop(), asyncio.Queue()

    def progress(ev):  # called from the worker thread
        loop.call_soon_threadsafe(queue.put_nowait, ev)

    async def worker():
        bench_state["running"] = True
        try:
            res = await asyncio.to_thread(evaluate_wer.run, models, body.compare_cleaning, "my-voice",
                                          pipeline.transcriber, progress)
            progress({"type": "done", "result_id": res["id"]})
        except Exception as e:  # noqa: BLE001
            progress({"type": "error", "error": str(e)})
        finally:
            bench_state["running"] = False
            progress(None)

    asyncio.create_task(worker())

    async def stream():
        while (ev := await queue.get()) is not None:
            yield json.dumps(ev, ensure_ascii=False) + "\n"
    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.get("/api/bench/results")
async def bench_results():
    return evaluate_wer.list_results()


@app.get("/api/bench/results/{result_id}")
async def bench_result(result_id: str):
    try:
        r = evaluate_wer.load_result(result_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "not found")
    return {**r, "markdown": evaluate_wer.markdown_table(r)}


@app.post("/api/enroll")
async def enroll_voice(audio: UploadFile = File(...), name: str = Form(...), lang: str = Form("en"),
                       script: str = Form(...)):
    if not state["clone_available"]:
        raise HTTPException(400, "Voice cloning packages are not installed")
    data = await audio.read()
    return ndjson(pipeline.enroll(data, name.strip()[:40] or "My voice", lang, script))


class PreviewIn(BaseModel):
    lang: str
    voice: str
    rate: int = 0
    pitch: int = 0
    text: str | None = None


@app.post("/api/preview")
async def preview(body: PreviewIn):
    text = body.text or config.PREVIEW_TEXT.get(body.lang, "Hello!")
    path, info = await speaker.synthesize(text, body.lang, body.voice, body.rate, body.pitch)
    return {"audio_url": f"/outputs/{path.name}", **info}


@app.post("/api/process")
async def process(audio: UploadFile = File(...), target: str = Form(...), source: str = Form("auto"),
                  voice: str = Form(""), rate: int = Form(0), pitch: int = Form(0)):
    data = await audio.read()
    src = None if source == "auto" else source
    return ndjson(pipeline.run(data, target, src, voice or None, rate, pitch))


class RetranslateIn(BaseModel):
    text: str
    source: str
    target: str
    voice: str | None = None
    rate: int = 0
    pitch: int = 0


@app.post("/api/retranslate")
async def retranslate(body: RetranslateIn):
    """Used after the user corrects the transcript by hand."""
    return ndjson(pipeline.translate_and_speak(body.text, body.source, body.target,
                                               body.voice, body.rate, body.pitch))


if __name__ == "__main__":
    import uvicorn
    print(f"Open http://{config.HOST}:{config.PORT} in Chrome or Edge")
    uvicorn.run(app, host=config.HOST, port=config.PORT)
