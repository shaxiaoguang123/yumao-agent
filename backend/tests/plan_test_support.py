from datetime import datetime, timezone

from backend.ai import queue_cues as cues
from backend.ai.nlu.courts import scan_bare_courts, scan_courts
from backend.ai.nlu.windows import scan_windows, clock
from backend.ai.queue_draft import ONE, TWO, fold

NOW = int(datetime(2026,10,10,2,tzinfo=timezone.utc).timestamp()*1000)


def draft(**changes):
    value = {
        'target_date':'2026-10-20', 'preferred_start_times':['18:00','19:00'],
        'duration_minutes':120, 'venue_preference':'人工意向场馆',
        'court_preferences':['6号场','5号场'],
        'fallback_policy':{'allow_any_court_in_venue':False,'allow_time_shift':False,'allowed_start_time_range':None},
        'price_ceiling_minor':None,
    }
    value.update(changes)
    return value


def synthetic_queue_turn(payload):
    """Small deterministic model double for parser and browser integration tests."""
    latest = payload["latest_user_message"]
    field = payload["current_step"]["field"]
    today = datetime.fromisoformat(payload["current_business_date"]).date()
    if any(phrase in latest for phrase in ("帮我直接预约并付款", "然后立即下单", "现在就预约并支付")):
        return {"intent": "execution_request", "kind": "answer", "updates": [], "unresolved": [],
                "reply": "我只能整理候选队列，不能在这里直接预约或付款。",
                "next_field": None, "next_question": ""}
    question_turn = any(mark in latest for mark in ("?", "？", "为什么", "有什么区别", "能不能", "可以吗"))
    eligible = payload.get("eligible_fields") or []
    if question_turn:
        if any(phrase in latest for phrase in ("已经记录", "确认了什么", "还差什么")):
            facts = [slot.get("display") for slot in payload.get("current_slots", [])
                     if isinstance(slot, dict) and slot.get("field") != "booking_mode"
                     and slot.get("active") and slot.get("status") in {"proposed", "verified"}
                     and isinstance(slot.get("display"), str) and slot["display"]]
            recorded = "；".join(facts) if facts else "目前没有已通过规则校验的预约信息"
            label = payload.get("current_step", {}).get("label") or "预约信息"
            reply = f"已记录：{recorded}。当前还需确认：{label}。"
        else:
            reply = "两组的时间和场地分别确认，互不继承。"
        return {"kind": "question", "updates": [], "unresolved": [],
                "reply": reply,
                "next_field": eligible[0] if eligible else None,
                "next_question": "这次想排哪种队列？例如3。" if eligible else ""}

    draft = fold(["", latest], [field], today)
    updates, unresolved = [], []
    if draft.booking_mode:
        updates.append({"field": "booking_mode", "operation": "set", "value": draft.booking_mode,
                        "evidence": latest})
    if draft.date_state == "resolved":
        updates.append({"field": "target_date", "operation": "set", "value": draft.dates[0].isoformat(),
                        "evidence": latest})
    elif draft.date_state == "ambiguous":
        unresolved.append({"field": "target_date", "evidence": latest})

    for minutes, tag in ((TWO, "2h"), (ONE, "1h")):
        group = draft.groups[minutes]
        windows = scan_windows(latest).mentions
        window_modes = [cues.mode_before(latest, item.pos, cues.sentence_start(latest, item.pos))
                        for item in windows]
        operation = "remove" if "remove" in window_modes else "append" if "append" in window_modes else "replace"
        if group.issue and not draft.duration_issue:
            unresolved.append({"field": f"windows_{tag}", "evidence": latest, "issue": group.issue})
        elif group.windows:
            updates.append({"field": f"windows_{tag}", "operation": operation,
                            "value":[{"start":clock(start),"end":clock(end)} for start,end in group.windows],
                            "evidence":latest})
        elif operation == "remove" and field == f"windows_{tag}":
            ranges = [{"start":clock(item.start),"end":clock(item.end)} for item in scan_windows(latest).mentions
                      if item.kind == "range" and item.start is not None and item.end is not None]
            if ranges:
                updates.append({"field":f"windows_{tag}","operation":"remove","value":ranges,"evidence":latest})
        court_mentions = scan_courts(latest) or scan_bare_courts(latest)
        numbers = list(dict.fromkeys(number for mention in court_mentions for number in mention.numbers))
        court_modes = [cues.mode_before(latest, mention.pos, cues.sentence_start(latest, mention.pos))
                       for mention in court_mentions]
        court_operation = "remove" if any(mention.negated for mention in court_mentions) or "remove" in court_modes else (
            "add" if "append" in court_modes else "replace")
        if court_operation == "remove" and group.courts:
            court_operation = "replace"
        if group.court_scope_ambiguous:
            unresolved.append({"field": f"courts_{tag}", "evidence": latest,
                               "issue": "scoped_preferences"})
        elif group.courts or group.bad_courts:
            updates.append({"field":f"courts_{tag}","operation":court_operation,
                            "value":list(group.courts) + list(group.bad_courts),"evidence":latest})
        elif numbers and field == f"courts_{tag}":
            updates.append({"field":f"courts_{tag}","operation":court_operation,"value":numbers,"evidence":latest})
        if field == f"overlap_{tag}" and cues.contains_any(latest, cues.KEEP_STRONG):
            updates.append({"field":f"overlap_{tag}","operation":"confirm","value":"keep","evidence":latest})
    if draft.duration_issue:
        duration, minutes = draft.duration_issue
        unresolved.append({"field":f"windows_{'1h' if minutes == ONE else '2h'}","evidence":latest,
                           "issue":"unsupported_duration","duration_minutes":duration})
    reply = ("明白，一小时就按刚才列出的时段处理。" if "没有其他时间段" in latest and ("一小时" in latest or "一个小时" in latest)
             else "明白，按已经列出的时段继续。" if "没有其他时间段" in latest else "")
    return {"kind":"answer","updates":updates,"unresolved":unresolved,"reply":reply,
            "next_field":None,"next_question":""}
