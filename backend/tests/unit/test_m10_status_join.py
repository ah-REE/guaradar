"""M10 tests — identity-join coverage in the DEFAULT run (closes N-12).

N-12 recorded that `status_repository.py` sat at ~70 % branch coverage because the identity
join was exercised only by opt-in PostgreSQL tests. This module fixes that with deterministic
fakes, so the logic is covered without a database.

IMPORTANT DISTINCTION, stated so nobody over-reads these tests:
  * These prove the ADAPTER LOGIC — row validation, matching, staleness, failure handling.
  * They do NOT prove that the SQL join behaves as intended in PostgreSQL. That is what
    tests/integration/test_m9_identity_pg.py is for, and both are reported separately in
    docs/M10-EVIDENCE.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

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
    SELECT_BY_EDGE_SQL,
    load_status,
    load_status_by_edge,
)

NOW = datetime(2026, 10, 26, 14, 0, 0, tzinfo=timezone.utc)


def edge_row(
    edge_id: int,
    status: str = STATUS_OPEN,
    age_min: int = 5,
    review_at: datetime | None = None,
    source: str = "operator",
    reason: str | None = None,
    road_segment_id: int = 9000,
) -> list[Any]:
    """Shape returned by SELECT_BY_EDGE_SQL: (edge_id, status, set_at, review_at, source, reason, id)."""
    return [
        edge_id,
        status,
        NOW - timedelta(minutes=age_min),
        review_at,
        source,
        reason,
        road_segment_id,
    ]


def fetch_returning(rows: Sequence[Sequence[Any]]):
    def fetch(sql: str):
        assert "road_segments" in sql and "road_status" in sql, (
            "the identity query must join through road_segments.edge_id"
        )
        return list(rows)

    return fetch


# ===========================================================================
# Happy path
# ===========================================================================


def test_identity_join_applies_matching_status() -> None:
    res = load_status_by_edge(
        graph_edge_ids={100, 200},
        fetch=fetch_returning([edge_row(100, STATUS_OPEN)]),
        now=NOW,
        default_freshness=DEFAULT_FRESHNESS,
    )
    assert res.ok
    assert res.records_fetched == 1
    assert res.matched_edge_count == 1
    assert res.index.status_of(100) == STATUS_OPEN
    # The edge with no record is unknown, never clear.
    assert res.index.status_of(200) == STATUS_UNKNOWN


def test_identity_join_applies_every_status_kind() -> None:
    rows = [
        edge_row(1, STATUS_CLOSED, reason="flooded"),
        edge_row(2, STATUS_AFFECTED),
        edge_row(3, STATUS_OPEN),
        edge_row(4, STATUS_UNKNOWN),
    ]
    res = load_status_by_edge(
        graph_edge_ids={1, 2, 3, 4},
        fetch=fetch_returning(rows),
        now=NOW,
        default_freshness=DEFAULT_FRESHNESS,
    )
    assert res.matched_edge_count == 4
    assert res.index.status_of(1) == STATUS_CLOSED
    assert res.index.status_of(2) == STATUS_AFFECTED
    assert res.index.status_of(3) == STATUS_OPEN
    assert res.index.status_of(4) == STATUS_UNKNOWN


def test_closed_never_counts_as_verified_coverage() -> None:
    res = load_status_by_edge(
        graph_edge_ids={1},
        fetch=fetch_returning([edge_row(1, STATUS_CLOSED, reason="water")]),
        now=NOW,
        default_freshness=DEFAULT_FRESHNESS,
    )
    assert res.index.is_closed(1) is True
    assert res.index.is_verified(1) is False


# ===========================================================================
# Unmapped / unknown handling
# ===========================================================================


def test_rows_for_absent_edges_are_dropped_and_counted() -> None:
    """A row for an edge this graph does not contain must not be remapped onto another."""
    rows = [edge_row(100, STATUS_CLOSED, reason="x"), edge_row(999, STATUS_OPEN)]
    res = load_status_by_edge(
        graph_edge_ids={100},
        fetch=fetch_returning(rows),
        now=NOW,
        default_freshness=DEFAULT_FRESHNESS,
    )
    assert res.records_fetched == 2
    assert res.matched_edge_count == 1
    assert any("absent from this graph" in n for n in res.notes)
    assert res.index.status_of(999) == STATUS_UNKNOWN


def test_empty_result_means_all_unknown() -> None:
    res = load_status_by_edge(
        graph_edge_ids={1, 2},
        fetch=fetch_returning([]),
        now=NOW,
        default_freshness=DEFAULT_FRESHNESS,
    )
    assert res.ok
    assert res.matched_edge_count == 0
    assert res.index.status_of(1) == STATUS_UNKNOWN
    assert any("remain unknown" in n for n in res.notes)


# ===========================================================================
# Staleness — including the O-8 asymmetry
# ===========================================================================


def test_stale_record_loses_verified_coverage() -> None:
    rows = [edge_row(1, STATUS_OPEN, review_at=NOW - timedelta(hours=2))]
    res = load_status_by_edge(
        graph_edge_ids={1},
        fetch=fetch_returning(rows),
        now=NOW,
        default_freshness=DEFAULT_FRESHNESS,
    )
    assert res.index.is_verified(1) is False
    assert any("past their review deadline" in n for n in res.notes)


def test_stale_closure_stays_excluded_o8() -> None:
    """O-8, asserted through the identity path: ageing a closure must not reopen the road."""
    rows = [
        edge_row(
            1, STATUS_CLOSED,
            age_min=600,
            review_at=NOW - timedelta(hours=5),
            reason="closed hours ago",
        )
    ]
    res = load_status_by_edge(
        graph_edge_ids={1},
        fetch=fetch_returning(rows),
        now=NOW,
        default_freshness=DEFAULT_FRESHNESS,
    )
    assert res.index.is_closed(1) is True, "a stale closure must still exclude the edge"
    assert res.index.is_verified(1) is False, "but it must not count as coverage"


def test_fresh_record_inside_review_deadline_is_verified() -> None:
    rows = [edge_row(1, STATUS_OPEN, review_at=NOW + timedelta(minutes=30))]
    res = load_status_by_edge(
        graph_edge_ids={1},
        fetch=fetch_returning(rows),
        now=NOW,
        default_freshness=DEFAULT_FRESHNESS,
    )
    assert res.index.is_verified(1) is True


# ===========================================================================
# Malformed rows and failures
# ===========================================================================


def test_row_with_too_few_columns_is_skipped() -> None:
    rows = [edge_row(1, STATUS_OPEN), [1, STATUS_OPEN]]
    res = load_status_by_edge(
        graph_edge_ids={1},
        fetch=fetch_returning(rows),
        now=NOW,
        default_freshness=DEFAULT_FRESHNESS,
    )
    assert res.matched_edge_count == 1
    assert any("malformed row" in n for n in res.notes)


def test_non_integer_edge_id_is_skipped() -> None:
    bad = ["not-an-int", STATUS_OPEN, NOW, None, "operator", None, 9000]
    res = load_status_by_edge(
        graph_edge_ids={1},
        fetch=fetch_returning([bad]),
        now=NOW,
        default_freshness=DEFAULT_FRESHNESS,
    )
    assert res.matched_edge_count == 0
    assert any("non-integer edge_id" in n for n in res.notes)


def test_unknown_status_value_is_skipped() -> None:
    bad = [1, "flooded", NOW, None, "operator", None, 9000]
    res = load_status_by_edge(
        graph_edge_ids={1},
        fetch=fetch_returning([bad]),
        now=NOW,
        default_freshness=DEFAULT_FRESHNESS,
    )
    assert res.matched_edge_count == 0
    assert any("unknown status" in n for n in res.notes)


def test_database_error_degrades_to_unknown_not_clear() -> None:
    def boom(sql: str):
        raise RuntimeError("connection refused")

    res = load_status_by_edge(
        graph_edge_ids={1},
        fetch=boom,
        now=NOW,
        default_freshness=DEFAULT_FRESHNESS,
    )
    assert res.ok is False
    assert "connection refused" in (res.error or "")
    assert res.index.status_of(1) == STATUS_UNKNOWN
    assert any("unknown" in n for n in res.notes)


# ===========================================================================
# The SQL contract (text assertions, no database)
# ===========================================================================


def test_identity_query_joins_on_edge_id_only() -> None:
    assert "road_segments" in SELECT_BY_EDGE_SQL
    assert "rs.edge_id" in SELECT_BY_EDGE_SQL
    assert "st.road_segment_id = rs.id" in SELECT_BY_EDGE_SQL
    # No heuristic matching anywhere.
    for forbidden in ("soundex", "similarity", "levenshtein", "st_distance", "percent"):
        assert forbidden not in SELECT_BY_EDGE_SQL.lower()


def test_identity_query_omits_operator_identity() -> None:
    """`set_by` is operator identity and must never reach a public response path."""
    assert "set_by" not in SELECT_BY_EDGE_SQL


# ===========================================================================
# Route integration through the identity path
# ===========================================================================


def test_route_uses_identity_status_for_closure_exclusion() -> None:
    from app.routing.search import find_routes

    coords = {i: (-2.19 + i * 0.0005, -79.89) for i in range(3)}
    edges = [Edge(0, 0, 1, 100.0), Edge(1, 1, 2, 100.0)]
    g = RoadGraph.from_edges(coords, edges, synthetic=True)

    res = load_status_by_edge(
        graph_edge_ids=set(g.edges),
        fetch=fetch_returning([edge_row(0, STATUS_CLOSED, reason="flooded")]),
        now=NOW,
        default_freshness=DEFAULT_FRESHNESS,
    )
    resp = find_routes(g, res.index, g.nodes[0].coord, g.nodes[2].coord)
    for r in resp.routes:
        if r.phase == 1:
            assert all(leg.status != STATUS_CLOSED for leg in r.legs)


def test_route_refuses_when_identity_closure_cuts_the_only_path() -> None:
    from app.routing.search import find_routes

    coords = {i: (-2.19 + i * 0.0005, -79.89) for i in range(3)}
    edges = [Edge(0, 0, 1, 100.0), Edge(1, 1, 2, 100.0)]
    g = RoadGraph.from_edges(coords, edges, synthetic=True)

    res = load_status_by_edge(
        graph_edge_ids=set(g.edges),
        fetch=fetch_returning([
            edge_row(0, STATUS_CLOSED, reason="a"),
            edge_row(1, STATUS_CLOSED, reason="b"),
        ]),
        now=NOW,
        default_freshness=DEFAULT_FRESHNESS,
    )
    resp = find_routes(g, res.index, g.nodes[0].coord, g.nodes[2].coord)
    # No clear path exists, so phase 2 answers and must be labelled hazard-crossing.
    assert resp.routes
    assert resp.all_routes_hazard_crossing is True
    for r in resp.routes:
        assert r.recommended is False
