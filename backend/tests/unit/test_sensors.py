"""Tests for the simulated sensor adapter.

The central claim under test is not "the numbers look plausible" — no test can establish
that, because the readings are synthetic by definition. What these tests establish is:

  * every reading is irrefutably marked SIMULATED, with no code path to unmark it
  * generation is deterministic, so rehearsals reproduce
  * thresholds are never invented here
  * gaps are preserved, not interpolated
  * health is derived from cadence, so it cannot lie
  * LIVE mode is unreachable while any sensor is simulated (SIM-3)
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from app.simulate.sensors import (
    VALID_PROFILES,
    SensorConfigError,
    SensorSpec,
    data_mode,
    describe_series,
    generate_all,
    generate_reading,
    generate_series,
)

NOW = datetime(2026, 10, 26, 14, 0, 0, tzinfo=timezone.utc)


def spec(
    sensor_id: str = "SIM-01",
    profile: str = "steady",
    threshold_m: float = 1.20,
) -> SensorSpec:
    return SensorSpec(
        sensor_id=sensor_id,
        sector_id="norte",
        threshold_m=threshold_m,
        lat=-2.1428,
        lon=-79.9056,
        profile=profile,      # type: ignore[arg-type]
    )


# ===========================================================================
# SIMULATED labelling
# ===========================================================================


def test_every_reading_is_simulated() -> None:
    for profile in VALID_PROFILES:
        r = generate_reading(spec(profile=profile), NOW)
        assert r.simulated is True
        assert r.label == "SIMULATED"


def test_series_is_simulated() -> None:
    s = generate_series(spec(), now=NOW, count=5)
    assert s.simulated is True
    assert all(r.simulated is True for r in s.readings)


def test_describe_always_leads_with_simulated() -> None:
    s = generate_series(spec(), now=NOW, count=5)
    text = describe_series(s)
    assert "SIMULATED" in text
    # The word must appear before any number, so a screenshot cannot be misread.
    assert text.index("SIMULATED") < text.index("m")


def test_simulated_flag_cannot_be_flipped_by_a_caller() -> None:
    """The only producer hardcodes True; there is no constructor path to False."""
    s = generate_series(spec(), now=NOW, count=1)
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
        s.readings[0].simulated = False        # type: ignore[misc]


# ===========================================================================
# Determinism
# ===========================================================================


def test_same_inputs_same_reading() -> None:
    a = generate_reading(spec(), NOW, seed=20261026)
    b = generate_reading(spec(), NOW, seed=20261026)
    assert a == b


def test_different_seed_changes_value() -> None:
    a = generate_reading(spec(), NOW, seed=1)
    b = generate_reading(spec(), NOW, seed=2)
    assert a.depth_m != b.depth_m or a.fraction_of_threshold != b.fraction_of_threshold


def test_series_is_deterministic() -> None:
    a = generate_series(spec(), now=NOW, count=6)
    b = generate_series(spec(), now=NOW, count=6)
    assert [r.depth_m for r in a.readings] == [r.depth_m for r in b.readings]


def test_generate_all_is_deterministic() -> None:
    specs = [spec("SIM-01", "steady"), spec("SIM-02", "surge")]
    a = generate_all(specs, now=NOW, count=4)
    b = generate_all(specs, now=NOW, count=4)
    assert [[r.depth_m for r in s.readings] for s in a] == [
        [r.depth_m for r in s.readings] for s in b
    ]


# ===========================================================================
# Thresholds are the caller's, never invented
# ===========================================================================


def test_threshold_is_passed_through_unchanged() -> None:
    for th in (0.5, 0.8, 1.0, 1.2, 2.5):
        r = generate_reading(spec(threshold_m=th), NOW)
        assert r.threshold_m == pytest.approx(th)


def test_intensity_scales_with_threshold() -> None:
    """The same profile at two thresholds keeps the same FRACTION of threshold.

    This is what stops a threshold change from silently redefining the scenario.
    """
    low = generate_reading(spec(threshold_m=1.0), NOW, seed=7)
    high = generate_reading(spec(threshold_m=2.0), NOW, seed=7)
    assert low.fraction_of_threshold == pytest.approx(high.fraction_of_threshold, abs=0.002)


def test_nonpositive_threshold_rejected() -> None:
    with pytest.raises(SensorConfigError, match="threshold_m must be > 0"):
        spec(threshold_m=0.0)
    with pytest.raises(SensorConfigError):
        spec(threshold_m=-1.0)


def test_unknown_profile_rejected() -> None:
    with pytest.raises(SensorConfigError, match="unknown profile"):
        SensorSpec("X", "norte", 1.0, -2.1, -79.9, profile="catastrophic")  # type: ignore[arg-type]


# ===========================================================================
# Profile behaviour
# ===========================================================================


def test_dry_stays_below_threshold() -> None:
    for h in range(24):
        r = generate_reading(spec(profile="dry"), NOW + timedelta(hours=h), seed=3)
        assert r.depth_m < r.threshold_m


def test_surge_reaches_or_exceeds_threshold_at_some_point() -> None:
    values = [
        generate_reading(spec(profile="surge"), NOW + timedelta(hours=h), seed=3).fraction_of_threshold
        for h in range(24)
    ]
    assert max(values) > 1.0, "the surge profile must be able to exceed threshold"


def test_depths_are_never_negative() -> None:
    for profile in VALID_PROFILES:
        for h in range(48):
            r = generate_reading(spec(profile=profile), NOW + timedelta(hours=h), seed=11)
            assert r.depth_m >= 0.0


# ===========================================================================
# Gaps and health
# ===========================================================================


def test_gaps_are_preserved_not_interpolated() -> None:
    s = generate_series(spec(), now=NOW, count=12, interval_s=300, include_gaps=True)
    assert len(s.readings) < 12, "expected some readings to be dropped as gaps"
    assert any("gaps" in n for n in s.notes)


def test_no_readings_means_offline() -> None:
    s = generate_series(spec(), now=NOW, count=0)
    assert s.health == "offline"
    assert s.last_reading_age_s is None
    assert s.latest is None


def test_old_reading_means_offline() -> None:
    """Cadence decides health, so a stopped sensor cannot report 'ok'."""
    old = spec()
    s = generate_series(old, now=NOW, count=1, interval_s=10_000)
    assert s.last_reading_age_s > old.stale_after_s
    assert s.health == "offline"


def test_recent_reading_is_ok() -> None:
    s = generate_series(spec(), now=NOW, count=3, interval_s=30)
    assert s.health == "ok"
    assert s.last_reading_age_s is not None


def test_late_reading_is_degraded_not_ok() -> None:
    s = generate_series(spec(), now=NOW, count=3, interval_s=300)
    # Last reading is 300 s old: beyond 3x the 60 s expected interval, within staleness.
    assert s.health == "degraded"


# ===========================================================================
# Data mode (§10.1 / SIM-3)
# ===========================================================================


def test_live_is_unreachable_with_simulated_sensors() -> None:
    """SIM-3: the honest state of this project can never be LIVE."""
    assert data_mode(external_live=True, any_simulated=True) == "MIXED"
    assert data_mode(external_live=False, any_simulated=True) == "SIMULATED"
    assert data_mode(external_live=True, any_simulated=False) == "LIVE"
    for ext in (True, False):
        assert data_mode(external_live=ext, any_simulated=True) != "LIVE"


# ===========================================================================
# A simulated reading cannot publish an alert
# ===========================================================================


def test_simulated_module_cannot_publish() -> None:
    """Structural check: this module exposes no publication path.

    A simulated reading becoming a published official alert would require the Stage 2
    lifecycle with a Publisher role, which is deliberately not importable from here.
    """
    import app.simulate.sensors as mod

    public = {n for n in dir(mod) if not n.startswith("_")}
    for forbidden in ("publish", "create_alert", "dispatch", "notify"):
        assert not any(forbidden in name for name in public), (
            f"simulation module exposes {forbidden!r}-like API; it must not be able to "
            f"publish alerts"
        )
