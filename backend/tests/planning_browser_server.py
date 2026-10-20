"""Fresh Flask/SQLite + synthetic model preview; no production configuration is read."""
from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import re
import socket
import time
from contextlib import closing
from pathlib import Path

import requests
from werkzeug.serving import make_server

from backend.app import create_app
from backend.ai.provider import ProviderFailure
from backend.ai.planning import PlanningService
from backend.ai.intent_planning import IntentPlanningService
from backend.ai.service import AIProviderService
from backend.auth.rate_limit import RateLimitDecision
from backend.auth.passwords import hash_password
from backend.credentials.keyring import CredentialKeyring
from backend.credentials.contracts import AdapterValidationResult
from backend.credentials.upstream import BoundedHttpResponse
from backend.db import connect_database
from backend.migrate import migrate_database
from backend.tests.support import credential_test_settings


class SyntheticPlanningTransport:
    """Deterministic test fixture, deliberately not a live model supplier."""
    def __init__(self, root):
        self.root = root
        self.counts = {'calls': 0, 'tests': 0}
        self._record()

    def _record(self):
        (self.root/'model-attempts.json').write_text(json.dumps(self.counts))

    def test(self, config):
        self.counts['tests'] += 1
        self._record()
        if config.model == 'synthetic-failure':
            raise ProviderFailure('provider_unavailable', 502)
        return True

    def chat(self, config, messages):
        self.counts['calls'] += 1
        self._record()
        payload = json.loads(messages[-1]['content'])
        turns = payload.get('user_turns', [payload.get('user_request', '')])
        if '模拟失败' in json.dumps(turns, ensure_ascii=False) or config.model == 'synthetic-failure':
            raise ProviderFailure('provider_unavailable', 502)
        if messages[0]['content'].startswith('你是预约意向草稿助手'):
            intent = dict(payload['current_intent'])
            request = payload['user_request']
            if '4号场' in request:
                intent['court_preferences'] = ['4号场']
                evidence = {'court_preferences': '4号场'}
            else:
                evidence = {}
            return json.dumps({'status': 'ready', 'intent': intent, 'questions': [], 'evidence': evidence}, ensure_ascii=False)
        if '判断用户最新一句是纯问题' in messages[0]['content']:
            return json.dumps({'kind': 'question', 'reply': '两种队列的时间和场地分别确认，互不继承。'}, ensure_ascii=False)
        if config.model == 'synthetic-invalid-json':
            return 'not structured JSON'
        if config.model == 'synthetic-warning':
            return json.dumps({'warnings': ['合成提示：请核对队列里的场地。']}, ensure_ascii=False)
        return json.dumps({'warnings': []})


class SyntheticAICallLimits:
    def __init__(self, delegate):
        self.delegate = delegate

    def check_and_record(self, event_type, buckets, now_utc_ms):
        if event_type == 'ai_call':
            return RateLimitDecision(True, 0)
        return self.delegate.check_and_record(event_type, buckets, now_utc_ms)


class SyntheticCredentialAdapter:
    """Accept only deterministic preview tokens; never contacts the upstream service."""
    def validate_token(self, _token):
        return AdapterValidationResult(
            'success', 'synthetic_preview_credential', b'synthetic-preview-account',
            'getuserinfo-idserial-v1', '2xx', None, 'complete', 200,
        )


class SyntheticAvailabilityTransport:
    """Only local fixture responses; never forwards a request to the upstream."""
    def post_json(self, url, *, headers, json_body):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
        if url.endswith('/getBookingNode'):
            body = {'success': True, 'resultData': [{'id': 'synthetic-badminton', 'nodename': '羽毛球'}]}
        elif url.endswith('/bookingByTime'):
            times = [f'{hour:02d}:00' for hour in range(9, 23)]
            body = {'success': True, 'resultData': {
                'stepnumber': len(times),
                'nodeList': [{'nodeid': f'synthetic-court-{n}', 'sitename': f'{n}号场'} for n in range(1, 11)],
                'timeList': [{'time': t, 'status': '0'} for t in times],
                'conflictList': [], 'priceList': [], 'isNew': False,
                'bookingstartdate': today.isoformat(), 'bookingenddate': (today + timedelta(days=2)).isoformat(),
                'bookingstarttime': '07:30', 'bookingendtime': '22:00',
            }}
        else:
            raise AssertionError('unrecognised synthetic availability route')
        return BoundedHttpResponse(200, json.dumps(body).encode(), None, None, 'complete')


