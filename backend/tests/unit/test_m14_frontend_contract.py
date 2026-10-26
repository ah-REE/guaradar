"""M14 — frontend contract for the seven-day forecast and INAMHI panels.

The UI is React and there is no browser here (N-5), so these assert the CONTRACT and the
DISCLOSURE DISCIPLINE rather than pixels:

  * the chart renders missing values as unavailable, never as zero;
  * no percentage difference is displayed anywhere;
  * the words that would imply verification are absent from the shipped strings;
  * dates are rendered in Guayaquil time / as calendar dates, avoiding the off-by-one;
  * the safety notes about rainfall-not-flooding are present.
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


def i18n() -> str:
    return src_text("i18n.ts")



def code_only(name: str) -> str:
    """Source with comments and docstrings removed.

    BulletinPanel.tsx's header comment QUOTES the forbidden phrases in order to forbid them
    ("not as 'agrees with'"). Scanning raw text flags the guard itself — the same mistake that
    made the M12 i18n scanner fail on its own explanatory comment. Prose is stripped first.
    """
    src = src_text(name)
    # Block comments, then line comments, then JSX {/* */} blocks.
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"\{/\*.*?\*/\}", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def catalogue_region() -> str:
    """Only the STRINGS object, so tf()'s own machinery is not scanned as prose."""
    s = i18n()
    return s[s.index("const STRINGS") : s.index("satisfies Record<string, Pair>")]


# ===========================================================================
# 1. Missing values are not zeroes
# ===========================================================================


def test_chart_draws_missing_values_as_unavailable_not_zero() -> None:
    """A zero-height bar reads as 'no rain' — a confident and possibly false claim."""
    week = src_text("ForecastWeek.tsx")
    # The null branch must exist and must not compute a height from null.
    assert "if (v === null || v < 0)" in week
    assert "t('dayUnavailable', locale)" in week
    # And the value must never be coerced with `|| 0`.
    assert "v || 0" not in week
    assert "?? 0" not in week


def test_daily_card_renders_unavailable_text_not_a_number() -> None:
    week = src_text("ForecastWeek.tsx")
    assert "rainTxt === null ? tr('dayUnavailable')" in week
    assert "probTxt === null ? tr('dayUnavailable')" in week
    assert "tmin === null || tmax === null" in week


def test_no_chart_rendered_when_all_values_missing() -> None:
    """Rather than an axis with no bars, say there is nothing to plot."""
    week = src_text("ForecastWeek.tsx")
    assert "anyValue" in week
    assert week.count("chartNoData") >= 2


def test_frontend_never_fills_missing_daily_values() -> None:
    for name in ("ForecastWeek.tsx", "BulletinPanel.tsx"):
        src = code_only(name)
        for pattern in ("parseFloat('0", '|| "0"', "?? 0.0", "Math.max(0,"):
            assert pattern not in src, f"{name} appears to coerce a missing value: {pattern}"


# ===========================================================================
# 2. No invented comparison arithmetic
# ===========================================================================


def test_no_percentage_difference_is_displayed() -> None:
    """A point forecast versus a regional band has no meaningful arithmetic difference."""
    panel = code_only("BulletinPanel.tsx")
    # No subtraction of model from bulletin, no division.
    assert "forecast_mm - " not in panel
    assert "low_mm - " not in panel
    assert "difference" not in panel.lower() or "no percentage difference" in panel.lower()


def test_comparison_shows_inside_band_language_only() -> None:
    panel = code_only("BulletinPanel.tsx")
    assert "comparisonInside" in panel
    assert "comparisonOutside" in panel
    # Must not claim agreement.
    low = panel.lower()
    for banned in ("agrees with", "corroborat", "cross-verified", "confirmed by"):
        assert banned not in low, f"BulletinPanel claims {banned!r}"


def test_caveats_are_rendered_verbatim_from_the_api() -> None:
    """Summarising a caveat turns it into a caveat that no longer constrains reading."""
    panel = src_text("BulletinPanel.tsx")
    assert "c.disclaimers_en" in panel and "c.disclaimers_es" in panel
    assert "caveats.map" in panel
    # And they render even when the comparison is refused.
    assert "{caveats.length > 0 &&" in panel


def test_caveats_rendered_on_a_refusal_too() -> None:
    panel = src_text("BulletinPanel.tsx")
    idx = panel.index("{!c.comparable &&")
    idx2 = panel.index("{caveats.length > 0 &&")
    assert idx < idx2, "caveats must not sit inside the comparable-only branch"


# ===========================================================================
# 3. No verification vocabulary in shipped strings
# ===========================================================================


@pytest.mark.parametrize(
    "banned",
    ["cross-verified", "corroborated", "validated against", "sources agree", "confirmed by inamhi"],
)
def test_catalogue_has_no_verification_vocabulary(banned: str) -> None:
    low = catalogue_region().lower()
    assert banned not in low, f"shipped copy claims {banned!r}"


