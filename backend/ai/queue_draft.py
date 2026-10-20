"""Fold a conversation into a booking-queue draft, deterministically and statelessly.

Each request replays every user turn, so the same words always give the same draft.
The question a turn answers (asked[i-1]) tells the parser how to read short replies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from backend.ai import queue_cues as cue
from backend.ai.nlu import courts as court_nlu
from backend.ai.nlu import dates as date_nlu
from backend.ai.nlu.text import prep
from backend.ai.nlu.windows import resolve_start, scan_windows

TWO, ONE = 120, 60
TAG = {TWO: "2h", ONE: "1h"}
MAX_ENTRIES = 32


@dataclass
class Group:
    minutes: int
    windows: list[tuple[int, int]] = field(default_factory=list)
    issue: str | None = None
    issue_text: str = ""
    acked: set = field(default_factory=set)
    courts: list[int] = field(default_factory=list)
    bad_courts: list[int] = field(default_factory=list)
    court_bindings: dict[tuple[int, int], list[int]] = field(default_factory=dict)
    court_scope_ambiguous: bool = False


@dataclass
class Draft:
    booking_mode: str | None = None
    date_state: str = "empty"
    dates: tuple = ()
    groups: dict[int, Group] = field(default_factory=lambda: {TWO: Group(TWO), ONE: Group(ONE)})
    asked: list = field(default_factory=list)
    duration_issue: tuple[int, int] | None = None

    @property
    def g2(self) -> Group:
        return self.groups[TWO]

    @property
    def g1(self) -> Group:
        return self.groups[ONE]

    def effective(self, minutes: int) -> bool:
        """Does this group take part in the queue?"""
        return self.booking_mode == "both" or (
            self.booking_mode == "two_hour_only" and minutes == TWO
        ) or (self.booking_mode == "one_hour_only" and minutes == ONE)

    def courts_of(self, minutes: int) -> list[int]:
        return self.groups[minutes].courts


def overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def overlapping_pairs(windows: list[tuple[int, int]]) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    return [(a, b) for i, a in enumerate(windows) for b in windows[i + 1:] if overlaps(a, b)]


def entry_count(draft: Draft) -> dict[int, int]:
    return {m: len(draft.groups[m].windows) * len(draft.courts_of(m)) for m in (TWO, ONE) if draft.effective(m)}


def _date_from(turn: str, today: date, draft: Draft, field_name: str | None, first: bool) -> None:
    mentions = date_nlu.scan_dates(court_nlu.mask_courts(turn), today)
    if not (first or field_name == "target_date"):
        mentions = [m for m in mentions if m.kind != "bare_day"]  # "1号" answering a court question is not a day
    use = [m for m in mentions if m.kind != "bare_day"] or mentions
    if not use:
        return
    found = tuple(dict.fromkeys(d for m in use for d in m.dates))
    if len(found) == 1 and not any(m.ambiguous for m in use):
        draft.date_state, draft.dates = "resolved", found
    else:
        draft.date_state, draft.dates = "ambiguous", ()


def _default_minutes(field_name: str | None, turn_minutes: int | None) -> int:
    if turn_minutes is not None:
        return turn_minutes
    if field_name and field_name.endswith("_1h"):
        return ONE
    return TWO


def _apply_windows(draft: Draft, turn: str, field_name: str | None) -> None:
    scan = scan_windows(turn)
    text = scan.text
    turn_minutes = scan.durations[0] if len(scan.durations) == 1 else None
    unsupported = next((minutes for minutes in scan.durations if minutes not in (TWO, ONE)), None)
    if unsupported is not None:
        range_minutes = next((m.end - m.start for m in scan.mentions
                              if m.kind == "range" and m.start is not None and m.end is not None
                              and m.end - m.start in (TWO, ONE)), None)
        issue_group = range_minutes or (ONE if field_name and field_name.endswith("_1h") else TWO)
        draft.duration_issue = (unsupported, issue_group)
    elif (field_name in ("windows_2h", "windows_1h")
          and scan.durations and all(minutes in (TWO, ONE) for minutes in scan.durations)):
        draft.duration_issue = None
    default = _default_minutes(field_name, turn_minutes)
    touched: dict[int, tuple[str, str] | None] = {}
    replaced: set[int] = set()
    previous_mode, previous_stop = None, None
    for mention in scan.mentions:
        mode = cue.mode_before(text, mention.pos, cue.sentence_start(text, mention.pos))
        if mode is None and previous_stop is not None and cue.only_separators(text[previous_stop:mention.pos]):
            mode = previous_mode
        mode = mode or cue.mode_after(text, mention.stop)
        previous_mode, previous_stop = mode, mention.stop
        if mention.kind == "range":
            start, end, issue = mention.start, mention.end, mention.issue
            length = end - start if start is not None and end is not None else 0
            minutes = length if length in (TWO, ONE) else default
        else:
            minutes = default
            if minutes not in (TWO, ONE):
                start, end, issue, minutes = (mention.starts[0] if mention.starts else None), None, "bad_length", TWO
            else:
                start, end, issue = resolve_start(mention, minutes)
        group = draft.groups[minutes]
        if mode == "remove":
            for other in draft.groups.values():
                if (start, end) in other.windows:
                    other.windows.remove((start, end))
            continue
        if issue:
            touched[minutes] = (issue, mention.text)
            continue
        key = (start, end)
        if mode in ("replace", "only") and minutes not in replaced:
            group.windows.clear()
            group.acked.clear()
            replaced.add(minutes)
        tag = TAG[minutes]
        if field_name == f"overlap_{tag}" and mode is None and key in group.windows:
            group.windows = [w for w in group.windows if w == key or not overlaps(w, key)]
        elif key not in group.windows:
            group.windows.append(key)
        touched.setdefault(minutes, None)
    for minutes, outcome in touched.items():
        group = draft.groups[minutes]
        group.issue, group.issue_text = (outcome if outcome else (None, ""))
    if field_name in ("overlap_2h", "overlap_1h"):
        group = draft.g2 if field_name == "overlap_2h" else draft.g1
        if cue.contains_any(text, cue.KEEP_STRONG) or (not scan.mentions and cue.contains_any(text, cue.KEEP_WEAK)):
            group.acked |= {frozenset(pair) for pair in overlapping_pairs(group.windows)}


def _preceding_window(scan, pos: int):
    for window in reversed(scan.mentions):
        if window.stop > pos:
            continue
        if window.kind == 'range':
            if not window.issue and window.start is not None and window.end is not None:
                return (window.start, window.end), window.end - window.start
            return None, None
        return None, None
    return None, None


def _apply_courts(draft: Draft, turn: str, field_name: str | None) -> None:
    scan = scan_windows(turn)
    text = prep(turn)
    mentions = court_nlu.scan_courts(turn)
    mentions += [court_nlu.CourtMention(m.group(), tuple(range(1, 11)), False, m.start())
                 for m in court_nlu.ALL_COURTS.finditer(text)]
    if not mentions and field_name and field_name.startswith("courts_"):
        mentions = court_nlu.scan_bare_courts(turn)
    mentions.sort(key=lambda mention: mention.pos)
    fallback = ONE if (field_name and field_name.endswith("_1h")) or draft.booking_mode == "one_hour_only" else TWO
    floor = 0
    previous_mode, previous_stop = None, None
    for mention in mentions:
        preceding_text = text[floor:mention.pos]
        window, window_minutes = _preceding_window(scan, mention.pos)
        stated_minutes = cue.governing_hours(preceding_text)
        target = stated_minutes or (window_minutes if window_minutes in (TWO, ONE) else fallback)
        scoped_window = window if window_minutes == target else None
        floor = mention.pos + len(mention.text)
        group = draft.groups[target]
        tag = TAG[target]
        explicit_mode = cue.mode_before(text, mention.pos, cue.sentence_start(text, mention.pos))
        mode = explicit_mode
        if mode is None and previous_stop is not None and cue.only_separators(text[previous_stop:mention.pos]):
            mode = previous_mode
        mode = 'remove' if mention.negated else mode or cue.mode_after(text, floor)
        previous_mode, previous_stop = mode, floor
        wholesale = bool(court_nlu.ALL_COURTS.fullmatch(mention.text))
        if mode == 'remove':
            if wholesale:
                group.courts.clear()
                group.bad_courts.clear()
            else:
                group.courts = [n for n in group.courts if n not in mention.numbers]
                group.bad_courts = [n for n in group.bad_courts if n not in mention.numbers]
            for bound in group.court_bindings.values():
                bound[:] = [n for n in bound if n not in mention.numbers]
            group.court_bindings = {key: bound for key, bound in group.court_bindings.items() if bound}
            continue
        scoped_cues = ("选", "订", "预约", "用", "的", "改成", "改为", "换成", "换为")
        has_later_window = any(
            candidate.pos > mention.pos and candidate.kind == "range"
            and candidate.start is not None and candidate.end is not None
            and candidate.end - candidate.start == target
            for candidate in scan.mentions
        )
        has_other_binding = any(key != scoped_window for key in group.court_bindings)
        scope_prefix = preceding_text.rstrip("、,，和及与跟或 ")
        scope_marked = (any(scope_prefix.endswith(cue_text) for cue_text in scoped_cues)
                        or (scope_prefix.endswith("选") and not scope_prefix.endswith(("候选", "备选"))))
        scoped = bool(scoped_window and explicit_mode is None and (
            len(group.windows) == 1 or has_later_window or has_other_binding
            or scope_marked
        ))
        replace = explicit_mode in ('replace', 'only') or wholesale or field_name == f"courts_{tag}"
        if replace and not (scoped and any(key != scoped_window for key in group.court_bindings)):
            group.courts.clear()
            group.bad_courts.clear()
            group.court_bindings.clear()
            group.court_scope_ambiguous = False
        for number in mention.numbers:
            if 1 <= number <= 10:
                if number not in group.courts:
                    group.courts.append(number)
            elif number not in group.bad_courts:
                group.bad_courts.append(number)
        if scoped:
            if explicit_mode in ('replace', 'only'):
                group.court_bindings[scoped_window] = list(mention.numbers)
            else:
                bound = group.court_bindings.setdefault(scoped_window, [])
                bound.extend(number for number in mention.numbers if number not in bound)
        else:
            for key in group.windows:
                group.court_bindings[key] = list(group.courts)
    for group in draft.groups.values():
        group.court_scope_ambiguous = len({tuple(bound) for bound in group.court_bindings.values()}) > 1


def fold(turns: list[str], asked: list, today: date, *, reference_date: date | None = None,
         turn_kinds: list[str] | None = None) -> Draft:
    draft = Draft(asked=list(asked))
    reference_date = reference_date or today
    turn_kinds = turn_kinds or ["answer"] * len(turns)
    if len(turn_kinds) != len(turns):
        raise ValueError("turn_kinds must match turns")
    for index, turn in enumerate(turns):
        if turn_kinds[index] == "question":
            continue
        field_name = asked[index - 1] if index and index - 1 < len(asked) else None
        mode = cue.booking_mode(turn, field_name, first=index == 0)
        if mode:
            draft.booking_mode = mode
        scan = scan_windows(turn)
        durations = {mention.end - mention.start for mention in scan.mentions
                     if mention.kind == "range" and mention.start is not None and mention.end is not None}
        if {TWO, ONE}.issubset(durations):
            draft.booking_mode = "both"
    for index, turn in enumerate(turns):
        if turn_kinds[index] == "question":
            continue
        field_name = asked[index - 1] if index and index - 1 < len(asked) else None
        _date_from(turn, reference_date, draft, field_name, index == 0)
        _apply_windows(draft, turn, field_name)
        _apply_courts(draft, turn, field_name)
    return draft
