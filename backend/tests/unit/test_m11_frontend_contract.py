"""M11 regression tests — the Status-tab fix must not come back.

These test the CONTRACT THE UI DEPENDS ON, not the UI itself (no browser is available here).
Three classes of bug caused the blank page, and each gets a guard:

  1. `toLocaleString` with `dateStyle`/`timeStyle` **and** `timeZoneName` throws
     `TypeError: Invalid option` in V8. That exception during render unmounted React and blanked
     the page. → assert the payload carries parseable ISO timestamps AND that the frontend
     formatter's option set is legal.
  2. Timestamps must be rendered in Guayaquil time, not the viewer's. → assert the frontend
     pins `America/Guayaquil`.
  3. `.toFixed()` on `null` throws; `latest` is null for an offline sensor. → assert the payload
     can legitimately contain nulls and that the frontend has a null-safe formatter.

The frontend source is inspected as text. That is deliberately crude, but it catches the exact
regressions that mattered, and it needs no browser or JS runtime harness.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "src"


def read_frontend(name: str) -> str:
    p = FRONTEND / name
    assert p.exists(), f"missing frontend file {p}"
    return p.read_text(encoding="utf-8")


def node_available() -> bool:
    import shutil

    return shutil.which("node") is not None


# ===========================================================================
# 1. The illegal Intl option combination must not return
# ===========================================================================


def test_frontend_never_combines_style_options_with_timezonename() -> None:
    """The exact bug: `dateStyle`/`timeStyle` may not be combined with `timeZoneName`.

    V8 raises `TypeError: Invalid option : option`, which during render blanks the page.
    Scans every frontend source file for a single call site containing both kinds of option.
    """
    offenders: list[str] = []
    for path in sorted(FRONTEND.glob("*.ts*")):
        src = path.read_text(encoding="utf-8")
        # Strip block and line comments first: the fix's own docstring deliberately QUOTES the
        # illegal combination while explaining it, and that must not count as a violation.
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        src = re.sub(r"^\s*//.*$", "", src, flags=re.M)
        src = re.sub(r"//[^\n]*", "", src)

        # A call's option object contains no nested braces in this codebase, so `[^{}]*` is a
        # safe single-object match and cannot run across statements.
        for match in re.finditer(
            r"(?:toLocaleString|DateTimeFormat)\s*\((?:[^(){}]|\{[^{}]*\})*?(\{[^{}]*\})",
            src,
            re.S,
        ):
            opts = match.group(1)
            has_style = "dateStyle" in opts or "timeStyle" in opts
            has_component = "timeZoneName" in opts
            if has_style and has_component:
                offenders.append(f"{path.name}: {opts[:120]}")
    assert not offenders, (
        "illegal Intl option combination reintroduced (throws at render time, blanks the page):\n"
        + "\n".join(offenders)
    )


def test_frontend_pins_guayaquil_timezone() -> None:
    """Timestamps must render in the app's city timezone, not the viewer's."""
    src = read_frontend("App.tsx")
    assert "America/Guayaquil" in src, (
        "App.tsx must pin the timezone; without it timestamps render in the viewer's zone "
        "(e.g. IST) which is wrong for a Guayaquil app"
    )
    assert "APP_TIMEZONE" in src


def test_stamp_is_wrapped_against_throw() -> None:
    """A formatter must degrade, never throw: an exception here blanks the page."""
    src = read_frontend("App.tsx")
    # Locate the stamp function body and confirm both a try and a catch are present.
    idx = src.find("function stamp(")
    assert idx != -1, "stamp() not found"
    body = src[idx: idx + 2500]
    assert "try {" in body, "stamp() must guard its formatting"
    assert "} catch" in body, "stamp() must have a catch fallback"


def test_frontend_has_null_safe_number_formatter() -> None:
    """`.toFixed()` on null throws; the UI must route numbers through a guard."""
    src = read_frontend("App.tsx")
    assert "function num(" in src, "a null-safe numeric formatter must exist"
    # The sensor card must use it rather than calling toFixed on possibly-null values.
    assert "num(s.latest.depth_m" in src
    assert "s.latest.depth_m.toFixed(" not in src, (
        "direct .toFixed() on a nullable field would throw when a sensor is offline"
    )


def test_num_formatter_semantics_documented() -> None:
    """A missing number must render as unavailable, never as a fabricated zero."""
    src = read_frontend("App.tsx")
    idx = src.find("function num(")
    body = src[idx: idx + 600]
    assert "'—'" in body or '"—"' in body, "missing values must render as an em dash"
    assert "toFixed" in body


def test_error_boundary_exists_and_is_wired() -> None:
    """One section's render error must not blank the whole app."""
    boundary = read_frontend("ErrorBoundary.tsx")
    assert "getDerivedStateFromError" in boundary
    assert "componentDidCatch" in boundary
    # Bilingual, per the brief.
    assert "could not be displayed" in boundary
    assert "no se pudo mostrar" in boundary

    app_src = read_frontend("App.tsx")
    assert "import ErrorBoundary" in app_src
    # Each section must be wrapped.
    assert app_src.count("<ErrorBoundary") >= 3, (
        "forecast, sensors and route sections should each be wrapped"
    )


def test_error_boundary_does_not_fabricate_values() -> None:
    """The boundary must report the failure, not substitute estimates."""
    boundary = read_frontend("ErrorBoundary.tsx")
    low = boundary.lower()
    assert "no estimated values" in low
    assert "0 mm" not in low and "0%" not in low


# ===========================================================================
# 2. The API must keep supplying what the UI formatting needs
# ===========================================================================


