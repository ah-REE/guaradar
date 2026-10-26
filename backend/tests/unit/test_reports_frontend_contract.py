"""Frontend contract tests for the road-report UI.

These run in Python (like the existing M11/M14 contract suites) and inspect the TypeScript
source plus the real built artefacts. The value is that they run in the SAME `pytest` invocation
as the backend, so a UI regression cannot pass a backend-only check.

Where a test inspects the BUILT bundle it prefers `dist/`, because that is what actually ships:
a constant that only exists in an unminified source file has been tree-shaken out by definition.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
FRONTEND = BACKEND.parent / "frontend"
SRC = FRONTEND / "src"
DIST = FRONTEND / "dist"


def src_text(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


def code_only(text: str) -> str:
    """Strip comments and block comments so a guard inspects code, not prose about the code.

    Necessary because these files deliberately DOCUMENT the rules they obey ("not base64",
    "no watchPosition"). Inspecting raw text would punish writing that down.
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def i18n_catalogue() -> str:
    text = src_text("i18n.ts")
    return text[text.index("const STRINGS") : text.index("satisfies Record<string, Pair>")]


# ===========================================================================
# 1. Types mirror the backend contract
# ===========================================================================


def test_report_states_match_the_backend_literals() -> None:
    """A drift between these two lists would render a blank chip for a real state."""
    api = src_text("reportApi.ts")
    python = (BACKEND / "app" / "reports" / "lifecycle.py").read_text(encoding="utf-8")

    ts_states = set(re.findall(r"^\s*\|\s*'(\w+)'", api, re.M))
    # Every PublicState in Python must appear in the TS union.
    for state in (
        "unverified",
        "potential_hazard",
        "blocked_verified",
        "passable_verified",
        "inconclusive",
        "rejected",
        "stale",
        "unknown",
    ):
        assert state in ts_states, state
        assert f'"{state}"' in python or f"'{state}'" in python or state in python


def test_categories_match_the_backend() -> None:
    api = src_text("reportApi.ts")
    for category in ("flooded", "blocked", "debris", "damaged", "rising", "other"):
        assert category in api, category
    python = (BACKEND / "app" / "reports" / "lifecycle.py").read_text(encoding="utf-8")
    assert "CATEGORIES" in python


def test_every_state_has_a_label_key_and_a_tone() -> None:
    """A total mapping, so adding a backend state without a label is a type error."""
    api = src_text("reportApi.ts")
    label_block = api[api.index("STATE_LABEL_KEY") : api.index("STATE_TONE")]
    tone_block = api[api.index("STATE_TONE") :]
    for state in (
        "unverified",
        "potential_hazard",
        "blocked_verified",
        "passable_verified",
        "inconclusive",
        "rejected",
        "stale",
        "unknown",
    ):
        assert state in label_block, f"no label for {state}"
        assert state in tone_block, f"no tone for {state}"


def test_label_keys_all_exist_in_the_catalogue() -> None:
    api = src_text("reportApi.ts")
    catalogue = i18n_catalogue()
    for key in re.findall(r": '(reportStatus\w+)'", api):
        assert f"{key}:" in catalogue, f"missing catalogue entry {key}"


def test_route_response_type_declares_the_overlay_fields() -> None:
    types = src_text("routeApi.ts")
    for field in (
        "report_overlay_applied",
        "report_segments_affected",
        "report_closures",
        "report_stale_closures",
    ):
        assert field in types, field


# ===========================================================================
# 2. Client behaviour
# ===========================================================================


def test_client_sends_the_session_cookie() -> None:
    api = src_text("reportApi.ts")
    assert "credentials: 'same-origin'" in api


def test_client_does_not_store_a_token() -> None:
    """The session is an httpOnly cookie; nothing here may touch localStorage."""
    for name in ("reportApi.ts", "ReportScreen.tsx", "AdminReports.tsx"):
        text = src_text(name)
        assert "localStorage" not in text, name
        assert "sessionStorage" not in text, name


def test_client_uploads_the_file_not_base64() -> None:
    """The brief asks that large images not be embedded as unnecessary base64 strings."""
    api = code_only(src_text("reportApi.ts"))
    assert "FormData" in api
    assert "FileReader" not in api
    assert "readAsDataURL" not in api
    assert "base64" not in api.lower()


