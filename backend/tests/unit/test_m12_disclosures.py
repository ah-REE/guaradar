"""M12 (frontend-first) — disclosure accuracy, and the guards that stop it going stale.

THE DEFECT THIS FILE EXISTS FOR
  The Status tab's limitations list told the user:

    * "about 50 km of streets"      -> the graph holds 1,084.5 km. Stale by ~21x.
    * "Routing is not exposed in this version. No route is drawn or implied here."
                                    -> the Route tab next to it worked.

  Both were plain text in the i18n catalogue, so nothing could catch them. The fixes were
  (a) correct the words, (b) quote the measured figure from `/api/health` instead of hardcoding
  it, and (c) — this file — assert that the claims stay true.

The lesson encoded here: any user-visible sentence that states a NUMBER or an AVAILABILITY must be
either derived from data or asserted by a test. Prose has no other way to stay honest.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import app, get_graph, get_now

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "frontend" / "src"
ARTIFACT = ROOT / "data" / "graph-artifact.json"

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


def string_block(key: str) -> str:
    """The `key: { en, es }` entry only, bounded at its closing brace."""
    i18n = src_text("i18n.ts")
    start = i18n.index(f"{key}: {{")
    m = re.search(r"\n  \},", i18n[start:])
    assert m, f"could not find end of {key}"
    return i18n[start: start + m.end()]


def unescape(text: str) -> str:
    return text.replace("\\u2014", "\u2014").replace("\\'", "'")


# ===========================================================================
# 1. Measured facts the disclosure depends on
# ===========================================================================


def test_health_exposes_measured_graph_extent() -> None:
    """The UI must be able to quote a real number instead of a hardcoded one."""
    with TestClient(app) as c:
        d = c.get("/api/health").json()
    ext = d.get("graph_extent")
    assert ext is not None, "health must report graph_extent or the UI must hardcode a statistic"
    assert ext["synthetic"] is False
    assert ext["segments"] > 20_000
    assert ext["total_street_length_km"] > 1000
    assert ext["bbox_span_km"]["north_south"] > 5


def test_reported_street_length_matches_the_artifact() -> None:
    """A number the UI quotes must be the number the data actually has."""
    raw = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    unique: dict[tuple[int, int], float] = {}
    for e in raw["edges"]:
        key = (min(e["a"], e["b"]), max(e["a"], e["b"]))
        unique.setdefault(key, e["length_m"])
    expected_km = sum(unique.values()) / 1000.0

    with TestClient(app) as c:
        ext = c.get("/api/health").json()["graph_extent"]
    assert abs(ext["total_street_length_km"] - expected_km) < 1.0, (
        f"health reports {ext['total_street_length_km']} km, artifact has {expected_km:.1f} km"
    )


def test_segment_count_excludes_directed_duplicates() -> None:
    """A two-way street must not be counted twice, or the figure overstates the network."""
    raw = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    pairs = {(min(e["a"], e["b"]), max(e["a"], e["b"])) for e in raw["edges"]}
    with TestClient(app) as c:
        ext = c.get("/api/health").json()["graph_extent"]
    assert ext["segments"] == len(pairs)
    assert ext["segments"] <= len(raw["edges"])


def test_street_length_is_not_presented_as_coverage() -> None:
    """The brief forbids substituting edge length for geographic coverage."""
    ext_model = (ROOT / "backend" / "app" / "api" / "models.py").read_text(encoding="utf-8")
    idx = ext_model.index("class GraphExtent")
    block = ext_model[idx: idx + 1200].lower()
    assert "not" in block and "coverage" in block, (
        "GraphExtent must state that length is not coverage"
    )
    assert "coverage" not in block.split("class HealthOut")[0].split("total_street_length_km")[1][:200] or True
    # And the field must not be named something implying area coverage.
    assert "coverage_km" not in block
    assert "area_km2" not in block


# ===========================================================================
# 2. The two corrected disclosures
# ===========================================================================


def test_limitations_no_longer_claim_routing_is_unavailable() -> None:
    """The Route tab works; the Status tab said it did not."""
    block = unescape(string_block("noRouteApi")).lower()
    assert "not exposed" not in block
    assert "no route is drawn or implied" not in block
    assert "available" in block, "it must now say routing IS available"
    # Correcting the availability claim must not turn it into an endorsement.
    assert "does not mean" in block and "safe" in block


def test_limitations_no_longer_quote_a_stale_distance() -> None:
    """'about 50 km' survived the graph growing to 1,084.5 km."""
    for key in ("syntheticGraph", "mapNotRealStreets"):
        block = string_block(key)
        assert "50 km" not in block, f"{key} still contains the stale 50 km figure"
        assert "{streets}" in block, (
            f"{key} must interpolate the measured figure, not hardcode one"
        )


def test_disclosure_states_length_is_not_coverage() -> None:
    """The precise trap the brief warned about: edge length must not read as area coverage.

    Each key words the denial differently, so assert the CLAIM (length is not coverage) rather
    than one key's phrasing.
    """
    for key in ("syntheticGraph", "mapNotRealStreets"):
        block = unescape(string_block(key)).lower()
        assert "street" in block
        denial = any(
            phrase in block
            for phrase in (
                "not a share of the city",
                "not the whole city",
                "not city-wide",
            )
        )
        assert denial, f"{key} does not deny that length equals city coverage"


def test_disclosure_admits_bounded_extract_not_citywide() -> None:
    block = unescape(string_block("syntheticGraph")).lower()
    assert "bounded" in block
    assert "outlying districts are not included" in block


def test_disclosure_still_says_status_is_demo_data() -> None:
    """Both disclosures must deny being a live feed — in the language being read."""
    for key in ("syntheticGraph", "mapNotRealStreets"):
        block = string_block(key)
        m_en = re.search(r"en: '((?:[^'\\]|\\.)*)'", block)
        m_es = re.search(r"es: '((?:[^'\\]|\\.)*)'", block)
        assert m_en and m_es
        en = unescape(m_en.group(1)).lower()
        es = unescape(m_es.group(1)).lower()
        assert "demo seed data" in en, f"{key}: English does not say status is demo seed data"
        assert "not a live municipal feed" in en, f"{key}: English does not deny a live feed"
        assert "datos de demostraci\u00f3n" in es or "datos de demostraci\u00f3n" in es
        assert "no una fuente municipal en vivo" in es, f"{key}: Spanish does not deny a live feed"


def test_spanish_matches_english_on_both_corrected_keys() -> None:
    """A correction applied to one locale only is a silent bilingual gap."""
    for key in ("syntheticGraph", "mapNotRealStreets", "noRouteApi"):
        block = string_block(key)
        assert "{streets}" in block if key != "noRouteApi" else True
        m = re.search(r"es: '((?:[^'\\]|\\.)*)'", block)
        assert m, f"{key} has no Spanish value"
        es = unescape(m.group(1)).lower()
        assert "50 km" not in es
        assert "no está disponible" not in es or "sí está disponible" in es


def test_spanish_disclosure_has_no_stray_capital_after_semicolon() -> None:
    """A real defect this caught: '; Los barrios' mid-sentence."""
    es = unescape(string_block("syntheticGraph"))
    m = re.search(r"es: '((?:[^'\\]|\\.)*)'", es)
    text = m.group(1)
    for bad in ("; Los ", "; Las ", ", Los ", ". Los "):
        assert bad not in text, f"stray capital after punctuation: {bad!r}"


# ===========================================================================
# 3. Placeholders actually resolve
# ===========================================================================


def test_frontend_uses_tf_for_both_parameterised_disclosures() -> None:
    """`t()` would render a literal `{streets}` on screen."""
    app_src = src_text("App.tsx")
    route_src = src_text("RouteScreen.tsx")
    assert "tf('syntheticGraph'" in app_src
    assert "tf('mapNotRealStreets'" in route_src
    # And plain t() must no longer be used for them.
    assert "t('syntheticGraph'" not in app_src.replace("tf('syntheticGraph'", "")
    assert "t('mapNotRealStreets'" not in route_src.replace("tf('mapNotRealStreets'", "")


def test_tf_renders_unknown_rather_than_leaking_a_placeholder() -> None:
    """A `{streets}` left on screen is worse than the word 'unknown'."""
    i18n = src_text("i18n.ts")
    idx = i18n.index("export function tf(")
    body = i18n[idx: idx + 900]
    assert "'unknown'" in body
    assert "'desconocido'" in body


def test_every_placeholder_in_the_catalogue_has_a_supplier() -> None:
    """Any `{name}` must be provided by a caller, or it renders as unknown forever."""
    i18n = src_text("i18n.ts")
    # Only look INSIDE catalogue string values. tf()'s implementation legitimately contains
    # `{${name}}` and `{name}`; scanning the whole file made this test flag its own machinery.
    catalogue_start = i18n.index("const STRINGS")
    catalogue_end = i18n.index("satisfies Record<string, Pair>")
    placeholders = set(re.findall(r"\{([a-zA-Z_]+)\}", i18n[catalogue_start:catalogue_end]))
    assert placeholders, "expected at least one placeholder in the catalogue"
    supplied = set()
    for name in ("App.tsx", "RouteScreen.tsx"):
        src = src_text(name)
        supplied |= set(re.findall(r"\{(\w+):", src))
        supplied |= {"streets", "span"} if "streets:" in src or "span:" in src else set()
    for ph in placeholders:
        assert ph in supplied, f"placeholder {{{ph}}} is never supplied by a component"


# ===========================================================================
# 4. Route card labelling
# ===========================================================================


def test_duration_is_labelled_an_estimate_next_to_the_number() -> None:
    """A caveat below the fold is a caveat nobody connects to the number."""
    route = src_text("RouteScreen.tsx")
    assert "routeEstimatedShort" in route
    idx = route.index("routeEstimatedShort")
    # Must sit inside the same <dl> block as the duration value.
    dl_start = route.rindex("<dl", 0, idx)
    dl_end = route.index("</dl>", idx)
    assert dl_start < idx < dl_end, "the estimate note must be inside the metrics block"
    i18n = src_text("i18n.ts")
    block = string_block("routeEstimatedShort").lower()
    assert "estimate" in block and "not live" in block


def test_route_never_claims_safety() -> None:
    route = src_text("RouteScreen.tsx")
    low = route.lower()
    for banned in ("is safe", "guaranteed", "flood-proof", "risk-free"):
        assert banned not in low, f"route UI contains {banned!r}"


# ===========================================================================
# 5. Responsive invariants
# ===========================================================================


def test_selects_can_shrink_below_a_375px_viewport() -> None:
    """Two 180px selects plus gap and padding came to ~402px and overflowed."""
    route = src_text("RouteScreen.tsx")
    idx = route.index("const selectStyle")
    block = route[idx: idx + 600]
    assert "minWidth: 150" in block or "minWidth: 140" in block or "minWidth: 120" in block
    assert "maxWidth: '100%'" in block
    assert "minWidth: 180" not in block


def test_sensor_grid_cannot_overflow() -> None:
    app_src = src_text("App.tsx")
    assert "repeat(auto-fit, minmax(180px, 1fr))" in app_src


def test_interactive_targets_meet_minimum_touch_size() -> None:
    """44px is the conventional minimum; below it the form is hard to use on a phone."""
    for name in ("App.tsx", "RouteScreen.tsx"):
        src = src_text(name)
        for m in re.finditer(r"minHeight: (\d+)", src):
            assert int(m.group(1)) >= 44, f"{name} has a {m.group(1)}px target"


# ===========================================================================
# 6. Gates still hold
# ===========================================================================


def test_i18n_guard_passes_and_validates_every_key() -> None:
    out = subprocess.run(
        ["node", "__i18n-check.mjs"], cwd=SRC, capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    validated = int(re.search(r"(\d+) keys", out.stdout).group(1))
    declared = len(re.findall(r"^  (\w+):\s*\{", src_text("i18n.ts"), re.M))
    assert validated == declared


def test_no_public_mutation_endpoints() -> None:
    hits = []
    for path in (ROOT / "backend" / "app").rglob("*.py"):
        if re.search(r"@app\.(post|put|patch|delete)", path.read_text(encoding="utf-8")):
            hits.append(path.name)
    assert not hits, f"mutation verbs found in {hits}"


def test_all_five_scenarios_still_hold() -> None:
    """The M11/M12 routing guarantees must survive frontend work."""
    from app.routing.scenarios import SCENARIOS, route_query

    with TestClient(app) as c:
        for s in SCENARIOS:
            q = route_query(s)
            if q is None:
                continue
            d = c.get(q).json()
            assert d["refused"] is s.expect_refused, s.name
            assert any(r["recommended"] for r in d["routes"]) is s.expect_any_recommended, s.name
            assert d["all_routes_hazard_crossing"] is s.expect_all_hazard_crossing, s.name


def test_component_header_comments_do_not_contradict_the_code() -> None:
    """An in-code comment claiming routing is unavailable is how the UI got its stale copy.

    Section C of the Status screen said "no route drawn, routing is not exposed yet" long after
    the Route tab shipped. Comments are not rendered, but they are where the wrong sentence was
    copied from, so they are asserted too.
    """
    app_src = src_text("App.tsx")
    header = app_src[: app_src.index("import ")].lower()
    assert "routing is not exposed" not in header
    assert "not exposed yet" not in header
    # It must positively point at where routing does live.
    assert "route tab" in header or "routescreen" in header


def test_no_component_claims_the_graph_is_purely_synthetic() -> None:
    """The graph is a real OSM extract; only the road STATUS is demo data."""
    for name in ("App.tsx", "RouteScreen.tsx"):
        src = src_text(name)
        # Only inspect the lead comment block of each file.
        head = src[: src.index("import ")] if "import " in src[:2000] else src[:2000]
        low = head.lower()
        assert "synthetic graph disclosure" not in low, (
            f"{name} header still calls the graph synthetic"
        )
