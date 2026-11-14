"""Voice enrolment: generate a reading script, then quality-check the recording.

Why a script? Voice cloning learns your timbre (the "colour" of your voice) and
speaking style from a short sample. A good sample:
  * is 20-30 s of clear speech (XTTS uses up to ~30 s),
  * contains many different speech sounds (vowels, consonants, clusters),
  * has varied intonation - statements, a question, an exclamation, numbers.
So the generator greedily picks sentences that add the most NEW sound patterns,
while guaranteeing one sentence of each intonation type.

After recording, our own ASR checks the take: front-end measures noise and
length, Whisper transcribes it and we compute the word error rate against the
script (did you read it, and is it really one clear voice?).
"""

from __future__ import annotations

import random
import re
import unicodedata

from asr.metrics import normalize_words, word_errors

# ----------------------------------------------------------------------------- sentence pools
# English: Harvard sentences + Rainbow Passage (public domain, phonetically balanced by design)
POOLS = {
    "en": {
        "statement": [
            "The birch canoe slid on the smooth planks.",
            "Glue the sheet to the dark blue background.",
            "It's easy to tell the depth of a well.",
            "These days a chicken leg is a rare dish.",
            "The juice of lemons makes fine punch.",
            "The box was thrown beside the parked truck.",
            "Four hours of steady work faced us.",
            "A large size in stockings is hard to sell.",
            "The source of the huge river is the clear spring.",
            "Kick the ball straight and follow through.",
            "Help the woman get back to her feet.",
            "A pot of tea helps to pass the evening.",
            "Smoky fires lack flame and heat.",
            "The soft cushion broke the man's fall.",
            "The salt breeze came across from the sea.",
            "The girl at the booth sold fifty bonds.",
            "When the sunlight strikes raindrops in the air, they act as a prism and form a rainbow.",
            "The rainbow is a division of white light into many beautiful colours.",
            "These take the shape of a long round arch, with its path high above.",
            "Thick fog rolled over the quiet village just before dawn.",
        ],
        "question": [
            "Have you ever wondered why the sky looks blue on a clear day?",
            "Could you tell me which way leads to the old railway station?",
            "Would you rather visit the mountains or the beach this summer?",
            "What time does the museum open on Thursday mornings?",
        ],
        "exclamation": [
            "Wow, that was the most amazing view I have ever seen!",
            "Oh no, I think I left my keys on the kitchen table!",
            "Hurry up, the train is about to leave the platform!",
        ],
        "numbers": [
            "My appointment is on the twenty-third of June at half past four.",
            "The recipe needs three cups of flour, two eggs, and a pinch of salt.",
            "Call me back at nine fifteen, or after six thirty tonight.",
        ],
    },
    "hi": {
        "statement": [
            "आज सुबह आसमान बिल्कुल साफ़ था और ठंडी हवा चल रही थी।",
            "मेरे दादाजी हर शाम बगीचे में टहलने जाते हैं।",
            "बाज़ार से ताज़ी सब्ज़ियाँ, फल और दूध लेकर आना।",
            "छोटे बच्चे मैदान में फ़ुटबॉल खेल रहे थे।",
            "घने जंगल के बीच एक पुराना मंदिर है।",
            "रेलगाड़ी ठीक समय पर स्टेशन पहुँच गई।",
            "उसने झटपट खाना बनाया और सबको परोसा।",
            "बारिश के मौसम में खेतों में हरियाली छा जाती है।",
            "ढोल की आवाज़ सुनकर सब नाचने लगे।",
            "हमारे विद्यालय में विज्ञान की प्रदर्शनी लगी थी।",
            "गंगा के किनारे शाम की आरती बहुत सुंदर लगती है।",
            "थोड़ी देर आराम करने के बाद हम फिर से चल पड़े।",
        ],
        "question": [
            "क्या आप मुझे बता सकते हैं कि पुस्तकालय कहाँ है?",
            "तुम्हें कौन सा मौसम सबसे ज़्यादा पसंद है?",
            "कल शाम को तुम कितने बजे घर पहुँचे थे?",
        ],
        "exclamation": [
            "वाह, कितना सुंदर नज़ारा है!",
            "अरे, जल्दी करो, बस निकलने वाली है!",
            "अरे बाप रे, आज तो बहुत गर्मी है!",
        ],
        "numbers": [
            "मेरा जन्मदिन पंद्रह अगस्त को आता है।",
            "इस किताब की कीमत दो सौ पचास रुपये है।",
            "ट्रेन सुबह सात बजकर बीस मिनट पर आएगी।",
        ],
    },
}
SCRIPT_LANGS = {"en": "English", "hi": "Hindi"}
WORDS_PER_SECOND = {"en": 2.6, "hi": 2.3}  # typical relaxed reading pace
TARGET_SECONDS = 30
MIN_SECONDS, GOOD_SECONDS = 10, 20

