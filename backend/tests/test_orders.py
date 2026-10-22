import base64
import json
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from backend.app import create_app
from backend.credentials.contracts import AdapterValidationResult
from backend.credentials.upstream import BoundedHttpResponse
from backend.db import connect_database
from backend.migrate import migrate_database
from backend.orders.status import ORDER_STATUSES, order_is_confirmed, order_status
from support import credential_test_settings


KEY, IV = '0123456789abcdef', 'abcdef0123456789'
ORIGIN = 'http://localhost:5173'


class Validation:
    def validate_token(self, token):
        return AdapterValidationResult('success', 'get_user_info_success', token.encode(),
                                       'getuserinfo-idserial-v1', '2xx', None, 'complete', 200)


class OrderTransport:
    def __init__(self):
        self.calls, self.status, self.http_status = [], '5', 200
        self.success, self.invalid, self.wrong_order = True, False, False

    def post_json(self, url, *, headers, json_body):
        path = url.rsplit('/', 1)[1]
        assert path in {'payOrderForPhone', 'payOrderDetails'}, 'orders must remain read-only'
        payload = json.loads(unpad(AES.new(KEY.encode(), AES.MODE_CBC, IV.encode()).decrypt(bytes.fromhex(json_body['item'])), 16))
        self.calls.append((path, payload))
        item = {'orderno': 'order-a', 'bookingno': 'booking-a', 'id': 'id-a',
                'appointmentdate': '2026-10-24', 'bookingtime': '2026-10-24 09:00-10:00',
                'nodename': '羽毛球1号场', 'status': self.status, 'txamt': '4000', 'totaltxamt': '4000',
                'paytime': '2026-10-22 12:36:00', 'username': 'private-name', 'idserial': 'private-id',
                'payphone': 'private-phone', 'qrcode': 'private-qr'}
        if path == 'payOrderForPhone':
            content = [] if payload.get('status') and payload['status'] != self.status else [item]
            data = {'content': content, 'number': str(payload['pageNumber'] - 1),
                    'size': str(payload['pageSize']), 'totalElements': str(len(content)), 'totalPages': '1' if content else '0'}
            if self.invalid:
                data['size'] = True
        else:
            data = {**item, 'payallamt': '4000', 'expirationTime': '2026-10-24 10:00'}
            if self.wrong_order:
                data['bookingno'] = 'different-order'
        return BoundedHttpResponse(self.http_status, json.dumps({'success': self.success, 'resultData': data}).encode(), None, None, 'complete')


class OrderStatusTests(unittest.TestCase):
    def test_statuses_and_confirmation_never_trust_paytime(self):
        self.assertEqual(len(ORDER_STATUSES), 15)
        for code in ORDER_STATUSES:
            with self.subTest(code=code):
                self.assertEqual(order_status(code), code)
                self.assertEqual(order_is_confirmed({'status': code, 'paytime': '2026-10-22 12:36:00'}), code in {'1', '4', '6', '8'})
        for code in (True, None, '99', 1.0, {}, 'paid'):
            self.assertEqual(order_status(code), '')
            self.assertFalse(order_is_confirmed({'status': code, 'paytime': 'not-empty'}))


class OrderApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='order-api-')
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'test.sqlite3'
        migrate_database(self.database, 5000)
        self.app = create_app({**credential_test_settings(self.database), 'TESTING': True,
                               'APP_ALLOWED_ORIGINS': ORIGIN,
                               'UPSTREAM_ITEM_AES_KEY_ASCII': KEY, 'UPSTREAM_ITEM_AES_IV_ASCII': IV})
        self.credentials = self.app.extensions['credential_service']
        self.credentials.adapter = Validation()
        self.credentials.gate.minimum_interval_ms = 1
        now = time.time_ns() // 1_000_000
        with closing(connect_database(self.database, 5000)) as db:
            for uid in ('user-a', 'user-b'):
                db.execute("INSERT INTO users (user_id,username,normalized_username,password_hash,role,status,created_at_utc_ms,updated_at_utc_ms) VALUES (?,?,?,'fixture','user','active',?,?)", (uid, uid, uid, now, now))
        def token(marker):
            encode = lambda data: base64.urlsafe_b64encode(data).rstrip(b'=').decode()
            return encode(b'{"alg":"none"}') + '.' + encode(json.dumps({'exp': now // 1000 + 86400, 'marker': marker}).encode()) + '.fixture'
        self.a = self.credentials.create('user-a', 'A', token('a'), now)
        self.clear_gate()
        self.b = self.credentials.create('user-b', 'B', token('b'), now)
        self.clear_gate()
        self.other = self.credentials.create('user-a', 'Other', token('other'), now)
        self.clear_gate()
        self.client = self.app.test_client()
        self.session_id, self.csrf = self.app.extensions['session_service'].create('user-a', now)
        self.client.set_cookie('yumao_session', self.session_id)
        self.transport = OrderTransport()
        self.app.extensions['booking_execution_protocol'].transport = self.transport

    def clear_gate(self):
        with closing(connect_database(self.database, 5000)) as db:
            db.execute("UPDATE upstream_request_gate SET next_allowed_at_utc_ms=NULL,upstream_backoff_until_utc_ms=NULL")

    def post(self, route='query', **body):
        self.clear_gate()
        return self.client.post('/api/orders/' + route, json={'credential_id': self.a.credential_id, **body}, headers={'Origin': ORIGIN, 'X-CSRF-Token': self.csrf})

    def reference(self):
        response = self.post()
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()['orders'][0]['reference']

    def test_lists_and_details_without_payment_password_and_never_leaks_raw_upstream_fields(self):
        self.assertFalse(self.a.has_payment_password)
        response = self.post()
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual((result['orders'][0]['amount_display'], result['orders'][0]['status_label']), ('40.00', '待支付'))
        self.assertEqual((result['total'], result['page'], result['page_size']), (1, 1, 10))
        self.assertEqual(len(result['status_options']), 15)
        self.assertFalse(result['orders'][0]['reservation_confirmed'])
        self.assertIsNone(result['orders'][0]['paid_at'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        detail = self.post('details', reference=result['orders'][0]['reference'])
        self.assertEqual(detail.status_code, 200, detail.get_json())
        self.assertEqual(detail.get_json()['order']['status'], '5')
        self.assertIsNone(detail.get_json()['order']['paid_at'])
        for forbidden in ('private-name', 'private-phone', 'private-qr', 'private-id', 'idserial', 'qrcode'):
            self.assertNotIn(forbidden, response.get_data(as_text=True) + detail.get_data(as_text=True))
        self.assertEqual([path for path, _ in self.transport.calls], ['payOrderForPhone', 'payOrderDetails'])
        with closing(connect_database(self.database, 5000)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM booking_execution_runs').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM booking_plan_revisions').fetchone()[0], 0)

    def test_pagination_and_status_filter_are_sent_to_official_endpoint(self):
        response = self.post(page=2, page_size=3, status='4')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.transport.calls[-1][1], {'pageNumber': 2, 'pageSize': 3, 'ordertype': 1, 'status': '4'})
        self.assertEqual(response.get_json()['orders'], [])

    def test_auth_csrf_and_foreign_credentials_stop_before_upstream(self):
        self.assertEqual(self.app.test_client().post('/api/orders/query', json={'credential_id': self.a.credential_id}, headers={'Origin': ORIGIN}).status_code, 401)
        self.assertEqual(self.client.post('/api/orders/query', json={'credential_id': self.a.credential_id}, headers={'Origin': ORIGIN}).status_code, 403)
        self.assertEqual(self.post(credential_id=self.b.credential_id).status_code, 404)
        self.assertEqual(self.transport.calls, [])

    def test_references_are_bound_to_session_owner_token_and_revision(self):
        reference = self.reference()
        count = len(self.transport.calls)
        for cid, ref in ((self.other.credential_id, reference), (self.a.credential_id, reference + '-tampered')):
            self.assertEqual(self.post('details', credential_id=cid, reference=ref).status_code, 404)
        session, self.csrf = self.app.extensions['session_service'].create('user-a', time.time_ns() // 1_000_000)
        self.client.set_cookie('yumao_session', session)
        self.assertEqual(self.post('details', reference=reference).status_code, 404)
        self.assertEqual(len(self.transport.calls), count)

    def test_expired_reference_cannot_be_replayed(self):
        with patch('itsdangerous.timed.TimestampSigner.get_timestamp', return_value=1):
            reference = self.reference()
        self.assertEqual(self.post('details', reference=reference).get_json()['error'], 'order_reference_expired')
        self.assertEqual(len(self.transport.calls), 1)

    def test_disabled_or_changed_credential_blocks_details(self):
        reference = self.reference()
        with closing(connect_database(self.database, 5000)) as db:
            db.execute('UPDATE credentials SET credential_version=credential_version+1 WHERE credential_id=?', (self.a.credential_id,))
        self.assertEqual(self.post('details', reference=reference).status_code, 404)
        self.assertEqual(len(self.transport.calls), 1)
        self.credentials.set_enabled('user-a', self.a.credential_id, self.a.credential_version + 1, False, time.time_ns() // 1_000_000)
        self.assertEqual(self.post().status_code, 422)

    def test_invalid_inputs_and_raw_detail_ids_are_rejected_without_calls(self):
        for body in ({'page': True}, {'page': 0}, {'page': 10001}, {'page_size': 51}, {'page_size': '10'}, {'status': '99'}, {'status': 5}, {'token': 'forbidden'}):
            self.assertEqual(self.post(**body).status_code, 400)
        self.assertEqual(self.post('details', bookingno='guess', id='guess').status_code, 400)
        self.assertEqual(self.transport.calls, [])

    def test_rate_limit_is_returned_without_sleep_or_extra_dispatch(self):
        self.credentials.gate.minimum_interval_ms = 5000
        self.assertEqual(self.post().status_code, 200)
        with patch('backend.execution.protocol.time.sleep') as sleep:
            response = self.client.post('/api/orders/query', json={'credential_id': self.a.credential_id}, headers={'Origin': ORIGIN, 'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.get_json()['error'], 'order_query_rate_limited')
        self.assertIn('Retry-After', response.headers)
        sleep.assert_not_called()
        self.assertEqual(len(self.transport.calls), 1)

    def test_upstream_401_does_not_become_an_application_session_401(self):
        self.transport.http_status = 401
        response = self.post()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()['error'], 'order_upstream_authentication_failed')
        self.assertEqual(self.client.get('/api/auth/session').status_code, 200)

    def test_invalid_envelope_pagination_or_wrong_detail_never_reports_success(self):
        self.transport.success = False
        self.assertEqual(self.post().status_code, 502)
        self.transport.success, self.transport.invalid = True, True
        self.assertEqual(self.post().status_code, 502)
        self.transport.invalid = False
        reference = self.reference()
        self.transport.wrong_order = True
        self.assertEqual(self.post('details', reference=reference).status_code, 502)

    def test_unknown_status_is_displayed_without_confirming_reservation(self):
        self.transport.status = '99'
        item = self.post().get_json()['orders'][0]
        self.assertEqual((item['status_label'], item['reservation_confirmed']), ('未知状态', False))


if __name__ == '__main__':
    unittest.main()
