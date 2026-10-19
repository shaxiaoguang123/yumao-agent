"""Slots, queue entries, progress strip and question text derived from a folded draft."""
from __future__ import annotations

from collections import Counter
from datetime import date

from backend.ai import queue_text as text
from backend.ai.conversation import PRIORITY, Reason, Slot, SlotStatus
from backend.ai.nlu.windows import clock
from backend.ai.queue_draft import MAX_ENTRIES, ONE, TWO, Draft, entry_count, overlapping_pairs

_DONE = {SlotStatus.PROPOSED, SlotStatus.VERIFIED}
_GROUPS = ((TWO, "2h"), (ONE, "1h"))


def _slot(field: str, status: SlotStatus, value=None, display="", detail=None, reason=None, active=True) -> Slot:
    if reason is None and status in (SlotStatus.AMBIGUOUS, SlotStatus.INVALID):
        reason = Reason.AMBIGUOUS if status is SlotStatus.AMBIGUOUS else Reason.INVALID
    return Slot(field, status, value, display, detail, reason, active)


def _off(field: str) -> Slot:
    return Slot(field, SlotStatus.VERIFIED, None, "", None, None, active=False)


def _date_slot(draft: Draft, today: date) -> Slot:
    if draft.date_state == "empty":
        return _slot("target_date", SlotStatus.EMPTY, reason=Reason.MISSING)
    if draft.date_state == "ambiguous":
        return _slot("target_date", SlotStatus.AMBIGUOUS, detail="ambiguous")
    day = draft.dates[0]
    if day < today:
        return _slot("target_date", SlotStatus.INVALID, day.isoformat(), text.show_date(day), "past")
    return _slot("target_date", SlotStatus.PROPOSED, day.isoformat(), text.show_date(day))


def _group_slots(draft: Draft, minutes: int, tag: str) -> dict[str, Slot]:
    group, asks = draft.groups[minutes], Counter(draft.asked)
    if not draft.effective(minutes):
        return {f"{name}_{tag}": _off(f"{name}_{tag}") for name in ("windows", "more", "overlap", "courts")}
    windows, courts = f"windows_{tag}", f"courts_{tag}"
    if group.issue:
        detail = text.issue_detail(minutes, group.issue, group.issue_text)
        status = SlotStatus.AMBIGUOUS if group.issue == "ambiguous" else SlotStatus.INVALID
        windows_slot = _slot(windows, status, group.windows, detail=detail)
    elif group.windows:
        windows_slot = _slot(windows, SlotStatus.PROPOSED, list(group.windows), text.show_windows(group.windows))
    else:
        windows_slot = _slot(windows, SlotStatus.EMPTY, reason=Reason.MISSING)
    settled = windows_slot.status in _DONE
    more_done = group.more_done or asks[f"more_{tag}"] >= 2
    more = _slot(f"more_{tag}", SlotStatus.VERIFIED if more_done else SlotStatus.EMPTY, reason=None if more_done else Reason.MISSING,
                 active=settled)
    pairs = [p for p in overlapping_pairs(group.windows) if frozenset(p) not in group.acked]
    if pairs and asks[f"overlap_{tag}"] < 2:
        overlap = _slot(f"overlap_{tag}", SlotStatus.AMBIGUOUS, pairs, active=settled)
    else:
        overlap = _slot(f"overlap_{tag}", SlotStatus.VERIFIED, active=settled and len(group.windows) > 1)
    group_courts = draft.courts_of(minutes)
    if group.bad_courts:
        bad = "、".join(f"{n}号场" for n in group.bad_courts)
        courts_slot = _slot(courts, SlotStatus.INVALID, detail=f"{bad}不在可选范围，这里只支持1～10号场。")
    elif group.court_scope_ambiguous:
        courts_slot = _slot(courts, SlotStatus.AMBIGUOUS, detail="你为不同时段指定了不同场地。目前每个时段共用同一组场地，不能直接交叉组合。请给出同意用于全部时段的场地列表；如果需要分别指定，请改用“选择预约”手动选场。")
    elif group_courts:
        courts_slot = _slot(courts, SlotStatus.PROPOSED, list(group_courts), text.show_courts(group_courts))
    else:
        courts_slot = _slot(courts, SlotStatus.EMPTY, reason=Reason.MISSING)
    return {windows: windows_slot, f"more_{tag}": more, f"overlap_{tag}": overlap, courts: courts_slot}


def _want_slot(draft: Draft) -> Slot:
    if draft.g1.wanted is False and draft.g2.wanted is False:
        return _slot("want_1h", SlotStatus.INVALID, detail="both_disabled")
    if draft.g2.wanted is False:
        return _off("want_1h")
    if draft.g1.wanted is True:
        return _slot("want_1h", SlotStatus.VERIFIED, True, "要")
    if draft.g1.wanted is False or Counter(draft.asked)["want_1h"] >= 2:
        return _slot("want_1h", SlotStatus.VERIFIED, False, "不需要")
    return _slot("want_1h", SlotStatus.EMPTY, reason=Reason.MISSING)


