"""Time-window mentions: 14-16, 14:00-16:00, 下午2点到4点, or a lone start such as 晚上7点."""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.ai.nlu import courts as court_nlu
from backend.ai.nlu import dates as date_nlu
from backend.ai.nlu import times as time_nlu
from backend.ai.nlu.text import NUM, to_int
from backend.plans.validation import CLOSE_MINUTE, OPEN_MINUTE

_PERIOD = r"(?:凌晨|清晨|早上|早晨|早|上午|中午|下午|傍晚|晚上|晚间|晚|夜里|夜间)"
_TOKEN = rf"(?:[0-9]{{1,2}}:[0-5][0-9]|{NUM}(?:点半|点整|点|时)?)"
_RANGE = re.compile(
    rf"(?<![0-9:])(?P<p1>{_PERIOD})?(?P<t1>{_TOKEN})(?P<sep>[到至~\-—–])(?P<p2>{_PERIOD})?(?P<t2>{_TOKEN})"
    r"(?![0-9:]|个?小时|个?钟头|分钟|号|日|月|年|元|块|天|周|次|人|个)"
)
RANK = {"ok": 0, "outside_hours": 1, "bad_length": 2, "unaligned": 3, "bad_order": 4}
ISSUE_TEXT = {
    "ambiguous": "分不清是上午还是晚上",
    "unaligned": "不是整点开始",
    "bad_length": "时长不是 1 小时或 2 小时",
    "outside_hours": "不在 09:00–22:00 内",
    "bad_order": "结束时间要晚于开始时间",
}


@dataclass(frozen=True, slots=True)
class WindowMention:
    pos: int
    text: str
    kind: str  # range | start
    start: int | None = None
    end: int | None = None
    issue: str | None = None
    starts: tuple[int, ...] = ()  # lone starts: every reading, in minutes
    stop: int = 0


@dataclass(frozen=True, slots=True)
class WindowScan:
    text: str  # normalised, courts and dates blanked, ranges still readable
    mentions: tuple[WindowMention, ...]
    durations: tuple[int, ...]


def judge(start: int, end: int) -> str:
    if end <= start:
        return "bad_order"
    if start % 60 or end % 60:
        return "unaligned"
    if end - start not in (60, 120):
        return "bad_length"
    if start < OPEN_MINUTE or end > CLOSE_MINUTE:
        return "outside_hours"
    return "ok"


def _token(token: str) -> tuple[int, int, bool] | None:
    clock = re.fullmatch(r"([0-9]{1,2}):([0-5][0-9])", token)
    if clock:
        return int(clock[1]), int(clock[2]), clock[1].startswith("0")
    match = re.fullmatch(rf"({NUM})(点半|点整|点|时)?", token)
    hour = to_int(match[1]) if match else None
    if hour is None:
        return None
    return hour, 30 if match[2] == "点半" else 0, False


def _side(period: str | None, token: str) -> list[int]:
    parsed = _token(token)
    if parsed is None:
        return []
    hour, minute, literal = parsed
    minutes = {h * 60 + minute for h in time_nlu.hour_candidates(period, hour, literal)}
    return sorted(m for m in minutes if m >= 0)


def _pair(pos: int, text: str, first: list[int], second: list[int], stop: int = 0) -> WindowMention | None:
    options = [(a, b) for a in first for b in second]
    if not options:
        return None
    good = [(a, b) for a, b in options if judge(a, b) == "ok"]
    if len(good) == 1:
        return WindowMention(pos, text, "range", good[0][0], good[0][1], stop=stop)
    if len(good) > 1:
        return WindowMention(pos, text, "range", good[0][0], good[0][1], "ambiguous", tuple(sorted({a for a, _ in good})), stop)
    a, b = min(options, key=lambda o: (RANK[judge(*o)], o))
    return WindowMention(pos, text, "range", a, b, judge(a, b), stop=stop)


def _bare_chinese(token: str) -> bool:
    return not re.search(r"[0-9]|点|时", token)


def resolve_start(mention: WindowMention, minutes: int) -> tuple[int | None, int | None, str | None]:
    """Give a lone start a length. Returns (start, end, issue)."""
    readings = list(mention.starts)
    if not readings:
        return None, None, "ambiguous"
    if any(r % 60 for r in readings):
        return readings[0], readings[0] + minutes, "unaligned"
    fits = [r for r in readings if judge(r, r + minutes) == "ok"]
    if len(fits) == 1:
        return fits[0], fits[0] + minutes, None
    if len(fits) > 1:
        return fits[0], fits[0] + minutes, "ambiguous"
    return readings[0], readings[0] + minutes, "outside_hours"


def scan_windows(text: str) -> WindowScan:
    clean = date_nlu.mask_dates(court_nlu.mask_courts(text))
    mentions: list[WindowMention] = []
    blank = list(clean)
    for match in _RANGE.finditer(clean):
        if _bare_chinese(match["t1"]) and _bare_chinese(match["t2"]):
            continue
        if _bare_chinese(match["t1"]) != _bare_chinese(match["t2"]) and not (match["t1"].isdigit() or match["t2"].isdigit()):
            continue
        first = _side(match["p1"], match["t1"])
        second = _side(match["p2"] or match["p1"], match["t2"])
        mention = _pair(match.start(), match.group(0), first, second, match.end())
        if mention is None:
            mention = WindowMention(match.start(), match.group(0), "range", issue="outside_hours", stop=match.end())
        mentions.append(mention)
        blank[match.start():match.end()] = "□" * (match.end() - match.start())
    rest = "".join(blank)
    seen = time_nlu.scan_times(rest)
    index = 0
    while index < len(seen):
        current = seen[index]
        following = seen[index + 1] if index + 1 < len(seen) else None
        if current.role == "end":
            index += 1
            continue
        if following is not None and following.role == "end":
            first = sorted({int(c[:2]) * 60 + int(c[3:]) for c in current.candidates})
            second = sorted({int(c[:2]) * 60 + int(c[3:]) for c in following.candidates})
            mention = _pair(current.pos, current.text + "…" + following.text, first, second, following.pos + len(following.text))
            if mention is not None:
                mentions.append(mention)
            index += 2
            continue
        starts = tuple(sorted({int(c[:2]) * 60 + int(c[3:]) for c in current.candidates}))
        mentions.append(WindowMention(current.pos, current.text, "start", issue="ambiguous" if len(starts) > 1 else None, starts=starts, stop=current.pos + len(current.text)))
        index += 1
    mentions.sort(key=lambda m: m.pos)
    durations = tuple(dict.fromkeys(time_nlu.scan_durations(rest)))
    return WindowScan(clean, tuple(mentions), durations)


def label(start: int, end: int) -> str:
    """Compact label for chat: 14-16, or 14:30-16:30 when not on the hour."""
    def one(minutes: int) -> str:
        hour, minute = divmod(minutes, 60)
        return f"{hour}" if minute == 0 else f"{hour}:{minute:02d}"
    return f"{one(start)}-{one(end)}"


def clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