def test_forecast_timestamps_are_parseable_iso() -> None:
    """Every timestamp the UI formats must round-trip through Date parsing."""
    from fastapi.testclient import TestClient

    from app.api.main import app, get_now

    app.dependency_overrides[get_now] = lambda: datetime(2026, 10, 26, 14, tzinfo=timezone.utc)
    try:
        with TestClient(app) as c:
            d = c.get("/api/public/forecast?hours=6").json()
    finally:
        app.dependency_overrides.clear()

    assert d["provenance"]["fetched_at"], "the UI needs a fetch timestamp"
    for key in ("fetched_at",):
        dt = datetime.fromisoformat(d["provenance"][key].replace("Z", "+00:00"))
        assert dt.tzinfo is not None, f"{key} must carry an offset or the UI guesses"
    for h in d["hours"]:
        dt = datetime.fromisoformat(h["at"].replace("Z", "+00:00"))
        assert dt.tzinfo is not None


def test_model_run_at_is_null_so_the_ui_shows_unavailable() -> None:
    """The UI branches on this being null; if it were fabricated the branch would never run."""
    from fastapi.testclient import TestClient

    from app.api.main import app, get_now

    app.dependency_overrides[get_now] = lambda: datetime(2026, 10, 26, 14, tzinfo=timezone.utc)
    try:
        with TestClient(app) as c:
            d = c.get("/api/public/forecast?hours=3").json()
    finally:
        app.dependency_overrides.clear()
    assert d["provenance"]["sources"][0]["model_run_at"] is None


def test_sensor_payload_can_legitimately_contain_null_latest() -> None:
    """The offline-sensor shape must be representable, because the UI must handle it."""
    from app.api.models import SensorOut

    # Constructing with latest=None must be legal — this is the shape that crashed the UI.
    s = SensorOut(
        sensor_id="SIM-99",
        sector_id="norte",
        profile="steady",
        lat=-2.19,
        lon=-2.21,
        threshold_m=1.0,
        health="offline",
        last_reading_age_s=None,
        latest=None,
    )
    assert s.latest is None
    payload = json.loads(s.model_dump_json())
    assert payload["latest"] is None
    assert payload["label"] == "SIMULATED"


def test_health_disclosure_still_matches_graph_source() -> None:
    """Regression for the M11 pre-work fix: the note must not claim 'synthetic' when it is OSM."""
    from fastapi.testclient import TestClient

    from app.api.main import app, get_graph, get_now

    app.dependency_overrides[get_now] = lambda: datetime(2026, 10, 26, 14, tzinfo=timezone.utc)
    try:
        with TestClient(app) as c:
            notes = " ".join(c.get("/api/health").json()["notes"]).lower()
    finally:
        app.dependency_overrides.clear()

    if get_graph().synthetic:
        assert "synthetic" in notes
    else:
        assert "openstreetmap" in notes or "osm" in notes
        assert "road graph is synthetic" not in notes


# ===========================================================================
# 3. The working route form must not regress
# ===========================================================================


def test_route_form_demo_points_all_snap() -> None:
    """All six route-form points must remain routable, or the form shows confusing refusals."""
    from app.api.main import get_graph
    from app.routing.scenarios import DEMO_POINTS
    from app.routing.search import MAX_SNAP_DISTANCE_M

    graph = get_graph()
    for name, (lat, lon) in DEMO_POINTS.items():
        _nid, dist = graph.nearest_node(lat, lon)
        assert dist <= MAX_SNAP_DISTANCE_M, (
            f"{name} is {dist:.1f} m from a node, beyond the {MAX_SNAP_DISTANCE_M:.0f} m limit"
        )


def test_frontend_demo_points_match_backend() -> None:
    """The frontend's DEMO_POINTS must be the same coordinates the backend uses.

    Three mistakes were made in earlier versions of this test, all worth recording:
      1. `rf"...[^}}]..."` in an f-string: `}}` becomes a literal `}`, so the character class
         silently never matched anything.
      2. Formatting the expected value with `:.4f` and string-matching it: -2.227579 rounds to
         -2.2276 while the file says -2.2275, so a CORRECT coordinate failed the test.
      3. Editing by text replacement that silently did not apply, then trusting it.
    Capturing the literal and comparing parsed floats with a tolerance avoids 1 and 2.
    """
    src = read_frontend("RouteScreen.tsx")
    from app.routing.scenarios import DEMO_POINTS

    for name, (lat, _lon) in DEMO_POINTS.items():
        pattern = r"id: '" + re.escape(name) + r"'[^}]*lat: (-?\d+\.\d+)"
        m = re.search(pattern, src)
        assert m, f"{name} not found in RouteScreen.tsx DEMO_POINTS"
        assert abs(float(m.group(1)) - lat) < 1e-3, (
            f"{name} latitude drifted: frontend {m.group(1)} vs backend {lat}"
        )


def test_route_endpoint_default_profile_is_baseline() -> None:
    """Omitting the profile must keep the pre-existing behaviour."""
    from fastapi.testclient import TestClient

    from app.api.main import app, get_now
    from app.routing.scenarios import DEMO_POINTS

    la, lo = DEMO_POINTS["SIM-01"]
    lb, lbo = DEMO_POINTS["SIM-04"]
    app.dependency_overrides[get_now] = lambda: datetime(2026, 10, 26, 14, tzinfo=timezone.utc)
    try:
        with TestClient(app) as c:
            d = c.get(
                f"/api/public/route?from_lat={la}&from_lon={lo}&to_lat={lb}&to_lon={lbo}"
            ).json()
    finally:
        app.dependency_overrides.clear()
    assert d["status_profile"] == "baseline"
    assert d["profile_is_demo_fixture"] is False