# ----------------------------------------------------------------------------- sound units
# English spelling is not phonetic, so we approximate sounds with common letter
# patterns (digraphs first). Devanagari is close to phonetic: each letter/matra ~ one sound.
EN_UNITS = ["tch", "dge", "igh", "th", "sh", "ch", "ng", "ph", "wh", "ck", "qu", "oo", "ee", "ea", "ai", "ay",
            "ou", "ow", "oi", "oy", "ar", "er", "ir", "or", "ur", "aw", "au"]


def sound_units(text: str, lang: str) -> set[str]:
    if lang == "hi":
        return {c for c in unicodedata.normalize("NFC", text) if "ऀ" <= c <= "ॿ" and c not in "।॥"}
    t = re.sub(r"[^a-z ]", "", text.lower())
    units, i = set(), 0
    while i < len(t):
        for u in EN_UNITS:
            if t.startswith(u, i):
                units.add(u); i += len(u); break
        else:
            if t[i] != " ":
                units.add(t[i])
            i += 1
    return units


def _all_units(lang: str) -> set[str]:
    return set().union(*(sound_units(s, lang) for kind in POOLS[lang].values() for s in kind))


def generate_script(lang: str = "en", seed: int | None = None) -> dict:
    if lang not in POOLS:
        raise ValueError(f"No script pool for {lang}")
    rng = random.Random(seed)
    pool = POOLS[lang]
    lines: list[dict] = []
    covered: set[str] = set()

    def add(text, kind):
        lines.append({"text": text, "kind": kind})
        covered.update(sound_units(text, lang))

    # one of each intonation type, chosen at random
    for kind in ("question", "exclamation", "numbers"):
        add(rng.choice(pool[kind]), kind)

    # then statements: greedily take the one adding most new sounds (random tie-break)
    est = lambda: sum(len(l["text"].split()) for l in lines) / WORDS_PER_SECOND[lang]
    candidates = pool["statement"][:]
    rng.shuffle(candidates)
    while est() < TARGET_SECONDS and candidates:
        best = max(candidates, key=lambda s: len(sound_units(s, lang) - covered))
        candidates.remove(best)
        add(best, "statement")

    # read in a natural order: statements first, the special ones spread through
    order = {"statement": 0, "question": 1, "numbers": 2, "exclamation": 3}
    stmts = [l for l in lines if l["kind"] == "statement"]
    specials = sorted([l for l in lines if l["kind"] != "statement"], key=lambda l: order[l["kind"]])
    mixed = []
    for i, l in enumerate(stmts):
        mixed.append(l)
        if i % 2 == 1 and specials:
            mixed.append(specials.pop(0))
    mixed += specials

    total_units = _all_units(lang)
    words = sum(len(l["text"].split()) for l in mixed)
    return {
        "lang": lang, "lang_name": SCRIPT_LANGS[lang], "lines": mixed, "words": words,
        "est_seconds": round(words / WORDS_PER_SECOND[lang]),
        "coverage": {"covered": len(covered & total_units), "total": len(total_units),
                     "unit": "letters/sounds" if lang == "hi" else "sound patterns"},
        "min_seconds": MIN_SECONDS, "good_seconds": GOOD_SECONDS,
    }


# ----------------------------------------------------------------------------- quality checks
def assess(report: dict, script_text: str, transcript: str, lang: str = "en") -> dict:
    """Turn measurements into pass / warn / fail checks the UI can show."""
    errs = word_errors(normalize_words(script_text, lang), normalize_words(transcript, lang))
    accuracy = max(0.0, 1 - errs["wer"])
    sec, snr = report["speech_seconds"], report["snr_db"]
    checks = [
        {"name": "Speech length", "value": f"{sec:.1f} s",
         "status": "pass" if sec >= GOOD_SECONDS else "warn" if sec >= MIN_SECONDS else "fail",
         "detail": f"need ≥ {MIN_SECONDS} s, best ≥ {GOOD_SECONDS} s"},
        {"name": "Background noise (SNR)", "value": f"{snr:.0f} dB",
         "status": "pass" if snr >= 25 else "warn" if snr >= 15 else "fail",
         "detail": "higher = cleaner; noise gets cloned too"},
        {"name": "Clipping", "value": "yes" if report["clipped"] else "none",
         "status": "warn" if report["clipped"] else "pass", "detail": "too loud distorts the voice"},
        {"name": "Reading accuracy", "value": f"{accuracy * 100:.0f}%",
         "status": "pass" if accuracy >= 0.85 else "warn" if accuracy >= 0.6 else "fail",
         "detail": f"1 − WER, Whisper vs the script ({errs['substitutions']} sub, {errs['deletions']} missed, {errs['insertions']} extra)"},
    ]
    ok = all(c["status"] != "fail" for c in checks)
    return {"ok": ok, "checks": checks, "accuracy": round(accuracy, 3), "errors": errs}
