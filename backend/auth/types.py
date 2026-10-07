from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class UserSummary:
    user_id: str
    username: str
    role: Literal["admin", "user"]


@dataclass(frozen=True, slots=True)
class SessionContext:
    user: UserSummary
    csrf_scheme_version: int
