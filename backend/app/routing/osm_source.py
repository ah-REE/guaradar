"""Build a road graph from a real OSM extract, with stable identity end to end (N-8).

This is the module that closes N-8: the graph and the `road_segments` rows now come from the
**same** source, so `Edge.id` is `osm_way_id * 1000 + segment_ordinal` on both sides and
persisted status applies to routes by construction rather than by luck.

SOURCE PROVENANCE
  data/osm-central-guayaquil.json — fetched 2026-10-26 from the Overpass API:
      bbox: -2.2000,-79.8950 to -2.1900,-79.8850  (central Guayaquil, ~1.1 x 1.1 km)
      query: highway in (primary, secondary, tertiary, residential), out body + skel
      osm timestamp: 2026-10-26T01:23:40Z
      contents: 148 ways, 841 nodes
  Real OSM data, ODbL. It provides **road geometry and names only**. It says nothing about
  flooding, closures, or safety, and nothing in this project should imply otherwise.

LIMITS OF THIS EXTRACT
  * ~1.1 km square around the centre. Durán, Samborondón and the northern suburbs are absent.
  * No turn restrictions, no one-way modelling, no lane count. Directionality is preserved only
    as way node order.
  * Coverage of the demo area is therefore partial, and the response says so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.routing.graph import Edge, RoadGraph, haversine_m
from app.routing.identity import (
    EdgeIdentity,
    SourceSegment,
    segments_from_way,
)

# Path chain: app/routing/osm_source.py -> parents[0]=routing, [1]=app, [2]=backend, [3]=repo root.
# The extract lives at <repo>/data/, i.e. parents[3] / 'data'.
# M10: the primary extract now covers all three demo sectors (~12.8 x 6.4 km, 5,809 ways).
# The earlier 1.1 km central extract is retained as a small fallback fixture.
DEFAULT_EXTRACT = Path(__file__).resolve().parents[3] / "data" / "osm-guayaquil-demo-sectors.json"
CENTRAL_EXTRACT = Path(__file__).resolve().parents[3] / "data" / "osm-central-guayaquil.json"

EXTRACT_BBOX = {
    "south": -2.2350,
    "west": -79.9250,
    "north": -2.1350,
    "east": -79.8800,
}

HIGHWAY_CLASSES = ("primary", "secondary", "tertiary", "residential")


# One-way tag parsing.
#
# Deliberately conservative: only values that explicitly mean "one-way" are treated as one.
# A MISSING tag, or an unrecognised value, yields 'both' — absence of a restriction tag is not
# evidence that a restriction exists. Inventing one-way streets would be as wrong as ignoring
# real ones.
ONEWAY_FORWARD = {"yes", "true", "1"}
ONEWAY_BACKWARD = {"-1", "reverse"}
ONEWAY_BOTH = {"no", "false", "0", ""}


def parse_direction(tags: Mapping[str, Any]) -> tuple[str, str]:
    """Return (direction, basis) for an OSM way.

    `basis` records WHY the direction was chosen, so the evidence report can separate a tagged
    one-way from one implied by a roundabout and from a plain default.
    """
    raw = tags.get("oneway")
    value = str(raw).strip().lower() if raw is not None else None

    if value in ONEWAY_FORWARD:
        return "forward", "tagged oneway=yes"
    if value in ONEWAY_BACKWARD:
        return "backward", "tagged oneway=-1 (reverse)"
    if value in ONEWAY_BOTH:
        return "both", "tagged oneway=no" if value not in (None, "") else "tagged oneway empty"

    # junction=roundabout implies one-way in OSM convention, whether or not oneway is tagged.
    if str(tags.get("junction", "")).strip().lower() == "roundabout":
        return "forward", "implied by junction=roundabout"

    if value is None:
        return "both", "no oneway tag (not evidence of a restriction)"
    return "both", f"unrecognised oneway={value!r}, treated as two-way"



@dataclass(frozen=True)
class ExtractProvenance:
    """Where the data came from, recorded so a reader never has to guess."""

    path: str
    provider: str
    osm_timestamp: datetime | None
    way_count: int
    node_count: int
    bbox: dict[str, float]
    licence: str = "ODbL (© OpenStreetMap contributors)"

    def notes(self) -> tuple[str, ...]:
        ts = self.osm_timestamp.isoformat() if self.osm_timestamp else "unknown"
        return (
            f"road geometry from a real OSM extract ({self.provider}), OSM data timestamp {ts}",
            f"extent: lat {self.bbox['south']}..{self.bbox['north']}, "
            f"lon {self.bbox['west']}..{self.bbox['east']} (central Guayaquil only)",
            f"{self.way_count} source ways, {self.node_count} nodes",
            "OSM provides road geometry and names only — no flood, closure or safety data",
        )


@dataclass(frozen=True)
class OsmBuild:
    """The built graph plus everything needed to persist matching road_segments rows."""

    graph: RoadGraph
    segments: tuple[SourceSegment, ...]
    provenance: ExtractProvenance
    # Why each way got its direction, e.g. {"tagged oneway=yes": 140}. Reported so a reader
    # can tell a tagged one-way from a default.
    direction_basis: dict[str, int] = field(default_factory=dict)

    def identities(self) -> tuple[EdgeIdentity, ...]:
        return tuple(s.identity for s in self.segments)


def load_extract(path: Path | str = DEFAULT_EXTRACT) -> tuple[dict[str, Any], ExtractProvenance]:
    """Read and validate an Overpass `out body; >; out skel qt;` payload."""
    p = Path(path)
    payload = json.loads(p.read_text(encoding="utf-8"))
    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise ValueError("extract has no 'elements' array")

    ways = [e for e in elements if e.get("type") == "way"]
    nodes = [e for e in elements if e.get("type") == "node"]
    if not ways:
        raise ValueError("extract contains no ways")

    ts_raw = (payload.get("osm3s") or {}).get("timestamp_osm_base")
    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")) if ts_raw else None

    prov = ExtractProvenance(
        path=str(p),
        provider="Overpass API",
        osm_timestamp=ts,
        way_count=len(ways),
        node_count=len(nodes),
        bbox=dict(EXTRACT_BBOX),
    )
    return payload, prov


def build_graph_from_extract(
    path: Path | str = DEFAULT_EXTRACT,
) -> OsmBuild:
    """Build a real road graph whose edge ids encode source identity.

    Every edge's integer id is `osm_way_id * 1000 + segment_ordinal`, so the same extract
    always produces the same ids, and any id can be decoded back to the road it came from.
    """
    payload, prov = load_extract(path)

    node_coords: dict[int, tuple[float, float]] = {}
    for e in payload.get("elements", []):
        if e.get("type") == "node" and "lat" in e and "lon" in e:
            node_coords[e["id"]] = (e["lat"], e["lon"])

    segments: list[SourceSegment] = []
    seen_identities: set[tuple[str, int, int]] = set()
    duplicate_ways = 0
    direction_basis: dict[str, int] = {}

    for way in sorted(
        (e for e in payload.get("elements", []) if e.get("type") == "way"),
        key=lambda w: w["id"],
    ):
        way_id = way["id"]
        tags = way.get("tags") or {}
        road_class = tags.get("highway")
        if road_class not in HIGHWAY_CLASSES:
            continue

        direction, _basis = parse_direction(tags)
        direction_basis[_basis] = direction_basis.get(_basis, 0) + 1

        built = segments_from_way(
            way_id,
            way.get("nodes") or [],
            node_coords,
            road_class=road_class,
            name=tags.get("name"),
            haversine_m=haversine_m,
            source="osm",
            direction=direction,
        )

        for seg in built:
            key = seg.identity.as_key()
            if key in seen_identities:
                # A duplicated way id in the payload would otherwise create two rows claiming
                # the same source segment, which is how a closure could apply to the wrong road.
                duplicate_ways += 1
                continue
            seen_identities.add(key)
            segments.append(seg)

    if not segments:
        raise ValueError("extract produced no routable segments")

    # Build the graph. Nodes are the OSM node ids themselves, so a route's geometry is real.
    used_nodes: set[int] = set()
    for s in segments:
        used_nodes.add(s.from_node)
        used_nodes.add(s.to_node)

    edges = [
        Edge(
            id=s.identity.encode(),
            a=s.from_node,
            b=s.to_node,
            length_m=s.length_m,
            road_class=s.road_class,
            name=s.name,
            # Elevation is filled later by terrain sampling; unknown here is honest.
            elevation_m=None,
            synthetic=False,
            # Legal travel direction, from the source tags. This is what makes the graph
            # directed; adding it to metadata alone would not change traversal.
            direction=s.direction,  # type: ignore[arg-type]
        )
        for s in segments
    ]

    graph = RoadGraph.from_edges(
        {n: node_coords[n] for n in used_nodes},
        edges,
        synthetic=False,
        osm_timestamp=prov.osm_timestamp,
    )

    return OsmBuild(
        graph=graph,
        segments=tuple(segments),
        provenance=prov,
        direction_basis=direction_basis,
    )


# ---------------------------------------------------------------------------
# Persistence of the mapping (idempotent)
# ---------------------------------------------------------------------------

UPSERT_SEGMENT_SQL = """
insert into road_segments
    (id, osm_way_id, segment_ordinal, edge_id, source_kind, name, road_class,
     sector_id, geom_latlon, length_m, elevation_m, elevation_source, osm_timestamp)
values ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, null, null, $11)
on conflict (source_kind, osm_way_id, segment_ordinal) where osm_way_id is not null and segment_ordinal is not null
do update set
    edge_id = excluded.edge_id,
    name = excluded.name,
    road_class = excluded.road_class,
    geom_latlon = excluded.geom_latlon,
    length_m = excluded.length_m,
    osm_timestamp = excluded.osm_timestamp
returning id
"""


def segment_rows(
    build: OsmBuild,
    node_coords: Mapping[int, tuple[float, float]],
    *,
    sector_id: str | None = None,
) -> list[tuple]:
    """Row tuples ready for UPSERT_SEGMENT_SQL.

    `road_segments.id` is allocated from a stable space derived from the identity, so repeat
    builds update the same rows instead of inserting new ones. The id is
    `way_id * 1000 + ordinal` plus a large offset, keeping it clear of the legacy seed ids
    (1001…3050) so an accidental collision cannot overwrite seeded demo data.
    """
    LEGACY_SAFE_OFFSET = 1_000_000_000
    rows: list[tuple] = []
    for seg in build.segments:
        way_id, ordinal = seg.identity.way_id, seg.identity.segment_ordinal
        road_segment_id = LEGACY_SAFE_OFFSET + seg.identity.encode()
        geom = [
            [node_coords[seg.from_node][0], node_coords[seg.from_node][1]],
            [node_coords[seg.to_node][0], node_coords[seg.to_node][1]],
        ]
        rows.append(
            (
                road_segment_id,
                way_id,
                ordinal,
                seg.identity.encode(),
                "osm",
                seg.name,
                seg.road_class,
                sector_id,
                json.dumps(geom),
                seg.length_m,
                build.provenance.osm_timestamp,
            )
        )
    return rows


def mapping_stats_from_build(build: OsmBuild) -> dict[str, int]:
    """Counts for the evidence report: how many edges carry a real source identity."""
    total = len(build.segments)
    with_name = sum(1 for s in build.segments if s.name)
    return {
        "graph_edges": total,
        "with_source_identity": total,      # every edge came from a way + ordinal
        "named_roads": with_name,
        "unnamed_segments": total - with_name,
    }
