import json
import unittest

from backend.venue_catalog import (
    CatalogCourt,
    CatalogError,
    CatalogVenue,
    VenueCatalog,
    VenueCatalogService,
)
from backend.availability_matching.protocol_evidence import CURRENT_EVIDENCE


def verified_manifest():
    manifest = json.loads(json.dumps(CURRENT_EVIDENCE))
    for key in manifest["findings"]:
        manifest["findings"][key] = "confirmed"
    manifest["findings"]["appointment_type_semantics"] = "missing"
    manifest["findings"]["booktype_semantics"] = "partial"
    manifest["findings"]["live_query_authorization"] = "missing"
    return manifest


def display_only_manifest():
    manifest = json.loads(json.dumps(CURRENT_EVIDENCE))
    manifest["findings"]["client_version_association"] = "confirmed"
    manifest["findings"]["venue_list_response"] = "confirmed"
    manifest["findings"]["venue_name_to_parent_scope"] = "partial"
    return manifest


def test_catalog():
    return VenueCatalog(
        version="catalog-test-v1",
        source_client_build="synthetic-test-build",
        evidence_ref="test-only-evidence",
        evidence_manifest=verified_manifest(),
        venues=(CatalogVenue(
            venue_key="test-east",
            display_name="测试东区场馆",
            scope_config_key="VENUE_SCOPE_TEST_ONLY",
            evidence_ref="test-only-venue-evidence",
            courts=(CatalogCourt("court-6", "6号场", "test-only-court-evidence"),),
        ),),
    )


class VenueCatalogTests(unittest.TestCase):
    def test_default_service_publishes_no_unverified_venue_or_capability(self):
        options = VenueCatalogService().public_options()

        self.assertEqual(options["catalog_status"], "not_configured")
        self.assertIsNone(options["catalog_version"])
        self.assertEqual(options["venues"], [])
        self.assertEqual(options["capabilities"], {
            "display": False,
            "plan_binding": False,
            "historical_availability": False,
            "live_availability": False,
        })

    def test_catalog_requires_confirmed_venue_scope_and_court_evidence(self):
        manifest = verified_manifest()
        manifest["findings"]["court_to_venue_association"] = "partial"
        with self.assertRaises(CatalogError) as failure:
            VenueCatalog(
                version="catalog-test-v1",
                source_client_build="synthetic-test-build",
                evidence_ref="test-only-evidence",
                evidence_manifest=manifest,
                venues=test_catalog().venues,
            )
        self.assertEqual(str(failure.exception), "venue_catalog_court_evidence_incomplete")

    def test_confirmed_venue_list_can_be_displayed_without_binding_or_query_scope(self):
        catalog = VenueCatalog(
            version="catalog-display-test-v1",
            source_client_build="synthetic-test-build",
            evidence_ref="test-only-evidence",
            evidence_manifest=display_only_manifest(),
            venues=(CatalogVenue("test-east", "测试东区场馆", None, "test-only-venue-evidence", ()),),
        )
        options = VenueCatalogService(catalog).public_options()

        self.assertTrue(options["capabilities"]["display"])
        self.assertFalse(options["capabilities"]["plan_binding"])
        self.assertFalse(options["capabilities"]["historical_availability"])
        self.assertEqual(options["venues"][0]["courts"], [])

    def test_public_options_are_versioned_semantic_data_without_scope_config_key(self):
        options = VenueCatalogService(test_catalog()).public_options()
        serialized = json.dumps(options, ensure_ascii=False)

        self.assertEqual(options["catalog_status"], "configured")
        self.assertEqual(options["catalog_version"], "catalog-test-v1")
        self.assertEqual(options["venues"], [{
            "venue_key": "test-east",
            "display_name": "测试东区场馆",
            "evidence_ref": "test-only-venue-evidence",
            "courts": [{"court_key": "court-6", "display_name": "6号场", "evidence_ref": "test-only-court-evidence"}],
        }])
        self.assertNotIn("VENUE_SCOPE_TEST_ONLY", serialized)
        self.assertNotIn("scope_config_key", serialized)
        self.assertFalse(options["capabilities"]["plan_binding"])
        self.assertFalse(options["capabilities"]["historical_availability"])
        self.assertFalse(options["capabilities"]["live_availability"])
        self.assertFalse(options["evidence_readiness"]["live_read_only_query"])

    def test_catalog_rejects_invalid_and_duplicate_semantic_entries(self):
        catalog = test_catalog()
        with self.assertRaises(CatalogError):
            CatalogCourt("场地 6", "6号场", "test-only-evidence")
        duplicate = CatalogVenue("test-east", "另一个显示名", "VENUE_SCOPE_OTHER", "test-evidence", catalog.venues[0].courts)
        with self.assertRaises(CatalogError):
            VenueCatalog(
                version="catalog-test-v1",
                source_client_build="synthetic-test-build",
                evidence_ref="test-only-evidence",
                evidence_manifest=verified_manifest(),
                venues=(catalog.venues[0], duplicate),
            )


if __name__ == "__main__":
    unittest.main()
