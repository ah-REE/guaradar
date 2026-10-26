"""Admin panel (read-only prototype) — honesty constraints.

The Admin panel is the easiest place in this project to accidentally lie, because an empty panel
looks broken and an invented one looks finished. These tests pin the choice: it states what is
missing rather than filling the gap.

What they assert:
  * it makes no claim that a write succeeded, and cannot (no mutation endpoint exists);
  * it does not fake authentication or a role check;
  * every unavailable feature is labelled unavailable, with a reason;
  * the road-status figures it DOES show are derived from real API legs and labelled a sample;
  * unknown is never counted as open or as verified coverage;
  * it is fully bilingual.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "frontend" / "src"


def src_text(name: str) -> str:
    p = SRC / name
    assert p.exists(), f"missing {p}"
    return p.read_text(encoding="utf-8")


def string_block(key: str) -> str:
    i18n = src_text("i18n.ts")
    start = i18n.index(f"{key}: {{")
    m = re.search(r"\n  \},", i18n[start:])
    assert m, f"could not find end of {key}"
    return i18n[start: start + m.end()]


def unescape(text: str) -> str:
    return text.replace("\\u2014", "\u2014").replace("\\'", "'")


# ===========================================================================
# 1. It cannot pretend to write
# ===========================================================================


def test_no_mutation_endpoint_exists_to_call() -> None:
    """The premise of the whole panel: there is nothing to POST to."""
    hits = []
    for path in (ROOT / "backend" / "app").rglob("*.py"):
        if re.search(r"@app\.(post|put|patch|delete)", path.read_text(encoding="utf-8")):
            hits.append(path.name)
    assert not hits, f"mutation endpoints exist in {hits} — the panel's disabled states would lie"


def test_admin_screen_issues_no_write_request() -> None:
    """It must only ever GET. A fetch with method POST would be a fake save."""
    admin = src_text("AdminScreen.tsx")
    for verb in ("method: 'POST'", 'method: "POST"', "method: 'PUT'", "method: 'PATCH'",
                 "method: 'DELETE'"):
        assert verb not in admin
    # And it must not use the route API for anything but reading.
    assert "fetchRoute(" in admin


def test_no_success_toast_or_saved_message() -> None:
    """A 'Saved' message on a read-only panel is the single worst thing it could say."""
    admin = src_text("AdminScreen.tsx").lower()
    for phrase in ("saved successfully", "changes saved", "published successfully",
                   "guardado correctamente", "cambios guardados"):
        assert phrase not in admin


def test_every_write_action_is_disabled_and_explained() -> None:
    """Disabled controls must carry their reason in visible text, not a tooltip."""
    admin = src_text("AdminScreen.tsx")
    assert "disabled" in admin
    assert "aria-describedby={`${a.id}-reason`}" in admin
    data = src_text("adminData.ts")
    # The four approved Stage 2 write actions.
    for action in ("publish_alert", "verify_incident", "set_road_status", "manage_users"):
        assert action in data, f"{action} missing from the disabled-action register"


def test_disabled_actions_have_bilingual_reasons() -> None:
    data = src_text("adminData.ts")
    for field in ("reasonEn", "reasonEs", "labelEn", "labelEs"):
        assert data.count(f"{field}:") >= 4, f"{field} must be supplied per action"


# ===========================================================================
# 2. It does not fake authentication
# ===========================================================================


def test_no_fake_login_or_role_switcher() -> None:
    """N-2 is open; a role selector would imply access control that does not exist."""
    admin = src_text("AdminScreen.tsx")
    low = admin.lower()
    for fake in ("isloggedin", "signin", "login(", "role === 'admin'", "currentuser",
                 "localstorage.setitem('role" ):
        assert fake not in low, f"suggests a real auth model: {fake}"


def test_panel_states_it_is_an_unauthorised_prototype() -> None:
    """The banner must be present, prominent and not dismissible."""
    admin = src_text("AdminScreen.tsx")
    assert "tr('adminPrototype')" in admin
    # role=alert so it is announced, and there must be NO dismiss handler.
    assert 'role="alert"' in admin
    banner = admin[admin.index("adminPrototype"): admin.index("adminPrototype") + 900]
    for dismissive in ("onClick", "setDismissed", "onClose", "×"):
        assert dismissive not in banner, "the prototype banner must not be dismissible"


def test_prototype_copy_says_nothing_can_change_public_data() -> None:
    en = unescape(string_block("adminPrototypeBody")).lower()
    assert "no write action is available" in en
    assert "nothing here can change public data" in en
    assert "not implemented" in en
    # Must not claim to be an operational console.
    assert "do not treat this screen as an operational console" in en


# ===========================================================================
# 3. Missing features are labelled, not invented
# ===========================================================================


@pytest.mark.parametrize("key", ["adminIncidentsEmpty", "adminAlertsEmpty", "adminSheltersEmpty"])
def test_missing_feature_states_what_is_missing(key: str) -> None:
    en = unescape(string_block(key)).lower()
    assert "no" in en
    # Each must explain absence in terms of a real missing component, not vague hedging.
    assert any(w in en for w in ("table", "endpoint", "register", "channel"))


def test_shelter_copy_refuses_to_invent_locations() -> None:
    """Shelter availability is life-safety information; simulating it is not acceptable."""
    en = unescape(string_block("adminSheltersEmpty")).lower()
    assert "cannot be simulated" in en
    assert "empty" in en


def test_unavailable_chip_is_used_for_absent_sources() -> None:
    admin = src_text("AdminScreen.tsx")
    assert admin.count("adminNotAvailable") >= 4


# ===========================================================================
# 4. What it does show is honestly sourced
# ===========================================================================


def test_road_status_is_labelled_a_sample_not_a_census() -> None:
    en = unescape(string_block("adminRoadStatusExplain")).lower()
    assert "sample" in en
    assert "not the whole network" in en
    # And it must say the network is bigger than what was sampled.
    assert "24,943" in en


def test_sample_size_is_displayed() -> None:
    admin = src_text("AdminScreen.tsx")
    assert "adminSampleSize" in admin
    assert "adminRoutesSampled" in admin


def test_unknown_is_never_counted_as_open() -> None:
    """The core data-integrity rule, asserted in the derivation and stated in the UI."""
    data = src_text("adminData.ts")
    idx = data.index("export function deriveStatusSample")
    body = data[idx: idx + 1400]
    # Unrecognised values fall to unknown, and unknown is its own bucket.
    assert "tally.unknown += 1" in body
    en = unescape(string_block("adminUnknownNote")).lower()
    assert "never counted as open" in en
    assert "lowers the verified share" in en


def test_status_source_is_shown_verbatim_from_the_api() -> None:
    """The panel must not upgrade 'seed_generator' to something friendlier."""
    admin = src_text("AdminScreen.tsx")
    assert "sample.statusSource" in admin
    assert "adminStatusSource" in admin


def test_verified_share_comes_from_leg_verified_flags() -> None:
    data = src_text("adminData.ts")
    assert "if (leg.verified) verified += 1" in data


# ===========================================================================
# 5. Bilingual and navigable
# ===========================================================================


def test_admin_strings_complete_in_both_locales() -> None:
    i18n = src_text("i18n.ts")
    admin_keys = re.findall(r"^  (admin\w+):\s*\{", i18n, re.M)
    assert len(admin_keys) >= 20, f"expected a full admin string set, found {len(admin_keys)}"
    entry = re.compile(
        r"(\w+):\s*\{\s*en:\s*'((?:[^'\\]|\\.)*)'\s*,\s*es:\s*'((?:[^'\\]|\\.)*)'\s*,?\s*\}",
        re.S,
    )
    parsed = {m.group(1): (m.group(2), m.group(3)) for m in entry.finditer(i18n)}
    for k in admin_keys:
        assert k in parsed, f"{k} is not a bilingual pair"
        en, es = parsed[k]
        assert en.strip() and es.strip(), f"{k} has an empty locale"


def test_admin_tab_is_reachable_from_navigation() -> None:
    app = src_text("App.tsx")
    assert "'status', 'route', 'admin'" in app, "the admin tab must be in the nav map"
    assert "AdminScreen" in app
    assert "TAB_LABEL" in app


def test_admin_is_wrapped_in_the_error_boundary() -> None:
    """One panel crashing must not blank the whole console."""
    app = src_text("App.tsx")
    idx = app.index("tab === 'admin'")
    block = app[idx: idx + 300]
    assert "ErrorBoundary" in block, "the admin screen must be isolated by an ErrorBoundary"
    assert 'section="Admin"' in block


def test_admin_panel_makes_no_safety_claims() -> None:
    """Neither the panel nor its data may imply a road is safe."""
    combined = src_text("AdminScreen.tsx") + src_text("adminData.ts") + string_block("adminRoadStatusExplain")
    low = unescape(combined).lower()
    for banned in ("is safe", "guaranteed", "flood-proof", "risk-free", "always passable",
                   "ruta segura"):
        assert banned not in low, f"admin panel makes a safety claim: {banned}"
