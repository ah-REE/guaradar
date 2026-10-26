"""M4 integration tests — cross-module routing safety.

These complement tests/unit/test_routing.py. Each targets behaviour that spans the graph,
status index, search, and response layers, or that the M4 audit found untested:

  * a phase-2 route is labelled, never recommended, and never appears alongside a phase-1 route
  * removing evidence can never IMPROVE recommendation eligibility (the route-level analogue
    of the risk engine's monotonicity rule — the direction that matters is the dangerous one)
  * stale closures stay excluded under the provisional O-8 interpretation
  * synthetic provenance propagates to the response, not just the route
  * empty / disconnected / no-path cases are explicit and distinguishable from each other
  * elevation cannot override hazard class or coverage (D29), re-checked end-to-end
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.routing.graph import (
    STATUS_AFFECTED,
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_UNKNOWN,
    Edge,
    EdgeStatus,
    RoadGraph,
    StatusIndex,
)
from app.routing.graph import DEFAULT_FRESHNESS
from app.routing.search import find_routes

NOW = datetime(2026, 10, 26, 14, 0, 0, tzinfo=timezone.utc)


def chain(n: int = 4, length_m: float = 100.0) -> tuple[RoadGraph, list[int]]:
    coords = {i: (-2.19 + i * 0.0009, -79.89) for i in range(n + 1)}
    edges = [Edge(i, i, i + 1, length_m, name=f"e{i}", elevation_m=5.0) for i in range(n)]
    return RoadGraph.from_edges(coords, edges, synthetic=True), [e.id for e in edges]


def idx(mapping: dict[int, tuple[str, int]], now: datetime = NOW) -> StatusIndex:
    """mapping: edge_id -> (status, age_minutes)."""
    return StatusIndex(
        [EdgeStatus(eid, st, now - timedelta(minutes=age)) for eid, (st, age) in mapping.items()],
        now=now,
    )


# ===========================================================================
# Phase discipline: a phase-2 route never coexists with a phase-1 route
# ===========================================================================


def test_phase2_never_mixed_with_phase1() -> None:
    """If phase 1 finds anything, phase 2 must not run at all.

    This is stronger than "phase 1 is ranked first": a client must never be able to pick a
    closure-crossing route from a list that also contains a clear one.
    """
    g, ids = chain(4)
    # One closure near the far end. A detour does not exist in a chain, so this needs a
    # branching graph — build one.
    coords = {
        0: (-2.1900, -79.8900),
        1: (-2.1900, -79.8890),
        2: (-2.1900, -79.8880),
        3: (-2.1912, -79.8900),
        4: (-2.1912, -79.8880),
    }
    edges = [
        Edge(0, 0, 1, 100.0, elevation_m=5.0),
        Edge(1, 1, 2, 100.0, elevation_m=5.0),     # direct middle
        Edge(2, 0, 3, 250.0, elevation_m=5.0),
        Edge(3, 3, 4, 250.0, elevation_m=5.0),     # detour leg
        Edge(4, 4, 2, 60.0, elevation_m=5.0),      # short connector back
    ]
    g = RoadGraph.from_edges(coords, edges, synthetic=True)

    # Direct path closed in the middle -> phase 1 must take the detour.
    st = idx({0: (STATUS_OPEN, 5), 1: (STATUS_CLOSED, 5), 2: (STATUS_OPEN, 5),
              3: (STATUS_OPEN, 5), 4: (STATUS_OPEN, 5)})
    resp = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord)
    assert resp.routes
    assert all(r.phase == 1 for r in resp.routes), "phase 2 leaked into a phase-1 response"
    assert resp.all_routes_hazard_crossing is False


def test_phase2_response_is_homogeneous() -> None:
    """When phase 2 runs, every served route is hazard-crossing — no clear route appears."""
    coords = {0: (-2.1900, -79.8900), 1: (-2.1900, -79.8890), 2: (-2.1900, -79.8880)}
    edges = [Edge(0, 0, 1, 100.0), Edge(1, 1, 2, 100.0)]
    g = RoadGraph.from_edges(coords, edges, synthetic=True)
    # Both edges closed: no clear path exists at all.
    st = idx({0: (STATUS_CLOSED, 5), 1: (STATUS_CLOSED, 5)})
    resp = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord)
    assert resp.routes
    assert {r.phase for r in resp.routes} == {2}
    assert all(r.hazard_class == "hazard_crossing" for r in resp.routes)
    assert resp.all_routes_hazard_crossing is True


# ===========================================================================
# Monotonicity — removing evidence must never improve eligibility
# ===========================================================================


def test_removing_verified_status_never_improves_eligibility() -> None:
    """The dangerous direction: less evidence must not produce a better recommendation.

    A route recommended with full verified coverage must not become MORE recommended, and
    must not stay recommended, once that coverage is withdrawn. Coverage falling can only
    demote; it can never promote.
    """
    g, ids = chain(4)
    full = idx({e: (STATUS_OPEN, 5) for e in ids})
    resp_full = find_routes(g, full, g.nodes[0].coord, g.nodes[4].coord)
    r_full = resp_full.routes[0]
    assert r_full.band == "high"
    assert r_full.recommended is True

    # Withdraw verified status progressively; `recommended` must never go False -> True.
    seen_recommended: list[bool] = []
    for keep in range(len(ids), -1, -1):
        partial = idx({e: (STATUS_OPEN, 5) for e in ids[:keep]})
        resp = find_routes(g, partial, g.nodes[0].coord, g.nodes[4].coord)
        assert resp.routes
        seen_recommended.append(resp.routes[0].recommended)

    # Once it stops being recommended, it must not become recommended again.
    assert seen_recommended[0] is True
    first_false = seen_recommended.index(False) if False in seen_recommended else len(seen_recommended)
    assert all(v is False for v in seen_recommended[first_false:]), (
        f"recommendation reappeared as evidence was removed: {seen_recommended}"
    )


def test_unknown_status_is_not_better_than_affected() -> None:
    """`unknown` must never rank above `affected`, since unknown is not knowledge of safety."""
    coords = {
        0: (-2.1900, -79.8900),
        1: (-2.1900, -79.8890),
        2: (-2.1900, -79.8880),
        3: (-2.1912, -79.8900),
        4: (-2.1912, -79.8880),
    }
    edges = [
        Edge(0, 0, 1, 100.0),
        Edge(1, 1, 2, 100.0),
        Edge(2, 0, 3, 250.0),
        Edge(3, 3, 4, 250.0),
        Edge(4, 4, 2, 60.0),
    ]
    g = RoadGraph.from_edges(coords, edges, synthetic=True)
    # Direct route: verified AFFECTED (band high, coverage 100).
    # Detour: entirely UNKNOWN (band none, coverage 0).
    st = idx({0: (STATUS_AFFECTED, 5), 1: (STATUS_AFFECTED, 5)})
    resp = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord)
    first = resp.routes[0]
    # The affected-but-verified route should precede an unknown-only alternative.
    assert first.coverage_pct > 0.0 or len(resp.routes) == 1
    for r in resp.routes:
        if r.band == "none":
            assert r.recommended is False


# ===========================================================================
# Stale closures — provisional O-8 behaviour, locked by test
# ===========================================================================


def test_stale_closure_still_excluded_from_phase1() -> None:
    """O-8 provisional reading: ageing a closure does not reopen the road.

    A closure recorded long past the freshness window must still be absent from phase 1.
    Recorded as provisional, NOT as a user-approved resolution.
    """
    coords = {0: (-2.190, -79.890), 1: (-2.190, -79.889), 2: (-2.190, -79.888)}
    edges = [Edge(0, 0, 1, 100.0), Edge(1, 1, 2, 100.0)]
    g = RoadGraph.from_edges(coords, edges, synthetic=True)

    # 12 hours stale, far beyond DEFAULT_FRESHNESS.
    st = idx({0: (STATUS_CLOSED, 12 * 60), 1: (STATUS_OPEN, 5)})
    assert (NOW - (NOW - timedelta(hours=12))) > DEFAULT_FRESHNESS

    resp = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord)
    # No clear path exists, so phase 2 answers — but it must be labelled, not eligible.
    assert resp.all_routes_hazard_crossing is True
    assert all(r.phase == 2 for r in resp.routes)
    assert all(r.recommended is False for r in resp.routes)


def test_stale_closure_lowers_coverage_even_in_phase2() -> None:
    g, ids = chain(3)
    st = idx({ids[0]: (STATUS_CLOSED, 600), ids[1]: (STATUS_OPEN, 600), ids[2]: (STATUS_OPEN, 5)})
    resp = find_routes(g, st, g.nodes[0].coord, g.nodes[3].coord)
    r = resp.routes[0]
    # Only the last edge is both fresh and non-closed: 100 of 300 m.
    assert r.coverage_pct == pytest.approx(33.33, abs=0.05)


# ===========================================================================
# Provenance propagation
# ===========================================================================


def test_synthetic_flag_propagates_to_response() -> None:
    g, ids = chain(2)
    resp = find_routes(g, idx({ids[0]: (STATUS_OPEN, 5)}), g.nodes[0].coord, g.nodes[2].coord)
    assert resp.synthetic is True
    assert any("synthetic" in n.lower() for n in resp.notes)
    assert any("not a surveyed OSM extract" in n for n in resp.notes)


def test_refusal_also_carries_synthetic_flag() -> None:
    """A refusal must not lose provenance: it still describes a synthetic dataset."""
    g, ids = chain(2)
    far = (-2.2000, -79.8900)
    resp = find_routes(g, idx({}), far, g.nodes[2].coord)
    assert resp.refused is True
    assert resp.synthetic is True


# ===========================================================================
# Empty / disconnected / no-path are distinguishable
# ===========================================================================


def test_empty_graph_refusal_is_explicit() -> None:
    empty = RoadGraph.from_edges({}, [], synthetic=True)
    resp = find_routes(empty, StatusIndex([], now=NOW), (-2.19, -79.89), (-2.20, -79.89))
    assert resp.refused is True
    assert "graph is empty" in (resp.refusal_reason or "")


def test_disconnected_graph_refuses_with_no_path_reason() -> None:
    """Two components: the snap succeeds but no path exists. Distinct from 'no dry route'."""
    coords = {
        0: (-2.1900, -79.8900),
        1: (-2.1900, -79.8890),
        10: (-2.2100, -79.8900),
        11: (-2.2100, -79.8890),
    }
    edges = [Edge(0, 0, 1, 100.0), Edge(1, 10, 11, 100.0)]
    g = RoadGraph.from_edges(coords, edges, synthetic=True)
    assert g.stats()["components"] == 2

    resp = find_routes(
        g, StatusIndex([], now=NOW), g.nodes[0].coord, g.nodes[11].coord
    )
    assert resp.refused is True
    assert "no path connects" in (resp.refusal_reason or "")
    assert resp.all_routes_hazard_crossing is False, (
        "a disconnected pair must not be reported as hazard-crossing"
    )


def test_closed_only_connection_is_not_reported_as_no_path() -> None:
    """The distinction that matters during an evacuation."""
    coords = {0: (-2.190, -79.890), 1: (-2.190, -79.889), 2: (-2.190, -79.888)}
    g = RoadGraph.from_edges(
        coords, [Edge(0, 0, 1, 100.0), Edge(1, 1, 2, 100.0)], synthetic=True
    )
    st = idx({0: (STATUS_CLOSED, 5), 1: (STATUS_CLOSED, 5)})
    resp = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord)
    assert resp.refused is False
    assert resp.all_routes_hazard_crossing is True
    assert "no path connects" not in (resp.refusal_reason or "")


# ===========================================================================
# D29 end-to-end: elevation cannot override class or coverage
# ===========================================================================


def test_elevation_cannot_make_a_closure_route_eligible() -> None:
    """Even with a far lower elevation, a hazard-crossing route stays out of rank 1."""
    coords = {
        0: (-2.1900, -79.8900),
        1: (-2.1900, -79.8890),
        2: (-2.1900, -79.8880),
        3: (-2.1912, -79.8900),
        4: (-2.1912, -79.8880),
    }
    edges = [
        Edge(0, 0, 1, 100.0, elevation_m=99.0),     # high
        Edge(1, 1, 2, 100.0, elevation_m=99.0),
        Edge(2, 0, 3, 250.0, elevation_m=1.0),      # very low detour
        Edge(3, 3, 4, 250.0, elevation_m=1.0),
        Edge(4, 4, 2, 60.0, elevation_m=1.0),
    ]
    g = RoadGraph.from_edges(coords, edges, synthetic=True)
    st = idx({0: (STATUS_OPEN, 5), 1: (STATUS_OPEN, 5),
              2: (STATUS_OPEN, 5), 3: (STATUS_OPEN, 5), 4: (STATUS_OPEN, 5)})
    resp = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord)
    first = resp.routes[0]
    # Coverage (band) is compared before elevation, so the fully-verified direct path
    # should win on band even though the detour is 90 m lower.
    assert first.band in ("high", "moderate")
    assert first.hazard_class == "clear"


def test_elevation_tiebreak_direction_only_affects_equal_routes() -> None:
    g, ids = chain(2)
    st = idx({ids[0]: (STATUS_OPEN, 5), ids[1]: (STATUS_OPEN, 5)})
    a = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord, prefer_lower_elevation=True)
    b = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord, prefer_lower_elevation=False)
    # Same classification and coverage either way; only ordering among ties may differ.
    assert [r.classification for r in a.routes] == [r.classification for r in b.routes]
    assert [r.coverage_pct for r in a.routes] == [r.coverage_pct for r in b.routes]


# ===========================================================================
# Wording guard (belt and braces on ROUTE-4)
# ===========================================================================


def test_no_stronger_than_supported_language() -> None:
    """No route copy may use stronger claims than the approved vocabulary."""
    from app.routing.search import BANNED_ROUTE_WORDS

    stronger = ("guaranteed", "flood-proof", "waterproof", "always passable", "risk-free")
    g, ids = chain(3)
    cases = [
        idx({}),
        idx({e: (STATUS_OPEN, 5) for e in ids}),
        idx({e: (STATUS_CLOSED, 5) for e in ids}),
        idx({e: (STATUS_AFFECTED, 5) for e in ids}),
    ]
    for st in cases:
        resp = find_routes(g, st, g.nodes[0].coord, g.nodes[3].coord)
        texts = [r.label for r in resp.routes] + ([resp.refusal_reason] if resp.refusal_reason else [])
        for t in texts:
            low = t.lower()
            for word in tuple(BANNED_ROUTE_WORDS) + stronger:
                assert word not in low, f"overclaiming word {word!r} in {t!r}"
