"""Malaysia multi-timezone utilities

Malaysia currently uses a single timezone (Malaysian Time, MYT = UTC+8)
year-round with no Daylight Saving Time. However, the country has a
complex timezone history:

Historical context:
  - Peninsular Malaysia: UTC+7:30 was used until 1941, then UTC+9
    during Japanese occupation (1942-1945), then UTC+7:30 again, and
    finally UTC+7:30 (daylight) / UTC+7 (standard) briefly in 1981.
  - Sabah (North Borneo): UTC+8 used since 1926.
  - Sarawak: UTC+8 used since 1933.
  - The current unified UTC+8 was adopted on 1 January 1982.

This is relevant for:
  - Restaurant opening hour display (consistent nationwide)
  - Historical data comparison across the 1982 timezone unification
  - Sabah/Sarawak vs Peninsular Malaysia data migration handling
  - Event timestamps that reference pre-1982 data

IMPORTANT: All new data should use UTC+8 (Asia/Kuala_Lumpur) as the
standard. The historical functions in this module are for ETL and data
migration only — do not use them in real-time transaction paths.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone, tzinfo
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

# Malaysia's current single timezone
MYT_UTC_OFFSET = timedelta(hours=8)

# IANA timezone identifier for Malaysia
MYT_IANA = "Asia/Kuala_Lumpur"

# Historical timezone offsets by region and period
# Format: (start_year, end_year) -> offset from UTC
PENINSULAR_MALAYSIA_HISTORICAL: dict[tuple[int, int], timedelta] = {
    (1901, 1904): timedelta(hours=6, minutes=46),  # Local Mean Time (Penang)
    (1905, 1932): timedelta(hours=7),  # Standard time (Malaya)
    (1933, 1941): timedelta(hours=7, minutes=30),  # Malaya Daylight Time
    (1942, 1945): timedelta(hours=9),  # Japanese occupation (Tokyo time)
    (1946, 1981): timedelta(hours=7, minutes=30),  # Post-war Malayan time
}

SABAH_HISTORICAL: dict[tuple[int, int], timedelta] = {
    (1926, 1981): timedelta(hours=8),  # North Borneo time
}

SARAWAK_HISTORICAL: dict[tuple[int, int], timedelta] = {
    (1933, 1981): timedelta(hours=8),  # Sarawak time
}

# Date of unification
UNIFICATION_DATE = "1982-01-01"


# ─────────────────────────────────────────────
# Timezone Class
# ─────────────────────────────────────────────


class MalaysiaTimeZone(tzinfo):
    """Fixed UTC+8 timezone for Malaysia.

    Malaysia does not observe DST, so this is a simple fixed offset.
    Use this for all new data storage and display operations.
    """

    def __init__(self) -> None:
        super().__init__()
        self._offset = MYT_UTC_OFFSET
        self._name = "MYT"

    def utcoffset(self, dt: Optional[datetime] = None) -> timedelta:
        return self._offset

    def dst(self, dt: Optional[datetime] = None) -> timedelta:
        return timedelta(0)

    def tzname(self, dt: Optional[datetime] = None) -> str:
        return self._name


# Singleton instance
MYT = MalaysiaTimeZone()


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────


def now_myt() -> datetime:
    """Get current datetime in Malaysia time (UTC+8).

    Returns:
        Timezone-aware datetime with MalaysiaTimeZone.
    """
    return datetime.now(timezone.utc).astimezone(MYT)


def to_myt(utc_dt: datetime) -> datetime:
    """Convert a UTC datetime to Malaysia time.

    Args:
        utc_dt: Timezone-aware or naive UTC datetime.

    Returns:
        Timezone-aware datetime in MYT.

    Raises:
        ValueError: If utc_dt is naive (no timezone info).
    """
    if utc_dt.tzinfo is None:
        raise ValueError(
            "Naive datetime provided. Supply a timezone-aware datetime "
            "or use utcfromtimestamp()."
        )
    return utc_dt.astimezone(MYT)


def format_myt(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format a datetime as a Malaysia time string.

    Args:
        dt: Timezone-aware datetime.
        fmt: strftime format string.

    Returns:
        Formatted time string in MYT.
    """
    return to_myt(dt).strftime(fmt)


