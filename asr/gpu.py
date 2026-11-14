"""Make the pip-installed NVIDIA libraries (cuBLAS, cuDNN) visible on Windows.

pip puts their DLLs in site-packages/nvidia/<lib>/bin, which Windows does not
search by default. CTranslate2 (the engine under faster-whisper) loads them
lazily, so we add those folders to the DLL search path before loading a model.
"""

import os
import sys
from pathlib import Path

_done = False


def register_cuda_dlls() -> list[str]:
    global _done
    added: list[str] = []
    if _done or sys.platform != "win32":
        return added
    try:
        import nvidia  # namespace package created by the nvidia-* wheels
    except ImportError:
        return added
    for base in map(Path, nvidia.__path__):
        for bin_dir in base.glob("*/bin"):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]
            added.append(str(bin_dir))
    _done = True
    return added
