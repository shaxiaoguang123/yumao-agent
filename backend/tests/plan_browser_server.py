"""Loopback-only synthetic preview for real browser tests. Never accepts a DB path."""
from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import time
from contextlib import closing
from pathlib import Path

import requests
from werkzeug.serving import make_server

from backend.app import create_app
from backend.auth.passwords import hash_password
from backend.db import connect_database
from backend.migrate import migrate_database
from backend.tests.support import credential_test_settings

PASSWORD = 'Synthetic-only-password-42'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    root = Path(args.output).resolve()
    # A fresh output directory and a hardcoded filename prevent production DB reuse.
    if root.exists():
        if not root.is_dir() or any(root.iterdir()):
            raise RuntimeError("synthetic browser output must be a fresh empty directory")
    else:
        root.mkdir(parents=True)
    database_path = root / 'synthetic-plans.sqlite3'
    attempts = {'http_attempts': 0, 'external_socket_attempts': 0}
    def record():
        (root/'upstream-attempts.json').write_text(json.dumps(attempts))
    def denied_request(*_args, **_kwargs):
        attempts['http_attempts'] += 1
        record()
        raise RuntimeError('Upstream transport is disabled in isolated browser tests')
    original_connect = socket.socket.connect
    def loopback_connect(sock, address):
        if isinstance(address, tuple) and not ipaddress.ip_address(address[0]).is_loopback:
            attempts['external_socket_attempts'] += 1
            record()
            raise RuntimeError('External sockets are disabled in isolated browser tests')
        return original_connect(sock, address)
    requests.sessions.Session.request = denied_request
    socket.socket.connect = loopback_connect
    record()
    migrate_database(database_path,5000)
    config = {**credential_test_settings(database_path), 'APP_ENV':'development', 'APP_ALLOWED_ORIGINS':args.origin,
              'BOOKING_TIMEZONE':'Asia/Shanghai', 'BOOKING_CURRENCY_CODE':'CNY', 'BOOKING_CURRENCY_MINOR_UNIT_EXPONENT':'2'}
    app = create_app(config)
    now = time.time_ns() // 1_000_000
    with closing(connect_database(database_path,5000)) as db:
        password_hash = hash_password(PASSWORD)
        for suffix in ('a','b'):
            user = f'synthetic-user-{suffix}'
            db.execute('INSERT INTO users (user_id,username,normalized_username,password_hash,role,status,created_at_utc_ms,updated_at_utc_ms) VALUES (?,?,?,?,?,?,?,?)', (user,f'plan_user_{suffix}',f'plan_user_{suffix}',password_hash,'user','active',now,now))
    server = make_server('127.0.0.1',args.port,app,threaded=True)
    manifest = {'origin':f'http://127.0.0.1:{server.server_port}','database_path':str(database_path),
                'users':['plan_user_a','plan_user_b'],'isolation':'fresh synthetic DB; HTTP and external sockets denied'}
    (root/'server.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps(manifest),flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
