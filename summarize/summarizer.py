"""Summarise long transcripts with the local LLM, using map-reduce.

A one-hour talk is ~9,000 words - far more than a small model reads well in one
go. So:
  MAP     split the transcript into chunks of ~400 words (a few minutes each) and
          ask the LLM for a title, key notes and action items per chunk.
          Each chunk's title + start time becomes a chapter.
  REDUCE  give the LLM all the chunk notes (much shorter than the transcript) and
          ask for the final TL;DR, key points and action items.
Both steps use Ollama's structured output (a JSON schema) so we get reliable
fields back instead of free text we'd have to parse.
"""

from __future__ import annotations

import json

import httpx

import config

CHUNK_WORDS = 400      # upper limit per chunk (~3 min of speech)
MIN_CHUNK_WORDS = 120  # lower limit (~1 min) - short recordings still get a few chapters
TARGET_CHAPTERS = 6
NUM_CTX = config.OLLAMA_NUM_CTX  # same as translation, so Ollama never reloads the model


def chunk_size_for(total_words: int) -> int:
    """Aim for ~6 chapters, but keep chunks between ~1 and ~3 minutes of speech."""
    return max(MIN_CHUNK_WORDS, min(CHUNK_WORDS, total_words // TARGET_CHAPTERS))

MAP_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "string"}},
        "action_items": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "notes", "action_items"],
}
REDUCE_SCHEMA = {
    "type": "object",
    "properties": {
        "tldr": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "action_items": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tldr", "key_points", "action_items"],
}


def fmt_time(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def chunk_segments(segments: list[dict], max_words: int = CHUNK_WORDS) -> list[dict]:
    """Group consecutive segments into chunks of about max_words, never splitting a segment."""
    chunks, cur, words = [], [], 0
    for s in segments:
        n = len(s["text"].split())
        if cur and words + n > max_words:
            chunks.append(cur); cur, words = [], 0
        cur.append(s); words += n
    if cur:
        chunks.append(cur)
    return [{"start": c[0]["start"], "end": c[-1]["end"], "text": " ".join(s["text"] for s in c),
             "words": sum(len(s["text"].split()) for s in c)} for c in chunks]


async def ask_json(system: str, user: str, schema: dict) -> tuple[dict, dict]:
    payload = {
        "model": config.OLLAMA_MODEL, "stream": False, "think": False, "format": schema,
        "keep_alive": config.OLLAMA_KEEP_ALIVE, "options": {"temperature": 0.2, "num_ctx": NUM_CTX},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(f"{config.OLLAMA_URL}/api/chat", json=payload)
        r.raise_for_status()
    body = r.json()
    stats = {"prompt_tokens": body.get("prompt_eval_count", 0), "output_tokens": body.get("eval_count", 0),
             "ms": round(body.get("total_duration", 0) / 1e6)}
    try:
        return json.loads(body["message"]["content"]), stats
    except json.JSONDecodeError:  # very rare with a schema; keep the raw text rather than fail
        return {"title": "", "notes": [body["message"]["content"]], "action_items": [],
                "tldr": body["message"]["content"], "key_points": []}, stats


def map_prompt(lang_name: str, i: int, n: int, chunk: dict) -> tuple[str, str]:
    system = (
        f"You summarise part {i} of {n} of a transcript of a recording, in {lang_name}. "
        "Use ONLY information from the text. The transcript comes from speech recognition, so "
        "ignore filler words and small recognition errors. Return JSON with: "
        "'title' - a short chapter title (max 8 words); "
        "'notes' - 2 to 6 concise bullet points with the important content (facts, decisions, numbers, names); "
        "'action_items' - EVERY task: anything someone says they will do ('I will...') or is asked to do, "
        "plus decisions with deadlines. Include who and when if mentioned, e.g. 'Ryan: fix charts by Wednesday'. "
        "If there are none, return an empty list [] - never an item saying there are none. "
        f"IMPORTANT: write the title, every note and every action item in {lang_name}, "
        f"translating if the transcript is in another language."
    )
    return system, f"[{fmt_time(chunk['start'])} - {fmt_time(chunk['end'])}]\n{chunk['text']}"


def reduce_prompt(lang_name: str, parts: list[dict]) -> tuple[str, str]:
    system = (
        f"You write the final summary of a recording in {lang_name}, from notes taken on each part. "
        "Use ONLY the notes. Return JSON with: "
        "'tldr' - 2 or 3 sentences giving the gist; "
        "'key_points' - the 4 to 8 most important points overall, no repetition; "
        "'action_items' - every task or commitment from the notes' Actions lines, merged and de-duplicated - "
        "do not drop any; empty list [] if there are none. "
        f"Write everything in {lang_name}."
    )
    user = "\n\n".join(
        f"Part {i} [{fmt_time(p['start'])}] {p['title']}\n" + "\n".join(f"- {n}" for n in p["notes"])
        + ("\nActions: " + "; ".join(p["action_items"]) if p["action_items"] else "")
        for i, p in enumerate(parts, 1))
    return system, user
