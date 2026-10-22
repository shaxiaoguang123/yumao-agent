"""Bounded, best-effort diagnostic events; never part of a booking transaction."""
from __future__ import annotations

import atexit
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
import json
import math
import os
from pathlib import Path
import queue
import re
import sqlite3
import stat
import sys
import threading
import time
from zoneinfo import ZoneInfo


MODULES = frozenset({"api", "auth", "admin", "credential", "upstream", "agent", "execution", "system"})
LEVELS = frozenset({"info", "warning", "error"})
_CODE = re.compile(r"[a-zA-Z0-9_.:-]{1,96}\Z", re.ASCII)
_ID = re.compile(r"[a-zA-Z0-9_-]{1,128}\Z", re.ASCII)
_CONTEXT = ContextVar("runtime_diagnostics", default={})
_ROOT = Path(__file__).resolve().parent.parent
_NUMBERS = frozenset({"http_status", "upstream_status", "attempt", "round_number", "candidate_index",
                     "candidate_count", "before_count", "after_count", "filtered_count", "context_turns",
                     "retry_after_seconds", "clock_offset_ms", "clock_uncertainty_ms", "version", "pid"})
_CODES = frozenset({"stage", "state", "phase", "field", "outcome", "method", "endpoint", "validation_code", "model_id", "target_user_id", "release", "process_role"})


def valid_identifier(value):
    return type(value) is str and bool(_ID.fullmatch(value))


def valid_code(value):
    return type(value) is str and bool(_CODE.fullmatch(value))


@contextmanager
def diagnostic_scope(collector=None, **identifiers):
    context = {**_CONTEXT.get(), **identifiers}
    if collector is not None:
        context["collector"] = collector
    token = _CONTEXT.set(context)
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def set_diagnostic_identity(**identifiers):
    _CONTEXT.set({**_CONTEXT.get(), **identifiers})


def record_event(module, action, *, level="info", code=None, exception=None, elapsed_ms=None, **details):
    context = _CONTEXT.get()
    collector = context.get("collector")
    if collector is not None:
        try:
            collector.emit(module, action, level=level, code=code, exception=exception,
                           elapsed_ms=elapsed_ms, **{**context, **details})
        except Exception:
            # A diagnostic failure must never change a booking or API result.
            with collector._lock:
                collector._dropped += 1


def _safe_frames(exception):
    frames = []
    current = exception.__traceback__
    while current is not None:
        frame = current.tb_frame
        filename = Path(frame.f_code.co_filename)
        try:
            filename = str(filename.resolve().relative_to(_ROOT))
        except (ValueError, OSError):
            filename = "<dependency>"
        frames.append({"file": filename, "function": frame.f_code.co_name[:100], "line": current.tb_lineno})
        current = current.tb_next
    return frames[-20:]


def report_exception(module, action, *, code, exception):
    record_event(module, action, level="error", code=code, exception=exception)
    # Fatal/unhandled errors must remain visible when async collection is disabled or fails.
    failure = {"module": module, "action": action, "code": code,
               "exception_type": type(exception).__name__[:80], "frames": _safe_frames(exception),
               **{key: value for key, value in _CONTEXT.get().items()
                  if key in {"request_id", "user_id", "credential_id", "conversation_id", "run_id"}
                  and valid_identifier(value)}}
    try:
        print(json.dumps(failure, ensure_ascii=False, separators=(",", ":")), file=sys.stderr)
    except (OSError, ValueError):
        pass


class DiagnosticsUnavailable(RuntimeError):
    pass


