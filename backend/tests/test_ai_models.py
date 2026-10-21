from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.ai.crypto import EncryptedProviderKey, ProviderKeyCipher
from backend.ai.provider import PinnedChatCompletionsTransport, ProviderConfig, ProviderFailure, _resolve_public, validate_base_url
from backend.credentials.keyring import CredentialKeyring
from backend.db import connect_database
from backend.migrate import migrate_database
from support import credential_test_settings


ORIGIN = "http://localhost:5173"
KEYRING = CredentialKeyring({"enc-v1": bytes(range(32, 64))}, "enc-v1")


class FakeTransport:
    def __init__(self): self.calls = []
    def list_models(self, config):
        self.calls.append((config, "GET /models"))
        return [{"id":"deepseek-flash"},{"id":"qwen-plus"},{"id":"deepseek-flash"},{"id":"bad id"},{"name":"missing-id"}]
    def chat(self, config, messages):
        self.calls.append((config, messages))
        return "synthetic reply"
    def test(self, config):
        self.calls.append((config, [{"role":"user", "content":"Reply with OK."}]))
        return True


class AIModelTests(unittest.TestCase):
    def test_default_chat_deadlines_allow_slower_structured_generation(self):
        transport = PinnedChatCompletionsTransport()
        self.assertEqual(transport.read_timeout, 45)
        self.assertEqual(transport.total_timeout, 90)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ai-models-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "db.sqlite3"
        migrate_database(self.path, 5000)
        self.app = __import__("backend.app", fromlist=["*"]).create_app({
            **credential_test_settings(self.path), "TESTING": True, "APP_ALLOWED_ORIGINS": ORIGIN,
            "LLM_BASE_URL": "https://service.example/v1", "LLM_MODEL": "svc-model",
            "LLM_API_KEY": "service-secret-synthetic", "LLM_AUTH_MODE": "bearer",
            "LLM_PROTOCOL": "openai-chat-completions",
        })
        self.app.testing = True
        self.assertNotIn("LLM_API_KEY", self.app.config)
        self.service = self.app.extensions["ai_provider_service"]
        self.service.resolver = lambda _host: ["93.184.216.34"]
        self.transport = FakeTransport()
        self.service.transport = self.transport
        self.a, self.b = self.app.test_client(), self.app.test_client()
        with connect_database(self.path, 5000) as db:
            for user, username in (("user-a", "alice"), ("user-b", "bob")):
                db.execute("""INSERT INTO users(user_id,username,normalized_username,password_hash,role,status,created_at_utc_ms,updated_at_utc_ms)
                    VALUES(?,?,?,'synthetic','user','active',1,1)""", (user,username,username))
        self.csrf_a = self._login(self.a, "user-a")
        self.csrf_b = self._login(self.b, "user-b")

    def _login(self, client, user):
        session, csrf = self.app.extensions["session_service"].create(user, 1_800_000_000_000)
        client.set_cookie("yumao_session", session)
        return csrf

    def _headers(self, csrf=None):
        result = {"Origin": ORIGIN, "Content-Type": "application/json"}
        if csrf: result["X-CSRF-Token"] = csrf
        return result

    def _create(self, client=None, csrf=None, name="My model"):
        return (client or self.a).post("/api/ai/models", headers=self._headers(csrf or self.csrf_a), json={
            "name":name,"base_url":"https://vendor.example/v1","model":"model-x",
            "auth_mode":"bearer","api_key":"user-secret-synthetic",
        })

    def test_explicit_parsing_tests_validate_without_saving_and_isolate_model(self):
        import json
        from datetime import date, timedelta
        selected=self._create(name='Selected').get_json()['model']
        tested=self._create(name='Tested').get_json()['model']
        self.service.set_preferences('user-a',selected['id'],None)
        def reply(config,messages):
            self.transport.calls.append((config,messages))
            if '羽毛球预约队列 Agent' in messages[0]['content']:
                payload=json.loads(messages[1]['content'])
                latest=payload['latest_user_message']
                choices={'1':'two_hour_only','2':'one_hour_only','3':'both',
                         'A':'two_hour_only','B':'one_hour_only','C':'both'}
                if latest in choices:
                    result={'kind':'answer','updates':[
                        {'field':'booking_mode','operation':'set','value':choices[latest],'evidence':latest},
                    ],'unresolved':[],'reply':'','next_field':'courts_2h',
                        'next_question':'2小时选哪些场地？例如1号和4号。'}
                elif '1小时还是2小时' in latest:
                    slots={slot['field']:slot for slot in payload['current_slots']}
                    result={'kind':'question','updates':[],'unresolved':[],
                            'reply':f"我记录了{slots['target_date']['display']}，2小时14:00-16:00；还缺场地。",
                            'next_field':'courts_2h','next_question':'2小时选哪些场地？例如1号和4号。'}
                elif latest=='1号场':
                    result={'kind':'answer','updates':[
                        {'field':'courts_2h','operation':'replace','value':[1],'evidence':'1号场'},
                    ],'unresolved':[],'reply':'已记录1号场。','next_field':None,'next_question':''}
                elif '把2小时' in latest and '18-20' in latest and '4号场' in latest:
                    result={'kind':'answer','updates':[
                        {'field':'windows_2h','operation':'replace','value':[{'start':'18:00','end':'20:00'}],
                         'evidence':'改为18-20'},
                        {'field':'courts_2h','operation':'replace','value':[4],'evidence':'4号场'},
                    ],'unresolved':[],'reply':'已将2小时候选改为18-20和4号场。',
                        'next_field':None,'next_question':''}
                elif '11号场' in latest or '22-24' in latest or '14-17' in latest:
                    target=(date.fromisoformat(payload['conversation_start_date'])+timedelta(days=2)).isoformat()
                    day=date.fromisoformat(target)
                    target_text=f'{day.month}月{day.day}日'
                    if '11号场' in latest:
                        window, court = {'start':'14:00','end':'16:00'}, 11
                        window_evidence, court_evidence = '14-16', '11号场'
                    elif '22-24' in latest:
                        window, court = {'start':'22:00','end':'24:00'}, 1
                        window_evidence, court_evidence = '22-24', '1号场'
                    else:
                        window, court = {'start':'14:00','end':'17:00'}, 1
                        window_evidence, court_evidence = '14-17', '1号场'
                    result={'kind':'answer','updates':[
                        {'field':'booking_mode','operation':'set','value':'two_hour_only','evidence':'只抢2小时'},
                        {'field':'target_date','operation':'set','value':target,'evidence':target_text},
                        {'field':'windows_2h','operation':'replace','value':[window],'evidence':window_evidence},
                        {'field':'courts_2h','operation':'replace','value':[court],'evidence':court_evidence},
                    ],'unresolved':[],'reply':'','next_field':'courts_2h','next_question':'请检查这个候选值。'}
                else:
                    target=(date.fromisoformat(payload['conversation_start_date'])+timedelta(days=2)).isoformat()
                    target_day=date.fromisoformat(target)
                    target_text=f'{target_day.month}月{target_day.day}日'
                    result={'kind':'answer','updates':[
                        {'field':'target_date','operation':'set','value':target,'evidence':target_text},
                        {'field':'windows_2h','operation':'replace','value':[{'start':'14:00','end':'16:00'}],
                         'evidence':'14-16'},
                    ],'unresolved':[],'reply':'','next_field':'booking_mode',
                        'next_question':'先选队列类型：1/A只抢2小时；2/B只抢1小时；3/C两种都抢。'}
                return json.dumps(result,ensure_ascii=False)
            return json.dumps({'warnings':[]})
        self.transport.chat=reply
        endpoint='/api/ai/models/'+tested['id']+'/test-parsing'
        response=self.a.post(endpoint,json={},headers=self._headers(self.csrf_a))
        self.assertEqual(response.status_code,200)
        body=response.get_json()
        self.assertEqual(body['outcome'],'parsed')
        self.assertTrue(body['ok'])
        self.assertTrue(body['question_check']['short_choice'])
        self.assertTrue(body['question_check']['mode_choices'])
        self.assertTrue(body['question_check']['answered'])
        self.assertTrue(body['question_check']['context_used'])
        self.assertTrue(body['question_check']['step_preserved'])
        self.assertTrue(body['question_check']['queue_ready'])
        self.assertTrue(body['question_check']['correction_applied'])
        self.assertTrue(body['question_check']['reviewed'])
        self.assertEqual(body['proposal']['entries'], [{
            'court_preference': '4号场', 'start_time': '18:00', 'end_time': '20:00',
            'duration_minutes': 120, 'scope_label': '羽毛球',
        }])
        self.assertEqual([call[0].provider_id for call in self.transport.calls],[tested['id']]*12)
        self.assertEqual(self.service.list_models('user-a')['selected_model_id'],selected['id'])
        self.assertEqual(self.b.post(endpoint,json={},headers=self._headers(self.csrf_b)).status_code,404)
        self.assertEqual(len(self.transport.calls),12)
        self.assertIn('羽毛球预约队列 Agent',self.transport.calls[0][1][0]['content'])
        with connect_database(self.path,5000) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM booking_plans').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM booking_plan_revisions').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM planning_conversations').fetchone()[0],0)
        self.assertEqual(self.app.test_client().post(endpoint,json={},headers=self._headers()).status_code,401)
        self.assertEqual(self.a.post(endpoint,json={},headers=self._headers()).status_code,403)

    def test_parsing_test_does_not_pass_on_a_generic_context_reply(self):
        import json
        from datetime import date, timedelta
        tested=self._create(name='Context model').get_json()['model']
        def reply(config,messages):
            self.transport.calls.append((config,messages))
            if '羽毛球预约队列 Agent' not in messages[0]['content']:
                return json.dumps({'warnings':[]})
            payload=json.loads(messages[1]['content'])
            latest=payload['latest_user_message']
            choices={'1':'two_hour_only','2':'one_hour_only','3':'both',
                     'A':'two_hour_only','B':'one_hour_only','C':'both'}
            if latest in choices:
                result={'kind':'answer','updates':[
                    {'field':'booking_mode','operation':'set','value':choices[latest],'evidence':latest},
                ],'unresolved':[],'reply':'','next_field':'courts_2h',
                    'next_question':'2小时选哪些场地？例如1号和4号。'}
            elif '1小时还是2小时' in latest:
                result={'kind':'question','updates':[],'unresolved':[],
                        'reply':'我可以帮你整理。','next_field':'courts_2h',
                        'next_question':'2小时选哪些场地？例如1号和4号。'}
            else:
                target=(date.fromisoformat(payload['conversation_start_date'])+timedelta(days=2)).isoformat()
                day=date.fromisoformat(target)
                result={'kind':'answer','updates':[
                    {'field':'target_date','operation':'set','value':target,'evidence':f'{day.month}月{day.day}日'},
                    {'field':'windows_2h','operation':'replace','value':[{'start':'14:00','end':'16:00'}],'evidence':'14-16'},
                ],'unresolved':[],'reply':'','next_field':'booking_mode',
                    'next_question':'先选队列类型：1/A只抢2小时；2/B只抢1小时；3/C两种都抢。'}
            return json.dumps(result,ensure_ascii=False)
        self.transport.chat=reply
        endpoint='/api/ai/models/'+tested['id']+'/test-parsing'
        response=self.a.post(endpoint,json={},headers=self._headers(self.csrf_a))
        body=response.get_json()
        self.assertEqual(response.status_code,200)
        self.assertEqual(body['outcome'],'context_failed')
        self.assertFalse(body['ok'])
        self.assertTrue(body['question_check']['answered'])
        self.assertTrue(body['question_check']['short_choice'])
        self.assertTrue(body['question_check']['mode_choices'])
        self.assertFalse(body['question_check']['context_used'])
        self.assertEqual(len(self.transport.calls),5)
        with connect_database(self.path,5000) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM booking_plans').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM planning_conversations').fetchone()[0],0)

    def test_parsing_capability_failures_remain_safe(self):
        import json
        model=self._create().get_json()['model']
        endpoint='/api/ai/models/'+model['id']+'/test-parsing'
        for content in ('raw supplier text', json.dumps({'warnings':'x'}), json.dumps({'warnings':[],'entries':[]})):
            self.transport.chat=lambda *_args: content
            response=self.a.post(endpoint,json={},headers=self._headers(self.csrf_a))
            self.assertEqual((response.status_code,response.get_json()['error']),(502,'invalid_model_proposal'))
            self.assertNotIn('raw supplier',response.get_data(as_text=True))
        for code in ('provider_auth_failed','provider_access_denied','provider_model_or_endpoint_not_found','provider_rate_limited','provider_timeout','provider_unavailable','provider_output_truncated'):
            def failure(*_args): raise ProviderFailure(code,502)
            self.transport.chat=failure
            response=self.a.post(endpoint,json={},headers=self._headers(self.csrf_a))
            body=response.get_json()
            self.assertEqual(response.status_code,200)
            self.assertEqual(body['outcome'],'provider_failed')
            self.assertEqual(body['provider_error'],code)
            self.assertEqual(body['failed_stage'],'queue_mode_prompt')
        with connect_database(self.path,5000) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM booking_plan_revisions').fetchone()[0],0)

    def test_user_call_limit_shared_by_connection_and_proposals(self):
        for _ in range(12):
            response=self.a.post('/api/ai/models/service_default/test',json={},headers=self._headers(self.csrf_a))
            self.assertEqual(response.status_code,200)
        response=self.a.post('/api/ai/models/service_default/test-parsing',json={},headers=self._headers(self.csrf_a))
        self.assertEqual((response.status_code,response.get_json()['error']),(429,'ai_call_rate_limited'))
        self.assertGreater(int(response.headers['Retry-After']),0)
        self.assertEqual(len(self.transport.calls),12)
        self.assertEqual(self.b.post('/api/ai/models/service_default/test',json={},headers=self._headers(self.csrf_b)).status_code,200)

    def test_auth_csrf_isolation_and_secret_never_echoes(self):
        anon = self.app.test_client()
        self.assertEqual(anon.get("/api/ai/models").status_code, 401)
        self.assertEqual(self.a.post("/api/ai/models", headers=self._headers(), json={}).status_code, 403)
        created = self._create()
        self.assertEqual(created.status_code, 201)
        self.assertNotIn(b"user-secret-synthetic", created.data)
        model_id = created.get_json()["model"]["id"]
        self.assertEqual(self.b.get("/api/ai/models").get_json()["models"], [])
        self.assertEqual(self.b.patch("/api/ai/models/preferences", headers=self._headers(self.csrf_b), json={
            "selected_model_id":model_id,"default_model_id":None,
        }).status_code, 404)
        body = self.a.get("/api/ai/models").get_json()
        self.assertEqual(body["service_default"]["id"], "service_default")
        self.assertEqual(body["models"][0]["has_api_key"], True)
        self.assertNotIn("'api_key':", str(body))

    def test_model_discovery_is_explicit_secret_safe_and_owner_scoped(self):
        body={"base_url":"https://vendor.example/v1","auth_mode":"bearer","api_key":"ephemeral-discovery-secret"}
        response=self.a.post('/api/ai/models/discover',json=body,headers=self._headers(self.csrf_a))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json(),{"models":["deepseek-flash","qwen-plus"]})
        self.assertNotIn(b"ephemeral-discovery-secret",response.data)
        config,operation=self.transport.calls[-1]
        self.assertEqual((operation,config.api_key),("GET /models","ephemeral-discovery-secret"))
        self.assertEqual(self.service.list_models('user-a')['models'],[])
        self.assertEqual(self.a.post('/api/ai/models/discover',json=body,headers=self._headers()).status_code,403)

        saved=self._create().get_json()['model']
        response=self.a.post(f"/api/ai/models/{saved['id']}/discover",json={},headers=self._headers(self.csrf_a))
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.transport.calls[-1][0].api_key,"user-secret-synthetic")
        self.assertEqual(self.b.post(f"/api/ai/models/{saved['id']}/discover",json={},headers=self._headers(self.csrf_b)).status_code,404)
        self.assertEqual(self.app.test_client().post(f"/api/ai/models/{saved['id']}/discover",json={},headers=self._headers()).status_code,401)

    def test_model_discovery_validates_endpoint_and_requires_ephemeral_key(self):
        for body in (
            {"base_url":"http://vendor.example/v1","auth_mode":"bearer","api_key":"secret"},
            {"base_url":"https://vendor.example/v1","auth_mode":"bearer"},
            {"base_url":"https://vendor.example/v1","auth_mode":"none","api_key":"secret"},
        ):
            response=self.a.post('/api/ai/models/discover',json=body,headers=self._headers(self.csrf_a))
            self.assertEqual(response.status_code,400)
        self.assertEqual(self.transport.calls,[])

    def test_crud_preferences_secret_replace_delete_and_fake_test(self):
        created = self._create().get_json()["model"]
        model_id = created["id"]
        self.assertEqual(self.a.patch("/api/ai/models/preferences", headers=self._headers(self.csrf_a), json={
            "selected_model_id":model_id,"default_model_id":"service_default",
        }).status_code, 200)
        answer, public = self.service.chat("user-a", [{"role":"user","content":"hi"}])
        self.assertEqual(answer, "synthetic reply")
        self.assertEqual(public["id"], model_id)
        self.assertEqual(self.transport.calls[-1][0].api_key, "user-secret-synthetic")
        tested = self.a.post(f"/api/ai/models/{model_id}/test", headers=self._headers(self.csrf_a), json={})
        self.assertEqual(tested.get_json(), {"ok":True,"message":"连接成功。"})
        changed = self.a.patch(f"/api/ai/models/{model_id}", headers=self._headers(self.csrf_a), json={
            "base_version":1,"name":"Renamed","base_url":"https://vendor.example/v1","model":"model-y",
            "auth_mode":"bearer","api_key":"replacement-secret-synthetic",
        })
        self.assertEqual(changed.status_code, 200)
        self.assertNotIn(b"replacement-secret-synthetic", changed.data)
        deleted_key = self.a.patch(f"/api/ai/models/{model_id}", headers=self._headers(self.csrf_a), json={
            "base_version":2,"name":"Renamed","base_url":"https://vendor.example/v1","model":"model-y",
            "auth_mode":"bearer","delete_api_key":True,
        })
        self.assertEqual(deleted_key.status_code, 200)
        self.assertFalse(deleted_key.get_json()["model"]["has_api_key"])
        removed = self.a.delete(f"/api/ai/models/{model_id}", headers=self._headers(self.csrf_a), json={"base_version":3})
        self.assertEqual(removed.status_code, 204)
        self.assertEqual(self.a.get("/api/ai/models").get_json()["selected_model_id"], None)

    def test_url_validation_and_dns_rebinding_set_rejection(self):
        for value in ("http://vendor.example", "https://user:pass@vendor.example", "https://vendor.example:444",
                      "https://vendor.example/v1?x=y", "https://vendor.example/#frag", "https://vendor.example/a/../b",
                      "https://vendor.example/a\r\nb"):
            with self.subTest(value=value), self.assertRaises(ProviderFailure): validate_base_url(value)
        for answer in ("127.0.0.1", "224.0.0.1", "240.0.0.1", "::ffff:8.8.8.8"):
            with patch("backend.ai.provider.socket.getaddrinfo", return_value=[(2,1,6,"",(answer,443))]):
                with self.subTest(address=answer), self.assertRaises(ProviderFailure): _resolve_public("mixed.example", timeout=1)

    def test_pinned_transport_does_not_retry_post_and_aborts_total_deadline(self):
        class FakeSocket:
            def settimeout(self, _value): pass
        class FakeConnection:
            instances=[]
            def __init__(self,*_args,**_kwargs): self.sock=FakeSocket(); self.closed=False; self.__class__.instances.append(self)
            def connect(self): pass
            def request(self,*_args,**_kwargs): raise OSError("synthetic ambiguous failure")
            def close(self): self.closed=True; self.sock=None
        transport = PinnedChatCompletionsTransport(resolver=lambda _host:["93.184.216.34","93.184.216.35"])
        with patch("backend.ai.provider._PinnedHTTPSConnection", FakeConnection):
            with self.assertRaises(ProviderFailure):
                transport.chat(ProviderConfig("m","m","https://vendor.example/v1","model","none"), [{"role":"user","content":"x"}])
        self.assertEqual(len(FakeConnection.instances),1)

        import time
        class SlowResponse:
            status=200
            reads=0
            def read1(self, _size):
                self.reads+=1
                if self.reads==1:
                    time.sleep(0.06)
                    return b"{}"
                return b""
        class SlowConnection(FakeConnection):
            instances=[]
            def request(self,*_args,**_kwargs): pass
            def getresponse(self): return SlowResponse()
        transport = PinnedChatCompletionsTransport(resolver=lambda _host:["93.184.216.34"],total_timeout=0.03)
        # The fake connection does not use TLS. Exclude machine certificate-load
        # latency so the 30ms budget actually tests the slow read/abort path.
        with patch("backend.ai.provider._PinnedHTTPSConnection", SlowConnection), \
                patch("backend.ai.provider.ssl.create_default_context", return_value=object()):
            with self.assertRaises(ProviderFailure) as caught:
                transport.chat(ProviderConfig("m","m","https://vendor.example/v1","model","none"), [{"role":"user","content":"x"}])
        self.assertEqual(caught.exception.code,"provider_timeout")
        self.assertEqual(len(SlowConnection.instances), 1)
        self.assertTrue(SlowConnection.instances[0].closed)

    def test_transport_no_auth_redirect_or_oversize_body_leak(self):
        import json
        class FakeSocket:
            def settimeout(self, _value): pass
        class Response:
            def __init__(self,status,body): self.status=status; self.body=body; self.sent=False
            def read1(self,size):
                if self.sent: return b""
                self.sent=True
                return self.body[:size]
        class RecordingConnection:
            last=None
            def __init__(self,*_args,**_kwargs): self.sock=FakeSocket(); self.path=None; self.headers=None; self.body=None; self.response=Response(200,b'{"choices":[{"message":{"content":"ok"}}]}'); RecordingConnection.last=self
            def connect(self): pass
            def request(self,_method,path,body,headers): self.path,self.body,self.headers=path,body,headers
            def getresponse(self): return self.response
            def close(self): self.sock=None
        transport=PinnedChatCompletionsTransport(resolver=lambda _host:["93.184.216.34"])
        with patch("backend.ai.provider._PinnedHTTPSConnection",RecordingConnection):
            result=transport.chat(ProviderConfig("m","m","https://vendor.example/v1","model","none"),[{"role":"user","content":"hello"}])
        self.assertEqual(result,"ok")
        request=json.loads(RecordingConnection.last.body)
        self.assertEqual(request["max_tokens"],3072)
        self.assertEqual(RecordingConnection.last.path,"/v1/chat/completions")
        self.assertNotIn("Authorization",RecordingConnection.last.headers)

        with patch("backend.ai.provider._PinnedHTTPSConnection",RecordingConnection):
            self.assertTrue(transport.test(ProviderConfig("m","m","https://vendor.example/v1","model","none")))
        self.assertEqual(json.loads(RecordingConnection.last.body)["max_tokens"],8)

        RecordingConnection.getresponse=lambda self: Response(302,b"vendor body")
        with patch("backend.ai.provider._PinnedHTTPSConnection",RecordingConnection):
            with self.assertRaises(ProviderFailure) as redirect:
                transport.chat(ProviderConfig("m","m","https://vendor.example/v1","model","none"),[{"role":"user","content":"x"}])
        self.assertEqual(redirect.exception.code,"provider_redirect_rejected")

        RecordingConnection.getresponse=lambda self: Response(200,b"x"*20)
        limited=PinnedChatCompletionsTransport(resolver=lambda _host:["93.184.216.34"],max_response_bytes=8)
        with patch("backend.ai.provider._PinnedHTTPSConnection",RecordingConnection):
            with self.assertRaises(ProviderFailure) as oversized:
                limited.chat(ProviderConfig("m","m","https://vendor.example/v1","model","none"),[{"role":"user","content":"x"}])
        self.assertEqual(oversized.exception.code,"provider_response_too_large")

    def test_truncated_provider_output_is_not_a_complete_model_decision(self):
        import json
        transport=PinnedChatCompletionsTransport()
        config=ProviderConfig("m","m","https://vendor.example/v1","model","none")
        for content in ('', '{"warnings":[]}'):
            raw=json.dumps({"choices":[{"finish_reason":"length","message":{"content":content}}]}).encode()
            with self.subTest(content=content), patch.object(transport,'_exchange',return_value=raw):
                with self.assertRaises(ProviderFailure) as caught:
                    transport.chat(config,[{"role":"user","content":"x"}])
                self.assertEqual(caught.exception.code,'provider_output_truncated')
                self.assertTrue(transport.test(config))
        with patch.object(transport,'_exchange',side_effect=ProviderFailure('provider_auth_failed')):
            with self.assertRaises(ProviderFailure) as caught:
                transport.test(config)
            self.assertEqual(caught.exception.code,'provider_auth_failed')

    def test_pinned_transport_reads_models_with_get_and_bearer_auth(self):
        import json
        class FakeSocket:
            def settimeout(self, _value): pass
        class Response:
            status=200
            def __init__(self): self.sent=False
            def read1(self,size):
                if self.sent:return b""
                self.sent=True
                return b'{"object":"list","data":[{"id":"deepseek-flash"}]}'[:size]
        class RecordingConnection:
            last=None
            def __init__(self,*_args,**_kwargs):self.sock=FakeSocket();self.response=Response();RecordingConnection.last=self
            def connect(self):pass
            def request(self,*args,**kwargs):self.request_args=args;self.request_kwargs=kwargs
            def getresponse(self):return self.response
            def close(self):self.sock=None
        transport=PinnedChatCompletionsTransport(resolver=lambda _host:["93.184.216.34"])
        config=ProviderConfig("m","m","https://vendor.example/v1","model","bearer","discovery-key")
        with patch("backend.ai.provider._PinnedHTTPSConnection",RecordingConnection):
            models=transport.list_models(config)
        self.assertEqual(models,[{"id":"deepseek-flash"}])
        self.assertEqual(RecordingConnection.last.request_args[:2],("GET","/v1/models"))
        self.assertEqual(RecordingConnection.last.request_kwargs["headers"]["Authorization"],"Bearer discovery-key")
        self.assertIsNone(RecordingConnection.last.request_kwargs["body"])

    def test_provider_http_failures_report_safe_categories(self):
        import socket
        class FakeSocket:
            def settimeout(self, _value): pass
        class Response:
            def __init__(self,status): self.status=status; self.sent=False
            def read1(self,_size):
                if self.sent:return b""
                self.sent=True
                return b'{"message":"private provider response"}'
        class Connection:
            status=401
            def __init__(self,*_args,**_kwargs): self.sock=FakeSocket()
            def connect(self): pass
            def request(self,*_args,**_kwargs): pass
            def getresponse(self): return Response(self.status)
            def close(self): self.sock=None
        transport=PinnedChatCompletionsTransport(resolver=lambda _host:["93.184.216.34"])
        config=ProviderConfig("m","m","https://vendor.example/v1","model","none")
        for status,expected in ((401,"provider_auth_failed"),(402,"provider_payment_required"),
                                (403,"provider_access_denied"),
                                (404,"provider_model_discovery_unavailable"),(429,"provider_rate_limited"),
                                (503,"provider_server_error")):
            with self.subTest(status=status), patch("backend.ai.provider._PinnedHTTPSConnection",Connection):
                Connection.status=status
                with self.assertRaises(ProviderFailure) as caught:
                    transport.list_models(config)
            self.assertEqual(caught.exception.code,expected)
            self.assertNotIn("private provider response",str(caught.exception))

        with patch("backend.ai.provider._PinnedHTTPSConnection",Connection):
            Connection.status=402
            with self.assertRaises(ProviderFailure) as chat:
                transport.chat(config,[{"role":"user","content":"Reply with OK."}])
        self.assertEqual(chat.exception.code,"provider_payment_required")
        self.assertNotIn("private provider response",str(chat.exception))

        with patch("backend.ai.provider.socket.getaddrinfo",side_effect=socket.gaierror("private resolver text")):
            with self.assertRaises(ProviderFailure) as dns:
                _resolve_public("vendor.example")
        self.assertEqual(dns.exception.code,"provider_dns_resolution_failed")

    def test_cipher_binds_user_model_revision_and_uses_derived_key(self):
        cipher = ProviderKeyCipher(KEYRING)
        envelope = cipher.encrypt(b"secret",user_id="a",model_id="m",revision="r1",key_id="enc-v1")
        self.assertEqual(cipher.decrypt(envelope,user_id="a",model_id="m",revision="r1"),b"secret")
        for user, model, revision in (("b","m","r1"),("a","other","r1"),("a","m","r2")):
            with self.subTest(user=user,model=model,revision=revision), self.assertRaises(ValueError):
                cipher.decrypt(envelope,user_id=user,model_id=model,revision=revision)
        self.assertNotEqual(cipher._key("enc-v1","a","m"), KEYRING.key("enc-v1"))

    def test_public_dns_mixed_answers_and_pinned_tls_hostname(self):
        from backend.ai.provider import _PinnedHTTPSConnection, _is_public_ip
        self.assertTrue(_is_public_ip('8.8.8.8'))
        self.assertTrue(_is_public_ip('2606:4700:4700::1111'))
        self.assertEqual(validate_base_url('https://[2606:4700:4700::1111]/v1'), 'https://[2606:4700:4700::1111]/v1')
        answers=[(2,1,6,'',('8.8.8.8',443)),(2,1,6,'',('10.0.0.1',443))]
        with patch('backend.ai.provider.socket.getaddrinfo',return_value=answers):
            with self.assertRaises(ProviderFailure):
                _resolve_public('mixed.example')
        from unittest.mock import Mock
        context=Mock();sock=Mock()
        connection=_PinnedHTTPSConnection('vendor.example','8.8.8.8',timeout=3,context=context)
        with patch('backend.ai.provider.socket.create_connection',return_value=sock) as dial:
            connection.connect()
        dial.assert_called_once_with(('8.8.8.8',443),3)
        context.wrap_socket.assert_called_once_with(sock,server_hostname='vendor.example')

    def test_key_retention_destination_change_and_stale_versions(self):
        model=self._create().get_json()['model'];identifier=model['id']
        body={'base_version':1,'name':'Edit','base_url':model['base_url'],'model':'new-model','auth_mode':'bearer'}
        result=self.a.patch('/api/ai/models/'+identifier,json=body,headers=self._headers(self.csrf_a))
        self.assertEqual(result.status_code,200)
        self.assertTrue(result.get_json()['model']['has_api_key'])
        self.assertEqual(self.a.patch('/api/ai/models/'+identifier,json=body,headers=self._headers(self.csrf_a)).status_code,409)
        body['base_version']=2;body['base_url']='https://other.example/v1'
        result=self.a.patch('/api/ai/models/'+identifier,json=body,headers=self._headers(self.csrf_a))
        self.assertEqual((result.status_code,result.get_json()['error']),(409,'provider_key_action_required'))
        body['api_key']='new-destination-synthetic-secret'
        self.assertEqual(self.a.patch('/api/ai/models/'+identifier,json=body,headers=self._headers(self.csrf_a)).status_code,200)
        for method in ('patch','delete'):
            result=getattr(self.b,method)('/api/ai/models/'+identifier,json=body if method=='patch' else {'base_version':3},headers=self._headers(self.csrf_b))
            self.assertEqual(result.status_code,404)
        self.assertEqual(self.b.post('/api/ai/models/'+identifier+'/test',json={},headers=self._headers(self.csrf_b)).status_code,404)

    def test_default_selection_and_cleared_key_never_inherit_service_secret(self):
        from backend.ai.service import AIModelError
        model=self._create().get_json()['model'];identifier=model['id']
        self.service.set_preferences('user-a',None,identifier)
        self.assertEqual(self.service.list_models('user-a')['effective_model_id'],identifier)
        self.assertEqual(self.service.resolve('user-a')[0].api_key,'user-secret-synthetic')
        body={'base_version':1,'name':model['name'],'base_url':model['base_url'],'model':model['model'],'auth_mode':'bearer','delete_api_key':True}
        self.assertEqual(self.a.patch('/api/ai/models/'+identifier,json=body,headers=self._headers(self.csrf_a)).status_code,200)
        with self.assertRaises(AIModelError) as error:
            self.service.chat('user-a',[{'role':'user','content':'hello'}])
        self.assertEqual(error.exception.code,'provider_api_key_required')
        self.assertEqual(self.transport.calls,[])
        self.service.set_preferences('user-a','service_default',None)
        self.assertEqual(self.service.resolve('user-a')[0].api_key,'service-secret-synthetic')
        with patch.object(self.transport,'chat',return_value='Echo: service-secret-synthetic'):
            with self.assertRaises(AIModelError) as echoed:
                self.service.chat('user-a',[{'role':'user','content':'hello'}])
        self.assertEqual(echoed.exception.code,'provider_response_invalid')

    def test_invalid_fields_body_limits_and_failure_reasons_never_echo(self):
        for body in ({'name':[], 'base_url':'https://vendor.example','model':'x','auth_mode':'none'},
                     {'name':'x','base_url':'https://vendor.example','model':'x','auth_mode':{}},
                     {'name':'x','base_url':'https://vendor.example','model':'x','auth_mode':'none','execute':True}):
            self.assertEqual(self.a.post('/api/ai/models',json=body,headers=self._headers(self.csrf_a)).status_code,400)
        for raw in ('{"name":NaN}','{"name":"a","name":"b"}'):
            self.assertEqual(self.a.post('/api/ai/models',data=raw,headers=self._headers(self.csrf_a)).status_code,400)
        self.assertEqual(self.a.post('/api/ai/models',data='x'*16385,headers=self._headers(self.csrf_a)).status_code,413)
        model=self._create().get_json()['model']
        with patch.object(self.transport,'test',side_effect=ProviderFailure('provider_auth_failed')):
            result=self.a.post('/api/ai/models/'+model['id']+'/test',json={},headers=self._headers(self.csrf_a))
        self.assertEqual(result.get_json(),{'ok':False,'error':'provider_auth_failed','status':502})
        self.assertNotIn('user-secret-synthetic',result.get_data(as_text=True))


if __name__ == "__main__": unittest.main()
