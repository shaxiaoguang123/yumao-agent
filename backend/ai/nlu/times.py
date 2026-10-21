"""Start-time and duration mentions (18:00, 晚上6点半, 两个半小时, 18:00-20:00)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.ai.nlu.text import NUM, norm, to_int
from backend.plans.validation import CLOSE_MINUTE, OPEN_MINUTE

LAST_START_MINUTE = CLOSE_MINUTE - 30
_AM = ("凌晨", "清晨", "早上", "早晨", "早", "上午")
_PM = ("下午", "傍晚", "晚上", "晚间", "晚", "夜里", "夜间")
_CLOCK = re.compile(
    r"(?P<per>凌晨|清晨|早上|早晨|早|上午|中午|下午|傍晚|晚上|晚间|晚|夜里|夜间)?"
    rf"(?:(?P<hh>[0-9]{{1,2}}):(?P<mm>[0-5][0-9])|(?P<h2>{NUM})[点时](?P<m2>半|整|{NUM}分|[0-5][0-9](?![0-9小个人元块号场日月年分]))?)"
)
_JOIN = {"到", "至", "-", "~", "—", "–"}
SHIFT_PHRASE = re.compile(
    rf"(?:前后|上下|提前|推迟|延后|延迟|浮动|相差|误差|早晚)[^，。；;,.]{{0,6}}?(?:{NUM}个半(?:小时|钟头)|{NUM}(?:个)?(?:小时|钟头|分钟)|半(?:个)?(?:小时|钟头))"
)
_RATE_HOUR = re.compile(rf"(?:每|(?<![0-9零〇一二两三四五六七八九十百]))(?:一|1)(?:个)?小时(?=[^，。；;,.]{{0,8}}[元块圆¥￥])")
_DURATION = re.compile(
    rf"(?P<hb>{NUM})个半(?:小时|钟头)"
    rf"|(?P<hm>(?P<h>{NUM})(?:个)?(?:小时|钟头)(?:(?P<half>半)|(?P<m>{NUM})分钟?)?)"
    r"|(?P<dec>[0-9]+\.[0-9]+)(?:个)?(?:小时|钟头)"
    r"|(?P<hh>半(?:个)?(?:小时|钟头))"
    rf"|(?P<min>(?P<mn>{NUM})分钟)"
)


@dataclass(frozen=True, slots=True)
class TimeMention:
    text: str
    candidates: tuple[str, ...]
    ambiguous: bool
    role: str  # start | end
    pos: int = 0


def _fmt(hour: int, minute: int) -> str | None:
    return f"{hour:02d}:{minute:02d}" if 0 <= hour <= 23 and 0 <= minute <= 59 else None


def hour_candidates(period: str | None, hour: int, literal: bool) -> set[int]:
    if period in _AM:
        return {0 if hour == 12 and period == "凌晨" else hour}
    if period in _PM:
        return {hour + 12 if hour < 12 else (0 if hour == 12 and period != "下午" else hour)}
    if period == "中午":
        return {hour if 10 <= hour <= 12 else hour + 12}
    if literal or hour > 12 or hour == 0 or hour == 12:
        return {hour}
    return {hour, hour + 12}


def _minutes(match: re.Match) -> int | None:
    if match.group("hh"):
        return int(match.group("mm"))
    raw = match.group("m2") or ""
    if raw in ("", "整"):
        return 0
    if raw == "半":
        return 30
    return to_int(raw.rstrip("分"))


def scan_times(text: str) -> list[TimeMention]:
    source = norm(text)
    found: list[tuple[re.Match, TimeMention]] = []
    for match in _CLOCK.finditer(source):
        hour = int(match.group("hh")) if match.group("hh") else to_int(match.group("h2"))
        minute = _minutes(match)
        if hour is None or minute is None or hour > 24:
            continue
        literal = bool(match.group("hh")) and match.group("hh").startswith("0")
        per = match.group("per")
        times = sorted(filter(None, (_fmt(h, minute) for h in hour_candidates(per, hour, literal))))
        if per is None and len(times) > 1:  # 6点 -> 18:00, 9点 stays ambiguous
            in_window = [t for t in times if OPEN_MINUTE <= int(t[:2]) * 60 + int(t[3:]) <= LAST_START_MINUTE]
            times = in_window if in_window else times
        found.append((match, TimeMention(match.group(0), tuple(times), len(times) > 1, "start", match.start())))
    result: list[TimeMention] = []
    for index, (match, mention) in enumerate(found):
        gap = source[found[index - 1][0].end():match.start()] if index else ""
        if index and (gap in _JOIN or (len(gap) <= 2 and gap[-1:] in {"到", "至"})):
            mention = TimeMention(mention.text, mention.candidates, mention.ambiguous, "end", mention.pos)
        result.append(mention)
    return result


def mask_shift(text: str) -> str:
    return _RATE_HOUR.sub(lambda m: "□" * len(m.group(0)), SHIFT_PHRASE.sub(lambda m: "□" * len(m.group(0)), norm(text)))


def scan_duration_mentions(text: str) -> list[tuple[str, int, int]]:
    values: list[tuple[str, int, int]] = []
    for match in _DURATION.finditer(mask_shift(text)):
        if match.group("hb"):
            hours = to_int(match.group("hb"))
            value = None if hours is None else hours * 60 + 30
        elif match.group("hm"):
            hours = to_int(match.group("h"))
            extra = 30 if match.group("half") else (to_int(match.group("m")) if match.group("m") else 0)
            value = None if hours is None or extra is None else hours * 60 + extra
        elif match.group("dec"):
            value = round(float(match.group("dec")) * 60)
        elif match.group("hh"):
            value = 30
        else:
            value = to_int(match.group("mn"))
        if value:
            values.append((match.group(0), value, match.start()))
    return values


def scan_durations(text: str) -> list[int]:
    return [value for _text, value, _pos in scan_duration_mentions(text)]
