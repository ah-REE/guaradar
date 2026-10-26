"""M8 tests — database-backed road status.

Two clearly separated groups:

  * MOCKED REPOSITORY tests (the majority): a fake `fetch` returns rows, so the adapter logic,
    staleness handling and failure paths are exercised with no database.
  * REAL POSTGRESQL integration tests (`@pytest.mark.integration`): skipped unless
    GUARADAR_PG_DSN is set, because this suite must not depend on a running server. Their
    results are reported separately in docs/M8-EVIDENCE.md — a mocked test is NOT evidence
    that real PostgreSQL behaves the same way.

The mapping question is the heart of this milestone: `road_status.road_segment_id` (1001+,
from seed.sql) and graph `Edge.id` (0+, from build_synthetic_grid) are **independent synthetic
generators with no shared identifier**. These tests assert that the repository refuses to
guess a correspondence.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.routing.graph import (
    STATUS_AFFECTED,
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_UNKNOWN,
    DEFAULT_FRESHNESS,
    Edge,
    RoadGraph,
    StatusIndex,
)
from app.routing.status_repository import (
    SELECT_SQL,
    RepositoryError,
    RoadStatusRecord,
    build_status_index,
    load_status,
)

NOW = datetime(2026, 10, 26, 14, 0, 0, tzinfo=timezone.utc)


def row(
    seg_id: int,
    status: str = STATUS_OPEN,
    age_min: int = 5,
    review_at: datetime | None = None,
    source: str = "operator",
    reason: str | None = None,
) -> list:
    return [seg_id, status, NOW - timedelta(minutes=age_min), review_at, source, reason]


# ===========================================================================
# Record validation
# ===========================================================================


def test_record_parses_valid_row() -> None:
    rec = RoadStatusRecord.from_row(row(1001, STATUS_OPEN))
    assert rec.road_segment_id == 1001
    assert rec.status == STATUS_OPEN
    assert rec.source == "operator"


@pytest.mark.parametrize(
    "bad,reason",
    [
        ([1001, "open", NOW], "expected >= 5 columns"),
        (["1001", "open", NOW, None, "operator"], "road_segment_id must be int"),
        ([1001, "flooded", NOW, None, "operator"], "unknown status"),
        ([1001, "open", NOW, None, "hacker"], "unknown source"),
        ([1001, "open", "not-a-date", None, "operator"], "set_at must be a datetime"),
    ],
)
def test_record_rejects_malformed_rows(bad: list, reason: str) -> None:
    with pytest.raises(RepositoryError, match=reason):
        RoadStatusRecord.from_row(bad)


def test_closed_without_reason_is_rejected() -> None:
    """The table has a CHECK for this, so its absence means a bad query, not a valid row."""
    with pytest.raises(RepositoryError, match="no reason"):
        RoadStatusRecord.from_row(row(1001, STATUS_CLOSED))


def test_closed_with_reason_accepted() -> None:
    rec = RoadStatusRecord.from_row(row(1001, STATUS_CLOSED, reason="water across road"))
    assert rec.status == STATUS_CLOSED
    assert rec.reason == "water across road"


# ===========================================================================
# Staleness
# ===========================================================================


def test_record_stale_by_review_deadline() -> None:
    rec = RoadStatusRecord.from_row(
        row(1, STATUS_OPEN, review_at=NOW - timedelta(minutes=1))
    )
    assert rec.is_stale(NOW, DEFAULT_FRESHNESS) is True


def test_record_fresh_inside_review_deadline() -> None:
    rec = RoadStatusRecord.from_row(
        row(1, STATUS_OPEN, review_at=NOW + timedelta(minutes=30))
    )
    assert rec.is_stale(NOW, DEFAULT_FRESHNESS) is False


def test_record_stale_by_age_when_no_review_at() -> None:
    rec = RoadStatusRecord.from_row(row(1, STATUS_OPEN, age_min=600))
    assert rec.is_stale(NOW, DEFAULT_FRESHNESS) is True


# ===========================================================================
# Mapping: the core of M8
# ===========================================================================


def test_unmatched_records_are_dropped_not_remapped() -> None:
    """A record for a segment that is not a graph edge must NOT be applied to some other edge."""
    records = [RoadStatusRecord.from_row(row(1001, STATUS_CLOSED, reason="demo"))]
    index, matched, notes = build_status_index(
        records, {0, 1, 2}, now=NOW, default_freshness=DEFAULT_FRESHNESS
    )
    assert matched == 0, "a 1001+ segment id must not match a 0+ graph edge id"
    assert index.status_of(0) == STATUS_UNKNOWN
    assert any("not remapped" in n for n in notes)


def test_matched_record_is_applied() -> None:
    records = [RoadStatusRecord.from_row(row(7, STATUS_CLOSED, reason="water"))]
    index, matched, _ = build_status_index(
        records, {0, 7, 9}, now=NOW, default_freshness=DEFAULT_FRESHNESS
    )
    assert matched == 1
    assert index.status_of(7) == STATUS_CLOSED


def test_unknown_status_record_adds_nothing() -> None:
    records = [RoadStatusRecord.from_row(row(1, STATUS_UNKNOWN))]
    index, matched, _ = build_status_index(
        records, {1}, now=NOW, default_freshness=DEFAULT_FRESHNESS
    )
    assert matched == 1
    assert index.status_of(1) == STATUS_UNKNOWN


# ===========================================================================
# Provenance states survive the adaption
# ===========================================================================


@pytest.mark.parametrize("status", [STATUS_OPEN, STATUS_AFFECTED, STATUS_CLOSED])
def test_verified_states_are_applied(status: str) -> None:
    records = [RoadStatusRecord.from_row(row(3, status, reason="r" if status == STATUS_CLOSED else None))]
    index, _, _ = build_status_index(
        records, {3}, now=NOW, default_freshness=DEFAULT_FRESHNESS
    )
    assert index.status_of(3) == status


def test_verified_open_counts_toward_coverage() -> None:
    records = [RoadStatusRecord.from_row(row(3, STATUS_OPEN))]
    index, _, _ = build_status_index(
        records, {3}, now=NOW, default_freshness=DEFAULT_FRESHNESS
    )
    assert index.is_verified(3) is True


def test_closed_is_not_verified_coverage() -> None:
    """A closure tells you the road is impassable; it does not verify travel is fine."""
    records = [RoadStatusRecord.from_row(row(3, STATUS_CLOSED, reason="flooded"))]
    index, _, _ = build_status_index(
        records, {3}, now=NOW, default_freshness=DEFAULT_FRESHNESS
    )
    assert index.is_verified(3) is False
    assert index.is_closed(3) is True


def test_stale_record_no_longer_counts_as_verified() -> None:
    records = [
        RoadStatusRecord.from_row(
            row(3, STATUS_OPEN, review_at=NOW - timedelta(hours=1))
        )
    ]
    index, _, notes = build_status_index(
        records, {3}, now=NOW, default_freshness=DEFAULT_FRESHNESS
    )
    assert index.is_verified(3) is False
    assert any("past their review deadline" in n for n in notes)


def test_stale_closure_remains_excluded_o8() -> None:
    """O-8 provisional rule, re-asserted through the database path.

    A closure past its review deadline still excludes the edge from phase 1. Ageing a closure
    must not quietly reopen the road; staleness only removes its verified-coverage credit.
    """
    records = [
        RoadStatusRecord.from_row(
            row(3, STATUS_CLOSED, age_min=600, review_at=NOW - timedelta(hours=5),
                reason="closed long ago")
        )
    ]
    index, _, _ = build_status_index(
        records, {3}, now=NOW, default_freshness=DEFAULT_FRESHNESS
    )
    assert index.is_closed(3) is True, "a stale closure must still exclude the edge"
    assert index.is_verified(3) is False, "but it must not count as verified coverage"


def test_missing_record_stays_unknown() -> None:
    """Absence of a record is never clear, never safe."""
    index, matched, _ = build_status_index(
        [], {0, 1, 2}, now=NOW, default_freshness=DEFAULT_FRESHNESS
    )
    assert matched == 0
    for eid in (0, 1, 2):
        assert index.status_of(eid) == STATUS_UNKNOWN
        assert index.is_verified(eid) is False


# ===========================================================================
# load_status: fetching, disabling, failure
# ===========================================================================


def test_load_disabled_yields_all_unknown_and_says_so() -> None:
    def never_called(sql: str):
        raise AssertionError("fetch must not be called when disabled")

    res = load_status(
        graph_edge_ids={0, 1}, fetch=never_called, now=NOW,
        default_freshness=DEFAULT_FRESHNESS, enabled=False,
    )
    assert res.ok
    assert res.records_fetched == 0
    assert res.index.status_of(0) == STATUS_UNKNOWN
    assert any("not enabled" in n for n in res.notes)
    assert any("not the same as clear" in n for n in res.notes)


def test_load_success_reports_counts() -> None:
    def fetch(sql: str):
        assert "road_status" in sql
        return [row(5, STATUS_OPEN), row(9999, STATUS_OPEN)]

    res = load_status(
        graph_edge_ids={5}, fetch=fetch, now=NOW,
        default_freshness=DEFAULT_FRESHNESS, enabled=True,
    )
    assert res.ok
    assert res.records_fetched == 2
    assert res.matched_edge_count == 1
    assert res.unmapped == 1
    assert res.index.status_of(5) == STATUS_OPEN


def test_load_db_error_degrades_to_unknown_not_clear() -> None:
    def fetch(sql: str):
        raise RuntimeError("connection refused")

    res = load_status(
        graph_edge_ids={0}, fetch=fetch, now=NOW,
        default_freshness=DEFAULT_FRESHNESS, enabled=True,
    )
    assert res.ok is False
    assert "connection refused" in (res.error or "")
    assert res.index.status_of(0) == STATUS_UNKNOWN
    assert any("unknown" in n for n in res.notes)


def test_load_empty_result_is_all_unknown() -> None:
    res = load_status(
        graph_edge_ids={0, 1}, fetch=lambda sql: [], now=NOW,
        default_freshness=DEFAULT_FRESHNESS, enabled=True,
    )
    assert res.ok
    assert res.records_fetched == 0
    assert res.matched_edge_count == 0
    assert res.index.status_of(0) == STATUS_UNKNOWN


def test_load_skips_malformed_row_but_keeps_good_ones() -> None:
    def fetch(sql: str):
        return [row(5, STATUS_OPEN), ["bad", "row"], row(6, STATUS_AFFECTED)]

    res = load_status(
        graph_edge_ids={5, 6}, fetch=fetch, now=NOW,
        default_freshness=DEFAULT_FRESHNESS, enabled=True,
    )
    assert res.ok
    assert res.records_fetched == 2, "the malformed row is skipped, not counted as usable"
    assert res.matched_edge_count == 2
    assert any("skipped malformed row" in n for n in res.notes)


def test_select_sql_omits_operator_identity() -> None:
    """`set_by` is operator identity and must never reach a public response path."""
    assert "set_by" not in SELECT_SQL
    assert "road_status" in SELECT_SQL


# ===========================================================================
# Integration with the routing engine (mocked repository)
# ===========================================================================


def line_graph(n: int = 4) -> tuple[RoadGraph, list[int]]:
    coords = {i: (-2.19 + i * 0.0009, -79.89) for i in range(n + 1)}
    edges = [Edge(i, i, i + 1, 100.0, name=f"e{i}") for i in range(n)]
    return RoadGraph.from_edges(coords, edges, synthetic=True), [e.id for e in edges]


def test_route_phase1_avoids_a_persisted_closure() -> None:
    """A closure read from the database must be excluded from phase 1, same as before."""
    from app.routing.search import find_routes

    g, ids = line_graph(3)
    records = [RoadStatusRecord.from_row(row(ids[1], STATUS_CLOSED, reason="flooded"))]
    index, matched, _ = build_status_index(
        records, set(g.edges), now=NOW, default_freshness=DEFAULT_FRESHNESS
    )
    assert matched == 1

    resp = find_routes(g, index, g.nodes[0].coord, g.nodes[3].coord)
    for r in resp.routes:
        if r.phase == 1:
            assert all(leg.status != STATUS_CLOSED for leg in r.legs)


def test_losing_evidence_via_repository_never_improves_recommendation() -> None:
    """The dangerous direction, through the database path.

    Withdrawing persisted status must never promote a route to recommended.
    """
    from app.routing.search import find_routes

    g, ids = line_graph(4)
    all_open = [RoadStatusRecord.from_row(row(e, STATUS_OPEN)) for e in ids]
    index_full, _, _ = build_status_index(
        all_open, set(g.edges), now=NOW, default_freshness=DEFAULT_FRESHNESS
    )
    full = find_routes(g, index_full, g.nodes[0].coord, g.nodes[4].coord).routes[0]
    assert full.band == "high"

    # Remove half the records: coverage falls, recommendation must not appear.
    half_open = [RoadStatusRecord.from_row(row(e, STATUS_OPEN)) for e in ids[:2]]
    index_half, _, _ = build_status_index(
        half_open, set(g.edges), now=NOW, default_freshness=DEFAULT_FRESHNESS
    )
    half = find_routes(g, index_half, g.nodes[0].coord, g.nodes[4].coord).routes[0]
    assert half.coverage_pct < full.coverage_pct
    assert not (half.recommended and not full.recommended), "removing evidence promoted a route"


def test_empty_repository_yields_zero_coverage_and_no_recommendation() -> None:
    from app.routing.search import find_routes

    g, ids = line_graph(3)
    index, _, _ = build_status_index(
        [], set(g.edges), now=NOW, default_freshness=DEFAULT_FRESHNESS
    )
    resp = find_routes(g, index, g.nodes[0].coord, g.nodes[3].coord)
    assert resp.routes
    for r in resp.routes:
        assert r.coverage_pct == pytest.approx(0.0)
        assert r.band == "none"
        assert r.recommended is False
    assert resp.best_available_is_uncertain is True


# ===========================================================================
# Real PostgreSQL integration — opt-in only
# ===========================================================================

PG_DSN = os.environ.get("GUARADAR_PG_DSN")

pytestmark_integration = pytest.mark.skipif(
    not PG_DSN,
    reason="set GUARADAR_PG_DSN to run real-PostgreSQL integration tests",
)


def _pg_fetch_factory(dsn: str):
    """Return a `fetch` callable backed by a real PostgreSQL connection.

    Uses psql rather than a driver: no new dependency, and the exact SQL in SELECT_SQL is what
    runs. Output is parsed as tab-separated values.
    """
    import subprocess

    def fetch(sql: str):
        proc = subprocess.run(
            [os.environ.get("GUARADAR_PSQL", "psql"), "-X", "-q", "-t", "-A", "-F",
             "\x1f", "-d", dsn, "-c", sql],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip()[:200] or "psql failed")
        out = []
        for line in proc.stdout.splitlines():
            if not line.strip():
                continue
            f = line.split("\x1f")
            out.append([
                int(f[0]),
                f[1],
                datetime.fromisoformat(f[2]),
                datetime.fromisoformat(f[3]) if f[3] else None,
                f[4],
                f[5] if len(f) > 5 and f[5] else None,
            ])
        return out

    return fetch


def _pg_row_count(dsn: str) -> int:
    """How many road_status rows exist. The test adapts to whatever the database holds."""
    import subprocess

    proc = subprocess.run(
        [os.environ.get("GUARADAR_PSQL", "psql"), "-X", "-q", "-t", "-A", "-d", dsn,
         "-c", "select count(*) from road_status;"],
        capture_output=True, text=True, timeout=30,
    )
    return int(proc.stdout.strip() or 0)


@pytestmark_integration
def test_pg_real_fetch_roundtrip() -> None:
    """Reads genuine rows from a real PostgreSQL database.

    M9 NOTE: this test used to require the five seeded demo rows (segment ids 1001+). It now
    adapts to whatever the database actually contains, because the M9 work moved the primary
    data path to real OSM segments. Requiring specific legacy ids would test fixture state
    rather than the read path.
    """
    if _pg_row_count(PG_DSN) == 0:
        pytest.skip("no road_status rows in this database; nothing to read")

    res = load_status(
        graph_edge_ids={1001, 1002, 2001, 3001, 3002},
        fetch=_pg_fetch_factory(PG_DSN),
        now=datetime.now(timezone.utc),
        default_freshness=timedelta(days=3650),          # ignore staleness for this assertion
        enabled=True,
    )
    assert res.ok, f"fetch failed: {res.error}"
    assert res.records_fetched >= 1, f"expected rows, got {res.records_fetched}"


@pytestmark_integration
def test_pg_legacy_join_does_not_match_real_osm_edges() -> None:
    """The legacy `road_segment_id` join must never match a real OSM graph edge.

    M9 NOTE: this test previously asserted a zero match against the *synthetic* graph. The
    default graph is now real OSM, so the assertion is restated in the form that still matters:
    the legacy id space (1001+) and the OSM edge-id space (way_id * 1000 + ordinal) are
    disjoint, so no legacy record may ever be applied to a real edge by accident. A non-zero
    match here would mean a collision has been introduced.
    """
    from app.api.main import get_graph

    graph = get_graph()
    res = load_status(
        graph_edge_ids=graph.edges.keys(),
        fetch=_pg_fetch_factory(PG_DSN),
        now=datetime.now(timezone.utc),
        default_freshness=timedelta(days=3650),
        enabled=True,
    )
    assert res.ok
    # Whether rows exist depends on fixture state; the invariant is the match count.
    assert res.matched_edge_count == 0, (
        "legacy road_segment_id values must not coincide with real OSM edge ids; if this "
        "fires, a collision has been introduced"
    )
