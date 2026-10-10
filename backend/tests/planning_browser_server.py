"""Fresh Flask/SQLite + synthetic model preview; no production configuration is read."""
from __future__ import annotations

import argparse
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
from backend.ai.service import AIProviderService
from backend.auth.passwords import hash_password
from backend.credentials.keyring import CredentialKeyring
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
        message = payload['user_request']
        if '模拟失败' in message or config.model == 'synthetic-failure':
            raise ProviderFailure('provider_unavailable', 502)
        if config.model == 'synthetic-invalid-json':
            return 'not structured JSON'
        if config.model == 'synthetic-needs-input':
            return json.dumps({'status':'needs_input','intent':None,'evidence':{},'questions':['请补充信息。']}, ensure_ascii=False)
        before = payload['current_intent']
        evidence = {}
        if before is None:
            if '东区体育馆' not in message:
                return json.dumps({'status':'needs_input','intent':None,'evidence':{},'questions':['请补充场馆名称或描述。']}, ensure_ascii=False)
            target = re.search(r'\d{4}-\d{2}-\d{2}', message)
            clock = re.search(r'\d{2}:\d{2}', message)
            if (not target and '下周六' not in message) or not clock or not any(word in message for word in ('两个小时','两小时','2小时','120分钟')):
                return json.dumps({'status':'needs_input','intent':None,'evidence':{},'questions':['请补充日期、开始时间和预约时长。']}, ensure_ascii=False)
            date_quote = target[0] if target else '下周六'
            if '6号场' not in message and '5号场' not in message:
                return json.dumps({'status':'needs_input','intent':None,'evidence':{},'questions':['请补充场地偏好或同场馆备用意愿。']}, ensure_ascii=False)
            duration_quote = next(word for word in ('两个小时','两小时','2小时','120分钟') if word in message)
            intent = {'target_date':target[0] if target else payload['relative_dates']['下周六'],
                'preferred_start_times':[clock[0]], 'duration_minutes':120, 'venue_preference':'东区体育馆',
                'court_preferences':[court for court in ('6号场','5号场') if court in message], 'fallback_policy':{
                    'allow_any_court_in_venue':False,'allow_time_shift':False,'allowed_start_time_range':None},
                'price_ceiling_minor':None}
            evidence = {'target_date':date_quote,'preferred_start_times':clock[0],'duration_minutes':duration_quote,
                        'venue_preference':'东区体育馆','court_preferences':next((t for t in payload.get('user_turns',[message]) if '号场' in t), message)}
        else:
            intent = json.loads(json.dumps(before))
            clock = re.search(r'\d{2}:\d{2}', message)
            if not clock and '开始时间' in message:
                return json.dumps({'status':'needs_input','intent':None,'evidence':{},'questions':['希望改为几点开始？']}, ensure_ascii=False)
            if clock:
                intent['preferred_start_times'] = [clock[0]]
                evidence['preferred_start_times'] = clock[0]
            if '5号场' in message and ('第一' in message or '优先' in message):
                intent['court_preferences'] = sorted(intent['court_preferences'], key=lambda value: 0 if '5号场' in value else 1)
                evidence['court_preferences'] = next((t for t in payload.get('user_turns',[message]) if '5号场' in t), message)
        return json.dumps({'status':'ready','intent':intent,'questions':[],'evidence':evidence}, ensure_ascii=False)


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
                      'AVAILABILITY_SIMULATION_ENABLED':'true' if args.simulation else 'false',
                      'BOOKING_TIMEZONE':'Asia/Shanghai','BOOKING_CURRENCY_CODE':'CNY','BOOKING_CURRENCY_MINOR_UNIT_EXPONENT':'2'})
    settings = app.extensions['app_settings']
    provider = AIProviderService(database_path=database,busy_timeout_ms=5000,
        keyring=CredentialKeyring(settings.credential_encryption_keys,settings.credential_encryption_active_key_id),
        transport=SyntheticPlanningTransport(root),destination_validator=lambda _url: None)
    app.extensions['ai_provider_service'] = provider
    app.extensions['planning_service'] = PlanningService(app.extensions['plan_service'],provider)
    with closing(connect_database(database,5000)) as db:
        now = time.time_ns()//1_000_000
        password = hash_password('Synthetic-only-password-42')
        for suffix in ('a','b'):
            user = 'synthetic-planning-'+suffix
            name = 'plan_user_'+suffix
            db.execute('INSERT INTO users(user_id,username,normalized_username,password_hash,role,status,created_at_utc_ms,updated_at_utc_ms) VALUES(?,?,?,?,?,?,?,?)', (user,name,name,password,'user','active',now,now))
    server = make_server('127.0.0.1',args.port,app,threaded=True)
    manifest = {'origin':f'http://127.0.0.1:{server.server_port}','database_path':str(database),
                'users':['plan_user_a','plan_user_b'],'provider':'synthetic Fake Provider; NOT real supplier verification',
                'isolation':'fresh synthetic DB; all external HTTP and sockets blocked'}
    (root/'server.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps(manifest),flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
