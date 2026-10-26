"""M14 — seven-day forecast, INAMHI bulletin, and honest comparison tests.

WHAT THESE ARE GUARDING
  1. A missing value must stay missing. `None` is not zero, and zero rain is a meaningful claim.
  2. Time zones must stay unambiguous: the provider is asked for UTC, and the bulletin's
     Ecuador-local issue time is converted once, not guessed.
  3. Source timestamps must be reported separately from fetch time.
  4. An unavailable INAMHI must produce an honest failure with a link, never invented numbers.
  5. Non-comparable data must be REFUSED, not forced into a percentage.
  6. The words "verified"/"corroborated" must never appear in a comparison verdict.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.ingest.comparison import compare
from app.ingest.inamhi import Bulletin, RegionBands, RainfallBand, parse_bulletin_text
from app.ingest.openmeteo import DailyRain, build_forecast_url, parse_open_meteo

NOW = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)

# A real-shaped payload: two days, with one deliberately missing value.
PAYLOAD = {
    "hourly_units": {"precipitation": "mm", "precipitation_probability": "%"},
    "hourly": {
        "time": ["2026-10-26T00:00", "2026-10-26T01:00", "2026-10-26T02:00"],
        "precipitation": [0.0, 2.5, None],
        "precipitation_probability": [10, 55, None],
    },
    "daily_units": {
        "time": "iso8601",
        "precipitation_sum": "mm",
        "precipitation_probability_max": "%",
        "temperature_2m_min": "°C",
        "temperature_2m_max": "°C",
        "weather_code": "wmo code",
    },
    "daily": {
        "time": ["2026-10-26", "2026-10-27"],
        "precipitation_sum": [21.5, None],
        "precipitation_probability_max": [97, 40],
        "temperature_2m_min": [24.8, 23.9],
        "temperature_2m_max": [30.2, 31.4],
        "weather_code": [81, 3],
    },
}


def parse(payload=PAYLOAD):
    return parse_open_meteo(payload, fetched_at=NOW, latitude=-2.1962, longitude=-79.8865)


# ===========================================================================
# 1. Seven-day data
# ===========================================================================


def test_daily_series_is_parsed() -> None:
    r = parse()
    assert r.ok
    assert len(r.days) == 2
    d0 = r.days[0]
    assert d0.date == date(2026, 10, 26)
    assert d0.precipitation_sum_mm == 21.5
    assert d0.probability_max_pct == 97
    assert d0.temperature_min_c == 24.8
    assert d0.temperature_max_c == 30.2
    assert d0.weather_code == 81


def test_daily_date_is_a_date_not_an_instant() -> None:
    """A daily aggregate covers a day; turning it into a timestamp invents precision."""
    r = parse()
    assert isinstance(r.days[0].date, date)
    assert not isinstance(r.days[0].date, datetime)


def test_url_requests_daily_fields_and_seven_days() -> None:
    url = build_forecast_url(
        "https://api.open-meteo.com/v1", -2.1962, -79.8865, forecast_hours=48, forecast_days=7
    )
    for var in (
        "precipitation_sum",
        "precipitation_probability_max",
        "temperature_2m_min",
        "temperature_2m_max",
        "weather_code",
    ):
        assert var in url, f"{var} not requested"
    assert "forecast_days=7" in url
    assert "timezone=UTC" in url


def test_daily_days_parameter_is_bounded() -> None:
    with pytest.raises(ValueError):
        build_forecast_url("https://x", 0, 0, forecast_days=0)
    with pytest.raises(ValueError):
        build_forecast_url("https://x", 0, 0, forecast_days=99)


# ===========================================================================
# 2. Missing values are never invented
# ===========================================================================


def test_missing_daily_value_stays_none() -> None:
    """`None` must NOT become 0 mm — that would read as 'no rain expected'."""
    r = parse()
    d1 = r.days[1]
    assert d1.precipitation_sum_mm is None
    assert d1.precipitation_sum_mm != 0
    # Other fields on the same day still parse.
    assert d1.probability_max_pct == 40


def test_absent_daily_block_yields_no_days_and_a_note() -> None:
    payload = {k: v for k, v in PAYLOAD.items() if k not in ("daily", "daily_units")}
    r = parse(payload)
    assert r.ok, "an hourly-only response is still a valid forecast"
    assert r.days == ()
    assert any("no daily block" in n for n in r.notes)


def test_absent_daily_series_filled_with_none_not_zero() -> None:
    payload = json.loads(json.dumps(PAYLOAD))
    del payload["daily"]["precipitation_sum"]
    r = parse(payload)
    assert len(r.days) == 2
    assert all(d.precipitation_sum_mm is None for d in r.days)


def test_negative_precipitation_is_treated_as_unavailable() -> None:
    payload = json.loads(json.dumps(PAYLOAD))
    payload["daily"]["precipitation_sum"] = [-3.0, 5.0]
    r = parse(payload)
    assert r.days[0].precipitation_sum_mm is None, "negative rain is impossible; not clamped to 0"
    assert any("negative daily precipitation" in n for n in r.notes)


def test_probability_outside_range_is_unavailable() -> None:
    payload = json.loads(json.dumps(PAYLOAD))
    payload["daily"]["precipitation_probability_max"] = [140, 40]
    r = parse(payload)
    assert r.days[0].probability_max_pct is None


def test_nan_is_not_rendered_as_a_number() -> None:
    payload = json.loads(json.dumps(PAYLOAD))
    payload["daily"]["precipitation_sum"] = [float("nan"), None]
    r = parse(payload)
    assert r.days[0].precipitation_sum_mm is None


def test_length_mismatch_is_reported_and_does_not_misalign() -> None:
    """Zipping a short series against 2 dates would put values on the wrong days."""
    payload = json.loads(json.dumps(PAYLOAD))
    payload["daily"]["precipitation_sum"] = [21.5]  # one value, two dates
    r = parse(payload)
    assert any("has 1 values for 2 dates" in n for n in r.notes)
    assert r.days[0].precipitation_sum_mm == 21.5, "the value stays on the day it belongs to"
    assert r.days[1].precipitation_sum_mm is None


def test_wrong_precipitation_unit_aborts_rather_than_assuming() -> None:
    payload = json.loads(json.dumps(PAYLOAD))
    payload["daily_units"]["precipitation_sum"] = "inches"
    with pytest.raises(Exception) as ei:
        parse(payload)
    assert "unit" in str(ei.value).lower()


# ===========================================================================
# 3. Time zones and source timestamps
# ===========================================================================


def test_hourly_timestamps_carry_utc() -> None:
    r = parse()
    for h in r.hours:
        assert h.at.tzinfo is not None, "a naive timestamp would be interpreted as local time"


def test_provider_is_asked_for_utc() -> None:
    assert "timezone=UTC" in build_forecast_url("https://x", 0, 0)


def test_model_run_time_stays_null_and_fetch_time_is_separate() -> None:
    """N-1: Open-Meteo gives no model run time. It must never be inferred from fetch time."""
    r = parse()
    assert r.model_run_at is None
    assert r.fetched_at == NOW
    assert r.model_run_at != r.fetched_at
    assert any("no model run time" in n for n in r.notes)


# ===========================================================================
# 4. INAMHI bulletin parsing
# ===========================================================================

BULLETIN_TEXT = """
Boletín Meteorológico Nro. 83
Estatus: ADVERTENCIA
Fecha y hora de emisión: domingo, 25 de octubre de 2026, 14:00 horas
Vigencia: desde 16H00 del 25 hasta las 23H00 del 28 de octubre de 2026
NIVEL AMENAZA: MEDIO – MUY ALTO
FENÓMENO: LLUVIAS, TORMENTAS ELÉCTRICAS
Precipitación acumulada diaria (mm/24h)
   REGIÓN          Nivel Medio    Nivel Alto      Muy Alto
   Litoral          10 – 18       19 – 41        42 – 100
   Interandina          8 – 11       12 – 30            -
