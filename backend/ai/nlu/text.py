"""Text helpers shared by the deterministic Chinese scheduling parsers."""
from __future__ import annotations

import re
import unicodedata

_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
           "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
# Arabic digits or Chinese numerals up to the hundreds.
NUM = r"(?:[0-9]+|[零〇一二两三四五六七八九十百]+)"


def norm(text: str) -> str:
    """NFKC, lower-case and whitespace-free: the form every parser matches on."""
    return "".join(unicodedata.normalize("NFKC", text).split()).lower()


_DIGIT_GAP = re.compile(r"(?<=[0-9])\s+(?=[0-9])")


def prep(text: str) -> str:
    """norm(), but a space between two digits becomes a comma so '14-16 1号' stays two numbers."""
    return norm(_DIGIT_GAP.sub(",", unicodedata.normalize("NFKC", text)))


def to_int(token: str) -> int | None:
    """Convert an Arabic or Chinese numeral (up to 999) to an int, else None."""
    if not token:
        return None
    if token.isascii():
        return int(token) if token.isdigit() else None
    total, digit, previous_digit = 0, None, False
    for char in token:
        if char in ("零", "〇"):
            digit, previous_digit = None, False
        elif char in _DIGITS:
            if previous_digit:
                return None
            digit, previous_digit = _DIGITS[char], True
        elif char in ("十", "百"):
            total += (1 if digit is None else digit) * (10 if char == "十" else 100)
            digit, previous_digit = None, False
        else:
            return None
    return total + (digit or 0) if (total or digit is not None or token in "零〇") else None