def synthetic_token(marker: str, now_utc_ms: int) -> str:
    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')
    header = encode(b'{"alg":"none","typ":"JWT"}')
    payload = encode(json.dumps({'exp': now_utc_ms // 1000 + 30 * 86_400, 'marker': marker}).encode())
    return f'{header}.{payload}.synthetic-signature'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--origin',required=True)
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--simulation',action='store_true',help='explicitly enable synthetic availability matching')
    args = parser.parse_args()
    root = Path(args.output).resolve()
    if root.exists():
        if not root.is_dir() or any(root.iterdir()):
            raise RuntimeError('synthetic preview requires a fresh empty directory')
    else:
        root.mkdir(parents=True)
    database = root/'synthetic-planning.sqlite3'
    counts = {'http_attempts':0,'external_socket_attempts':0}
    def record():
        (root/'upstream-attempts.json').write_text(json.dumps(counts))
    def deny_http(*_args,**_kwargs):
        counts['http_attempts'] += 1; record()
        raise RuntimeError('Real HTTP disabled in synthetic planning preview')
    connect = socket.socket.connect
    def loopback_connect(sock,address):
        if isinstance(address,tuple) and not ipaddress.ip_address(address[0]).is_loopback:
            counts['external_socket_attempts'] += 1; record()
            raise RuntimeError('External socket disabled in synthetic planning preview')
        return connect(sock,address)
    requests.sessions.Session.request = deny_http
    socket.socket.connect = loopback_connect
    record()
    migrate_database(database,5000)
    app = create_app({**credential_test_settings(database),'APP_ENV':'development','APP_ALLOWED_ORIGINS':args.origin,
                      'SESSION_COOKIE_NAME':'yumao_planning_qa_session',
                      'UPSTREAM_GET_USER_INFO_MIN_INTERVAL_MS':'10',
                      'LIVE_AVAILABILITY_ENABLED':'true',
                      'UPSTREAM_ITEM_AES_KEY_ASCII':'0123456789abcdef', 'UPSTREAM_ITEM_AES_IV_ASCII':'abcdef0123456789',
                      'AVAILABILITY_SIMULATION_ENABLED':'true' if args.simulation else 'false',
                      'BOOKING_TIMEZONE':'Asia/Shanghai','BOOKING_CURRENCY_CODE':'CNY','BOOKING_CURRENCY_MINOR_UNIT_EXPONENT':'2'})
    # This synthetic browser workflow exceeds the production call burst by design.
    app.extensions['ai_call_guard'].rate_limits = SyntheticAICallLimits(app.extensions['rate_limit_service'])
    settings = app.extensions['app_settings']
    app.extensions['live_availability_service']._transport = SyntheticAvailabilityTransport()
    provider = AIProviderService(database_path=database,busy_timeout_ms=5000,
        keyring=CredentialKeyring(settings.credential_encryption_keys,settings.credential_encryption_active_key_id),
        transport=SyntheticPlanningTransport(root),destination_validator=lambda _url: None)
    app.extensions['ai_provider_service'] = provider
    app.extensions['planning_service'] = PlanningService(app.extensions['plan_service'],provider)
    app.extensions['intent_planning_service'] = IntentPlanningService(app.extensions['plan_service'],provider)
    with closing(connect_database(database,5000)) as db:
        now = time.time_ns()//1_000_000
        password = hash_password('Synthetic-only-password-42')
        for suffix in ('a','b'):
            user = 'synthetic-planning-'+suffix
            name = 'plan_user_'+suffix
            db.execute('INSERT INTO users(user_id,username,normalized_username,password_hash,role,status,created_at_utc_ms,updated_at_utc_ms) VALUES(?,?,?,?,?,?,?,?)', (user,name,name,password,'user','active',now,now))
    for suffix, name in (('a', 'A 会话检查模型'), ('b', 'B 合成模型')):
        provider.create(
            f'synthetic-planning-{suffix}', name, 'https://model.example/v1',
            f'synthetic-planner-{suffix}', 'none',
        )
    credential_service = app.extensions['credential_service']
    credential_service.adapter = SyntheticCredentialAdapter()
    for index, suffix in enumerate(('a','b')):
        if index:
            time.sleep(0.025)
        credential_now = time.time_ns() // 1_000_000
        credential_service.create(
            f'synthetic-planning-{suffix}', 'Synthetic planning credential',
            synthetic_token(suffix, credential_now), credential_now, 'Synthetic-only-payment-password',
        )
    server = make_server('127.0.0.1',args.port,app,threaded=True)
    manifest = {'origin':f'http://127.0.0.1:{server.server_port}','database_path':str(database),
                'users':['plan_user_a','plan_user_b'],'provider':'synthetic Fake Provider; NOT real supplier verification',
                'isolation':'fresh synthetic DB; all external HTTP and sockets blocked'}
    (root/'server.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps(manifest),flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