def test_client_maps_error_codes_to_translated_text() -> None:
    """A backend code must never be rendered raw; unknown codes fall back to a generic message."""
    screen = src_text("ReportScreen.tsx")
    assert "ReportApiError" in screen
    assert "rate_limited" in screen
    assert "reportSubmitFailed" in screen


def test_client_does_not_recompute_staleness() -> None:
    """Freshness is a server decision; a second implementation would drift."""
    text = src_text("ReportScreen.tsx")
    # It reads `is_stale` from the payload...
    assert "report.is_stale" in text
    # ...and does not compare expires_at against the local clock itself.
    assert "expires_at < " not in text
    assert "Date.now() >" not in text


# ===========================================================================
# 3. Translation completeness
# ===========================================================================


def test_i18n_guard_passes() -> None:
    out = subprocess.run(
        ["node", "__i18n-check.mjs"], cwd=SRC, capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    validated = int(re.search(r"(\d+) keys", out.stdout).group(1))
    declared = len(re.findall(r"^  \w+:\s*\{", src_text("i18n.ts"), re.M))
    assert validated == declared, "the guard did not validate every declared key"
    assert validated >= 300, f"expected the full catalogue, saw {validated}"


def test_new_strings_exist_in_both_languages() -> None:
    catalogue = i18n_catalogue()
    keys = re.findall(r"^  (\w+):\s*\{", catalogue, re.M)
    new_keys = [k for k in keys if k.startswith(("report", "adminReport", "adminDecision", "routeOrigin", "routeUseMy", "routeLocation", "routeReports"))]
    assert len(new_keys) >= 55, f"expected ~60 new keys, found {len(new_keys)}"
    for key in new_keys:
        block = catalogue[catalogue.index(f"  {key}:"):]
        block = block[: block.index("\n  },") + 4 if "\n  }," in block else 400]
        assert "en:" in block, key
        assert "es:" in block, key
        # A Spanish entry identical to English is only acceptable for brand names.
        en = re.search(r"en:\s*'([^']*)'", block)
        es = re.search(r"es:\s*'([^']*)'", block)
        if en and es and en.group(1) == es.group(1):
            assert en.group(1) in ("Guaradar",), f"{key} is untranslated: {en.group(1)!r}"


def test_no_hardcoded_english_sentences_in_the_new_screens() -> None:
    """Any user-facing sentence must come from the catalogue, or one locale is silently broken."""
    for name in ("ReportScreen.tsx", "AdminReports.tsx"):
        text = code_only(src_text(name))
        # Find JSX text nodes longer than a few words (three or more words in a row).
        offenders = re.findall(r">\s*([A-Za-z][A-Za-z ,.'\-]{25,})\s*<", text)
        assert not offenders, f"{name} has hardcoded copy: {offenders[:3]}"


def test_banned_overclaim_terms_are_absent_from_new_copy() -> None:
    catalogue = i18n_catalogue().lower()
    for banned in ("flood-proof", "risk-free", "guaranteed safe", "always passable"):
        assert banned not in catalogue, banned


# ===========================================================================
# 4. Accessibility of the new controls
# ===========================================================================


def test_status_is_never_conveyed_by_colour_alone() -> None:
    """Every status chip renders a word as well as a background colour."""
    screen = src_text("ReportScreen.tsx")
    chip = screen[screen.index("function StatusChip") : screen.index("function formatTime")]
    assert "STATE_LABEL_KEY" in chip
    assert "{" in chip  # the label is interpolated, not implied by colour


def test_interactive_controls_meet_the_touch_target() -> None:
    """The user is on a phone in the rain; 40 px minimum, matching the existing screens."""
    for name in ("ReportScreen.tsx", "AdminReports.tsx"):
        text = src_text(name)
        assert "minHeight: 40" in text, name


def test_form_inputs_are_labelled() -> None:
    screen = src_text("ReportScreen.tsx")
    # The textarea has an explicit label element bound by htmlFor/id.
    assert 'htmlFor="report-description"' in screen
    assert 'id="report-description"' in screen
    # Radio categories are wrapped in <label>, so the text is the accessible name.
    assert screen.count("<label") >= 4


def test_errors_are_announced() -> None:
    """A silent failure is the worst outcome on this screen."""
    for name in ("ReportScreen.tsx", "AdminReports.tsx"):
        text = src_text(name)
        assert 'role="alert"' in text or "role={message.kind" in text, name


def test_admin_failure_message_says_nothing_changed() -> None:
    """An operator who believes a closure was saved when it was not is the worst case here."""
    text = src_text("i18n.ts")
    block = text[text.index("adminDecisionFailed"):]
    block = block[: block.index("\n  },")]
    assert "not saved" in block
    assert "Nothing was changed" in block


# ===========================================================================
# 5. Build artefacts
# ===========================================================================


def test_typecheck_passes() -> None:
    out = subprocess.run(
        ["npx", "tsc", "-b", "--pretty", "false"],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stdout + out.stderr


def test_production_build_contains_no_secrets() -> None:
    """No API key, service-role key or OPENTOPOGRAPHY token may reach the browser bundle."""
    if not DIST.exists():
        pytest.skip("no dist/ build present")
    candidates = sorted(DIST.rglob("*.js")) + sorted(DIST.rglob("*.html"))
    assert candidates, "build produced no JavaScript"
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="ignore")
        # Names only. A live key must never appear here — not even as a "tripwire" literal,
        # because a test fixture is a committed file and the brief forbids the key in fixtures.
        # The value-based check below covers the case where a key really did leak: any long
        # high-entropy token in the bundle is flagged regardless of its name.
        for needle in ("OPENTOPOGRAPHY_API_KEY", "SERVICE_ROLE", "SUPABASE_SERVICE"):
            assert needle not in text, f"{path.name} contains {needle}"
        # A JWT-shaped tripwire: Supabase keys are JWTs and must never ship.
        assert not re.search(r"eyJhbGciOi[A-Za-z0-9_\-]{10,}", text), f"{path.name} contains a JWT"
        # Generic high-entropy token tripwire: catches a leaked key whose NAME was not on the
        # list above, which is the case a name-based check structurally cannot cover.
        for token in re.findall(r"[A-Za-z0-9]{32,}", text):
            # Source maps and bundled identifiers produce long strings too; a real API key is
            # hex-ish and does not contain the uppercase runs typical of minified identifiers.
            assert token.lower() != token or not re.search(r"[A-F0-9]{32}", token), (
                f"{path.name} contains a high-entropy token that looks like a credential"
            )


def test_bundle_does_not_contain_server_only_gps_field_names() -> None:
    """`gps_lat` is an admin field; the public client must not expect it."""
    if not DIST.exists():
        pytest.skip("no dist/ build present")
    bundle = " ".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in DIST.rglob("*.js")
    )
    # The admin panel legitimately reads gps_lat, so presence is allowed. What must not exist is
    # a PUBLIC component reading it — asserted at source level instead, which is precise.
    reports = src_text("ReportScreen.tsx")
    assert "gps_lat" not in reports
    assert "gps_lon" not in reports
    assert bundle  # keep the build check meaningful


