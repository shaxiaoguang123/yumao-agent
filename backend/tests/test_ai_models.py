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
    def chat(self, config, messages):
        self.calls.append((config, messages))
        return "synthetic reply"
    def test(self, config):
        self.calls.append((config, [{"role":"user", "content":"Reply with OK."}]))
        return True


class AIModelTests(unittest.TestCase):
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
        from test_planning import ready
        selected=self._create(name='Selected').get_json()['model']
        tested=self._create(name='Tested').get_json()['model']
        self.service.set_preferences('user-a',selected['id'],None)
        def reply(config,messages):
            self.transport.calls.append((config,messages))
            payload=json.loads(messages[-1]['content'])
            intent=json.loads(ready())['intent']
            intent['target_date']=payload['relative_dates']['下周六']
            return ready(intent,{**json.loads(ready())['evidence'],'duration_minutes':'120分钟','court_preferences':'优先6号场，5号场作为备选'})
        self.transport.chat=reply
        endpoint='/api/ai/models/'+tested['id']+'/test-parsing'
        response=self.a.post(endpoint,json={},headers=self._headers(self.csrf_a))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json()['outcome'],'parsed')
        self.assertEqual(self.transport.calls[-1][0].provider_id,tested['id'])
        self.assertEqual(self.service.list_models('user-a')['selected_model_id'],selected['id'])
        self.assertEqual(self.b.post(endpoint,json={},headers=self._headers(self.csrf_b)).status_code,404)
        self.assertEqual(len(self.transport.calls),1)
        with connect_database(self.path,5000) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM booking_plan_revisions').fetchone()[0],0)
        self.assertEqual(self.app.test_client().post(endpoint,json={},headers=self._headers()).status_code,401)
        self.assertEqual(self.a.post(endpoint,json={},headers=self._headers()).status_code,403)

    def test_parsing_capability_failures_remain_safe(self):
        import json
        from test_planning import ready
        model=self._create().get_json()['model']
        endpoint='/api/ai/models/'+model['id']+'/test-parsing'
        for content in ('raw supplier text', ready(intent={**json.loads(ready())['intent'],'nodeid':'forbidden'})):
            self.transport.chat=lambda *_args: content
            response=self.a.post(endpoint,json={},headers=self._headers(self.csrf_a))
            self.assertEqual((response.status_code,response.get_json()['error']),(502,'invalid_model_proposal'))
            self.assertNotIn('raw supplier',response.get_data(as_text=True))
        self.transport.chat=lambda *_args: json.dumps({'status':'needs_input','intent':None,'questions':['请补充信息。'],'evidence':{}})
        self.assertEqual(self.a.post(endpoint,json={},headers=self._headers(self.csrf_a)).get_json()['outcome'],'needs_input')
        for code in ('provider_auth_failed','provider_access_denied','provider_model_or_endpoint_not_found','provider_rate_limited','provider_timeout','provider_unavailable'):
            def failure(*_args): raise ProviderFailure(code,502)
            self.transport.chat=failure
            self.assertEqual(self.a.post(endpoint,json={},headers=self._headers(self.csrf_a)).get_json()['error'],code)
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
        with patch("backend.ai.provider._PinnedHTTPSConnection", SlowConnection):
            with self.assertRaises(ProviderFailure) as caught:
                transport.chat(ProviderConfig("m","m","https://vendor.example/v1","model","none"), [{"role":"user","content":"x"}])
        self.assertEqual(caught.exception.code,"provider_timeout")
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
