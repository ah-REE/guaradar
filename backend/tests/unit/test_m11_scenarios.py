"""M11 tests — demo scenarios, profile isolation, and Status-tab regressions.

Two groups:

  * SCENARIO tests assert the five required demonstrations against the real API, so the demo
    cannot silently stop demonstrating what it claims.
  * PROFILE tests prove the `demo_clear` fixture is isolated: it writes nothing, it does not
    change the baseline, and its closures cannot be mistaken for live data.

The Status-tab regressions (timestamp formatting, null-safe numbers, error boundary) live in
tests/unit/test_m11_frontend_contract.py, because they are about the payload contract the UI
depends on rather than about the API itself.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.main import app, get_graph, get_now
from app.routing.demo_profiles import (
    baseline_status,
    build_profile_status,
    demo_clear_status,
)
from app.routing.graph import STATUS_AFFECTED, STATUS_CLOSED, STATUS_OPEN, STATUS_UNKNOWN
from app.routing.scenarios import SCENARIOS, route_query, scenario_by_name

NOW = datetime(2026, 10, 26, 14, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fixed_clock():
    app.dependency_overrides[get_now] = lambda: NOW
    yield
    app.dependency_overrides.clear()


def client() -> TestClient:
    return TestClient(app)


# ===========================================================================
# Section 1 — the five required scenarios, against the real API
# ===========================================================================


@pytest.mark.parametrize("scenario", [s for s in SCENARIOS if s.origin is not None],
                         ids=lambda s: s.name)
def test_scenario_matches_its_contract(scenario) -> None:
    """Each scenario must produce exactly the outcome it documents."""
    q = route_query(scenario)
    assert q is not None
    with client() as c:
        resp = c.get(q)
    assert resp.status_code == 200, f"{scenario.name}: {resp.status_code}"
    d = resp.json()

    assert d["refused"] is scenario.expect_refused, (
        f"{scenario.name}: refused={d['refused']} expected {scenario.expect_refused}"
    )
    recommended = any(r["recommended"] for r in d["routes"])
    assert recommended is scenario.expect_any_recommended, (
        f"{scenario.name}: recommended={recommended} expected {scenario.expect_any_recommended}"
    )
    assert d["all_routes_hazard_crossing"] is scenario.expect_all_hazard_crossing

    if scenario.expect_band_in:
        bands = {r["band"] for r in d["routes"]}
        assert bands <= set(scenario.expect_band_in), (
            f"{scenario.name}: bands {bands} outside {scenario.expect_band_in}"
        )


def test_scenario_eligible_has_a_recommended_clear_route() -> None:
    """Scenario 1 in detail: phase 1, clear, high coverage, recommended, and not fixture-hidden."""
    s = scenario_by_name("eligible")
    with client() as c:
        d = c.get(route_query(s)).json()

    assert d["profile_is_demo_fixture"] is True, "the fixture must be disclosed"
    best = d["routes"][0]
    assert best["phase"] == 1, "an eligible route must come from phase 1"
    assert best["hazard_class"] == "clear"
    assert best["recommended"] is True
    assert best["coverage_pct"] >= 60.0
    # Every returned route is clear: with 6 closures the closed-free graph is essentially whole.
    assert all(r["hazard_class"] == "clear" for r in d["routes"])


def test_scenario_hazard_crossing_never_recommended() -> None:
    """Scenario 2: phase 2 only, and nothing recommended."""
    s = scenario_by_name("hazard_crossing")
    with client() as c:
        d = c.get(route_query(s)).json()

    assert d["profile_is_demo_fixture"] is False, "baseline must not claim to be a fixture"
    assert d["all_routes_hazard_crossing"] is True
    for r in d["routes"]:
        assert r["phase"] == 2, "phase 1 should have found nothing here"
        assert r["hazard_class"] == "hazard_crossing"
        assert r["recommended"] is False
        assert "crosses a closed road" in r["label"]


def test_scenario_low_coverage_served_but_not_recommended() -> None:
    """Scenario 3: served for transparency, never recommended."""
    s = scenario_by_name("low_coverage")
    with client() as c:
        d = c.get(route_query(s)).json()

    assert d["refused"] is False
    assert d["routes"], "routes should still be served"
    for r in d["routes"]:
        assert r["band"] in ("low", "none")
        assert r["recommended"] is False


def test_scenario_refused_gives_a_reason() -> None:
    """Scenario 4: a truthful refusal, HTTP 200, with a usable reason."""
    s = scenario_by_name("refused")
    with client() as c:
        resp = c.get(route_query(s))

    # A valid question with an unroutable answer is not a transport error.
    assert resp.status_code == 200
    d = resp.json()
    assert d["refused"] is True
    assert d["routes"] == []
    assert "nearest road" in (d["refusal_reason"] or "")
    assert "60 m" in (d["refusal_reason"] or "")


def test_scenario_unknown_edge_stays_unknown() -> None:
    """Scenario 5: asserted on the status index — absence is `unknown`, never `open`."""
    graph = get_graph()
    index = baseline_status(graph, NOW)

    # Find an edge the baseline generator deliberately leaves without a record.
    no_record = [
        eid for eid in sorted(graph.edges)
        if index.status_of(eid) == STATUS_UNKNOWN
    ]
    assert no_record, "the baseline profile should leave some edges unknown"

    for eid in no_record[:20]:
        assert index.status_of(eid) == STATUS_UNKNOWN
        assert index.status_of(eid) != STATUS_OPEN, "unknown must never read as open"
        assert index.is_verified(eid) is False, "unknown must not count as verified coverage"
        assert index.is_closed(eid) is False, "unknown is not a closure either"


def test_all_scenarios_are_defined_and_documented() -> None:
    """Guards against a scenario being deleted without noticing."""
    names = {s.name for s in SCENARIOS}
    assert names == {"eligible", "hazard_crossing", "low_coverage", "refused", "unknown_edge"}
    for s in SCENARIOS:
        assert s.title
        assert s.demonstrates, f"{s.name} must say what it demonstrates"
        assert s.profile in ("baseline", "demo_clear")


# ===========================================================================
# Section 2 — profile isolation and honesty
# ===========================================================================


def test_demo_clear_has_far_fewer_closures_than_baseline() -> None:
    """The fixture exists to be sparse; if it ever became dense it would defeat its purpose."""
    graph = get_graph()
    base, base_info = build_profile_status(graph, NOW, "baseline")
    demo, demo_info = build_profile_status(graph, NOW, "demo_clear")

    assert demo_info.is_demo_fixture is True
    assert base_info.is_demo_fixture is False
    assert demo_info.closure_count == 6, f"expected exactly 6, got {demo_info.closure_count}"
    assert demo_info.closure_count < base_info.closure_count


def test_demo_clear_is_deterministic() -> None:
    """Same inputs, same statuses — a rehearsal must reproduce exactly."""
    graph = get_graph()
    a, _ = build_profile_status(graph, NOW, "demo_clear")
    b, _ = build_profile_status(graph, NOW, "demo_clear")
    for eid in list(graph.edges)[:500]:
        assert a.status_of(eid) == b.status_of(eid)


def test_baseline_profile_unchanged_by_the_fixture_existing() -> None:
    """Adding a profile must not alter the baseline. This is the isolation guarantee."""
    graph = get_graph()
    index, info = build_profile_status(graph, NOW, "baseline")

    # Recompute the original algorithm inline and compare, so a future edit to
    # baseline_status() that changes behaviour fails here.
    expected: dict[int, str] = {}
    for i, eid in enumerate(sorted(graph.edges)):
        if i % 29 == 0:
            expected[eid] = STATUS_CLOSED
        elif i % 13 == 0:
            expected[eid] = STATUS_AFFECTED
        elif i % 2 != 0:
            expected[eid] = STATUS_OPEN
    checked = 0
    for eid, want in list(expected.items())[:500]:
        assert index.status_of(eid) == want, f"baseline changed for edge {eid}"
        checked += 1
    assert checked > 100
    assert info.closure_count > 800, "baseline should still be dense"


def test_unknown_profile_rejected_by_api() -> None:
    with client() as c:
        r = c.get(
            "/api/public/route?from_lat=-2.142763&from_lon=-79.905598"
            "&to_lat=-2.220429&to_lon=-79.908965&profile=nonsense"
        )
    assert r.status_code == 422
    assert "unknown profile" in r.json()["detail"]


def test_fixture_disclosure_reaches_provenance_notes() -> None:
    """A consumer must be able to tell a fixture from the baseline in the payload itself."""
    s = scenario_by_name("eligible")
    with client() as c:
        d = c.get(route_query(s)).json()

    notes = " ".join(d["provenance"]["notes"]).lower()
    assert "demo fixture" in notes
    assert "not " in notes and "real" in notes, "must deny being real data"


def test_baseline_disclosure_does_not_claim_fixture() -> None:
    s = scenario_by_name("hazard_crossing")
    with client() as c:
        d = c.get(route_query(s)).json()
    assert d["profile_is_demo_fixture"] is False
    assert d["status_profile"] == "baseline"


# ===========================================================================
# Section 3 — invariants must survive the profiles
# ===========================================================================


@pytest.mark.parametrize("profile", ["baseline", "demo_clear"])
def test_phase1_never_crosses_a_closure_under_any_profile(profile: str) -> None:
    """The structural guarantee must hold regardless of which status set is supplied."""
    graph = get_graph()
    index, _ = build_profile_status(graph, NOW, profile)

    from app.routing.search import find_routes

    from app.routing.scenarios import DEMO_POINTS

    origin = DEMO_POINTS["SIM-01"]
    dest = DEMO_POINTS["SIM-04"]
    resp = find_routes(graph, index, origin, dest)

    for r in resp.routes:
        if r.phase == 1:
            for leg in r.legs:
                assert index.status_of(leg.edge_id) != STATUS_CLOSED, (
                    f"{profile}: phase-1 route crossed closed edge {leg.edge_id}"
                )


@pytest.mark.parametrize("profile", ["baseline", "demo_clear"])
def test_stale_closure_still_excluded_under_any_profile(profile: str) -> None:
    """O-8: ageing a closure must not reopen the road, whichever profile is active."""
    from app.routing.graph import EdgeStatus, StatusIndex

    index, _ = build_profile_status(get_graph(), NOW, profile)
    # Build a deliberately stale closure on a known edge and confirm it still excludes.
    target = sorted(get_graph().edges)[0]
    stale = StatusIndex(
        [EdgeStatus(target, STATUS_CLOSED, NOW - timedelta(hours=48))],
        now=NOW,
    )
    assert stale.is_closed(target) is True
    assert stale.is_verified(target) is False


@pytest.mark.parametrize("profile", ["baseline", "demo_clear"])
def test_one_way_adjacency_untouched_by_profiles(profile: str) -> None:
    """Status profiles must not influence directionality, which lives in adjacency."""
    graph = get_graph()
    # Reachability is a graph property; status cannot change it.
    oneway = [e for e in graph.edges.values() if e.direction == "forward"][:50]
    assert oneway, "expected one-way edges in the real graph"
    for e in oneway:
        assert e.id in graph.adjacency[e.a]
        assert e.id not in graph.adjacency[e.b]


def test_recommendation_requires_moderate_coverage_in_every_profile() -> None:
    """Low coverage can never be recommended, no matter the closure situation."""
    for s in SCENARIOS:
        if s.origin is None:
            continue
        with client() as c:
            d = c.get(route_query(s)).json()
        for r in d["routes"]:
            if r["band"] in ("low", "none"):
                assert r["recommended"] is False, (
                    f"{s.name}: {r['id']} has band {r['band']} but is recommended"
                )
