import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from backend.availability_matching.protocol_evidence import (
    CURRENT_EVIDENCE,
    EvidenceManifestError,
    assess_evidence,
    parse_evidence_manifest,
)
from backend.tools.availability_evidence_audit import main


class ProtocolEvidenceTests(unittest.TestCase):
    def test_current_evidence_does_not_publish_a_catalog_or_enable_recorded_data(self):
        report = assess_evidence(CURRENT_EVIDENCE)

        self.assertEqual(report["readiness"], {
            "booking_node_scope_flow": True,
            "venue_directory_display": False,
            "venue_catalog": False,
            "plan_binding": False,
            "recorded_availability": False,
            "price_aware_matching": False,
            "live_read_only_query": False,
        })
        self.assertEqual(report["findings"]["venue_name_to_parent_scope"], "partial")
        self.assertEqual(report["findings"]["venue_list_response"], "missing")

    def test_booking_node_scope_chain_is_separate_from_physical_venue_evidence(self):
        report = assess_evidence(CURRENT_EVIDENCE)
        self.assertTrue(report['readiness']['booking_node_scope_flow'])
        self.assertEqual(report['findings']['booking_node_list_response'], 'confirmed')
        self.assertEqual(report['findings']['selected_booking_node_to_query_scope'], 'confirmed')
        self.assertFalse(report['readiness']['venue_catalog'])
        self.assertIn('physical_venue_label_to_parent_scope', report['blocking_findings']['venue_catalog'])

    def test_read_only_contract_does_not_depend_on_booking_type_semantics(self):
        manifest = {
            "schema_version": 1,
            "findings": {key: "confirmed" for key in CURRENT_EVIDENCE["findings"]},
        }
        manifest["findings"]["appointment_type_semantics"] = "missing"
        manifest["findings"]["booktype_semantics"] = "partial"
        manifest["findings"]["live_query_authorization"] = "missing"

        readiness = assess_evidence(manifest)["readiness"]

        self.assertTrue(readiness["venue_catalog"])
        self.assertTrue(readiness["plan_binding"])
        self.assertTrue(readiness["recorded_availability"])
        self.assertTrue(readiness["price_aware_matching"])
        self.assertFalse(readiness["live_read_only_query"])

    def test_manifest_rejects_unknown_fields_and_statuses_without_reflecting_values(self):
        malformed = json.loads(json.dumps(CURRENT_EVIDENCE))
        malformed["upstream_nodeid"] = "private-value-must-not-be-echoed"
        with self.assertRaises(EvidenceManifestError) as failure:
            parse_evidence_manifest(malformed)
        self.assertNotIn("private-value-must-not-be-echoed", str(failure.exception))

        malformed = json.loads(json.dumps(CURRENT_EVIDENCE))
        malformed["findings"]["availability_status_semantics"] = "probably_available"
        with self.assertRaises(EvidenceManifestError):
            parse_evidence_manifest(malformed)

    def test_offline_cli_emits_only_readiness_and_never_echoes_manifest_path(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "private-local-name.json"
            manifest_path.write_text(json.dumps(CURRENT_EVIDENCE), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = main([str(manifest_path)])

        self.assertEqual(status, 0)
        result = json.loads(stdout.getvalue())
        self.assertFalse(result["readiness"]["venue_catalog"])
        self.assertNotIn("private-local-name", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
