"""Fixed Chinese wording for the queue conversation. Durations are 1小时 / 2小时, never minutes."""
from __future__ import annotations

from datetime import date, timedelta

from backend.ai.nlu.dates import WEEKDAY_NAMES
from backend.ai.nlu.windows import ISSUE_TEXT, clock, label

HOURS = {120: "2小时", 60: "1小时"}
SLOT_LABEL = {"target_date": "日期", "windows_2h": "2小时时段", "courts_2h": "2小时场地", "want_1h": "1小时备选"}
EXECUTION_NOTE = "执行时从上往下依次尝试，抢到第一个就停，所以顺序就是优先级。"


def show_date(day: date) -> str:
    return f"{day.month}月{day.day}日 {WEEKDAY_NAMES[day.weekday()]}"


def show_windows(windows: list[tuple[int, int]]) -> str:
    return "、".join(label(a, b) for a, b in windows)


def show_courts(courts: list[int]) -> str:
    return "、".join(f"{n}号" for n in courts)


def latest_start(minutes: int) -> str:
    return clock(22 * 60 - minutes)


def issue_detail(minutes: int, issue: str, text: str) -> str:
    hours = HOURS[minutes]
    if issue == "bad_length":
        return f"“{text}”不是 1 小时或 2 小时的时段。这一步按{hours}整理，请写成像 14-{14 + minutes // 60} 这样。"
    if issue == "outside_hours":
        return f"“{text}”不在可预约时间内（09:00–22:00）。{hours}最晚 {latest_start(minutes)} 开始。"
    if issue == "unaligned":
        return f"“{text}”不是整点开始。目前只能按整点预约，例如 14-{14 + minutes // 60}。"
    if issue == "bad_order":
        return f"“{text}”的结束时间要晚于开始时间，例如 14-{14 + minutes // 60}。"
    if issue == "unsupported_duration":
        return (f"你提到“{text}”，但每个候选时段只支持1小时或2小时。这里的{text}是当天累计时长还是单个时段？"
                "候选抢到一项就停止，不会把多项累计预约。请说明具体预约方式，再按每个候选时段写清楚时间。")
    return f"“{text}”分不清是上午还是晚上，请写成 24 小时制，例如 18-{18 + minutes // 60}。"


def ask(slot_id: str, *, detail: str | None, repeated: bool, today: date, pairs=None) -> str:
    example_day = today + timedelta(days=2)
    day_text = f"{example_day.month}月{example_day.day}日"
    if slot_id == "target_date":
        if detail == "past":
            return f"这个日期已经过了（今天是 {show_date(today)}）。请选一个今天之后的日期，例如“{day_text}”。"
        if detail == "ambiguous":
            return f"这个日期有不止一种理解。请说完整，例如“{day_text}”或“下周六”。"
        return ("还没确认是哪一天。请直接说日期或星期，例如“" + day_text + "”或“下周六”。" if repeated
                else f"想订哪一天？说日期或星期都行，例如“{day_text}”或“下周六”。")
    if slot_id in ("windows_2h", "windows_1h"):
        minutes = 120 if slot_id.endswith("2h") else 60
        end = 16 if minutes == 120 else 15
        if detail:
            return f"{detail}\n请重新给{HOURS[minutes]}的时间，例如“14-{end}”。"
        if minutes == 120:
            return (f"{HOURS[minutes]}要哪个时间段？写开始到结束就行，例如“14-16”，可以写多个：“14-16、18-20”。"
                    if not repeated else f"还没读到{HOURS[minutes]}的时间段。请写成“14-16”这样，也可以写多个。")
        return (f"1小时备选要哪个时间段？例如“14-15”，可以写多个：“14-15、18-19”。"
                if not repeated else "还没读到1小时的时间段。请写成“14-15”这样，也可以写多个。")
    if slot_id in ("more_2h", "more_1h"):
        minutes = 120 if slot_id.endswith("2h") else 60
        extra = "15-17" if minutes == 120 else "15-16"
        return (f"{HOURS[minutes]}还要再加候选时间吗？前面的时间抢不到时，会按顺序试这些。要就直接写，例如“{extra}”；不要就回“不用”。")
    if slot_id in ("overlap_2h", "overlap_1h"):
        shown = "；".join(f"{label(*a)} 与 {label(*b)}" for a, b in (pairs or []))
        return (f"这些时间段有重叠：{shown}。重叠的只是备选，会按顺序试，不会冲突。"
                "要删掉哪个就直接说，例如“去掉15-17”；都留着就回“都保留”。")
    if slot_id in ("courts_2h", "courts_1h"):
        minutes = 120 if slot_id.endswith("2h") else 60
        if detail:
            return f"{detail}\n请重新说场地，例如“1号和4号”。"
        who = ("每个时间段都用同一组场地。" if minutes == 120
               else "和2小时队列分开选择；每个1小时时段都用同一组场地。")
        return f"{HOURS[minutes]}要订哪几号场？{who}例如“1号和4号”（1～10号）。"
    if slot_id == "want_1h":
        if detail == "both_disabled":
            return "你说1小时和2小时都不需要，所以目前没有可保存的候选。若还想预约，请明确选择一种，例如“只要2小时”；如果都不需要，可以取消本次整理。"
        return "还要加1小时的备选吗？2小时抢不到时才会试它。要就回“要”，不要就回“不用”。"
    return "请再补充一下。"
