"""Controlled server-side forecast ingestion (N-6).

Orchestrates: adapter fetch -> validate/normalise -> persist via the existing append-only
snapshot library. **No HTTP route calls this.** There is no public POST/PUT/PATCH/DELETE in
the application, and this module deliberately exposes no web-facing entry point.

AUTHORIZATION GATE — READ THIS BEFORE ENABLING WRITES
  `current_app_role()` trusts a session setting (`guaradar.role`), so it is **not proof of
  identity**. N-2 remains open. Therefore:

    * `DATABASE_WRITES_ENABLED` defaults to **False**.
    * With writes disabled the job still fetches, validates and reports what it *would* have
      written, using a no-op execute. Nothing reaches the database.
    * Enabling writes requires an operator to supply a trusted, server-side connection. The
      job never accepts a role, user id, or verification flag from any caller, and never reads
      them from a request.
    * No credentials appear in this file, in logs, or in the evidence report.

  This is intentionally a deployment prerequisite rather than a code workaround. A
  session-settable role must not be able to authorise a database write.

WHAT IT REFUSES TO DO
  * Publish alerts. It writes forecast snapshots and nothing else.
  * Touch risk-policy parameters, weights, thresholds or the disabled heavy-rain floor.
  * Turn a forecast into an observation, or a simulated sensor reading into telemetry.
  * Infer a model-run time (N-1): a missing value is persisted as NULL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal, Sequence

from app.ingest.openmeteo import ForecastResult, fetch_forecast
from app.ingest.persistence import PersistOutcome, build_snapshot, persist_forecast

log = logging.getLogger(__name__)

# Writes are OFF by default until a trusted connection exists (N-2). Flipping this requires a
# deployment change, not a request parameter.
DATABASE_WRITES_ENABLED = False

SNAPSHOT_STALE_AFTER_S = 3600

Outcome = Literal[
    "persisted", "would_persist", "duplicate", "provider_failed", "nothing_usable", "db_failed",
]


@dataclass(frozen=True)
class IngestionTarget:
    """One location to ingest. Named sectors keep the job declarative."""

    sector_id: str
    lat: float
    lon: float


@dataclass(frozen=True)
class IngestionResult:
    """Per-target outcome. `detail` never contains credentials or connection strings."""

    target: IngestionTarget
    outcome: Outcome
    ok: bool
    snapshot_id: int | None = None
    detail: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
    hours_received: int = 0
    model_run_supplied: bool = False

    @property
    def wrote_to_database(self) -> bool:
        return self.outcome == "persisted"


HttpGet = Callable[[str, float], tuple[int, str]]
ExecuteFn = Callable[[str, Sequence[Any]], int | None]


def ingest_forecast(
    target: IngestionTarget,
    *,
    now: datetime,
    base_url: str,
    http_get: HttpGet,
    execute: ExecuteFn | None = None,
    writes_enabled: bool | None = None,
    forecast_hours: int = 24,
) -> IngestionResult:
    """Run one ingestion for one target. Never raises for provider or database failure.

    `execute` must be a trusted server-side connection when writes are enabled. If it is None
    or writes are disabled, the job validates the full path and reports `would_persist`.
    """
    enabled = DATABASE_WRITES_ENABLED if writes_enabled is None else writes_enabled

    # Fetch first: both the disabled and enabled paths need a validated provider result.
    result: ForecastResult = fetch_forecast(
        base_url=base_url,
        latitude=target.lat,
        longitude=target.lon,
        now=now,
        http_get=http_get,
        forecast_hours=forecast_hours,
    )

    if not result.ok:
        return IngestionResult(
            target=target,
            outcome="provider_failed",
            ok=False,
            detail=result.error,
            notes=result.notes,
            hours_received=len(result.hours),
            model_run_supplied=result.model_run_at is not None,
        )

    if not enabled:
        # Validate the FULL path (build the row) but never touch the write path.
        #
        # Why not call persist_forecast with a no-op execute: persist_forecast reports
        # reason='duplicate' whenever execute() returns None, and a no-op also returns None.
        # That would report 'duplicate' for a run that never consulted the database — a claim
        # we cannot support. So the disabled path stops before the write entirely and says
        # `would_persist`, which is exactly and only what happened.
        row = build_snapshot(
            result, sector_id=target.sector_id, stale_after_s=SNAPSHOT_STALE_AFTER_S, now=now
        )
        if row is None:
            return IngestionResult(
                target=target,
                outcome="nothing_usable",
                ok=False,
                detail="provider result contained no usable hours",
                notes=tuple(result.notes),
                hours_received=len(result.hours),
                model_run_supplied=result.model_run_at is not None,
            )
        return IngestionResult(
            target=target,
            outcome="would_persist",
            ok=True,
            snapshot_id=None,
            detail=(
                f"validated {len(row.hours)} hour(s), total {row.total_mm} mm, "
                f"validation_status={row.validation_status}; NOT written"
            ),
            notes=tuple(result.notes) + (
                "database writes are disabled (N-2 open): the snapshot was validated but NOT "
                "written; enable only with a trusted server-side connection",
                "duplicate status is UNKNOWN for a disabled run — the database was not consulted",
            ),
            hours_received=len(result.hours),
            model_run_supplied=result.model_run_at is not None,
        )

    if execute is None:
        # Writes were requested but no trusted connection was supplied. Refuse to pretend.
        return IngestionResult(
            target=target,
            outcome="db_failed",
            ok=False,
            detail="writes are enabled but no trusted database connection was supplied",
            notes=(
                "refusing to fall back to a no-op while claiming success",
                "provide a server-side connection; never a client-supplied role",
            ),
            hours_received=len(result.hours),
            model_run_supplied=result.model_run_at is not None,
        )

    outcome: PersistOutcome = persist_forecast(
        result,
        sector_id=target.sector_id,
        stale_after_s=SNAPSHOT_STALE_AFTER_S,
        now=now,
        execute=execute,
    )

    notes = list(outcome.notes)

    if outcome.reason == "inserted":
        reported: Outcome = "persisted"
        ok = True
    elif outcome.reason == "duplicate":
        # A duplicate is a healthy outcome: history is intact and nothing was overwritten.
        reported = "duplicate"
        ok = True
    elif outcome.reason == "nothing_usable":
        reported = "nothing_usable"
        ok = False
    else:
        reported = "db_failed"
        ok = False

    return IngestionResult(
        target=target,
        outcome=reported,
        ok=ok,
        snapshot_id=outcome.snapshot_id,
        detail=outcome.detail,
        notes=tuple(notes),
        hours_received=len(result.hours),
        model_run_supplied=result.model_run_at is not None,
    )


def ingest_all(
    targets: Sequence[IngestionTarget],
    *,
    now: datetime,
    base_url: str,
    http_get: HttpGet,
    execute: ExecuteFn | None = None,
    writes_enabled: bool | None = None,
    forecast_hours: int = 24,
) -> tuple[IngestionResult, ...]:
    """Ingest every target. One failure does not abort the others — a partial feed is normal."""
    out: list[IngestionResult] = []
    for t in targets:
        try:
            res = ingest_forecast(
                t,
                now=now,
                base_url=base_url,
                http_get=http_get,
                execute=execute,
                writes_enabled=writes_enabled,
                forecast_hours=forecast_hours,
            )
        except Exception as exc:  # noqa: BLE001 - a single target must not kill the run
            res = IngestionResult(
                target=t,
                outcome="provider_failed",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
                notes=("this target failed; other targets were still attempted",),
            )
        # Log the outcome, never credentials or the connection string.
        log.info(
            "ingest sector=%s outcome=%s hours=%d model_run_supplied=%s",
            res.target.sector_id, res.outcome, res.hours_received, res.model_run_supplied,
        )
        out.append(res)
    return tuple(out)


def summarise(results: Sequence[IngestionResult]) -> dict[str, Any]:
    """Aggregate counts. Reports `would_persist` separately from `persisted`, always."""
    counts: dict[str, int] = {}
    for r in results:
        counts[r.outcome] = counts.get(r.outcome, 0) + 1
    return {
        "targets": len(results),
        "by_outcome": counts,
        "wrote_to_database": sum(1 for r in results if r.wrote_to_database),
        "database_writes_enabled": any(r.outcome == "persisted" for r in results),
        "model_run_supplied_count": sum(1 for r in results if r.model_run_supplied),
        "note": (
            "model_run_supplied=false means the provider omitted it and NULL was persisted "
            "(N-1); it is never inferred from the fetch time"
        ),
    }
