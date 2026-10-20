"""Server-owned state for the booking-queue drafting conversation.

Everything that decides *what happens next* is a pure function of the user's own
words (see queue_draft.fold), so the flow cannot loop because a model repeated
itself. A duration excluded by the chosen queue mode is inactive and never blocks.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum


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
PRIORITY = (
    "booking_mode", "target_date",
    "windows_2h", "overlap_2h", "courts_2h",
    "windows_1h", "overlap_1h", "courts_1h",
)
MAX_ANSWERS = 20
MAX_ASKS_PER_FIELD = 3
UNRESOLVED = frozenset({SlotStatus.EMPTY, SlotStatus.AMBIGUOUS, SlotStatus.INVALID})
TERMINAL = frozenset({Phase.READY, Phase.UNSUPPORTED, Phase.ESCALATED})
# A conversation may only move on from an open phase; terminal phases end it.
TRANSITIONS = {
    Phase.COLLECTING: frozenset(Phase),
    Phase.REPAIRING: frozenset(Phase),
    Phase.READY: frozenset(),
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


def can_follow(previous: Phase | None, current: Phase) -> bool:
    return previous is None or current in TRANSITIONS[previous]


def blocking_slots(slots: dict[str, Slot]) -> list[Slot]:
    return [slots[f] for f in PRIORITY if slots[f].blocking]


def _reason(slot: Slot) -> Reason:
    if slot.reason is not None:
        return slot.reason
    return {SlotStatus.AMBIGUOUS: Reason.AMBIGUOUS, SlotStatus.INVALID: Reason.INVALID}.get(slot.status, Reason.MISSING)


def decide(slots: dict[str, Slot], asked: list[str | None], turns_used: int, *, has_command: bool = False) -> Decision:
    """Pick the next phase and the single field to ask about."""
    if has_command:
        return Decision(Phase.UNSUPPORTED)
    open_slots = blocking_slots(slots)
    if not open_slots:
        return Decision(Phase.READY)  # nothing is open, so even the last allowed turn can finish
    first = open_slots[0]
    reason = _reason(first)
    if Counter(asked)[first.field] >= MAX_ASKS_PER_FIELD:
        return Decision(Phase.ESCALATED, first.field, reason, "stalled")
    if turns_used >= MAX_ANSWERS:
        return Decision(Phase.ESCALATED, first.field, reason, "turn_limit")
    phase = Phase.REPAIRING if reason in {Reason.INVALID, Reason.AMBIGUOUS} else Phase.COLLECTING
    return Decision(phase, first.field, reason)
