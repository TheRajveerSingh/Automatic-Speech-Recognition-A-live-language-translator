"""ASR evaluation metrics: text normalisation, WER/CER with word alignment.

WER (word error rate) = (Substitutions + Deletions + Insertions) / words in reference
CER (character error rate) = the same idea on characters (useful for Hindi, where
word boundaries and spellings vary more).

Before comparing, BOTH texts are normalised the same way so that harmless
differences are not counted as mistakes:
  * case and punctuation:          "Hello," == "hello"
  * numbers written as digits:     "42" == "forty two",  "7:20" == "seven twenty",  "23rd" == "twenty third"
  * Hindi spelling variants:       पाँच == पांच (chandrabindu/anusvara),  ज़ == ज (nukta),  २ == 2
"""

from __future__ import annotations

import re
import unicodedata

# ----------------------------------------------------------------------------- numbers
_ORDINAL_RE = re.compile(r"\b(\d+)(st|nd|rd|th)\b")
# times: "7:20" and the Indian/British "7.20" (two digits that are valid minutes) -
# matched before decimals, so "9.30" reads "nine thirty", not "nine point three zero"
_TIME_RE = re.compile(r"\b(\d{1,2})[:.]([0-5]\d)\b(?!\s*%)")
_DECIMAL_RE = re.compile(r"\b(\d+)\.(\d+)\b")
_INT_RE = re.compile(r"\d+")


def _en_number(n: int, ordinal: bool = False) -> str:
    try:
        from num2words import num2words
        return num2words(n, to="ordinal" if ordinal else "cardinal", lang="en")
    except Exception:  # noqa: BLE001 - library missing: compare digits as-is
        return str(n)


def _hi_number(n: int) -> str:
    from tts.cloner import hindi_number  # pure-Python table, no heavy imports
    return hindi_number(n)


def spell_out_numbers(text: str, lang: str) -> str:
    text = text.translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 1,250 -> 1250
    if lang == "hi":
        to_words = _hi_number
        text = _TIME_RE.sub(lambda m: f"{to_words(int(m[1]))} {to_words(int(m[2]))}", text)
        text = _DECIMAL_RE.sub(lambda m: f"{to_words(int(m[1]))} दशमलव {' '.join(to_words(int(d)) for d in m[2])}", text)
        return _INT_RE.sub(lambda m: f" {to_words(int(m[0]))} ", text)
    if lang != "en":
        return text  # other languages: digits are compared as digits
    text = text.replace("%", " percent")
    text = _ORDINAL_RE.sub(lambda m: _en_number(int(m[1]), ordinal=True), text)
    text = _TIME_RE.sub(lambda m: f"{_en_number(int(m[1]))} {_en_number(int(m[2]))}" if m[2] != "00" else _en_number(int(m[1])), text)
    text = _DECIMAL_RE.sub(lambda m: f"{_en_number(int(m[1]))} point {' '.join(_en_number(int(d)) for d in m[2])}", text)
    return _INT_RE.sub(lambda m: f" {_en_number(int(m[0]))} ", text)


# ----------------------------------------------------------------------------- normalisation
# "I'm" and "I am" are the same words spoken; expand both sides so they compare equal.
EN_CONTRACTIONS = {
    "i'm": "i am", "it's": "it is", "that's": "that is", "what's": "what is", "there's": "there is",
    "he's": "he is", "she's": "she is", "let's": "let us", "you're": "you are", "we're": "we are",
    "they're": "they are", "i've": "i have", "you've": "you have", "we've": "we have", "i'll": "i will",
    "you'll": "you will", "we'll": "we will", "it'll": "it will", "i'd": "i would", "don't": "do not",
    "doesn't": "does not", "didn't": "did not", "can't": "can not", "cannot": "can not", "won't": "will not",
    "isn't": "is not", "aren't": "are not", "wasn't": "was not", "weren't": "were not", "haven't": "have not",
    "hasn't": "has not", "couldn't": "could not", "wouldn't": "would not", "shouldn't": "should not",
}


