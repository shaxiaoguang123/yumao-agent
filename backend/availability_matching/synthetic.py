from backend.availability_matching.models import AvailabilitySlot, AvailabilitySnapshot, AvailabilityError, clock

SCENARIOS = (
    {'id': 'complete', 'name': '完整可用', 'description': '合成场地全天按半小时连续可用。'},
    {'id': 'partially_occupied', 'name': '部分占用', 'description': '第一偏好场地的 18:30～19:00 模拟为占用，其余可用。'},
    {'id': 'time_gap', 'name': '时间断档', 'description': '所有场地缺少 18:30～19:00 的数据；不会推定可用。'},
    {'id': 'no_match', 'name': '全部不可用', 'description': '所有合成时段均不可用。'},
    {'id': 'high_price', 'name': '高价场景', 'description': '每半小时模拟价 9999 CNY；设置价格上限后可演示超预算。'},
    {'id': 'price_unknown', 'name': '价格缺失', 'description': '库存模拟可用但没有价格；有预算时不能认定符合。'},
)


class SyntheticAvailabilitySource:
    """Fixed 30-minute scenario templates instantiated with unverified manual labels.

    Copying the plan's labels is deliberate simulation, not a real venue/court lookup
    or confirmation of membership. No catalog entry or upstream identifier is created.
    """
    def snapshot(self, plan, scenario):
        if type(scenario) is not str or scenario not in {item['id'] for item in SCENARIOS}:
            raise AvailabilityError('invalid_simulation_scenario', 400)
        intent = plan['intent']
        courts = list(intent['court_preferences']) or ['模拟场地A']
        extra = '模拟备用场地A'
        while extra in courts:
            extra += 'A'
        courts.append(extra)
        slots = []
        for i, court in enumerate(courts):
            for start in range(0, 1440, 30):
                if scenario == 'time_gap' and start == 1110:
                    continue
                status = 'unavailable' if scenario == 'no_match' or (scenario == 'partially_occupied' and i == 0 and start == 1110) else 'available'
                price = None if scenario == 'price_unknown' else (999900 if scenario == 'high_price' else 1500 + i * 300)
                slots.append(AvailabilitySlot(court, clock(start), clock(start + 30), status, price))
        return AvailabilitySnapshot(intent['target_date'], plan['context']['timezone_name'], intent['venue_preference'],
                                    tuple(slots), 'synthetic-v1:' + scenario, True, 'CNY', 2)
