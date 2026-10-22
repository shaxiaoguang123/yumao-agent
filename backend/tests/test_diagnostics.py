from contextlib import closing
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from support import credential_test_settings
from backend.app import create_app
from backend.db import connect_database
from backend.diagnostics import RuntimeDiagnostics, diagnostic_scope, record_event
from backend.metrics import overview
from backend.migrate import migrate_database
from backend.ai.provider import ProviderConfig, ProviderFailure
from backend.ai.service import AIModelError
from backend.execution.repository import BookingExecutionRepository
from backend.ai.queue_graph import QueuePlanningGraph
from backend.ai.conversation import Phase
from test_queue_graph import StubService


class DiagnosticApiTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="yumao-diagnostics-")
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)/"business.sqlite3"
        migrate_database(self.path,5000)
        self.app = create_app({**credential_test_settings(self.path),"TESTING":True,"RUNTIME_LOGS_ENABLED":"true"})
        self.logs = self.app.extensions["runtime_diagnostics"]
        self.addCleanup(self.logs.close)
        self.clients = {}
        now = time.time_ns()//1_000_000
        with closing(connect_database(self.path,5000)) as db:
            for name,role in (("admin","admin"),("alice","user"),("bob","user")):
                db.execute("INSERT INTO users(user_id,username,normalized_username,password_hash,role,status,created_at_utc_ms,updated_at_utc_ms) VALUES (?,?,?,?,?,'active',?,?)",
                           (name,name,name,"synthetic-unused-hash",role,now,now))
        for name in ("admin","alice","bob"):
            client = self.app.test_client()
            session,_csrf = self.app.extensions["session_service"].create(name,now)
            client.set_cookie(self.app.config["SESSION_COOKIE_NAME"],session)
            self.clients[name] = client
        self.assertTrue(self.logs._ready.wait(2))

    def emit(self, **values):
        with diagnostic_scope(self.logs,user_id="alice",request_id="a"*32):
            record_event("agent","agent.interpretation_rejected",level="warning",code="invalid_model_proposal",**values)
        self.assertTrue(self.logs.flush())

    def test_log_and_global_metrics_require_a_current_administrator(self):
        for endpoint in ("/api/admin/logs","/api/admin/logs/1","/api/admin/metrics"):
            self.assertEqual(self.app.test_client().get(endpoint).status_code,401)
            self.assertEqual(self.clients["alice"].get(endpoint).status_code,403)
            self.assertEqual(self.clients["admin"].get(endpoint).headers["Cache-Control"],"no-store")
        with closing(connect_database(self.path,5000)) as db:
            db.execute("UPDATE users SET role='user' WHERE user_id='admin'")
        self.assertEqual(self.clients["admin"].get("/api/admin/logs").status_code,403)

    def test_filtering_cursor_and_related_events_are_stable(self):
        for attempt in range(1,5):
            self.emit(attempt=attempt,conversation_id="conversation-synthetic")
        client = self.clients["admin"]
        first = client.get("/api/admin/logs?module=agent&limit=2").get_json()
        self.assertEqual([item["details"]["attempt"] for item in first["events"]],[4,3])
        self.emit(attempt=5)
        second = client.get(f'/api/admin/logs?module=agent&limit=2&before={first["next_cursor"]}').get_json()
        self.assertEqual([item["details"]["attempt"] for item in second["events"]],[2,1])
        self.assertIsNone(second["next_cursor"])
        detail = client.get(f'/api/admin/logs/{first["events"][0]["event_id"]}').get_json()
        self.assertEqual(len(detail["related"]),5)
        self.assertEqual(client.get("/api/admin/logs/999999").status_code,404)

    def test_filters_reject_injection_duplicates_and_unbounded_reads(self):
        for query in ("?path=/etc/passwd","?limit=0","?limit=101","?limit=x","?level=debug",
                      "?module=unknown","?before=-1","?user_id=a%0Ab","?level=info&level=error",
                      "?since=0","?since=2&until=1","?before=99999999999999999999999999"):
            self.assertEqual(self.clients["admin"].get("/api/admin/logs"+query).status_code,400,query)

    def test_sensitive_payloads_exception_messages_and_locals_are_never_stored(self):
        secret = "synthetic-api-key-token-password-cookie"
        try:
            raise ValueError(secret)
        except ValueError as exc:
            self.emit(exception=exc,token=secret,api_key=secret,payment_password=secret,
                      prompt=secret,body={"secret":secret},headers={"Authorization":secret},url="https://example.invalid/"+secret)
        result = self.clients["admin"].get("/api/admin/logs?module=agent").get_json()
        event = result["events"][0]
        self.assertEqual(event["details"]["exception_type"],"ValueError")
        self.assertTrue(event["details"]["frames"])
        self.assertNotIn(secret,json.dumps(result))
        self.assertNotIn(secret.encode(),self.logs.path.read_bytes())

    def test_unhandled_errors_have_safe_stack_and_request_id_without_raw_target(self):
        secret = "synthetic-secret-in-error-and-url"
        @self.app.get("/api/synthetic-crash")
        def crash():
            raise RuntimeError(secret)
        self.app.config["PROPAGATE_EXCEPTIONS"] = False
        response = self.clients["alice"].get("/api/synthetic-crash?token="+secret)
        self.assertEqual(response.status_code,500)
        request_id = response.headers["X-Request-ID"]
        self.assertEqual(len(request_id),32)
        self.assertTrue(self.logs.flush())
        result = self.clients["admin"].get("/api/admin/logs?request_id="+request_id).get_json()
        self.assertEqual({row["action"] for row in result["events"]},{"api.unhandled","api.request"})
        self.assertNotIn(secret,json.dumps(result))

    def test_request_context_does_not_leak_between_users_or_outside_requests(self):
        a = self.clients["alice"].get("/api/credentials")
        b = self.clients["bob"].get("/api/credentials")
        self.assertNotEqual(a.headers["X-Request-ID"],b.headers["X-Request-ID"])
        self.emit(attempt=1)
        record_event("agent","should.not.be.recorded")
        self.logs.flush()
        with self.logs.reader() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runtime_events WHERE action='should.not.be.recorded'").fetchone()[0],0)
            for response,user_id in ((a,"alice"),(b,"bob")):
                self.assertEqual(db.execute("SELECT user_id FROM runtime_events WHERE request_id=? AND action='api.request'",(response.headers["X-Request-ID"],)).fetchone()[0],user_id)

    def test_request_modules_follow_the_actual_api_blueprint(self):
        response = self.clients["alice"].get("/api/auth/session")
        self.assertTrue(self.logs.flush())
        result = self.clients["admin"].get("/api/admin/logs?module=auth&request_id="+response.headers["X-Request-ID"]).get_json()
        self.assertEqual(result["events"][0]["details"]["endpoint"],"auth.session_status")

    def test_provider_failures_retain_http_category_without_content_or_api_key(self):
        config = ProviderConfig("synthetic-model","synthetic","https://example.invalid","synthetic-model","bearer","synthetic-provider-secret")
        provider = self.app.extensions["ai_provider_service"]
        with patch.object(provider,"resolve",return_value=(config,config.public())),patch.object(provider.transport,"chat",side_effect=ProviderFailure("provider_payment_required",upstream_status=402)):
            with diagnostic_scope(self.logs,user_id="alice",conversation_id="synthetic-conversation"):
                with self.assertRaises(AIModelError) as raised:
                    provider.chat("alice",[{"role":"user","content":"synthetic-private-conversation"}])
        self.assertEqual(raised.exception.code,"provider_payment_required")
        self.logs.flush()
        result = self.clients["admin"].get("/api/admin/logs?module=agent").get_json()
        self.assertEqual(result["events"][0]["details"]["upstream_status"],402)
        self.assertNotIn("synthetic-provider-secret",json.dumps(result))
        self.assertNotIn("synthetic-private-conversation",json.dumps(result))

    def test_langgraph_nodes_keep_the_request_diagnostic_context(self):
        service = StubService(Phase.COLLECTING)
        original = service.interpret_turn
        def interpret(prepared):
            record_event("agent","synthetic.graph_node")
            return original(prepared)
        with patch.object(service,"interpret_turn",side_effect=interpret),diagnostic_scope(self.logs,user_id="alice",request_id="b"*32,conversation_id="synthetic-conversation"):
            QueuePlanningGraph().invoke(service,{"message":"synthetic"})
        self.assertTrue(self.logs.flush())
        result = self.clients["admin"].get("/api/admin/logs?request_id="+"b"*32).get_json()
        self.assertEqual(result["events"][0]["user_id"],"alice")
        self.assertEqual(result["events"][0]["conversation_id"],"synthetic-conversation")

    def test_execution_detail_reuses_durable_stages_and_metrics_isolate_users(self):
        now = time.time_ns()//1_000_000
        target = (datetime.fromtimestamp(now/1000,ZoneInfo("Asia/Shanghai")).date()+timedelta(days=2)).isoformat()
        entry = {"court_preference":"1号场","start_time":"14:00","end_time":"16:00","duration_minutes":120}
        repository = BookingExecutionRepository(self.path,5000)
        stages = [{"stage_key":stage,"started_at_utc_ms":now,"completed_at_utc_ms":now+5,"elapsed_ms":5,"outcome":"success","round_number":0,"candidate_index":0,"safe_code":None}
                  for stage in ("reconcile_booking_node","reconcile_booking_by_time")]
        for name in ("alice","bob"):
            with closing(connect_database(self.path,5000)) as db:
                db.execute("BEGIN")
                db.execute("""INSERT INTO credentials(credential_id,user_id,label,credential_version,enabled,current_token_revision_id,account_binding_state,last_confirmed_validation_state,requires_revalidation,created_at_utc_ms,updated_at_utc_ms)
                    VALUES (?,?,?,1,1,?,'unresolved','never_confirmed',0,?,?)""",(name+"-credential",name,"synthetic",name+"-revision",now,now))
                db.execute("""INSERT INTO credential_token_revisions(revision_id,user_id,credential_id,revision_number,token_fingerprint,token_fingerprint_key_version,
                    initial_validation_result,initial_validation_at_utc_ms,created_by_user_id,secret_material_active,ciphertext,nonce,tag,encryption_key_version)
                    VALUES (?,?,?,1,?,'fp-v1','success',?,?,1,?,?,?,'enc-v1')""",
                    (name+"-revision",name,name+"-credential","a"*64,now,name,b'c',b'n'*12,b't'*16))
                db.commit()
            queue = self.app.extensions["plan_service"].save_manual_queue(name,target,0,[entry],now)
            with diagnostic_scope(self.logs,user_id=name,credential_id=name+"-credential"):
                run = repository.create_run(user_id=name,credential_id=name+"-credential",target_date=target,queue=queue,candidates=[],reconciliation={},state="empty",now_utc_ms=now,stage_events=stages)
            if name=="alice":
                run_id = run["run_id"]
        self.logs.flush()
        result = self.clients["admin"].get("/api/admin/logs?run_id="+run_id).get_json()
        detail = self.clients["admin"].get(f'/api/admin/logs/{result["events"][0]["event_id"]}').get_json()
        self.assertCountEqual([item["stage_key"] for item in detail["execution"]["stages"]],[item["stage_key"] for item in stages])
        self.assertNotIn("snapshot_json",detail["execution"])
        own = overview(self.app.extensions["app_settings"],now+10,user_id="alice")
        global_ = overview(self.app.extensions["app_settings"],now+10,diagnostics=self.logs)
        self.assertEqual(own["execution"]["runs"],1)
        self.assertEqual(global_["execution"]["runs"],2)
        self.assertEqual(own["execution"]["states"]["empty"],1)
        self.assertEqual(own["execution"]["trend"][-1]["total"],1)

    def test_metrics_are_user_scoped_and_count_current_queue_revision_once(self):
        zone = ZoneInfo("Asia/Shanghai")
        now = int(datetime(2026,10,22,7,tzinfo=zone).timestamp()*1000)
        plans = self.app.extensions["plan_service"]
        entry = {"court_preference":"1号场","start_time":"14:00","end_time":"16:00","duration_minutes":120}
        first = plans.save_manual_queue("alice","2026-10-24",0,[entry],now)
        plans.save_manual_queue("alice","2026-10-24",first["version"],[entry,{**entry,"court_preference":"2号场"}],now)
        plans.save_manual_queue("bob","2026-10-24",0,[entry],now)
        plans.save_manual_queue("alice","2026-10-21",0,[entry],now-3*86400000)
        result = overview(self.app.extensions["app_settings"],now,user_id="alice")
        self.assertEqual(result["queues"],{"upcoming":1,"candidates":2,"before_opening":1,"one_hour":0,"two_hour":2})
        self.assertNotIn("users",result)
        self.assertNotIn("diagnostics",result)
        self.assertEqual(len(result["execution"]["trend"]),7)
        boundary = int(datetime(2026,10,22,7,30,tzinfo=zone).timestamp()*1000)
        self.assertEqual(overview(self.app.extensions["app_settings"],boundary,user_id="alice")["queues"]["before_opening"],0)
        self.assertEqual(self.clients["alice"].get("/api/metrics/overview?user_id=bob").get_json()["scope"],"personal")

    def test_disabled_collection_does_not_prevent_business_metrics(self):
        self.logs.enabled = False
        self.assertEqual(self.clients["admin"].get("/api/admin/logs").status_code,503)
        response = self.clients["admin"].get("/api/admin/metrics")
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.get_json()["diagnostics"]["available"])

    def test_a_locked_log_database_does_not_block_business_requests(self):
        self.assertTrue(self.logs.flush())
        with closing(sqlite3.connect(self.logs.path,timeout=.1)) as db:
            db.execute("BEGIN EXCLUSIVE")
            try:
                started = time.monotonic()
                response = self.clients["alice"].get("/api/credentials")
                self.assertEqual(response.status_code,200)
                self.assertLess(time.monotonic()-started,.4)
                self.assertEqual(self.clients["admin"].get("/api/admin/logs").status_code,503)
            finally:
                db.rollback()


