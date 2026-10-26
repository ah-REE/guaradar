"""Stable graph-edge identity (closes N-8).

THE PROBLEM THIS SOLVES
  Before M9 the router's `Edge.id` was a sequential counter from `build_synthetic_grid`, while
  `road_segments.id` came from `seed.sql` ordinal arithmetic. Two independent generators, no
  shared identifier, so persisted road status could never apply to a route (N-8).

  A second, subtler problem: **an OSM way id does not uniquely identify a graph edge.** Measured
  against a real extract of central Guayaquil (data/osm-central-guayaquil.json, 148 ways):

      total graph segments   994
      ways split into >1     116 of 148
      mean segments per way  6.7
      max segments per way   47

  So one source road legitimately becomes many graph edges, and a closure on that road must
  propagate to exactly those edges — no more.

THE IDENTITY MODEL
  Natural key:  (source, source_way_id, segment_ordinal)
  Router int:   edge_id = source_way_id * ORDINAL_SPACE + segment_ordinal

  Why this and not the alternatives:

    * Sequential counter — UNSTABLE. Inserting one way renumbers every later edge, so a stored
      mapping would silently point at a different road after a rebuild. Rejected.
    * Hash of (way, ordinal) — stable but opaque and collision-prone; nothing downstream could
      audit a mapping it cannot read. Rejected as the primary key.
    * Composite natural key with an invertible surrogate — ADOPTED. Both components are
      meaningful, the pair is stable because it derives from source data plus position within
      that source, and `decode()` recovers the source identity from the integer.

  `ORDINAL_SPACE = 1000` is the only magic number. It is safe because the measured maximum is
  47 segments per way; `encode()` **raises** if a caller ever exceeds it rather than silently
  producing a colliding id. That bound is asserted by a test against the real extract.

  Segment identity is derived from the **way's node sequence** (which node pair it spans), so it
  survives a rebuild of the same source data. It is NOT an array index into a mutable list.

WHAT THIS DOES NOT DO
  * It does not make synthetic data real. `RoadGraph.synthetic` still reflects the source.
  * It does not claim OSM provides flood conditions, closures, or verified status. OSM provides
    road geometry and names; status remains operator/report/seed data.
  * It does not resolve directionality beyond preserving way node order. Turn restrictions and
    one-way tags are not modelled here (recorded as a limitation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Mapping, Sequence

# One thousand ordinals per source way. Measured maximum is 47; encode() refuses to exceed it.
ORDINAL_SPACE = 1000

# Segments shorter than this are treated as data noise and skipped. See segments_from_way.
#
# Set to 0.1 m rather than a centimetre because lengths are ROUNDED TO 1 DECIMAL for storage.
# `round(0.011, 1) == 0.0`, so any segment under 0.05 m would be stored as a zero-length edge
# and then fail the "positive length" invariant downstream — which is exactly how this was
# discovered (way 1556835856, an 11 mm segment). Thresholding at the storage precision avoids
# storing a value the invariant rejects.
MIN_SEGMENT_LENGTH_M = 0.1

SourceKind = Literal["osm", "synthetic"]


class IdentityError(ValueError):
    """Raised for programmer error or an id that cannot represent a valid identity."""


@dataclass(frozen=True, order=True)
class EdgeIdentity:
    """The stable identity of one graph edge.

    `source` is part of the key because the same numeric way id could in principle appear in
    two different datasets. Including it prevents a cross-source collision from ever being
    silently accepted.
    """

    source: SourceKind
    way_id: int
    segment_ordinal: int

    def __post_init__(self) -> None:
        if self.way_id < 0:
            raise IdentityError(f"way_id must be >= 0, got {self.way_id}")
        if not 0 <= self.segment_ordinal < ORDINAL_SPACE:
            raise IdentityError(
                f"segment_ordinal must be within 0..{ORDINAL_SPACE - 1}, "
                f"got {self.segment_ordinal} — a way with more segments than this needs the "
                f"ordinal space widened, not a colliding id"
            )

    def encode(self) -> int:
        """Invertible integer for the router.

        Not a hash and not a counter: `decode(encode(x)) == x` always, which is what lets the
        API return an int id while remaining auditable.
        """
        return self.way_id * ORDINAL_SPACE + self.segment_ordinal

    @classmethod
    def decode(cls, edge_id: int, source: SourceKind = "osm") -> "EdgeIdentity":
        if edge_id < 0:
            raise IdentityError(f"edge_id must be >= 0, got {edge_id}")
        return cls(
            source=source,
            way_id=edge_id // ORDINAL_SPACE,
            segment_ordinal=edge_id % ORDINAL_SPACE,
        )

    def as_key(self) -> tuple[str, int, int]:
        """Tuple form for database rows and dict keys."""
        return (self.source, self.way_id, self.segment_ordinal)


def encode_edge_id(way_id: int, segment_ordinal: int) -> int:
    return EdgeIdentity("osm", way_id, segment_ordinal).encode()


def decode_edge_id(edge_id: int) -> tuple[int, int]:
    ident = EdgeIdentity.decode(edge_id)
    return (ident.way_id, ident.segment_ordinal)


# ---------------------------------------------------------------------------
# Building identities from a source extract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceSegment:
    """One graph segment derived from a source way.

    Carries the geometry so the caller can build an Edge without re-deriving identity.
    """

    identity: EdgeIdentity
    from_node: int
    to_node: int
    length_m: float
    road_class: str
    name: str | None
    # Ordinal position is meaningful: it is the segment's place in the way's node order.
    node_sequence_index: int
    # Legal travel direction of this physical segment ('both' | 'forward' | 'backward').
    # Identity is unaffected: a one-way segment is still one segment with one edge_id.
    direction: str = "both"


def segments_from_way(
    way_id: int,
    node_ids: Sequence[int],
    node_coords: Mapping[int, tuple[float, float]],
    *,
    road_class: str,
    name: str | None,
    haversine_m,
    source: SourceKind = "osm",
    direction: str = "both",
) -> list[SourceSegment]:
    """Split one source way into graph segments with stable identities.

    Every consecutive node pair becomes one segment, and its ordinal is its position in the
    way's node list. That makes identity a function of the **source data**, not of iteration
    order during a build: rebuilding the same extract yields the same ids.

    Nodes missing coordinates are skipped, and the ordinal still advances, so a later repair of
    the extract does not renumber the remaining segments.
    """
    if len(node_ids) < 2:
        return []

    out: list[SourceSegment] = []
    for ordinal, (a, b) in enumerate(zip(node_ids, node_ids[1:])):
        if a not in node_coords or b not in node_coords:
            # Skip unbuildable geometry but keep the ordinal slot, so identities of the
            # segments that DO exist stay stable if this gap is later filled.
            continue
        if a == b:
            # A way repeating the same node yields no segment at all.
            continue
        length = haversine_m(node_coords[a], node_coords[b])
        if round(length, 1) < MIN_SEGMENT_LENGTH_M:
            # Real OSM data contains DISTINCT node ids at effectively identical coordinates.
            # Observed in the Guayaquil extract:
            #   way 31097256  nodes 411046932 / 405568714  -> 0.000 m (same coordinate pair)
            #   way 1556835856 nodes 14160137365 / 14160134939 -> 0.011 m (rounds to 0.0)
            # A sub-centimetre segment is below the precision of the source data and is not
            # routable, so it is skipped. The ordinal slot is KEPT, exactly as for a missing
            # node, so the identities of neighbouring segments do not shift.
            #
            # The threshold is 1 cm, not a rounding artefact: `round(length, 1)` would map a
            # 11 mm segment to 0.0 and then fail the "positive length" invariant downstream,
            # which is how this was found.
            continue
        out.append(
            SourceSegment(
                identity=EdgeIdentity(source, way_id, ordinal),
                from_node=a,
                to_node=b,
                length_m=round(length, 1),
                road_class=road_class,
                name=name,
                node_sequence_index=ordinal,
                direction=direction,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Mapping records: graph edge <-> persisted road_segments row
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EdgeMapping:
    """An explicit graph-edge-to-source-road mapping.

    This is the artefact that replaces guessing. It is written once per build, is idempotent,
    and is the ONLY thing `road_status` may join through.
    """

    identity: EdgeIdentity
    road_segment_id: int = 0          # filled when persisted; 0 means "not yet assigned"
    notes: tuple[str, ...] = ()

    @property
    def edge_id(self) -> int:
        return self.identity.encode()


def build_mappings(
    segments: Iterable[SourceSegment],
    road_segment_id_for: "callable[[EdgeIdentity], int | None]",
) -> tuple[list[EdgeMapping], tuple[str, ...]]:
    """Produce mapping records, and notes about anything left unmapped.

    `road_segment_id_for` resolves an identity to the persisted `road_segments.id`. Returning
    None leaves the edge **unmapped** — deliberately, rather than inventing a row. An unmapped
    edge keeps `unknown` status, which is the honest consequence.
    """
    mappings: list[EdgeMapping] = []
    unmapped = 0
    for seg in segments:
        rid = road_segment_id_for(seg.identity)
        if rid is None:
            unmapped += 1
            mappings.append(
                EdgeMapping(
                    identity=seg.identity,
                    road_segment_id=0,
                    notes=("no persisted road_segments row for this identity",),
                )
            )
            continue
        mappings.append(EdgeMapping(identity=seg.identity, road_segment_id=rid))

    notes: list[str] = []
    if unmapped:
        notes.append(
            f"{unmapped} graph edge(s) have no persisted road_segments row; they stay "
            f"unmapped and therefore unknown, rather than being assigned by guesswork"
        )
    return mappings, tuple(notes)


def mapping_stats(mappings: Sequence[EdgeMapping]) -> dict[str, int]:
    """Counts for the evidence report. Never rounds a zero match away."""
    total = len(mappings)
    mapped = sum(1 for m in mappings if m.road_segment_id > 0)
    return {
        "graph_edges": total,
        "mapped": mapped,
        "unmapped": total - mapped,
    }
