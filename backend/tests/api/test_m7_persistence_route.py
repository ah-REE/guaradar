"""M7 tests — forecast persistence and route API.

Persistence is tested against a fake `execute` callable, so no database is required and no
test depends on live network access. The route API is tested through the FastAPI test client
with an injected clock.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.main import app, build_demo_status, get_graph, get_now
from app.ingest.openmeteo import ForecastResult, HourlyRain
from app.ingest.persistence import (
    INSERT_SQL,
    PersistOutcome,
    SnapshotRow,
    build_snapshot,
    persist_forecast,
)

NOW = datetime(2026, 10, 26, 14, 0, 0, tzinfo=timezone.utc)


def hourly(n: int = 3, precip: list[float | None] | None = None) -> tuple[HourlyRain, ...]:
    if precip is None:
        precip = [1.2, 4.5, 0.0][:n]
    return tuple(
        HourlyRain(
            at=NOW + timedelta(hours=i),
            precipitation_mm=precip[i],
            probability_pct=80.0,
            kind="forecast",
        )
        for i in range(n)
    )


def result(
    ok: bool = True,
    hours: tuple[HourlyRain, ...] | None = None,
    model_run_at: datetime | None = None,
    units: str | None = "mm",
    notes: tuple[str, ...] = (),
) -> ForecastResult:
    h = hours if hours is not None else hourly()
    return ForecastResult(
        ok=ok,
        hours=h,
        source="open-meteo",
        provider_units_original=units,
        model_run_at=model_run_at,
        fetched_at=NOW,
        latitude=-2.1962,
        longitude=-79.8865,
        error=None if ok else "provider unavailable",
        notes=notes,
    )


class FakeDb:
    """Minimal stand-in for a trusted server-side connection."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.next_id = 1
        self.calls: list[tuple[str, tuple]] = []
        self.fail_with: Exception | None = None

    def execute(self, sql: str, params: tuple) -> int | None:
        self.calls.append((sql, params))
        if self.fail_with is not None:
            raise self.fail_with
        # Rebuild the dedupe key from the bound parameters, the same way the generated
        # column does, so duplicate detection is exercised for real.
        lat, lon = params[0], params[1]
        fetched = params[7]
        model_run = params[8]
        fmt = lambda d: "none" if d is None else d.strftime("%Y-%m-%dT%H:%M:%S")
        key = f"{params[3]}|{lat:.6f}|{lon:.6f}|{fmt(fetched)}|{fmt(model_run)}"
        if key in self.rows:
            return None                      # ON CONFLICT DO NOTHING
        rid = self.next_id
        self.next_id += 1
        self.rows[key] = {"id": rid, "params": params}
        return rid


# ===========================================================================
# Persistence — provenance preservation
# ===========================================================================


def test_persist_success_stores_row() -> None:
    db = FakeDb()
    out = persist_forecast(
        result(), sector_id="centro", stale_after_s=3600, now=NOW, execute=db.execute
    )
    assert out.stored is True
    assert out.reason == "inserted"
    assert out.snapshot_id == 1
    assert len(db.rows) == 1


def test_persist_preserves_missing_model_run_as_null() -> None:
    """N-1: no model run time supplied means NULL, never a copy of fetched_at."""
    db = FakeDb()
    persist_forecast(
        result(model_run_at=None), sector_id=None, stale_after_s=3600, now=NOW,
        execute=db.execute,
    )
    (_sql, params), = db.calls
    assert params[8] is None, "model_run_at must be NULL, not filled from fetched_at"
    assert params[7] == NOW, "fetched_at is stored separately and distinctly"


def test_persist_keeps_model_run_when_supplied() -> None:
    db = FakeDb()
    mr = NOW - timedelta(hours=6)
    persist_forecast(
        result(model_run_at=mr), sector_id=None, stale_after_s=3600, now=NOW,
        execute=db.execute,
    )
    (_sql, params), = db.calls
    assert params[8] == mr


def test_persist_always_kind_forecast() -> None:
    db = FakeDb()
    persist_forecast(
        result(), sector_id=None, stale_after_s=3600, now=NOW, execute=db.execute
    )
    (_sql, params), = db.calls
    assert params[4] == "forecast"


def test_persist_units_recorded_both_ways() -> None:
    db = FakeDb()
    persist_forecast(
        result(units="inch"), sector_id=None, stale_after_s=3600, now=NOW,
        execute=db.execute,
    )
    (_sql, params), = db.calls
    assert params[9] == "mm"            # normalised
    assert params[10] == "inch"         # original preserved


