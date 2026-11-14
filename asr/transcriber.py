"""Whisper speech recogniser with language ID, per-word confidence and token-level detail."""

from __future__ import annotations

import math
import threading

import numpy as np

import config
from asr import features
from asr.gpu import register_cuda_dlls


class Transcriber:
    def __init__(self, model_name: str = config.WHISPER_MODEL):
        self.model_name = model_name
        self.device = None
        self._model = None
        self._lock = threading.Lock()  # one GPU inference at a time

    # ------------------------------------------------------------ loading
    def load(self):
        if self._model is not None:
            return self._model
        register_cuda_dlls()
        from faster_whisper import WhisperModel

        want = config.WHISPER_DEVICE
        if want in ("auto", "cuda"):
            try:
                self._model = WhisperModel(self.model_name, device="cuda",
                                           compute_type=config.WHISPER_COMPUTE_GPU)
                self.device = "cuda"
                return self._model
            except Exception as e:  # noqa: BLE001
                if want == "cuda":
                    raise
                print(f"[asr] GPU load failed ({e}); falling back to CPU")
        self._model = WhisperModel(self.model_name, device="cpu",
                                   compute_type=config.WHISPER_COMPUTE_CPU)
        self.device = "cpu"
        return self._model

    def unload(self) -> None:
        """Free the model's GPU memory (used by the benchmark when switching models)."""
        import gc
        with self._lock:
            self._model = None
        gc.collect()

    @property
    def n_mels(self) -> int:
        return self.load().feature_extractor.mel_filters.shape[0]

    # ------------------------------------------------------------ features (for the UI)
    def mel_visualization(self, audio: np.ndarray) -> dict:
        model = self.load()
        reference = model.feature_extractor(audio)  # faster-whisper's own computation
        return features.visualize(audio, self.n_mels, reference)

    # ------------------------------------------------------------ long recordings (streamed)
    def transcribe_stream(self, audio: np.ndarray, language: str | None = None):
        """Yield segments as Whisper decodes them, for long recordings.

        Uses faster-whisper's built-in Silero VAD (a small neural voice detector)
        to skip long pauses - in hour-long audio those cause hallucinated text.
        """
        model = self.load()
        with self._lock:
            segments, info = model.transcribe(
                audio, language=language, beam_size=config.BEAM_SIZE, vad_filter=True,
                condition_on_previous_text=False, word_timestamps=False,
            )
            yield {"type": "info", "language": info.language,
                   "language_probability": round(float(info.language_probability), 3),
                   "duration": round(float(info.duration), 2),
                   "speech_duration": round(float(info.duration_after_vad or info.duration), 2)}
            for s in segments:  # decoding happens lazily, one 30 s window at a time
                yield {"type": "segment", "start": round(float(s.start), 2), "end": round(float(s.end), 2),
                       "text": s.text.strip(), "avg_logprob": round(float(s.avg_logprob), 3)}

    # ------------------------------------------------------------ language ID between known languages
    def detect_between(self, audio: np.ndarray, languages: list[str]) -> dict:
        """Which of these languages is being spoken? (conversation mode)

        Whisper scores all ~100 languages; we keep only the conversation's
        languages and renormalise, so e.g. Hindi speech can't be mistaken for Urdu
        when the conversation is Hindi <-> Spanish.
        """
        model = self.load()
        with self._lock:
            _, _, all_probs = model.detect_language(audio=audio)
        probs = dict(all_probs)
        raw = {lang: float(probs.get(lang, 0.0)) for lang in languages}
        total = sum(raw.values()) or 1.0
        scores = {lang: round(p / total, 4) for lang, p in raw.items()}
        best = max(scores, key=scores.get)
        top = sorted(all_probs, key=lambda p: -p[1])[0]
        return {"language": best, "scores": scores, "raw": {k: round(v, 4) for k, v in raw.items()},
                "whisper_top": {"code": top[0], "prob": round(float(top[1]), 4)}}

    # ------------------------------------------------------------ inference
    def transcribe(self, audio: np.ndarray, language: str | None = None) -> dict:
        from faster_whisper.tokenizer import Tokenizer

        model = self.load()
        with self._lock:
            segments, info = model.transcribe(
                audio,
                language=language,              # None = auto-detect
                beam_size=config.BEAM_SIZE,
                word_timestamps=True,           # gives us per-word probability
                condition_on_previous_text=False,  # reduces repetition loops
                vad_filter=False,               # we already ran our own VAD
            )
            segments = list(segments)  # generator: decoding happens here

        tok = Tokenizer(model.hf_tokenizer, model.model.is_multilingual,
                        task="transcribe", language=info.language)

        words, seg_out = [], []
        for s in segments:
            text_tokens = [t for t in s.tokens if t < tok.eot]  # drop timestamp/special tokens
            seg_out.append({
                "start": round(float(s.start), 2), "end": round(float(s.end), 2), "text": s.text.strip(),
                "avg_logprob": round(float(s.avg_logprob), 3),
                "avg_token_prob": round(math.exp(float(s.avg_logprob)), 3),
                "compression_ratio": round(float(s.compression_ratio), 2),
                "no_speech_prob": round(float(s.no_speech_prob), 3),
                "temperature": float(s.temperature or 0.0),
                "tokens": [{"id": int(t), "text": tok.decode([t])} for t in text_tokens],
                "special_tokens": len(s.tokens) - len(text_tokens),
            })
            for w in s.words or []:
                p = float(w.probability)  # numpy -> plain float (JSON-safe)
                words.append({
                    "word": w.word, "start": round(float(w.start), 2), "end": round(float(w.end), 2),
                    "prob": round(p, 3), "low": p < config.LOW_CONFIDENCE,
                })

        text = "".join(w["word"] for w in words).strip() or " ".join(s["text"] for s in seg_out)
        top_langs = sorted(info.all_language_probs or [], key=lambda p: -p[1])[:8]
        return {
            "text": text,
            "language": info.language,
            "language_probability": round(float(info.language_probability), 3),
            "language_candidates": [{"code": c, "prob": round(float(p), 4)} for c, p in top_langs],
            "languages_considered": len(info.all_language_probs or []),
            "confidence": round(float(np.mean([w["prob"] for w in words])), 3) if words else 0.0,
            "low_confidence_words": sum(w["low"] for w in words),
            "words": words,
            "segments": seg_out,
            "device": self.device,
            "model": self.model_name,
            "decoding": {"beam_size": config.BEAM_SIZE, "vocab_size": model.hf_tokenizer.get_vocab_size(),
                         "compression_threshold": 2.4, "low_confidence_threshold": config.LOW_CONFIDENCE},
        }
