"""M12 — demo scenario selector: UI contract, demo disclosure, and i18n guard integrity.

The selector itself is React; without a browser (see docs/M12-VISUAL-CHECKLIST.md) these tests
verify the CONTRACT the selector depends on:

  * the profile parameter round-trips through the API client's URL shape;
  * `baseline` stays the default and is unchanged;
  * `demo_clear` yields a phase-1, high-coverage, recommended route;
  * an unknown profile still fails with 422 — a typo can never silently select demo data;
  * every string the selector renders exists in BOTH locales;
  * the demo disclosure is present, non-dismissible, and makes no safety claim.

The i18n guard itself is tested too, because M12 found that it had been silently skipping 31 of
76 keys: a guard that reports "passed" while validating 59 % of the catalogue is a liability, not
a control.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import app, get_now

ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / "frontend"
SRC = FRONTEND / "src"

from datetime import datetime, timezone

NOW = datetime(2026, 10, 26, 14, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clock():
    app.dependency_overrides[get_now] = lambda: NOW
    yield
    app.dependency_overrides.clear()


def src_text(name: str) -> str:
    p = SRC / name
    assert p.exists(), f"missing {p}"
    return p.read_text(encoding="utf-8")


ROUTE_A = "from_lat=-2.142763&from_lon=-79.905598&to_lat=-2.220429&to_lon=-79.908965"


def string_block(key: str) -> str:
    """Return ONLY the `key: { en, es }` entry, never the following constants.

    A fixed character window is not safe here: the catalogue is followed by `BANNED_TERMS`, so a
    window wide enough to hold a long Spanish string also swallows the banned-word list and the
    test "fails" on the guard's own vocabulary. Bounding at the closing brace is exact.
    """
    i18n = src_text("i18n.ts")
    start = i18n.index(f"{key}: {{")
    # The entry closes at the first `},` or `\n  },` after the Spanish value.
    m = re.search(r"\n  \},", i18n[start:])
    assert m, f"could not find the end of {key}"
    return i18n[start: start + m.end()]





# ===========================================================================
# 1. The API contract the selector relies on
# ===========================================================================


def test_client_always_sends_profile_explicitly() -> None:
    """The request must state its scenario, not rely on a default it cannot see."""
    api = src_text("routeApi.ts")
    assert "profile: StatusProfile = 'baseline'" in api, "baseline must be the client default"
    assert "profile," in api, "the profile must be included in the query string"


def test_client_offer_only_the_two_known_profiles() -> None:
    """A free-text profile field would let a typo reach the server; the type prevents it."""
    api = src_text("routeApi.ts")
    assert "export type StatusProfile = 'baseline' | 'demo_clear'" in api


def test_selector_defaults_to_baseline() -> None:
    """Out-of-the-box behaviour must be unchanged."""
    screen = src_text("RouteScreen.tsx")
    assert "useState<StatusProfile>('baseline')" in screen


def test_selector_offers_both_options_and_refetches_on_change() -> None:
    """A selector that does not refetch would show stale results under the wrong label."""
    screen = src_text("RouteScreen.tsx")
    assert '<option value="baseline">' in screen
    assert '<option value="demo_clear">' in screen
    # The effect must depend on the profile, not run once on mount.
    assert "}, [profile])" in screen, "changing the scenario must trigger a refetch"


def test_baseline_still_returns_phase2_non_recommended() -> None:
    """M12 must not have altered baseline behaviour."""
    with TestClient(app) as c:
        d = c.get(f"/api/public/route?{ROUTE_A}&profile=baseline").json()
    assert d["status_profile"] == "baseline"
    assert d["profile_is_demo_fixture"] is False
    assert d["all_routes_hazard_crossing"] is True
    for r in d["routes"]:
        assert r["recommended"] is False
        assert r["phase"] == 2


def test_demo_clear_returns_phase1_high_coverage_recommended() -> None:
    """The scenario the selector exists to expose."""
    with TestClient(app) as c:
        d = c.get(f"/api/public/route?{ROUTE_A}&profile=demo_clear").json()
    assert d["status_profile"] == "demo_clear"
    assert d["profile_is_demo_fixture"] is True
    best = d["routes"][0]
    assert best["phase"] == 1
    assert best["hazard_class"] == "clear"
    assert best["recommended"] is True
    assert best["band"] == "high"
    assert best["coverage_pct"] >= 60.0


def test_omitting_profile_still_defaults_to_baseline() -> None:
    with TestClient(app) as c:
        d = c.get(f"/api/public/route?{ROUTE_A}").json()
    assert d["status_profile"] == "baseline"


@pytest.mark.parametrize("bad", ["demo", "DEMO_CLEAR", "demo-clear", "", "baseline "])
def test_unknown_profile_still_422(bad: str) -> None:
    """A typo must fail loudly. Falling back to demo data would be the dangerous direction."""
    with TestClient(app) as c:
        r = c.get(f"/api/public/route?{ROUTE_A}&profile={bad}")
    assert r.status_code == 422, f"{bad!r} should be rejected, got {r.status_code}"


# ===========================================================================
# 2. The demo disclosure
# ===========================================================================


def test_demo_warning_is_rendered_only_for_the_demo_scenario() -> None:
    screen = src_text("RouteScreen.tsx")
    # Guarded by a conditional render, not always visible.
    assert "{profile === 'demo_clear' && (" in screen
    assert "tr('scenarioDemoWarning')" in screen


def test_demo_warning_is_not_dismissible() -> None:
    """A dismissible warning about simulated data is a warning users stop seeing."""
    screen = src_text("RouteScreen.tsx")
    idx = screen.index("{profile === 'demo_clear' && (")
    block = screen[idx: idx + 900]
    for word in ("onClick", "onClose", "setDismissed", "×", "hide"):
        assert word not in block, f"demo warning must not be dismissible (found {word!r})"


def test_demo_warning_says_simulated_and_not_verified() -> None:
    """Worded so it cannot be read as a claim about real roads."""
    block = string_block("scenarioDemoWarning")
    en = block.lower()
    assert "simulated" in en, "must say the closures are simulated"
    assert "not verified" in en, "must deny being verified real-world reports"
    # Spanish must say the same thing, not approximate it.
    assert "simulados" in block
    assert "no reportes reales verificados" in block


def test_demo_warning_makes_no_safety_claim() -> None:
    block = string_block("scenarioDemoWarning").lower()
    for banned in ("is safe", "route is safe", "guaranteed", "es segura", "flood-proof"):
        assert banned not in block, f"demo warning must not claim {banned!r}"


def test_selector_has_accessible_label_and_description() -> None:
    """An unlabelled select is unusable with a screen reader."""
    screen = src_text("RouteScreen.tsx")
    assert 'htmlFor="scenario-select"' in screen
    assert 'id="scenario-select"' in screen
    assert 'aria-describedby="scenario-help"' in screen
    assert 'id="scenario-help"' in screen


# ===========================================================================
# 3. i18n guard integrity — the M12 finding
# ===========================================================================


def test_every_declared_string_key_is_parsed_by_the_guard() -> None:
    """M12 found the guard skipping 31 of 76 keys, including every long safety message.

    It reported "passed" while validating 59 % of the catalogue. This asserts full coverage.
    """
    i18n = src_text("i18n.ts")
    entry_re = re.compile(
        r"(\w+):\s*\{\s*en:\s*('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")\s*,"
        r"\s*es:\s*('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")\s*,?\s*\}",
        re.S,
    )
    declared = re.findall(r"^  (\w+):\s*\{", i18n, re.M)
    parsed = {m.group(1) for m in entry_re.finditer(i18n)}
    missing = [k for k in declared if k not in parsed]
    assert not missing, f"unvalidated keys: {missing}"


def test_guard_runs_clean_and_reports_full_coverage() -> None:
    """The guard must name the key count it validated, and it must equal the declared count."""
    out = subprocess.run(
        ["node", "__i18n-check.mjs"],
        cwd=SRC,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr
    m = re.search(r"(\d+) keys", out.stdout)
    assert m, out.stdout
    validated = int(m.group(1))
    declared = len(re.findall(r"^  (\w+):\s*\{", src_text("i18n.ts"), re.M))
    assert validated == declared, (
        f"guard validated {validated} of {declared} keys — coverage is not complete"
    )


def test_guard_catches_a_real_overclaim() -> None:
    """Proof the guard still fails on a genuine violation, not just on well-formed input."""
    i18n_path = SRC / "i18n.ts"
    original = i18n_path.read_text(encoding="utf-8")
    try:
        mutated = original.replace(
            "en: 'A path existing in the data does not mean a road is safe to travel.'",
            "en: 'This is a safe route and it is guaranteed.'",
        )
        assert mutated != original, "mutation target not found — the test would be vacuous"
        i18n_path.write_text(mutated, encoding="utf-8")
        out = subprocess.run(
            ["node", "__i18n-check.mjs"], cwd=SRC, capture_output=True, text=True
        )
        assert out.returncode != 0, "guard failed to catch an injected overclaim"
        assert "safe route" in out.stderr or "guaranteed" in out.stderr
    finally:
        i18n_path.write_text(original, encoding="utf-8")


def test_guard_is_negation_aware_for_honest_disclaimers() -> None:
    """The disclaimers contain "is safe" inside a negation; they must not be flagged."""
    for key in ("routeNotSafe", "pathIsNotSafety", "routeElevationTiebreak"):
        block = string_block(key).lower()
        assert "not" in block, f"{key} should read as a negation and be allowed through"
    # And the guard must agree.
    out = subprocess.run(["node", "__i18n-check.mjs"], cwd=SRC, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


# ===========================================================================
# 4. Selector strings are complete in both locales
# ===========================================================================


@pytest.mark.parametrize(
    "key",
    [
        "scenarioLabel",
        "scenarioBaseline",
        "scenarioDemoClear",
        "scenarioHelp",
        "scenarioDemoWarning",
    ],
)
def test_selector_string_exists_in_both_languages(key: str) -> None:
    i18n = src_text("i18n.ts")
    m = re.search(rf"{key}:\s*\{{\s*en:\s*'((?:[^'\\]|\\.)*)'\s*,\s*es:\s*'((?:[^'\\]|\\.)*)'", i18n, re.S)
    assert m, f"{key} missing or not bilingual"
    assert m.group(1).strip(), f"{key}: empty English"
    assert m.group(2).strip(), f"{key}: empty Spanish"


def test_selector_help_explains_why_two_scenarios_exist() -> None:
    """Without the explanation the selector looks like a way to make results look better."""
    block = string_block("scenarioHelp").lower()
    assert "twenty-nine" in block or "veintinueve" in block
    assert "six" in block or "seis" in block
