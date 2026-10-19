"""Court-number mentions such as 6号场, 六号场, 6号和5号场, 1号4号场 or 1到3号场."""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.ai.nlu.text import NUM, prep, to_int

_SUFFIX = r"号(?:场地|球场|场)"
# Items are joined by punctuation, or run together when each already ends in 号 (1号4号场).
_PATTERN = re.compile(
    rf"(?P<range>(?P<lo>{NUM})(?:号)?[到至~\-](?P<hi>{NUM}){_SUFFIX})"
    rf"|(?P<list>(?<![0-9\-:])(?:{NUM}号(?=[0-9零〇一二两三四五六七八九十百]))*{NUM}(?:号)?(?:[、,，和及与跟或]{NUM}(?:号)?)*{_SUFFIX})"
)
_NEGATION = re.compile(r"(?:不要|不选|不用|别|去掉|取消|删掉|删除|排除|不考虑|不包括|除了)$")
ALL_COURTS = re.compile(r"(?:所有|全部|每个|每一个)(?:的)?(?:球)?场")
_BARE_LIST = re.compile(rf"(?P<prefix>场地[:：]?|只保留|只留|只要|改成|改为|换成|换为|不要|不选|选|要)?(?P<body>{NUM}号?(?:[、,，和及与跟或]{NUM}号?)*)[。.!！]?")


@dataclass(frozen=True, slots=True)
class CourtMention:
    text: str
    numbers: tuple[int, ...]
    negated: bool
    pos: int = 0


def scan_courts(text: str) -> list[CourtMention]:
    source = prep(text)
    found: list[CourtMention] = []
    for match in _PATTERN.finditer(source):
        if match.group("range"):
            lo, hi = to_int(match.group("lo")), to_int(match.group("hi"))
            numbers = tuple(range(lo, hi + 1)) if lo is not None and hi is not None and 0 <= lo <= hi <= 99 else ()
        else:
            body = re.sub(_SUFFIX + r"$", "", match.group(0))
            numbers = tuple(n for n in (to_int(t) for t in re.findall(NUM, body)) if n is not None)
        negated = bool(_NEGATION.search(source[max(0, match.start() - 8):match.start()]))
        found.append(CourtMention(match.group(0), numbers, negated, match.start()))
    return found


def scan_bare_courts(text: str) -> list[CourtMention]:
    """A short court answer must be a complete list, never digits from a duration or date."""
    source = prep(text)
    match = _BARE_LIST.fullmatch(source)
    if not match:
        return []
    numbers = tuple(to_int(token) for token in re.findall(NUM, match['body']))
    if any(number is None for number in numbers):
        return []
    return [CourtMention(match['body'], numbers, bool(_NEGATION.fullmatch(match['prefix'] or '')), match.start('body'))]


def mask_courts(text: str) -> str:
    """Replace court mentions so date/time scanners cannot read '6号' as a day."""
    return _PATTERN.sub(lambda m: "□" * len(m.group(0)), prep(text))


def court_name(number: int) -> str:
    return f"{number}号场"