ZONAS AFECTADAS
 • Región Litoral: Mayor intensidad en Guayas.
¿QUÉ PUEDE PASAR?
 • Es probable que se produzca acumulación de agua en hogares.
"""


def test_bulletin_fields_extracted() -> None:
    b = parse_bulletin_text(BULLETIN_TEXT, source_url="https://x/a.pdf", fetched_at=NOW)
    assert b.ok
    assert b.bulletin_number == "83"
    assert b.status == "ADVERTENCIA"
    assert b.threat_level == "MEDIO – MUY ALTO"


def test_bulletin_issue_time_converted_from_ecuador_local() -> None:
    """The bulletin states 14:00 local (UTC-5), so 19:00 UTC. Not 14:00 UTC."""
    b = parse_bulletin_text(BULLETIN_TEXT, source_url="https://x/a.pdf", fetched_at=NOW)
    assert b.issued_at is not None
    assert b.issued_at == datetime(2026, 10, 25, 19, 0, tzinfo=timezone.utc)


def test_bulletin_validity_window_parsed() -> None:
    b = parse_bulletin_text(BULLETIN_TEXT, source_url="https://x/a.pdf", fetched_at=NOW)
    assert b.valid_from == datetime(2026, 10, 25, 21, 0, tzinfo=timezone.utc)  # 16:00 local
    assert b.valid_until == datetime(2026, 10, 29, 4, 0, tzinfo=timezone.utc)   # 23:00 local


def test_bulletin_bands_extracted_as_ranges() -> None:
    b = parse_bulletin_text(BULLETIN_TEXT, source_url="https://x/a.pdf", fetched_at=NOW)
    lit = b.bands_for("Litoral")
    assert lit is not None
    levels = {x.level: (x.low_mm, x.high_mm) for x in lit.bands}
    assert levels["Medio"] == (10.0, 18.0)
    assert levels["Alto"] == (19.0, 41.0)
    assert levels["Muy Alto"] == (42.0, 100.0)
    assert b.is_quantitative is True


def test_qualitative_bulletin_reports_no_numbers() -> None:
    """A bulletin with no numeric table must not yield invented bands."""
    text = "Boletín Meteorológico Nro. 90\nEstatus: ALERTA\nNIVEL AMENAZA: ALTO\n"
    b = parse_bulletin_text(text, source_url="https://x/a.pdf", fetched_at=NOW)
    assert b.ok
    assert b.regions == ()
    assert b.is_quantitative is False
    assert any("qualitative" in w or "no numeric" in w for w in b.warnings)


def test_unparseable_issue_time_is_reported_not_guessed() -> None:
    text = "Boletín Meteorológico Nro. 1\nFecha y hora de emisión: cuando sea\n"
    b = parse_bulletin_text(text, source_url="https://x", fetched_at=NOW)
    assert b.issued_at is None
    assert any("issue time could not be parsed" in w for w in b.warnings)


def test_missing_bulletin_number_is_reported() -> None:
    b = parse_bulletin_text("Estatus: ADVERTENCIA\n", source_url="https://x", fetched_at=NOW)
    assert b.bulletin_number is None
    assert any("bulletin number not found" in w for w in b.warnings)


# ===========================================================================
# 5. INAMHI unavailability
# ===========================================================================


def test_unreachable_bulletin_gives_an_honest_failure() -> None:
    from app.ingest.inamhi import fetch_bulletin

    b = fetch_bulletin(now=NOW, http_get=lambda url, t: (0, b"", None))
    assert b.ok is False
    assert b.error is not None and "unreachable" in b.error
    assert b.source_url, "the official link must survive a failure so the user can read it"
    assert b.bulletin_number is None
    assert b.regions == ()


def test_http_error_bulletin_is_reported() -> None:
    from app.ingest.inamhi import fetch_bulletin

    b = fetch_bulletin(now=NOW, http_get=lambda url, t: (503, b"", None))
    assert b.ok is False
    assert "503" in (b.error or "")


def test_non_pdf_response_is_refused_not_parsed() -> None:
    """A maintenance page returning HTML must not be parsed as a bulletin."""
    from app.ingest.inamhi import fetch_bulletin

    b = fetch_bulletin(now=NOW, http_get=lambda url, t: (200, b"<html>maintenance</html>", None))
    assert b.ok is False
    assert "not a PDF" in (b.error or "")


def test_oversized_pdf_is_refused() -> None:
    from app.ingest.inamhi import fetch_bulletin

    b = fetch_bulletin(now=NOW, http_get=lambda url, t: (413, b"", None))
    assert b.ok is False
    assert "size limit" in (b.error or "")


# ===========================================================================
# 6. Comparison honesty
# ===========================================================================


def _bulletin(with_bands: bool = True) -> Bulletin:
    regions: tuple[RegionBands, ...] = ()
    if with_bands:
        regions = (
            RegionBands(
                region="Litoral",
                bands=(
                    RainfallBand(level="Medio", low_mm=10, high_mm=18),
                    RainfallBand(level="Alto", low_mm=19, high_mm=41),
                ),
            ),
        )
    return Bulletin(
        ok=True,
        source_url="https://www.inamhi.gob.ec/pronostico/advertencia.pdf",
        bulletin_number="83",
        issued_at=datetime(2026, 10, 25, 19, tzinfo=timezone.utc),
        valid_from=datetime(2026, 10, 25, 21, tzinfo=timezone.utc),
        valid_until=datetime(2026, 10, 29, 4, tzinfo=timezone.utc),
        regions=regions,
    )


def _days(vals: list[float | None]) -> tuple[DailyRain, ...]:
    return tuple(
        DailyRain(
            date=date(2026, 10, 26) + timedelta(days=i),
            precipitation_sum_mm=v,
            probability_max_pct=None,
            temperature_min_c=None,
            temperature_max_c=None,
            weather_code=None,
        )
        for i, v in enumerate(vals)
    )


def test_inside_a_band_is_reported_as_consistency_not_agreement() -> None:
    c = compare(_days([21.5]), _bulletin())
    assert c.comparable is True
    assert c.days[0].matching_bands[0].level == "Alto"
    joined = " ".join(c.explanation_en.lower().split())
    assert "consistency" in joined
    assert "not agreement" in joined or "nothing more" in joined or "not a cross-verification" in joined


def test_outside_every_band_is_not_a_contradiction() -> None:
    c = compare(_days([3.0]), _bulletin())
    assert c.comparable is True
    assert c.days[0].matching_bands == ()
    assert "not contradiction" in c.explanation_en.lower()


def test_comparison_never_claims_verification() -> None:
    """The single most important assertion in this file."""
    c = compare(_days([21.5, 14.9]), _bulletin())
    corpus = " ".join(
        [c.explanation_en, c.explanation_es, *c.disclaimers_en, *c.disclaimers_es, *c.notes]
    ).lower()
    for banned in ("cross-verification", "cross verification"):
        # Allowed ONLY inside an explicit denial.
        idx = corpus.find(banned)
        while idx != -1:
            window = corpus[max(0, idx - 40): idx + len(banned) + 10]
            assert "not" in window or "no es" in window, f"unqualified use of {banned!r}: {window}"
            idx = corpus.find(banned, idx + 1)
    for banned in ("corroborated", "confirmed by", "sources agree", "validated"):
        assert banned not in corpus, f"comparison claims {banned!r}"


def test_no_percentage_difference_is_computed() -> None:
    """A point versus a regional band has no meaningful arithmetic difference."""
    c = compare(_days([21.5]), _bulletin())
    corpus = " ".join(c.notes).lower()
    assert "no percentage difference" in corpus
    assert "%" not in c.explanation_en.replace("100", "")


def test_disclaimers_present_in_both_languages() -> None:
    c = compare(_days([21.5]), _bulletin())
    assert len(c.disclaimers_en) >= 3
    assert len(c.disclaimers_es) >= 3
    assert any("NOT a cross-verification" in d for d in c.disclaimers_en)
    assert any("NO es una verificación" in d for d in c.disclaimers_es)


def test_missing_bulletin_refuses_comparison() -> None:
    c = compare(_days([21.5]), None)
    assert c.comparable is False
    assert c.reason == "no_bulletin"
    assert "official link" in c.explanation_en.lower()


def test_qualitative_bulletin_refuses_comparison() -> None:
    c = compare(_days([21.5]), _bulletin(with_bands=False))
    assert c.comparable is False
    assert c.reason == "no_numeric_bands"


def test_unknown_region_refuses_comparison() -> None:
    c = compare(_days([21.5]), _bulletin(), region="Patagonia")
    assert c.comparable is False
    assert c.reason == "unknown_region"


def test_no_forecast_days_refuses_comparison() -> None:
    c = compare((), _bulletin())
    assert c.comparable is False
    assert c.reason == "no_overlapping_day"


def test_missing_forecast_value_on_a_day_is_not_compared() -> None:
    """A day with no model value must not be treated as 0 mm inside the lowest band."""
    c = compare(_days([None]), _bulletin())
    assert c.days[0].forecast_available is False
    assert c.days[0].matching_bands == ()


def test_refusal_also_carries_the_disclaimers() -> None:
    """A refusal must still explain the comparison would not have been a verification."""
    c = compare(_days([21.5]), None)
    assert len(c.disclaimers_en) >= 3
