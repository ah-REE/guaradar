"""Guaradar road graph — immutable topology, status applied at query time.

Approved specification: docs/STAGE-3-ARCHITECTURE.md §9 (graph construction, route search),
§9.1 (eligibility policy), §9.3 (two-phase guarantee); decisions D14 (no route caching),
D16 (closed edges removed, not penalised), D29 (elevation as last tie-break only).

TWO INVARIANTS THIS MODULE ENFORCES STRUCTURALLY
  1. The graph holds TOPOLOGY AND STATIC ATTRIBUTES ONLY. It never stores road status.
     Status is passed in per query and applied at search time. That is what makes
     "a newly closed road keeps being recommended" impossible rather than unlikely (D14).
  2. Edges are immutable and shared, so a caller cannot mutate the graph by accident and
     silently affect a later request.

SYNTHETIC DATA WARNING
  The demo graph is generated from sector centres (see supabase/seed.sql). It is NOT an OSM
  extract, its geometry is not surveyed, and it does not represent Guayaquil's real street
  network. Every generated node/edge carries `synthetic=True`. Real extraction is a
  separate step and, as of this milestone, has not been run.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Literal, Mapping

# ---------------------------------------------------------------------------
# Status model. These names match supabase/migrations/0001_init.sql road_status.status.
# ---------------------------------------------------------------------------

STATUS_OPEN = "open"
STATUS_AFFECTED = "affected"
STATUS_CLOSED = "closed"
STATUS_UNKNOWN = "unknown"

# §9 step 2 cost factors. `closed` is deliberately absent: it is removed, not weighted.
COST_FACTOR_AFFECTED = 2.5
COST_FACTOR_UNKNOWN = 1.15
COST_FACTOR_STALE = 1.1
COST_FACTOR_OPEN = 1.0

# Phase 2 only (§9.3). When phase 1 finds nothing, closures are restored so the app can
# answer "the only way out is flooded" instead of "no route exists". This multiplier is
# NEVER used in phase 1 — its existence is not a licence to penalise closures into the
# phase-1 graph. Any route it contributes to is classified hazard_crossing by construction.
COST_FACTOR_CLOSED_PHASE2 = 50.0

# Default assumed speed, used only to express duration. Labelled "estimated" everywhere.
DEFAULT_SPEED_MPS = 11.0        # ~40 km/h

# Freshness windows (§9.1 "verified and inside its freshness window").
DEFAULT_FRESHNESS = timedelta(minutes=30)

EARTH_RADIUS_M = 6_371_000.0

# Legal travel directions for a road segment.
#   'both'     — traversable in either direction (no oneway tag, or oneway=no)
#   'forward'  — only a -> b
#   'backward' — only b -> a  (OSM oneway=-1 / reverse)
Direction = Literal["both", "forward", "backward"]
VALID_DIRECTIONS: tuple[Direction, ...] = ("both", "forward", "backward")


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in metres between (lat, lon) pairs."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


# ---------------------------------------------------------------------------
# Static topology
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    """A graph node. `synthetic` propagates the honesty label into every response."""

    id: int
    lat: float
    lon: float
    synthetic: bool = True

    @property
    def coord(self) -> tuple[float, float]:
        return (self.lat, self.lon)


@dataclass(frozen=True)
class Edge:
    """An undirected road segment between two nodes, with a legal travel direction.

    The physical segment is one object with one stable id. `direction` constrains
    **traversal only** — it does not create a second edge. That keeps the identity mapping
    1:1 (one source segment = one `edge_id`) while making illegal travel unreachable.

    `elevation_m` is approximate static context only (D12/D29). It may break an exact tie
    and nothing else; see routing/search.py for how that is enforced.
    """

    id: int
    a: int
    b: int
    length_m: float
    road_class: str = "residential"
    name: str | None = None
    elevation_m: float | None = None
    synthetic: bool = True
    # Legal travel direction. 'forward' means only a->b; 'backward' only b->a.
    # 'both' is the default because a MISSING oneway tag is not evidence of a restriction.
    direction: Direction = "both"

    def __post_init__(self) -> None:
        if self.direction not in VALID_DIRECTIONS:
            raise ValueError(
                f"edge {self.id}: unknown direction {self.direction!r}; "
                f"expected one of {VALID_DIRECTIONS}"
            )

    def other(self, node_id: int) -> int:
        """The far endpoint. Geometry only — says nothing about legality."""
        if node_id == self.a:
            return self.b
        if node_id == self.b:
            return self.a
        raise ValueError(f"edge {self.id} does not touch node {node_id}")

    def can_travel(self, from_node: int, to_node: int) -> bool:
        """Whether travelling from_node -> to_node is legal on this segment."""
        if {from_node, to_node} != {self.a, self.b}:
            raise ValueError(f"edge {self.id} does not connect {from_node} and {to_node}")
        if self.direction == "both":
            return True
        if self.direction == "forward":
            return from_node == self.a and to_node == self.b
        # 'backward'
        return from_node == self.b and to_node == self.a

    def directed_target(self, from_node: int) -> int | None:
        """The reachable endpoint from `from_node`, or None if travel is illegal."""
        if from_node not in (self.a, self.b):
            raise ValueError(f"edge {self.id} does not touch node {from_node}")
        far = self.other(from_node)
        return far if self.can_travel(from_node, far) else None

    def mean_elevation(self) -> float | None:
        return self.elevation_m


@dataclass(frozen=True)
class RoadGraph:
    """Immutable graph. `adjacency` maps node id -> tuple of edge ids."""

    nodes: Mapping[int, Node]
    edges: Mapping[int, Edge]
    # OUTGOING adjacency: node id -> sorted tuple of edge ids that may be LEFT from it.
    # A one-way segment therefore appears at only one of its endpoints. This is what makes
    # illegal travel structurally unreachable rather than merely discouraged.
    adjacency: Mapping[int, tuple[int, ...]]
    synthetic: bool = True
    osm_timestamp: datetime | None = None

    # -- construction -----------------------------------------------------

    @classmethod
    def from_edges(cls, node_coords: Mapping[int, tuple[float, float]],
                   edges: Iterable[Edge],
                   synthetic: bool = True,
                   osm_timestamp: datetime | None = None) -> "RoadGraph":
        nodes = {nid: Node(nid, lat, lon, synthetic) for nid, (lat, lon) in node_coords.items()}
        edge_map: dict[int, Edge] = {}
        adj: dict[int, list[int]] = {nid: [] for nid in nodes}
        for e in edges:
            if e.a not in nodes or e.b not in nodes:
                raise ValueError(f"edge {e.id} references an unknown node")
            if e.length_m <= 0:
                raise ValueError(f"edge {e.id} has non-positive length")
            if e.id in edge_map:
                raise ValueError(f"duplicate edge id {e.id}")
            edge_map[e.id] = e
            # Register only the endpoints from which this edge may legally be entered.
            if e.direction in ("both", "forward"):
                adj[e.a].append(e.id)
            if e.direction in ("both", "backward"):
                adj[e.b].append(e.id)
        return cls(
            nodes=nodes,
            edges=edge_map,
            adjacency={k: tuple(sorted(v)) for k, v in adj.items()},
            synthetic=synthetic,
            osm_timestamp=osm_timestamp,
        )

    # -- queries ----------------------------------------------------------

    def neighbours(self, node_id: int) -> Iterable[tuple[int, Edge]]:
        """Yield (other_node, edge) for each LEGALLY reachable departure from `node_id`.

        A one-way edge is absent when approached from its forbidden end, so a shortest-path
        search cannot travel against it even if it tried.
        """
        for eid in self.adjacency.get(node_id, ()):
            e = self.edges[eid]
            target = e.directed_target(node_id)
            if target is not None:
                yield target, e

    def is_oneway(self, edge_id: int) -> bool:
        e = self.edges[edge_id]
        return e.direction != "both"

    def oneway_stats(self) -> dict[str, int]:
        """Counts by direction, for the evidence report."""
        out = {"both": 0, "forward": 0, "backward": 0}
        for e in self.edges.values():
            out[e.direction] += 1
        out["oneway_total"] = out["forward"] + out["backward"]
        return out

    def nearest_node(self, lat: float, lon: float) -> tuple[int | None, float]:
        """Return (node_id, distance_m) of the closest node. O(n) — fine at 22k nodes."""
        best_id: int | None = None
        best_d = float("inf")
        for nid, node in self.nodes.items():
            d = haversine_m((lat, lon), node.coord)
            if d < best_d:
                best_d = d
                best_id = nid
        return best_id, best_d

    def stats(self) -> dict[str, float | int | bool]:
        """Descriptive statistics, for evidence documents and the admin screen."""
        total_len = sum(e.length_m for e in self.edges.values())
        degs = [len(v) for v in self.adjacency.values()]
        junctions = sum(1 for d in degs if d >= 3)
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "total_length_m": round(total_len, 1),
            "junctions": junctions,
            "junctions_pct": round(100.0 * junctions / len(degs), 1) if degs else 0.0,
            "mean_degree": round(sum(degs) / len(degs), 2) if degs else 0.0,
            "components": self.component_count(),
            "largest_component_pct": round(self.largest_component_pct(), 1),
            "synthetic": self.synthetic,
        }

    def component_count(self) -> int:
        seen: set[int] = set()
        count = 0
        for nid in self.nodes:
            if nid in seen:
                continue
            count += 1
            stack = [nid]
            seen.add(nid)
            while stack:
                u = stack.pop()
                for v, _ in self.neighbours(u):
                    if v not in seen:
                        seen.add(v)
                        stack.append(v)
        return count

    def largest_component_pct(self) -> float:
        seen: set[int] = set()
        best = 0
        for nid in self.nodes:
            if nid in seen:
                continue
            size = 0
            stack = [nid]
            seen.add(nid)
            while stack:
                u = stack.pop()
                size += 1
                for v, _ in self.neighbours(u):
                    if v not in seen:
                        seen.add(v)
                        stack.append(v)
            best = max(best, size)
        return 100.0 * best / len(self.nodes) if self.nodes else 0.0


# ---------------------------------------------------------------------------
# Status: supplied per query, never stored in the graph (D14)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EdgeStatus:
    """The current state of one segment, as of `set_at`.

    `verified` is False when the claim is stale, i.e. past its freshness window. Staleness
    removes the *verification*, never the closure — see the note in routing/search.py.
    """

    edge_id: int
    status: str
    set_at: datetime
    verified: bool = True

    def __post_init__(self) -> None:
        if self.status not in (STATUS_OPEN, STATUS_AFFECTED, STATUS_CLOSED, STATUS_UNKNOWN):
            raise ValueError(f"unknown status {self.status!r} for edge {self.edge_id}")


class StatusIndex:
    """Lookup of edge status with explicit staleness handling.

    Deliberately a plain object rather than a dict so the staleness rule lives in one
    place and is testable.
    """

    def __init__(
        self,
        statuses: Iterable[EdgeStatus] = (),
        now: datetime | None = None,
        freshness: timedelta = DEFAULT_FRESHNESS,
    ) -> None:
        if now is None:
            raise ValueError("StatusIndex requires an explicit `now`; it must never read a clock")
        self._now = now
        self._freshness = freshness
        self._by_edge: dict[int, EdgeStatus] = {}
        for s in statuses:
            if s.edge_id in self._by_edge:
                raise ValueError(f"duplicate status for edge {s.edge_id}")
            self._by_edge[s.edge_id] = s

    def is_fresh(self, s: EdgeStatus) -> bool:
        """Whether this claim still counts as current verification.

        Two independent conditions, both required:

          1. the record has not been declared unverified by its source (`verified` flag), and
          2. its age is inside this index's freshness window.

        The flag exists because a caller may know something the timestamp cannot express:
        `road_status.review_at` is a per-record re-check deadline, so a row can be old by clock
        yet still current, or recent yet explicitly expired. The status repository sets
        `verified=False` in the latter case rather than back-dating `set_at`, which would
        falsify a stored timestamp to influence a downstream calculation.

        Staleness never affects `is_closed` (O-8): an expired closure still excludes the edge.
        """
        if getattr(s, "verified", True) is False:
            return False
        return (self._now - s.set_at) <= self._freshness

    def status_of(self, edge_id: int) -> str:
        """Effective status. Absent status means UNKNOWN, never OPEN.

        A road with no record is not a road known to be clear — that conflation is the
        single most dangerous simplification available here.
        """
        s = self._by_edge.get(edge_id)
        return s.status if s is not None else STATUS_UNKNOWN

    def is_verified(self, edge_id: int) -> bool:
        """True only for a non-stale OPEN or AFFECTED record.

        CLOSED and UNKNOWN are never counted as verified coverage: a closure tells you a
        road is impassable, which does not verify that travelling it is fine.
        """
        s = self._by_edge.get(edge_id)
        if s is None or not self.is_fresh(s):
            return False
        return s.status in (STATUS_OPEN, STATUS_AFFECTED)

    def is_closed(self, edge_id: int) -> bool:
        """Whether phase 1 must exclude this edge.

        IMPORTANT — the conservative reading, documented in docs/M3-EVIDENCE.md §5:
        a closure excludes the edge REGARDLESS of freshness. A 3-hour-old closure that was
        never re-checked must not become traversable merely by ageing; lifting a closure is
        the higher-risk direction. Staleness lowers coverage instead.
        """
        return self.status_of(edge_id) == STATUS_CLOSED

    def edges_with_records(self) -> tuple[int, ...]:
        """Every edge id that has an explicit record.

        Exists so a caller can build a superset index (for example, one that merges citizen
        reports over seeded status) WITHOUT reaching into `_by_edge`. Reading a private
        attribute from another module works until the representation changes, and then fails
        silently in whichever caller nobody re-ran.
        """
        return tuple(self._by_edge.keys())

    def record_for(self, edge_id: int) -> EdgeStatus | None:
        """The raw record for one edge, or None. Same rationale as `edges_with_records`."""
        return self._by_edge.get(edge_id)

    def freshness_window(self) -> timedelta:
        """The freshness budget this index was built with.

        Exposed so a caller constructing a merged index can preserve the original policy
        instead of assuming `DEFAULT_FRESHNESS` — which would silently widen or narrow
        staleness whenever the caller's window differed from the default.
        """
        return self._freshness

    def cost_factor(self, edge_id: int) -> float:
        """§9 step 2. Closed is never costed here — it is excluded before costing."""
        s = self._by_edge.get(edge_id)
        if s is None:
            return COST_FACTOR_UNKNOWN
        if s.status == STATUS_CLOSED:
            # Should be unreachable: phase 1 filters these out. If it is reached, refusing
            # loudly is better than silently applying a multiplier.
            raise ValueError(
                f"edge {edge_id} is closed and must be filtered out, not costed"
            )
        if not self.is_fresh(s):
            return COST_FACTOR_STALE
        if s.status == STATUS_AFFECTED:
            return COST_FACTOR_AFFECTED
        if s.status == STATUS_UNKNOWN:
            return COST_FACTOR_UNKNOWN
        return COST_FACTOR_OPEN


# ---------------------------------------------------------------------------
# Synthetic demo graph
# ---------------------------------------------------------------------------


def build_synthetic_grid(
    sector_centres: Mapping[str, tuple[float, float]],
    *,
    cells_per_side: int = 7,
    spacing_m: float = 120.0,
    elevation_base: float = 6.0,
    extra_places: Mapping[str, tuple[float, float]] | None = None,
) -> RoadGraph:
    """Build a connected grid per sector, joined by a spine between sector centres.

    This exists because no OSM extract is available offline. It is deliberately labelled
    synthetic everywhere. The topology is a grid, which is a fair approximation of a
    Latin-American city block layout — but it is not Guayaquil.

    `cells_per_side=7` gives 49 nodes and 84 edges per sector before the spine: about 40 km
    of network at 120 m spacing.

    `extra_places` adds named points (sensor sites, shelters) as REAL NODES connected to the
    nearest grid corner. Without this, a synthetic 40 km grid covering a 9 km city leaves
    sensor sites hundreds of metres from any node, and `find_routes` correctly REFUSES to
    route (snap > 60 m). Adding the places is the honest fix: it makes the demo routable
    without widening the 60 m refusal rule, which exists because routing from a guessed
    origin is worse than no route.
    """
    if cells_per_side < 2:
        raise ValueError("cells_per_side must be >= 2")

    node_coords: dict[int, tuple[float, float]] = {}
    edges: list[Edge] = []
    edge_id = 0
    base_node = 0

    # metres per degree at this latitude
    lat_deg_m = 111_320.0
    lon_deg_m = 111_320.0 * math.cos(math.radians(-2.17))

    sector_rep: dict[str, int] = {}

    for s_idx, (sector_id, (clat, clon)) in enumerate(sector_centres.items()):
        dlat = spacing_m / lat_deg_m
        dlon = spacing_m / lon_deg_m
        origin_lat = clat - (cells_per_side - 1) * dlat / 2
        origin_lon = clon - (cells_per_side - 1) * dlon / 2

        def nid(r: int, c: int) -> int:
            return base_node + r * cells_per_side + c

        for r in range(cells_per_side):
            for c in range(cells_per_side):
                node_coords[nid(r, c)] = (
                    round(origin_lat + r * dlat, 6),
                    round(origin_lon + c * dlon, 6),
                )

        for r in range(cells_per_side):
            for c in range(cells_per_side):
                if c + 1 < cells_per_side:
                    edges.append(
                        Edge(
                            id=edge_id,
                            a=nid(r, c),
                            b=nid(r, c + 1),
                            length_m=round(spacing_m, 1),
                            road_class="residential" if (r + c) % 3 else "secondary",
                            name=f"synthetic-{sector_id}-{r}-{c}-E",
                            # Rounded to 1 m: approximate static context (D12).
                            elevation_m=round(elevation_base + ((r * 7 + c * 3) % 10) * 0.9, 0),
                            synthetic=True,
                        )
                    )
                    edge_id += 1
                if r + 1 < cells_per_side:
                    edges.append(
                        Edge(
                            id=edge_id,
                            a=nid(r, c),
                            b=nid(r + 1, c),
                            length_m=round(spacing_m, 1),
                            road_class="residential" if (r + c) % 4 else "primary",
                            name=f"synthetic-{sector_id}-{r}-{c}-S",
                            elevation_m=round(elevation_base + ((r * 5 + c * 11) % 10) * 0.8, 0),
                            synthetic=True,
                        )
                    )
                    edge_id += 1

        sector_rep[sector_id] = nid(cells_per_side // 2, cells_per_side // 2)
        base_node += cells_per_side * cells_per_side

    # Extra named places: add each as its own node, wired to the nearest existing grid
    # corner with a short synthetic connector. This keeps sensor/shelter coordinates
    # routable at their true positions instead of snapping them hundreds of metres away.
    if extra_places:
        for _name, (plat, plon) in extra_places.items():
            new_id = base_node
            base_node += 1
            # Find the closest existing node WITHOUT using RoadGraph (not built yet).
            best_id = -1
            best_d = float("inf")
            for nid_existing, (nlat, nlon) in node_coords.items():
                d = haversine_m((plat, plon), (nlat, nlon))
                if d < best_d:
                    best_d = d
                    best_id = nid_existing
            node_coords[new_id] = (round(plat, 6), round(plon, 6))
            if best_id >= 0:
                edges.append(
                    Edge(
                        id=edge_id,
                        a=new_id,
                        b=best_id,
                        length_m=round(max(best_d, 1.0), 1),
                        road_class="residential",
                        name=f"synthetic-connector-{_name}",
                        elevation_m=round(elevation_base, 0),
                        synthetic=True,
                    )
                )
                edge_id += 1

    # Spine: connect sector representatives so the graph is one component. Longer edges,
    # roughly the real separation between these districts.
    reps = list(sector_rep.items())
    for (sid_a, na), (sid_b, nb) in zip(reps, reps[1:]):
        pa, pb = node_coords[na], node_coords[nb]
        edges.append(
            Edge(
                id=edge_id,
                a=na,
                b=nb,
                length_m=round(haversine_m(pa, pb), 1),
                road_class="primary",
                name=f"synthetic-spine-{sid_a}-{sid_b}",
                elevation_m=round(elevation_base, 0),
                synthetic=True,
            )
        )
        edge_id += 1

    return RoadGraph.from_edges(node_coords, edges, synthetic=True)


# ---------------------------------------------------------------------------
# Real OSM extraction (not run in this milestone)
# ---------------------------------------------------------------------------


def build_from_osm_json(payload: Mapping, osm_timestamp: datetime | None = None) -> RoadGraph:
    """Build a graph from an Overpass `out body; >; out skel qt;` JSON payload.

    Written so the synthetic graph can be swapped for a real extract without touching the
    search code. NOT EXERCISED IN M3: no network extraction was performed, so this
    function's behaviour on a real Guayaquil payload is unverified. That limitation is
    recorded in docs/M3-EVIDENCE.md rather than glossed over.
    """
    nodes: dict[int, tuple[float, float]] = {}
    for el in payload.get("elements", []):
        if el.get("type") == "node" and "lat" in el and "lon" in el:
            nodes[el["id"]] = (el["lat"], el["lon"])

    edges: list[Edge] = []
    seen_pairs: set[tuple[int, int]] = set()
    edge_id = 0
    for el in payload.get("elements", []):
        if el.get("type") != "way":
            continue
        tags = el.get("tags", {}) or {}
        nds = el.get("nodes") or []
        for a, b in zip(nds, nds[1:]):
            if a not in nodes or b not in nodes:
                continue
            key = (a, b) if a < b else (b, a)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            edges.append(
                Edge(
                    id=edge_id,
                    a=a,
                    b=b,
                    length_m=round(haversine_m(nodes[a], nodes[b]), 1),
                    road_class=tags.get("highway", "residential"),
                    name=tags.get("name"),
                    elevation_m=None,          # filled later by sample_terrain
                    synthetic=False,
                )
            )
            edge_id += 1

    return RoadGraph.from_edges(nodes, edges, synthetic=False, osm_timestamp=osm_timestamp)
