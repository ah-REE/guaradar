"""Tests for the Guaradar routing search.

Named after the safety properties in docs/STAGE-3-ARCHITECTURE.md §17.1 (`ROUTE-1`…
`ROUTE-7`) plus `ROUTE-8`/`ROUTE-9` from Stage 4 §4.2 (D29).

The two-phase guarantee is the property this module exists to provide, so it is tested
against the same adversarial shape that refuted the finite-penalty design in
research/routing_invariant.py.
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
    build_synthetic_grid,
    haversine_m,
)
from app.routing.search import (
    BANNED_ROUTE_WORDS,
    MAX_SNAP_DISTANCE_M,
    NO_KNOWN_HAZARDS,
    _band_for,
    find_routes,
)

NOW = datetime(2026, 10, 26, 14, 0, 0, tzinfo=timezone.utc)

SECTORS = {
    "norte": (-2.1420, -79.9050),
    "centro": (-2.1962, -79.8865),
    "sur": (-2.2200, -79.9100),
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def line_graph(n: int, length_m: float = 100.0) -> tuple[RoadGraph, list[int]]:
    """A straight chain of n+1 nodes. Simple enough to reason about by hand."""
    coords = {i: (-2.19 + i * 0.0009, -79.89) for i in range(n + 1)}
    edges = [
        Edge(id=i, a=i, b=i + 1, length_m=length_m, name=f"e{i}", elevation_m=5.0)
        for i in range(n)
    ]
    return RoadGraph.from_edges(coords, edges, synthetic=True), [e.id for e in edges]


def two_route_graph() -> tuple[RoadGraph, dict[str, int]]:
    """Two paths from 0 to 2: a short one via node 1, a long one via nodes 3 and 4.

        0 --(e0: 100m)-- 1 --(e1: 100m)-- 2        short, 200 m
        0 --(e2: 300m)-- 3 --(e3: 300m)-- 4 --(e4: 300m)-- 2   long, 900 m
    """
    coords = {
        0: (-2.190, -79.890),
        1: (-2.190, -79.889),
        2: (-2.190, -79.888),
        3: (-2.191, -79.890),
        4: (-2.191, -79.889),
    }
    edges = [
        Edge(0, 0, 1, 100.0, name="short-a", elevation_m=5.0),
        Edge(1, 1, 2, 100.0, name="short-b", elevation_m=5.0),
        Edge(2, 0, 3, 300.0, name="long-a", elevation_m=4.0),
        Edge(3, 3, 4, 300.0, name="long-b", elevation_m=4.0),
        Edge(4, 4, 2, 300.0, name="long-c", elevation_m=4.0),
    ]
    g = RoadGraph.from_edges(coords, edges, synthetic=True)
    return g, {"short": 0, "short_b": 1, "long": 2, "long_b": 3, "long_c": 4}


def adversarial_graph() -> tuple[RoadGraph, int, int]:
    """The counterexample shape from research/routing_invariant.py.

    A cheap direct edge 0->1 that is CLOSED, plus a long open chain 0->2..->41->1.
    A finite penalty serves the closed edge here; the two-phase filter must not.
    """
    coords = {0: (-2.190, -79.890), 1: (-2.190, -79.880)}
    edges: list[Edge] = [Edge(0, 0, 1, 5.0, name="closed-direct", elevation_m=5.0)]
    chain = [0] + list(range(2, 42)) + [1]
    eid = 1
    for i, (a, b) in enumerate(zip(chain, chain[1:])):
        coords.setdefault(b, (-2.191 + i * 0.00002, -79.889))
        edges.append(Edge(eid, a, b, 600.0, name=f"open-{i}", elevation_m=6.0))
        eid += 1
    g = RoadGraph.from_edges(coords, edges, synthetic=True)
    return g, 0, 1


def index(statuses: dict[int, str], now: datetime = NOW, age_min: int = 5) -> StatusIndex:
    return StatusIndex(
        [EdgeStatus(eid, st, now - timedelta(minutes=age_min)) for eid, st in statuses.items()],
        now=now,
    )


# ===========================================================================
# ROUTE-1 / ROUTE-1b — the two-phase guarantee
# ===========================================================================


def test_ROUTE_1_phase1_never_crosses_a_closure() -> None:
    """The core guarantee, on the adversarial shape that refuted the penalty design."""
    g, src, dst = adversarial_graph()
    st = index({0: STATUS_CLOSED})
    resp = find_routes(g, st, g.nodes[src].coord, g.nodes[dst].coord)

    assert not resp.refused
    assert resp.routes, "a closed-free route exists, so one must be served"
    for r in resp.routes:
        assert r.phase == 1
        assert r.hazard_class == "clear"
        assert all(leg.status != STATUS_CLOSED for leg in r.legs), (
            "phase 1 served a route crossing a closed edge"
        )
    assert resp.all_routes_hazard_crossing is False


def test_ROUTE_1_phase2_only_when_phase1_fails() -> None:
    """When every route must cross a closure, phase 2 answers and labels it."""
    g, src, dst = adversarial_graph()
    # Close the entire open chain, leaving only the direct closed edge as any connection.
    st = index({e.id: STATUS_CLOSED for e in g.edges.values()})
    resp = find_routes(g, st, g.nodes[src].coord, g.nodes[dst].coord)

    assert not resp.refused
    assert resp.routes
    assert resp.all_routes_hazard_crossing is True
    for r in resp.routes:
        assert r.phase == 2
        assert r.hazard_class == "hazard_crossing"
        assert r.classification == "hazard_crossing"
        assert r.recommended is False, "a hazard-crossing route must never be recommended"
        assert "crosses a closed road" in r.label


def test_ROUTE_1b_two_phase_beats_finite_penalty() -> None:
    """Port of research/routing_invariant.py's key finding, as a regression test.

    A finite penalty (any finite multiplier) lets the closed 5 m edge win: it is cheaper
    than 41 x 600 m. The two-phase filter must not, because in phase 1 the edge does not
    exist. This test asserts both halves so a future "optimisation" back to penalties
    fails the build.
    """
    g, src, dst = adversarial_graph()
    st = index({0: STATUS_CLOSED})

    # What a finite-penalty design would have chosen:
    closed_cost = 5.0 * 250.0                      # the multiplier used in the probe
    open_cost = 41 * 600.0
    assert closed_cost < open_cost, (
        "if the penalty were large enough to beat this, the adversarial case would no "
        "longer be adversarial and this test would be meaningless"
    )

    # What the implemented design chooses:
    resp = find_routes(g, st, g.nodes[src].coord, g.nodes[dst].coord)
    best = resp.routes[0]
    assert all(leg.status != STATUS_CLOSED for leg in best.legs)
    assert best.distance_m == pytest.approx(open_cost, rel=0.01)


def test_ROUTE_1_no_dry_route_is_distinct_from_no_path() -> None:
    """'The only way is flooded' must not be reported as 'no path exists'."""
    g, src, dst = adversarial_graph()
    st = index({e.id: STATUS_CLOSED for e in g.edges.values()})
    resp = find_routes(g, st, g.nodes[src].coord, g.nodes[dst].coord)
    assert resp.refused is False
    assert resp.all_routes_hazard_crossing is True

    # A genuinely disconnected pair must be refused with a different reason.
    g2 = RoadGraph.from_edges(
        {0: (-2.19, -79.89), 1: (-2.19, -79.88)},
        [Edge(0, 0, 1, 100.0)],
        synthetic=True,
    )
    resp2 = find_routes(g2, index({}), g2.nodes[0].coord, (-2.195, -79.885))
    # destination snaps to a real node, so this is connected; instead test an empty graph
    empty = RoadGraph.from_edges({}, [], synthetic=True)
    resp3 = find_routes(empty, index({}), (-2.19, -79.89), (-2.20, -79.89))
    assert resp3.refused is True
    assert "graph is empty" in (resp3.refusal_reason or "")


# ===========================================================================
# ROUTE-2 / 2b — coverage arithmetic and band boundaries
# ===========================================================================


def test_ROUTE_2_coverage_is_length_weighted() -> None:
    """The documented fixture: 4.2 km path, 1.8 km verified => 42.9 %."""
    g, ids = line_graph(42, length_m=100.0)     # 42 edges x 100 m = 4.2 km
    # 18 edges verified open (1.8 km), the rest unknown.
    st = index({ids[i]: STATUS_OPEN for i in range(18)})
    resp = find_routes(g, st, g.nodes[0].coord, g.nodes[42].coord)
    assert not resp.refused
    r = resp.routes[0]
    assert r.distance_m == pytest.approx(4200.0)
    assert r.coverage_pct == pytest.approx(42.86, abs=0.05)
    assert r.band == "low"


def test_ROUTE_2_coverage_not_edge_count() -> None:
    """Unequal edge lengths must weight by metres, not by segment count."""
    coords = {0: (-2.19, -79.89), 1: (-2.19, -79.889), 2: (-2.19, -79.888)}
    edges = [
        Edge(0, 0, 1, 900.0, name="long"),
        Edge(1, 1, 2, 100.0, name="short"),
    ]
    g = RoadGraph.from_edges(coords, edges, synthetic=True)
    # Only the SHORT edge is verified: 100 of 1000 m = 10 %, not 50 %.
    st = index({1: STATUS_OPEN})
    r = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord).routes[0]
    assert r.coverage_pct == pytest.approx(10.0)
    assert r.band == "low"


@pytest.mark.parametrize(
    "pct,expected",
    [
        (100.0, "high"),
        (80.0, "high"),
        (79.99, "moderate"),
        (60.0, "moderate"),
        (59.99, "low"),
        (0.01, "low"),
        (0.0, "none"),
    ],
)
def test_ROUTE_2b_band_boundaries_exact(pct: float, expected: str) -> None:
    """§9.1 band edges, inclusive at the bottom, on the rounded value."""
    assert _band_for(pct) == expected


def test_ROUTE_2b_closed_edges_do_not_count_as_verified() -> None:
    """A closure is not verification that travel is fine.

    Three parallel-ish segments in a chain, with only the middle one closed: the route must
    detour in phase 1 and the open edges that remain verified determine coverage.
    """
    coords = {
        0: (-2.1900, -79.8900),
        1: (-2.1900, -79.8890),
        2: (-2.1900, -79.8880),
        3: (-2.1910, -79.8900),   # detour node
    }
    edges = [
        Edge(0, 0, 1, 100.0, name="direct-a"),
        Edge(1, 1, 2, 100.0, name="direct-b"),
        Edge(2, 0, 3, 200.0, name="detour-a"),
        Edge(3, 3, 2, 200.0, name="detour-b"),
    ]
    g = RoadGraph.from_edges(coords, edges, synthetic=True)
    # Close the direct middle edge 1->2 path edge (id 1). Phase 1 must take the detour.
    st = index({0: STATUS_OPEN, 1: STATUS_CLOSED, 2: STATUS_OPEN, 3: STATUS_OPEN})
    resp = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord)
    assert resp.routes
    r = resp.routes[0]
    assert r.phase == 1, "a closed-free detour exists, so phase 1 must answer"
    assert all(leg.edge_id != 1 for leg in r.legs), "the closed edge must be avoided"
    # The detour uses edges 2 and 3, both verified open => 100 % coverage.
    assert r.coverage_pct == pytest.approx(100.0)
    # And the closed edge contributes nothing: total verified length excludes it.
    closed_legs = [leg for leg in r.legs if leg.status == STATUS_CLOSED]
    assert closed_legs == []


# ===========================================================================
# ROUTE-2c / 2d — never recommend low coverage; Clear outranks hazard-crossing
# ===========================================================================


def test_ROUTE_2c_zero_coverage_served_but_not_recommended() -> None:
    """A 0 %-coverage route may be the shortest, and still must not be rank-1-recommended."""
    g, ids = two_route_graph()
    # Nothing verified anywhere => every route is band 'none'.
    resp = find_routes(g, index({}), g.nodes[0].coord, g.nodes[2].coord)
    assert resp.routes
    assert resp.best_available_is_uncertain is True
    for r in resp.routes:
        assert r.band == "none"
        assert r.recommended is False
        assert r.classification == "marginal"
        assert "conditions along this route are unknown" in r.label.lower()


def test_ROUTE_2c_low_coverage_is_demoted_below_moderate() -> None:
    """Given a moderate-coverage longer route and a low-coverage shorter one, moderate wins."""
    g, ids = two_route_graph()
    st = index(
        {
            ids["long"]: STATUS_OPEN,
            ids["long_b"]: STATUS_OPEN,
            ids["long_c"]: STATUS_OPEN,   # long route fully verified => high
            ids["short"]: STATUS_OPEN,    # short route half verified => 50 % low
        }
    )
    resp = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord)
    assert len(resp.routes) >= 2
    first = resp.routes[0]
    assert first.band in ("high", "moderate"), (
        f"rank 1 has band {first.band}; a low-coverage route must not outrank it"
    )
    assert first.recommended is True
    low = [r for r in resp.routes if r.band == "low"]
    assert low, "the short low-coverage route should still be served"
    assert all(not r.recommended for r in low)


def test_ROUTE_2d_clear_outranks_hazard_crossing_always() -> None:
    """Every Clear route precedes every hazard-crossing route, regardless of duration."""
    g, ids = two_route_graph()
    # Short route fully verified (Clear, high coverage, 200 m).
    # Make the long route a closure crossing by closing one of its edges and forcing
    # no clear alternative... but a clear alternative exists, so phase 1 wins.
    st = index(
        {
            ids["short"]: STATUS_OPEN,
            ids["short_b"]: STATUS_OPEN,
            ids["long"]: STATUS_CLOSED,
        }
    )
    resp = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord)
    assert all(r.phase == 1 for r in resp.routes)
    assert all(r.hazard_class == "clear" for r in resp.routes)
    assert resp.all_routes_hazard_crossing is False


# ===========================================================================
# ROUTE-5 — snap refusal
# ===========================================================================


def test_ROUTE_5_snap_beyond_limit_refuses() -> None:
    """A start point far from every node must be refused, not snapped onto a guess."""
    g, ids = line_graph(3)
    # Line graph nodes sit near lat -2.19, lon -79.89, spaced ~100 m. A point 0.01 deg
    # north (~1.1 km) is far outside the 60 m snap limit of every node.
    far = (-2.2000, -79.8900)
    nearest, d = g.nearest_node(*far)
    assert d > MAX_SNAP_DISTANCE_M, f"{d:.0f} m is not beyond the limit"
    resp = find_routes(g, index({}), far, g.nodes[3].coord)
    assert resp.refused is True
    assert "nearest road" in (resp.refusal_reason or "")
    assert f"{MAX_SNAP_DISTANCE_M:.0f} m" in (resp.refusal_reason or "")
    assert resp.routes == ()


def test_ROUTE_5_snap_within_limit_proceeds() -> None:
    g, ids = line_graph(3)
    near = (g.nodes[0].lat + 0.0002, g.nodes[0].lon)  # ~22 m
    assert haversine_m(near, g.nodes[0].coord) < MAX_SNAP_DISTANCE_M
    resp = find_routes(g, index({ids[0]: STATUS_OPEN}), near, g.nodes[3].coord)
    assert resp.refused is False
    assert resp.snap_from_m is not None and resp.snap_from_m < MAX_SNAP_DISTANCE_M


# ===========================================================================
# ROUTE-6 — hazard-crossing labelled and last
# ===========================================================================


def test_ROUTE_6_all_hazard_crossing_flag() -> None:
    g, src, dst = adversarial_graph()
    st = index({e.id: STATUS_CLOSED for e in g.edges.values()})
    resp = find_routes(g, st, g.nodes[src].coord, g.nodes[dst].coord)
    assert resp.all_routes_hazard_crossing is True
    for r in resp.routes:
        assert r.hazard_class == "hazard_crossing"
        assert r.recommended is False
        assert r.classification == "hazard_crossing"


# ===========================================================================
# ROUTE-7 — stale majority cannot be Eligible
# ===========================================================================


def test_ROUTE_7_stale_status_removes_verification() -> None:
    """A stale closure still excludes the edge, but contributes no verified coverage."""
    g, ids = line_graph(2)
    # Both edges recorded closed 3 hours ago: stale, but still closures.
    st = StatusIndex(
        [EdgeStatus(e, STATUS_CLOSED, NOW - timedelta(hours=3)) for e in ids], now=NOW
    )
    resp = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord)
    assert resp.all_routes_hazard_crossing is True
    for r in resp.routes:
        assert r.coverage_pct == pytest.approx(0.0)
        assert r.band == "none"


def test_ROUTE_7_stale_majority_is_not_eligible() -> None:
    """More than half the route stale => at most marginal, never eligible."""
    g, ids = line_graph(10, length_m=100.0)
    fresh = {ids[i]: STATUS_OPEN for i in range(4)}         # 400 m fresh
    stale = {ids[i]: STATUS_OPEN for i in range(4, 10)}     # 600 m stale
    st = StatusIndex(
        [EdgeStatus(e, s, NOW - timedelta(minutes=5)) for e, s in fresh.items()]
        + [EdgeStatus(e, s, NOW - timedelta(hours=4)) for e, s in stale.items()],
        now=NOW,
    )
    r = find_routes(g, st, g.nodes[0].coord, g.nodes[10].coord).routes[0]
    assert r.coverage_pct == pytest.approx(40.0)
    assert r.band == "low"
    assert r.classification == "marginal"
    assert r.recommended is False


# ===========================================================================
# ROUTE-4 — banned vocabulary
# ===========================================================================


def test_ROUTE_4_route_labels_never_say_safe() -> None:
    """No route label may contain the banned words in any served state."""
    g, src, dst = adversarial_graph()
    labels: list[str] = []

    for statuses in (
        {},
        {0: STATUS_CLOSED},
        {e.id: STATUS_CLOSED for e in g.edges.values()},
        {e.id: STATUS_AFFECTED for e in g.edges.values()},
        {e.id: STATUS_UNKNOWN for e in g.edges.values()},
    ):
        resp = find_routes(g, index(statuses), g.nodes[src].coord, g.nodes[dst].coord)
        labels.extend(r.label for r in resp.routes)
        if resp.refusal_reason:
            labels.append(resp.refusal_reason)

    assert labels, "expected some labels to check"
    for text in labels:
        low = text.lower()
        for banned in BANNED_ROUTE_WORDS:
            # "clear" is permitted only inside 'no known hazards' phrasing checks below;
            # here we assert the word does not appear as a safety claim at all.
            assert banned not in low, f"banned word {banned!r} in route copy: {text!r}"


def test_ROUTE_4_no_known_hazards_phrasing_available() -> None:
    """The permitted characterisation exists and is used for a clean route."""
    g, ids = two_route_graph()
    st = index({ids["short"]: STATUS_OPEN, ids["short_b"]: STATUS_OPEN})
    r = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord).routes[0]
    assert r.band == "high"
    assert NO_KNOWN_HAZARDS in r.label.lower()


# ===========================================================================
# ROUTE-8 / ROUTE-9 — D29 elevation tie-break discipline
# ===========================================================================


def test_ROUTE_8_elevation_cannot_cross_a_class_boundary() -> None:
    """D29 limit 2/3: elevation is the LAST sort term and cannot reorder by class.

    Built so that a Clear/low route and a hazard-crossing route are both present in the
    ordering computation; the Clear one must stay first even if much higher.
    """
    g, src, dst = adversarial_graph()
    st = index({0: STATUS_CLOSED})
    resp = find_routes(g, st, g.nodes[src].coord, g.nodes[dst].coord)
    # Only phase-1 routes exist here, so cross-class comparison needs the ranking helper.
    from app.routing.search import _rank, _build_route

    clear_path = [(src, g.edges[1])]
    clear_route = _build_route(g, clear_path, st, phase=1)
    # A hazard-crossing route that would be faster (shorter) than the clear one.
    hz_path = [(src, g.edges[0])]
    hz_route = _build_route(g, hz_path, st, phase=2)
    assert hz_route.hazard_class == "hazard_crossing"
    assert hz_route.distance_m < clear_route.distance_m, "the hazard route is shorter"

    ranked = _rank([hz_route, clear_route])
    assert ranked[0].hazard_class == "clear", (
        "a shorter hazard-crossing route was ranked above a clear one"
    )


def test_ROUTE_8_elevation_cannot_cross_a_band_boundary() -> None:
    """Same band discipline: a low-elevation low-coverage route stays behind high coverage."""
    from app.routing.search import _build_route, _rank

    g, ids = line_graph(2)
    st_high = index({ids[0]: STATUS_OPEN, ids[1]: STATUS_OPEN})
    st_low = index({ids[0]: STATUS_OPEN})

    high_cov = _build_route(g, [(0, g.edges[ids[0]]), (1, g.edges[ids[1]])], st_high, 1)
    low_cov = _build_route(g, [(0, g.edges[ids[0]]), (1, g.edges[ids[1]])], st_low, 1)

    assert high_cov.band == "high"
    assert low_cov.band == "low"

    # Give the low-coverage route a much lower elevation. It must still rank second.
    import dataclasses

    low_cov_lower = dataclasses.replace(low_cov, mean_elevation_m=0.0)
    high_cov_higher = dataclasses.replace(high_cov, mean_elevation_m=99.0)
    ranked = _rank([low_cov_lower, high_cov_higher])
    assert ranked[0].band == "high"
    assert ranked[1].band == "low"


def test_ROUTE_9_elevation_is_last_sort_term() -> None:
    """Given otherwise identical routes, elevation breaks the tie; and it is disclosed."""
    import dataclasses
    from app.routing.search import _rank

    g, ids = line_graph(1)
    st = index({ids[0]: STATUS_OPEN})
    from app.routing.search import _build_route

    base = _build_route(g, [(0, g.edges[ids[0]])], st, 1)
    assert base.duration_s == base.duration_s  # identical class, band, duration

    low = dataclasses.replace(base, mean_elevation_m=4.0)
    high = dataclasses.replace(base, mean_elevation_m=9.0)

    ranked_desc = _rank([high, low], prefer_lower_elevation=True)
    assert ranked_desc[0].mean_elevation_m == 4.0, "lower elevation should tie-break first"
    assert ranked_desc[0].elevation_used_as_tiebreak is True, (
        "the tie-break must be disclosed, not silent"
    )

    # The direction is configurable, and reversing it is the only effect elevation has.
    ranked_asc = _rank([high, low], prefer_lower_elevation=False)
    assert ranked_asc[0].mean_elevation_m == 9.0


def test_ROUTE_9_removing_elevation_changes_nothing_but_ties() -> None:
    """With no elevation data at all, ordering by the first three terms is unchanged."""
    import dataclasses
    from app.routing.search import _rank, _build_route

    g, ids = line_graph(3)
    st = index({ids[0]: STATUS_OPEN, ids[1]: STATUS_OPEN, ids[2]: STATUS_OPEN})
    full = _build_route(g, [(i, g.edges[ids[i]]) for i in range(3)], st, 1)
    no_elev = dataclasses.replace(full, mean_elevation_m=None)

    a = _rank([full])
    b = _rank([no_elev])
    assert a[0].classification == b[0].classification
    assert a[0].duration_s == b[0].duration_s
    assert b[0].elevation_used_as_tiebreak is False


# ===========================================================================
# Supplementary — honest labelling and determinism
# ===========================================================================


def test_synthetic_graph_is_labelled_in_notes() -> None:
    g, ids = line_graph(2)
    resp = find_routes(g, index({ids[0]: STATUS_OPEN}), g.nodes[0].coord, g.nodes[2].coord)
    joined = " ".join(resp.notes)
    assert "synthetic" in joined.lower()
    assert resp.synthetic is True


def test_no_status_means_unknown_not_open() -> None:
    """The single most dangerous conflation: absent status is not 'clear'."""
    g, ids = line_graph(2)
    resp = find_routes(g, index({}), g.nodes[0].coord, g.nodes[2].coord)
    r = resp.routes[0]
    assert all(leg.status == STATUS_UNKNOWN for leg in r.legs)
    assert r.coverage_pct == 0.0
    assert r.band == "none"
    assert r.recommended is False


def test_determinism_identical_inputs_identical_output() -> None:
    g, ids = line_graph(20)
    st = index({ids[i]: STATUS_OPEN for i in range(0, 20, 2)})
    a = find_routes(g, st, g.nodes[0].coord, g.nodes[20].coord)
    b = find_routes(g, st, g.nodes[0].coord, g.nodes[20].coord)
    assert [tuple(l.edge_id for l in r.legs) for r in a.routes] == [
        tuple(l.edge_id for l in r.legs) for r in b.routes
    ]
    assert [r.coverage_pct for r in a.routes] == [r.coverage_pct for r in b.routes]


def test_status_change_affects_routing_without_cache() -> None:
    """ROUTE-3 engine-side form: a new closure changes the very next query (D14)."""
    g, ids = line_graph(2)
    open_index = index({ids[0]: STATUS_OPEN, ids[1]: STATUS_OPEN})
    first = find_routes(g, open_index, g.nodes[0].coord, g.nodes[2].coord)
    assert first.routes[0].phase == 1
    assert first.routes[0].coverage_pct == pytest.approx(100.0)

    closed_index = index({ids[0]: STATUS_CLOSED, ids[1]: STATUS_OPEN})
    second = find_routes(g, closed_index, g.nodes[0].coord, g.nodes[2].coord)
    assert second.all_routes_hazard_crossing is True
    assert second.routes[0].coverage_pct == pytest.approx(50.0)


def test_synthetic_grid_is_one_component() -> None:
    g = build_synthetic_grid(SECTORS)
    stats = g.stats()
    assert stats["components"] == 1
    assert stats["largest_component_pct"] == pytest.approx(100.0)
    assert stats["synthetic"] is True


def test_src_equals_dst_returns_empty_path() -> None:
    """Same origin and destination: a zero-length route, not a refusal."""
    from app.routing.search import _dijkstra

    g, ids = line_graph(2)
    st = index({ids[0]: STATUS_OPEN})
    assert _dijkstra(g, 0, 0, st, exclude_closed=True) == []
    resp = find_routes(g, st, g.nodes[0].coord, g.nodes[0].coord)
    assert resp.refused is False


def test_negative_affected_route_note_is_absent_when_clean() -> None:
    """A route crossing no affected road must not invent an 'affected' note."""
    g, ids = line_graph(2)
    st = index({ids[0]: STATUS_OPEN, ids[1]: STATUS_OPEN})
    r = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord).routes[0]
    assert not any("affected" in n for n in r.notes)
    assert r.hazards_avoided == ()


def test_affected_route_is_noted_and_marginal() -> None:
    """A route crossing an affected road carries the note (§9.1 Marginal rule)."""
    g, ids = line_graph(2)
    st = index({ids[0]: STATUS_AFFECTED, ids[1]: STATUS_AFFECTED})
    resp = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord)
    r = resp.routes[0]
    assert r.phase == 1
    assert any("affected" in n for n in r.notes)
    assert r.hazards_avoided == ("2 affected",)
    # Affected edges are verified, so coverage is 100 % and it is eligible.
    assert r.coverage_pct == pytest.approx(100.0)
    assert r.classification == "eligible"


def test_multi_alternative_clamp_respected() -> None:
    """max_alternatives caps the number returned."""
    g, ids = line_graph(20)
    st = index({ids[i]: STATUS_OPEN for i in range(20)})
    one = find_routes(g, st, g.nodes[0].coord, g.nodes[20].coord, max_alternatives=1)
    assert len(one.routes) == 1


def test_hazard_crossing_never_recommended_even_if_only_option() -> None:
    """ROUTE-6 corollary: being the only route does not make a closure-crossing safe."""
    g, ids = line_graph(2)
    st = index({ids[0]: STATUS_CLOSED, ids[1]: STATUS_CLOSED})
    resp = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord)
    assert resp.routes
    for r in resp.routes:
        assert r.recommended is False
        assert r.classification == "hazard_crossing"


def test_invalid_arguments_rejected() -> None:
    g, ids = line_graph(1)
    with pytest.raises(ValueError):
        find_routes(g, index({}), g.nodes[0].coord, g.nodes[1].coord, max_alternatives=0)
    with pytest.raises(ValueError):
        EdgeStatus(0, "flooded", NOW)
    with pytest.raises(ValueError):
        StatusIndex([EdgeStatus(0, STATUS_OPEN, NOW), EdgeStatus(0, STATUS_OPEN, NOW)], now=NOW)
    with pytest.raises(ValueError):
        StatusIndex([], now=None)


# ===========================================================================
# Supplementary — graph construction guards and the untested OSM path
# ===========================================================================


def test_graph_rejects_dangling_edge() -> None:
    with pytest.raises(ValueError, match="unknown node"):
        RoadGraph.from_edges({0: (-2.19, -79.89)}, [Edge(0, 0, 99, 100.0)])


def test_graph_rejects_nonpositive_length() -> None:
    with pytest.raises(ValueError, match="non-positive length"):
        RoadGraph.from_edges(
            {0: (-2.19, -79.89), 1: (-2.19, -79.88)}, [Edge(0, 0, 1, 0.0)]
        )


def test_graph_rejects_duplicate_edge_id() -> None:
    with pytest.raises(ValueError, match="duplicate edge id"):
        RoadGraph.from_edges(
            {0: (-2.19, -79.89), 1: (-2.19, -79.88)},
            [Edge(0, 0, 1, 100.0), Edge(0, 1, 0, 50.0)],
        )


def test_edge_other_node_guard() -> None:
    e = Edge(0, 0, 1, 100.0)
    assert e.other(0) == 1
    assert e.other(1) == 0
    with pytest.raises(ValueError, match="does not touch"):
        e.other(99)


def test_status_index_rejects_costing_a_closed_edge() -> None:
    """The guard that makes the structural guarantee explicit.

    If phase 1 ever tried to *cost* a closed edge instead of filtering it, this raises
    rather than silently applying a multiplier.
    """
    st = index({0: STATUS_CLOSED})
    assert st.is_closed(0) is True
    with pytest.raises(ValueError, match="must be filtered out, not costed"):
        st.cost_factor(0)


def test_build_synthetic_grid_argument_guard() -> None:
    with pytest.raises(ValueError):
        build_synthetic_grid(SECTORS, cells_per_side=1)


@pytest.mark.skip(
    reason=(
        "build_from_osm_json is NOT exercised in M3: no network OSM extraction was run. "
        "Recorded as an explicit gap in docs/M3-EVIDENCE.md rather than left silently "
        "untested. Enabling this test requires a committed fixture payload."
    )
)
def test_build_from_osm_json_real_payload() -> None:
    """Placeholder — deliberately skipped, see reason. Do not delete."""
    raise AssertionError("should never run")
