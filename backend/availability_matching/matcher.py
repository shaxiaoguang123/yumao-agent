from __future__ import annotations

from collections import Counter
from datetime import date

from backend.availability_matching.models import AvailabilitySnapshot, AvailabilityError, MAX_MINOR, clock, minutes
from backend.plans.models import PlanInterpretationContext
from backend.plans.validation import parse_manual_intent, IntentValidationError

REASONS = {
    'date_mismatch': '数据日期与计划目标日期不一致。',
    'timezone_mismatch': '数据业务时区与计划时区不一致，不能直接匹配。',
    'venue_mismatch': '数据场馆范围与人工偏好不一致。',
    'court_not_authorized': '该场地不在填写的偏好中，且未允许同场馆其他场地。',
    'time_not_authorized': '该开始时间不是首选，且不在明确授权的浮动范围内。',
    'unavailable': '组合包含明确不可用的时段。',
    'availability_unknown': '组合包含可用状态尚未确认的时段。',
    'time_discontinuous': '时段断档或缺少完整的开始/结束边界，无法覆盖预约时长。',
    'over_budget': '完整组合的模拟总价超过意向价格上限。',
    'price_unconfirmed': '缺少完整价格或货币信息，不能确认符合预算。',
    'currency_mismatch': '数据和计划的货币或最小单位指数不一致，不能比较预算。',
    'no_slots': '该日期没有可用时段数据。',
}
SORT_ORDER = ['preferred_start_priority', 'court_preference_priority', 'shift_distance_minutes',
              'nearest_preference_priority', 'start_time', 'court_name']