class DiagnosticStorageTests(unittest.TestCase):
    def test_two_process_roles_share_storage_without_changing_business_db(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"business.sqlite3"
            with closing(sqlite3.connect(path)) as db:
                db.execute("CREATE TABLE sentinel(value)")
                db.execute("INSERT INTO sentinel VALUES ('retained')")
                db.commit()
            collectors = [RuntimeDiagnostics(path,role=role) for role in ("web","worker")]
            try:
                for collector in collectors:
                    for index in range(20):
                        collector.emit("system","synthetic.event",attempt=index)
                self.assertTrue(all(collector.flush(5) for collector in collectors))
                with collectors[0].reader() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0],40)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM runtime_collectors").fetchone()[0],2)
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute("SELECT value FROM sentinel").fetchone()[0],"retained")
                    self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0],"delete")
            finally:
                for collector in collectors:
                    collector.close()

    def test_full_queue_and_unavailable_storage_are_bounded_and_visible(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(RuntimeDiagnostics,"_open_writer",side_effect=OSError("synthetic-secret")),patch("sys.stderr",new_callable=io.StringIO) as stderr:
                collector = RuntimeDiagnostics(Path(temp)/"business.sqlite3",capacity=2)
                try:
                    started = time.monotonic()
                    for _ in range(100):
                        collector.emit("system","synthetic.event")
                    self.assertLess(time.monotonic()-started,.5)
                    self.assertTrue(collector._ready.wait(2))
                    status = collector.status()
                    self.assertGreater(status["dropped_events"],0)
                    self.assertEqual(status["state"],"degraded")
                    self.assertNotIn("synthetic-secret",stderr.getvalue())
                finally:
                    collector.close()

    def test_retention_removes_old_and_excess_events(self):
        with tempfile.TemporaryDirectory() as temp:
            collector = RuntimeDiagnostics(Path(temp)/"business.sqlite3")
            try:
                for _ in range(5):
                    collector.emit("system","synthetic.event")
                self.assertTrue(collector.flush())
                with closing(sqlite3.connect(collector.path,timeout=1)) as db:
                    db.execute("UPDATE runtime_events SET at_utc_ms=1 WHERE event_id=1")
                    collector.MAX_EVENTS = 2
                    collector._prune(db,time.time_ns()//1_000_000)
                    db.commit()
                    self.assertEqual([r[0] for r in db.execute("SELECT event_id FROM runtime_events ORDER BY event_id")],[4,5])
            finally:
                collector.close()


if __name__ == "__main__":
    unittest.main()
