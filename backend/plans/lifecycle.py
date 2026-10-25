"""Read-only presentation of saved queues and their immutable execution records."""

from datetime import date

from backend.plans.manual_queue import automatic_queue_schedule


STATE_LABELS = {
    "ready": "已复核 · 等待开抢", "calibrated": "时间已校准 · 等待执行",
    "running": "执行中", "succeeded": "已执行 · 抢票成功",
    "failed": "三轮未成功", "empty": "复核后没有可执行候选",
    "stale": "保存队列已变更", "needs_attention": "需要关注",
}
TERMINAL_STATES = ("succeeded", "failed", "empty", "stale", "needs_attention")


def queue_lifecycle(row, now_utc_ms, timezone_name):
    schedule = automatic_queue_schedule(date.fromisoformat(row["target_date"]), now_utc_ms, row["timezone_name"])
    state = row["run_state"]
    if state:
        category = "succeeded" if state == "succeeded" else "pending" if state in {"ready", "calibrated", "running"} else "attention"
        label = STATE_LABELS.get(state, "执行状态待核对")
    elif not row["credential_id"]:
        category, state, label = "attention", "unbound", "历史未关联凭据"
    elif not row["candidate_count"]:
        category, state, label = "attention", "cleared", "候选已清空"
    elif row["timezone_name"] != timezone_name:
        category, state, label = "attention", "timezone_mismatch", "预约时区需要核对"
    elif schedule["eligible"]:
        category, state, label = "pending", "waiting", "待复核 · 未执行"
    else:
        category, state, label = "attention", "missed", "已错过开抢 · 未执行"
    event_at = row["completed_at_utc_ms"] or row["run_updated_at_utc_ms"] or (
        schedule["opening_at_utc_ms"] if state == "missed" else row["revision_created_at_utc_ms"]
    )
    return {
        "category": category, "state": state, "label": label,
        "opening_at_utc_ms": schedule["opening_at_utc_ms"],
        "completed_at_utc_ms": row["completed_at_utc_ms"],
        "event_at_utc_ms": event_at, "run_id": row["run_id"],
        "is_current_revision": row["revision_id"] == row["plan_current_revision_id"],
        "current_version": row["plan_current_version"],
    }


def lifecycle_sort_key(item, category):
    lifecycle = item["lifecycle"]
    if category == "pending":
        return (0 if lifecycle["state"] == "running" else 1, lifecycle["opening_at_utc_ms"], item["record_id"])
    return (-lifecycle["event_at_utc_ms"], item["record_id"])
