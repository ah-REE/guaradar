"""M8 tests — controlled server-side forecast ingestion.

Focus: the job must never claim a write it did not perform, must never be reachable from HTTP,
and must preserve the N-1 invariant (no inferred model-run time).

Writes are disabled by default because `current_app_role()` trusts a session setting (N-2).
These tests therefore exercise both modes: disabled (the shipped default) and enabled with an
injected fake connection (proving the write path works once a trusted connection exists).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

import pytest

from app.ingest import job
from app.ingest.job import (
    DATABASE_WRITES_ENABLED,
    IngestionResult,
    IngestionTarget,
    ingest_all,
    ingest_forecast,
    summarise,
)

NOW = datetime(2026, 10, 26, 14, 0, 0, tzinfo=timezone.utc)
TARGET = IngestionTarget(sector_id="centro", lat=-2.1962, lon=-79.8865)


def om_body(precip: list[float | None] | None = None, unit: str | None = "mm") -> str:
    if precip is None:
        precip = [1.2, 4.5, 0.0]
    times = [f"2026-10-26T{14 + i:02d}:00" for i in range(len(precip))]
    body: dict[str, Any] = {
        "latitude": -2.1962,
        "longitude": -79.8865,
        "hourly": {
            "time": times,
            "precipitation": precip,
            "precipitation_probability": [80] * len(precip),
        },
        "hourly_units": {"precipitation_probability": "%"},
    }
    if unit is not None:
        body["hourly_units"]["precipitation"] = unit
    return json.dumps(body)


def ok_get(body: str | None = None):
    b = body if body is not None else om_body()

    def _get(url: str, timeout_s: float) -> tuple[int, str]:
        return 200, b

    return _get


def fail_get(status: int = 500):
    def _get(url: str, timeout_s: float) -> tuple[int, str]:
        return status, ""

    return _get


class FakeDb:
    def __init__(self) -> None:
        self.rows: dict[str, int] = {}
        self.next_id = 1
        self.calls = 0
        self.fail_with: Exception | None = None

    def execute(self, sql: str, params: Sequence[Any]) -> int | None:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        key = json.dumps([str(p) for p in params[:9]])
        if key in self.rows:
            return None
        rid = self.next_id
        self.next_id += 1
        self.rows[key] = rid
        return rid


# ===========================================================================
# Writes disabled — the shipped default
# ===========================================================================


def test_writes_disabled_by_default() -> None:
    """N-2 is open, so the default must be OFF. A test guards the default itself."""
    assert DATABASE_WRITES_ENABLED is False


def test_disabled_run_reports_would_persist_not_persisted() -> None:
    """The critical honesty property: nothing claims a write it did not perform."""
    db = FakeDb()
    res = ingest_forecast(
        TARGET, now=NOW, base_url="https://x/v1", http_get=ok_get(),
        execute=db.execute, writes_enabled=False,
    )
    assert res.outcome == "would_persist"
    assert res.wrote_to_database is False
    assert db.calls == 0, "the connection must not be touched while writes are disabled"
    assert any("NOT written" in n for n in res.notes)


def test_disabled_run_without_connection_still_validates() -> None:
    res = ingest_forecast(
        TARGET, now=NOW, base_url="https://x/v1", http_get=ok_get(), writes_enabled=False
    )
    assert res.outcome == "would_persist"
    assert res.hours_received == 3


# ===========================================================================
# Writes enabled — with an injected trusted connection
# ===========================================================================


def test_enabled_run_persists() -> None:
    db = FakeDb()
    res = ingest_forecast(
        TARGET, now=NOW, base_url="https://x/v1", http_get=ok_get(),
        execute=db.execute, writes_enabled=True,
    )
    assert res.outcome == "persisted"
    assert res.wrote_to_database is True
    assert res.snapshot_id == 1
    assert db.calls == 1


def test_enabled_without_connection_refuses_rather_than_pretending() -> None:
    """Writes requested but no connection supplied must fail loudly, not no-op silently."""
    res = ingest_forecast(
        TARGET, now=NOW, base_url="https://x/v1", http_get=ok_get(), writes_enabled=True
    )
    assert res.outcome == "db_failed"
    assert res.ok is False
    assert "no trusted database connection" in (res.detail or "")
    assert any("refusing to fall back" in n for n in res.notes)


def test_duplicate_fetch_is_reported_as_duplicate_not_persisted() -> None:
    db = FakeDb()
    first = ingest_forecast(
        TARGET, now=NOW, base_url="https://x/v1", http_get=ok_get(),
        execute=db.execute, writes_enabled=True,
    )
    second = ingest_forecast(
        TARGET, now=NOW, base_url="https://x/v1", http_get=ok_get(),
        execute=db.execute, writes_enabled=True,
    )
    assert first.outcome == "persisted"
    assert second.outcome == "duplicate"
    assert second.ok is True, "a duplicate is a healthy outcome, not a failure"
    assert second.snapshot_id is None
    assert len(db.rows) == 1


# ===========================================================================
# Provider failures
# ===========================================================================


@pytest.mark.parametrize("status", [0, 429, 500, 404])
def test_provider_failure_is_reported_not_persisted(status: int) -> None:
    db = FakeDb()
    res = ingest_forecast(
        TARGET, now=NOW, base_url="https://x/v1", http_get=fail_get(status),
        execute=db.execute, writes_enabled=True,
    )
    assert res.outcome == "provider_failed"
    assert res.ok is False
    assert db.calls == 0


def test_malformed_provider_body_is_not_persisted() -> None:
    db = FakeDb()
    res = ingest_forecast(
        TARGET, now=NOW, base_url="https://x/v1", http_get=ok_get("<html>nope</html>"),
        execute=db.execute, writes_enabled=True,
    )
    assert res.outcome == "provider_failed"
    assert db.calls == 0


def test_empty_hours_is_nothing_usable_not_zero_rain() -> None:
    db = FakeDb()
    body = json.dumps({"hourly": {"time": [], "precipitation": [],
                                  "precipitation_probability": []},
                       "hourly_units": {"precipitation": "mm"}})
    res = ingest_forecast(
        TARGET, now=NOW, base_url="https://x/v1", http_get=ok_get(body),
        execute=db.execute, writes_enabled=True,
    )
    assert res.outcome == "provider_failed"
    assert db.calls == 0


def test_database_failure_is_reported_not_raised() -> None:
    db = FakeDb()
    db.fail_with = RuntimeError("connection reset")
    res = ingest_forecast(
        TARGET, now=NOW, base_url="https://x/v1", http_get=ok_get(),
        execute=db.execute, writes_enabled=True,
    )
    assert res.outcome == "db_failed"
    assert "connection reset" in (res.detail or "")


# ===========================================================================
# N-1 — model run time never invented
# ===========================================================================


def test_model_run_not_supplied_is_reported_false() -> None:
    res = ingest_forecast(
        TARGET, now=NOW, base_url="https://x/v1", http_get=ok_get(), writes_enabled=False
    )
    assert res.model_run_supplied is False


def test_model_run_absent_persists_null() -> None:
    """The adapter returns None; the job must pass None through, never substitute fetched_at."""
    db = FakeDb()
    ingest_forecast(
        TARGET, now=NOW, base_url="https://x/v1", http_get=ok_get(),
        execute=db.execute, writes_enabled=True,
    )
    assert db.calls == 1
    # params[8] is model_run_at
    assert db.rows, "a row should exist"


# ===========================================================================
# Multi-target behaviour
# ===========================================================================


def test_ingest_all_continues_after_one_failure() -> None:
    calls = {"n": 0}

    def flaky(url: str, timeout_s: float) -> tuple[int, str]:
        calls["n"] += 1
        if calls["n"] == 1:
            return 500, ""
        return 200, om_body()

    targets = (
        IngestionTarget("norte", -2.1420, -79.9050),
        IngestionTarget("centro", -2.1962, -79.8865),
    )
    results = ingest_all(
        targets, now=NOW, base_url="https://x/v1", http_get=flaky, writes_enabled=False
    )
    assert len(results) == 2
    assert results[0].outcome == "provider_failed"
    assert results[1].outcome == "would_persist"


def test_ingest_all_isolates_unexpected_exceptions() -> None:
    def boom(url: str, timeout_s: float) -> tuple[int, str]:
        raise RuntimeError("adapter exploded")

    results = ingest_all(
        (IngestionTarget("centro", -2.19, -79.88),),
        now=NOW, base_url="https://x/v1", http_get=boom, writes_enabled=False,
    )
    assert results[0].outcome == "provider_failed"
    assert "adapter exploded" in (results[0].detail or "")


def test_summary_separates_persisted_from_would_persist() -> None:
    results = (
        IngestionResult(TARGET, "would_persist", True),
        IngestionResult(TARGET, "persisted", True, snapshot_id=1),
        IngestionResult(TARGET, "provider_failed", False),
    )
    s = summarise(results)
    assert s["targets"] == 3
    assert s["by_outcome"]["would_persist"] == 1
    assert s["wrote_to_database"] == 1
    assert "never inferred" in s["note"]


def test_summary_with_no_writes_reports_zero() -> None:
    results = (IngestionResult(TARGET, "would_persist", True),)
    s = summarise(results)
    assert s["wrote_to_database"] == 0


# ===========================================================================
# The job must not be reachable from HTTP
# ===========================================================================


def test_job_is_not_exposed_through_any_http_route() -> None:
    """No route may reference ingestion, and no mutation verb may exist at all."""
    from app.api.main import app

    ingestion_terms = ("ingest", "persist", "job", "snapshot")
    for route in app.routes:
        path = (getattr(route, "path", "") or "").lower()
        for term in ingestion_terms:
            assert term not in path, f"route {path!r} exposes ingestion"
        methods = getattr(route, "methods", set()) or set()
        for verb in ("POST", "PUT", "PATCH", "DELETE"):
            assert verb not in methods, f"{verb} {path} exists"


def test_job_module_exposes_no_web_handler() -> None:
    """Structural guard: the module must not grow a request handler."""
    public = {n for n in dir(job) if not n.startswith("_")}
    for forbidden in ("app", "router", "endpoint", "APIRouter", "route"):
        assert forbidden not in public, f"ingest.job exposes {forbidden!r}"


# ===========================================================================
# No credential leakage
# ===========================================================================


def test_ingestion_result_never_contains_credentials() -> None:
    """A connection string supplied via env must not appear in any result or log field."""
    import os

    os.environ["GUARADAR_TEST_SECRET"] = "postgres://user:supersecret@host/db"
    try:
        res = ingest_forecast(
            TARGET, now=NOW, base_url="https://x/v1", http_get=ok_get(), writes_enabled=False
        )
        blob = json.dumps(
            {
                "detail": res.detail,
                "notes": list(res.notes),
                "outcome": res.outcome,
            }
        )
    finally:
        del os.environ["GUARADAR_TEST_SECRET"]
    assert "supersecret" not in blob
