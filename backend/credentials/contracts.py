from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


TokenValidationOutcome = Literal[
    "success",
    "explicit_invalid",
    "network_error",
    "rate_limited",
    "contract_drift",
    "validation_unknown",
]
HttpStatusClass = Literal["1xx", "2xx", "3xx", "4xx", "5xx"]
DispatchState = Literal["not_dispatched", "complete", "uncertain"]


@dataclass(frozen=True, slots=True)
class AdapterValidationResult:
    token_outcome: TokenValidationOutcome
    safe_code: str
    identity_bytes: bytes | None = field(repr=False)
    identity_contract_version: str | None
    http_status_class: HttpStatusClass | None
    retry_after_header: str | None = field(repr=False)
    dispatch_state: DispatchState = "not_dispatched"
    http_status_code: int | None = None
