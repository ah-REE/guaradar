"""M10 tests — one-way directionality.

The point of this module is that directionality must be enforced by TRAVERSAL, not by a
metadata tag. A test asserting `edge.direction == "forward"` proves nothing about routing;
these tests assert that a search cannot reach through a one-way edge backwards.

All fixtures here are small synthetic graphs built for the purpose, clearly labelled, so the
assertions are about graph semantics rather than about the Guayaquil extract. The real-extract
tests at the end check the same properties against genuine OSM data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.routing.graph import (
    STATUS_CLOSED,
    STATUS_OPEN,
    Edge,
    EdgeStatus,
    RoadGraph,
    StatusIndex,
    haversine_m,
)
from app.routing.osm_source import DEFAULT_EXTRACT, build_graph_from_extract, parse_direction
from app.routing.search import find_routes

NOW = datetime(2026, 10, 26, 14, 0, 0, tzinfo=timezone.utc)


def chain(n: int = 3, direction: str = "both", start_lat: float = -2.19):
    """A straight chain 0-1-2-..., all edges sharing one direction."""
    coords = {i: (start_lat + i * 0.0005, -79.89) for i in range(n + 1)}
    edges = [
        Edge(i, i, i + 1, 100.0, name=f"e{i}", direction=direction)
        for i in range(n)
    ]
    return RoadGraph.from_edges(coords, edges, synthetic=True), edges


def two_parallel_routes() -> RoadGraph:
    """0 -> 2 via a short one-way edge, and via a longer two-way detour.

        0 -[short, FORWARD only]-> 1 -> 2   (both forward)
        0 -[detour, both]-> 3 -[both]-> 2
    """
    coords = {
        0: (-2.1900, -79.8900),
        1: (-2.1900, -79.8895),
        2: (-2.1900, -79.8890),
        3: (-2.1905, -79.8900),
    }
    edges = [
        Edge(0, 0, 1, 50.0, name="short-a", direction="forward"),
        Edge(1, 1, 2, 50.0, name="short-b", direction="forward"),
        Edge(2, 0, 3, 200.0, name="detour-a", direction="both"),
        Edge(3, 3, 2, 200.0, name="detour-b", direction="both"),
    ]
    return RoadGraph.from_edges(coords, edges, synthetic=True)


def status_all_open(graph: RoadGraph, now: datetime = NOW) -> StatusIndex:
    return StatusIndex(
        [EdgeStatus(eid, STATUS_OPEN, now - timedelta(minutes=1)) for eid in graph.edges],
        now=now,
    )


# ===========================================================================
# Tag parsing
# ===========================================================================


@pytest.mark.parametrize(
    "tags,expected",
    [
        ({"oneway": "yes"}, "forward"),
        ({"oneway": "true"}, "forward"),
        ({"oneway": "1"}, "forward"),
        ({"oneway": "YES"}, "forward"),
        ({"oneway": "-1"}, "backward"),
        ({"oneway": "reverse"}, "backward"),
        ({"oneway": "no"}, "both"),
        ({"oneway": "0"}, "both"),
        ({}, "both"),
    ],
)
def test_parse_direction_values(tags: dict, expected: str) -> None:
    direction, basis = parse_direction(tags)
    assert direction == expected
    assert basis, "every decision must record its basis"


def test_missing_tag_is_not_a_restriction() -> None:
    """Absence of a oneway tag must never be read as one-way."""
    direction, basis = parse_direction({})
    assert direction == "both"
    assert "not evidence of a restriction" in basis


def test_unrecognised_value_falls_back_to_two_way() -> None:
    direction, basis = parse_direction({"oneway": "sometimes"})
    assert direction == "both"
    assert "unrecognised" in basis


def test_roundabout_implies_oneway_even_without_tag() -> None:
    direction, basis = parse_direction({"junction": "roundabout"})
    assert direction == "forward"
    assert "roundabout" in basis


def test_explicit_oneway_no_wins_over_roundabout() -> None:
    """An explicit tag should beat the implied convention."""
    direction, _ = parse_direction({"junction": "roundabout", "oneway": "no"})
    assert direction == "both"


# ===========================================================================
# Edge direction semantics
# ===========================================================================


def test_both_direction_allows_both_ways() -> None:
    e = Edge(0, 10, 20, 100.0, direction="both")
    assert e.can_travel(10, 20) and e.can_travel(20, 10)


def test_forward_direction_blocks_reverse() -> None:
    e = Edge(0, 10, 20, 100.0, direction="forward")
    assert e.can_travel(10, 20) is True
    assert e.can_travel(20, 10) is False


def test_backward_direction_blocks_forward() -> None:
    e = Edge(0, 10, 20, 100.0, direction="backward")
    assert e.can_travel(10, 20) is False
    assert e.can_travel(20, 10) is True


def test_invalid_direction_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="unknown direction"):
        Edge(0, 1, 2, 100.0, direction="sideways")  # type: ignore[arg-type]


def test_directed_target_reports_illegal_travel_as_none() -> None:
    e = Edge(0, 10, 20, 100.0, direction="forward")
    assert e.directed_target(10) == 20
    assert e.directed_target(20) is None


def test_can_travel_rejects_unrelated_nodes() -> None:
    e = Edge(0, 10, 20, 100.0)
    with pytest.raises(ValueError):
        e.can_travel(10, 99)


# ===========================================================================
# Adjacency is outgoing-only — the structural enforcement
# ===========================================================================


def test_forward_edge_appears_only_at_its_start_node() -> None:
    g, edges = chain(1, direction="forward")
    e = edges[0]
    assert e.id in g.adjacency[e.a]
    assert e.id not in g.adjacency[e.b], "a forward edge must not be departable from b"


def test_backward_edge_appears_only_at_its_end_node() -> None:
    g, edges = chain(1, direction="backward")
    e = edges[0]
    assert e.id not in g.adjacency[e.a]
    assert e.id in g.adjacency[e.b]


def test_two_way_edge_appears_at_both() -> None:
    g, edges = chain(1, direction="both")
    e = edges[0]
    assert e.id in g.adjacency[e.a] and e.id in g.adjacency[e.b]


def test_neighbours_never_yields_illegal_travel() -> None:
    g, edges = chain(1, direction="forward")
    e = edges[0]
    from_b = [x.id for _, x in g.neighbours(e.b)]
    assert e.id not in from_b
    from_a = [x.id for _, x in g.neighbours(e.a)]
    assert e.id in from_a


def test_oneway_stats_report_by_direction() -> None:
    coords = {0: (-2.19, -79.89), 1: (-2.1895, -79.89), 2: (-2.189, -79.89)}
    edges = [
        Edge(0, 0, 1, 100.0, direction="forward"),
        Edge(1, 1, 2, 100.0, direction="both"),
    ]
    g = RoadGraph.from_edges(coords, edges, synthetic=True)
    stats = g.oneway_stats()
    assert stats["forward"] == 1
    assert stats["both"] == 1
    assert stats["oneway_total"] == 1


# ===========================================================================
# Routing must obey direction — the property that matters
# ===========================================================================


def test_route_cannot_travel_against_a_one_way() -> None:
    """A chain of forward-only edges is routable one way and refuses the other."""
    g, _ = chain(3, direction="forward")
    forward = find_routes(g, status_all_open(g), g.nodes[0].coord, g.nodes[3].coord)
    assert forward.refused is False
    assert forward.routes

    backward = find_routes(g, status_all_open(g), g.nodes[3].coord, g.nodes[0].coord)
    assert backward.refused is True, (
        "routing against a chain of one-way streets must refuse, not reverse them"
    )
    assert backward.routes == ()


def test_route_prefers_legal_detour_over_illegal_shortcut() -> None:
    """From 2 to 0 the short path is illegal, so the longer legal detour must be chosen."""
    g = two_parallel_routes()
    st = status_all_open(g)
    resp = find_routes(g, st, g.nodes[2].coord, g.nodes[0].coord)

    assert resp.refused is False
    assert resp.routes
    best = resp.routes[0]
    used = {leg.edge_id for leg in best.legs}
    assert 0 not in used and 1 not in used, (
        "the route used a forward-only edge in the reverse direction"
    )
    assert {2, 3} <= used, "the legal detour should have been used"
    # The detour is 400 m; the illegal shortcut would have been 100 m.
    assert best.distance_m == pytest.approx(400.0, rel=0.01)


def test_route_forward_uses_the_short_legal_path() -> None:
    g = two_parallel_routes()
    resp = find_routes(g, status_all_open(g), g.nodes[0].coord, g.nodes[2].coord)
    assert resp.refused is False
    best = resp.routes[0]
    assert best.distance_m == pytest.approx(100.0, rel=0.05)
    assert {0, 1} <= {leg.edge_id for leg in best.legs}


def test_mixed_directions_within_one_node() -> None:
    """At a junction, only some departures are legal; the search must honour that."""
    coords = {
        0: (-2.1900, -79.8900),
        1: (-2.1900, -79.8895),   # east
        2: (-2.1905, -79.8900),   # south
    }
    edges = [
        Edge(0, 0, 1, 100.0, direction="forward"),   # 0 -> 1 only
        Edge(1, 0, 2, 100.0, direction="forward"),   # 0 -> 2 only
        Edge(2, 1, 2, 100.0, direction="both"),
    ]
    g = RoadGraph.from_edges(coords, edges, synthetic=True)
    st = status_all_open(g)

    # From 1 to 0 is illegal directly (edge 0 is forward 0->1). Path must be 1->2->0? No:
    # edge 1 is 0->2 only, so 2->0 is also illegal. Therefore unreachable.
    resp = find_routes(g, st, g.nodes[1].coord, g.nodes[0].coord)
    assert resp.refused is True

    # From 0 to 1 is a direct legal hop.
    ok = find_routes(g, st, g.nodes[0].coord, g.nodes[1].coord)
    assert ok.refused is False


def test_parallel_roads_stay_distinct() -> None:
    """Two distinct segments between the same node pair must not collapse into one."""
    coords = {0: (-2.1900, -79.8900), 1: (-2.1900, -79.8895)}
    edges = [
        Edge(10, 0, 1, 100.0, name="one-way A->B", direction="forward"),
        Edge(11, 0, 1, 120.0, name="the other direction", direction="backward"),
    ]
    g = RoadGraph.from_edges(coords, edges, synthetic=True)
    assert 10 in g.edges and 11 in g.edges
    assert g.edges[10].can_travel(0, 1) is True
    assert g.edges[11].can_travel(1, 0) is True
    # Both directions are now traversable, via different physical segments.
    st = status_all_open(g)
    assert find_routes(g, st, g.nodes[0].coord, g.nodes[1].coord).refused is False
    assert find_routes(g, st, g.nodes[1].coord, g.nodes[0].coord).refused is False


# ===========================================================================
# Closure behaviour with directionality
# ===========================================================================


def test_closure_on_a_oneway_still_excluded_in_phase1() -> None:
    g, edges = chain(2, direction="forward")
    st = StatusIndex(
        [EdgeStatus(edges[0].id, STATUS_CLOSED, NOW - timedelta(minutes=1))]
        + [EdgeStatus(edges[1].id, STATUS_OPEN, NOW - timedelta(minutes=1))],
        now=NOW,
    )
    resp = find_routes(g, st, g.nodes[0].coord, g.nodes[2].coord)
    phase1 = [r for r in resp.routes if r.phase == 1]
    for r in phase1:
        assert all(leg.status != STATUS_CLOSED for leg in r.legs)


def test_unmapped_oneway_edge_is_unknown_not_clear() -> None:
    """A one-way edge with no status record must not be treated as verified."""
    g, edges = chain(2, direction="forward")
    st = StatusIndex([], now=NOW)      # no records at all
    assert st.status_of(edges[0].id) == "unknown"
    assert st.is_verified(edges[0].id) is False


# ===========================================================================
# Real extract: directionality against genuine OSM data
# ===========================================================================

needs_extract = pytest.mark.skipif(
    not DEFAULT_EXTRACT.exists(), reason="real OSM extract not present"
)


@needs_extract
def test_real_extract_has_oneway_streets() -> None:
    build = build_graph_from_extract(DEFAULT_EXTRACT)
    stats = build.graph.oneway_stats()
    assert stats["oneway_total"] > 0, (
        "the extract is tagged oneway=yes on most ways; zero would mean parsing failed"
    )
    assert build.direction_basis.get("tagged oneway=yes", 0) > 100


@needs_extract
def test_real_graph_adjacency_reflects_direction() -> None:
    """For every forward edge in the real graph, it must be absent from `b`'s adjacency."""
    build = build_graph_from_extract(DEFAULT_EXTRACT)
    g = build.graph
    checked = 0
    for e in g.edges.values():
        if e.direction == "forward":
            assert e.id in g.adjacency[e.a], f"forward edge {e.id} missing from a's adjacency"
            assert e.id not in g.adjacency[e.b], (
                f"forward edge {e.id} is departable from its far end — direction not enforced"
            )
            checked += 1
        elif e.direction == "backward":
            assert e.id not in g.adjacency[e.a]
            assert e.id in g.adjacency[e.b]
            checked += 1
    assert checked > 0, "no one-way edges found in the real extract"


@needs_extract
def test_real_route_does_not_traverse_a_oneway_backwards() -> None:
    """End-to-end: inspect the served route's legs and confirm each was legal."""
    build = build_graph_from_extract(DEFAULT_EXTRACT)
    g = build.graph
    ids = sorted(g.nodes)
    # Pick two nodes that are actually connected in the directed graph.
    origin = None
    dest = None
    for s in ids[:40]:
        seen = {s}
        stack = [s]
        while stack:
            u = stack.pop()
            for v, _ in g.neighbours(u):
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        far = [n for n in seen if n != s]
        if len(far) > 50:
            origin, dest = s, far[-1]
            break
    assert origin is not None, "no reachable pair found in the directed graph"

    resp = find_routes(g, status_all_open(g), g.nodes[origin].coord, g.nodes[dest].coord)
    assert resp.refused is False
    assert resp.routes

    for route in resp.routes:
        for leg in route.legs:
            edge = g.edges[leg.edge_id]
            assert edge.can_travel(leg.from_node, leg.to_node), (
                f"route traversed edge {leg.edge_id} against its legal direction"
            )
