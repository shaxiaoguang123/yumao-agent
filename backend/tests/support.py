from __future__ import annotations

import base64
import json
from pathlib import Path


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def credential_test_settings(database_path: Path | None = None) -> dict[str, str]:
    """Return deterministic synthetic settings; never reads process env or .env."""
    settings = {
        "CSRF_HMAC_SECRET": _b64url(bytes(range(32))),
        "APP_CREDENTIAL_ENCRYPTION_KEYS": json.dumps(
            {"enc-v1": _b64url(bytes(range(32, 64)))}, separators=(",", ":")
        ),
        "APP_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID": "enc-v1",
        "APP_UPSTREAM_FINGERPRINT_KEYS": json.dumps(
            {"fp-v1": _b64url(bytes(range(64, 96)))}, separators=(",", ":")
        ),
        "APP_UPSTREAM_FINGERPRINT_ACTIVE_KEY_ID": "fp-v1",
        "UPSTREAM_ORIGIN": "https://bdtyg.cugb.edu.cn",
        "UPSTREAM_CONNECT_TIMEOUT_SECONDS": "3",
        "UPSTREAM_READ_TIMEOUT_SECONDS": "5",
        "UPSTREAM_TOTAL_DEADLINE_SECONDS": "10",
        "UPSTREAM_MAX_RESPONSE_BYTES": "65536",
        "UPSTREAM_RETRY_AFTER_FALLBACK_SECONDS": "30",
        "MAX_UPSTREAM_BACKOFF_SECONDS": "900",
        "UPSTREAM_LEASE_SAFETY_MARGIN_SECONDS": "6",
    }
    if database_path is not None:
        settings["DATABASE_PATH"] = str(database_path)
    return settings
