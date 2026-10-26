"""Deterministic demo scenario profiles (M11 Part B and Part D).

WHY THIS EXISTS — the N-16 diagnosis, quantified
  The baseline demo generator marks 1 edge in 29 as closed across the whole graph. On the
  24,943-edge graph that is 861 closures, **3.5 % density**. A cross-sector route traverses
  200–300 edges, so the probability that it avoids every closure is:

      path of  50 edges: 17.3 %
      path of 100 edges:  2.98 %
      path of 200 edges:  0.089 %
      path of 300 edges:  0.0026 %

  So phase 1 almost never succeeds for a cross-sector trip, and nearly every route is served by
  phase 2 as `hazard_crossing`. That is **correct engine behaviour** with dense demo status — the
  two-phase guarantee is doing exactly what it should. It simply makes a poor demonstration,
  because the eligible case is invisible.

WHAT THIS MODULE DOES ABOUT IT
  It does **not** lower the baseline closure density. The baseline generator is untouched, so no
  existing test, invariant or artefact changes.

  Instead it adds an **explicitly selectable, isolated** demo profile with a handful of closures
  placed on a small number of named corridors. Selecting it is a deliberate act with a visible
  label; the default is unchanged.

SAFETY PROPERTIES PRESERVED (all of them, by construction — the engine is not modified)
  * phase 1 still structurally excludes closed edges (the profile only supplies statuses)
  * phase 2 still runs only when phase 1 finds nothing
  * closure-crossing routes are still never recommended
  * unknown/stale evidence still cannot improve eligibility
  * low/zero coverage still never becomes recommended
  * one-way directionality is untouched (it lives in adjacency)
  * O-8 stale-closure behaviour is untouched

ISOLATION
  A profile is a pure function of (graph, now, profile name). It writes nothing, cannot touch
  persisted rows, and its closures carry `source="demo_profile"` semantics via the returned
  label so the API can disclose which profile produced a response. Deactivating it is simply not
  requesting it — there is no state to restore, and no data to destroy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.routing.graph import (
    DEFAULT_FRESHNESS,
    STATUS_AFFECTED,
    STATUS_CLOSED,
    STATUS_OPEN,
    EdgeStatus,
    RoadGraph,
    StatusIndex,
    haversine_m,
)

ProfileName = Literal["baseline", "demo_clear"]


@dataclass(frozen=True)
class ProfileInfo:
    """What a profile is, stated plainly so an API can disclose it."""

    name: ProfileName
    label: str
    description: str
    # True when the profile exists purely to make a demonstration legible.
    is_demo_fixture: bool
    # How many closures it applies, for the response notes.
    closure_count: int


# ---------------------------------------------------------------------------
# Baseline — the existing behaviour, extracted unchanged
# ---------------------------------------------------------------------------


def baseline_status(graph: RoadGraph, now: datetime) -> StatusIndex:
    """The pre-existing generator, **unchanged in behaviour**.

    Kept byte-equivalent to the original: every 29th edge closed, every 13th affected, every
    other edge verified open. Any change here would silently alter every existing demo result,
    so it is deliberately not "improved".
    """
    statuses: list[EdgeStatus] = []
    for i, eid in enumerate(sorted(graph.edges)):
        if i % 29 == 0:
            statuses.append(EdgeStatus(eid, STATUS_CLOSED, now - timedelta(minutes=10)))
        elif i % 13 == 0:
            statuses.append(EdgeStatus(eid, STATUS_AFFECTED, now - timedelta(minutes=5)))
        elif i % 2 != 0:
            statuses.append(EdgeStatus(eid, STATUS_OPEN, now - timedelta(minutes=5)))
    return StatusIndex(statuses, now=now, freshness=DEFAULT_FRESHNESS)


# ---------------------------------------------------------------------------
# demo_clear — a small, isolated set of closures on named corridors
# ---------------------------------------------------------------------------


def _pseudo_random_edges(graph: RoadGraph, count: int, salt: str) -> list[int]:
    """Pick `count` edges deterministically, spread across the graph.

    Deterministic by construction (sorted edge ids + a fixed stride), so repeated calls give
    identical results and a rehearsal reproduces exactly.
    """
    ids = sorted(graph.edges)
    if not ids:
        return []
    stride = max(1, len(ids) // max(count, 1))
    offset = sum(ord(c) for c in salt) % max(stride, 1)
    picked: list[int] = []
    for k in range(count):
        idx = (offset + k * stride) % len(ids)
        picked.append(ids[idx])
    return picked


def demo_clear_status(graph: RoadGraph, now: datetime) -> StatusIndex:
    """A deliberately sparse profile so an eligible route is demonstrable.

    Design choices, each deliberate:

      * **Few closures, far apart.** Route-search repulsion means the alternative path must
        exist; with 6 closures over 24,943 edges the closed-free graph is still essentially
        complete, so phase 1 succeeds for most trips.
      * **Most edges verified open.** Without verified status the coverage figure is 0 % and
        nothing can be recommended regardless of closures — a route can only be *recommended*
        if its coverage is moderate or better. So this profile makes the majority verified.
      * **A slice deliberately left `unknown`.** Roughly one edge in six gets no record, so the
        "served but not recommended because coverage is low" scenario remains reachable and the
        app cannot look more certain than it is.

    No edge is marked `open` merely because it exists: `open` here is demo status, and the API
    response says the profile is a demo fixture.
    """
    graph_edges = sorted(graph.edges)
    n = len(graph_edges)
    if n == 0:
        return StatusIndex([], now=now, freshness=DEFAULT_FRESHNESS)

    closed_ids = set(_pseudo_random_edges(graph, 6, "demo-clear-closures"))
    # A handful of affected roads, kept clear of the closed set.
    affected_ids = set(_pseudo_random_edges(graph, 12, "demo-clear-affected")) - closed_ids

    statuses: list[EdgeStatus] = []
    for i, eid in enumerate(graph_edges):
        if eid in closed_ids:
            statuses.append(EdgeStatus(eid, STATUS_CLOSED, now - timedelta(minutes=10)))
        elif eid in affected_ids:
            statuses.append(EdgeStatus(eid, STATUS_AFFECTED, now - timedelta(minutes=5)))
        elif i % 6 == 0:
            # Left with no record -> unknown. Keeps a low-coverage case reachable and honest.
            continue
        else:
            statuses.append(EdgeStatus(eid, STATUS_OPEN, now - timedelta(minutes=5)))
    return StatusIndex(statuses, now=now, freshness=DEFAULT_FRESHNESS)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


PROFILE_INFO: dict[ProfileName, str] = {
    "baseline": "Baseline demo status",
    "demo_clear": "Sparse demo status (few closures)",
}


def build_profile_status(
    graph: RoadGraph, now: datetime, profile: ProfileName
) -> tuple[StatusIndex, ProfileInfo]:
    """Return the status index for a profile, plus its disclosure info."""
    if profile == "baseline":
        index = baseline_status(graph, now)
        info = ProfileInfo(
            name="baseline",
            label=PROFILE_INFO["baseline"],
            description=(
                "Baseline demo generator: 1 edge in 29 closed, 1 in 13 affected. Dense enough "
                "that most cross-sector routes must cross a closure, which is why phase 2 is "
                "the common outcome."
            ),
            is_demo_fixture=False,
            closure_count=sum(1 for e in graph.edges if index.is_closed(e)),
        )
        return index, info

    if profile == "demo_clear":
        index = demo_clear_status(graph, now)
        info = ProfileInfo(
            name="demo_clear",
            label=PROFILE_INFO["demo_clear"],
            description=(
                "DEMO FIXTURE: 6 synthetic closures placed deterministically, with most other "
                "edges verified open and ~1 in 6 left unknown. Exists only so an eligible route "
                "can be demonstrated. These closures are demo data, not real reports."
            ),
            is_demo_fixture=True,
            closure_count=sum(1 for e in graph.edges if index.is_closed(e)),
        )
        return index, info

    raise ValueError(f"unknown profile {profile!r}; expected one of {sorted(PROFILE_INFO)}")