def test_the_only_cross_verification_mention_is_a_denial() -> None:
    low = catalogue_region().lower()
    idx = low.find("cross-verification")
    if idx != -1:
        window = low[max(0, idx - 30) : idx + 40]
        assert "not a" in window or "no es una" in window, window


# ===========================================================================
# 4. Dates and time zones
# ===========================================================================


def test_calendar_dates_avoid_the_utc_off_by_one() -> None:
    """`new Date('2026-10-26')` is UTC midnight; in UTC-5 that renders as the 25th."""
    week = src_text("ForecastWeek.tsx")
    assert "Date.UTC(y, (m ?? 1) - 1, d ?? 1)" in week, (
        "daily dates must be constructed from parts with an explicit UTC basis"
    )
    assert "timeZone: 'UTC'" in week, "a calendar date must be formatted in UTC to stay aligned"
    # The naive form would reintroduce the bug.
    assert "new Date(iso)" not in week.split("function dayLabel")[1][:600]


def test_hourly_labels_use_guayaquil_time() -> None:
    week = src_text("ForecastWeek.tsx")
    assert "America/Guayaquil" in week


def test_bulletin_times_use_guayaquil_time() -> None:
    panel = src_text("BulletinPanel.tsx")
    assert "America/Guayaquil" in panel


def test_time_formatting_cannot_throw_during_render() -> None:
    """An exception here blanked a whole tab once; the formatter must degrade instead."""
    panel = src_text("BulletinPanel.tsx")
    idx = panel.index("function guayaquil(")
    body = panel[idx : idx + 700]
    assert "try {" in body and "} catch" in body
    assert "Number.isNaN" in body


def test_no_illegal_intl_option_combination_in_new_files() -> None:
    """`dateStyle`/`timeStyle` may not be combined with `timeZoneName`; it throws."""
    for name in ("ForecastWeek.tsx", "BulletinPanel.tsx"):
        src = re.sub(r"/\*.*?\*/", "", src_text(name), flags=re.S)
        src = re.sub(r"//[^\n]*", "", src)
        for m in re.finditer(r"toLocaleString\s*\([^)]*?(\{[^{}]*\})", src, re.S):
            opts = m.group(1)
            if ("dateStyle" in opts or "timeStyle" in opts) and "timeZoneName" in opts:
                raise AssertionError(f"{name}: illegal Intl option combination {opts[:90]}")


# ===========================================================================
# 5. Safety disclosures
# ===========================================================================


def test_rainfall_is_not_presented_as_flood_prediction() -> None:
    low = catalogue_region().lower()
    assert "rainfall is not a flood prediction" in low
    assert "la lluvia no es una predicción de inundación" in low


def test_no_flood_risk_score_from_rainfall() -> None:
    low = catalogue_region().lower()
    assert "no flood-risk score" in low
    assert "ninguna puntuación de riesgo" in low


def test_safety_notes_are_rendered_before_the_numbers() -> None:
    app = src_text("App.tsx")
    i_note = app.index("<ForecastSafetyNotes")
    i_forecast = app.index("<ForecastSection")
    assert i_note < i_forecast, "the safety note must precede the figures"


def test_bulletin_panel_links_to_the_official_source() -> None:
    panel = src_text("BulletinPanel.tsx")
    assert "b.source_url" in panel
    assert 'rel="noopener noreferrer"' in panel
    assert 'target="_blank"' in panel


def test_bulletin_failure_shows_the_link_and_no_values() -> None:
    panel = src_text("BulletinPanel.tsx")
    idx = panel.index("if (unavailable)")
    block = panel[idx : idx + 1400]
    assert "bulletinUnavailable" in block
    assert "bulletinOpenOfficial" in block
    # No table or numbers in the failure branch.
    assert "<table" not in block


def test_bulletin_qualitative_case_is_stated_not_faked() -> None:
    panel = src_text("BulletinPanel.tsx")
    assert "bulletinQualitative" in panel
    # The qualitative branch must not render a bands table.
    idx = panel.index("b.regions.length > 0 ?")
    alt = panel[idx : idx + 2600]
    assert "bulletinQualitative" in alt
    low = catalogue_region().lower()
    assert "no numeric rainfall table" in low


# ===========================================================================
# 6. Caching transparency
# ===========================================================================


def test_cache_state_is_visible_to_the_user() -> None:
    panel = src_text("BulletinPanel.tsx")
    assert "b.cached" in panel
    assert "bulletinCached" in panel
    assert "cache_age_s" in panel


def test_cache_ttl_is_defined_in_the_backend() -> None:
    routes = (ROOT / "backend" / "app" / "api" / "bulletin_routes.py").read_text(encoding="utf-8")
    assert "BULLETIN_CACHE_TTL_S" in routes
    assert "FAILURE_CACHE_TTL_S" in routes
    # A failure must be cached for less time than a success, or an outage pins the error.
    assert "FAILURE_CACHE_TTL_S = 60" in routes
