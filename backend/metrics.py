"""Read-only aggregates of durable business facts; no upstream calls or secrets."""
from contextlib import closing
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.db import connect_database
from backend.diagnostics import DiagnosticsUnavailable
from backend.plans.manual_queue import QUEUE_KIND, automatic_queue_schedule


def overview(settings, now, *, user_id=None, diagnostics=None):
    zone = ZoneInfo(settings.booking_timezone_name)
    today = datetime.fromtimestamp(now/1000,zone).date()
    days = [(today-timedelta(days=index)).isoformat() for index in range(6,-1,-1)]
    since = int(datetime.fromisoformat(days[0]).replace(tzinfo=zone).timestamp()*1000)
    predicate = " WHERE user_id=?" if user_id is not None else ""
    parameters = (user_id,) if user_id is not None else ()
    with closing(connect_database(settings.database_path,settings.sqlite_busy_timeout_ms)) as db:
        credentials = db.execute("SELECT COUNT(*) total,COALESCE(SUM(enabled),0) enabled FROM credentials"+predicate+
                                 (" AND " if predicate else " WHERE ")+"deleted_at_utc_ms IS NULL",parameters).fetchone()
        queues = db.execute("""SELECT json_extract(r.intent_json,'$.target_date') target_date,
            json_array_length(r.intent_json,'$.candidates') candidate_count,
            (SELECT COUNT(*) FROM json_each(r.intent_json,'$.candidates') WHERE json_extract(value,'$.duration_minutes')=60) one_hour,
            (SELECT COUNT(*) FROM json_each(r.intent_json,'$.candidates') WHERE json_extract(value,'$.duration_minutes')=120) two_hour
            FROM booking_plans p JOIN booking_plan_revisions r ON r.revision_id=p.current_revision_id AND r.user_id=p.user_id
            WHERE json_extract(r.intent_json,'$.kind')=? AND COALESCE(json_extract(r.intent_json,'$.deleted'),0)=0
              AND json_extract(r.intent_json,'$.target_date')>=? AND json_array_length(r.intent_json,'$.candidates')>0"""+
            (" AND p.user_id=?" if user_id is not None else ""),(QUEUE_KIND,today.isoformat(),*parameters)).fetchall()
        runs = db.execute("SELECT state,created_at_utc_ms FROM booking_execution_runs"+predicate+
                          (" AND " if predicate else " WHERE ")+"created_at_utc_ms BETWEEN ? AND ?",(*parameters,since,now)).fetchall()
        users = dict(db.execute("SELECT COUNT(*) total,COALESCE(SUM(status='active'),0) active FROM users").fetchone()) if user_id is None else None
    queue_count = candidates = eligible = one_hour = two_hour = 0
    for row in queues:
        queue_count += 1
        candidates += row["candidate_count"]
        one_hour += row["one_hour"]
        two_hour += row["two_hour"]
        eligible += int(automatic_queue_schedule(datetime.fromisoformat(row["target_date"]).date(),now,settings.booking_timezone_name)["eligible"])
    states = {key:0 for key in ("ready","calibrated","running","succeeded","failed","empty","stale","needs_attention")}
    trend = {day:{"date":day,"total":0,"succeeded":0,"failed":0,"needs_attention":0,"other":0} for day in days}
    for row in runs:
        states[row["state"]] += 1
        day = datetime.fromtimestamp(row["created_at_utc_ms"]/1000,zone).date().isoformat()
        trend[day]["total"] += 1
        trend[day][row["state"] if row["state"] in {"succeeded","failed","needs_attention"} else "other"] += 1
    result = {"scope":"personal" if user_id is not None else "system", "generated_at_utc_ms":now,
              "timezone":settings.booking_timezone_name,"business_date":today.isoformat(),
              "credentials":dict(credentials),
              "queues":{"upcoming":queue_count,"candidates":candidates,"before_opening":eligible,"one_hour":one_hour,"two_hour":two_hour},
              "execution":{"states":states,"trend":list(trend.values()),"runs":len(runs),
                           "pending":states["ready"]+states["calibrated"]+states["running"]}}
    if users is not None:
        result["users"] = users
        try:
            result["diagnostics"] = diagnostics.aggregate(now,settings.booking_timezone_name)
        except DiagnosticsUnavailable:
            result["diagnostics"] = {"available":False,"collection":diagnostics.status()}
    return result