def test_persist_gaps_are_partial_not_zero() -> None:
    """A provider gap must be stored as null and flagged, never coerced to 0.0."""
    db = FakeDb()
    h = hourly(3, precip=[1.0, None, 2.0])
    persist_forecast(
        result(hours=h), sector_id=None, stale_after_s=3600, now=NOW, execute=db.execute
    )
    (_sql, params), = db.calls
    assert params[11] == "partial"
    assert params[12] == 1
    stored_hours = json.loads(params[14])
    assert stored_hours[1]["precipitation_mm"] is None


def test_persist_failed_fetch_stores_nothing() -> None:
    """A provider outage must not become a stored 'valid forecast of zero rain'."""
    db = FakeDb()
    out = persist_forecast(
        result(ok=False, hours=()), sector_id=None, stale_after_s=3600, now=NOW,
        execute=db.execute,
    )
    assert out.stored is False
    assert out.reason == "nothing_usable"
    assert db.calls == []
    assert any("not stored as an empty success" in n for n in out.notes)


def test_persist_empty_hours_stores_nothing() -> None:
    db = FakeDb()
    out = persist_forecast(
        result(hours=()), sector_id=None, stale_after_s=3600, now=NOW, execute=db.execute
    )
    assert out.stored is False
    assert out.reason == "nothing_usable"


def test_persist_duplicate_is_idempotent() -> None:
    """Same source/location/fetch/model-run => no second row, history untouched."""
    db = FakeDb()
    first = persist_forecast(
        result(), sector_id=None, stale_after_s=3600, now=NOW, execute=db.execute
    )
    second = persist_forecast(
        result(), sector_id=None, stale_after_s=3600, now=NOW, execute=db.execute
    )
    assert first.stored is True
    assert second.stored is False
    assert second.reason == "duplicate"
    assert len(db.rows) == 1
    assert second.snapshot_id is None


def test_persist_different_fetch_time_creates_new_row() -> None:
    """A genuinely later fetch IS new history and must be kept."""
    db = FakeDb()
    persist_forecast(
        result(), sector_id=None, stale_after_s=3600, now=NOW, execute=db.execute
    )
    later = result()
    later = ForecastResult(**{**later.__dict__, "fetched_at": NOW + timedelta(minutes=15)})
    out = persist_forecast(
        later, sector_id=None, stale_after_s=3600, now=NOW + timedelta(minutes=15),
        execute=db.execute,
    )
    assert out.stored is True
    assert len(db.rows) == 2


def test_persist_db_error_is_reported_not_raised() -> None:
    db = FakeDb()
    db.fail_with = RuntimeError("connection refused")
    out = persist_forecast(
        result(), sector_id=None, stale_after_s=3600, now=NOW, execute=db.execute
    )
    assert out.stored is False
    assert out.reason == "db_error"
    assert "connection refused" in (out.detail or "")


def test_persist_stale_flag_computed_at_write() -> None:
    db = FakeDb()
    late = NOW + timedelta(hours=3)
    persist_forecast(
        result(), sector_id=None, stale_after_s=3600, now=late, execute=db.execute
    )
    (_sql, params), = db.calls
    assert params[17] is True, "stale_at_write should reflect the age at write time"


def test_insert_uses_nulls_not_distinct_conflict_target() -> None:
    """Dedupe must work when model_run_at IS NULL, which is the only real case (N-1).

    A plain UNIQUE constraint treats NULLs as distinct, so two fetches with a NULL model run
    would both insert and history would silently duplicate. The migration uses
    UNIQUE NULLS NOT DISTINCT and the INSERT must target the same columns.
    """
    assert "on conflict (source, lat, lon, fetched_at, model_run_at) do nothing" in INSERT_SQL
    assert "dedupe_key" not in INSERT_SQL


def test_build_snapshot_requires_coordinates_on_success() -> None:
    bad = ForecastResult(**{**result().__dict__, "latitude": None})
    with pytest.raises(Exception):
        build_snapshot(bad, sector_id=None, stale_after_s=3600, now=NOW)


def test_insert_sql_targets_the_history_table() -> None:
    assert "weather_forecast_snapshots" in INSERT_SQL
    assert "on conflict" in INSERT_SQL and "do nothing" in INSERT_SQL
    assert "update" not in INSERT_SQL.lower(), "history must never be updated"


# ===========================================================================
# Route API
# ===========================================================================

# M9: endpoints are derived from the loaded graph rather than hardcoded sensor coordinates.
# With the real OSM extract the sensor sites mostly lie outside the bounded area, so a
# hardcoded pair would make every route refuse. Deriving from nodes tests the routing
# behaviour instead of testing that two specific coordinates happen to exist.
from app.api.main import get_graph as _get_graph

_IDS = sorted(_get_graph().nodes)
ORIGIN = (_get_graph().nodes[_IDS[0]].lat, _get_graph().nodes[_IDS[0]].lon)
DEST = (_get_graph().nodes[_IDS[-1]].lat, _get_graph().nodes[_IDS[-1]].lon)


def route_client() -> TestClient:
    app.dependency_overrides[get_now] = lambda: NOW
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


