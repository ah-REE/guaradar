"""M9 tests — stable edge identity (N-8).

These tests fall into three groups:

  * IDENTITY UNIT tests — encode/decode, bounds, rebuild stability. No data files needed.
  * REAL-EXTRACT tests — run against data/osm-central-guayaquil.json, a genuine Overpass
    extract of central Guayaquil fetched 2026-10-26. Skipped if the file is absent, so the
    suite still runs elsewhere, but their results are the actual evidence for N-8.
  * MAPPING tests — the graph-edge to road_segments relationship, including the "one way,
    many segments" case the brief warned about.

Nothing here asserts anything about flooding, closures, or safety. OSM supplies geometry.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.routing.graph import Edge, RoadGraph, haversine_m
from app.routing.identity import (
    ORDINAL_SPACE,
    EdgeIdentity,
    IdentityError,
    build_mappings,
    decode_edge_id,
    encode_edge_id,
    mapping_stats,
    segments_from_way,
)
from app.routing.osm_source import (
    DEFAULT_EXTRACT,
    build_graph_from_extract,
    load_extract,
    mapping_stats_from_build,
    segment_rows,
)

EXTRACT_AVAILABLE = DEFAULT_EXTRACT.exists()
needs_extract = pytest.mark.skipif(
    not EXTRACT_AVAILABLE,
    reason=f"real OSM extract not present at {DEFAULT_EXTRACT}",
)


# ===========================================================================
# 1. Identity encoding is invertible and bounded
# ===========================================================================


@pytest.mark.parametrize(
    "way,ordinal",
    [(31097791, 0), (31097816, 1), (31097816, 2), (1, 999), (0, 0)],
)
def test_encode_decode_roundtrip(way: int, ordinal: int) -> None:
    ident = EdgeIdentity("osm", way, ordinal)
    encoded = ident.encode()
    assert EdgeIdentity.decode(encoded) == ident
    assert decode_edge_id(encoded) == (way, ordinal)


def test_encode_is_deterministic_not_sequential() -> None:
    """The same identity must always produce the same integer, regardless of order."""
    a = encode_edge_id(31097816, 3)
    # Recompute in a different "order"
    b = encode_edge_id(31097816, 3)
    assert a == b
    # And a different way must not collide
    assert a != encode_edge_id(31097817, 3)


def test_ordinal_beyond_space_raises_rather_than_colliding() -> None:
    """A way with more segments than the ordinal space must fail loudly, not alias another."""
    with pytest.raises(IdentityError, match="ordinal space widened"):
        EdgeIdentity("osm", 42, ORDINAL_SPACE)
    with pytest.raises(IdentityError):
        EdgeIdentity("osm", 42, -1)


def test_negative_edge_id_rejected() -> None:
    with pytest.raises(IdentityError):
        EdgeIdentity.decode(-1)


def test_source_is_part_of_the_key() -> None:
    """Two datasets could reuse a numeric way id; the source must keep them distinct."""
    osm = EdgeIdentity("osm", 100, 0)
    synth = EdgeIdentity("synthetic", 100, 0)
    assert osm.encode() == synth.encode(), "same integer by design"
    assert osm.as_key() != synth.as_key(), "but the natural keys differ"


# ===========================================================================
# 2. Segments from one way — the multi-edge case
# ===========================================================================


def coords_for(n: int) -> dict[int, tuple[float, float]]:
    return {i: (-2.19 + i * 0.0005, -79.89) for i in range(n)}


def test_one_way_yields_many_segments_with_distinct_ordinals() -> None:
    nodes = [10, 11, 12, 13]
    segs = segments_from_way(
        777, nodes, coords_for(20), road_class="residential", name="Calle X",
        haversine_m=haversine_m,
    )
    assert len(segs) == 3
    assert [s.identity.segment_ordinal for s in segs] == [0, 1, 2]
    assert {s.identity.way_id for s in segs} == {777}
    assert len({s.identity.encode() for s in segs}) == 3


def test_segment_ordinal_follows_node_order_not_iteration() -> None:
    """Identity must derive from the source node sequence, so a rebuild renumbers nothing."""
    nodes = [10, 11, 12]
    forward = segments_from_way(
        777, nodes, coords_for(20), road_class="residential", name="X",
        haversine_m=haversine_m,
    )
    again = segments_from_way(
        777, list(nodes), coords_for(20), road_class="residential", name="X",
        haversine_m=haversine_m,
    )
    assert [s.identity for s in forward] == [s.identity for s in again]


def test_missing_node_coords_skip_segment_but_keep_ordinal_slot() -> None:
    """A gap in the extract must not shift later ordinals, or identities would drift."""
    nodes = [10, 11, 12, 13]
    coords = coords_for(20)
    del coords[11]     # node 11 has no coordinates
    segs = segments_from_way(
        777, nodes, coords, road_class="residential", name="X", haversine_m=haversine_m,
    )
    # Segments (10,11) and (11,12) are unbuildable; only (12,13) survives, as ordinal 2.
    assert len(segs) == 1
    assert segs[0].identity.segment_ordinal == 2


def test_single_node_way_yields_nothing() -> None:
    assert segments_from_way(1, [5], coords_for(20), road_class="x", name=None,
                             haversine_m=haversine_m) == []


# ===========================================================================
# 3. Mapping records
# ===========================================================================


def make_segs(n: int = 3, way: int = 500):
    nodes = list(range(n + 1))
    return segments_from_way(
        way, nodes, coords_for(n + 5), road_class="residential", name="Y",
        haversine_m=haversine_m,
    )


def test_mapped_identity_gets_road_segment_id() -> None:
    segs = make_segs(2)
    mappings, notes = build_mappings(segs, lambda ident: 9000 + ident.segment_ordinal)
    assert [m.road_segment_id for m in mappings] == [9000, 9001]
    assert notes == ()


def test_unmapped_edge_stays_unmapped_and_is_reported() -> None:
    """No invented road_segments row: unmapped means unknown status downstream."""
    segs = make_segs(3)
    mappings, notes = build_mappings(segs, lambda ident: None)
    assert all(m.road_segment_id == 0 for m in mappings)
    assert any("stay unmapped" in n for n in notes)
    stats = mapping_stats(mappings)
    assert stats == {"graph_edges": 3, "mapped": 0, "unmapped": 3}


def test_partial_mapping_is_counted_honestly() -> None:
    segs = make_segs(4)
    mappings, _ = build_mappings(
        segs, lambda ident: 1 if ident.segment_ordinal % 2 == 0 else None
    )
    stats = mapping_stats(mappings)
    assert stats["mapped"] == 2
    assert stats["unmapped"] == 2, "a partial match must not be rounded up"


# ===========================================================================
# 4. Real extract — identity stability and multi-segment ways
# ===========================================================================

pytestmark_real = needs_extract


@needs_extract
def test_real_extract_loads_with_provenance() -> None:
    payload, prov = load_extract(DEFAULT_EXTRACT)
    assert prov.way_count > 0
    assert prov.node_count > 0
    assert prov.osm_timestamp is not None, "an extract without a timestamp is not traceable"
    assert prov.licence.startswith("ODbL")
    notes = " ".join(prov.notes())
    assert "no flood, closure or safety data" in notes


@needs_extract
def test_real_build_reports_identity_for_every_edge() -> None:
    build = build_graph_from_extract(DEFAULT_EXTRACT)
    stats = mapping_stats_from_build(build)
    assert stats["graph_edges"] > 0
    assert stats["with_source_identity"] == stats["graph_edges"], (
        "every edge must have a source identity; otherwise the scheme has a hole"
    )


@needs_extract
def test_real_edge_ids_decode_to_real_osm_ways() -> None:
    """Every integer id must decode to a way id that exists in the extract."""
    payload, _ = load_extract(DEFAULT_EXTRACT)
    way_ids = {e["id"] for e in payload["elements"] if e.get("type") == "way"}
    build = build_graph_from_extract(DEFAULT_EXTRACT)

    for edge_id in build.graph.edges:
        ident = EdgeIdentity.decode(edge_id)
        assert ident.way_id in way_ids, f"edge {edge_id} decodes to unknown way {ident.way_id}"
        assert 0 <= ident.segment_ordinal < ORDINAL_SPACE


@needs_extract
def test_real_build_is_stable_across_rebuilds() -> None:
    """Requirement 1: identical ids on a second build. This is the whole point of the scheme."""
    first = build_graph_from_extract(DEFAULT_EXTRACT)
    second = build_graph_from_extract(DEFAULT_EXTRACT)
    assert sorted(first.graph.edges) == sorted(second.graph.edges)
    # And the identity of every edge maps to the same way/ordinal.
    assert first.identities() == second.identities()


@needs_extract
def test_real_extract_has_multi_segment_ways() -> None:
    """Confirms empirically that one OSM way does NOT identify one graph edge."""
    build = build_graph_from_extract(DEFAULT_EXTRACT)
    by_way: dict[int, int] = {}
    for seg in build.segments:
        by_way[seg.identity.way_id] = by_way.get(seg.identity.way_id, 0) + 1

    multi = {w: c for w, c in by_way.items() if c > 1}
    assert multi, "expected at least one way to split into several segments"
    assert max(by_way.values()) < ORDINAL_SPACE, (
        "a way with more segments than the ordinal space would collide"
    )
    # Restate the measured reality for the evidence report.
    assert len(multi) >= 50, f"expected many split ways, got {len(multi)}"


@needs_extract
def test_real_build_is_not_labelled_synthetic() -> None:
    """The extract is genuine OSM data, so the graph must not claim to be synthetic."""
    build = build_graph_from_extract(DEFAULT_EXTRACT)
    assert build.graph.synthetic is False
    assert build.graph.osm_timestamp is not None


@needs_extract
def test_real_graph_is_weakly_connected() -> None:
    """The network is one piece when direction is ignored.

    M10 NOTE: this test previously asserted `components == 1` on an UNDIRECTED adjacency.
    Now that one-way tags are honoured, adjacency is outgoing-only, so a directed
    connected-component count is not the right measure — many streets can only be entered
    from one end. Weak connectivity is the property that still holds and still matters
    (the road network is one piece of geography), so it is asserted explicitly here.
    """
    from collections import defaultdict

    build = build_graph_from_extract(DEFAULT_EXTRACT)
    g = build.graph
    und: dict[int, set[int]] = defaultdict(set)
    for e in g.edges.values():
        und[e.a].add(e.b)
        und[e.b].add(e.a)

    seen: set[int] = set()
    comps: list[int] = []
    for n in g.nodes:
        if n in seen:
            continue
        stack = [n]
        seen.add(n)
        size = 0
        while stack:
            u = stack.pop()
            size += 1
            for v in und[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        comps.append(size)

    comps.sort(reverse=True)
    # M10 NOTE: the wider demo-sectors extract legitimately contains small detached
    # fragments (side streets whose connecting way falls outside the bounding box), so
    # asserting exactly one component would now be asserting something false. What matters
    # is that the network is overwhelmingly one piece; the measured value is 97.6 %.
    largest_pct = 100.0 * comps[0] / len(g.nodes)
    assert largest_pct >= 95.0, (
        f"largest weak component is only {largest_pct:.1f} % of nodes; the extract may be "
        f"truncated or the builder may be dropping ways"
    )
    # Fragments must be small, not a second real network.
    assert comps[1] < len(g.nodes) * 0.02 if len(comps) > 1 else True


@needs_extract
def test_real_graph_is_not_strongly_connected_which_is_expected() -> None:
    """Documents the honest consequence of honouring one-way tags.

    A directed network of one-way streets is NOT strongly connected: some nodes cannot be
    reached from others. This is a property of the DATA, not a defect. If this ever became
    fully strongly connected, directionality would have stopped being applied.
    """
    build = build_graph_from_extract(DEFAULT_EXTRACT)
    g = build.graph
    ids = sorted(g.nodes)
    sample = ids[:25]

    reach = []
    for s in sample:
        seen = {s}
        stack = [s]
        while stack:
            u = stack.pop()
            for v, _ in g.neighbours(u):
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        reach.append(len(seen))

    worst = min(reach)
    assert worst < len(g.nodes), (
        "every sampled node reached the whole graph — directionality is not being applied"
    )
    # And it must still be a large fraction, i.e. the network is usable, not fragmented.
    assert max(reach) > len(g.nodes) * 0.4, "no node can reach a useful share of the network"


@needs_extract
def test_real_segment_rows_are_idempotent_by_construction() -> None:
    """Requirement 8: repeated builds produce the SAME row keys, so upserts cannot duplicate."""
    build = build_graph_from_extract(DEFAULT_EXTRACT)
    payload, _ = load_extract(DEFAULT_EXTRACT)
    node_coords = {
        e["id"]: (e["lat"], e["lon"])
        for e in payload["elements"]
        if e.get("type") == "node" and "lat" in e
    }

    first = segment_rows(build, node_coords)
    second = segment_rows(build_graph_from_extract(DEFAULT_EXTRACT), node_coords)

    # The primary key and the identity columns must be identical across builds.
    assert [r[0] for r in first] == [r[0] for r in second]
    assert [(r[1], r[2]) for r in first] == [(r[1], r[2]) for r in second]
    assert len({r[0] for r in first}) == len(first), "road_segment ids must be unique"
    assert len({(r[1], r[2]) for r in first}) == len(first), (
        "the (way, ordinal) natural key must be unique"
    )


@needs_extract
def test_real_segment_rows_avoid_legacy_seed_id_space() -> None:
    """The new rows must not collide with the seeded demo ids (1001…3050)."""
    build = build_graph_from_extract(DEFAULT_EXTRACT)
    payload, _ = load_extract(DEFAULT_EXTRACT)
    node_coords = {
        e["id"]: (e["lat"], e["lon"])
        for e in payload["elements"]
        if e.get("type") == "node" and "lat" in e
    }
    rows = segment_rows(build, node_coords)
    for r in rows:
        assert r[0] > 3050, f"row id {r[0]} would overwrite seeded demo data"


@needs_extract
def test_real_row_edge_id_matches_identity_constraint() -> None:
    """Mirrors the DB CHECK: edge_id must equal way_id * 1000 + ordinal."""
    build = build_graph_from_extract(DEFAULT_EXTRACT)
    payload, _ = load_extract(DEFAULT_EXTRACT)
    node_coords = {
        e["id"]: (e["lat"], e["lon"])
        for e in payload["elements"]
        if e.get("type") == "node" and "lat" in e
    }
    for r in segment_rows(build, node_coords):
        _rid, way_id, ordinal, edge_id = r[0], r[1], r[2], r[3]
        assert edge_id == way_id * 1000 + ordinal
        assert 0 <= ordinal <= 999


# ===========================================================================
# 5. Duplicate / invalid source records
# ===========================================================================


def test_duplicate_way_ids_are_deduplicated(tmp_path: Path) -> None:
    """A payload containing the same way twice must not create two identities for it."""
    nodes = [
        {"type": "node", "id": 1, "lat": -2.19, "lon": -79.89},
        {"type": "node", "id": 2, "lat": -2.1895, "lon": -79.89},
    ]
    way = {
        "type": "way", "id": 4242,
        "nodes": [1, 2],
        "tags": {"highway": "residential", "name": "Dup Road"},
    }
    payload = {
        "elements": nodes + [way, dict(way)],          # the same way twice
        "osm3s": {"timestamp_osm_base": "2026-10-26T00:00:00Z"},
    }
    p = tmp_path / "dup.json"
    p.write_text(json.dumps(payload))

    build = build_graph_from_extract(p)
    assert len(build.segments) == 1, "a duplicated way must not yield two segments"


def test_way_without_highway_tag_is_ignored(tmp_path: Path) -> None:
    payload = {
        "elements": [
            {"type": "node", "id": 1, "lat": -2.19, "lon": -79.89},
            {"type": "node", "id": 2, "lat": -2.1895, "lon": -79.89},
            {"type": "way", "id": 1, "nodes": [1, 2], "tags": {"building": "yes"}},
        ],
        "osm3s": {"timestamp_osm_base": "2026-10-26T00:00:00Z"},
    }
    p = tmp_path / "one.json"
    p.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="no routable segments"):
        build_graph_from_extract(p)


def test_extract_without_elements_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"nope": 1}))
    with pytest.raises(ValueError, match="no 'elements'"):
        load_extract(p)


# ===========================================================================
# 6. The database view contract (SQL text assertions, no DB required)
# ===========================================================================


def test_migration_view_joins_through_edge_id_not_position() -> None:
    """The view must join on edge_id, never on array position or name."""
    # tests/unit/test_m9_identity.py -> parents[0]=unit, [1]=tests, [2]=backend, [3]=repo root
    sql = (Path(__file__).resolve().parents[3] / "supabase" / "migrations"
           / "0006_road_identity.sql").read_text(encoding="utf-8")
    view = sql[sql.index("create or replace view road_edge_status"):]
    assert "rs.edge_id" in view
    assert "road_status st on st.road_segment_id = rs.id" in view
    # No heuristic joins anywhere in the migration.
    for forbidden in ("soundex", "similarity", "percent", "levenshtein", "st_distance"):
        assert forbidden not in sql.lower(), f"migration contains a fuzzy-match construct: {forbidden}"
    assert "edge_id = osm_way_id * 1000 + segment_ordinal" in sql