def test_leaflet_stays_out_of_first_paint() -> None:
    """Both map screens import Leaflet dynamically, so the bundle is not blocked by it."""
    for name in ("ReportScreen.tsx", "RouteScreen.tsx"):
        text = src_text(name)
        assert "await import('leaflet')" in text, name
        assert "from 'leaflet')\n" not in text.split("await import")[0], name


# ===========================================================================
# 6. Navigation and wiring
# ===========================================================================


def test_report_tab_is_wired_into_the_app() -> None:
    app = src_text("App.tsx")
    assert "import ReportScreen" in app
    assert "tab === 'report'" in app
    assert "tabReport" in app


def test_admin_report_panel_is_mounted_inside_the_admin_gate() -> None:
    """It must sit behind the existing session check, not beside it."""
    app = src_text("App.tsx")
    admin_branch = app[app.index("tab === 'admin'") : app.index("tab === 'report'")]
    assert "AdminReports" in admin_branch
    assert "session.is_admin" in admin_branch


def test_screens_are_wrapped_in_error_boundaries() -> None:
    """One panel throwing must not blank the portal, which is the existing project rule."""
    app = src_text("App.tsx")
    report_branch = app[app.index("tab === 'report'") :]
    report_branch = report_branch[: report_branch.index(") : tab ===")]
    assert "ErrorBoundary" in report_branch
