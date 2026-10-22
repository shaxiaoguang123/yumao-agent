"""Single source for queue-agent fields, dependencies, and product facts."""
from __future__ import annotations

FIELD_ORDER = (
    "booking_mode", "target_date",
    "windows_2h", "overlap_2h", "courts_2h",
    "windows_1h", "overlap_1h", "courts_1h",
)
FIELD_LABELS = {
    "booking_mode": "选择队列类型", "target_date": "日期",
    "windows_2h": "2小时时段", "overlap_2h": "2小时时间确认", "courts_2h": "2小时场地",
    "windows_1h": "1小时时段", "overlap_1h": "1小时时间确认", "courts_1h": "1小时场地",
}
GROUP_FIELDS = {
    "2h": ("windows_2h", "overlap_2h", "courts_2h"),
    "1h": ("windows_1h", "overlap_1h", "courts_1h"),
}
MAX_ANSWER_COUNT = 20
MAX_UPDATES_PER_TURN = 12
MAX_WINDOWS_PER_UPDATE = 12
MAX_INVALID_WINDOWS_PER_GROUP = (MAX_ANSWER_COUNT + 1) * MAX_WINDOWS_PER_UPDATE

WORKFLOW_CONTEXT = {
    "purpose": "把用户的预约意图整理成可核对的候选队列，不执行查询、预约、下单或付款。",
    "max_updates_per_turn": MAX_UPDATES_PER_TURN,
    "max_windows_per_update": MAX_WINDOWS_PER_UPDATE,
    "priority_order": ["booking_mode", "target_date", "2h_group", "1h_group", "queue_review"],
    "priority_note": "这是默认缺口优先级；若用户明确表示某个时长组更重要，优先处理该组当前 eligible 的缺口。",
    "stages": [
        {"id": "booking_mode", "fields": ["booking_mode"], "description": "先明确只抢2小时、只抢1小时或两种都抢。"},
        {"id": "target_date", "fields": ["target_date"], "description": "确认未过期且明确的目标日期。"},
        {"id": "2h_group", "fields": list(GROUP_FIELDS["2h"]), "description": "先确认2小时的时段、重叠、场地。"},
        {"id": "1h_group", "fields": list(GROUP_FIELDS["1h"]), "description": "独立确认1小时的时段、重叠、场地；通常在2小时组之后。"},
        {"id": "queue_review", "fields": [], "description": "全部启用字段有效后，生成预览等待用户核对。"},
    ],
    "groups": {
        "2h": {"active_when": "booking_mode is two_hour_only or both", "fields": list(GROUP_FIELDS["2h"])},
        "1h": {"active_when": "booking_mode is one_hour_only or both", "fields": list(GROUP_FIELDS["1h"])},
    },
    "gates": [
        {"field": "target_date", "requires": "booking_mode is explicit"},
        {"field": "windows_2h", "requires": "target_date is valid", "when": "2h group active"},
        {"field": "overlap_2h", "requires": "windows_2h are valid and overlap"},
        {"field": "courts_2h", "requires": "windows_2h valid and overlap resolved", "when": "2h group active"},
        {"field": "windows_1h", "requires": "target_date is valid", "when": "1h group active"},
        {"field": "overlap_1h", "requires": "windows_1h are valid and overlap"},
        {"field": "courts_1h", "requires": "windows_1h valid and overlap resolved", "when": "1h group active"},
        {"field": "queue_review", "requires": "all active fields valid"},
    ],
    "rules": [
        "每轮新提供的相对日期按 current_business_date 解释；历史已确认的 ISO 日期不重新计算；目标日期不得早于今天。今天和未来均可保存，自动执行仅在目标日前两天07:30尚未到达时具备资格。",
        "1小时和2小时是完全独立的队列，不能继承另一组的时段或场地。",
        "明确选择只抢一种时长时，另一组信息不改变队列类型，也不进入候选；在摘要里说明被排除的字段。",
        "只提及时段长度或时段候选不能代替队列类型选择；必须由用户明确选择只抢1小时、只抢2小时或两种都抢。",
        "队列类型尚未选择时，仍可保存已明确的日期与两个时长组的信息作为待用事实；不能因此生成候选或推断队列类型。",
        "同一时长组的场地列表应用于该组的每个时段；如果用户给不同时间段分配不同场地，不要合并成一个列表，必须标为场地范围歧义。",
        "每个时段开始和结束必须为整点、结束晚于开始；时长只能是1小时或2小时，且完整位于09:00–22:00内。",
        "场地编号只允许1到10；范围表示范围内的全部场地。",
        "不要因为字段值违反业务规则就把用户明确说出的事实丢弃；保留 typed update 供服务端标记为无效并追问。",
        "重叠时段需要用户明确保留或删除，不擅自删改。",
        "同一条消息可以提供多个字段；已明确的信息不重复提问。",
        "用户的问题可以结合已确认事实回答，同时只追问当前最优先的一个缺口。",
        "队列保存后由独立执行器处理；非空队列是用户的自动预约与付款授权，不需要再次问付款确认。",
        "实时场地状态只在服务端复核阶段获得；不得声称当前已查到未来余位。",
    ],
    "hard_gates": [
        "队列类型必须明确后才能创建候选。",
        "目标日期必须有效且不能早于业务日期。",
        "每个启用时长组都必须确认时间段和场地；场地不能在该组有效时间段尚未确认时确认。",
        "出现重叠时必须先由用户保留或删除，再确认对应场地。",
        "全部启用字段有效后才能生成预览。",
    ],
}


def eligible_fields(slots: dict) -> list[str]:
    """Return active unresolved fields the model may prioritize this turn."""
    if slots["booking_mode"].blocking:
        return ["booking_mode"]
    if slots["target_date"].blocking:
        return ["target_date"]
    return [field for field in FIELD_ORDER if slots[field].blocking]
