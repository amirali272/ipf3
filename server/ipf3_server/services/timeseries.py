from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, literal_column

NICE_BUCKETS = [10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400]
MAX_RANGE = timedelta(days=400)


def resolve_range(
    start: datetime | None, end: datetime | None, default: timedelta = timedelta(hours=1)
) -> tuple[datetime, datetime]:
    end = end or datetime.now(timezone.utc)
    start = start or end - default
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if start >= end:
        raise HTTPException(422, "'from' must be before 'to'")
    if end - start > MAX_RANGE:
        raise HTTPException(422, "time range too large")
    return start, end


def pick_bucket(start: datetime, end: datetime, requested: int | None, points: int = 300) -> int:
    if requested:
        return max(10, min(requested, 86400))
    span = (end - start).total_seconds()
    want = math.ceil(span / points)
    for b in NICE_BUCKETS:
        if b >= want:
            return b
    return NICE_BUCKETS[-1]


def bucket_expr(column, seconds: int):
    """PostgreSQL date_bin() aligned to the Unix epoch."""
    return func.date_bin(
        func.make_interval(0, 0, 0, 0, 0, 0, seconds),
        column,
        literal_column("TIMESTAMPTZ '1970-01-01 00:00:00+00'"),
    )
