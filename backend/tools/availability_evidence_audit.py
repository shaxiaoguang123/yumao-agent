"""Validate a sanitized protocol evidence manifest without printing its path/data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from backend.availability_matching.protocol_evidence import (
    EvidenceManifestError,
    assess_evidence,
    manifest_template,
)


MAX_MANIFEST_BYTES = 16 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceManifestError()
        result[key] = value
    return result


def _reject_constant(_value):
    raise EvidenceManifestError()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", help="local sanitized evidence manifest")
    parser.add_argument("--template", action="store_true", help="print a safe manifest template")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.template:
        if args.manifest:
            print(json.dumps({"error": "invalid_evidence_manifest"}))
            return 2
        print(json.dumps(manifest_template(), sort_keys=True, indent=2))
        return 0
    if not args.manifest:
        print(json.dumps({"error": "invalid_evidence_manifest"}))
        return 2
    try:
        raw = Path(args.manifest).read_bytes()
        if len(raw) > MAX_MANIFEST_BYTES:
            raise EvidenceManifestError()
        manifest = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        report = assess_evidence(manifest)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, EvidenceManifestError, RecursionError):
        print(json.dumps({"error": "invalid_evidence_manifest"}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
