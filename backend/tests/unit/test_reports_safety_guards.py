"""Safety and privacy guards for the road-report feature.

These are the tests that should FAIL LOUDLY if someone later makes the feature more convenient
by weakening it. Each one encodes a sentence from the brief, quoted in the test, so a future
reviewer can see what constraint they are about to break.

They are deliberately cheap: mostly source-text and route-table assertions with no I/O. That
makes them run on every commit, which is the only way a guard against future regressions stays
useful.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
SRC = BACKEND.parent / "frontend" / "src"
APP = BACKEND / "app"


def src_text(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


def py_text(rel: str) -> str:
    return (APP / rel).read_text(encoding="utf-8")

def code_only(text: str) -> str:
    """Remove comments and docstrings so a guard inspects CODE, not the notes about the code.

    This distinction matters more than it looks. A file that documents "we never say the road is
    confirmed safe" must not fail a check for the string "confirmed safe". The first version of
    these guards did exactly that, which is a test that punishes writing the comment that explains
    the rule.
    """
    # Triple-quoted blocks (docstrings and long comments).
    text = re.sub(r'""" .*? """', " ", text, flags=re.S)
    text = re.sub(r'""".*?"""', " ", text, flags=re.S)
    # Line comments in Python and in JS/TS, plus JS block comments.
    text = re.sub(r"#.*", " ", text)
    text = re.sub(r"//.*", " ", text)
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return text


def string_values(text: str) -> list[str]:
    """The quoted string literals in a file, in order.

    Used where the question is "what might be DISPLAYED", which is a question about literals,
    not about identifiers or comments.
    """
    return re.findall(r"""['"]([^'"\n]{2,400})['"]""", text)



# ===========================================================================
# 1. No report path can call a road safe
# ===========================================================================


def test_backend_report_code_never_claims_safety() -> None:
    """The permitted vocabulary is "no known hazards" / "unknown". Never "safe"."""
    text = (
        code_only(py_text("api/report_routes.py")) + code_only(py_text("reports/lifecycle.py"))
    ).lower()
    for banned in ("is safe", "are safe", "road is clear", "confirmed safe", "flood-free"):
        assert banned not in text, banned


def test_frontend_report_code_never_claims_safety() -> None:
    for name in ("ReportScreen.tsx", "AdminReports.tsx", "reportApi.ts"):
        text = code_only(src_text(name)).lower()
        for banned in ("is safe", "are safe", "safe route", "road is clear", "flood-free"):
            assert banned not in text, f"{name}: {banned}"


def test_translated_report_strings_contain_no_safety_overclaim() -> None:
    """Checked in both languages, because a claim is a claim in either locale.

    Only the DISPLAYED values are inspected. The catalogue also contains the `BANNED_TERMS`
    guard list, which exists precisely to name these phrases; inspecting identifiers and that
    list would make the guard fail on its own vocabulary.
    """
    text = src_text("i18n.ts")
    catalogue = text[text.index("const STRINGS") : text.index("satisfies Record<string, Pair>")]
    joined = " ".join(string_values(catalogue)).lower()
    for banned in ("flood-proof", "risk-free", "guaranteed safe", "always passable"):
        assert banned not in joined, banned
    # Spanish equivalents of the same overclaims.
    for banned in ("a prueba de inundaciones", "libre de riesgo", "siempre transitable"):
        assert banned not in joined, banned


# ===========================================================================
# 2. A photograph cannot close a road
# ===========================================================================


def test_only_an_operator_decision_can_produce_a_closure() -> None:
    """No submitter-reachable code path may write `blocked_verified`."""
    text = py_text("api/report_routes.py")
    # The insert statement hardcodes 'unverified'; cite it so the guarantee is visible.
    assert "'unverified'" in text
    # `blocked_verified` appears only in the admin decision Literal and the documentation.
    creation = text[text.index("def create_report") : text.index("def list_reports")]
    assert "blocked_verified" not in creation


def test_lifecycle_maps_unverified_to_caution_only() -> None:
    text = py_text("reports/lifecycle.py")
    # The unverified branch must return `affected` (or `unknown` when stale), never `closed`.
    assert 'return "affected" if not self.is_stale(now) else "unknown"' in text


# ===========================================================================
# 3. Staleness cannot be a stored status
# ===========================================================================


def test_no_stale_column_or_stored_stale_status_exists() -> None:
    """Requirement D.3 is a schema property here, not a coding convention."""
    store_text = py_text("store.py")
    # The `decision` CHECK must not admit 'stale'.
    decision_check = re.search(
        r"decision\s+text not null default 'unverified' check \(decision in \(([^)]*)\)",
        store_text,
        re.S,
    )
    assert decision_check is not None, "could not find the decision CHECK constraint"
    allowed = decision_check.group(1)
    assert "stale" not in allowed, "a stored 'stale' status would let a timer rewrite decisions"


def test_no_update_rewrites_a_decision_on_a_timer() -> None:
    """Nothing in the codebase may flip a decision because time passed."""
    text = py_text("reports/repository.py")
    for statement in re.findall(r"update road_reports.*?(?=\"\"\"|$)", text, re.S):
        # The only permitted decision write is the admin decision path, which sets it explicitly
        # from an operator payload.
        assert "set decision" not in statement or "decided_by" in statement


def test_staleness_is_derived_from_expiry() -> None:
    text = py_text("reports/lifecycle.py")
    assert "def is_stale" in text
    assert "now > self.expires_at" in text


# ===========================================================================
# 4. Privacy of position and identity
# ===========================================================================


def test_public_projection_omits_private_columns() -> None:
    """The public model must be an allow-list, not `dict(row)` minus keys."""
    text = py_text("api/report_routes.py")
    public_model = text[text.index("class PublicReportOut") : text.index("class ReportListOut")]
    for private in ("gps_lat", "gps_lon", "user_id", "decided_by"):
        assert private not in public_model, f"{private} must not appear in the public model"


def test_admin_model_is_the_only_place_raw_gps_is_exposed() -> None:
    text = py_text("api/report_routes.py")
    occurrences = text.count("gps_lat: float")
    assert occurrences == 1, "raw latitude must be declared exactly once, on AdminReportOut"
    admin_model = text[text.index("class AdminReportOut") : text.index("class DecisionIn")]
    assert "gps_lat" in admin_model and "gps_lon" in admin_model


def test_public_queries_filter_on_the_published_coordinate() -> None:
    """A bbox over the PRIVATE coordinate would be an oracle for where someone stood."""
    text = py_text("reports/repository.py")
    query = text[text.index("def query_reports") : text.index("def fetch_claims")]
    assert "public_lat" in query
    assert "gps_lat" not in query


# ===========================================================================
# 5. Authorisation is server-side and cannot be requested
# ===========================================================================


def test_every_report_mutation_requires_a_session() -> None:
    """No report mutation may be reachable anonymously."""
    text = py_text("api/report_routes.py")
    # Split on route decorators and check each POST block names a dependency.
    blocks = re.split(r"@(?:public_router|admin_reports_router)\.", text)[1:]
    checked = 0
    for block in blocks:
        header = block.split("def ", 1)[0]
        if not header.strip().startswith("post("):
            continue
        checked += 1
        assert "Depends(" in block.split("def ", 1)[1][:400], (
            f"a POST handler has no dependency: {header[:80]}"
        )
    assert checked >= 3, f"expected several mutations, found {checked}"


def test_admin_routes_use_the_role_dependency() -> None:
    text = py_text("api/report_routes.py")
    assert "require_admin(" in text
    # And no admin handler is registered without one.
    for block in re.split(r"@admin_reports_router\.", text)[1:]:
        assert "Depends(_admin" in block.split("def ", 1)[1][:400]


def test_request_models_forbid_extra_fields() -> None:
    """A payload cannot carry a `role`, `decision` or `user_id` it was not offered."""
    text = py_text("api/report_routes.py")
    for model in ("DecisionIn", "ConfirmationIn"):
        block = text[text.index(f"class {model}") :]
        block = block[: block.index("\n\n\n")] if "\n\n\n" in block else block
        assert 'extra": "forbid"' in block.replace("'", '"'), model


def test_no_request_model_declares_a_role_field() -> None:
    # A pydantic FIELD would look like `name: type` at the start of a line inside a class.
    # Mentioning the word "role" in a docstring is not a field, so declarations are matched
    # precisely and comments are stripped first.
    text = code_only(py_text("api/report_routes.py"))
    assert not re.search(r"^\s+role\s*:", text, re.M), "a request model declares a role field"
    assert not re.search(r"^\s+is_admin\s*:", text, re.M)


def test_self_registration_still_cannot_choose_a_role() -> None:
    """Feature C: "Preserve the existing CLI/bootstrap-only admin creation safeguards"."""
    text = py_text("api/auth_routes.py")
    register_model = code_only(text[text.index("class RegisterIn") : text.index("class LoginIn")])
    # No `role` FIELD. The model does forbid extra inputs, and the docstring explains why —
    # which is a comment, so it is stripped rather than counted as a violation.
    assert not re.search(r"^\s+role\s*:", register_model, re.M)
    assert 'extra": "forbid"' in register_model.replace("'", '"')
    register_handler = text[text.index("def register(") : text.index("def login(")]
    assert 'role="public"' in register_handler


# ===========================================================================
# 6. Upload safety
# ===========================================================================


def test_image_pipeline_re_encodes_from_pixels() -> None:
    """Metadata is stripped by construction, not by deleting known blocks."""
    text = py_text("reports/images.py")
    assert 'format="JPEG"' in text
    # Passing `exif=` would copy metadata into the output; it must not appear in a save call.
    save_calls = re.findall(r"\.save\([^)]*\)", text)
    assert save_calls
    for call in save_calls:
        assert "exif=" not in call, f"save call copies metadata: {call}"


def test_image_formats_are_an_allow_list() -> None:
    text = py_text("reports/images.py")
    assert 'ALLOWED_FORMATS: tuple[str, ...] = ("JPEG", "PNG", "WEBP")' in text


def test_upload_size_is_checked_before_decoding() -> None:
    text = py_text("reports/images.py")
    process = text[text.index("def process_image") :]
    size_check_pos = process.index("validate_size(")
    decode_pos = process.index("Image.open(")
    assert size_check_pos < decode_pos


def test_served_images_carry_hardening_headers() -> None:
    text = py_text("api/report_routes.py")
    for header in ("X-Content-Type-Options", "Content-Security-Policy", "Cache-Control"):
        assert header in text, header


def test_client_filename_is_never_stored() -> None:
    """A user-supplied filename is a path-traversal and header-injection surface."""
    text = py_text("api/report_routes.py")
    creation = text[text.index("def create_report") : text.index("def list_reports")]
    assert "image.filename" not in creation
    assert "uuid" in py_text("reports/repository.py")


# ===========================================================================
# 7. Honest degradation
# ===========================================================================


def test_missing_report_store_does_not_break_routing() -> None:
    text = py_text("api/report_routes.py")
    overlay = text[text.index("def build_report_overlay") :]
    assert "except repo.ReportStoreError" in overlay
    # And it must SAY the reports were not considered, rather than silently omitting them.
    assert "were NOT considered" in overlay


def test_terrain_is_not_claimed_anywhere() -> None:
    """Feature F/G are out of scope; nothing may imply terrain risk is active."""
    text = py_text("api/report_routes.py") + py_text("api/main.py")
    assert "terrain_risk" not in text.lower()
    assert "OPENTOPOGRAPHY" not in text


# ===========================================================================
# 8. Frontend guards
# ===========================================================================


def test_geolocation_is_only_requested_on_a_user_action() -> None:
    """No mount-time or effect-time geolocation: the brief forbids background tracking."""
    for name in ("ReportScreen.tsx", "RouteScreen.tsx"):
        text = src_text(name)
        code = code_only(text)
        calls = code.count("getCurrentPosition")
        assert calls >= 1, f"{name} should offer a location action"
        # `watchPosition` is continuous tracking. The COMMENTS explain that it is deliberately
        # absent, so only code is checked — otherwise the guard forbids documenting the rule.
        assert "watchPosition" not in code, f"{name} must not track continuously"


def test_geolocation_call_sits_inside_a_handler_not_an_effect() -> None:
    text = src_text("ReportScreen.tsx")
    # The call must be inside a function named for the click action.
    assert "const useMyLocation = () => {" in text
    handler_at = text.index("const useMyLocation")
    call_at = text.index("getCurrentPosition")
    # And must not be inside any useEffect body: every effect starts before the handler.
    for m in re.finditer(r"useEffect\(", text):
        assert m.start() < handler_at or m.start() > call_at + 400, "geolocation inside an effect"


def test_camera_capture_has_a_file_picker_fallback() -> None:
    """`capture` is honoured by phones and ignored elsewhere; a second input is the fallback."""
    text = src_text("ReportScreen.tsx")
    assert 'capture="environment"' in text
    # Two inputs: one with capture, one without.
    assert text.count('type="file"') >= 2
    assert 'accept="image/*"' in text


def test_report_screen_labels_unverified_reports() -> None:
    text = src_text("ReportScreen.tsx")
    assert "STATE_LABEL_KEY" in text
    # The chip is rendered from the server's state, never recomputed from a timestamp here.
    assert "is_stale" in text


def test_admin_panel_does_not_decide_authorisation_client_side() -> None:
    """Gating is a convenience; the comment must say so, or the next reader will trust it."""
    text = src_text("AdminReports.tsx")
    assert "server-side" in text.lower()
    assert "not a control" in text.lower() or "not a security control" in text.lower()


def test_report_tab_is_reachable() -> None:
    app = src_text("App.tsx")
    assert "'report'" in app
    assert "ReportScreen" in app
    assert "tabReport" in app


def test_new_ui_text_is_translated_in_both_locales() -> None:
    """Every report string must exist in English and Spanish (project language rule D22)."""
    i18n = src_text("i18n.ts")
    keys = re.findall(r"^  (\w+):\s*\{\s*\n?\s*en:", i18n, re.M)
    report_keys = [k for k in keys if k.startswith(("report", "adminReport", "adminDecision"))]
    assert len(report_keys) >= 50, f"expected the full report catalogue, found {len(report_keys)}"
    for key in report_keys:
        block = i18n[i18n.index(f"  {key}:") :]
        block = block[: block.index("  },") if "  }," in block else 400]
        assert "en:" in block and "es:" in block, key
