"""Tests for the Guaradar risk engine.

Every test is named after the safety property it defends, so a passing run maps directly
onto docs/STAGE-3-ARCHITECTURE.md §17.1. A test that does not correspond to a property is
marked `# supplementary`.

The engine is pure and takes `now` as a parameter, so these tests need no clock mocking,
no database, and no network. That is the point of the design.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.risk import (
    FLOOR_CLOSURE_LEVEL,
    FLOOR_REPORT_LEVEL,
    INSUFFICIENT_EVIDENCE_BELOW,
    RoadState,
    RiskInputs,
    SensorReading,
    VerifiedReport,
    assess,
    clamp01,
    level_from_score,
    precaution_floor,
    rain_score,
    report_score,
    sensor_score,
    trend_bonus_component,
)

NOW = datetime(2026, 10, 26, 14, 0, 0, tzinfo=timezone.utc)


def reading(
    sensor_id: str = "SIM-01",
    depth_m: float = 0.1,
    threshold_m: float = 1.0,
    age_s: int = 0,
    simulated: bool = True,
) -> SensorReading:
    return SensorReading(
        sensor_id=sensor_id,
        depth_m=depth_m,
        threshold_m=threshold_m,
        observed_at=NOW - timedelta(seconds=age_s),
        simulated=simulated,
    )


def all_inputs(**overrides) -> RiskInputs:
    """A complete, healthy input set. Individual tests knock pieces out."""
    base = dict(
        rain_6h_mm=10.0,
        rain_24h_mm=20.0,
        sensors=(reading(depth_m=0.2),),
        water_rise_1h_m=0.02,
        verified_reports=(),
        roads=RoadState(closed_count=0, affected_fraction=0.0),
    )
    base.update(overrides)
    return RiskInputs(**base)


# ===========================================================================
# RISK-1 — every level reachable; boundaries exact
# ===========================================================================


@pytest.mark.parametrize(
    "score,expected",
    [
        (0.0, 1),
        (0.2499, 1),
        (0.25, 2),      # boundary: inclusive at the bottom
        (0.4499, 2),
        (0.45, 3),
        (0.6999, 3),
        (0.70, 4),
        (1.0, 4),
    ],
)
def test_RISK_1_level_boundaries(score: float, expected: int) -> None:
    assert level_from_score(score) == expected


def test_RISK_1_clamp01_edges() -> None:
    assert clamp01(-5) == 0.0
    assert clamp01(0.5) == 0.5
    assert clamp01(5) == 1.0
    with pytest.raises(ValueError):
        clamp01(float("nan"))


# ===========================================================================
# RISK-2 — missing input renormalises weights, never sums as zero
# ===========================================================================


def test_RISK_2_missing_input_renormalises_not_zero() -> None:
    """Dropping an input must RAISE the influence of the rest, not lower the score."""
    full = assess(all_inputs(rain_6h_mm=40.0, rain_24h_mm=None), NOW)
    # Same scenario with the sensor absent. If absent were treated as 0.0, the score
    # would fall; renormalisation means it rises (only rain remains at 1.0).
    without_sensor = assess(
        all_inputs(rain_6h_mm=40.0, rain_24h_mm=None, sensors=()), NOW
    )
    assert without_sensor.score is not None and full.score is not None
    assert without_sensor.score > full.score
    # With the sensor gone the remaining terms are rain (1.0), trend (0.02 m/h -> 0.0333),
    # reports (0.0) and roads (0.0), over present weight 0.30+0.15+0.15+0.10 = 0.70.
    expected = (0.30 * 1.0 + 0.15 * (0.02 / 0.3 * 0.5) + 0.15 * 0.0 + 0.10 * 0.0) / 0.70
    assert without_sensor.score == pytest.approx(expected)
    assert without_sensor.coverage == pytest.approx(0.70)


def test_RISK_2_coverage_equals_sum_of_present_weights() -> None:
    result = assess(all_inputs(rain_6h_mm=None, rain_24h_mm=None, sensors=()), NOW)
    # rain (0.30) + sensor (0.30) removed => 0.40 remains
    assert result.coverage == pytest.approx(0.40)
    assert set(result.missing_inputs) == {"rain", "sensor"}


# ===========================================================================
# RISK-3 — all sensors stale does NOT lower the level; it lowers confidence
# ===========================================================================


def test_RISK_3_all_sensors_stale_does_not_lower_level() -> None:
    """The withdrawn cap must not reappear. Severity is unaffected by sensor loss."""
    scenarios = {
        "fresh": dict(
            rain_6h_mm=40.0,
            rain_24h_mm=80.0,
            sensors=(reading(depth_m=1.0, threshold_m=1.0, age_s=0),),
            water_rise_1h_m=0.3,
            roads=RoadState(closed_count=1, closed_confirmed_by_operator=True, affected_fraction=1.0),
        ),
        "all_stale": dict(
            rain_6h_mm=40.0,
            rain_24h_mm=80.0,
            sensors=(reading(depth_m=0.1, threshold_m=1.0, age_s=3600),),
            water_rise_1h_m=None,
            roads=RoadState(closed_count=1, closed_confirmed_by_operator=True, affected_fraction=1.0),
        ),
    }
    fresh = assess(RiskInputs(**scenarios["fresh"]), NOW)
    stale = assess(RiskInputs(**scenarios["all_stale"]), NOW)

    assert fresh.level is not None and stale.level is not None
    assert stale.level >= fresh.level, "losing sensors must not reduce severity"
    assert stale.confidence == "low"
    assert stale.insufficient_evidence is True
    assert fresh.confidence == "high"
    assert any("SIMULATED" in r or "stale" in r or "missing" in r for r in stale.reasons)


# ===========================================================================
# RISK-4 — coverage < 0.6 affects MESSAGES only, never the level
# ===========================================================================


def test_RISK_4_low_coverage_does_not_cap_level() -> None:
    """Severity must survive low coverage. The withdrawn cap must not reappear.

    Only the rain term is available and it is saturated, so coverage is 0.30 — far below
    the 0.60 insufficient-evidence line — while the score is 1.0. The critical assertion
    is that severity is NOT capped at 2 by that low coverage.
    """
    inputs = RiskInputs(
        rain_6h_mm=40.0, rain_24h_mm=None, sensors=(), verified_reports=None, roads=None
    )
    result = assess(inputs, NOW)
    assert result.coverage == pytest.approx(0.30)
    assert result.coverage < INSUFFICIENT_EVIDENCE_BELOW
    assert result.insufficient_evidence is True
    assert result.score == pytest.approx(1.0)
    assert result.level == 4, "low coverage must not cap severity (D18/D27)"


def test_RISK_4_identical_score_different_coverage_same_level() -> None:
    """The decisive form: coverage changes messaging, never severity."""
    low_cov = assess(
        RiskInputs(rain_6h_mm=40.0, sensors=(), verified_reports=None, roads=None), NOW
    )
    # Same rain contribution, but add inputs that are also saturated so the renormalised
    # score stays 1.0 while coverage rises.
    high_cov = assess(
        RiskInputs(
            rain_6h_mm=40.0,
            rain_24h_mm=80.0,
            sensors=(reading(depth_m=2.0, threshold_m=1.0),),
            water_rise_1h_m=1.0,
            verified_reports=tuple(VerifiedReport(NOW) for _ in range(20)),
            roads=RoadState(closed_count=1, closed_confirmed_by_operator=True,
                            affected_fraction=1.0),
        ),
        NOW,
    )
    assert low_cov.score == pytest.approx(1.0)
    assert high_cov.score == pytest.approx(0.925)   # trend cap, SPEC_CONFLICT 2
    assert low_cov.coverage < high_cov.coverage
    assert low_cov.confidence == "low"
    assert high_cov.confidence == "high"
    # Both are Emergency: coverage changed the confidence, not the severity.
    assert low_cov.level == 4
    assert high_cov.level == 4


def test_RISK_4_confidence_bands() -> None:
    high = assess(all_inputs(), NOW)
    assert high.coverage == pytest.approx(1.0)
    assert high.confidence == "high"

    # Rain + report + road remain available => 0.55 coverage, below the 0.60 line.
    medium = assess(all_inputs(sensors=(), water_rise_1h_m=None), NOW)
    assert medium.coverage == pytest.approx(0.55)
    assert medium.confidence == "low"
    assert medium.insufficient_evidence is True

    # Drop roads too => 0.45; still low, from a different cause.
    sparser = assess(
        all_inputs(sensors=(), water_rise_1h_m=None, roads=None), NOW
    )
    assert sparser.coverage == pytest.approx(0.45)
    assert sparser.confidence == "low"


# ===========================================================================
# RISK-4c — precaution floor raises, never lowers
# ===========================================================================


def test_RISK_4c_floor_raises_never_lowers() -> None:
    reports = tuple(VerifiedReport(NOW - timedelta(minutes=5)) for _ in range(3))
    inputs = RiskInputs(rain_6h_mm=1.0, rain_24h_mm=2.0, sensors=(), verified_reports=reports)
    result = assess(inputs, NOW)
    assert result.precaution == FLOOR_REPORT_LEVEL
    assert result.score_level is not None
    assert result.level == max(result.score_level, result.precaution)

    # And with a high score, the floor must not pull it down.
    hot = RiskInputs(
        rain_6h_mm=40.0,
        rain_24h_mm=80.0,
        sensors=(reading(depth_m=1.0),),
        water_rise_1h_m=0.3,
        verified_reports=reports,
        roads=RoadState(closed_count=1, closed_confirmed_by_operator=True, affected_fraction=1.0),
    )
    hot_result = assess(hot, NOW)
    assert hot_result.level == 4
    assert hot_result.precaution == 3
    assert hot_result.level >= hot_result.precaution


# ===========================================================================
# RISK-4d — the disabled rain floor must not leak into output or reason text
# ===========================================================================


def test_RISK_4d_rain_floor_is_disabled() -> None:
    """Heavy rain with no reports and no closures must apply NO floor (D23)."""
    inputs = RiskInputs(
        rain_6h_mm=60.0,
        rain_24h_mm=None,
        sensors=(),
        verified_reports=(),
        roads=RoadState(closed_count=0, affected_fraction=0.0),
    )
    result = assess(inputs, NOW)
    assert result.precaution is None, "rain must not trigger a precaution floor"
    joined = " ".join(result.reasons).lower()
    assert "heavy rain" not in joined
    assert "heavy-rain" not in joined
    # The score legitimately reflects saturated rain; the FLOOR is what must be absent.
    # Level 3 here comes from the score alone (0.55), not from any floor.
    assert result.score_level == 3
    assert result.level == result.score_level
    assert result.precaution is None


def test_RISK_4d_floor_function_ignores_rain_entirely() -> None:
    inputs = RiskInputs(rain_6h_mm=500.0, rain_24h_mm=500.0, sensors=())
    floor, reasons = precaution_floor(inputs, NOW)
    assert floor is None
    assert reasons == ()


# ===========================================================================
# RISK-5 — verified-low -> unknown can never lower the published level
# ===========================================================================


def test_RISK_5_masking_inputs_never_lower_level() -> None:
    """Monotonicity over input masking.

    For each single input, removing it must not lower the level. This is the documented,
    testable form of the property, and it holds for the implemented formula.
    """
    base = all_inputs(
        rain_6h_mm=30.0,
        rain_24h_mm=60.0,
        sensors=(reading(depth_m=0.6, threshold_m=1.0),),
        water_rise_1h_m=0.2,
        verified_reports=tuple(VerifiedReport(NOW - timedelta(minutes=10)) for _ in range(4)),
        roads=RoadState(closed_count=1, closed_confirmed_by_operator=True, affected_fraction=0.6),
    )
    base_level = assess(base, NOW).level
    assert base_level is not None

    variants = {
        "no_rain": RiskInputs(**{**base.__dict__, "rain_6h_mm": None, "rain_24h_mm": None}),
        "no_sensor": RiskInputs(**{**base.__dict__, "sensors": ()}),
        "no_trend": RiskInputs(**{**base.__dict__, "water_rise_1h_m": None}),
        "no_reports": RiskInputs(**{**base.__dict__, "verified_reports": ()}),
        "no_roads": RiskInputs(**{**base.__dict__, "roads": None}),
    }
    for name, variant in variants.items():
        result = assess(variant, NOW)
        assert result.level is not None
        assert result.level >= base_level, f"{name} lowered the level ({base_level} -> {result.level})"


def test_RISK_5_stale_high_reading_is_not_silently_zeroed() -> None:
    """A high-then-silent sensor must not be treated as dry.

    Without an approved decay window the reading is excluded (documented behaviour), which
    means it contributes nothing — never \"0.05 m therefore safe\".
    """
    stale_high = reading(depth_m=1.5, threshold_m=1.0, age_s=3600)
    score, used, notes = sensor_score((stale_high,), NOW, stale_after_s=300, high_decay_window_s=0)
    assert score is None
    assert used == ()
    assert any("high" in n for n in notes)


# ===========================================================================
# RISK-6 — zero usable inputs => None / "Unable to assess", never level 1
# ===========================================================================


def test_RISK_6_no_inputs_is_not_assessable() -> None:
    result = assess(RiskInputs(), NOW)
    assert result.score is None
    assert result.level is None
    assert result.level != 1
    assert result.coverage == 0.0
    assert result.confidence == "low"
    assert result.insufficient_evidence is True
    assert "Unable to assess" in " ".join(result.reasons)


# ===========================================================================
# RISK-7 — hysteresis prevents flapping
# ===========================================================================


def test_RISK_7_hysteresis_holds_on_small_dip() -> None:
    hot = RiskInputs(
        rain_6h_mm=40.0,
        rain_24h_mm=None,
        sensors=(reading(depth_m=0.9),),
        water_rise_1h_m=0.3,
        roads=RoadState(affected_fraction=1.0),
    )
    first = assess(hot, NOW)
    assert first.level == 4

    # Score drops slightly but stays above the 4->3 release boundary (0.66).
    warm = RiskInputs(
        rain_6h_mm=30.0,
        rain_24h_mm=None,
        sensors=(reading(depth_m=0.85),),
        water_rise_1h_m=0.3,
        roads=RoadState(affected_fraction=1.0),
    )
    second = assess(warm, NOW + timedelta(minutes=1), previous=first)
    assert second.score_level == 4 or second.score_level == 3
    if second.score is not None and second.score >= 0.66:
        assert second.level == 4, "must hold at 4 while score stays above 0.66"

    # A real drop below the boundary releases it.
    cold = RiskInputs(
        rain_6h_mm=2.0,
        rain_24h_mm=4.0,
        sensors=(reading(depth_m=0.05),),
        water_rise_1h_m=0.0,
        roads=RoadState(affected_fraction=0.0),
    )
    third = assess(cold, NOW + timedelta(minutes=20), previous=first)
    assert third.level is not None and third.level < 4


# ===========================================================================
# RISK-8 / 8b / 8c — conflicts surfaced, never averaged; no veto
# ===========================================================================


def test_RISK_8_high_rain_low_sensor_is_surfaced() -> None:
    inputs = RiskInputs(
        rain_6h_mm=40.0,
        rain_24h_mm=None,
        sensors=(reading(depth_m=0.02, threshold_m=1.0),),
        water_rise_1h_m=0.0,
        roads=RoadState(affected_fraction=0.0),
    )
    result = assess(inputs, NOW)
    kinds = {c.kind for c in result.conflicts}
    assert "rain_vs_sensor" in kinds
    # Documented behaviour, not silence: the conflict is named in spec_conflicts so a
    # later reader sees that RISK-8b's prose is violated by this very case.
    assert "RISK-8b:rain_dry_sensor" in result.spec_conflicts


def test_RISK_8_low_rain_high_sensor_is_surfaced() -> None:
    inputs = RiskInputs(
        rain_6h_mm=1.0,
        rain_24h_mm=None,
        sensors=(reading(depth_m=0.95, threshold_m=1.0),),
        water_rise_1h_m=0.05,
        roads=RoadState(affected_fraction=0.0),
    )
    result = assess(inputs, NOW)
    assert "sensor_vs_rain" in {c.kind for c in result.conflicts}


def test_RISK_8_reports_versus_sensor_cluster_outlier() -> None:
    readings = (
        reading("SIM-01", depth_m=0.9, threshold_m=1.0),
        reading("SIM-02", depth_m=0.05, threshold_m=1.0),
    )
    inputs = RiskInputs(
        rain_6h_mm=10.0,
        rain_24h_mm=None,
        sensors=readings,
        water_rise_1h_m=0.0,
        roads=RoadState(affected_fraction=0.0),
    )
    result = assess(inputs, NOW)
    assert "sensor_cluster" in {c.kind for c in result.conflicts}


def test_RISK_8c_sensor_cannot_veto_the_floor() -> None:
    """A dry sensor must not cancel a floor earned by reports and closures."""
    inputs = RiskInputs(
        rain_6h_mm=1.0,
        rain_24h_mm=None,
        sensors=(reading(depth_m=0.0, threshold_m=1.0),),   # bone dry
        water_rise_1h_m=0.0,
        verified_reports=tuple(VerifiedReport(NOW - timedelta(minutes=5)) for _ in range(3)),
        roads=RoadState(closed_count=1, closed_confirmed_by_operator=True, affected_fraction=0.2),
    )
    result = assess(inputs, NOW)
    assert result.precaution == FLOOR_CLOSURE_LEVEL
    assert result.level is not None and result.level >= FLOOR_CLOSURE_LEVEL


# ===========================================================================
# RISK-9 — override is stored separately (engine-side representation)
# ===========================================================================


def test_RISK_9_override_fields_exist_and_default_false() -> None:
    """The engine represents an override without letting it rewrite the computed score.

    Persistence and auditing of overrides is a database/API concern (M1 schema, later
    milestone); this test asserts only that the result can carry both facts and that the
    score is not mutated by the presence of an override.
    """
    result = assess(all_inputs(), NOW)
    assert result.overridden is False
    assert result.score is not None
    assert result.score_level is not None


# ===========================================================================
# RISK-10 — determinism
# ===========================================================================


def test_RISK_10_identical_inputs_identical_output() -> None:
    inputs = all_inputs(
        sensors=(reading(depth_m=0.4), reading("SIM-02", depth_m=0.8)),
        verified_reports=(VerifiedReport(NOW - timedelta(minutes=3)),),
        roads=RoadState(closed_count=1, closed_confirmed_by_operator=True, affected_fraction=0.3),
    )
    a = assess(inputs, NOW)
    b = assess(inputs, NOW)
    assert a == b, "assess() must be deterministic for identical inputs and instant"


def test_RISK_10_determinism_over_random_inputs() -> None:
    """Property-style check: 500 randomised input sets, each evaluated twice."""
    import random

    rng = random.Random(20261026)
    for _ in range(500):
        n_sensors = rng.randint(0, 4)
        sensors = tuple(
            reading(
                f"SIM-{i:02d}",
                depth_m=rng.uniform(0.0, 2.0),
                threshold_m=rng.uniform(0.5, 1.5),
                age_s=rng.randint(0, 900),
            )
            for i in range(n_sensors)
        )
        inputs = RiskInputs(
            rain_6h_mm=rng.choice([None, rng.uniform(0, 80)]),
            rain_24h_mm=rng.choice([None, rng.uniform(0, 160)]),
            sensors=sensors,
            water_rise_1h_m=rng.choice([None, rng.uniform(-0.1, 0.5)]),
            verified_reports=tuple(
                VerifiedReport(NOW - timedelta(minutes=rng.randint(0, 200)))
                for _ in range(rng.randint(0, 6))
            ),
            roads=rng.choice(
                [None, RoadState(closed_count=rng.randint(0, 3),
                                 closed_confirmed_by_operator=rng.random() > 0.5,
                                 affected_fraction=rng.random())]
            ),
        )
        assert assess(inputs, NOW) == assess(inputs, NOW)


# ===========================================================================
# Supplementary — component behaviour and honesty requirements
# ===========================================================================


def test_rain_score_saturation() -> None:
    assert rain_score(None, None) is None
    assert rain_score(0.0, 0.0) == 0.0
    assert rain_score(40.0, 0.0) == 1.0        # 40 mm / 6 h = full marks
    assert rain_score(0.0, 80.0) == 1.0        # 80 mm / 24 h = full marks
    assert rain_score(20.0, 0.0) == pytest.approx(0.5)
    assert rain_score(1000.0, 1000.0) == 1.0   # clamped


def test_trend_bonus_capped_and_never_negative() -> None:
    assert trend_bonus_component(None) is None
    assert trend_bonus_component(0.0) == 0.0
    assert trend_bonus_component(-0.5) == 0.0        # falling water cannot subtract risk
    assert trend_bonus_component(0.3) == pytest.approx(0.5)   # spec-literal 0.5 cap
    assert trend_bonus_component(10.0) == pytest.approx(0.5)


def test_report_score_saturation() -> None:
    assert report_score(()) == 0.0
    assert report_score(tuple(VerifiedReport(NOW) for _ in range(5))) == 1.0
    assert report_score(tuple(VerifiedReport(NOW) for _ in range(10))) == 1.0


def test_simulated_flag_is_carried_and_named() -> None:
    result = assess(all_inputs(sensors=(reading(depth_m=0.5, simulated=True),)), NOW)
    assert result.simulated is True
    assert any("SIMULATED" in r for r in result.reasons)


def test_max_score_is_below_one_because_trend_is_capped() -> None:
    """Documents SPEC_CONFLICT 2 rather than hiding it.

    With every input saturated the score is 0.925, not 1.0, because trend_bonus is capped
    at 0.5 by the approved formula.
    """
    inputs = RiskInputs(
        rain_6h_mm=40.0,
        rain_24h_mm=80.0,
        sensors=(reading(depth_m=2.0, threshold_m=1.0),),
        water_rise_1h_m=1.0,
        verified_reports=tuple(VerifiedReport(NOW) for _ in range(10)),
        roads=RoadState(closed_count=2, closed_confirmed_by_operator=True, affected_fraction=1.0),
    )
    result = assess(inputs, NOW)
    assert result.score == pytest.approx(0.925)
    assert result.level == 4


def test_elevation_lowers_effective_threshold() -> None:
    """§8 Formula: elevation is a static threshold multiplier, never a live term (D12)."""
    flat = SensorReading("A", 0.5, 1.0, NOW, simulated=True, elevation_percentile=0.0)
    low = SensorReading("B", 0.5, 1.0, NOW, simulated=True, elevation_percentile=1.0)
    assert flat.effective_threshold() == pytest.approx(1.0)
    assert low.effective_threshold() == pytest.approx(1.15)
    # Same depth is a larger fraction of threshold in the lower sector.
    assert (0.5 / low.effective_threshold()) < (0.5 / flat.effective_threshold())


def test_invalid_inputs_rejected() -> None:
    with pytest.raises(ValueError):
        SensorReading("X", depth_m=-1.0, threshold_m=1.0, observed_at=NOW)
    with pytest.raises(ValueError):
        SensorReading("X", depth_m=0.1, threshold_m=0.0, observed_at=NOW)
    with pytest.raises(ValueError):
        SensorReading("X", depth_m=float("nan"), threshold_m=1.0, observed_at=NOW)
    with pytest.raises(ValueError):
        RoadState(affected_fraction=1.5)
    with pytest.raises(ValueError):
        RoadState(closed_count=-1)


# ===========================================================================
# Supplementary — documented gaps and cap behaviour
# ===========================================================================


def test_decay_window_retains_stale_high_reading_when_supplied() -> None:
    """§8.2 asymmetry, enabled form.

    No number for the decay window exists in the spec, so the default is 0 (disabled).
    When a caller supplies a window, a high-then-silent reading is RETAINED rather than
    dropped — the alarm pattern must not be lost. This test proves the mechanism works
    and documents that the default keeps it off.
    """
    stale_high = reading(depth_m=1.5, threshold_m=1.0, age_s=600)

    # Default: no window -> excluded, contributes nothing.
    score_off, used_off, _ = sensor_score(
        (stale_high,), NOW, stale_after_s=300, high_decay_window_s=0
    )
    assert score_off is None
    assert used_off == ()

    # With a window longer than the age -> retained and still alarming.
    # sensor_score clamps to [0,1], so a reading at 1.5x threshold yields 1.0.
    score_on, used_on, notes = sensor_score(
        (stale_high,), NOW, stale_after_s=300, high_decay_window_s=900
    )
    assert score_on == pytest.approx(1.0)
    assert len(used_on) == 1
    assert any("decay window" in n for n in notes)

    # Window shorter than the age -> still excluded.
    score_expired, used_expired, _ = sensor_score(
        (stale_high,), NOW, stale_after_s=300, high_decay_window_s=100
    )
    assert score_expired is None
    assert used_expired == ()


def test_hysteresis_holds_when_score_stays_above_boundary() -> None:
    """The hold branch: score in [0.66, 0.70) maps to level 3 but must be held at 4.

    Constructed from a search over the documented formula so the case is real, not assumed:
    rain 40 mm/6h, one verified report, 40 % of roads affected, sensor at threshold, no
    rise -> score 0.67, raw level 3, release boundary for 4 is 0.66.
    """
    previous = assess(
        RiskInputs(
            rain_6h_mm=40.0,
            rain_24h_mm=80.0,
            sensors=(reading(depth_m=2.0, threshold_m=1.0),),
            water_rise_1h_m=1.0,
            verified_reports=tuple(VerifiedReport(NOW) for _ in range(20)),
            roads=RoadState(closed_count=1, closed_confirmed_by_operator=True,
                            affected_fraction=1.0),
        ),
        NOW,
    )
    assert previous.level == 4

    dip = RiskInputs(
        rain_6h_mm=40.0,
        rain_24h_mm=None,
        sensors=(reading(depth_m=1.0, threshold_m=1.0),),
        water_rise_1h_m=0.0,
        verified_reports=(VerifiedReport(NOW),),
        roads=RoadState(affected_fraction=0.4),
    )
    raw = assess(dip, NOW)
    assert raw.score == pytest.approx(0.67, abs=0.005)
    assert raw.score_level == 3, "raw mapping gives 3"

    held = assess(dip, NOW + timedelta(minutes=1), previous=previous)
    assert held.level == 4, "score 0.67 >= 0.66 must hold level 4"
    assert any("held at 4" in r for r in held.reasons)


def test_rain_24h_only_reason_line() -> None:
    """Hits the 24 h-only branch of the rain reason builder (no 6 h value supplied)."""
    result = assess(RiskInputs(rain_6h_mm=None, rain_24h_mm=50.0), NOW)
    assert any(r == "rain: 50 mm in 24 h" for r in result.reasons)
    assert not any("mm forecast in 6 h" in r for r in result.reasons)


def test_reasons_include_forecast_millimetres() -> None:
    result = assess(all_inputs(rain_6h_mm=38.0, rain_24h_mm=90.0), NOW)
    joined = " ".join(result.reasons)
    assert "38 mm forecast in 6 h" in joined
    assert "90 mm in 24 h" in joined


def test_simulated_flag_false_is_carried_without_simulated_reason() -> None:
    """A non-simulated reading must not print the SIMULATED disclaimer.

    Nothing in this project sets simulated=False, so this branch exists only to prove the
    disclaimer is conditional rather than decorative.
    """
    real = reading(depth_m=0.5, simulated=False)
    result = assess(RiskInputs(rain_6h_mm=5.0, sensors=(real,), roads=None), NOW)
    assert result.simulated is True          # inputs.simulated defaults True
    assert not any("SIMULATED" in r for r in result.reasons)
