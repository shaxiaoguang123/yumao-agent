"""Audit a local getBookingNode capture without emitting captured values."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


_MAX_CAPTURE_BYTES = 12 * 1024 * 1024
_SCOPE_VALUE = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z", re.ASCII)


class BookingNodeEvidenceError(ValueError):
    def __init__(self):
        super().__init__("invalid_booking_node_evidence")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BookingNodeEvidenceError()
        result[key] = value
    return result


def _reject_constant(_value):
    raise BookingNodeEvidenceError()


def _request_context(raw: bytes, method: str, route_suffix: str) -> str:
    first = raw.splitlines()[0] if raw else b""
    match = re.fullmatch(rb"(GET|POST) ([^ ?]+) HTTP/1\.[01]", first)
    if not match or match.group(1).decode("ascii") != method:
        raise BookingNodeEvidenceError()
    route = match.group(2).decode("ascii")
    if not route.endswith(route_suffix):
        raise BookingNodeEvidenceError()
    host, agent = None, None
    for line in raw.splitlines()[1:]:
        if not line:
            break
        name, separator, value = line.partition(b":")
        if not separator:
            continue
        name = name.strip().lower()
        if name == b"host":
            if host is not None:
                raise BookingNodeEvidenceError()
            host = value.strip().lower()
        elif name == b"user-agent":
            if agent is not None or not value.strip():
                raise BookingNodeEvidenceError()
            agent = hashlib.sha256(value.strip()).hexdigest()
    if host != b"bdtyg.cugb.edu.cn" or agent is None:
        raise BookingNodeEvidenceError()
    return agent


def _body(raw: bytes) -> bytes:
    if len(raw) > _MAX_CAPTURE_BYTES:
        raise BookingNodeEvidenceError()
    headers, separator, body = raw.partition(b"\r\n\r\n")
    if not separator:
        headers, separator, body = raw.partition(b"\n\n")
    status_line = headers.splitlines()[0] if headers.splitlines() else b""
    if not separator or not re.match(rb"HTTP/1\.[01] 200(?: |$)", status_line):
        raise BookingNodeEvidenceError()
    return body.strip()


def _check_source(directory_source: str, booking_source: str) -> None:
    directory_markers = (
        "getBookingNode:function", "t.links=n.data.resultData", "t._l(t.links,",
        "t._s(e.nodename)", "goToNotice:function", "r.id=t.id", "r.nodename=t.nodename",
    )
    booking_markers = ("this.param.nodeid=e.id", "e.param.nodeid=e.nodeid", "bookingByTime")
    if (any(marker not in directory_source for marker in directory_markers)
            or any(marker not in booking_source for marker in booking_markers)):
        raise BookingNodeEvidenceError()


def audit_booking_node_capture(*, asset_request: bytes, asset_response: bytes,
                               node_request: bytes, node_response: bytes,
                               directory_source: str, booking_source: str,
                               asset_sequence: int, node_sequence: int) -> dict:
    """Report the observed field path while keeping all scalar capture values local."""
    try:
        asset_agent = _request_context(
            asset_request, "GET", "/" + _asset_name(asset_request)
        )
        node_agent = _request_context(
            node_request, "POST", "/service/appointment/appointment/phone/getBookingNode"
        )
        if (type(asset_sequence) is not int or type(node_sequence) is not int
                or not 0 < node_sequence - asset_sequence <= 8 or asset_agent != node_agent):
            raise BookingNodeEvidenceError()
        asset_body = _body(asset_response)
        envelope = json.loads(
            _body(node_response).decode("utf-8", errors="strict"),
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
        )
        options = envelope.get("resultData") if type(envelope) is dict and envelope.get("success") is True else None
        if type(options) is not list or not 1 <= len(options) <= 128:
            raise BookingNodeEvidenceError()
        ids, labels = set(), set()
        for item in options:
            if type(item) is not dict:
                raise BookingNodeEvidenceError()
            node_id, node_name = item.get("id"), item.get("nodename")
            if (type(node_id) is not str or not _SCOPE_VALUE.fullmatch(node_id)
                    or type(node_name) is not str or not 1 <= len(node_name.strip()) <= 200
                    or node_name != node_name.strip() or node_id in ids or node_name in labels):
                raise BookingNodeEvidenceError()
            ids.add(node_id)
            labels.add(node_name)
        _check_source(directory_source, booking_source)
        if not asset_body:
            raise BookingNodeEvidenceError()
        return {
            "audit_version": "booking-node-scope-audit-v1",
            "source_asset_sha256": hashlib.sha256(asset_body).hexdigest(),
            "capture_asset_and_response_association": "same_host_agent_and_nearby_sequence",
            "client_release_version": "unknown",
            "observed_option_count": len(options),
            "field_flow": {
                "display_label_field": "nodename",
                "selected_item_field": "id",
                "booking_query_scope_field": "nodeid",
                "selected_item_to_query_scope": "confirmed_by_official_source",
            },
            "readiness": {
                "booking_node_scope_flow": True,
                "physical_venue_catalog": False,
                "court_ownership": False,
                "availability_snapshot": False,
                "live_read_only_query": False,
            },
            "blocking_evidence": [
                "physical_venue_label_to_parent_scope",
                "court_to_physical_venue_association",
                "booking_by_time_sample_to_selected_scope",
                "availability_state_semantics",
                "time_atom_and_continuity_rule",
                "live_query_authorization",
            ],
            "private_values_written": False,
            "live_request_sent": False,
        }
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, AttributeError, TypeError, ValueError):
        raise BookingNodeEvidenceError() from None


def _asset_name(raw: bytes) -> str:
    first = raw.splitlines()[0] if raw else b""
    match = re.fullmatch(rb"GET ([^ ?]+) HTTP/1\.[01]", first)
    if not match:
        raise BookingNodeEvidenceError()
    path = match.group(1).decode("ascii", errors="strict")
    found = re.search(r"pages-custom-home-bookingnode\.[A-Za-z0-9_-]+\.js\Z", path)
    if not found:
        raise BookingNodeEvidenceError()
    return found.group(0)


def _read(path: str) -> bytes:
    try:
        content = Path(path).read_bytes()
    except OSError:
        raise BookingNodeEvidenceError() from None
    if len(content) > _MAX_CAPTURE_BYTES:
        raise BookingNodeEvidenceError()
    return content


def _sequence(path: str) -> int:
    match = re.match(r"\[(\d{1,6})\]", Path(path).name)
    if not match:
        raise BookingNodeEvidenceError()
    return int(match.group(1))


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-request", required=True)
    parser.add_argument("--asset-response", required=True)
    parser.add_argument("--node-request", required=True)
    parser.add_argument("--node-response", required=True)
    parser.add_argument("--booking-source", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = audit_booking_node_capture(
            asset_request=_read(args.asset_request), asset_response=_read(args.asset_response),
            node_request=_read(args.node_request), node_response=_read(args.node_response),
            directory_source=_body(_read(args.asset_response)).decode("utf-8", errors="strict"),
            booking_source=Path(args.booking_source).read_text(encoding="utf-8", errors="strict"),
            asset_sequence=_sequence(args.asset_request), node_sequence=_sequence(args.node_request),
        )
    except (OSError, UnicodeDecodeError, BookingNodeEvidenceError):
        print(json.dumps({"error": "invalid_booking_node_evidence"}))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