def test_route_response_shape() -> None:
    with route_client() as c:
        r = c.get(
            f"/api/public/route?from_lat={ORIGIN[0]}&from_lon={ORIGIN[1]}"
            f"&to_lat={DEST[0]}&to_lon={DEST[1]}"
        )
    assert r.status_code == 200
    body = r.json()
    for key in (
        "schema_version", "routes", "refused", "all_routes_hazard_crossing",
        "best_available_is_uncertain", "synthetic", "provenance",
    ):
        assert key in body, f"missing {key}"
    assert body["schema_version"] == "1"
    # M9: the graph may be real OSM (synthetic=False); assert consistency, not a fixed value.
    assert body["synthetic"] is _get_graph().synthetic


def test_route_provenance_propagates() -> None:
    """Disclosures must reach the response, and must match the graph's real source.

    M9: the default graph is now a REAL OSM extract, so the response must say so rather than
    repeating the old "synthetic roads" claim, while still disclosing that road STATUS is seed
    data. Neither claim is skipped.
    """
    with route_client() as c:
        body = c.get(
            f"/api/public/route?from_lat={ORIGIN[0]}&from_lon={ORIGIN[1]}"
            f"&to_lat={DEST[0]}&to_lon={DEST[1]}"
        ).json()

    graph_is_osm = not _get_graph().synthetic
    assert body["synthetic"] is _get_graph().synthetic
    notes = " ".join(body["provenance"]["notes"]).lower()
    if graph_is_osm:
        assert "openstreetmap" in notes or "real" in notes
        assert "status" in notes and "seed" in notes
    else:
        assert "synthetic" in notes
    assert "does not mean a road is safe" in notes
    for route in body["routes"]:
        assert route["synthetic"] is _get_graph().synthetic
        assert all(leg["synthetic"] is _get_graph().synthetic for leg in route["legs"])


def test_route_geometry_is_from_the_graph_only() -> None:
    """Every returned coordinate must exist as a graph node. Nothing is interpolated."""
    graph = get_graph()
    node_coords = {(round(n.lat, 6), round(n.lon, 6)) for n in graph.nodes.values()}
    with route_client() as c:
        body = c.get(
            f"/api/public/route?from_lat={ORIGIN[0]}&from_lon={ORIGIN[1]}"
            f"&to_lat={DEST[0]}&to_lon={DEST[1]}"
        ).json()
    assert body["routes"], "expected at least one route"
    for route in body["routes"]:
        for pt in route["geometry"]:
            assert (round(pt["lat"], 6), round(pt["lon"], 6)) in node_coords


def test_route_phase1_never_crosses_a_closure() -> None:
    """The structural guarantee, re-asserted at the API layer."""
    with route_client() as c:
        body = c.get(
            f"/api/public/route?from_lat={ORIGIN[0]}&from_lon={ORIGIN[1]}"
            f"&to_lat={DEST[0]}&to_lon={DEST[1]}"
        ).json()
    phase1 = [r for r in body["routes"] if r["phase"] == 1]
    for route in phase1:
        assert route["hazard_class"] == "clear"
        assert all(leg["status"] != "closed" for leg in route["legs"]), (
            "a phase-1 route crossed a closed edge"
        )


def test_route_hazard_crossing_never_recommended() -> None:
    with route_client() as c:
        body = c.get(
            f"/api/public/route?from_lat={ORIGIN[0]}&from_lon={ORIGIN[1]}"
            f"&to_lat={DEST[0]}&to_lon={DEST[1]}"
        ).json()
    for route in body["routes"]:
        if route["hazard_class"] == "hazard_crossing":
            assert route["recommended"] is False
            assert route["classification"] == "hazard_crossing"


def test_route_low_coverage_never_recommended() -> None:
    with route_client() as c:
        body = c.get(
            f"/api/public/route?from_lat={ORIGIN[0]}&from_lon={ORIGIN[1]}"
            f"&to_lat={DEST[0]}&to_lon={DEST[1]}"
        ).json()
    for route in body["routes"]:
        if route["band"] in ("low", "none"):
            assert route["recommended"] is False, (
                f"{route['id']} has band {route['band']} but is recommended"
            )


def test_route_at_most_one_recommended() -> None:
    with route_client() as c:
        body = c.get(
            f"/api/public/route?from_lat={ORIGIN[0]}&from_lon={ORIGIN[1]}"
            f"&to_lat={DEST[0]}&to_lon={DEST[1]}"
        ).json()
    assert sum(1 for r in body["routes"] if r["recommended"]) <= 1


