"""Validated queue state and hard gates for the model-orchestrated conversation.

The model proposes the next active field from context; this module rejects inactive
or dependency-blocked fields and derives readiness from server-validated facts.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum

from backend.ai.queue_policy import FIELD_ORDER, MAX_ANSWER_COUNT, eligible_fields


class SlotStatus(str, Enum):
    EMPTY = "empty"
    PROPOSED = "proposed"      # read from the user's words
    AMBIGUOUS = "ambiguous"    # more than one reading
    INVALID = "invalid"        # understood but breaks a booking rule
    VERIFIED = "verified"      # settled: confirmed, defaulted, or not applicable


class Phase(str, Enum):
    COLLECTING = "collecting"
    REPAIRING = "repairing"
    READY = "ready"
    UNSUPPORTED = "unsupported"
    ESCALATED = "escalated"


class Reason(str, Enum):
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"


# Order is the order questions are asked. The duration choice is mandatory and
# each active duration group is completed before the next one begins.
PRIORITY = FIELD_ORDER
MAX_ANSWERS = MAX_ANSWER_COUNT
MAX_ASKS_PER_FIELD = 3
UNRESOLVED = frozenset({SlotStatus.EMPTY, SlotStatus.AMBIGUOUS, SlotStatus.INVALID})
TERMINAL = frozenset({Phase.UNSUPPORTED, Phase.ESCALATED})
TURN_COMPLETE = TERMINAL | {Phase.READY}
# A preview remains editable; refusal and escalation require an explicit restart.
TRANSITIONS = {
    Phase.COLLECTING: frozenset(Phase),
    Phase.REPAIRING: frozenset(Phase),
    Phase.READY: frozenset({Phase.READY, Phase.COLLECTING, Phase.REPAIRING, Phase.UNSUPPORTED, Phase.ESCALATED}),
    Phase.UNSUPPORTED: frozenset(),
    Phase.ESCALATED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class Slot:
    field: str
    status: SlotStatus
    value: object = None
    display: str = ""
    detail: str | None = None
    reason: Reason | None = None
    active: bool = True

    @property
    def blocking(self) -> bool:
        """Needs another user turn before the queue can be built."""
        return self.active and self.status in UNRESOLVED

    def public(self) -> dict:
        return {"field": self.field, "status": self.status.value, "display": self.display,
                "active": self.active, "reason": self.reason.value if self.reason else None}


@dataclass(frozen=True, slots=True)
class Decision:
    phase: Phase
    asking: str | None = None
    reason: Reason | None = None
    escalation: str | None = None  # "stalled" | "turn_limit"
    eligible_fields: tuple[str, ...] = ()
    model_choice_accepted: bool = False


def can_follow(previous: Phase | None, current: Phase) -> bool:
    return previous is None or current in TRANSITIONS[previous]


def blocking_slots(slots: dict[str, Slot]) -> list[Slot]:
    return [slots[f] for f in PRIORITY if slots[f].blocking]


def _reason(slot: Slot) -> Reason:
    if slot.reason is not None:
        return slot.reason
    return {SlotStatus.AMBIGUOUS: Reason.AMBIGUOUS, SlotStatus.INVALID: Reason.INVALID}.get(slot.status, Reason.MISSING)


def decide(slots: dict[str, Slot], asked: list[str | None], turns_used: int, *, has_command: bool = False,
           preferred_field: str | None = None, pending_edit: dict | None = None) -> Decision:
    """Validate the model's field choice against the queue workflow gates."""
    if has_command:
        return Decision(Phase.UNSUPPORTED)
    if pending_edit is not None:
        remaining = pending_edit["remaining"]
        if not remaining:
            return Decision(Phase.REPAIRING)
        field = preferred_field if preferred_field in remaining else remaining[0]
        slot = slots[field]
        reason = _reason(slot) if slot.blocking else Reason.MISSING
        if Counter(asked)[field] >= MAX_ASKS_PER_FIELD:
            return Decision(Phase.ESCALATED, field, reason, "stalled", tuple(remaining))
        if turns_used >= MAX_ANSWERS:
            return Decision(Phase.ESCALATED, field, reason, "turn_limit", tuple(remaining))
        return Decision(Phase.REPAIRING, field, reason, None, tuple(remaining), preferred_field == field)
    eligible = eligible_fields(slots)
    if not eligible:
        return Decision(Phase.READY)  # nothing is open, so even the last allowed turn can finish
    accepted = preferred_field in eligible
    field = preferred_field if accepted else eligible[0]
    chosen = slots[field]
    reason = _reason(chosen)
    if Counter(asked)[chosen.field] >= MAX_ASKS_PER_FIELD:
        return Decision(Phase.ESCALATED, chosen.field, reason, "stalled", tuple(eligible), accepted)
    if turns_used >= MAX_ANSWERS:
        return Decision(Phase.ESCALATED, chosen.field, reason, "turn_limit", tuple(eligible), accepted)
    phase = Phase.REPAIRING if reason in {Reason.INVALID, Reason.AMBIGUOUS} else Phase.COLLECTING
    return Decision(phase, chosen.field, reason, None, tuple(eligible), accepted)
