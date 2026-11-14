"""Translate text with a local LLM served by Ollama (streamed token by token)."""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

import config

SYSTEM_PROMPT = (
    "You are a professional translator. Translate the user's text from {src} to {tgt}. "
    "The text is a transcript of speech, so it may lack punctuation or contain small "
    "recognition errors: keep the speaker's meaning and tone, and write natural {tgt}. "
    "Use the native script of {tgt} and proper punctuation for {tgt}. Reply with ONLY "
    "the translation - no quotes, notes, explanations or transliteration."
)


def lang_name(code: str) -> str:
    return config.LANGUAGES.get(code, {}).get("name", code)


async def translate_stream(text: str, source: str, target: str) -> AsyncIterator[dict]:
    """Yields {"delta": "..."} pieces as the model writes, then a final {"done": True, ...}."""
    system = SYSTEM_PROMPT.format(src=lang_name(source), tgt=lang_name(target))
    if source == target or not text.strip():
        yield {"done": True, "text": text, "system_prompt": system, "skipped": True}
        return
    payload = {
        "model": config.OLLAMA_MODEL,
        "stream": True,
        "think": False,  # gemma4 can "reason" first; we only want the answer
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
        "options": {"temperature": 0.2, "num_ctx": config.OLLAMA_NUM_CTX},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}],
    }
    parts: list[str] = []
    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream("POST", f"{config.OLLAMA_URL}/api/chat", json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                delta = chunk.get("message", {}).get("content", "")
                if delta:
                    parts.append(delta)
                    yield {"delta": delta}
                if chunk.get("done"):
                    ns = 1e9
                    yield {
                        "done": True,
                        "text": "".join(parts).strip().strip('"“”'),
                        "system_prompt": system,
                        "stats": {
                            "model": config.OLLAMA_MODEL,
                            "prompt_tokens": chunk.get("prompt_eval_count", 0),
                            "output_tokens": chunk.get("eval_count", 0),
                            "tokens_per_s": round(chunk.get("eval_count", 0) / (chunk.get("eval_duration", 1) / ns), 1),
                            "prompt_ms": round(chunk.get("prompt_eval_duration", 0) / 1e6),
                            "generate_ms": round(chunk.get("eval_duration", 0) / 1e6),
                            "load_ms": round(chunk.get("load_duration", 0) / 1e6),
                            "temperature": 0.2,
                        },
                    }


async def translate(text: str, source: str, target: str) -> str:
    result = text
    async for ev in translate_stream(text, source, target):
        if ev.get("done"):
            result = ev["text"]
    return result


async def warm_up() -> None:
    """Load the model into GPU memory so the first real request is fast."""
    async with httpx.AsyncClient(timeout=300) as client:
        await client.post(f"{config.OLLAMA_URL}/api/generate",
                          json={"model": config.OLLAMA_MODEL, "keep_alive": config.OLLAMA_KEEP_ALIVE,
                                "options": {"num_ctx": config.OLLAMA_NUM_CTX}})
