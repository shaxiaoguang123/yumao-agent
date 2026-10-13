from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from backend.app import create_app
from backend.availability_matching.live_observation import OfficialBookingByTimeObservationAdapter
from backend.availability_matching.models import AvailabilityError
from backend.credentials.contracts import AdapterValidationResult
from backend.credentials.upstream import BoundedHttpResponse
from backend.db import connect_database
from backend.migrate import migrate_database
from support import credential_test_settings


ORIGIN = 'http://localhost:5173'
OBSERVED_NOW = int(datetime(2026, 10, 13, 12, tzinfo=timezone.utc).timestamp() * 1000)


def envelope():
    return {'success': True, 'resultData': {
        'stepnumber': 2,
        'nodeList': [{'nodeid': 'fixture-court-private', 'sitename': '测试一号场'},
                     {'nodeid': 'fixture-court-two', 'sitename': '测试二号场'}],
        'timeList': [{'time': '18:00', 'status': '0'}, {'time': '19:00', 'status': '0'}],
        'conflictList': ['0-0', '0-0', '1-0-3', '0-1-7'],
        'priceList': [{'x': '0', 'y': '0', 'price': 'fixture-unverified-price'}],
        'isNew': True, 'bookingstartdate': '2026-10-13', 'bookingenddate': '2026-10-15',
        'bookingstarttime': '00:00', 'bookingendtime': '23:59',
        'mintimeselect': '1', 'maxtimeselect': '4', 'maxAppointmentNodeNum': '2',
    }}


class FakeValidation:
    def validate_token(self, _token):
        return AdapterValidationResult('success', 'get_user_info_success', b'fixture-account',
                                       'getuserinfo-idserial-v1', '2xx', None, 'complete', 200)


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.failure = None

    def post_json(self, url, *, headers, json_body):
        self.calls.append(url.rsplit('/', 1)[-1])
        if self.failure:
            raise RuntimeError('fixture transport exception')
        body = {'success': True, 'resultData': [{'id': 'fixture-query-private', 'nodename': '羽毛球'}]} \
            if url.endswith('getBookingNode') else envelope()
        return BoundedHttpResponse(200, json.dumps(body).encode(), None, None, 'complete')


