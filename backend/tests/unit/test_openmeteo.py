"""Tests for the Open-Meteo ingestion adapter.

All tests are offline: `http_get` is injected, so no network is required or attempted.
The single live smoke test is opt-in via an environment variable and is skipped by default.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.ingest.openmeteo import (
    ForecastError,
    ForecastResult,
    build_forecast_url,
    describe,
    fetch_forecast,
    parse_open_meteo,
)

NOW = datetime(2026, 10, 26, 14, 0, 0, tzinfo=timezone.utc)


def payload(
    times: list[str] | None = None,
    precip: list[float | None] | None = None,
    prob: list[float | None] | None = None,
    unit: str | None = "mm",
) -> dict:
    # Use `is None` rather than truthiness: an EMPTY list is a meaningful input here
    # (it is how the "no hourly values" case is expressed).
    if times is None:
        times = ["2026-10-26T14:00", "2026-10-26T15:00", "2026-10-26T16:00"]
    if precip is None:
        precip = [1.2, 4.5, 0.0]
    if prob is None:
        prob = [80, 95, 40]
    body: dict = {
        "latitude": -2.17,
        "longitude": -79.92,
        "hourly": {"time": times, "precipitation": precip,
                   "precipitation_probability": prob},
        "hourly_units": {"precipitation_probability": "%"},
    }
    if unit is not None:
        body["hourly_units"]["precipitation"] = unit
    return body


def fake_get(status: int, body: str):
    def _get(url: str, timeout_s: float) -> tuple[int, str]:
        _get.last_url = url           # type: ignore[attr-defined]
        return status, body
    return _get


def fetch(status: int = 200, body: str | dict | None = None) -> ForecastResult:
    if body is None:
        body = json.dumps(payload())
    elif isinstance(body, dict):
        body = json.dumps(body)
    return fetch_forecast(
        base_url="https://api.open-meteo.com/v1",
        latitude=-2.17,
        longitude=-79.92,
        now=NOW,
        http_get=fake_get(status, body),
    )


# ===========================================================================
# Normal case
# ===========================================================================


def test_parse_normal_payload() -> None:
    result = parse_open_meteo(payload(), fetched_at=NOW, latitude=-2.17, longitude=-79.92)
    assert result.ok is True
    assert len(result.hours) == 3
    assert result.hours[0].precipitation_mm == pytest.approx(1.2)
    assert result.hours[1].probability_pct == pytest.approx(95.0)
    assert result.total_mm == pytest.approx(5.7)
    assert result.max_hourly_mm == pytest.approx(4.5)
    assert result.provider_units_original == "mm"
    assert result.source == "open-meteo"


def test_every_value_is_labelled_forecast() -> None:
    """R-04: nothing from a forecast endpoint may claim to be an observation."""
    result = parse_open_meteo(payload(), fetched_at=NOW, latitude=-2.17, longitude=-79.92)
    assert {h.kind for h in result.hours} == {"forecast"}


def test_timestamps_are_utc_aware() -> None:
    result = parse_open_meteo(payload(), fetched_at=NOW, latitude=-2.17, longitude=-79.92)
    for h in result.hours:
        assert h.at.tzinfo is not None
        assert h.at.utcoffset() == timedelta(0)


def test_model_run_time_is_absent_and_declared() -> None:
    """We must not imply we know the model vintage when the provider omits it."""
    result = parse_open_meteo(payload(), fetched_at=NOW, latitude=-2.17, longitude=-79.92)
    assert result.model_run_at is None
    assert any("no model run time" in n for n in result.notes)


def test_age_is_fetch_age_not_model_age() -> None:
    result = parse_open_meteo(payload(), fetched_at=NOW, latitude=-2.17, longitude=-79.92)
    assert result.age_seconds(NOW) == 0.0
    assert result.age_seconds(NOW + timedelta(minutes=10)) == pytest.approx(600.0)


# ===========================================================================
# Unit handling — the one place conversion happens
# ===========================================================================


def test_inch_unit_is_converted_and_recorded() -> None:
    body = payload(precip=[0.1, 0.2, 0.0], unit="inch")
    result = parse_open_meteo(body, fetched_at=NOW, latitude=-2.17, longitude=-79.92)
    assert result.hours[0].precipitation_mm == pytest.approx(2.54)
    assert result.hours[1].precipitation_mm == pytest.approx(5.08)
    assert result.provider_units_original == "inch"
    assert any("unit converted" in n for n in result.notes)


def test_missing_unit_is_an_error_not_a_guess() -> None:
    """Displaying a mislabelled quantity is worse than displaying nothing."""
    body = payload(unit=None)
    with pytest.raises(ForecastError, match="unit missing"):
        parse_open_meteo(body, fetched_at=NOW, latitude=-2.17, longitude=-79.92)


def test_unknown_unit_is_an_error() -> None:
    with pytest.raises(ForecastError, match="unsupported precipitation unit"):
        parse_open_meteo(payload(unit="cm"), fetched_at=NOW, latitude=-2.17, longitude=-79.92)


# ===========================================================================
# Missing and implausible values
# ===========================================================================


def test_nulls_are_preserved_as_gaps() -> None:
    body = payload(precip=[1.0, None, 2.0], prob=[50, None, 60])
    result = parse_open_meteo(body, fetched_at=NOW, latitude=-2.17, longitude=-79.92)
    assert result.hours[1].precipitation_mm is None
    assert result.hours[1].probability_pct is None
    # A gap must not be silently counted as zero in the total.
    assert result.total_mm == pytest.approx(3.0)


def test_negative_precipitation_dropped_as_missing() -> None:
    body = payload(precip=[-1.0, 2.0, 0.0])
    result = parse_open_meteo(body, fetched_at=NOW, latitude=-2.17, longitude=-79.92)
    assert result.hours[0].precipitation_mm is None
    assert any("implausible" in n for n in result.notes)


def test_absurd_precipitation_dropped() -> None:
    body = payload(precip=[9999.0, 1.0, 0.0])
    result = parse_open_meteo(body, fetched_at=NOW, latitude=-2.17, longitude=-79.92)
    assert result.hours[0].precipitation_mm is None


def test_out_of_range_probability_dropped() -> None:
    body = payload(prob=[120, -5, 50])
    result = parse_open_meteo(body, fetched_at=NOW, latitude=-2.17, longitude=-79.92)
    assert result.hours[0].probability_pct is None
    assert result.hours[1].probability_pct is None
    assert result.hours[2].probability_pct == pytest.approx(50.0)


# ===========================================================================
# Empty / malformed / error responses
# ===========================================================================


def test_empty_time_array_raises() -> None:
    with pytest.raises(ForecastError, match="time missing or empty"):
        parse_open_meteo(
            payload(times=[], precip=[], prob=[]),
            fetched_at=NOW, latitude=-2.17, longitude=-79.92,
        )


@pytest.mark.parametrize(
    "body,reason",
    [
        ({"error": True, "reason": "Latitude must be in range"}, "provider reported an error"),
        ({"hourly": {}}, "time missing or empty"),
        ({"hourly": {"time": ["2026-10-26T14:00"]}}, "neither precipitation nor probability"),
        ({"latitude": 1}, "no 'hourly' object"),
    ],
)
def test_malformed_payloads_raise(body: dict, reason: str) -> None:
    with pytest.raises(ForecastError, match=reason):
        parse_open_meteo(body, fetched_at=NOW, latitude=-2.17, longitude=-79.92)


def test_length_mismatch_raises() -> None:
    body = payload(times=["2026-10-26T14:00", "2026-10-26T15:00"], precip=[1.0], prob=[10, 20])
    with pytest.raises(ForecastError, match="length mismatch"):
        parse_open_meteo(body, fetched_at=NOW, latitude=-2.17, longitude=-79.92)


def test_unparseable_timestamp_raises() -> None:
    body = payload(times=["not-a-time"], precip=[1.0], prob=[10])
    with pytest.raises(ForecastError, match="unparseable timestamp"):
        parse_open_meteo(body, fetched_at=NOW, latitude=-2.17, longitude=-79.92)


# ===========================================================================
# fetch_forecast error paths — never raises, never invents
# ===========================================================================


@pytest.mark.parametrize(
    "status,body,fragment",
    [
        (0, "", "network unavailable"),
        (429, "", "rate-limited"),
        (500, "", "HTTP 500"),
        (404, "", "HTTP 404"),
        (200, "", "empty body"),
        (200, "<html>not json</html>", "not valid JSON"),
        (200, json.dumps({"hourly": {}}), "time missing or empty"),
    ],
)
def test_fetch_failures_are_returned_not_raised(status: int, body: str, fragment: str) -> None:
    result = fetch(status=status, body=body)
    assert result.ok is False
    assert result.hours == ()
    assert fragment in (result.error or "")
    assert any("no values were invented" in n for n in result.notes)


def test_failure_result_still_carries_provenance() -> None:
    result = fetch(status=500, body="")
    assert result.source == "open-meteo"
    assert result.fetched_at == NOW
    assert result.latitude == pytest.approx(-2.17)


def test_stale_fetch_is_detectable_by_age() -> None:
    """A successfully fetched payload is still old information later."""
    result = fetch()
    later = NOW + timedelta(hours=3)
    assert result.ok
    assert result.age_seconds(later) == pytest.approx(3 * 3600)


# ===========================================================================
# URL construction
# ===========================================================================


def test_url_requests_probability_and_utc() -> None:
    url = build_forecast_url("https://api.open-meteo.com/v1", -2.17, -79.92)
    assert "hourly=precipitation%2Cprecipitation_probability" in url
    assert "timezone=UTC" in url
    assert "past_days" not in url, "must never blur observation into forecast"


@pytest.mark.parametrize("lat,lon", [(91, 0), (-91, 0), (0, 181), (0, -181)])
def test_url_rejects_out_of_range_coordinates(lat: float, lon: float) -> None:
    with pytest.raises(ValueError):
        build_forecast_url("https://x/v1", lat, lon)


def test_url_rejects_absurd_horizon() -> None:
    with pytest.raises(ValueError):
        build_forecast_url("https://x/v1", 0, 0, forecast_hours=100000)


def test_invalid_params_do_not_raise_from_fetch() -> None:
    result = fetch_forecast(
        base_url="https://x/v1", latitude=999, longitude=0, now=NOW,
        http_get=fake_get(200, "{}"),
    )
    assert result.ok is False
    assert "invalid request parameters" in " ".join(result.notes)


# ===========================================================================
# Presentation helper
# ===========================================================================


def test_describe_never_says_heavy_rain() -> None:
    """B13: no approved threshold, so no classification may be invented."""
    result = fetch()
    text = describe(result, NOW)
    low = text.lower()
    assert "heavy" not in low
    assert "forecast" in low
    assert "not an observation" in low
    assert "mm" in low


def test_describe_failure_invents_no_number() -> None:
    text = describe(fetch(status=500, body=""), NOW)
    assert "unavailable" in text.lower()
    assert "no estimate is shown" in text.lower()
    assert "mm" not in text.replace("estimates", ""), "a failed fetch must show no millimetres"


# ===========================================================================
# Optional live smoke test — opt-in only, never in CI
# ===========================================================================


@pytest.mark.skipif(
    os.environ.get("GUARADAR_LIVE_API") != "1",
    reason="live provider smoke test disabled; set GUARADAR_LIVE_API=1 to opt in",
)
def test_live_open_meteo_smoke() -> None:
    """Real read-only call. Not run by default; its result is reported separately."""
    result = fetch_forecast(
        base_url="https://api.open-meteo.com/v1",
        latitude=-2.17,
        longitude=-79.92,
        now=datetime.now(timezone.utc),
        forecast_hours=6,
    )
    assert result.ok is True
    assert len(result.hours) >= 1
    assert all(h.kind == "forecast" for h in result.hours)
