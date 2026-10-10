from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import re
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.plans.validation import parse_target_date, IntentValidationError

MAX_MINOR = 9007199254740991


class AvailabilityError(ValueError):
    def __init__(self, code: str, status: int = 422):
        self.code, self.status = code, status
        super().__init__(code)


def minutes(value, *, end=False):
    if end and value == '24:00':
        return 1440
    if type(value) is not str or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value, re.ASCII):
        raise AvailabilityError('invalid_availability_snapshot')
    return int(value[:2]) * 60 + int(value[3:])


def clock(value):
    return f'{value // 60:02d}:{value % 60:02d}'


def _text(value, maximum):
    if (type(value) is not str or not 1 <= len(value) <= maximum or value != value.strip()
            or any(unicodedata.category(c) in {'Cc', 'Cs'} for c in value)):
        raise AvailabilityError('invalid_availability_snapshot')


@dataclass(frozen=True, slots=True)
class AvailabilitySlot:
    """One indivisible inventory/pricing unit; intervals are local and half-open."""
    court_name: str
    start_time: str
    end_time: str
    status: str  # available / unavailable / unknown; no upstream status-code assumptions
    price_minor: int | None = None

    def __post_init__(self):
        _text(self.court_name, 100)
        if minutes(self.start_time) >= minutes(self.end_time, end=True):
            raise AvailabilityError('invalid_availability_snapshot')
        if self.status not in ('available', 'unavailable', 'unknown'):
            raise AvailabilityError('invalid_availability_snapshot')
        if self.price_minor is not None and (type(self.price_minor) is not int or not 0 <= self.price_minor <= MAX_MINOR):
            raise AvailabilityError('invalid_availability_snapshot')


@dataclass(frozen=True, slots=True)
class AvailabilitySnapshot:
    target_date: str
    timezone_name: str
    venue_name: str
    slots: tuple[AvailabilitySlot, ...]
    source: str
    simulation: bool
    currency_code: str | None = None
    currency_minor_unit_exponent: int | None = None
    venue_semantic_key: str | None = None

    def __post_init__(self):
        try:
            target = parse_target_date(self.target_date)
            zone = ZoneInfo(self.timezone_name)
        except (IntentValidationError, TypeError, ValueError, ZoneInfoNotFoundError):
            raise AvailabilityError('invalid_availability_snapshot') from None
        # Local HH:MM cannot express folds or skipped minutes. A future adapter must
        # supply an unambiguous contract for DST/offset-transition days, not guess.
        midnight = datetime.combine(target, time())
        offsets = set()
        for minute in range(1441):
            try:
                local = midnight + timedelta(minutes=minute)
                aware = local.replace(tzinfo=zone, fold=0)
                alternate = local.replace(tzinfo=zone, fold=1)
                if aware.utcoffset() != alternate.utcoffset() or aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != local:
                    raise AvailabilityError('availability_timezone_day_unsupported')
                offsets.add(aware.utcoffset())
            except OverflowError:
                raise AvailabilityError('invalid_availability_snapshot') from None
        if len(offsets) != 1:
            raise AvailabilityError('availability_timezone_day_unsupported')
        _text(self.venue_name, 200)
        _text(self.source, 100)
        if type(self.simulation) is not bool or type(self.slots) is not tuple or len(self.slots) > 2048:
            raise AvailabilityError('invalid_availability_snapshot')
        if self.venue_semantic_key is not None:
            _text(self.venue_semantic_key, 100)
        code, exponent = self.currency_code, self.currency_minor_unit_exponent
        if (code is None) != (exponent is None):
            raise AvailabilityError('invalid_availability_snapshot')
        if code is not None and (type(code) is not str or not re.fullmatch('[A-Z]{3}', code, re.ASCII)
                                 or type(exponent) is not int or not 0 <= exponent <= 6):
            raise AvailabilityError('invalid_availability_snapshot')
        by_court = {}
        for slot in self.slots:
            if type(slot) is not AvailabilitySlot:
                raise AvailabilityError('invalid_availability_snapshot')
            by_court.setdefault(slot.court_name, []).append(slot)
        if len(by_court) > 32:
            raise AvailabilityError('invalid_availability_snapshot')
        # Reject duplicate or overlapping atoms rather than choosing an optimistic state/price.
        for slots in by_court.values():
            ordered = sorted(slots, key=lambda s: s.start_time)
            if any(minutes(a.end_time, end=True) > minutes(b.start_time) for a, b in zip(ordered, ordered[1:])):
                raise AvailabilityError('invalid_availability_snapshot')

    def provenance(self):
        return {'source': self.source, 'simulation': self.simulation,
                'trust_state': 'synthetic' if self.simulation else 'normalized_unverified',
                'target_date': self.target_date, 'timezone_name': self.timezone_name,
                'venue_name': self.venue_name, 'venue_semantic_key': self.venue_semantic_key}
