"""Central settings for the project.

Machine-specific values can be overridden in a `.env` file (see .env.example);
everything else is changed here.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")  # no-op if the file doesn't exist


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


# Hugging Face (where Whisper weights download from) warns about symlinks on Windows; harmless.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

OUTPUT_DIR = ROOT / "outputs"  # generated speech files land here
OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUT_MAX_AGE_HOURS = float(env("OUTPUT_MAX_AGE_HOURS", "24"))
VOICES_DIR = ROOT / "voices"   # your enrolled voice samples (stay on this PC)
VOICES_DIR.mkdir(exist_ok=True)
MODELS_DIR = ROOT / "models"   # coqui-tts housekeeping (XTTS weights live in the HF cache)
EVAL_DIR = ROOT / "eval"       # benchmark datasets + results

# ---------------- Web server ----------------
HOST = env("HOST", "127.0.0.1")
PORT = int(env("PORT", "8000"))

# ---------------- ASR (Whisper) ----------------
WHISPER_MODEL = env("WHISPER_MODEL", "large-v3-turbo")  # or "small", "medium", "large-v3"
WHISPER_DEVICE = env("WHISPER_DEVICE", "auto")          # "cuda", "cpu" or "auto" (GPU if it works)
WHISPER_COMPUTE_GPU = "int8_float16"  # int8 weights, fp16 maths: ~half the VRAM of fp16
WHISPER_COMPUTE_CPU = "int8"
BEAM_SIZE = 5

# Our own preprocessing
SAMPLE_RATE = 16_000        # Whisper is trained on 16 kHz mono audio
HIGHPASS_HZ = 80            # remove rumble / desk thumps below this
TARGET_PEAK_DBFS = -1.0     # normalise loudness so quiet mics still work
VAD_FRAME_MS = 30           # energy-VAD frame size
VAD_PAD_MS = 250            # keep this much audio around detected speech
LOW_CONFIDENCE = 0.60       # words below this probability get highlighted in the UI

# ---------------- Translation (Ollama) ----------------
OLLAMA_URL = env("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = env("OLLAMA_MODEL", "gemma4:e2b")  # fallback idea: "gemma3:4b"
OLLAMA_KEEP_ALIVE = "10m"    # keep the model in memory between requests
# Context window (tokens). Every request must use the SAME value - Ollama reloads
# the model whenever it changes. 8192 is enough for the summary "reduce" step.
OLLAMA_NUM_CTX = 8192

# ---------------- Languages ----------------
# code = Whisper/ISO-639-1 code. voice = Microsoft Edge neural voice used for TTS.
LANGUAGES = {
    "en": {"name": "English",    "voice": "en-US-AriaNeural"},
    "hi": {"name": "Hindi",      "voice": "hi-IN-SwaraNeural"},
    "bn": {"name": "Bengali",    "voice": "bn-IN-TanishaaNeural"},
    "ta": {"name": "Tamil",      "voice": "ta-IN-PallaviNeural"},
    "te": {"name": "Telugu",     "voice": "te-IN-ShrutiNeural"},
    "mr": {"name": "Marathi",    "voice": "mr-IN-AarohiNeural"},
    "gu": {"name": "Gujarati",   "voice": "gu-IN-DhwaniNeural"},
    "kn": {"name": "Kannada",    "voice": "kn-IN-SapnaNeural"},
    "ml": {"name": "Malayalam",  "voice": "ml-IN-SobhanaNeural"},
    "ur": {"name": "Urdu",       "voice": "ur-PK-UzmaNeural"},
    "es": {"name": "Spanish",    "voice": "es-ES-ElviraNeural"},
    "fr": {"name": "French",     "voice": "fr-FR-DeniseNeural"},
    "de": {"name": "German",     "voice": "de-DE-KatjaNeural"},
    "it": {"name": "Italian",    "voice": "it-IT-ElsaNeural"},
    "pt": {"name": "Portuguese", "voice": "pt-BR-FranciscaNeural"},
    "ru": {"name": "Russian",    "voice": "ru-RU-SvetlanaNeural"},
    "ja": {"name": "Japanese",   "voice": "ja-JP-NanamiNeural"},
    "ko": {"name": "Korean",     "voice": "ko-KR-SunHiNeural"},
    "zh": {"name": "Chinese",    "voice": "zh-CN-XiaoxiaoNeural"},
    "ar": {"name": "Arabic",     "voice": "ar-SA-ZariyahNeural"},
    "tr": {"name": "Turkish",    "voice": "tr-TR-EmelNeural"},
    "nl": {"name": "Dutch",      "voice": "nl-NL-ColetteNeural"},
}

# Short phrase used by the voice "Preview" button ("Hello, how are you?")
PREVIEW_TEXT = {
    "en": "Hello! This is how my voice sounds.", "hi": "नमस्ते, आप कैसे हैं?",
    "bn": "নমস্কার, আপনি কেমন আছেন?", "ta": "வணக்கம், நீங்கள் எப்படி இருக்கிறீர்கள்?",
    "te": "నమస్కారం, మీరు ఎలా ఉన్నారు?", "mr": "नमस्कार, तुम्ही कसे आहात?",
    "gu": "નમસ્તે, તમે કેમ છો?", "kn": "ನಮಸ್ಕಾರ, ನೀವು ಹೇಗಿದ್ದೀರಿ?", "ml": "നമസ്കാരം, സുഖമാണോ?",
    "ur": "السلام علیکم، آپ کیسے ہیں؟", "es": "Hola, ¿cómo estás?", "fr": "Bonjour, comment allez-vous ?",
    "de": "Hallo, wie geht es dir?", "it": "Ciao, come stai?", "pt": "Olá, como você está?",
    "ru": "Здравствуйте, как дела?", "ja": "こんにちは、お元気ですか？", "ko": "안녕하세요, 잘 지내세요?",
    "zh": "你好，你好吗？", "ar": "مرحبا، كيف حالك؟", "tr": "Merhaba, nasılsın?", "nl": "Hallo, hoe gaat het?",
}
