"""Privacy-safe readiness checks for the venue/availability protocol evidence.

This module records evidence status only. It never contains upstream identifiers,
capture payloads, credentials, or inferred field values.
"""

from __future__ import annotations

FINDING_STATUSES = frozenset({"confirmed", "partial", "missing"})
FINDING_KEYS = frozenset({
    "client_version_association",
    "venue_list_response",
    "venue_name_to_parent_scope",
    "court_to_venue_association",
    "booking_by_time_scope_response_association",
    "booking_by_time_response_structure",
    "availability_status_semantics",
    "conflict_list_semantics",
    "time_atom_duration_continuity",
    "price_unit_currency_scope",
    "capture_timestamp_freshness",
    "appointment_type_semantics",
    "booktype_semantics",
    "live_query_authorization",
})


class EvidenceManifestError(ValueError):
    """The evidence manifest is malformed or contains fields outside its contract."""

    def __init__(self):
        super().__init__("invalid_evidence_manifest")


CURRENT_EVIDENCE = {
    "schema_version": 1,
    "findings": {
        "client_version_association": "missing",
        "venue_list_response": "missing",
        "venue_name_to_parent_scope": "partial",
        "court_to_venue_association": "missing",
        "booking_by_time_scope_response_association": "missing",
        "booking_by_time_response_structure": "partial",
        "availability_status_semantics": "missing",
        "conflict_list_semantics": "missing",
        "time_atom_duration_continuity": "partial",
        "price_unit_currency_scope": "missing",
        "capture_timestamp_freshness": "missing",
        "appointment_type_semantics": "partial",
        "booktype_semantics": "partial",
        "live_query_authorization": "missing",
    },
}


_REQUIREMENTS = {
    "venue_directory_display": (
        "client_version_association",
        "venue_list_response",
    ),
    "venue_catalog": (
        "client_version_association",
        "venue_list_response",
        "venue_name_to_parent_scope",
    ),
    "plan_binding": (
        "client_version_association",
        "venue_list_response",
        "venue_name_to_parent_scope",
        "court_to_venue_association",
    ),
    "recorded_availability": (
        "client_version_association",
        "venue_list_response",
        "venue_name_to_parent_scope",
        "court_to_venue_association",
        "booking_by_time_scope_response_association",
        "booking_by_time_response_structure",
        "availability_status_semantics",
        "conflict_list_semantics",
        "time_atom_duration_continuity",
    ),
    "price_aware_matching": (
        "client_version_association",
        "venue_list_response",
        "venue_name_to_parent_scope",
        "court_to_venue_association",
        "booking_by_time_scope_response_association",
        "booking_by_time_response_structure",
        "availability_status_semantics",
        "conflict_list_semantics",
        "time_atom_duration_continuity",
        "price_unit_currency_scope",
    ),
    "live_read_only_query": (
        "client_version_association",
        "venue_list_response",
        "venue_name_to_parent_scope",
        "court_to_venue_association",
        "booking_by_time_scope_response_association",
        "booking_by_time_response_structure",
        "availability_status_semantics",
        "conflict_list_semantics",
        "time_atom_duration_continuity",
        "capture_timestamp_freshness",
        "live_query_authorization",
    ),
}


def parse_evidence_manifest(value: object) -> dict:
    """Validate a value-only manifest; never include submitted values in errors."""
    if type(value) is not dict or value.keys() != {"schema_version", "findings"}:
        raise EvidenceManifestError()
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise EvidenceManifestError()
    findings = value["findings"]
    if type(findings) is not dict or set(findings) != FINDING_KEYS:
        raise EvidenceManifestError()
    if any(type(status) is not str or status not in FINDING_STATUSES for status in findings.values()):
        raise EvidenceManifestError()
    return {"schema_version": 1, "findings": dict(findings)}


def assess_evidence(manifest: object) -> dict:
    parsed = parse_evidence_manifest(manifest)
    findings = parsed["findings"]
    readiness = {
        capability: all(findings[key] == "confirmed" for key in required)
        for capability, required in _REQUIREMENTS.items()
    }
    blockers = {
        capability: [key for key in required if findings[key] != "confirmed"]
        for capability, required in _REQUIREMENTS.items()
    }
    return {"findings": findings, "readiness": readiness, "blocking_findings": blockers}


def current_evidence_report() -> dict:
    """Return a fresh assessment so callers cannot mutate the process-wide baseline."""
    return assess_evidence(CURRENT_EVIDENCE)


def manifest_template() -> dict:
    """Create a safe, all-missing manifest template for reviewed evidence intake."""
    return {
        "schema_version": 1,
        "findings": {key: "missing" for key in sorted(FINDING_KEYS)},
    }
