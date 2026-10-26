"""Guaradar route search — two-phase, coverage-aware, honestly labelled.

Approved specification: docs/STAGE-3-ARCHITECTURE.md §9 (steps 1–7), §9.1 (eligibility),
§9.3 (the two-phase guarantee); Stage 4 §4.1–4.2 (D29). Decisions: D14 (no caching),
D16 (closed edges REMOVED, never penalised), D24/D25 (serve low coverage, never recommend),
D29 (elevation as the last tie-break only), D12 (terrain never ranks streets).

THE ONE PROPERTY THIS MODULE EXISTS TO PROVIDE
  A route that crosses a known closure must never be served as `Clear`. This is guaranteed
  STRUCTURALLY: phase 1 searches a graph from which closed edges are absent, so a closed
  edge is unrepresentable in its output. A finite penalty cannot provide this guarantee —
  research/routing_invariant.py refuted that approach on 1,201 graphs.

  Phase 2 runs ONLY when phase 1 finds nothing, restores the closed edges, and every route
  it returns is classified `hazard_crossing`. A phase-2 route can never displace a phase-1
  route because alternatives are generated within a phase and phases are ordered.

WHAT THIS MODULE DOES NOT DO
  * It does not claim any route is safe. Success means "a path exists in the data".
  * It does not model traffic, water behaviour, or turn restrictions.
  * It never caches. Each call reads status fresh (D14).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Literal, Sequence

from app.routing.graph import (
    COST_FACTOR_CLOSED_PHASE2,
    DEFAULT_SPEED_MPS,
    STATUS_AFFECTED,
    STATUS_CLOSED,
    STATUS_UNKNOWN,
    Edge,
    RoadGraph,
    StatusIndex,
)

# ---------------------------------------------------------------------------
# §9 route-search constants
# ---------------------------------------------------------------------------

# §9 step 1: routing from a guessed origin is worse than no route.
MAX_SNAP_DISTANCE_M = 60.0

# §9 step 4: up to 3 alternatives.
MAX_ALTERNATIVES = 3

# §9.1 coverage bands, inclusive at the bottom.
BAND_HIGH_MIN = 80.0
BAND_MODERATE_MIN = 60.0
BAND_LOW_MIN = 0.01        # 0.0 is its own band

# §9 step 4: edge-penalty iteration factor for k-alternatives.
ALT_PENALTY = 3.0

BAND = Literal["high", "moderate", "low", "none"]
HazardClass = Literal["clear", "hazard_crossing"]
Classification = Literal["eligible", "marginal", "hazard_crossing", "refused"]

# Banned vocabulary (§9.2 / ROUTE-4). Route copy must be checked against this.
BANNED_ROUTE_WORDS = ("safe", "clear", "secure", "flood-free")

# The only permitted characterisation of a route.
NO_KNOWN_HAZARDS = "no known hazards"


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RouteLeg:
    edge_id: int
    from_node: int
    to_node: int
    length_m: float
    status: str
    verified: bool
    elevation_m: float | None


@dataclass(frozen=True)
class Route:
    """One candidate route. Every field needed to explain it honestly."""

    legs: tuple[RouteLeg, ...]
    distance_m: float
    duration_s: float
    phase: int                     # 1 or 2
    hazard_class: HazardClass
    coverage_pct: float            # length-weighted, verified-only (§9.1)
    band: BAND
    classification: Classification
    recommended: bool
    # Elevation, disclosed as approximate and used only as a tie-break (D29).
    mean_elevation_m: float | None
    elevation_used_as_tiebreak: bool
    hazards_avoided: tuple[str, ...]
    notes: tuple[str, ...]

    @property
    def label(self) -> str:
        """The honest one-line characterisation. Never says 'safe'.

        Uses the permitted phrase "no known hazards" verbatim (§9.2): a route is described
        by what was avoided and what is unknown, never by an assertion of safety.
        """
        if self.hazard_class == "hazard_crossing":
            return (
                "No route avoids all closures. This route crosses a closed road."
            )
        if self.band == "none":
            return "Road conditions along this route are unknown."
        if self.band == "low":
            return (
                f"High uncertainty — only {self.coverage_pct:.0f} % verified. "
                f"{self.coverage_pct:.0f} % of this route has {NO_KNOWN_HAZARDS}."
            )
        return f"No known hazards on the verified portion · coverage {self.coverage_pct:.0f} %"


@dataclass(frozen=True)
class RouteResponse:
    """The complete answer, including refusals and the uncertainty flags (§9.1)."""

    routes: tuple[Route, ...]
    refused: bool
    refusal_reason: str | None
    all_routes_hazard_crossing: bool
    best_available_is_uncertain: bool
    snap_from_m: float | None
    snap_to_m: float | None
    synthetic: bool
    notes: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Internal search
# ---------------------------------------------------------------------------


def _edge_cost(edge: Edge, status: StatusIndex, allow_closed: bool) -> float:
    """§9 step 2.

    In phase 1 (`allow_closed=False`) a closed edge can never be costed — StatusIndex
    raises, which is the guard that makes the structural guarantee explicit. In phase 2
    (`allow_closed=True`) closures are restored deliberately and priced very high, and
    every resulting route is classified hazard-crossing.
    """
    if allow_closed and status.is_closed(edge.id):
        return edge.length_m * COST_FACTOR_CLOSED_PHASE2
    return edge.length_m * status.cost_factor(edge.id)


def _dijkstra(
    graph: RoadGraph,
    src: int,
    dst: int,
    status: StatusIndex,
    exclude_closed: bool,
    penalised_edges: dict[int, float] | None = None,
) -> list[tuple[int, Edge]] | None:
    """Shortest path by (length x cost factor). Returns [(node, edge), …] or None.

    `exclude_closed`:

      True  — phase 1. Closed edges are ABSENT from the search. This is what makes the
              guarantee structural rather than arithmetic.
      False — phase 2. Closed edges are included and costed; the caller must classify the
              result as hazard-crossing.
    """
    if src == dst:
        return []

    # The closed-ness test is applied to the EDGE, not to a cost multiplier, so no
    # floating-point comparison can accidentally readmit a closure.
    def allowed(edge_id: int) -> bool:
        if exclude_closed and status.is_closed(edge_id):
            return False
        return True

    dist: dict[int, float] = {src: 0.0}
    prev: dict[int, tuple[int, Edge]] = {}
    pq: list[tuple[float, int]] = [(0.0, src)]
    settled: set[int] = set()

    while pq:
        d, u = heapq.heappop(pq)
        if u in settled:
            continue
        settled.add(u)
        if u == dst:
            break
        for v, edge in graph.neighbours(u):
            if not allowed(edge.id):
                continue
            w = _edge_cost(edge, status, allow_closed=not exclude_closed)
            if penalised_edges and edge.id in penalised_edges:
                w *= penalised_edges[edge.id]
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = (u, edge)
                heapq.heappush(pq, (nd, v))

    if dst not in settled and dst not in dist:
        return None

    path: list[tuple[int, Edge]] = []
    cur = dst
    while cur != src:
        if cur not in prev:
            return None
        u, edge = prev[cur]
        path.append((u, edge))
        cur = u
    path.reverse()
    return path


def _band_for(coverage_pct: float) -> BAND:
    """§9.1 bands, inclusive at the bottom, applied to the rounded value."""
    if coverage_pct >= BAND_HIGH_MIN:
        return "high"
    if coverage_pct >= BAND_MODERATE_MIN:
        return "moderate"
    if coverage_pct >= BAND_LOW_MIN:
        return "low"
    return "none"


def _build_route(
    graph: RoadGraph,
    path: Sequence[tuple[int, Edge]],
    status: StatusIndex,
    phase: int,
) -> Route:
    """Assemble a Route, computing coverage length-weighted (§9 step 5)."""
    total_len = 0.0
    verified_len = 0.0
    legs: list[RouteLeg] = []
    avoided_closures = 0
    avoided_affected = 0
    crossed_closed = False
    elevations: list[float] = []

    for u, edge in path:
        v = edge.other(u)
        st = status.status_of(edge.id)
        ver = status.is_verified(edge.id)
        legs.append(
            RouteLeg(
                edge_id=edge.id,
                from_node=u,
                to_node=v,
                length_m=edge.length_m,
                status=st,
                verified=ver,
                elevation_m=edge.elevation_m,
            )
        )
        total_len += edge.length_m
        if ver:
            verified_len += edge.length_m
        if st == STATUS_CLOSED:
            crossed_closed = True
        if st == STATUS_AFFECTED:
            avoided_affected += 1
        if edge.elevation_m is not None:
            elevations.append(edge.elevation_m)

    coverage_pct = round(100.0 * verified_len / total_len, 2) if total_len > 0 else 0.0
    band = _band_for(coverage_pct)
    hazard_class: HazardClass = "hazard_crossing" if crossed_closed else "clear"

    # Classification. A phase-2 route is ALWAYS hazard-crossing by definition (§9.3);
    # asserting both keeps the invariant visible if it is ever violated.
    if phase == 2 or hazard_class == "hazard_crossing":
        classification: Classification = "hazard_crossing"
    elif band in ("high", "moderate"):
        classification = "eligible"
    else:
        classification = "marginal"

    duration_s = round(total_len / DEFAULT_SPEED_MPS, 1)
    mean_elev = round(sum(elevations) / len(elevations), 1) if elevations else None

    notes: list[str] = []
    if graph.synthetic:
        notes.append(
            "synthetic road network — not a surveyed OSM extract; coverage percentages "
            "describe this demo dataset only"
        )
    if band in ("low", "none"):
        notes.append(
            "served but not recommended: most of this route has no verified status"
        )
    if avoided_affected:
        notes.append(f"crosses {avoided_affected} road(s) reported as affected")

    return Route(
        legs=tuple(legs),
        distance_m=round(total_len, 1),
        duration_s=duration_s,
        phase=phase,
        hazard_class=hazard_class,
        coverage_pct=coverage_pct,
        band=band,
        classification=classification,
        recommended=False,           # assigned during ranking, never by construction
        mean_elevation_m=mean_elev,
        elevation_used_as_tiebreak=False,
        hazards_avoided=tuple(
            [f"{avoided_affected} affected"] if avoided_affected else []
        ),
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# Ranking (§9.1 ordering + D29 elevation tie-break)
# ---------------------------------------------------------------------------

_CLASS_RANK = {"clear": 0, "hazard_crossing": 1}
_BAND_RANK = {"high": 0, "moderate": 1, "low": 2, "none": 3}


def _sort_key(route: Route, prefer_lower_elevation: bool):
    """`(hazard_class, coverage_band, duration, ±elevation)` — D29.

    Elevation is the LAST term and can only separate routes already equal on the first
    three. Because class and band precede duration and elevation, no elevation value can
    move a route across a class or band boundary. That is the structural enforcement of
    D29 limits 2 and 3.
    """
    elev = route.mean_elevation_m
    if elev is None:
        elev_term = 0.0
    else:
        elev_term = elev if prefer_lower_elevation else -elev
    return (
        _CLASS_RANK[route.hazard_class],
        _BAND_RANK[route.band],
        route.duration_s,
        elev_term,
    )


def _rank(routes: Sequence[Route], prefer_lower_elevation: bool = True) -> list[Route]:
    """Order routes and mark exactly one as recommended.

    D29: elevation is applied only inside a group that is already identical on
    (class, band, duration). This is done in two passes so the tie-break can be *detected*
    and disclosed, rather than silently influencing order.
    """
    ordered = sorted(routes, key=lambda r: _sort_key(r, prefer_lower_elevation))

    # Detect whether elevation actually decided anything, so the UI can disclose it.
    tiebroken: set[int] = set()
    for i in range(len(ordered) - 1):
        a, b = ordered[i], ordered[i + 1]
        same_first_three = (
            _CLASS_RANK[a.hazard_class] == _CLASS_RANK[b.hazard_class]
            and _BAND_RANK[a.band] == _BAND_RANK[b.band]
            and a.duration_s == b.duration_s
        )
        if same_first_three and a.mean_elevation_m != b.mean_elevation_m:
            tiebroken.add(i)

    out: list[Route] = []
    recommended_set = False
    for idx, r in enumerate(ordered):
        recommended = False
        # "Recommended" = rank 1 with normal weight, and only for a clear route in a
        # high/moderate band (§9.1). Nothing else may be recommended.
        if (
            not recommended_set
            and r.hazard_class == "clear"
            and r.band in ("high", "moderate")
        ):
            recommended = True
            recommended_set = True
        out.append(
            Route(
                **{
                    **r.__dict__,
                    "recommended": recommended,
                    "elevation_used_as_tiebreak": idx in tiebroken or (idx - 1) in tiebroken,
                }
            )
        )
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def find_routes(
    graph: RoadGraph,
    status: StatusIndex,
    origin: tuple[float, float],
    destination: tuple[float, float],
    *,
    max_alternatives: int = MAX_ALTERNATIVES,
    prefer_lower_elevation: bool = True,
) -> RouteResponse:
    """Find up to `max_alternatives` routes, two-phase, honestly classified.

    `prefer_lower_elevation` controls the DIRECTION of the D29 tie-break only. It cannot
    change which route is recommended when class or band differ.
    """
    if max_alternatives < 1:
        raise ValueError("max_alternatives must be >= 1")

    notes: list[str] = []

    # ---- step 1: snap, and refuse rather than guess --------------------------
    src, src_d = graph.nearest_node(*origin)
    dst, dst_d = graph.nearest_node(*destination)

    if src is None or dst is None:
        return RouteResponse(
            routes=(),
            refused=True,
            refusal_reason="Cannot calculate a route: the road graph is empty.",
            all_routes_hazard_crossing=False,
            best_available_is_uncertain=False,
            snap_from_m=src_d if src is not None else None,
            snap_to_m=dst_d if dst is not None else None,
            synthetic=graph.synthetic,
            notes=("no graph nodes available",),
        )

    if src_d > MAX_SNAP_DISTANCE_M:
        return RouteResponse(
            routes=(),
            refused=True,
            refusal_reason=(
                f"Cannot calculate a route: your starting point is {src_d:.0f} m from the "
                f"nearest road (limit {MAX_SNAP_DISTANCE_M:.0f} m)."
            ),
            all_routes_hazard_crossing=False,
            best_available_is_uncertain=False,
            snap_from_m=src_d,
            snap_to_m=dst_d,
            synthetic=graph.synthetic,
            notes=notes,
        )
    if dst_d > MAX_SNAP_DISTANCE_M:
        return RouteResponse(
            routes=(),
            refused=True,
            refusal_reason=(
                f"Cannot calculate a route: the destination is {dst_d:.0f} m from the "
                f"nearest road (limit {MAX_SNAP_DISTANCE_M:.0f} m)."
            ),
            all_routes_hazard_crossing=False,
            best_available_is_uncertain=False,
            snap_from_m=src_d,
            snap_to_m=dst_d,
            synthetic=graph.synthetic,
            notes=notes,
        )

    # ---- phase 1: closed edges ABSENT ---------------------------------------
    phase1: list[Route] = []
    penalised: dict[int, float] = {}
    for _ in range(max_alternatives):
        path = _dijkstra(graph, src, dst, status, exclude_closed=True,
                         penalised_edges=penalised or None)
        if path is None:
            break
        route = _build_route(graph, path, status, phase=1)
        # Defence in depth: phase 1 cannot contain a closure, so assert it.
        if route.hazard_class != "clear":  # pragma: no cover - structural invariant
            raise AssertionError(
                "phase 1 returned a hazard-crossing route; the closed-edge filter failed"
            )
        phase1.append(route)
        for leg in route.legs:
            penalised[leg.edge_id] = penalised.get(leg.edge_id, 1.0) * ALT_PENALTY

    if phase1:
        ranked = _rank(phase1, prefer_lower_elevation)[:max_alternatives]
        best_uncertain = all(r.band in ("low", "none") for r in ranked)
        if best_uncertain:
            notes.append(
                "every available route has low or no verified coverage; none is recommended"
            )
        # Provenance note about the dataset itself, so every positive response carries it.
        if graph.synthetic:
            notes.append(
                "synthetic road network — not a surveyed OSM extract; coverage percentages "
                "describe this demo dataset only"
            )
        return RouteResponse(
            routes=tuple(ranked),
            refused=False,
            refusal_reason=None,
            all_routes_hazard_crossing=False,
            best_available_is_uncertain=best_uncertain,
            snap_from_m=round(src_d, 1),
            snap_to_m=round(dst_d, 1),
            synthetic=graph.synthetic,
            notes=tuple(notes),
        )

    # ---- phase 2: only now restore closures, and label the result -----------
    notes.append(
        "no route avoids every known closure; showing the least-exposed option and "
        "labelling it explicitly"
    )
    phase2: list[Route] = []
    penalised = {}
    for _ in range(max_alternatives):
        path = _dijkstra(graph, src, dst, status, exclude_closed=False,
                         penalised_edges=penalised or None)
        if path is None:
            break
        route = _build_route(graph, path, status, phase=2)
        phase2.append(route)
        for leg in route.legs:
            penalised[leg.edge_id] = penalised.get(leg.edge_id, 1.0) * ALT_PENALTY

    if not phase2:
        return RouteResponse(
            routes=(),
            refused=True,
            refusal_reason=(
                "Cannot calculate a route: no path connects those points in the road data."
            ),
            all_routes_hazard_crossing=False,
            best_available_is_uncertain=False,
            snap_from_m=round(src_d, 1),
            snap_to_m=round(dst_d, 1),
            synthetic=graph.synthetic,
            notes=tuple(notes),
        )

    ranked = _rank(phase2, prefer_lower_elevation)[:max_alternatives]
    if graph.synthetic:
        notes.append(
            "synthetic road network — not a surveyed OSM extract; coverage percentages "
            "describe this demo dataset only"
        )
    return RouteResponse(
        routes=tuple(ranked),
        refused=False,
        refusal_reason=None,
        all_routes_hazard_crossing=all(r.hazard_class == "hazard_crossing" for r in ranked),
        best_available_is_uncertain=False,
        snap_from_m=round(src_d, 1),
        snap_to_m=round(dst_d, 1),
        synthetic=graph.synthetic,
        notes=tuple(notes),
    )
