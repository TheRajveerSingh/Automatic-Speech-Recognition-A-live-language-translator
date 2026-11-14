"""Shared test setup: make the project root importable (so `import asr`, `import tts` work)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