def get_historical_offset(year: int, region: str = "peninsular") -> timedelta:
    """Get the historical UTC offset for a given year and region.

    Only relevant for ETL/migration of legacy data. Modern data should
    always use UTC+8.

    Args:
        year: The calendar year to query.
        region: One of "peninsular", "sabah", "sarawak".

    Returns:
        The UTC offset as a timedelta for that period.

    Raises:
        ValueError: If the region is unknown or the year has no data.
    """
    registry: dict[str, dict[tuple[int, int], timedelta]] = {
        "peninsular": PENINSULAR_MALAYSIA_HISTORICAL,
        "sabah": SABAH_HISTORICAL,
        "sarawak": SARAWAK_HISTORICAL,
    }

    periods = registry.get(region)
    if periods is None:
        raise ValueError(f"Unknown region: {region}. Must be 'peninsular', 'sabah', or 'sarawak'.")

    for (start, end), offset in periods.items():
        if start <= year <= end:
            return offset

    # After 1982, all Malaysia uses UTC+8
    if year >= 1982:
        return MYT_UTC_OFFSET

    raise ValueError(
        f"No historical timezone data for region={region}, year={year}. "
        f"Peninsular data covers 1901-1981; Sabah covers 1926-1981; "
        f"Sarawak covers 1933-1981."
    )


def has_unified_timezone(year: int) -> bool:
    """Check if Malaysia had unified UTC+8 by the given year.

    Args:
        year: The calendar year to check.

    Returns:
        True if the unified UTC+8 was in effect.
    """
    return year >= 1982


# ─────────────────────────────────────────────
# Time-based Business Rules
# ─────────────────────────────────────────────


# Meal period time ranges in MYT (local time)
MEAL_PERIOD_RANGES: dict[str, tuple[time, time]] = {
    "breakfast": (time(6, 0), time(11, 0)),
    "lunch": (time(11, 0), time(15, 0)),
    "afternoon_tea": (time(15, 0), time(17, 0)),
    "dinner": (time(17, 0), time(22, 0)),
    "supper": (time(22, 0), time(2, 0)),  # Crosses midnight
}


def get_current_meal_period() -> str:
    """Determine the current meal period in Malaysia time.

    Returns:
        One of "breakfast", "lunch", "afternoon_tea", "dinner", "supper".
    """
    current_hour = now_myt().hour
    current_minute = now_myt().minute
    current_time = time(current_hour, current_minute)

    # Check supper first (crosses midnight, 10pm-2am)
    supper_start = time(22, 0)
    supper_end = time(2, 0)
    if current_time >= supper_start or current_time < supper_end:
        return "supper"

    for period, (start, end) in MEAL_PERIOD_RANGES.items():
        if period == "supper":
            continue  # Already handled
        if start <= current_time < end:
            return period

    return "breakfast"  # Default fallback


def is_peak_hour(current_hour: Optional[int] = None) -> bool:
    """Check if the current or given hour is a peak dining period in Malaysia.

    Peak hours are determined by Malaysian dining patterns:
      - Lunch: 12:00-14:00
      - Dinner: 18:00-21:00

    Args:
        current_hour: Hour to check (0-23). Defaults to current MYT hour.

    Returns:
        True if the hour falls within a peak dining period.
    """
    if current_hour is None:
        current_hour = now_myt().hour

    return (12 <= current_hour < 14) or (18 <= current_hour < 21)


# ─────────────────────────────────────────────
# Sabah / Sarawak Specific
# ─────────────────────────────────────────────


def is_east_malaysia(store_region: str) -> bool:
    """Check if a store region is in East Malaysia (Sabah/Sarawak/Labuan).

    East Malaysia historically and culturally has different dining patterns,
    holiday schedules (Gawai, Kaamatan), and business hours.

    Args:
        store_region: Region string from store config.

    Returns:
        True if the region is East Malaysian.
    """
    east_malaysia_regions = {"sabah", "sarawak", "labuan"}
    return store_region.strip().lower() in east_malaysia_regions


EAST_MALAYSIA_BUSINESS_HOURS: dict[str, dict[str, Any]] = {
    "sabah": {
        "typical_open": "6:30",
        "typical_close": "21:00",
        "lunch_peak": "12:00-14:00",
        "dinner_peak": "18:00-20:00",
        "note": "Sabah dining tends to start and end earlier than KL.",
    },
    "sarawak": {
        "typical_open": "6:00",
        "typical_close": "21:30",
        "lunch_peak": "11:30-13:30",
        "dinner_peak": "17:30-19:30",
        "note": "Sarawak has early dinner patterns; many restaurants close by 21:00.",
    },
    "labuan": {
        "typical_open": "7:00",
        "typical_close": "22:00",
        "lunch_peak": "12:00-14:00",
        "dinner_peak": "18:30-21:00",
        "note": "Labuan follows Sabah patterns with later dinner due to ferry/port activity.",
    },
}


def get_east_malaysia_hours(region: str) -> dict[str, Any] | None:
    """Get typical business hours for an East Malaysia region.

    Args:
        region: "sabah", "sarawak", or "labuan".

    Returns:
        Business hours dict or None if region not recognized.
    """
    return EAST_MALAYSIA_BUSINESS_HOURS.get(region.lower())
