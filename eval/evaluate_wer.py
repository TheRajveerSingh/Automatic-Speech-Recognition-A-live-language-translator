"""Benchmark Whisper on YOUR recordings: accuracy, speed, language ID, confidence calibration.

How it works
  1. Build a test set: read sentences shown in the app (Benchmark tab). We know
     exactly what you said, so we have a perfect reference transcript.
  2. For every Whisper model x {with, without our audio cleaning}, transcribe
     every recording and compare it with the reference (asr/metrics.py).
  3. Report per configuration:
       WER / CER     - how many words / characters were wrong (lower = better)
       RTF           - processing time / audio length (0.1 = 10x faster than real time)
       Language ID   - how often auto-detect picked the right language
       Calibration   - does a low confidence score really mean a wrong word?
                       (precision / recall of the yellow highlights, best threshold)

Terminal:  python -m eval.evaluate_wer --models tiny,small,large-v3-turbo
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

import config
from asr.audio import NoSpeechError, decode, preprocess
from asr.metrics import score
from asr.transcriber import Transcriber

DATASETS_DIR = config.EVAL_DIR / "datasets"
RESULTS_DIR = config.EVAL_DIR / "results"

MODEL_INFO = {  # parameters, download size
    "tiny": "39 M params · 75 MB",
    "small": "244 M params · 0.5 GB",
    "medium": "769 M params · 1.5 GB",
    "large-v3-turbo": "809 M params · 1.6 GB (app default)",
}

# Everyday sentences: mixed lengths, numbers, questions, names, places.
PROMPTS = {
    "en": [
        "Good morning, could you please tell me the way to the nearest bus stop?",
        "I usually drink two cups of coffee before I start working.",
        "The library closes at nine thirty on weekdays.",
        "My sister moved to Bangalore last year for a new job.",
        "Please remind me to call the doctor tomorrow afternoon.",
        "We need to buy milk, bread, eggs, and some fresh vegetables.",
        "How long does it take to reach the airport from here?",
        "The weather forecast says it will rain heavily this weekend.",
        "I left my phone charger in the hotel room.",
        "Could you speak a little slower, please?",
        "The train to Mumbai is running forty minutes late.",
        "She has been learning to play the guitar for three years.",
        "Turn left at the second traffic signal and then go straight.",
        "Our team finished the project two days before the deadline.",
        "What is the best time to visit the mountains?",
        "I would like to order a vegetarian pizza with extra cheese.",
        "The museum has more than five thousand paintings.",
        "My laptop battery drains very quickly these days.",
        "Do you know where I can find a good pharmacy nearby?",
        "Thank you so much for helping me with my homework.",
        "The children were playing cricket in the park until sunset.",
        "Please send me the report by Friday evening.",
        "I think we should leave early to avoid the traffic.",
        "He forgot his umbrella and got completely wet.",
        "The new restaurant downtown serves amazing South Indian food.",
        "Can you recommend a good book to read on vacation?",
        "My flight departs at six fifteen in the morning.",
        "Learning a new language takes patience and daily practice.",
        "The price of tomatoes has doubled this month.",
        "Let me check my calendar and get back to you.",
        "Our neighbors adopted a small brown puppy last week.",
        "Is there a quiet place where I can make a phone call?",
        "The concert was so loud that my ears were ringing.",
        "I need to renew my passport before the end of the year.",
        "Water boils at one hundred degrees Celsius.",
        "Would you mind closing the window? It is getting cold.",
        "The software update fixed most of the bugs.",
        "My grandmother tells the most wonderful stories.",
        "We celebrated my brother's birthday with a big chocolate cake.",
        "Excuse me, is this seat taken?",
    ],
    "hi": [
        "नमस्ते, आप कैसे हैं?",
        "मुझे सुबह जल्दी उठना पसंद है।",
        "कृपया मुझे रेलवे स्टेशन का रास्ता बताइए।",
        "आज बाज़ार में बहुत भीड़ थी।",
        "मेरी बहन डॉक्टर बनना चाहती है।",
        "हम कल शाम को फ़िल्म देखने जाएंगे।",
        "इस दुकान में ताज़ी सब्ज़ियाँ मिलती हैं।",
        "क्या आप मेरी मदद कर सकते हैं?",
        "बारिश की वजह से सड़कें गीली हैं।",
        "मैंने आज तीन किताबें खरीदीं।",
        "मेरे दादाजी हर रोज़ अख़बार पढ़ते हैं।",
        "ट्रेन दस मिनट देर से चल रही है।",
        "खाना बहुत स्वादिष्ट बना है।",
        "हमारे स्कूल में कल खेल दिवस है।",
        "मुझे चाय के साथ बिस्कुट चाहिए।",
        "पानी की बोतल फ्रिज में रखी है।",
        "यह किताब बहुत रोचक है।",
        "तुम्हारा पसंदीदा रंग कौन सा है?",
        "मैं अगले महीने दिल्ली जा रहा हूँ।",
        "शाम को पार्क में टहलना अच्छा लगता है।",
    ],
}


def prompt_id(lang: str, i: int) -> str:
    return f"{lang}-{i:02d}"


# ----------------------------------------------------------------------------- dataset on disk
class Dataset:
    """eval/datasets/<name>/  with one audio file per recording + manifest.json."""

    def __init__(self, name: str = "my-voice"):
        if not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("bad dataset name")
        self.name = name
        self.dir = DATASETS_DIR / name
        self.manifest = self.dir / "manifest.json"

    def items(self) -> list[dict]:
        if not self.manifest.exists():
            return []
        return json.loads(self.manifest.read_text(encoding="utf-8"))

    def _save(self, items: list[dict]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    def add(self, pid: str, text: str, lang: str, audio: bytes, ext: str = "webm") -> dict:
        samples = decode(audio)  # validates the audio and measures its length
        items = [i for i in self.items() if i["prompt_id"] != pid]  # re-recording replaces
        for old in self.items():
            if old["prompt_id"] == pid:
                (self.dir / old["file"]).unlink(missing_ok=True)
        self.dir.mkdir(parents=True, exist_ok=True)
        item_id = uuid.uuid4().hex[:8]
        fname = f"{pid}_{item_id}.{ext}"
        (self.dir / fname).write_bytes(audio)
        item = {"id": item_id, "prompt_id": pid, "text": text, "lang": lang, "file": fname,
                "seconds": round(len(samples) / config.SAMPLE_RATE, 2), "recorded": time.strftime("%Y-%m-%d %H:%M")}
        items.append(item)
        self._save(sorted(items, key=lambda i: i["prompt_id"]))
        return item

    def delete(self, item_id: str) -> None:
        keep = []
        for i in self.items():
            if i["id"] == item_id:
                (self.dir / i["file"]).unlink(missing_ok=True)
            else:
                keep.append(i)
        self._save(keep)

    def audio_path(self, item_id: str) -> Path | None:
        for i in self.items():
            if i["id"] == item_id:
                return self.dir / i["file"]
        return None

    def stats(self) -> dict:
        items = self.items()
        by_lang: dict[str, int] = {}
        for i in items:
            by_lang[i["lang"]] = by_lang.get(i["lang"], 0) + 1
        return {"name": self.name, "count": len(items), "seconds": round(sum(i["seconds"] for i in items), 1),
                "by_lang": by_lang}


def prompts_with_status(lang: str, ds: Dataset) -> list[dict]:
    recorded = {i["prompt_id"]: i for i in ds.items()}
    return [{"id": prompt_id(lang, n), "text": t, "lang": lang, "recorded": recorded.get(prompt_id(lang, n))}
            for n, t in enumerate(PROMPTS[lang], 1)]


# ----------------------------------------------------------------------------- benchmark
@dataclass
class Prepared:
    item: dict
    raw: np.ndarray    # just decoded to 16 kHz mono
    clean: np.ndarray  # our front-end: DC, high-pass, normalise, VAD trim
    seconds: float


def _summarize(per: list[dict]) -> dict:
    S = sum(p["substitutions"] for p in per); D = sum(p["deletions"] for p in per)
    I = sum(p["insertions"] for p in per); N = sum(p["reference_words"] for p in per)
    C = sum(p["char_errors"] for p in per); NC = sum(p["reference_chars"] for p in per)
    audio = sum(p["seconds"] for p in per); proc = sum(p["time"] for p in per)
    scored = [w for p in per for w in p["words_scored"]]

    # calibration: is a low probability really a sign of a wrong word?
    bins = []
    for lo in np.arange(0, 1.0, 0.1):
        ws = [w for w in scored if lo <= w["prob"] < lo + 0.1 or (lo >= 0.9 and w["prob"] == 1.0)]
        bins.append({"lo": round(float(lo), 1), "count": len(ws),
                     "accuracy": round(sum(w["correct"] for w in ws) / len(ws), 3) if ws else None})

    def pr(threshold: float) -> dict:
        flagged = [w for w in scored if w["prob"] < threshold]
        wrong = [w for w in scored if not w["correct"]]
        hit = sum(not w["correct"] for w in flagged)
        p = hit / len(flagged) if flagged else 0.0
        r = hit / len(wrong) if wrong else 0.0
        return {"threshold": round(threshold, 2), "flagged": len(flagged), "wrong_words": len(wrong),
                "precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0}

    best = max((pr(t) for t in np.arange(0.05, 1.0, 0.05)), key=lambda x: (x["f1"], -x["flagged"]))
    return {
        "utterances": len(per), "reference_words": N,
        "wer": round((S + D + I) / max(1, N), 4), "cer": round(C / max(1, NC), 4),
        "substitutions": S, "deletions": D, "insertions": I,
        "rtf": round(proc / max(1e-9, audio), 3), "avg_latency_s": round(proc / max(1, len(per)), 3),
        "lid_accuracy": round(sum(p["lid_ok"] for p in per) / max(1, len(per)), 3),
        "avg_confidence": round(float(np.mean([w["prob"] for w in scored])), 3) if scored else None,
        "calibration": bins, "highlight_at_current": pr(config.LOW_CONFIDENCE), "best_threshold": best,
    }


def run(models: list[str], compare_cleaning: bool = True, dataset: str = "my-voice",
        shared: Transcriber | None = None, progress: Callable[[dict], None] = lambda e: None) -> dict:
    ds = Dataset(dataset)
    items = ds.items()
    if not items:
        raise ValueError("The test set is empty - record some sentences first.")

    progress({"type": "status", "message": f"Preparing {len(items)} recordings…"})
    prepared = []
    for it in items:
        data = (ds.dir / it["file"]).read_bytes()
        raw = decode(data)
        try:
            clean, _, _ = preprocess(data)
        except NoSpeechError:
            clean = raw
        prepared.append(Prepared(it, raw, clean, len(raw) / config.SAMPLE_RATE))

    variants = [True, False] if compare_cleaning else [True]
    total = len(models) * len(variants) * len(prepared)
    done = 0
    configs = []
    for model in models:
        progress({"type": "status", "message": f"Loading Whisper {model}… (first use downloads it)"})
        tr = shared if shared is not None and shared.model_name == model else Transcriber(model)
        tr.load()
        for cleaning in variants:
            name = f"{model} · {'cleaned' if cleaning else 'raw audio'}"
            per = []
            for p in prepared:
                audio = p.clean if cleaning else p.raw
                t0 = time.perf_counter()
                r = tr.transcribe(audio, None)  # auto language detection, like the app
                dt = time.perf_counter() - t0
                s = score(p.item["text"], r["words"], r["text"], p.item["lang"])
                per.append({**s, "id": p.item["id"], "prompt_id": p.item["prompt_id"], "lang": p.item["lang"],
                            "reference": p.item["text"], "hypothesis": r["text"], "detected": r["language"],
                            "lid_ok": r["language"] == p.item["lang"], "seconds": round(p.seconds, 2),
                            "time": round(dt, 3)})
                done += 1
                progress({"type": "progress", "config": name, "done": done, "total": total,
                          "utterance": p.item["prompt_id"], "wer": s["wer"]})
            summary = _summarize(per)
            configs.append({"name": name, "model": model, "cleaning": cleaning, "info": MODEL_INFO.get(model, ""),
                            "summary": summary, "utterances": per})
            progress({"type": "config_done", "name": name, "summary": summary})
        if tr is not shared:
            tr.unload()

    result = {
        "id": time.strftime("%Y%m%d-%H%M%S"), "created": time.strftime("%Y-%m-%d %H:%M"),
        "dataset": ds.stats(), "device": shared.device if shared else None,
        "low_confidence_threshold": config.LOW_CONFIDENCE, "configs": configs,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{result['id']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def list_results() -> list[dict]:
    out = []
    for f in sorted(RESULTS_DIR.glob("*.json"), reverse=True):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
            out.append({"id": r["id"], "created": r["created"], "utterances": r["dataset"]["count"],
                        "configs": [c["name"] for c in r["configs"]]})
        except Exception:  # noqa: BLE001
            continue
    return out


def load_result(result_id: str) -> dict:
    if not result_id.replace("-", "").isdigit():
        raise ValueError("bad result id")
    return json.loads((RESULTS_DIR / f"{result_id}.json").read_text(encoding="utf-8"))


def markdown_table(result: dict) -> str:
    rows = ["| Configuration | WER | CER | Speed (RTF) | Language ID |", "|---|---|---|---|---|"]
    for c in result["configs"]:
        s = c["summary"]
        rows.append(f"| {c['name']} | {s['wer'] * 100:.1f}% | {s['cer'] * 100:.1f}% | {s['rtf']:.2f} | {s['lid_accuracy'] * 100:.0f}% |")
    d = result["dataset"]
    rows.append(f"\n_{d['count']} recordings of my own voice ({d['seconds']} s), measured {result['created']}._")
    return "\n".join(rows)


# ----------------------------------------------------------------------------- CLI
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default="tiny,small,large-v3-turbo")
    ap.add_argument("--dataset", default="my-voice")
    ap.add_argument("--no-compare", action="store_true", help="only test with our audio cleaning")
    args = ap.parse_args()

    def show(e):
        if e["type"] == "status":
            print(e["message"])
        elif e["type"] == "config_done":
            s = e["summary"]
            print(f"  {e['name']:34s} WER {s['wer'] * 100:5.1f}%  CER {s['cer'] * 100:5.1f}%  RTF {s['rtf']:.2f}")

    res = run(args.models.split(","), not args.no_compare, args.dataset, progress=show)
    print("\n" + markdown_table(res))
