"""Spoken cues used while folding a conversation into a booking-queue draft."""
from __future__ import annotations

import re
import unicodedata

_ONE = r"(?:1|一)(?:个)?(?:小时|钟头)"
_TWO = r"(?:2|两|二)(?:个)?(?:小时|钟头)"
ONE_HOUR = re.compile(_ONE)
TWO_HOUR = re.compile(_TWO)
_WANT = r"(?:要|订|选|抢|需要|想要|想)?"
_ONLY = r"(?:只|仅|就)"
_NOT = r"(?:不|无需|不需要|别|没有)(?:要|用|必|订|选|想|加)?"
ONLY_ONE = re.compile(_ONLY + _WANT + r"(?:打)?" + _ONE)
ONLY_TWO = re.compile(_ONLY + _WANT + r"(?:打)?" + _TWO)
NO_ONE = re.compile(_NOT + r"(?:候选|备选|的)?" + _ONE)
NO_TWO = re.compile(_NOT + r"(?:候选|备选|的)?" + _TWO)
_BOTH_GROUPS = re.compile(r"(?:两种|两组|两个?时长).{0,12}(?:都|同时|分别|一起)|(?:都|同时|分别|一起).{0,12}(?:抢|订|排|安排)")

NO_WORDS = ("不要", "不需要", "不用", "没有", "算了", "不加", "不必", "无需", "不想", "不了", "否", "没了", "不添", "不再", "不行", "不好", "no")
YES_REPLY = re.compile(r"(?:^|[，。；,;!?！？\s])(?:我)?(?:要|需要|想要|加|可以|好的?|是的|同意|对|嗯|yes|ok|okay)(?=$|[，。；,;!?！？\s])", re.I)
NO_MORE = ("没有", "不用", "不需要", "不要", "够了", "就这些", "就这样", "不加", "不添", "没了", "不再", "算了", "不必",
           "可以了", "好了", "行了", "不了", "无需", "就这", "只有这", "没别的", "没其他", "没有其他")
NO_MORE_ANYWHERE = re.compile(
    r"(?:不用|不需要|不要|没有|无需|不必)(?:再)?(?:其他|别的|更多|额外|其它)?(?:候选|备选|时间)"
    r"|(?:只|仅)(?:接受|限于|限)[^，。；;!?！？]{0,20}(?:这个|这些|刚才|上述)(?:时段|时间|场地)"
)
KEEP_STRONG = ("都保留", "都留", "全留", "全部保留", "都要", "都可以", "不用删", "不用去掉", "不删", "不去掉", "无所谓",
               "没关系", "保持", "不改", "不用改", "就这样", "这样就行", "这样可以", "都行", "不需要删", "不用处理", "不处理")
KEEP_WEAK = ("保留", "留着", "不动", "可以", "行", "好", "没事", "没问题", "不用", "不必", "嗯", "对")

REMOVE = ("去掉", "删掉", "删除", "不要", "不用", "取消", "排除", "去除", "拿掉", "删", "不选", "不考虑", "不包括", "除了")
REPLACE = ("改成", "改为", "换成", "换为", "改")
ONLY_CUES = ("只要", "只留", "只保留", "只订", "只选", "仅要", "仅保留", "仅订", "仅", "就要", "就订", "就选")
_SEPARATORS = "、,，和及与跟或 "
_AFTER_REMOVE = ("去掉", "删掉", "删除", "取消", "不要了", "不用了")


def contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def booking_mode(text: str, field_name: str | None, first: bool = False) -> str | None:
    """Read an explicit duration choice; a lone 2h/1h window is not a choice."""
    normalized = unicodedata.normalize("NFKC", text).strip().casefold()
    if field_name == "booking_mode" or first:
        choice = re.sub(r"[\s.,、:：()（）)）]+", "", normalized)
        if re.fullmatch(r"(?:1|a)(?:[.、)）])?", choice):
            return "two_hour_only"
        if re.fullmatch(r"(?:2|b)(?:[.、)）])?", choice):
            return "one_hour_only"
        if re.fullmatch(r"(?:3|c)(?:[.、)）])?", choice):
            return "both"
    has_one, has_two = bool(ONE_HOUR.search(normalized)), bool(TWO_HOUR.search(normalized))
    if _BOTH_GROUPS.search(normalized) and (has_one and has_two or re.search(r"两种|两组|两个?时长", normalized)):
        return "both"
    if ONLY_ONE.search(normalized):
        return "one_hour_only"
    if ONLY_TWO.search(normalized):
        return "two_hour_only"
    no_one, no_two = NO_ONE.search(normalized), NO_TWO.search(normalized)
    if no_one and not no_two:
        return "two_hour_only"
    if no_two and not no_one:
        return "one_hour_only"
    return None


def mode_before(text: str, pos: int, floor: int) -> str | None:
    """'remove' | 'replace' | 'only' | None, from the words just before a mention."""
    before = text[floor:pos].rstrip(_SEPARATORS)
    for word in sorted(ONLY_CUES, key=len, reverse=True):
        if before.endswith(word):
            return "only"
    for word in sorted(REMOVE, key=len, reverse=True):
        if before.endswith(word):
            return "remove"
    for word in REPLACE:
        if before.endswith(word):
            return "replace"
    return None


def mode_after(text: str, stop: int) -> str | None:
    return "remove" if text[stop:stop + 3].startswith(_AFTER_REMOVE) else None  # "18-20不用候选" is not a removal


def only_separators(gap: str) -> bool:
    return bool(gap) and all(char in _SEPARATORS for char in gap)


def sentence_start(text: str, pos: int) -> int:
    marks = [text.rfind(mark, 0, pos) for mark in "。；;!?！？\n"]
    return max(marks) + 1


def governing_hours(before: str) -> int | None:
    """120 or 60 when a spoken length just before a court mention names one; negated lengths are ignored."""
    cleaned = NO_ONE.sub(lambda m: "□" * len(m.group(0)), NO_TWO.sub(lambda m: "□" * len(m.group(0)), before))
    last: tuple[int, int] | None = None
    for pattern, minutes in ((TWO_HOUR, 120), (ONE_HOUR, 60)):
        for match in pattern.finditer(cleaned):
            if last is None or match.start() > last[0]:
                last = (match.start(), minutes)
    return last[1] if last else None
