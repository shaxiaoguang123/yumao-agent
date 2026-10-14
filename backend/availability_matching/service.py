from backend.availability_matching.matcher import AvailabilityMatcher
from backend.availability_matching.models import AvailabilityError
from backend.availability_matching.synthetic import SyntheticAvailabilitySource, SCENARIOS
from backend.availability_matching.venue_time_grid import AvailabilityGridProjector
from backend.availability_matching.official_history import OfficialBookingByTimeHistoryAdapter
from backend.plans.service import PlanError
from backend.plans.validation import IntentValidationError, parse_manual_intent

NOTICE = '当前为模拟时段匹配，使用合成数据，并非真实场馆库存，不会自动预约或支付。'


class SimulationAvailabilityService:
    def __init__(self, plans, *, enabled=False, grid_preview_enabled=False, history_preview_enabled=False):
        self.plans, self.enabled = plans, enabled
        self.grid_preview_enabled = grid_preview_enabled
        self.history_preview_enabled = history_preview_enabled
        self.source, self.matcher = SyntheticAvailabilitySource(), AvailabilityMatcher()
        self.grid_projector = AvailabilityGridProjector()
        self.history_adapter = OfficialBookingByTimeHistoryAdapter()

    def options(self):
        return {'enabled': self.enabled, 'grid_preview_enabled': self.grid_preview_enabled,
                'mode': 'simulation', 'notice': NOTICE,
                'scenarios': [dict(item) for item in SCENARIOS] if self.enabled else [],
                'grid_scenarios': [dict(item) for item in SCENARIOS] if self.grid_preview_enabled else [],
                'history_preview_enabled': self.history_preview_enabled}

    def preview_history(self, response):
        if not self.history_preview_enabled:
            raise AvailabilityError('history_preview_not_enabled', 404)
        return self.history_adapter.preview(response)

    def preview_grid(self, payload, now_utc_ms):
        if not self.grid_preview_enabled:
            raise AvailabilityError('grid_preview_not_enabled', 404)
        required = {'target_date', 'duration_minutes', 'venue_preference', 'court_preferences'}
        if (type(payload) is not dict or not required.issubset(payload)
                or payload.keys() - required - {'scenario'}):
            raise AvailabilityError('invalid_request', 400)
        scenario = payload.get('scenario', 'partially_occupied')
        intent = {
            'target_date': payload['target_date'],
            'preferred_start_times': ['18:00'],
            'duration_minutes': payload['duration_minutes'],
            'venue_preference': payload['venue_preference'],
            'court_preferences': payload['court_preferences'],
            'fallback_policy': {
                'allow_any_court_in_venue': False,
                'allow_time_shift': False,
                'allowed_start_time_range': None,
            },
            'price_ceiling_minor': None,
        }
        try:
            normalized = parse_manual_intent(
                intent,
                today_business_date=self.plans.policy.business_date_at_utc(now_utc_ms),
                context=self.plans.active_context,
            ).value['intent']
        except IntentValidationError as exc:
            raise PlanError('invalid_plan', 400, exc.fields) from None
        ephemeral_plan = {'intent': normalized,
                          'context': self.plans.active_context.to_dict()}
        snapshot = self.source.snapshot(ephemeral_plan, scenario)
        if snapshot.simulation is not True:
            raise AvailabilityError('simulation_source_invalid', 503)
        return self.grid_projector.project(snapshot, court_names=normalized['court_preferences'],
                                           duration_minutes=normalized['duration_minutes'], scenario=scenario,
                                           window_start='17:00', window_end='23:00')

    def simulate(self, user_id, plan_id, base_version, scenario, now):
        if not self.enabled:
            raise AvailabilityError('simulation_not_enabled', 404)
        if type(base_version) is not int or base_version < 1:
            raise AvailabilityError('invalid_request', 400)
        plan = self.plans.get_plan(user_id, plan_id, now)
        if plan['version'] != base_version:
            raise PlanError('plan_version_conflict', 409)
        snapshot = self.source.snapshot(plan, scenario)
        if snapshot.simulation is not True:
            raise AvailabilityError('simulation_source_invalid', 503)
        result = self.matcher.match(plan, snapshot, as_of_utc_ms=now)
        # Do not silently present results after a concurrently advanced revision.
        if self.plans.get_plan(user_id, plan_id, now)['version'] != base_version:
            raise PlanError('plan_version_conflict', 409)
        return {'mode': 'simulation', 'simulation': True, 'scenario': scenario, 'notice': NOTICE,
                'plan_id': plan_id, 'base_version': base_version, **result,
                'scope_note': '场馆和已填写的场地名称仅作为合成场景标签，不证明场地归属或真实库存。'}
