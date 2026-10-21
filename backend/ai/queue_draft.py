"""Legacy natural-language parser used to migrate v2 conversation snapshots.

New turns apply the model's typed updates directly to Draft; keep this parser until
all persisted v2 conversations have either migrated or expired.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from backend.ai import queue_cues as cue
from backend.ai.nlu import courts as court_nlu
from backend.ai.nlu import dates as date_nlu
from backend.ai.nlu.text import prep
from backend.ai.nlu.windows import judge, resolve_start, scan_windows
from backend.ai.queue_policy import MAX_CANDIDATES, MAX_INVALID_WINDOWS_PER_GROUP

TWO, ONE = 120, 60
TAG = {TWO: "2h", ONE: "1h"}
MAX_ENTRIES = MAX_CANDIDATES


@dataclass
class Group:
    minutes: int
    windows: list[tuple[int, int]] = field(default_factory=list)
    invalid_windows: list[tuple[int, int, str, str]] = field(default_factory=list)
    issue: str | None = None
    issue_text: str = ""
    acked: set = field(default_factory=set)
    courts: list[int] = field(default_factory=list)
    bad_courts: list[int] = field(default_factory=list)
    court_bindings: dict[tuple[int, int], list[int]] = field(default_factory=dict)
    court_scope_ambiguous: bool = False
    courts_issue: str | None = None


@dataclass
class Draft:
    booking_mode: str | None = None
    mode_issue: str | None = None
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


def _mask_courts_in_court_answer(turn: str, field_name: str | None) -> str:
    if not field_name or not field_name.startswith("courts_"):
        return turn
    source = prep(turn)
    mentions = court_nlu.scan_bare_courts(source)
    if not mentions:
        return turn
    masked = list(source)
    for mention in mentions:
        masked[mention.pos:mention.pos + len(mention.text)] = "□" * len(mention.text)
    return "".join(masked)


def _date_from(turn: str, today: date, draft: Draft, field_name: str | None, first: bool) -> None:
    source = _mask_courts_in_court_answer(turn, field_name)
    mentions = date_nlu.scan_dates(court_nlu.mask_courts(source), today)
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
    scan = scan_windows(_mask_courts_in_court_answer(turn, field_name))
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
            hinted = cue.governing_hours(text[:mention.pos])
            expected = hinted or (default if field_name in ("windows_2h", "windows_1h") else None)
            minutes = expected or (length if length in (TWO, ONE) else default)
            if expected in (TWO, ONE) and length and length != expected and issue is None:
                issue = "bad_length"
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
    scan = scan_windows(_mask_courts_in_court_answer(turn, field_name))
    text = prep(turn)
    mentions = (court_nlu.scan_bare_courts(turn)
                if field_name and field_name.startswith("courts_") else [])
    if not mentions:
        mentions = court_nlu.scan_courts(turn)
    mentions += [court_nlu.CourtMention(m.group(), tuple(range(1, 11)), False, m.start())
                 for m in court_nlu.ALL_COURTS.finditer(text)]
    mentions.sort(key=lambda mention: mention.pos)
    fallback = ONE if (field_name and field_name.endswith("_1h")) or draft.booking_mode == "one_hour_only" else TWO
    floor = 0
    previous_mode, previous_stop = None, None
    cleared_groups: set[int] = set()
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
        scoped = bool(scoped_window and (
            (explicit_mode is None and (len(group.windows) == 1 or has_later_window or has_other_binding or scope_marked))
            or (explicit_mode in ('replace', 'only') and has_later_window)
        ))
        replace = mode != 'remove' and (
            explicit_mode in ('replace', 'only') or wholesale
            or field_name == f"courts_{tag}" and explicit_mode != 'append'
        )
        if (replace and (target not in cleared_groups or explicit_mode in ('replace', 'only') and not scoped)
                and not (scoped and any(key != scoped_window for key in group.court_bindings))):
            group.courts.clear()
            group.bad_courts.clear()
            group.court_bindings.clear()
            group.court_scope_ambiguous = False
            cleared_groups.add(target)
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
    explicit_mode_seen = False
    for index, turn in enumerate(turns):
        if turn_kinds[index] == "question":
            continue
        field_name = asked[index - 1] if index and index - 1 < len(asked) else None
        mode = cue.booking_mode(turn, field_name, first=index == 0)
        if mode:
            draft.booking_mode = mode
            explicit_mode_seen = True
        scan = scan_windows(turn)
        durations = {mention.end - mention.start for mention in scan.mentions
                     if mention.kind == "range" and mention.start is not None and mention.end is not None}
        if {TWO, ONE}.issubset(durations) and not explicit_mode_seen:
            draft.booking_mode = "both"
    for index, turn in enumerate(turns):
        if turn_kinds[index] == "question":
            continue
        field_name = asked[index - 1] if index and index - 1 < len(asked) else None
        _date_from(turn, reference_date, draft, field_name, index == 0)
        _apply_windows(draft, turn, field_name)
        _apply_courts(draft, turn, field_name)
    return draft


def reconcile_legacy_slots(draft: Draft, snapshot: object) -> Draft:
    """Use the last saved slot statuses to correct one-time migration from old queue flows."""
    if type(snapshot) is not dict or type(snapshot.get("slots")) is not list:
        return draft
    slots = {}
    for item in snapshot["slots"]:
        if (type(item) is dict and isinstance(item.get("field"), str)
                and item.get("status") in {"empty", "proposed", "verified", "ambiguous", "invalid"}):
            slots[item["field"]] = item

    date_slot = slots.get("target_date")
    if date_slot and date_slot["status"] in {"ambiguous", "invalid"}:
        draft.date_state, draft.dates = "ambiguous", ()

    want_one_hour = slots.get("want_1h")
    if want_one_hour:
        mode = cue.booking_mode(str(want_one_hour.get("display") or ""), "want_1h")
        if mode and want_one_hour["status"] in {"proposed", "verified"}:
            draft.booking_mode, draft.mode_issue = mode, None
        elif want_one_hour["status"] in {"empty", "ambiguous", "invalid"} and want_one_hour.get("active", True):
            draft.booking_mode = None
            draft.mode_issue = "旧记录中是否加入1小时备选尚未确认。" if want_one_hour["status"] != "empty" else None

    for minutes, tag in ((TWO, "2h"), (ONE, "1h")):
        group = draft.groups[minutes]
        windows_slot = slots.get(f"windows_{tag}")
        if windows_slot:
            status, display = windows_slot["status"], windows_slot.get("display")
            if status == "proposed" and isinstance(display, str) and display:
                scan = scan_windows(display)
                windows = [(m.start, m.end) for m in scan.mentions
                           if m.kind == "range" and m.start is not None and m.end is not None
                           and m.end - m.start == minutes and judge(m.start, m.end) == "ok"]
                if windows:
                    group.windows = list(dict.fromkeys(windows))
                    group.invalid_windows = []
                    group.issue, group.issue_text = None, ""
                    if draft.duration_issue and draft.duration_issue[1] == minutes:
                        draft.duration_issue = None
            elif status == "empty":
                group.windows, group.issue, group.issue_text = [], None, ""
                group.invalid_windows = []
                if draft.duration_issue and draft.duration_issue[1] == minutes:
                    draft.duration_issue = None
            elif status == "verified" and windows_slot.get("active") is False:
                group.windows, group.issue, group.issue_text = [], None, ""
                group.invalid_windows = []
                if draft.duration_issue and draft.duration_issue[1] == minutes:
                    draft.duration_issue = None
            elif status in {"ambiguous", "invalid"} and group.issue is None:
                # Old snapshots stored a status but no typed invalid value; block until the user restates it.
                group.issue = "ambiguous"

        courts_slot = slots.get(f"courts_{tag}")
        if courts_slot:
            status, display = courts_slot["status"], courts_slot.get("display")
            if status == "proposed" and isinstance(display, str) and display:
                mentions = court_nlu.scan_courts(display) or court_nlu.scan_bare_courts(display)
                courts = list(dict.fromkeys(n for mention in mentions for n in mention.numbers if 1 <= n <= 10))
                if courts:
                    group.courts, group.bad_courts = courts, []
                    group.courts_issue, group.court_scope_ambiguous = None, False
            elif status == "empty":
                group.courts, group.bad_courts, group.court_bindings = [], [], {}
                group.courts_issue, group.court_scope_ambiguous = None, False
            elif status == "verified" and courts_slot.get("active") is False:
                group.courts, group.bad_courts, group.court_bindings = [], [], {}
                group.courts_issue, group.court_scope_ambiguous = None, False
            elif status in {"ambiguous", "invalid"} and not (group.bad_courts or group.courts_issue):
                group.courts_issue = "旧记录中的场地尚未确认，请重新选择1～10号场，例如1号和4号。"

        overlap_slot = slots.get(f"overlap_{tag}")
        if overlap_slot and overlap_slot["status"] == "verified":
            group.acked.update(frozenset(pair) for pair in overlapping_pairs(group.windows))
        elif overlap_slot and overlap_slot["status"] in {"ambiguous", "invalid"}:
            group.acked.difference_update(frozenset(pair) for pair in overlapping_pairs(group.windows))
    return draft


def serialize_draft(draft: Draft) -> dict:
    """Persist canonical facts, never model-generated parser text."""
    groups = {}
    for minutes, tag in ((TWO, "2h"), (ONE, "1h")):
        group = draft.groups[minutes]
        groups[tag] = {
            "windows": [list(window) for window in group.windows],
            "invalid_windows": [{"start": start, "end": end, "issue": issue, "label": label}
                                for start, end, issue, label in group.invalid_windows],
            "issue": group.issue, "issue_text": group.issue_text,
            "acked": [[list(window) for window in sorted(pair)]
                      for pair in sorted(group.acked, key=lambda item: sorted(item))],
            "courts": list(group.courts), "bad_courts": list(group.bad_courts),
            "court_bindings": [{"window": list(window), "courts": list(courts)}
                               for window, courts in sorted(group.court_bindings.items())],
            "court_scope_ambiguous": group.court_scope_ambiguous,
            "courts_issue": group.courts_issue,
        }
    return {
        "booking_mode": draft.booking_mode, "mode_issue": draft.mode_issue,
        "date_state": draft.date_state, "dates": [day.isoformat() for day in draft.dates],
        "groups": groups, "asked": list(draft.asked),
        "duration_issue": list(draft.duration_issue) if draft.duration_issue else None,
    }


def deserialize_draft(value: object) -> Draft | None:
    """Load the server's JSON state defensively; invalid snapshots are ignored."""
    if type(value) is not dict or set(value) != {
        "booking_mode", "mode_issue", "date_state", "dates", "groups", "asked", "duration_issue",
    }:
        return None
    if value["booking_mode"] not in (None, "two_hour_only", "one_hour_only", "both"):
        return None
    if type(value["date_state"]) is not str or value["date_state"] not in {"empty", "resolved", "ambiguous"}:
        return None
    if (value["mode_issue"] is not None and type(value["mode_issue"]) is not str
            or type(value["dates"]) is not list or type(value["asked"]) is not list
            or any(type(item) is not str for item in value["asked"])):
        return None
    try:
        dates = tuple(date.fromisoformat(item) for item in value["dates"])
    except (TypeError, ValueError):
        return None
    if (value["date_state"] == "resolved" and len(dates) != 1
            or value["date_state"] != "resolved" and dates):
        return None
    raw_groups = value["groups"]
    if type(raw_groups) is not dict or set(raw_groups) != {"2h", "1h"}:
        return None
    draft = Draft(booking_mode=value["booking_mode"], mode_issue=value["mode_issue"],
                  date_state=value["date_state"], dates=dates, asked=list(value["asked"]))
    for minutes, tag in ((TWO, "2h"), (ONE, "1h")):
        raw = raw_groups[tag]
        old_keys = {"windows", "issue", "issue_text", "acked", "courts", "bad_courts",
                    "court_bindings", "court_scope_ambiguous", "courts_issue"}
        if type(raw) is not dict or set(raw) not in (old_keys, old_keys | {"invalid_windows"}):
            return None
        if any(type(raw[key]) is not list for key in ("windows", "acked", "courts", "bad_courts", "court_bindings")):
            return None
        if any(raw[key] is not None and type(raw[key]) is not str for key in ("issue", "issue_text", "courts_issue")):
            return None
        if type(raw["court_scope_ambiguous"]) is not bool:
            return None
        group = draft.groups[minutes]
        invalid_windows = raw.get("invalid_windows", [])
        if type(invalid_windows) is not list or len(invalid_windows) > MAX_INVALID_WINDOWS_PER_GROUP:
            return None
        for item in invalid_windows:
            if (type(item) is not dict or set(item) != {"start", "end", "issue", "label"}
                    or type(item["start"]) is not int or type(item["end"]) is not int
                    or not 0 <= item["start"] <= 99 * 60 + 59 or not 0 <= item["end"] <= 99 * 60 + 59
                    or not isinstance(item["issue"], str)
                    or item["issue"] not in {"bad_order", "bad_length", "outside_hours", "unaligned"}
                    or not isinstance(item["label"], str) or len(item["label"]) > 80):
                return None
            group.invalid_windows.append((item["start"], item["end"], item["issue"], item["label"]))
        for window in raw["windows"]:
            pair = _state_pair(window)
            if (pair is None or pair[1] - pair[0] != minutes or pair[0] < 9 * 60
                    or pair[1] > 22 * 60 or pair[0] % 60 or pair[1] % 60 or pair in group.windows):
                return None
            group.windows.append(pair)
        for pair_value in raw["acked"]:
            if type(pair_value) is not list or len(pair_value) != 2:
                return None
            first, second = (_state_pair(window) for window in pair_value)
            if first is None or second is None:
                return None
            group.acked.add(frozenset({first, second}))
        for key in ("courts", "bad_courts"):
            items = raw[key]
            if any(type(number) is not int or not 0 <= number <= 99 for number in items):
                return None
        if any(not 1 <= number <= 10 for number in raw["courts"]) or len(set(raw["courts"])) != len(raw["courts"]):
            return None
        group.courts = list(raw["courts"])
        group.bad_courts = list(raw["bad_courts"])
        group.issue, group.issue_text = raw["issue"], raw["issue_text"]
        group.court_scope_ambiguous, group.courts_issue = raw["court_scope_ambiguous"], raw["courts_issue"]
        for binding in raw["court_bindings"]:
            if type(binding) is not dict or set(binding) != {"window", "courts"}:
                return None
            window = _state_pair(binding["window"])
            courts = binding["courts"]
            if (window is None or type(courts) is not list
                    or any(type(number) is not int or not 0 <= number <= 99 for number in courts)):
                return None
            group.court_bindings[window] = list(courts)
    duration_issue = value["duration_issue"]
    if duration_issue is not None:
        if (type(duration_issue) is not list or len(duration_issue) != 2
                or any(type(item) is not int for item in duration_issue)
                or not 1 <= duration_issue[0] <= 1440 or duration_issue[1] not in (ONE, TWO)):
            return None
        draft.duration_issue = tuple(duration_issue)
    return draft


def _state_pair(value: object) -> tuple[int, int] | None:
    if (type(value) is not list or len(value) != 2
            or any(type(item) is not int or not 0 <= item <= 24 * 60 for item in value)
            or value[0] >= value[1]):
        return None
    return value[0], value[1]
