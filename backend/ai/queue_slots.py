"""Slots, queue entries, progress strip and questions derived from validated facts."""
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
    group = draft.groups[minutes]
    if not draft.effective(minutes):
        return {f"{name}_{tag}": _off(f"{name}_{tag}") for name in ("windows", "overlap", "courts")}
    windows, courts = f"windows_{tag}", f"courts_{tag}"
    if group.issue:
        detail = ("这个时段还不明确。请说清开始和结束时间，例如14-16。"
                  if group.issue == "ambiguous" else text.issue_detail(minutes, group.issue, group.issue_text))
        status = SlotStatus.AMBIGUOUS if group.issue == "ambiguous" else SlotStatus.INVALID
        windows_slot = _slot(windows, status, group.windows, detail=detail)
    elif group.invalid_windows:
        start, end, issue, label = group.invalid_windows[0]
        detail = text.issue_detail(minutes, issue, label)
        if len(group.invalid_windows) > 1:
            detail += f" 另外还有{len(group.invalid_windows) - 1}个无效时段需要修正或移除。"
        windows_slot = _slot(windows, SlotStatus.INVALID, list(group.windows),
                             text.show_windows(group.windows), detail)
    elif group.windows:
        windows_slot = _slot(windows, SlotStatus.PROPOSED, list(group.windows), text.show_windows(group.windows))
    else:
        windows_slot = _slot(windows, SlotStatus.EMPTY, reason=Reason.MISSING)
    settled = windows_slot.status in _DONE
    pairs = [p for p in overlapping_pairs(group.windows) if frozenset(p) not in group.acked]
    if pairs:
        overlap = _slot(f"overlap_{tag}", SlotStatus.AMBIGUOUS, pairs, active=settled)
    else:
        overlap = _slot(f"overlap_{tag}", SlotStatus.VERIFIED, active=settled and len(group.windows) > 1)
    group_courts = draft.courts_of(minutes)
    if group.bad_courts:
        bad = "、".join(f"{n}号场" for n in group.bad_courts)
        courts_slot = _slot(courts, SlotStatus.INVALID, detail=f"{bad}不在可选范围，这里只支持1～10号场。",
                            active=settled and not pairs)
    elif group.courts_issue:
        courts_slot = _slot(courts, SlotStatus.AMBIGUOUS, detail=group.courts_issue, active=settled and not pairs)
    elif group.court_scope_ambiguous:
        courts_slot = _slot(courts, SlotStatus.AMBIGUOUS, detail="你为不同时段指定了不同场地。目前每个时段共用同一组场地，不能直接交叉组合。请给出同意用于全部时段的场地列表；如果需要分别指定，请改用“选择预约”手动选场。",
                            active=settled and not pairs)
    elif group_courts:
        courts_slot = _slot(courts, SlotStatus.PROPOSED, list(group_courts), text.show_courts(group_courts),
                            active=settled and not pairs)
    else:
        courts_slot = _slot(courts, SlotStatus.EMPTY, reason=Reason.MISSING, active=settled and not pairs)
    return {windows: windows_slot, f"overlap_{tag}": overlap, courts: courts_slot}


def _mode_slot(draft: Draft) -> Slot:
    labels = {"two_hour_only": "只抢2小时", "one_hour_only": "只抢1小时", "both": "1小时和2小时都抢（独立队列）"}
    if draft.mode_issue:
        return _slot("booking_mode", SlotStatus.AMBIGUOUS, detail=draft.mode_issue)
    if draft.booking_mode is None:
        return _slot("booking_mode", SlotStatus.EMPTY, reason=Reason.MISSING)
    return _slot("booking_mode", SlotStatus.PROPOSED, draft.booking_mode, labels[draft.booking_mode])


