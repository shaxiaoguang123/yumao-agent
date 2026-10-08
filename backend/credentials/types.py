from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class CredentialDTO:
    credential_id: str
    label: str
    credential_version: int
    current_token_revision_id: str
    enabled: bool
    account_binding_state: str
    requires_revalidation: bool
    expiry_state: str
    token_expires_at_utc_ms: int | None
    last_confirmed_validation_state: str
    last_successful_validation_at_utc_ms: int | None
    latest_requested_validation_attempt: Mapping[str, Any] | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class CredentialOperationResult:
    code: str
    http_status: int
    credential: CredentialDTO | None = None
    retry_after_seconds: int | None = None
    deleted: bool = False

    @property
    def succeeded(self) -> bool:
        return 200 <= self.http_status < 300


class CredentialOperationError(RuntimeError):
    """Safe operation error; it never stores upstream or Token response material."""

    def __init__(
        self,
        code: str,
        http_status: int = 409,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.code = code
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code)
