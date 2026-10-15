from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime


@dataclass(frozen=True, slots=True)
class ClockSample:
    offset_ms: int
    uncertainty_ms: int
    server_utc_ms: int


class ClockCalibrationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def sample_upstream_clock(date_header: object, started_at_utc_ms: int,
                          completed_at_utc_ms: int) -> ClockSample:
    if (type(date_header) is not str or not date_header or len(date_header) > 128
            or type(started_at_utc_ms) is not int or type(completed_at_utc_ms) is not int
            or started_at_utc_ms <= 0 or completed_at_utc_ms < started_at_utc_ms):
        raise ClockCalibrationError("upstream_clock_sample_missing")
    try:
        parsed = parsedate_to_datetime(date_header)
        if parsed is None:
            raise ValueError
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        server_second_ms = int(parsed.astimezone(timezone.utc).timestamp() * 1000)
    except (TypeError, ValueError, OverflowError):
        raise ClockCalibrationError("upstream_clock_sample_invalid") from None
    midpoint = (started_at_utc_ms + completed_at_utc_ms) // 2
    # HTTP Date has one-second granularity; midpoint removes most of the RTT bias.
    server_utc_ms = server_second_ms + 500
    uncertainty = math.ceil((completed_at_utc_ms - started_at_utc_ms) / 2 + 500)
    offset = server_utc_ms - midpoint
    if uncertainty > 2500:
        raise ClockCalibrationError("upstream_clock_uncertainty_too_high")
    if abs(offset) > 120_000:
        raise ClockCalibrationError("local_clock_outside_supported_drift")
    return ClockSample(offset_ms=offset, uncertainty_ms=uncertainty, server_utc_ms=server_utc_ms)
