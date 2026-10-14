"""Semantic manual candidates. These queues never invoke the legacy execution flow."""
from datetime import date
from backend.plans.models import PlanInterpretationContext
from backend.plans.validation import IntentValidationError, parse_manual_intent, parse_target_date

QUEUE_KIND = 'manual_queue_draft'
PRIORITY = (120, 60)


def parse_queue(payload, context: PlanInterpretationContext, today: date, *, allow_past=False):
    def fail(message):
        raise IntentValidationError('queue', message)
    if type(payload) is not dict or payload.keys() != {'target_date', 'entries'}:
        fail('请提交日期与语义候选队列；不接受坐标、凭据或执行参数。')
    target = parse_target_date(payload['target_date'])
    if target < today and not allow_past:
        fail('目标日期不能早于当前业务日期。')
    entries = payload['entries']
    if type(entries) is not list or len(entries) > 32:
        fail('候选队列最多 32 项。')
    candidates, seen = [], set()
    for entry in entries:
        if type(entry) is not dict or entry.keys() != {'court_preference', 'start_time', 'end_time', 'duration_minutes'}:
            fail('候选只接受场地名称、起止时间和时长。')
        duration = entry['duration_minutes']
        if type(duration) is not int or duration not in PRIORITY:
            fail('请选择一小时或两个连续小时。')
        intent = parse_manual_intent({
            'target_date': target.isoformat(), 'preferred_start_times': [entry['start_time']],
            'duration_minutes': duration, 'venue_preference': '羽毛球（场馆未绑定）',
            'court_preferences': [entry['court_preference']],
            'fallback_policy': {'allow_any_court_in_venue': False, 'allow_time_shift': False, 'allowed_start_time_range': None},
            'price_ceiling_minor': None,
        }, today_business_date=min(today, target) if allow_past else today, context=context).value['intent']
        start = intent['preferred_start_times'][0]
        if not start.endswith(':00'):
            fail('当前小时队列须从整点开始。')
        end_minutes = int(start[:2]) * 60 + duration
        expected_end = f'{end_minutes // 60:02d}:00'
        if entry['end_time'] != expected_end:
            fail('起止时间必须完整覆盖同一场地的连续一小时或两小时，不能跨日。')
        key = (duration, start, intent['court_preferences'][0])
        if key in seen:
            fail('同一队列不能重复加入相同场地与时间。')
        seen.add(key)
        candidates.append(intent)
    # Stable group priority; preserve user insertion/reorder order within each group.
    candidates.sort(key=lambda item: PRIORITY.index(item['duration_minutes']))
    return {'kind': QUEUE_KIND, 'queue_contract_version': 1, 'target_date': target.isoformat(),
            'context': context.to_dict(), 'duration_priority': list(PRIORITY), 'candidates': candidates}