def build_slots(draft: Draft, today: date, unresolved: dict | None = None) -> dict[str, Slot]:
    slots = {"booking_mode": _mode_slot(draft), "target_date": _date_slot(draft, today)}
    slots.update(_group_slots(draft, TWO, "2h"))
    slots.update(_group_slots(draft, ONE, "1h"))
    if draft.duration_issue and draft.effective(draft.duration_issue[1]):
        duration, minutes = draft.duration_issue
        tag = dict(_GROUPS)[minutes]
        field = f"windows_{tag}"
        text_duration = f"{duration // 60}小时{duration % 60}分钟" if duration % 60 else f"{duration // 60}小时"
        slots[field] = _slot(field, SlotStatus.AMBIGUOUS, detail=text.issue_detail(minutes, "unsupported_duration", text_duration))
    counts = entry_count(draft)
    total = sum(counts.values())
    if total > MAX_ENTRIES:
        minutes = max(counts, key=counts.get)
        field = f"courts_{dict(_GROUPS)[minutes]}"
        breakdown = "、".join(f"{text.HOURS[m]} {count}项" for m, count in counts.items())
        window_total = sum(len(draft.groups[m].windows) for m in counts)
        if window_total <= MAX_ENTRIES:
            court_limit = MAX_ENTRIES // window_total
            if len(counts) == 1:
                suggestion = f"例如只留1～{court_limit}号场，可降到上限内。"
            else:
                suggestion = f"例如两组都只留1～{court_limit}号场，可降到上限内。"
        else:
            suggestion = "请先减少候选时段。"
        detail = f"当前候选：{breakdown}，共{total}项，最多 {MAX_ENTRIES} 项。{suggestion}"
        slots[field] = _slot(field, SlotStatus.INVALID, slots[field].value, slots[field].display, detail)
    for field, issue in (unresolved or {}).items():
        slot = slots[field]
        active = slot.active or field.startswith("overlap_") and draft.effective(ONE if field.endswith("_1h") else TWO)
        if active and slot.status in _DONE:
            slots[field] = _slot(field, SlotStatus.AMBIGUOUS, slot.value, slot.display,
                                 f"还不能确认“{issue['evidence']}”的具体处理方式。", active=True)
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
    items = [("mode", "队列类型", ("booking_mode",), slots["booking_mode"].display),
             ("date", "日期", ("target_date",), slots["target_date"].display)]
    for minutes, tag, label in ((TWO, "2h", "2小时"), (ONE, "1h", "1小时")):
        members = (f"windows_{tag}", f"overlap_{tag}", f"courts_{tag}")
        if not draft.effective(minutes):
            items.append((tag, label, members, "本次不选"))
            continue
        display = " · ".join(value for value in (slots[members[0]].display, slots[members[2]].display) if value)
        items.append((tag, label, members, display))
    result = []
    for ident, name, members, display in items:
        blocked = any(slots[m].blocking for m in members)
        if asking in members:
            state = "current"
        elif display and display != "本次不选" and not blocked:
            state = "done"
        elif display == "本次不选":
            state = "off"
        else:
            state = "empty"
        result.append({"id": ident, "label": name, "state": state,
                       "display": display if state not in ("current", "empty") else display or "正在确认"})
    return result


def recap(slots: dict[str, Slot], asking: str | None) -> str:
    """What is already settled, limited to what comes before the question being asked."""
    cutoff = PRIORITY.index(asking) if asking in PRIORITY else len(PRIORITY)
    parts = []
    for name in PRIORITY[:cutoff]:
        slot = slots[name]
        if slot.status not in _DONE or not slot.active or not slot.display or name == "booking_mode" or name.startswith("overlap"):
            continue
        prefix = {"windows_2h": "2小时 ", "courts_2h": "2小时场地 ",
                  "windows_1h": "1小时 ", "courts_1h": "1小时场地 "}.get(name, "")
        parts.append(prefix + slot.display)
    return "已记录：" + "；".join(parts) + "。" if parts else ""


def question(slots: dict[str, Slot], asking: str, draft: Draft, today: date) -> str:
    slot = slots[asking]
    if asking == "booking_mode":
        return ("先选本次要排哪种队列：\n"
                "1 / A：只抢2小时\n"
                "2 / B：只抢1小时\n"
                "3 / C：1小时和2小时都抢，两组的时间与场地分别确认。")
    if draft.duration_issue and asking == ("windows_1h" if draft.duration_issue[1] == ONE else "windows_2h"):
        duration, _ = draft.duration_issue
        minutes = ONE if asking.endswith("_1h") else TWO
        detail = text.issue_detail(minutes, "unsupported_duration",
                                   f"{duration // 60}小时{duration % 60}分钟" if duration % 60 else f"{duration // 60}小时")
        lead = recap(slots, asking)
        return f"{lead}\n{detail}" if lead else detail
    if asking.startswith("overlap_") and slot.detail and not slot.value:
        return f"{slot.detail}希望保留或删除哪些时段？例如保留14-16。"
    repeated = Counter(draft.asked)[asking] >= 1
    body = text.ask(asking, detail=slot.detail, repeated=repeated, today=today,
                    pairs=slot.value if asking.startswith("overlap") else None)
    lead = recap(slots, asking)
    return f"{lead}\n{body}" if lead else body
