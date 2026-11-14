"""Spelling numbers out for XTTS (tts/cloner.py).

XTTS crashes on digits in Hindi and Chinese (num2words has no support), which is
the bug that broke "मैं 42 साल का हूँ" in the user's own voice.
"""

import pytest

from tts.cloner import chinese_number, hindi_number, spell_numbers


@pytest.mark.parametrize("n, words", [
    (0, "शून्य"), (7, "सात"), (42, "बयालीस"), (99, "निन्यानवे"), (100, "एक सौ"), (105, "एक सौ पाँच"),
    (250, "दो सौ पचास"), (1000, "एक हज़ार"), (2026, "दो हज़ार छब्बीस"), (150000, "एक लाख पचास हज़ार"),
    (12345678, "एक करोड़ तेईस लाख पैंतालीस हज़ार छह सौ अठहत्तर"),
])
def test_hindi_numbers(n, words):
    assert hindi_number(n) == words


@pytest.mark.parametrize("n, words", [
    (0, "零"), (10, "十"), (12, "十二"), (42, "四十二"), (105, "一百零五"), (1005, "一千零五"),
    (1010, "一千零一十"), (10000, "一万"), (100005, "十万零五"), (2026, "二千零二十六"), (120000000, "一亿二千万"),
])
def test_chinese_numbers(n, words):
    assert chinese_number(n) == words


def test_spell_numbers_in_hindi_sentence():
    out = spell_numbers("मैं 42 साल का हूँ।", "hi")
    assert out == "मैं बयालीस साल का हूँ।"
    assert not any(c.isdigit() for c in spell_numbers("कीमत 1,250 रुपये, तापमान 3.5 डिग्री, साल २०२६", "hi"))


def test_spell_numbers_in_chinese_sentence():
    assert spell_numbers("我今年42岁，房间号是105。", "zh") == "我今年四十二岁，房间号是一百零五。"


def test_other_languages_left_alone():
    # XTTS handles digits itself for these languages
    assert spell_numbers("I am 42", "en") == "I am 42"
    assert spell_numbers("Tengo 3 hermanos", "es") == "Tengo 3 hermanos"