class RuntimeDiagnostics:
    RETENTION_DAYS = 14
    MAX_EVENTS = 50_000

    def __init__(self, database_path, *, enabled=True, role="web", capacity=2048):
        database_path = Path(database_path)
        self.path = database_path.with_name(database_path.stem + ".diagnostics.sqlite3")
        self.enabled = bool(enabled)
        self.role = role
        release = os.environ.get("APP_RELEASE", _ROOT.name)
        self.release = release if re.fullmatch(r"[a-f0-9]{7,40}", release) else "development"
        self._queue = queue.Queue(maxsize=capacity)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._state = "starting" if enabled else "disabled"
        self._last_write = None
        self._dropped = self._failed = 0
        self._lock = threading.Lock()
        self._thread = None
        if enabled:
            self._thread = threading.Thread(target=self._run, name="runtime-diagnostics", daemon=True)
            self._thread.start()
            atexit.register(self.close)

    def emit(self, module, action, *, level="info", code=None, exception=None, elapsed_ms=None, **values):
        if not self.enabled or self._stop.is_set() or module not in MODULES or level not in LEVELS or not valid_code(action):
            return
        details = {key: value for key, value in values.items()
                   if (key in _NUMBERS and type(value) is int and abs(value) <= 10**12)
                   or (key in _CODES and valid_code(value))}
        details.update(release=self.release, pid=os.getpid(), process_role=self.role)
        if exception is not None:
            details["exception_type"] = type(exception).__name__[:80]
            details["frames"] = _safe_frames(exception)
        event = {
            "at_utc_ms": time.time_ns() // 1_000_000, "level": level, "module": module,
            "action": action, "code": code if valid_code(code) else None,
            "elapsed_ms": max(0, min(10**12, int(elapsed_ms))) if type(elapsed_ms) in (int,float) and math.isfinite(elapsed_ms) else None,
            **{key: value if valid_identifier(value) else None for key, value in
               ((name, values.get(name)) for name in ("request_id", "user_id", "credential_id", "conversation_id", "run_id"))},
            "details_json": json.dumps(details, ensure_ascii=False, separators=(",", ":")),
        }
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            with self._lock:
                self._dropped += 1

    def status(self):
        with self._lock:
            return {"enabled": self.enabled, "state": self._state, "role": self.role,
                    "queue_depth": self._queue.qsize(), "dropped_events": self._dropped,
                    "failed_events": self._failed, "last_write_at_utc_ms": self._last_write,
                    "retention_days": self.RETENTION_DAYS}

    def flush(self, timeout=3):
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            self._stop.wait(.01)
        return self._queue.unfinished_tasks == 0

    def close(self):
        self._stop.set()
        if self._thread is not None and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)
        atexit.unregister(self.close)

    def _open_writer(self):
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise OSError("unsafe_diagnostic_file")
        finally:
            os.close(fd)
        db = sqlite3.connect(self.path, timeout=.5)
        db.execute("PRAGMA busy_timeout=500")
        # Separate rollback-journal DB: do not change the business DB's journaling or locks.
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        db.execute(f"PRAGMA max_page_count={200 * 1024 * 1024 // page_size}")
        db.executescript("""
          CREATE TABLE IF NOT EXISTS runtime_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT, at_utc_ms INTEGER NOT NULL,
            level TEXT NOT NULL, module TEXT NOT NULL, action TEXT NOT NULL, code TEXT,
            request_id TEXT, user_id TEXT, credential_id TEXT, conversation_id TEXT, run_id TEXT,
            elapsed_ms INTEGER, details_json TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS runtime_events_time ON runtime_events(at_utc_ms,event_id);
          CREATE INDEX IF NOT EXISTS runtime_events_request ON runtime_events(request_id,event_id);
          CREATE INDEX IF NOT EXISTS runtime_events_run ON runtime_events(run_id,event_id);
          CREATE INDEX IF NOT EXISTS runtime_events_conversation ON runtime_events(conversation_id,event_id);
          CREATE TABLE IF NOT EXISTS runtime_collectors (
            role TEXT NOT NULL, pid INTEGER NOT NULL, seen_at_utc_ms INTEGER NOT NULL,
            state TEXT NOT NULL, dropped_events INTEGER NOT NULL, failed_events INTEGER NOT NULL,
            last_write_at_utc_ms INTEGER, PRIMARY KEY(role,pid));
        """)
        return db

    def _prune(self, db, now):
        db.execute("DELETE FROM runtime_events WHERE at_utc_ms<?", (now-self.RETENTION_DAYS*86400000,))
        db.execute("DELETE FROM runtime_events WHERE event_id IN (SELECT event_id FROM runtime_events ORDER BY event_id DESC LIMIT -1 OFFSET ?)", (self.MAX_EVENTS,))
        db.execute("DELETE FROM runtime_collectors WHERE seen_at_utc_ms<?", (now-86400000,))

    def _run(self):
        db = None
        maintenance = heartbeat = 0
        notified = False
        try:
            while not self._stop.is_set() or not self._queue.empty():
                batch = []
                try:
                    batch.append(self._queue.get(timeout=.2))
                    while len(batch) < 128:
                        try:
                            batch.append(self._queue.get_nowait())
                        except queue.Empty:
                            break
                except queue.Empty:
                    pass
                try:
                    if db is None:
                        db = self._open_writer()
                    now = time.time_ns() // 1_000_000
                    maintain = now-maintenance >= 3600000
                    if maintain:
                        self._prune(db, now)
                    if batch:
                        db.executemany("""INSERT INTO runtime_events
                          (at_utc_ms,level,module,action,code,request_id,user_id,credential_id,conversation_id,run_id,elapsed_ms,details_json)
                          VALUES (:at_utc_ms,:level,:module,:action,:code,:request_id,:user_id,:credential_id,:conversation_id,:run_id,:elapsed_ms,:details_json)""", batch)
                    beat = now-heartbeat >= 30000 or bool(batch)
                    if beat:
                        with self._lock:
                            dropped, failed = self._dropped, self._failed
                        db.execute("INSERT OR REPLACE INTO runtime_collectors VALUES (?,?,?,?,?,?,?)",
                                   (self.role, os.getpid(), now, "ready", dropped, failed, now if batch else self._last_write))
                    db.commit()
                    if maintain:
                        maintenance = now
                    if beat:
                        heartbeat = now
                    with self._lock:
                        self._state = "ready"
                        if batch:
                            self._last_write = now
                    notified = False
                except (sqlite3.Error, OSError):
                    if db is not None:
                        db.rollback()
                        db.close()
                        db = None
                    with self._lock:
                        self._state = "degraded"
                        self._failed += len(batch)
                    if not notified:
                        # Fixed text only; a storage exception may contain paths or data.
                        print('{"event":"runtime_log_storage_unavailable"}', file=sys.stderr)
                        notified = True
                    self._stop.wait(.5)
                finally:
                    self._ready.set()
                    for _ in batch:
                        self._queue.task_done()
        finally:
            if db is not None:
                db.close()

    @contextmanager
    def reader(self):
        if not self.enabled:
            raise DiagnosticsUnavailable()
        db = None
        try:
            db = sqlite3.connect(self.path.resolve().as_uri()+"?mode=ro", uri=True, timeout=.25)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            yield db
        except (sqlite3.Error, OSError):
            raise DiagnosticsUnavailable() from None
        finally:
            if db is not None:
                db.close()

    @staticmethod
    def dto(row):
        result = dict(row)
        result["details"] = json.loads(result.pop("details_json"))
        return result

    def query(self, filters, *, since, until, limit=50, before=None):
        where, params = ["at_utc_ms>=?", "at_utc_ms<=?"], [since, until]
        for key, value in filters.items():
            if key not in {"level", "module", "user_id", "code", "request_id", "conversation_id", "run_id"}:
                raise ValueError("invalid_log_filter")
            where.append(f"{key}=?")
            params.append(value)
        if before is not None:
            where.append("event_id<?")
            params.append(before)
        with self.reader() as db:
            rows = db.execute("SELECT * FROM runtime_events WHERE " + " AND ".join(where) + " ORDER BY event_id DESC LIMIT ?",
                              (*params, limit+1)).fetchall()
            collectors = [dict(row) for row in db.execute("SELECT * FROM runtime_collectors ORDER BY role,seen_at_utc_ms DESC")]
        return {"events": [self.dto(row) for row in rows[:limit]],
                "next_cursor": rows[limit-1]["event_id"] if len(rows)>limit else None,
                "collection": self.status(), "collectors": collectors}

    def detail(self, event_id):
        with self.reader() as db:
            row = db.execute("SELECT * FROM runtime_events WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                return None
            # A request is the narrowest link; a run or conversation provides cross-request context.
            key = next((key for key in ("run_id", "request_id", "conversation_id") if row[key]), None)
            related = [] if key is None else db.execute(
                f"SELECT * FROM runtime_events WHERE {key}=? ORDER BY event_id DESC LIMIT 101", (row[key],)).fetchall()
        return {"event": self.dto(row), "related": [self.dto(item) for item in reversed(related[:100])],
                "related_truncated":len(related)>100}

    def aggregate(self, now, timezone_name):
        zone = ZoneInfo(timezone_name)
        today = datetime.fromtimestamp(now/1000, zone).date()
        days = [(today-timedelta(days=index)).isoformat() for index in range(6, -1, -1)]
        since = int(datetime.fromisoformat(days[0]).replace(tzinfo=zone).timestamp()*1000)
        with self.reader() as db:
            levels = {row["level"]: row["n"] for row in db.execute(
                "SELECT level,COUNT(*) n FROM runtime_events WHERE at_utc_ms BETWEEN ? AND ? GROUP BY level", (now-86400000, now))}
            modules = [dict(row) for row in db.execute(
                "SELECT module,COUNT(*) count FROM runtime_events WHERE at_utc_ms BETWEEN ? AND ? AND level IN ('warning','error') GROUP BY module ORDER BY count DESC,module", (now-86400000,now))]
            requests = db.execute("""SELECT COUNT(*) count,AVG(elapsed_ms) mean_ms,
                SUM(CASE WHEN json_extract(details_json,'$.http_status')>=500 THEN 1 ELSE 0 END) failed
                FROM runtime_events WHERE action='api.request' AND at_utc_ms BETWEEN ? AND ?""", (now-86400000,now)).fetchone()
            rows = db.execute("SELECT at_utc_ms,level FROM runtime_events WHERE at_utc_ms BETWEEN ? AND ? AND level IN ('warning','error')", (since,now)).fetchall()
            oldest = db.execute("SELECT MIN(at_utc_ms) FROM runtime_events").fetchone()[0]
        trend = {day:{"date":day,"warning":0,"error":0} for day in days}
        for row in rows:
            day = datetime.fromtimestamp(row["at_utc_ms"]/1000,zone).date().isoformat()
            trend[day][row["level"]] += 1
        return {"available":True,"levels":levels,"modules":modules,"trend":list(trend.values()),
                "request_count":requests["count"],"failed_requests":requests["failed"] or 0,
                "mean_request_ms":round(requests["mean_ms"]) if requests["mean_ms"] is not None else None,
                "retained_from_utc_ms":oldest,"collection":self.status()}


def init_request_diagnostics(app, collector):
    from flask import g, request
    import uuid

    @app.before_request
    def start_diagnostics():
        g.runtime_request_id = uuid.uuid4().hex
        g.runtime_started = time.monotonic_ns()
        scope = diagnostic_scope(collector, request_id=g.runtime_request_id)
        scope.__enter__()
        g.runtime_scope = scope

    @app.after_request
    def finish_diagnostics(response):
        response.headers["X-Request-ID"] = g.runtime_request_id
        response.headers.add("Access-Control-Expose-Headers", "X-Request-ID")
        error = None
        if response.status_code >= 400 and response.is_json and not response.is_streamed and (response.content_length or 0) <= 8192:
            body = response.get_json(silent=True)
            error = body.get("error") if type(body) is dict else None
        endpoint = request.endpoint or "unmatched"
        module = {"auth":"auth", "admin":"admin", "credentials":"credential", "planning":"agent",
                  "ai_models":"agent", "booking_execution":"execution", "orders":"upstream",
                  "availability_live":"upstream"}.get(endpoint.split(".",1)[0],"api")
        elapsed = (time.monotonic_ns()-g.runtime_started)//1_000_000
        # Log reads are audited without generating a second request event for polling.
        if (not endpoint.startswith("diagnostics.") or response.status_code>=400) and endpoint != "health.health":
            record_event(module, "api.request", code=error, method=request.method, endpoint=endpoint,
                         http_status=response.status_code, elapsed_ms=elapsed,
                         level="error" if response.status_code >= 500 else "warning" if response.status_code >= 400 else "info")
        return response

    @app.teardown_request
    def reset_diagnostics(_error):
        scope = g.pop("runtime_scope", None)
        if scope is not None:
            scope.__exit__(None, None, None)
