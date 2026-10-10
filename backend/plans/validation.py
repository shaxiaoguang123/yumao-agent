from __future__ import annotations

import re
import unicodedata
from datetime import date

from backend.plans.models import PlanInterpretationContext, PlanSnapshot

_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z", re.ASCII)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z", re.ASCII)
_FIELDS = {"target_date", "preferred_start_times", "duration_minutes", "venue_preference", "court_preferences", "fallback_policy", "price_ceiling_minor"}


class IntentValidationError(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__("invalid_plan")
        self.fields = {field: message}


def _invalid(field: str, message: str):
    raise IntentValidationError(field, message)


def parse_target_date(value: object) -> date:
    if type(value) is not str or not _DATE.fullmatch(value):
        _invalid("target_date", "请选择有效日期（YYYY-MM-DD）。")
    try:
        return date.fromisoformat(value)
    except ValueError:
        _invalid("target_date", "请选择真实存在的日期。")


def _text(value: object, field: str, maximum: int) -> str:
    if type(value) is not str:
        _invalid(field, "请填写文本偏好。")
    value = value.strip()
    if not 1 <= len(value) <= maximum or any(unicodedata.category(c) in {"Cc", "Cs"} for c in value):
        _invalid(field, f"请输入 1～{maximum} 个字符，不含控制字符。")
    return value


def _time(value: object, field: str) -> str:
    if type(value) is not str or not _TIME.fullmatch(value):
        _invalid(field, "时间须使用 24 小时 HH:MM 格式。")
    return value


def _minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def parse_manual_intent(payload: object, *, today_business_date: date, context: PlanInterpretationContext) -> PlanSnapshot:
    if type(payload) is not dict or payload.keys() != _FIELDS:
        _invalid("intent", "请提交完整的人工意向字段；不接受上游标识或执行参数。")
    target = parse_target_date(payload["target_date"])
    if target < today_business_date:
        _invalid("target_date", "目标日期不能早于当前业务日期。")
    times = payload["preferred_start_times"]
    if type(times) is not list or not 1 <= len(times) <= 8:
        _invalid("preferred_start_times", "请按优先顺序设置 1～8 个开始时间。")
    times = [_time(item, "preferred_start_times") for item in times]
    if len(set(times)) != len(times):
        _invalid("preferred_start_times", "开始时间不能重复。")
    duration = payload["duration_minutes"]
    if type(duration) is not int or not 30 <= duration <= 240 or duration % 30:
        _invalid("duration_minutes", "时长须为 30～240 分钟，以 30 分钟递增。")
    if any(_minutes(item) + duration > 1440 for item in times):
        _invalid("preferred_start_times", "开始时间与时长不能跨越当天午夜。")
    venue = _text(payload["venue_preference"], "venue_preference", 200)
    courts = payload["court_preferences"]
    if type(courts) is not list or len(courts) > 16:
        _invalid("court_preferences", "场地偏好最多 16 项，按输入顺序排列。")
    courts = [_text(item, "court_preferences", 100) for item in courts]
    if len(set(courts)) != len(courts):
        _invalid("court_preferences", "场地偏好不能重复。")
    fallback = payload["fallback_policy"]
    if type(fallback) is not dict or fallback.keys() != {"allow_any_court_in_venue", "allow_time_shift", "allowed_start_time_range"}:
        _invalid("fallback_policy", "请提交明确的备用策略。")
    for key in ("allow_any_court_in_venue", "allow_time_shift"):
        if type(fallback[key]) is not bool:
            _invalid("fallback_policy", "备用策略开关须为布尔值。")
    if not courts and not fallback["allow_any_court_in_venue"]:
        _invalid("court_preferences", "请填写场地偏好，或允许同场馆备选。")
    time_range = fallback["allowed_start_time_range"]
    if not fallback["allow_time_shift"]:
        if time_range is not None:
            _invalid("fallback_policy", "未允许时间浮动时，浮动范围须为空。")
    else:
        if type(time_range) is not dict or time_range.keys() != {"start", "end"}:
            _invalid("fallback_policy", "请设置完整的时间浮动范围。")
        start, end = (_time(time_range[key], "fallback_policy") for key in ("start", "end"))
        if start > end or any(not start <= item <= end for item in times) or _minutes(end) + duration > 1440:
            _invalid("fallback_policy", "浮动范围须包含全部首选时间，且加上时长不跨日。")
        time_range = {"start": start, "end": end}
    ceiling = payload["price_ceiling_minor"]
    if ceiling is not None:
        if type(ceiling) is not int or not 0 <= ceiling <= 9007199254740991:
            _invalid("price_ceiling_minor", "价格上限须为有效的最小货币单位整数。")
        if context.currency_code is None or context.currency_minor_unit_exponent is None:
            _invalid("price_ceiling_minor", "部署尚未配置货币，当前不能设置价格上限。")
    intent = {
        "target_date": target.isoformat(), "preferred_start_times": times, "duration_minutes": duration,
        "venue_preference": venue, "court_preferences": courts,
        "fallback_policy": {"allow_any_court_in_venue": fallback["allow_any_court_in_venue"], "allow_time_shift": fallback["allow_time_shift"], "allowed_start_time_range": time_range},
        "price_ceiling_minor": ceiling,
    }
    return PlanSnapshot.build(intent, context)