def build_slots(draft: Draft, today: date) -> dict[str, Slot]:
    slots = {"target_date": _date_slot(draft, today)}
    slots.update(_group_slots(draft, TWO, "2h"))
    slots["want_1h"] = _want_slot(draft)
    slots.update(_group_slots(draft, ONE, "1h"))
    if draft.duration_issue:
        duration, minutes = draft.duration_issue
        if not draft.effective(minutes):
            minutes = ONE if draft.effective(ONE) else TWO
        tag = dict(_GROUPS)[minutes]
        field = f"windows_{tag}"
        text_duration = f"{duration // 60}小时{duration % 60}分钟" if duration % 60 else f"{duration // 60}小时"
        slots[field] = _slot(field, SlotStatus.AMBIGUOUS, detail=text.issue_detail(minutes, "unsupported_duration", text_duration))
    counts = entry_count(draft)
    total = sum(counts.values())
    if total > MAX_ENTRIES:
        minutes = max(counts, key=counts.get)
        field = f"courts_{dict(_GROUPS)[minutes]}"
        detail = f"按现在的时段和场地一共会生成 {total} 项候选，最多 {MAX_ENTRIES} 项。请少选几个场地。"
        slots[field] = _slot(field, SlotStatus.INVALID, slots[field].value, slots[field].display, detail)
    return {name: slots[name] for name in PRIORITY}


def build_entries(draft: Draft, scope_label: str | None = None) -> list[dict]:
    """Time-major order inside each length; 2小时 candidates come before 1小时 ones."""
    entries = []
    for minutes, _ in _GROUPS:
        if not draft.effective(minutes):
            continue
        for start, end in draft.groups[minutes].windows:
            for court in draft.courts_of(minutes):
                entry = {"court_preference": f"{court}号场", "start_time": clock(start), "end_time": clock(end),
                         "duration_minutes": minutes}
                if scope_label:
                    entry["scope_label"] = scope_label
                entries.append(entry)
    return entries


def window_summary(draft: Draft) -> list[dict]:
    return [{"minutes": m, "label": text.HOURS[m], "windows": [text.show_windows([w]) for w in draft.groups[m].windows],
             "courts": draft.courts_of(m)} for m, _ in _GROUPS if draft.effective(m) and draft.groups[m].windows]


def strip(draft: Draft, slots: dict[str, Slot], asking: str | None) -> list[dict]:
    both_off = draft.g1.wanted is False and draft.g2.wanted is False
    one_off = not draft.effective(ONE) and not both_off
    items = [
        ("date", "日期", ("target_date",), slots["target_date"].display),
        ("windows", "2小时时段", ("windows_2h", "more_2h", "overlap_2h"), text.show_windows(draft.g2.windows) if draft.effective(TWO) else ""),
        ("courts", "场地", ("courts_2h",), text.show_courts(draft.courts_of(TWO)) if draft.effective(TWO) else ""),
        ("one", "1小时备选", ("want_1h", "windows_1h", "more_1h", "overlap_1h", "courts_1h"),
         "不需要" if one_off and draft.g1.wanted is False else ("" if one_off or both_off else text.show_windows(draft.g1.windows))),
    ]
    result = []
    for ident, name, members, display in items:
        blocked = any(slots[m].blocking for m in members)
        if asking in members:
            state = "current"
        elif display and not blocked:
            state = "done"
        else:
            state = "empty"
        result.append({"id": ident, "label": name, "state": state, "display": display if state != "current" else display or "正在确认"})
    return result


def recap(slots: dict[str, Slot], asking: str | None) -> str:
    """What is already settled, limited to what comes before the question being asked."""
    cutoff = PRIORITY.index(asking) if asking in PRIORITY else len(PRIORITY)
    parts = []
    for name in PRIORITY[:cutoff]:
        slot = slots[name]
        if slot.status not in _DONE or not slot.active or not slot.display or name.startswith(("want", "more", "overlap")):
            continue
        prefix = {"windows_2h": "2小时 ", "courts_2h": "场地 ", "windows_1h": "1小时 ", "courts_1h": "1小时场地 "}.get(name, "")
        parts.append(prefix + slot.display)
    return "已记录：" + "；".join(parts) + "。" if parts else ""


def question(slots: dict[str, Slot], asking: str, draft: Draft, today: date) -> str:
    slot = slots[asking]
    if draft.duration_issue and asking in ("windows_2h", "windows_1h"):
        duration, _ = draft.duration_issue
        minutes = ONE if asking.endswith("_1h") else TWO
        detail = text.issue_detail(minutes, "unsupported_duration",
                                   f"{duration // 60}小时{duration % 60}分钟" if duration % 60 else f"{duration // 60}小时")
        lead = recap(slots, asking)
        return f"{lead}\n{detail}" if lead else detail
    repeated = Counter(draft.asked)[asking] >= 1
    body = text.ask(asking, detail=slot.detail, repeated=repeated, today=today,
                    pairs=slot.value if asking.startswith("overlap") else None)
    lead = recap(slots, asking)
    return f"{lead}\n{body}" if lead else body
