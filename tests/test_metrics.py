"""WER/CER scoring and text normalisation (asr/metrics.py).

Several of these cases are real bugs we hit while building the benchmark.
"""

import pytest

from asr.metrics import char_distance, normalize_words, score, word_errors


def wer(reference: str, hypothesis: str, lang: str = "en") -> float:
    return word_errors(normalize_words(reference, lang), normalize_words(hypothesis, lang))["wer"]


@pytest.mark.parametrize("reference, whisper_output", [
    ("Hello, how are you?", "hello how are you"),                                  # case + punctuation
    ("My train leaves at seven twenty.", "My train leaves at 7:20."),              # time with colon
    ("The library closes at nine thirty.", "The library closes at 9.30."),         # Indian/British time (bug)
    ("The museum has five thousand paintings.", "The museum has 5,000 paintings."),# thousands separator
    ("It is on the twenty-third of June.", "It is on the 23rd of June."),          # ordinal
    ("It costs three point five dollars.", "It costs 3.5 dollars."),               # decimal
    ("I am forty-two years old.", "I'm 42 years old."),                            # contraction + number
    ("I can't come.", "I can’t come."),                                            # curly apostrophe
])
def test_harmless_differences_are_not_errors_en(reference, whisper_output):
    assert wer(reference, whisper_output) == 0.0


@pytest.mark.parametrize("reference, whisper_output", [
    ("मेरे पास पाँच रुपये हैं।", "मेरे पास पांच रुपये हैं"),      # chandrabindu vs anusvara
    ("बाज़ार से सब्ज़ियाँ लाओ।", "बाजार से सब्जियां लाओ"),       # nukta dropped
    ("मैं बयालीस साल का हूँ।", "मैं 42 साल का हूं।"),            # digits -> Hindi number words
    ("मैं बयालीस साल का हूँ।", "मैं ४२ साल का हूं।"),            # Devanagari digits
])
def test_harmless_differences_are_not_errors_hi(reference, whisper_output):
    assert wer(reference, whisper_output, "hi") == 0.0


def test_hindi_vowel_signs_stay_inside_words():
    # regex \w treats matras as non-letters - words must not be split apart
    assert normalize_words("क्या आप मुझे बता सकते हैं", "hi") == ["क्या", "आप", "मुझे", "बता", "सकते", "हैं"]


def test_real_mistakes_are_counted():
    e = word_errors(normalize_words("platform four is closed"), normalize_words("platform for is closed"))
    assert e["wer"] == 0.25 and e["substitutions"] == 1


def test_substitution_deletion_insertion_counts():
    e = word_errors(["a", "b", "c", "d"], ["a", "x", "c", "d", "e"])
    assert (e["substitutions"], e["deletions"], e["insertions"]) == (1, 0, 1)
    e = word_errors(["a", "b", "c"], ["a", "c"])
    assert (e["substitutions"], e["deletions"], e["insertions"]) == (0, 1, 0)
    assert [op["op"] for op in e["alignment"]] == ["ok", "del", "ok"]


def test_empty_hypothesis_is_100_percent_wrong():
    assert word_errors(["hello", "world"], [])["wer"] == 1.0


def test_char_distance():
    assert char_distance("kitten", "sitting") == 3
    assert char_distance("", "abc") == 3
    assert char_distance("same", "same") == 0


def test_score_merges_split_whisper_words():
    # Whisper's word timing splits "5,000" into "5," + "000" (bug: scored as "five zero")
    words = [{"word": " more", "prob": 0.99}, {"word": " than", "prob": 0.99},
             {"word": " 5,", "prob": 0.95}, {"word": "000", "prob": 0.97}, {"word": " paintings.", "prob": 0.99}]
    s = score("more than five thousand paintings", words, "", "en")
    assert s["wer"] == 0.0


def test_score_labels_each_word_with_confidence():
    words = [{"word": " Platform", "prob": 0.98}, {"word": " for", "prob": 0.41},
             {"word": " is", "prob": 0.99}, {"word": " closed.", "prob": 0.95}]
    s = score("Platform four is closed.", words, "", "en")
    labelled = [(w["word"], w["correct"]) for w in s["words_scored"]]
    assert labelled == [("platform", True), ("for", False), ("is", True), ("closed", True)]
    assert s["words_scored"][1]["prob"] == 0.41