def test_route_no_overclaiming_language() -> None:
    with route_client() as c:
        body = c.get(
            f"/api/public/route?from_lat={ORIGIN[0]}&from_lon={ORIGIN[1]}"
            f"&to_lat={DEST[0]}&to_lon={DEST[1]}"
        ).json()
    text = json.dumps(body).lower()
    for banned in ("flood-proof", "risk-free", "guaranteed", "always passable"):
        assert banned not in text
    # "safe" may only appear in negations such as "does not mean a road is safe".
    for route in body["routes"]:
        low = route["label"].lower()
        assert " is safe" not in low
        assert "safe route" not in low


def test_route_refuses_when_snap_too_far() -> None:
    """A point far from the synthetic grid must be refused, not snapped onto a guess."""
    app.dependency_overrides[get_now] = lambda: NOW
    with TestClient(app) as c:
        r = c.get(
            "/api/public/route?from_lat=-2.4000&from_lon=-80.0000"
            f"&to_lat={DEST[0]}&to_lon={DEST[1]}"
        )
    body = r.json()
    assert body["refused"] is True
    assert "nearest road" in (body["refusal_reason"] or "")


def test_route_rejects_coordinates_outside_guayaquil() -> None:
    app.dependency_overrides[get_now] = lambda: NOW
    with TestClient(app) as c:
        r = c.get(
            "/api/public/route?from_lat=51.5&from_lon=-0.1&to_lat=-2.19&to_lon=-79.89"
        )
    assert r.status_code == 422


def test_route_requires_all_coordinates() -> None:
    app.dependency_overrides[get_now] = lambda: NOW
    with TestClient(app) as c:
        r = c.get("/api/public/route?from_lat=-2.14&from_lon=-79.90")
    assert r.status_code == 422


def test_route_alternatives_bounds() -> None:
    app.dependency_overrides[get_now] = lambda: NOW
    with TestClient(app) as c:
        assert c.get(
            f"/api/public/route?from_lat={ORIGIN[0]}&from_lon={ORIGIN[1]}"
            f"&to_lat={DEST[0]}&to_lon={DEST[1]}&alternatives=9"
        ).status_code == 422


def test_route_response_excludes_privileged_fields() -> None:
    forbidden = {
        "created_by", "published_by", "reviewed_by", "reporter_code", "photo_path",
        "service_role", "password", "token", "role", "audit",
    }
    with route_client() as c:
        body = c.get(
            f"/api/public/route?from_lat={ORIGIN[0]}&from_lon={ORIGIN[1]}"
            f"&to_lat={DEST[0]}&to_lon={DEST[1]}"
        ).json()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)

    for key in walk(body):
        assert key.lower() not in forbidden, f"privileged field {key!r} exposed"


def test_route_is_deterministic_for_a_fixed_clock() -> None:
    with route_client() as c:
        a = c.get(
            f"/api/public/route?from_lat={ORIGIN[0]}&from_lon={ORIGIN[1]}"
            f"&to_lat={DEST[0]}&to_lon={DEST[1]}"
        ).json()
        b = c.get(
            f"/api/public/route?from_lat={ORIGIN[0]}&from_lon={ORIGIN[1]}"
            f"&to_lat={DEST[0]}&to_lon={DEST[1]}"
        ).json()
    assert a == b


def test_route_demo_status_is_sparse_enough_for_phase1() -> None:
    """Guards the demo-data tuning: closures must not swallow every path."""
    graph = get_graph()
    status = build_demo_status(NOW)
    closed = sum(1 for eid in graph.edges if status.is_closed(eid))
    assert 0 < closed < len(graph.edges) * 0.05, (
        f"{closed} of {len(graph.edges)} edges closed; too dense for a usable demo"
    )


def test_route_demo_points_are_inside_the_graph() -> None:
    """Route endpoints must be real nodes, so routing is possible at all.

    HISTORICAL NOTE (M9): this test previously asserted that all six sensor sites snapped to
    within 1 m, which held for the synthetic 9 km grid where the sensors were injected as
    nodes. The default graph is now a real OSM extract covering ~1.1 km of central Guayaquil,
    and most sensor sites lie 1–5 km outside it. Rather than move the sensors to make a test
    pass, the test now asserts the property that actually matters: the demo route endpoints
    are genuine graph nodes, and out-of-extract points are refused rather than guessed.
    """
    graph = get_graph()
    from app.api.main import demo_route_points

    points = demo_route_points()
    assert len(points) == 2
    for p in points:
        _nid, dist = graph.nearest_node(p["at"]["lat"], p["at"]["lon"])
        assert dist < 1.0, f"demo point {p['id']} is {dist:.0f} m from any node"


def test_no_mutation_routes_exist_after_m7() -> None:
    """Adding the route endpoint must not have introduced a write verb."""
    for route in app.routes:
        methods = getattr(route, "methods", set()) or set()
        for verb in ("POST", "PUT", "PATCH", "DELETE"):
            assert verb not in methods, f"{verb} {getattr(route, 'path', '')} appeared"
