"""M11 demo scenarios — the five required demonstrations, made explicit and testable.

Each scenario states what it must show, which profile and endpoints produce it, and the exact
outcome observed. The tests in `tests/unit/test_m11_scenarios.py` assert these outcomes, so the
demo cannot silently stop demonstrating what it claims.

THE FIVE SCENARIOS (from the M11 brief)

  1. eligible        A route that avoids all known closures and is recommended.
                     Profile: `demo_clear` (a labelled DEMO FIXTURE — 6 synthetic closures).
  2. hazard_crossing Phase 1 finds nothing; phase 2 returns a labelled closure-crossing route.
                     Profile: `baseline`, where 3.5 % closure density makes this the norm for
                     cross-sector trips.
  3. low_coverage    Served but NOT recommended because verified coverage is low.
                     Profile: `baseline`, where much of the route is unknown.
  4. refused         Origin/destination outside the extract or too far from a road.
  5. unknown_edge    An edge with no status record stays `unknown`, never `open`/safe.

WHY TWO PROFILES ARE NEEDED
  Scenario 1 and scenarios 2–3 are mutually exclusive on one dataset. With 3.5 % closure density
  the chance a 200-edge path avoids every closure is 0.09 %, so an eligible route is essentially
  unreachable; with 6 closures almost every trip is eligible, so a forced phase-2 case is
  unreachable. Rather than tune one generator to fake both, each scenario uses the profile that
  genuinely produces it, and the response discloses which profile was used.

ISOLATION
  Profiles are pure functions of (graph, now, name). They write nothing, cannot touch persisted
  rows, and are selected per request. Deactivating `demo_clear` is simply not requesting it —
  there is no state to restore and no data to destroy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ScenarioName = Literal[
    "eligible", "hazard_crossing", "low_coverage", "refused", "unknown_edge"
]


@dataclass(frozen=True)
class Scenario:
    """A demo scenario with the properties it must exhibit."""

    name: ScenarioName
    title: str
    profile: str
    origin: tuple[float, float] | None
    destination: tuple[float, float] | None
    # What the response must show. Used directly by the tests.
    expect_refused: bool
    expect_any_recommended: bool
    expect_all_hazard_crossing: bool
    expect_band_in: tuple[str, ...] | None
    demonstrates: str
    is_demo_fixture: bool


# The six demo points = real graph nodes nearest each sensor site.
DEMO_POINTS: dict[str, tuple[float, float]] = {
    "SIM-01": (-2.142763, -79.905598),
    "SIM-02": (-2.149230, -79.901801),
    "SIM-03": (-2.196117, -79.886222),
    "SIM-04": (-2.220429, -79.908965),
    "SIM-05": (-2.227579, -79.914710),
    "SIM-06": (-2.157834, -79.889898),
}

# Deliberately far outside the extract (~19 km from any road).
OUTSIDE_ORIGIN = (-2.4000, -80.0000)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="eligible",
        title="Recommended route that avoids every closure",
        profile="demo_clear",
        origin=DEMO_POINTS["SIM-01"],
        destination=DEMO_POINTS["SIM-04"],
        expect_refused=False,
        expect_any_recommended=True,
        expect_all_hazard_crossing=False,
        expect_band_in=("high", "moderate"),
        demonstrates=(
            "Phase 1 succeeds and the top route is `clear` with high verified coverage, so it is "
            "recommended. Uses the DEMO FIXTURE profile; its closures are synthetic demo data, "
            "not real reports."
        ),
        is_demo_fixture=True,
    ),
    Scenario(
        name="hazard_crossing",
        title="No clear route exists; phase 2 answers with a labelled closure crossing",
        profile="baseline",
        origin=DEMO_POINTS["SIM-01"],
        destination=DEMO_POINTS["SIM-04"],
        expect_refused=False,
        expect_any_recommended=False,
        expect_all_hazard_crossing=True,
        expect_band_in=None,
        demonstrates=(
            "3.5 % closure density makes every route cross at least one closure, so phase 1 "
            "finds nothing and phase 2 returns hazard-crossing routes. None is recommended."
        ),
        is_demo_fixture=False,
    ),
    Scenario(
        name="low_coverage",
        title="Served but not recommended because coverage is low",
        profile="baseline",
        origin=DEMO_POINTS["SIM-03"],
        destination=DEMO_POINTS["SIM-06"],
        expect_refused=False,
        expect_any_recommended=False,
        expect_all_hazard_crossing=False,
        expect_band_in=("low", "none"),
        demonstrates=(
            "Routes are served for transparency but carry low verified coverage, so "
            "`recommended` is false regardless of the closure question."
        ),
        is_demo_fixture=False,
    ),
    Scenario(
        name="refused",
        title="Request refused — origin is nowhere near a road",
        profile="baseline",
        origin=OUTSIDE_ORIGIN,
        destination=DEMO_POINTS["SIM-04"],
        expect_refused=True,
        expect_any_recommended=False,
        expect_all_hazard_crossing=False,
        expect_band_in=None,
        demonstrates=(
            "The 60 m snap limit refuses rather than routing from a guessed origin. The response "
            "is HTTP 200 with `refused: true` and a reason, because an unroutable point is a "
            "valid answer to a valid question."
        ),
        is_demo_fixture=False,
    ),
    Scenario(
        name="unknown_edge",
        title="An edge with no status record stays unknown",
        profile="baseline",
        origin=None,
        destination=None,
        expect_refused=False,
        expect_any_recommended=False,
        expect_all_hazard_crossing=False,
        expect_band_in=None,
        demonstrates=(
            "Absence of a status record is `unknown`, which is never `open` and never counted as "
            "verified coverage. Asserted directly against the status index rather than through a "
            "route, because a route's legs only show the edges it happens to use."
        ),
        is_demo_fixture=False,
    ),
)


def scenario_by_name(name: str) -> Scenario:
    for s in SCENARIOS:
        if s.name == name:
            return s
    raise KeyError(f"unknown scenario {name!r}; have {[s.name for s in SCENARIOS]}")


def route_query(scenario: Scenario, *, alternatives: int = 3) -> str | None:
    """The exact query string for a scenario, or None for the index-level scenario."""
    if scenario.origin is None or scenario.destination is None:
        return None
    (la, lo), (lb, lbo) = scenario.origin, scenario.destination
    return (
        f"/api/public/route?from_lat={la}&from_lon={lo}"
        f"&to_lat={lb}&to_lon={lbo}"
        f"&alternatives={alternatives}&profile={scenario.profile}"
    )
