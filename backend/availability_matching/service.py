from backend.availability_matching.matcher import AvailabilityMatcher
from backend.availability_matching.models import AvailabilityError
from backend.availability_matching.synthetic import SyntheticAvailabilitySource, SCENARIOS
from backend.plans.service import PlanError

NOTICE = '当前为模拟时段匹配，使用合成数据，并非真实场馆库存，不会自动预约或支付。'


class SimulationAvailabilityService:
    def __init__(self, plans, *, enabled=False):
        self.plans, self.enabled = plans, enabled
        self.source, self.matcher = SyntheticAvailabilitySource(), AvailabilityMatcher()

    def options(self):
        return {'enabled': self.enabled, 'mode': 'simulation', 'notice': NOTICE,
                'scenarios': [dict(item) for item in SCENARIOS] if self.enabled else []}

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
        result = self.matcher.match(plan, snapshot)
        # Do not silently present results after a concurrently advanced revision.
        if self.plans.get_plan(user_id, plan_id, now)['version'] != base_version:
            raise PlanError('plan_version_conflict', 409)
        return {'mode': 'simulation', 'simulation': True, 'scenario': scenario, 'notice': NOTICE,
                'plan_id': plan_id, 'base_version': base_version, **result,
                'scope_note': '场馆和已填写的场地名称仅作为合成场景标签，不证明场地归属或真实库存。'}
