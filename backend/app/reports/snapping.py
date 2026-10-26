"""Snap a GPS position to the nearest road SEGMENT (not merely the nearest node).

WHY NOT REUSE `RoadGraph.nearest_node`
  The router snaps to nodes because Dijkstra starts and ends at nodes. A road REPORT, though,
  describes a stretch of road: a hazard 12 m from a segment's midpoint is on that segment, even
  though both of its endpoints are 60 m away. Using node snapping here would therefore refuse
  perfectly good reports, or worse, attribute them to the far side of a junction.

WHY A BOUNDING-BOX PRE-FILTER
  `nearest_node` is O(n) over 20,386 nodes and is called once per route request. Reports are
  more frequent, and a naive O(E) scan over 24,943 edges per submission would make the endpoint
  an easy way to burn CPU. The pre-filter narrows candidates by latitude band first, which is
  cheap, then does exact point-to-segment distances only on what survives.

WHY THE THRESHOLD IS THE WHOLE POINT
  The brief is explicit: "Snap a GPS location to the nearest road segment only when it is
  within a configurable distance threshold. If the location is too far from a road or accuracy
  is poor, ask the user to adjust the pin rather than silently assigning the wrong road."

  So a miss is a RESULT, not an error to be papered over. `snap()` returns `None` plus the
  measured distance, and the API turns that into an actionable message. Assigning the nearest
  road regardless would put a report about a flooded garden onto whatever street happened to be
  closest, and that wrong road would then be routed around. Silently wrong is worse than
  visibly unmatched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping

from app.routing.graph import Edge, RoadGraph, haversine_m

# Projected metres per degree. Guayaquil sits near the equator, so the longitude scale is
# within 0.1 % of the latitude scale; using a local cos(lat) factor is still correct practice
# and costs nothing.
M_PER_DEG_LAT = 111_320.0

# Configurable matching threshold. 50 m is chosen to be comparable to the router's existing
# 60 m snap refusal, so a report that matches a road can also be routed to. Making it larger
# than the router's limit would let a report attach to a road the router then refuses as an
# endpoint, which is a confusing pair of answers about the same point.
DEFAULT_SNAP_THRESHOLD_M = 50.0

# GPS accuracy gate. A fix with 500 m accuracy is not evidence of a position, and snapping it
# to a street would launder a bad fix into a confident-looking segment id. This does NOT reject
# the report — the user may correct the pin — it only prevents an automatic match.
DEFAULT_MAX_ACCURACY_M = 100.0


@dataclass(frozen=True)
class SnapResult:
    """Outcome of a snap attempt. `edge_id is None` means no confident match."""

    edge_id: int | None
    distance_m: float
    # The point on the segment, not the submitter's position. This is what may be published.
    snapped_lat: float | None
    snapped_lon: float | None
    reason: str
    # True when the miss was caused by the accuracy gate rather than by distance.
    accuracy_rejected: bool = False

    @property
    def matched(self) -> bool:
        return self.edge_id is not None


def _project(lat: float, lon: float, lat0: float) -> tuple[float, float]:
    """Local equirectangular projection to metres, relative to `lat0`.

    Exact enough at this scale: over a 10 km box the error is millimetres, and segment lengths
    in the artifact are already rounded to 0.1 m.
    """
    x = lon * M_PER_DEG_LAT * math.cos(math.radians(lat0))
    y = lat * M_PER_DEG_LAT
    return x, y


def point_to_segment_m(
    plat: float, plon: float, alat: float, alon: float, blat: float, blon: float
) -> tuple[float, float, float]:
    """Perpendicular distance from a point to a segment, plus the closest point.

    Returns (distance_m, closest_lat, closest_lon). The closest point is clamped to the segment,
    so a point beside an endpoint reports the endpoint rather than an extrapolated position off
    the end of the road — which would put a published pin in a building.
    """
    lat0 = (alat + blat) / 2.0
    px, py = _project(plat, plon, lat0)
    ax, ay = _project(alat, alon, lat0)
    bx, by = _project(blat, blon, lat0)

    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq <= 1e-12:
        # Degenerate segment (identical endpoints). The artifact contains 0.1 m segments, so
        # this is reachable and must not divide by zero.
        cx, cy = ax, ay
    else:
        t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        cx, cy = ax + t * dx, ay + t * dy

    dist = math.hypot(px - cx, py - cy)
    # Back to degrees from the local frame.
    lat = cy / M_PER_DEG_LAT
    lon = cx / (M_PER_DEG_LAT * math.cos(math.radians(lat0)))
    return dist, lat, lon


def _candidate_edges(
    graph: RoadGraph, lat: float, lon: float, radius_m: float
) -> Iterable[Edge]:
    """Edges whose endpoints both lie within a latitude band around the point.

    The band is `radius_m` wide plus the length of the longest edge, because a long segment can
    have both endpoints outside the band while the segment itself passes right through it. That
    slack is computed from the graph rather than hardcoded, so it stays correct if the extract
    is rebuilt with longer ways.
    """
    if not graph.edges:
        return ()
    longest = max(e.length_m for e in graph.edges.values())
    lat_slack = (radius_m + longest) / M_PER_DEG_LAT
    lat0, lat1 = lat - lat_slack, lat + lat_slack

    out: list[Edge] = []
    for e in graph.edges.values():
        na = graph.nodes[e.a]
        nb = graph.nodes[e.b]
        # Cheap reject: neither endpoint inside the latitude band means the segment cannot be
        # within `radius_m` either, since segments do not curve (they are straight chords).
        if na.lat < lat0 and nb.lat < lat0:
            continue
        if na.lat > lat1 and nb.lat > lat1:
            continue
        out.append(e)
    return out


def snap_to_road(
    graph: RoadGraph,
    lat: float,
    lon: float,
    *,
    accuracy_m: float | None = None,
    threshold_m: float = DEFAULT_SNAP_THRESHOLD_M,
    max_accuracy_m: float = DEFAULT_MAX_ACCURACY_M,
) -> SnapResult:
    """Find the road segment a position most likely refers to, or explain why none does.

    The order of checks matters and is deliberate: accuracy is judged FIRST. A fix too imprecise
    to locate a street should not silently match the nearest one just because that street happens
    to be 8 m away on the map — 8 m of map distance means nothing when the fix itself carries
    300 m of uncertainty.
    """
    if not threshold_m > 0:
        raise ValueError("threshold_m must be > 0")
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise ValueError(f"coordinates out of range: lat={lat}, lon={lon}")

    if accuracy_m is not None and accuracy_m > max_accuracy_m:
        return SnapResult(
            edge_id=None,
            distance_m=float("inf"),
            snapped_lat=None,
            snapped_lon=None,
            reason=(
                f"GPS accuracy is about {accuracy_m:.0f} m, worse than the "
                f"{max_accuracy_m:.0f} m needed to identify a road; adjust the pin manually"
            ),
            accuracy_rejected=True,
        )

    best: tuple[float, Edge, float, float] | None = None
    for e in _candidate_edges(graph, lat, lon, threshold_m):
        na = graph.nodes[e.a]
        nb = graph.nodes[e.b]
        d, clat, clon = point_to_segment_m(lat, lon, na.lat, na.lon, nb.lat, nb.lon)
        if best is None or d < best[0]:
            best = (d, e, clat, clon)

    if best is None:
        return SnapResult(
            edge_id=None,
            distance_m=float("inf"),
            snapped_lat=None,
            snapped_lon=None,
            reason="no road segments exist near this position",
        )

    dist, edge, clat, clon = best
    if dist > threshold_m:
        return SnapResult(
            edge_id=None,
            distance_m=dist,
            snapped_lat=None,
            snapped_lon=None,
            reason=(
                f"the nearest road is {dist:.0f} m away, beyond the "
                f"{threshold_m:.0f} m matching limit; move the pin closer to a road"
            ),
        )

    return SnapResult(
        edge_id=edge.id,
        distance_m=round(dist, 1),
        snapped_lat=round(clat, 6),
        snapped_lon=round(clon, 6),
        reason="matched to the nearest road segment",
    )


# ---------------------------------------------------------------------------
# Public-location coarsening
# ---------------------------------------------------------------------------

# 0.001 degrees of latitude is ~111 m. Rounding to this grid means an unmatched report's
# published pin is accurate to a city block rather than to the submitter's doorstep, while
# still being useful on a map. It is applied ONLY when no segment was matched: a matched
# report publishes the snapped point, which is already a road position and carries no
# information about where the person was standing.
PUBLIC_ROUNDING_DEG = 0.001


def public_location(
    lat: float,
    lon: float,
    snap: SnapResult | None,
    *,
    rounding_deg: float = PUBLIC_ROUNDING_DEG,
) -> tuple[float, float, bool]:
    """The coordinate a public map may show, plus whether it is the snapped road point.

    Returns (lat, lon, is_snapped).

    Rationale for the two branches, because this is a privacy control and not cosmetics:

      matched   -> the snapped point on the road. Publishing this reveals nothing about the
                   submitter's exact standing position; it reveals where the road is.
      unmatched -> the coarse-grid centre of the cell containing the raw fix. Publishing the
                   raw coordinate here would disclose a precise position, and the report has
                   no road to attach to anyway, so precision buys the map nothing.
    """
    if snap is not None and snap.matched and snap.snapped_lat is not None:
        return snap.snapped_lat, snap.snapped_lon, True  # type: ignore[return-value]
    if rounding_deg <= 0:
        raise ValueError("rounding_deg must be > 0")
    return (
        round(round(lat / rounding_deg) * rounding_deg, 6),
        round(round(lon / rounding_deg) * rounding_deg, 6),
        False,
    )


def is_within_city(lat: float, lon: float, bounds: Mapping[str, float]) -> bool:
    """Bounding check so this app does not become a general-purpose report inbox."""
    return (
        bounds["lat_min"] <= lat <= bounds["lat_max"]
        and bounds["lon_min"] <= lon <= bounds["lon_max"]
    )


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Thin alias so callers do not import the graph module just for a distance."""
    return haversine_m(a, b)