class AvailabilityMatcher:
    """Pure matching; exact starts precede all authorized shifts. Price is a filter, not a sort key."""
    def match(self, plan: dict, snapshot: AvailabilitySnapshot) -> dict:
        if type(snapshot) is not AvailabilitySnapshot:
            raise AvailabilityError('invalid_availability_snapshot')
        try:
            context = PlanInterpretationContext(plan['context']['timezone_name'], plan['context']['currency_code'],
                                                plan['context']['currency_minor_unit_exponent'])
            # Match historical saved drafts without imposing today's calendar eligibility.
            intent = parse_manual_intent(plan['intent'], today_business_date=date.min, context=context).value['intent']
        except (KeyError, TypeError, ValueError, IntentValidationError):
            raise AvailabilityError('invalid_matching_plan') from None
        provenance = snapshot.provenance()
        result = {'candidates': [], 'rejections': [], 'reason_summary': [], 'source': provenance,
                  'sort_order': SORT_ORDER.copy(), 'total_candidates': 0, 'candidates_truncated': False,
                  'rejections_truncated': False, 'can_book': False, 'can_pay': False, 'can_create_job': False,
                  'can_query_upstream': False}
        counts = Counter()

        def reject(code, court=None, start=None):
            counts[code] += 1
            if len(result['rejections']) < 128:
                result['rejections'].append({'code': code, 'message': REASONS[code], 'court_name': court, 'start_time': start})
            else:
                result['rejections_truncated'] = True

        def finish():
            result['reason_summary'] = [{'code': code, 'message': REASONS[code], 'count': counts[code]}
                                        for code in REASONS if counts[code]]
            return result

        for key, expected, code in (('target_date', intent['target_date'], 'date_mismatch'),
                                     ('timezone_name', context.timezone_name, 'timezone_mismatch'),
                                     ('venue_name', intent['venue_preference'], 'venue_mismatch')):
            if getattr(snapshot, key) != expected:
                reject(code)
        if counts:
            return finish()
        if not snapshot.slots:
            reject('no_slots')
            return finish()
        by_court = {}
        for slot in snapshot.slots:
            by_court.setdefault(slot.court_name, {})[minutes(slot.start_time)] = slot
        prefs = [minutes(t) for t in intent['preferred_start_times']]
        court_prefs = intent['court_preferences']
        fallback = intent['fallback_policy']
        authorized_range = fallback['allowed_start_time_range']
        candidates = []
        # Include requested courts absent from the data so their failure is explainable.
        for court in sorted(set(by_court) | set(court_prefs)):
            if court not in court_prefs and not fallback['allow_any_court_in_venue']:
                reject('court_not_authorized', court)
                continue
            slots = by_court.get(court, {})
            starts = set(prefs)
            for start in sorted(slots):
                if start in prefs:
                    continue
                if (fallback['allow_time_shift'] and minutes(authorized_range['start']) <= start <= minutes(authorized_range['end'])):
                    starts.add(start)
                else:
                    reject('time_not_authorized', court, clock(start))
            for start in sorted(starts):
                end = start + intent['duration_minutes']
                cursor, atoms, failure = start, [], None
                while cursor < end:
                    slot = slots.get(cursor)
                    if slot is None or minutes(slot.end_time, end=True) > end:
                        failure = 'time_discontinuous'
                        break
                    atoms.append(slot)
                    cursor = minutes(slot.end_time, end=True)
                if failure is None:
                    if any(slot.status == 'unavailable' for slot in atoms):
                        failure = 'unavailable'
                    elif any(slot.status == 'unknown' for slot in atoms):
                        failure = 'availability_unknown'
                # For incomplete coverage report the gap first; never infer unknown inventory.
                if failure:
                    reject(failure, court, clock(start))
                    continue
                price, price_status = self._price(atoms, snapshot)
                ceiling = intent['price_ceiling_minor']
                if ceiling is not None:
                    if price is None:
                        reject('price_unconfirmed', court, clock(start))
                        continue
                    if (snapshot.currency_code, snapshot.currency_minor_unit_exponent) != (context.currency_code, context.currency_minor_unit_exponent):
                        reject('currency_mismatch', court, clock(start))
                        continue
                    if price > ceiling:
                        reject('over_budget', court, clock(start))
                        continue
                exact = start in prefs
                time_priority = prefs.index(start) if exact else len(prefs)
                court_priority = court_prefs.index(court) if court in court_prefs else len(court_prefs)
                nearest = min(range(len(prefs)), key=lambda i: (abs(start - prefs[i]), i))
                distance = 0 if exact else abs(start - prefs[nearest])
                reasons = [f'由 {len(atoms)} 个连续且明确可用的时段完整覆盖 {intent["duration_minutes"]} 分钟。',
                           f'开始时间偏好第 {time_priority + 1} 顺位。' if exact else f'在授权浮动范围内，距首选 {distance} 分钟。',
                           f'场地偏好第 {court_priority + 1} 顺位。' if court in court_prefs else '使用已授权的同场馆其他场地。']
                backup = {'lower_priority_time': exact and time_priority > 0,
                          'lower_priority_court': court in court_prefs and court_priority > 0,
                          'other_court': court not in court_prefs, 'time_shift': not exact}
                candidates.append(((time_priority, court_priority, distance, nearest, start, court), {
                    'court_name': court, 'start_time': clock(start), 'end_time': clock(end),
                    'duration_minutes': intent['duration_minutes'], 'slot_count': len(atoms),
                    'price': None if price is None else {'total_minor': price, 'currency_code': snapshot.currency_code,
                                                       'minor_unit_exponent': snapshot.currency_minor_unit_exponent},
                    'price_status': price_status, 'budget_status': 'within_limit' if ceiling is not None else 'no_limit',
                    'uses_fallback': any(backup.values()), 'fallback': backup, 'match_reasons': reasons,
                    'source': provenance.copy(), 'can_book': False, 'can_pay': False, 'can_create_job': False,
                }))
        candidates.sort(key=lambda row: row[0])
        result['total_candidates'] = len(candidates)
        result['candidates_truncated'] = len(candidates) > 256
        result['candidates'] = [{**candidate, 'rank': i + 1} for i, (_key, candidate) in enumerate(candidates[:256])]
        return finish()

    @staticmethod
    def _price(atoms, snapshot):
        if snapshot.currency_code is None or any(slot.price_minor is None for slot in atoms):
            return None, 'unconfirmed'
        total = sum(slot.price_minor for slot in atoms)
        return (total, 'confirmed') if total <= MAX_MINOR else (None, 'unconfirmed')