def normalize_words(text: str, lang: str = "en") -> list[str]:
    text = unicodedata.normalize("NFC", text.lower()).replace("’", "'").replace("‘", "'")
    text = spell_out_numbers(text, lang)
    if lang == "hi":
        text = text.replace("ँ", "ं")  # chandrabindu -> anusvara  (पाँच ~ पांच)
        text = text.replace("़", "")        # drop nukta                (ज़ ~ ज)
        text = unicodedata.normalize("NFC", text)
    text = text.replace("-", " ")                # forty-two -> forty two
    # drop punctuation (P*) and symbols (S*) by Unicode category; keeps Devanagari
    # vowel signs, which regex \w would wrongly treat as non-letters
    text = "".join(" " if unicodedata.category(c)[0] in "PS" and c != "'" else c for c in text)
    words = [w.strip("'") for w in text.split() if w.strip("'")]
    if lang == "en":
        words = " ".join(EN_CONTRACTIONS.get(w, w) for w in words).split()
    return words


# ----------------------------------------------------------------------------- edit distance
def word_errors(reference: list[str], hypothesis: list[str]) -> dict:
    """Word-level Levenshtein alignment -> substitutions, deletions, insertions (classic WER)."""
    R, H = len(reference), len(hypothesis)
    d = [[0] * (H + 1) for _ in range(R + 1)]
    for i in range(R + 1):
        d[i][0] = i
    for j in range(H + 1):
        d[0][j] = j
    for i in range(1, R + 1):
        for j in range(1, H + 1):
            cost = 0 if reference[i - 1] == hypothesis[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
    i, j, ops = R, H, []
    S = D = I = 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (reference[i - 1] != hypothesis[j - 1]):
            same = reference[i - 1] == hypothesis[j - 1]
            ops.append({"ref": reference[i - 1], "hyp": hypothesis[j - 1], "op": "ok" if same else "sub"})
            S += not same; i -= 1; j -= 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            ops.append({"ref": reference[i - 1], "hyp": None, "op": "del"}); D += 1; i -= 1
        else:
            ops.append({"ref": None, "hyp": hypothesis[j - 1], "op": "ins"}); I += 1; j -= 1
    ops.reverse()
    return {"wer": round((S + D + I) / max(1, R), 4), "substitutions": S, "deletions": D, "insertions": I,
            "reference_words": R, "alignment": ops}


def char_distance(a: str, b: str) -> int:
    """Plain Levenshtein distance between two strings (two-row version, O(len(b)) memory)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def score(reference: str, words: list[dict], text: str, lang: str) -> dict:
    """Score one utterance. `words` are Whisper's words with probabilities (may be empty)."""
    ref = normalize_words(reference, lang)
    # Whisper's word timing can split one written word into pieces ("5," + "000").
    # A piece without a leading space continues the previous word - glue it back,
    # otherwise "5,000" would be scored as "five zero". Keep the lower probability.
    merged: list[dict] = []
    for w in words:
        if merged and w["word"] and not w["word"][0].isspace():
            merged[-1] = {"word": merged[-1]["word"] + w["word"], "prob": min(merged[-1]["prob"], w["prob"])}
        else:
            merged.append({"word": w["word"], "prob": w["prob"]})
    words = merged
    hyp, probs = [], []
    for w in words:  # normalise word-by-word so every token keeps its word's probability
        toks = normalize_words(w["word"], lang)
        hyp += toks
        probs += [w["prob"]] * len(toks)
    if not words:
        hyp = normalize_words(text, lang)
        probs = [None] * len(hyp)
    errs = word_errors(ref, hyp)
    # label every hypothesis word as right/wrong, with the confidence Whisper gave it
    labelled, j = [], 0
    for op in errs["alignment"]:
        if op["hyp"] is not None:
            if probs[j] is not None:
                labelled.append({"word": op["hyp"], "prob": probs[j], "correct": op["op"] == "ok"})
            j += 1
    ref_chars, hyp_chars = "".join(ref), "".join(hyp)
    return {**errs, "char_errors": char_distance(ref_chars, hyp_chars), "reference_chars": len(ref_chars),
            "cer": round(char_distance(ref_chars, hyp_chars) / max(1, len(ref_chars)), 4),
            "words_scored": labelled}