class LiveObservationAdapterTests(unittest.TestCase):
    def adapt(self, body):
        return OfficialBookingByTimeObservationAdapter().adapt(
            body, target_date='2026-10-15', timezone_name='Asia/Shanghai',
            query_scope_label='羽毛球', captured_at_utc_ms=OBSERVED_NOW)

    def test_projection_is_read_only_and_omits_private_ids_and_prices(self):
        result = self.adapt(envelope())
        self.assertEqual(result['data_state'], 'live_observed_unverified')
        self.assertEqual(result['diagnostics']['duplicate_conflict_count'], 1)
        self.assertEqual([cell['state'] for cell in result['rows'][0]['cells']],
                         ['observed_reserved', 'observed_activity_occupied'])
        self.assertEqual(result['rows'][1]['cells'][0]['state'], 'observed_unbookable')
        self.assertEqual(result['rows'][1]['cells'][1]['state'], 'observed_clear_unmarked')
        self.assertFalse(result['can_match'])
        self.assertFalse(result['can_select'])
        self.assertNotIn('fixture-court-private', json.dumps(result))
        self.assertNotIn('fixture-unverified-price', json.dumps(result))

    def test_unknown_row_and_conflicting_duplicates_never_become_clear(self):
        body = envelope()
        body['resultData']['timeList'][1]['status'] = 'future-code'
        body['resultData']['conflictList'] += ['0-0-2', '1-1-99']
        result = self.adapt(body)
        self.assertEqual(result['rows'][0]['cells'][0]['state'], 'observed_unknown')
        self.assertEqual(result['rows'][1]['cells'][1]['state'], 'observed_unknown')
        body['resultData']['conflictList'] = []
        result = self.adapt(body)
        self.assertTrue(all(cell['state'] == 'observed_unknown' for cell in result['rows'][1]['cells']))

    def test_intent_selectability_is_separate_from_inventory_and_uses_observed_boundaries(self):
        body = envelope()
        body['resultData']['conflictList'] = ['1-0-3']
        result = self.adapt(body)
        self.assertTrue(result['can_select_intent'])
        self.assertFalse(result['can_select'])
        self.assertTrue(result['rows'][0]['cells'][0]['intent_selectable'])
        self.assertFalse(result['rows'][0]['cells'][1]['intent_selectable'])
        self.assertEqual(result['rows'][0]['cells'][1]['activity_type'], 3)
        self.assertEqual(result['rows'][0]['intent_end_time'], '19:00')
        self.assertFalse(result['rows'][1]['cells'][0]['intent_selectable'])
        self.assertEqual(result['source']['time_atom_state'], 'unknown')

    def test_official_booking_window_closed_or_unknown_never_enables_selection(self):
        body = envelope()
        body['resultData']['bookingendtime'] = '19:00'
        result = self.adapt(body)  # observed clock is 20:00 in Shanghai
        self.assertEqual(result['client_selection_window'], 'closed')
        self.assertTrue(all(not cell['intent_selectable'] for row in result['rows'] for cell in row['cells']))
        body['resultData'].pop('isNew')
        result = self.adapt(body)
        self.assertEqual(result['client_selection_window'], 'unknown')
        self.assertTrue(all(not cell['intent_selectable'] for row in result['rows'] for cell in row['cells']))

    def test_invalid_structure_and_out_of_range_conflicts_are_rejected(self):
        for mutate in (lambda data: data.update(stepnumber=3),
                       lambda data: data.update(conflictList=['99-0']),
                       lambda data: data.update(nodeList=[])):
            body = envelope()
            mutate(body['resultData'])
            with self.assertRaises(AvailabilityError):
                self.adapt(body)

    def test_official_terminal_row_does_not_render_as_clear_inventory(self):
        body = envelope()
        body['resultData']['timeList'][1]['status'] = '1'
        result = self.adapt(body)
        self.assertFalse(result['rows'][1]['client_displays_cells'])
        self.assertTrue(all(cell['state'] == 'observed_unknown' for cell in result['rows'][1]['cells']))


class LiveAvailabilityApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='yumao-live-tests-')
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'test.sqlite3'
        migrate_database(self.database, 5000)
        self.config = {**credential_test_settings(self.database), 'APP_ENV': 'development',
                       'APP_ALLOWED_ORIGINS': ORIGIN, 'LIVE_AVAILABILITY_ENABLED': 'true',
                       'UPSTREAM_ITEM_AES_KEY_ASCII': '0123456789abcdef',
                       'UPSTREAM_ITEM_AES_IV_ASCII': 'abcdef0123456789', 'TESTING': True}
        self.app = create_app(self.config)
        self.credentials = self.app.extensions['credential_service']
        self.credentials.adapter = FakeValidation()
        self.gate = self.app.extensions['upstream_request_gate']
        self.gate.minimum_interval_ms = 1
        self.service = self.app.extensions['live_availability_service']
        self.service._clock = lambda: OBSERVED_NOW
        self.transport = FakeTransport()
        self.service._transport = self.transport
        now = time.time_ns() // 1_000_000
        with closing(connect_database(self.database, 5000)) as connection:
            for user in ('user-a', 'user-b'):
                connection.execute("INSERT INTO users (user_id,username,normalized_username,password_hash,role,status,created_at_utc_ms,updated_at_utc_ms) VALUES (?,?,?,'fixture','user','active',?,?)", (user, user, user, now, now))
        encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b'=').decode()
        token = encode(b'{"alg":"none"}') + '.' + encode(json.dumps({'exp': now // 1000 + 86400}).encode()) + '.fixture'
        self.credential = self.credentials.create('user-a', '测试凭据', token, now)
        self.clear_spacing()
        self.client = self.app.test_client()
        self.session_id, self.csrf = self.app.extensions['session_service'].create('user-a', now)
        self.client.set_cookie('yumao_session', self.session_id)

    def clear_spacing(self):
        with closing(connect_database(self.database, 5000)) as connection:
            connection.execute("UPDATE upstream_request_gate SET next_allowed_at_utc_ms=NULL,upstream_backoff_until_utc_ms=NULL WHERE endpoint_key='getUserInfo'")

    def post(self, path, body):
        return self.client.post('/api/availability/live/' + path, json=body,
                                headers={'Origin': ORIGIN, 'X-CSRF-Token': self.csrf})

    def categories(self):
        response = self.post('categories', {'credential_id': self.credential.credential_id})
        self.assertEqual(response.status_code, 200)
        return response.get_json()['options'][0]['reference']

    def test_full_read_only_chain_and_no_plan_revision_writes(self):
        reference = self.categories()
        self.clear_spacing()
        response = self.post('grid', {'credential_id': self.credential.credential_id,
                             'scope_reference': reference, 'target_date': '2026-10-15'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.transport.calls, ['getBookingNode', 'bookingByTime'])
        self.assertNotIn('fixture-query-private', response.get_data(as_text=True))
        self.assertFalse(response.get_json()['can_book'])
        with closing(connect_database(self.database, 5000)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM booking_plan_revisions').fetchone()[0], 0)
            self.assertIsNone(connection.execute('SELECT lease_owner_id FROM upstream_request_gate').fetchone()[0])

    def test_session_csrf_owner_and_scope_checks_prevent_network_calls(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get('/api/availability/live/options').status_code, 401)
        self.assertEqual(self.client.post('/api/availability/live/categories', json={'credential_id': self.credential.credential_id}).status_code, 403)
        reference = self.categories()
        now = time.time_ns() // 1_000_000
        session_b, csrf_b = self.app.extensions['session_service'].create('user-b', now)
        self.client.set_cookie('yumao_session', session_b)
        self.csrf = csrf_b
        self.clear_spacing()
        response = self.post('categories', {'credential_id': self.credential.credential_id})
        self.assertEqual(response.status_code, 409)
        response = self.post('grid', {'credential_id': self.credential.credential_id, 'scope_reference': reference, 'target_date': '2026-10-15'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.transport.calls, ['getBookingNode'])

    def test_window_and_arbitrary_scope_rejected_before_network(self):
        reference = self.categories()
        for target, scope, expected in [('2026-11-15', reference, 422), ('2026-10-15', 'x' * 32, 409)]:
            response = self.post('grid', {'credential_id': self.credential.credential_id, 'scope_reference': scope, 'target_date': target})
            self.assertEqual(response.status_code, expected)
        self.assertEqual(self.transport.calls, ['getBookingNode'])

    def test_transport_exception_releases_lease_and_does_not_change_validation(self):
        self.transport.failure = True
        response = self.post('categories', {'credential_id': self.credential.credential_id})
        self.assertEqual(response.status_code, 502)
        with closing(connect_database(self.database, 5000)) as connection:
            self.assertIsNone(connection.execute('SELECT lease_owner_id FROM upstream_request_gate').fetchone()[0])
            self.assertEqual(connection.execute('SELECT last_confirmed_validation_state FROM credentials').fetchone()[0], 'confirmed_valid')

    def test_rate_limit_and_production_disable(self):
        self.gate.minimum_interval_ms = 60000
        self.categories()
        response = self.post('categories', {'credential_id': self.credential.credential_id})
        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response.headers)
        production = create_app({**self.config, 'APP_ENV': 'production'})
        self.assertFalse(production.extensions['live_availability_service'].options()['enabled'])


if __name__ == '__main__':
    unittest.main()
