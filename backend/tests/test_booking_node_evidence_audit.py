import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from backend.tools.booking_node_evidence_audit import audit_booking_node_capture, main


def request(method, path, *, user_agent='Synthetic official app/1'):
    return (
        f'{method} {path} HTTP/1.1\r\nHost: bdtyg.cugb.edu.cn\r\n'
        f'User-Agent: {user_agent}\r\ntoken: synthetic-token-never-report\r\n\r\n'
    ).encode()


def response(body):
    return f'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{json.dumps(body)}'.encode()


class BookingNodeEvidenceAuditTests(unittest.TestCase):
    def setUp(self):
        self.asset_request = request('GET', '/static/js/pages-custom-home-bookingnode.abc123.js')
        self.asset_response = response({'source': 'irrelevant'})
        self.node_request = request('POST', '/service/appointment/appointment/phone/getBookingNode')
        self.node_response = response({
            'success': True,
            'resultData': [
                {'id': 'private-scope-alpha', 'nodename': 'Private Label Alpha'},
                {'id': 'private-scope-beta', 'nodename': 'Private Label Beta'},
            ],
        })
        self.directory_source = (
            'getBookingNode:function t.links=n.data.resultData t._l(t.links, '
            't._s(e.nodename) goToNotice:function r.id=t.id r.nodename=t.nodename'
        )
        self.booking_source = 'this.param.nodeid=e.id this.nodeid=t.nodeid e.param.nodeid=e.nodeid bookingByTime'

    def test_reports_scope_field_flow_without_publishing_values_or_claiming_a_venue_catalog(self):
        report = audit_booking_node_capture(
            asset_request=self.asset_request, asset_response=self.asset_response,
            node_request=self.node_request, node_response=self.node_response,
            directory_source=self.directory_source, booking_source=self.booking_source,
            asset_sequence=163, node_sequence=166,
        )
        rendered = json.dumps(report)
        self.assertEqual(report['observed_option_count'], 2)
        self.assertEqual(report['field_flow']['selected_item_to_query_scope'], 'confirmed_by_official_source')
        self.assertFalse(report['readiness']['physical_venue_catalog'])
        self.assertFalse(report['readiness']['court_ownership'])
        self.assertFalse(report['readiness']['availability_snapshot'])
        self.assertNotIn('private-scope-alpha', rendered)
        self.assertNotIn('Private Label Alpha', rendered)
        self.assertNotIn('synthetic-token-never-report', rendered)
        self.assertFalse(report['live_request_sent'])

    def test_mismatched_capture_context_or_incomplete_source_fails_without_reflection(self):
        cases = (
            {'node_request': request('POST', '/wrong')},
            {'node_request': request('POST', '/service/appointment/appointment/phone/getBookingNode', user_agent='Other/2')},
            {'node_sequence': 163},
            {'directory_source': 'unrelated source'},
            {'booking_source': 'unrelated source'},
            {'node_response': response({'success': False, 'message': 'private response text', 'resultData': []})},
        )
        for changes in cases:
            args = {
                'asset_request': self.asset_request, 'asset_response': self.asset_response,
                'node_request': self.node_request, 'node_response': self.node_response,
                'directory_source': self.directory_source, 'booking_source': self.booking_source,
                'asset_sequence': 163, 'node_sequence': 166,
            }
            args.update(changes)
            with self.subTest(changed_fields=tuple(changes)):
                with self.assertRaises(ValueError) as failure:
                    audit_booking_node_capture(**args)
                self.assertEqual(str(failure.exception), 'invalid_booking_node_evidence')
                self.assertNotIn('private', str(failure.exception))

    def test_cli_emits_only_sanitized_audit_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {
                'asset_request': root / '[163] request-asset.txt',
                'asset_response': root / '[163] response-asset.txt',
                'node_request': root / '[166] request-node.txt',
                'node_response': root / '[166] response-node.txt',
                'booking_source': root / 'booking-source.js',
            }
            files['asset_request'].write_bytes(self.asset_request)
            files['asset_response'].write_bytes(
                b'HTTP/1.1 200 OK\r\nContent-Type: text/javascript\r\n\r\n'
                + self.directory_source.encode()
            )
            files['node_request'].write_bytes(self.node_request)
            files['node_response'].write_bytes(self.node_response)
            files['booking_source'].write_text(self.booking_source, encoding='utf-8')
            output = io.StringIO()
            with redirect_stdout(output):
                status = main([
                    '--asset-request', str(files['asset_request']),
                    '--asset-response', str(files['asset_response']),
                    '--node-request', str(files['node_request']),
                    '--node-response', str(files['node_response']),
                    '--booking-source', str(files['booking_source']),
                ])
        rendered = output.getvalue()
        self.assertEqual(status, 0)
        self.assertIn('booking_node_scope_flow', rendered)
        self.assertNotIn('private-scope-alpha', rendered)
        self.assertNotIn('Private Label Alpha', rendered)
        self.assertNotIn('synthetic-token-never-report', rendered)
        self.assertNotIn(directory, rendered)


if __name__ == '__main__':
    unittest.main()
