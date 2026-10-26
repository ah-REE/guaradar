"""Forecast provenance persistence.

Stores validated provider results as **append-only snapshots** so repeated fetches cannot
overwrite history (migration 0005). `weather_cache` remains a latest-value cache, which is
what a cache is for.

WHY A REPOSITORY CALLABLE INSTEAD OF BAKING IN A DRIVER
  This layer performs no I/O of its own. It builds a validated row and hands it to an
  injected `execute` callable. That keeps it unit-testable with no database, lets the same
  code run against local PostgreSQL (as M1 did) or Supabase, and prevents the service from
  quietly acquiring a privileged connection string of its own.

AUTHORIZATION POSTURE (N-2 still open)
  `persist_forecast` is **not** reachable from an HTTP route. The M7 brief forbids adding a
  privileged write endpoint while `current_app_role()` trusts a session setting. This module
  therefore builds and validates the row, and the caller (a server-side ingestion job) is
  responsible for supplying a trusted connection. Nothing here accepts a client-supplied
  role, user ID, or verification flag.

NEVER INVENTED
  `model_run_at` is copied from the adapter and persisted as NULL when absent (N-1). There
  is no fallback to `fetched_at`, and a database CHECK constraint enforces the same rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal, Sequence

from app.ingest.openmeteo import ForecastResult, HourlyRain

# Sentinel inserted where a provider gap exists. Distinct from 0.0, which would claim a
# measured zero.
GAP = None

ValidationStatus = Literal["ok", "partial", "failed"]

# A gap in the payload is a real absence. This many gaps turns the write into 'partial'.
PARTIAL_DROPPED_THRESHOLD = 1


class PersistenceError(Exception):
    """Raised only for programmer error, never for a provider failure."""


@dataclass(frozen=True)
class SnapshotRow:
    """One validated forecast snapshot, ready to insert.

    Field names mirror weather_forecast_snapshots so the mapping is auditable by eye.
    """

    lat: float
    lon: float
    sector_id: str | None
    source: str
    kind: Literal["forecast"]
    source_first_hour_at: datetime | None
    source_last_hour_at: datetime | None
    fetched_at: datetime
    model_run_at: datetime | None
    units: str
    units_original: str | None
    validation_status: ValidationStatus
    dropped_value_count: int
    validation_notes: list[str]
    hours: list[dict[str, Any]]
    total_mm: float | None
    max_hourly_mm: float | None
    stale_at_write: bool

    def as_params(self) -> tuple:
        """Ordered parameters matching the INSERT in `persist_forecast`."""
        return (
            round(self.lat, 6),
            round(self.lon, 6),
            self.sector_id,
            self.source,
            self.kind,
            self.source_first_hour_at,
            self.source_last_hour_at,
            self.fetched_at,
            self.model_run_at,
            self.units,
            self.units_original,
            self.validation_status,
            self.dropped_value_count,
            json.dumps(self.validation_notes),
            json.dumps(self.hours),
            self.total_mm,
            self.max_hourly_mm,
            self.stale_at_write,
        )


@dataclass(frozen=True)
class PersistOutcome:
    """What happened, without claiming more than it knows."""

    stored: bool
    reason: Literal["inserted", "duplicate", "nothing_usable", "db_error"]
    snapshot_id: int | None = None
    detail: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Row construction
# ---------------------------------------------------------------------------


def build_snapshot(
    result: ForecastResult,
    *,
    sector_id: str | None,
    stale_after_s: int,
    now: datetime,
) -> SnapshotRow | None:
    """Convert an adapter result into a snapshot row.

    Returns None when the result has nothing usable — a failed fetch is not persisted as an
    empty "success", because a row claiming `validation_status='ok'` with no hours would
    misrepresent a provider outage as a valid forecast of zero rain.
    """
    if not result.ok:
        return None
    if not result.hours:
        return None
    if result.latitude is None or result.longitude is None:
        raise PersistenceError("successful result must carry coordinates")

    hours = list(result.hours)
    gaps = sum(1 for h in hours if h.precipitation_mm is None)
    dropped = gaps
    notes = list(result.notes)

    if dropped >= PARTIAL_DROPPED_THRESHOLD:
        status: ValidationStatus = "partial"
        notes.append(
            f"{dropped} hour(s) had no precipitation value; stored as gaps, not as zero"
        )
    else:
        status = "ok"

    age_s = result.age_seconds(now)
    stale = age_s is not None and age_s > stale_after_s

    return SnapshotRow(
        lat=result.latitude,
        lon=result.longitude,
        sector_id=sector_id,
        source=result.source,
        # Always 'forecast'. An observation would need a different adapter and label.
        kind="forecast",
        source_first_hour_at=hours[0].at,
        source_last_hour_at=hours[-1].at,
        fetched_at=result.fetched_at or now,
        # Copied verbatim. None stays None (N-1).
        model_run_at=result.model_run_at,
        units="mm",
        units_original=result.provider_units_original,
        validation_status=status,
        dropped_value_count=dropped,
        validation_notes=notes,
        hours=[_hour_to_dict(h) for h in hours],
        total_mm=result.total_mm,
        max_hourly_mm=result.max_hourly_mm,
        stale_at_write=stale,
    )


def _hour_to_dict(h: HourlyRain) -> dict[str, Any]:
    """Serialise one hour. `null` precipitation is preserved, never coerced to 0."""
    return {
        "at": h.at.isoformat(),
        "precipitation_mm": h.precipitation_mm,
        "probability_pct": h.probability_pct,
        "kind": h.kind,
    }


# ---------------------------------------------------------------------------
# The INSERT statement, kept beside the parameters it binds
# ---------------------------------------------------------------------------

INSERT_SQL = """
insert into weather_forecast_snapshots (
    lat, lon, sector_id, source, kind,
    source_first_hour_at, source_last_hour_at,
    fetched_at, model_run_at,
    units, units_original,
    validation_status, dropped_value_count, validation_notes,
    hours, total_mm, max_hourly_mm, stale_at_write
) values (
    $1, $2, $3, $4, $5,
    $6, $7,
    $8, $9,
    $10, $11,
    $12, $13, $14,
    $15::jsonb, $16, $17, $18
)
on conflict (source, lat, lon, fetched_at, model_run_at) do nothing
returning id
"""

# `on conflict do nothing` is what makes repeated fetches idempotent instead of overwriting.
# A second identical fetch inserts nothing and returns no id, which the service reports as
# 'duplicate' rather than pretending it stored something new.
#
# The conflict target matches the table's UNIQUE NULLS NOT DISTINCT constraint, which is
# required because model_run_at is NULL for every Open-Meteo fetch (N-1). Without
# NULLS NOT DISTINCT, two NULL model_run_at rows would be considered distinct and duplicate
# detection would silently do nothing in exactly the case this project produces.

ExecuteFn = Callable[[str, Sequence[Any]], int | None]


def persist_forecast(
    result: ForecastResult,
    *,
    sector_id: str | None,
    stale_after_s: int,
    now: datetime,
    execute: ExecuteFn,
) -> PersistOutcome:
    """Persist one validated forecast. Never raises for a provider failure.

    `execute(sql, params) -> inserted_id | None` is injected. It must run with a trusted,
    server-side connection; the service never accepts credentials or a role from a caller.
    """
    row = build_snapshot(result, sector_id=sector_id, stale_after_s=stale_after_s, now=now)
    if row is None:
        return PersistOutcome(
            stored=False,
            reason="nothing_usable",
            detail="provider result was unsuccessful or contained no hours",
            notes=(
                "a failed fetch is not stored as an empty success — that would report a "
                "provider outage as a forecast of zero rain",
            ),
        )

    try:
        inserted_id = execute(INSERT_SQL, row.as_params())
    except Exception as exc:  # noqa: BLE001 - converted to a result, never swallowed silently
        return PersistOutcome(
            stored=False,
            reason="db_error",
            detail=f"{type(exc).__name__}: {exc}",
            notes=("the database rejected the insert; nothing was written",),
        )

    if inserted_id is None:
        return PersistOutcome(
            stored=False,
            reason="duplicate",
            detail="an identical snapshot (same source, location, fetch and model run) exists",
            notes=("history was left untouched; no row was overwritten",),
        )

    return PersistOutcome(
        stored=True,
        reason="inserted",
        snapshot_id=int(inserted_id),
        notes=(
            f"validation_status={row.validation_status}",
            f"model_run_at={'supplied' if row.model_run_at else 'NULL (not supplied by provider)'}",
        ),
    )
