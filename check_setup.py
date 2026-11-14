"""Verify every piece of the toolchain before we run the app.

Run:  conda activate asr-translate
      python check_setup.py
"""

import asyncio
import os
import shutil
import subprocess
import sys

import config

OK, BAD = "[ OK ]", "[FAIL]"
problems = 0


def report(ok: bool, name: str, detail: str = "", fix: str = "") -> None:
    global problems
    print(f"{OK if ok else BAD} {name}" + (f"  -  {detail}" if detail else ""))
    if not ok:
        problems += 1
        if fix:
            print(f"       fix: {fix}")


def check_env() -> None:
    env = os.environ.get("CONDA_DEFAULT_ENV") or os.path.basename(sys.prefix)
    report(env == "asr-translate", "Conda env", env,
           "run `conda activate asr-translate` first")
    report(sys.version_info[:2] == (3, 11), "Python version", sys.version.split()[0])


def check_ffmpeg() -> None:
    path = shutil.which("ffmpeg")
    if not path:
        report(False, "ffmpeg", "not found",
               "conda install -c conda-forge --override-channels ffmpeg")
        return
    out = subprocess.run([path, "-version"], capture_output=True, text=True)
    report(out.returncode == 0, "ffmpeg", out.stdout.split("\n")[0][:40])


def check_whisper() -> None:
    try:
        import numpy as np
        import ctranslate2
        from asr.gpu import register_cuda_dlls
        register_cuda_dlls()
        from faster_whisper import WhisperModel
    except ImportError as e:
        report(False, "faster-whisper import", str(e), "pip install -r requirements.txt")
        return

    gpus = ctranslate2.get_cuda_device_count()
    report(gpus > 0, "CUDA GPU visible", f"{gpus} device(s)",
           "update the NVIDIA driver; the app will still work on CPU (slower)")
    if gpus == 0:
        return
    # Actually run a tiny model on the GPU - this is what proves cuBLAS/cuDNN load.
    try:
        model = WhisperModel("tiny", device="cuda", compute_type=config.WHISPER_COMPUTE_GPU)
        audio = (0.1 * np.sin(2 * np.pi * 440 * np.arange(16000) / 16000)).astype("float32")
        segments, _ = model.transcribe(audio)
        list(segments)
        report(True, "Whisper runs on GPU", "cuBLAS + cuDNN loaded")
    except Exception as e:  # noqa: BLE001 - we want to show any failure
        report(False, "Whisper runs on GPU", str(e)[:150],
               "check that nvidia-cublas-cu12 / nvidia-cudnn-cu12 are installed")


def check_ollama() -> None:
    import httpx
    try:
        tags = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=5).json()
    except Exception:  # noqa: BLE001
        report(False, "Ollama server", "not reachable",
               "open the Ollama app (it runs in the system tray)")
        return
    report(True, "Ollama server", config.OLLAMA_URL)
    names = [m["name"] for m in tags.get("models", [])]
    report(config.OLLAMA_MODEL in names, f"Ollama model {config.OLLAMA_MODEL}",
           "installed" if config.OLLAMA_MODEL in names else f"have: {names}",
           f"ollama pull {config.OLLAMA_MODEL}")


def check_tts() -> None:
    try:
        import edge_tts
    except ImportError as e:
        report(False, "edge-tts import", str(e), "pip install -r requirements.txt")
        return

    async def voices():
        return {v["ShortName"] for v in await edge_tts.list_voices()}

    try:
        available = asyncio.run(voices())
    except Exception as e:  # noqa: BLE001
        report(False, "edge-tts service", str(e)[:120], "check your internet connection")
        return
    missing = [c for c, l in config.LANGUAGES.items() if l["voice"] not in available]
    report(not missing, "edge-tts voices",
           f"{len(config.LANGUAGES) - len(missing)}/{len(config.LANGUAGES)} languages",
           f"voice names wrong for: {missing}")


def check_voice_clone() -> None:
    """Optional: only reported, never counted as a problem."""
    try:
        import torch
        import TTS  # noqa: F401
    except ImportError:
        print("[ -- ] Own-voice cloning  -  not installed (optional: pip install -r requirements-voice.txt)")
        return
    gpu = torch.cuda.is_available()
    print(f"[{' OK ' if gpu else 'WARN'}] Own-voice cloning  -  torch {torch.__version__}, "
          f"{'GPU ' + torch.cuda.get_device_name(0) if gpu else 'CPU only (very slow)'}")


if __name__ == "__main__":
    print("Checking setup...\n")
    check_env()
    check_ffmpeg()
    check_whisper()
    check_ollama()
    check_tts()
    check_voice_clone()
    print("\nAll good!" if problems == 0 else f"\n{problems} problem(s) found.")
    sys.exit(1 if problems else 0)
