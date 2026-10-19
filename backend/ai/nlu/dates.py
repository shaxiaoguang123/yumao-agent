"""Date mentions. Past dates are reported as written; nothing is rolled forward."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from backend.ai.nlu.text import NUM, norm, to_int

_WEEKDAY = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6, "末": None}
# Longest words first so 大后天 is never read as 后天.
_RELATIVE = (("大后天", 3), ("大前天", -3), ("后天", 2), ("前天", -2), ("明天", 1), ("昨天", -1), ("今天", 0))
_PATTERN = re.compile("|".join((
    rf"(?P<ymd>(?P<y1>[0-9]{{4}})年(?P<m1>{NUM})月(?P<d1>{NUM})[日号]?)",
    r"(?P<iso>(?P<y2>[0-9]{4})[-/.](?P<m2>[0-9]{1,2})[-/.](?P<d2>[0-9]{1,2}))",
    rf"(?P<md>(?P<m3>{NUM})月(?P<d3>{NUM})[日号]?)",
    rf"(?P<nm>(?P<which>下个月|下月|本月|这个月|这月)(?P<d4>{NUM})[日号])",
    "(?P<rel>" + "|".join(word for word, _ in _RELATIVE) + ")",
    r"(?P<wk>(?P<pre>下下个?|下个?|本个?|这个?|上个?)?(?:周|星期|礼拜)(?P<day>[一二三四五六日天末]))",
    rf"(?P<bare>(?<![0-9]){NUM}[日号](?![场球地馆]))",
)))


@dataclass(frozen=True, slots=True)
class DateMention:
    kind: str
    text: str
    dates: tuple[date, ...]
    ambiguous: bool


def _safe(year: int, month: int | None, day: int | None) -> date | None:
    try:
        return date(year, month, day)
    except (TypeError, ValueError):
        return None


def _weekday(today: date, prefix: str | None, day_char: str) -> tuple[tuple[date, ...], bool]:
    index = _WEEKDAY[day_char]
    monday = today - timedelta(days=today.weekday())
    if index is None:  # 周末 names two days, so it is never a single answer
        weeks = 2 if (prefix or "").startswith("下下") else 1 if (prefix or "").startswith("下") else 0
        base = monday + timedelta(days=5 + 7 * weeks)
        return (base, base + timedelta(days=1)), True
    if prefix and prefix.startswith("下下"):
        return (monday + timedelta(days=14 + index),), False
    if prefix and prefix.startswith("下"):
        return (monday + timedelta(days=7 + index),), False
    if prefix and prefix.startswith(("本", "这")):
        return (monday + timedelta(days=index),), False
    if prefix and prefix.startswith("上"):
        return (monday + timedelta(days=index - 7),), False
    if index == today.weekday():  # "周六" said on a Saturday: today or next week
        return (today, today + timedelta(days=7)), True
    return (today + timedelta(days=(index - today.weekday()) % 7),), False


def scan_dates(masked_text: str, today: date) -> list[DateMention]:
    """Scan text whose court mentions were already masked (see courts.mask_courts)."""
    mentions: list[DateMention] = []
    for match in _PATTERN.finditer(norm(masked_text)):
        text = match.group(0)
        kind = next(name for name in ("ymd", "iso", "md", "nm", "rel", "wk", "bare") if match.group(name) is not None)
        if kind in {"ymd", "iso", "md"}:
            y = int(match.group("y1" if kind == "ymd" else "y2")) if kind != "md" else today.year
            m = to_int(match.group({"ymd": "m1", "iso": "m2", "md": "m3"}[kind]))
            d = to_int(match.group({"ymd": "d1", "iso": "d2", "md": "d3"}[kind]))
            found = _safe(y, m, d)
            mentions.append(DateMention("invalid_date" if found is None else "exact", text, (found,) if found else (), found is None))
        elif kind == "nm":
            month_start = today.replace(day=1)
            if match.group("which") in {"下个月", "下月"}:
                month_start = (month_start + timedelta(days=32)).replace(day=1)
            found = _safe(month_start.year, month_start.month, to_int(match.group("d4")))
            mentions.append(DateMention("invalid_date" if found is None else "relative_month", text, (found,) if found else (), found is None))
        elif kind == "rel":
            offset = dict(_RELATIVE)[text]
            mentions.append(DateMention("relative", text, (today + timedelta(days=offset),), False))
        elif kind == "wk":
            dates, ambiguous = _weekday(today, match.group("pre"), match.group("day"))
            mentions.append(DateMention("weekday", text, dates, ambiguous))
        else:
            mentions.append(DateMention("bare_day", text, (), True))
    return mentions


def mask_dates(masked_text: str) -> str:
    """Blank out date mentions (digits included) so time scanners never read 10-24 or 14号 as a window."""
    return _PATTERN.sub(lambda m: "□" * len(m.group(0)), norm(masked_text))


WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def settle(turns: list[str], today: date, mask) -> tuple[str, tuple[date, ...], list[DateMention]]:
    """Resolve the most recent turn that mentions a date.

    Returns (state, dates, mentions) where state is ``empty``, ``resolved`` or
    ``ambiguous``. A full date in a turn outranks a bare day number in that turn.
    """
    for turn in reversed(turns):
        mentions = scan_dates(mask(turn), today)
        if not mentions:
            continue
        if any(m.kind != "bare_day" for m in mentions):
            mentions = [m for m in mentions if m.kind != "bare_day"]
        unique = tuple(dict.fromkeys(d for m in mentions for d in m.dates))
        if len(unique) == 1 and not any(m.ambiguous for m in mentions):
            return "resolved", unique, mentions
        return "ambiguous", unique, mentions
    return "empty", (), []
