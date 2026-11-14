"""Voice-enrolment script + checks (tts/enroll.py) and transcript chunking (summarize/summarizer.py)."""

import pytest

from summarize.summarizer import chunk_segments, chunk_size_for, fmt_time
from tts.enroll import MIN_SECONDS, assess, generate_script, sound_units


# ----------------------------------------------------------------------------- reading script
@pytest.mark.parametrize("lang", ["en", "hi"])
def test_script_has_every_intonation_type_and_enough_speech(lang):
    for seed in range(10):
        s = generate_script(lang, seed=seed)
        kinds = {line["kind"] for line in s["lines"]}
        assert {"statement", "question", "exclamation", "numbers"} <= kinds
        assert 25 <= s["est_seconds"] <= 45             # ~30 s of reading
        assert s["coverage"]["covered"] / s["coverage"]["total"] > 0.8


def test_script_is_reproducible_with_a_seed():
    assert generate_script("en", seed=3) == generate_script("en", seed=3)


def test_unknown_script_language_raises():
    with pytest.raises(ValueError):
        generate_script("xx")


def test_sound_units():
    assert {"th", "sh", "ee"} <= sound_units("The sheep", "en")
    assert sound_units("क्या", "hi") == {"क", "्", "य", "ा"}


# ----------------------------------------------------------------------------- recording checks
GOOD = {"speech_seconds": 28.0, "snr_db": 35.0, "clipped": False}
SCRIPT = "The birch canoe slid on the smooth planks."


def test_good_recording_passes():
    v = assess(GOOD, SCRIPT, "the birch canoe slid on the smooth planks")
    assert v["ok"] and v["accuracy"] == 1.0


def test_too_short_recording_fails():
    v = assess({**GOOD, "speech_seconds": MIN_SECONDS - 1}, SCRIPT, SCRIPT)
    assert not v["ok"]


def test_reading_something_else_fails():
    v = assess(GOOD, SCRIPT, "hello this is a completely different sentence")
    assert not v["ok"]
    assert next(c for c in v["checks"] if c["name"] == "Reading accuracy")["status"] == "fail"


def test_noisy_recording_fails():
    assert not assess({**GOOD, "snr_db": 8.0}, SCRIPT, SCRIPT)["ok"]


# ----------------------------------------------------------------------------- summary chunking
def segs(n, words_each=10):
    return [{"start": i * 5.0, "end": i * 5.0 + 4.5, "text": " ".join(["word"] * words_each)} for i in range(n)]


def test_chunks_respect_size_and_never_split_segments():
    chunks = chunk_segments(segs(40), max_words=100)
    assert len(chunks) == 4
    assert all(c["words"] <= 100 for c in chunks)
    assert sum(c["words"] for c in chunks) == 400          # nothing lost
    assert chunks[1]["start"] == 50.0                      # starts on a segment boundary


def test_chunk_size_adapts_to_length():
    assert chunk_size_for(300) == 120      # short recording: still a few chapters
    assert chunk_size_for(1800) == 300     # ~6 chapters
    assert chunk_size_for(9000) == 400     # one hour: capped at ~3 min per chunk


def test_fmt_time():
    assert fmt_time(65) == "1:05"
    assert fmt_time(3725) == "1:02:05"
