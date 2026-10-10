from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date

from backend.booking_window import BookingWindowPolicy


@dataclass(frozen=True, slots=True)
class PlanInterpretationContext:
    timezone_name: str
    currency_code: str | None
    currency_minor_unit_exponent: int | None

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "preference_verification": "unverified_manual",
            "catalog_version": None,
            "venue_binding": None,
        }


@dataclass(frozen=True, slots=True)
class PlanSnapshot:
    canonical_json: str
    sha256: str

    @classmethod
    def build(cls, intent: dict, context: PlanInterpretationContext) -> PlanSnapshot:
        encoded = json.dumps(
            {"kind": "unbound_draft", "intent": intent, "context": context.to_dict()},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        return cls(encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest())

    @property
    def value(self) -> dict:
        # Every caller gets a copy; editing a DTO cannot mutate a frozen snapshot.
        return json.loads(self.canonical_json)


def describe_window(policy: BookingWindowPolicy, target_date: date, now_utc_ms: int, saved_timezone: str | None = None) -> dict:
    state = asdict(policy.describe(target_date, now_utc_ms, saved_timezone))
    for key in ("business_date", "default_target_date", "target_date"):
        state[key] = state[key].isoformat()
    state["queryable_target_dates"] = [item.isoformat() for item in state["queryable_target_dates"]]
    return {**state, "can_query_upstream": False, "can_create_job": False}
