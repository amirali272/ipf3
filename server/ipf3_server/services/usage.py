from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..config import get_settings


@lru_cache
def usage_tz() -> ZoneInfo | timezone:
    name = get_settings().usage_timezone
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def usage_day(ts: datetime) -> date:
    """Calendar day a sample belongs to in the configured usage timezone."""
    return ts.astimezone(usage_tz()).date()


def today() -> date:
    return usage_day(datetime.now(timezone.utc))


def month_start(d: date) -> date:
    return d.replace(day=1)


def days_back(d: date, n: int) -> date:
    return d - timedelta(days=n)
