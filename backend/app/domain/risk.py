"""Guaradar risk engine — pure, deterministic, I/O-free.

Approved specification: docs/STAGE-3-ARCHITECTURE.md §8 (formula, level mapping, hysteresis,
hard rules), §8.1 (renormalisation), §8.2 (stale asymmetry), §8.3 (conflicts), §8.4
(severity vs coverage, precaution floor); decisions D18–D30.

WHAT THIS MODULE DOES NOT DO
  * It is not a hydrological model. It is an unvalidated heuristic (R9). It has never been
    checked against observed flood depths and must never be described as predicting flooding.
  * It performs no I/O: no database, no network, no filesystem, no clock reads. `now` is
    injected so hysteresis and staleness are testable at any instant.

TWO SPECIFICATION CONFLICTS CARRIED INTO THIS FILE
  Both are recorded in docs/M2-EVIDENCE.md and were NOT silently resolved. They are marked
  with SPEC_CONFLICT below and surfaced at runtime when the relevant path is taken.

  SPEC_CONFLICT 1 — RISK-8b prose vs test row.
    Prose (§17.1): "no single input may reduce the level below what the remaining inputs
    alone would produce". The documented formula *does* violate this: heavy rain with a dry
    sensor present yields level 2, while the same scenario with the sensor absent yields
    level 3 (0.312 vs 0.545). The published test row ("removing any one input never lowers
    the level") is satisfied by the formula, so prose and testable row disagree.
    D23 disabled the heavy-rain floor, so nothing lifts the dry-sensor case back to 3.

  SPEC_CONFLICT 2 — trend_bonus saturation.
    §8 Formula comments "weights sum to 1.0" and lists trend weight 0.15, but defines
    trend_bonus = clamp01(...) * 0.5, i.e. capped at 0.5. So trend contributes at most
    0.075, and the maximum achievable score is 0.925, not 1.0.
    Implemented literally as written (trend capped at 0.5). Flagged, not "fixed": changing
    it would invent a weight.

UNDEFINED VALUES
  * "bounded decay window" for a high-then-silent sensor (§8.2) has no number in the spec.
    Parameterised as `high_decay_window_s` and defaulted to 0 — i.e. the behaviour is
    DISABLED by default rather than invented. Enabling it needs an approved value.
  * "max_rise_over_1h" (§8 Formula) is unqualified: it could be rain or water level. Read as
    sensor water-level rise (m/h), because 0.3 m/h only makes sense for water. Flagged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, Sequence

# ---------------------------------------------------------------------------
# Documented constants. Every number here is traceable to the approved spec;
# nothing is introduced by this module.
# ---------------------------------------------------------------------------

# §8 Formula: weights, declared to sum to 1.0.
WEIGHT_RAIN = 0.30
WEIGHT_SENSOR = 0.30
WEIGHT_TREND = 0.15
WEIGHT_REPORT = 0.15
WEIGHT_ROAD = 0.10
TOTAL_WEIGHT = (
    WEIGHT_RAIN + WEIGHT_SENSOR + WEIGHT_TREND + WEIGHT_REPORT + WEIGHT_ROAD
)  # 1.0

# §8 Formula: saturation points.
RAIN_6H_FULL_MM = 40.0       # 40 mm / 6 h = full marks (a SCORING input, not a warning threshold)
RAIN_24H_FULL_MM = 80.0      # 80 mm / 24 h = full marks
TREND_FAST_M_PER_H = 0.3     # 0.3 m/h = fast
TREND_CAP = 0.5              # trend_bonus is clamped to 0.5 (see SPEC_CONFLICT 2)
REPORTS_FOR_FULL = 5.0       # I / 5

# §8 Level mapping boundaries.
LEVEL_BOUNDS = ((0.70, 4), (0.45, 3), (0.25, 2), (0.0, 1))

# §8 Hysteresis: a down-shift requires the score to fall below `threshold` for `hold`.
HYSTERESIS = {
    4: (0.66, timedelta(minutes=10)),
    3: (0.42, timedelta(minutes=10)),
    2: (0.22, timedelta(minutes=10)),
}

# §8.4 Confidence bands (EVIDENCE ONLY — never a severity cap; D18/D27).
CONFIDENCE_HIGH_COVERAGE = 0.85
CONFIDENCE_MEDIUM_COVERAGE = 0.60
INSUFFICIENT_EVIDENCE_BELOW = 0.60

# §8.4 / D23: precaution floor. The rain trigger is DISABLED and therefore absent
# from the constants on purpose — an unreachable code path cannot leak a warning.
FLOOR_REPORT_COUNT = 3          # >= 3 verified reports (provisional, unvalidated)
FLOOR_REPORT_WINDOW_MIN = 60    # in the last 60 min (provisional, unvalidated)
FLOOR_CLOSURE_LEVEL = 3         # any operator-confirmed closure -> >= 3
FLOOR_REPORT_LEVEL = 3          # >= 3 verified reports -> >= 3

# §8 Formula: elevation enters only as a static threshold multiplier (D12).
ELEVATION_THRESHOLD_COEFF = 0.15

Level = Literal[1, 2, 3, 4]
Confidence = Literal["high", "medium", "low"]

NOT_ASSESSABLE_REASON = "Unable to assess: no usable inputs."


def clamp01(x: float) -> float:
    """Clamp to [0, 1]. Spelled out because every score component depends on it."""
    if x != x:  # NaN guard: a NaN must never silently become a 0 or a 1
        raise ValueError("clamp01 received NaN")
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x

def level_from_score(score: float) -> Level:
    """§8 level mapping, boundaries inclusive at the bottom of each band."""
    if score >= 0.70:
        return 4
    if score >= 0.45:
        return 3
    if score >= 0.25:
        return 2
    return 1


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SensorReading:
    """One depth reading from one node.

    `simulated` defaults True: in this project every sensor is simulated (D28), and a
    caller must explicitly pass False to claim otherwise. The engine propagates the flag
    into its output so a simulated reading can never be rendered as a real observation.
    """

    sensor_id: str
    depth_m: float
    threshold_m: float
    observed_at: datetime
    simulated: bool = True
    # Static, approximate, SRTM-derived percentile of this node's sector within the city.
    # None means unknown; D12 forbids using it to rank streets.
    elevation_percentile: float | None = None

    def __post_init__(self) -> None:
        # Fail fast at construction. Discovering a negative depth deep inside scoring
        # would attribute a caller's mistake to the risk model.
        if self.threshold_m <= 0:
            raise ValueError(f"{self.sensor_id}: threshold_m must be > 0")
        if self.depth_m != self.depth_m:      # NaN check must precede the < 0 comparison
            raise ValueError(f"{self.sensor_id}: depth_m is NaN")
        if self.depth_m < 0:
            raise ValueError(f"{self.sensor_id}: depth_m must be >= 0")

    def effective_threshold(self) -> float:
        """§8 Formula: lower sectors reach 'flooding' at a smaller depth."""
        if self.elevation_percentile is None:
            return self.threshold_m
        pct = clamp01(self.elevation_percentile)
        return self.threshold_m * (1.0 + ELEVATION_THRESHOLD_COEFF * pct)


@dataclass(frozen=True)
class VerifiedReport:
    """A citizen report that an operator has verified. Counts toward the floor (§8.4)."""

    reported_at: datetime


@dataclass(frozen=True)
class RoadState:
    """Aggregate road information for the sector."""

    closed_count: int = 0            # operator-confirmed closures present in sector
    closed_confirmed_by_operator: bool = False
    affected_fraction: float = 0.0   # 0..1, share of segments affected or closed

    def __post_init__(self) -> None:
        if self.closed_count < 0:
            raise ValueError("closed_count must be >= 0")
        if not 0.0 <= self.affected_fraction <= 1.0:
            raise ValueError("affected_fraction must be within [0, 1]")


@dataclass(frozen=True)
class RiskInputs:
    """Everything the engine may consider. Any field may be None meaning 'unavailable'.

    None is NOT zero. The engine excludes absent inputs and renormalises (§8.1).
    """

    rain_6h_mm: float | None = None
    rain_24h_mm: float | None = None
    sensors: Sequence[SensorReading] = field(default_factory=tuple)
    water_rise_1h_m: float | None = None      # see UNDEFINED VALUES note in the module docstring
    # None means the report feed itself is unavailable. An EMPTY TUPLE means the feed was
    # available and contained zero verified reports — a real observation of absence, which
    # legitimately scores 0.0. Conflating the two is how "no data" becomes "no risk".
    verified_reports: Sequence[VerifiedReport] | None = None
    roads: RoadState | None = None
    # §8.2 asymmetry: retain a HIGH reading that has since gone silent. Disabled unless a
    # window is supplied, because no number exists in the approved spec.
    high_decay_window_s: int = 0
    # True when the sector has any confirmed closure. Used only for the floor, never as
    # an independent severity term beyond road_score.
    simulated: bool = True


@dataclass(frozen=True)
class Conflict:
    """A disagreement the engine refuses to average away (§8.3)."""

    kind: str
    detail: str


@dataclass(frozen=True)
class RiskResult:
    score: float | None
    level: Level | None
    coverage: float
    confidence: Confidence
    insufficient_evidence: bool
    missing_inputs: tuple[str, ...]
    precaution: int | None
    conflicts: tuple[Conflict, ...]
    reasons: tuple[str, ...]
    simulated: bool
    # Components, exposed for the admin console and for tests. Not for public display.
    components: dict[str, float | None] = field(default_factory=dict)
    # SPEC_CONFLICT markers that were actually relevant to this evaluation.
    spec_conflicts: tuple[str, ...] = ()
    # Level implied by the score alone, before the floor. Useful for explaining a floor.
    score_level: Level | None = None
    overridden: bool = False


# ---------------------------------------------------------------------------
# Component scoring
# ---------------------------------------------------------------------------


def rain_score(rain_6h_mm: float | None, rain_24h_mm: float | None) -> float | None:
    """§8: clamp01(max(R6/40, R24/80)). None if both horizons are missing.

    Note: 40 mm/6 h and 80 mm/24 h are SCORING saturation points. They are explicitly
    NOT an approved public "heavy rain" warning threshold (D23 / blocker B13).
    """
    candidates: list[float] = []
    if rain_6h_mm is not None:
        candidates.append(rain_6h_mm / RAIN_6H_FULL_MM)
    if rain_24h_mm is not None:
        candidates.append(rain_24h_mm / RAIN_24H_FULL_MM)
    if not candidates:
        return None
    return clamp01(max(candidates))


def _is_stale(reading: SensorReading, now: datetime, stale_after_s: int) -> bool:
    return (now - reading.observed_at).total_seconds() > stale_after_s


def sensor_score(
    readings: Sequence[SensorReading],
    now: datetime,
    stale_after_s: int,
    high_decay_window_s: int,
) -> tuple[float | None, tuple[SensorReading, ...], tuple[str, ...]]:
    """§8 sensor component with the §8.2 asymmetry rule.

    Returns (score or None, sensors actually used, notes).

    Rules implemented exactly as §8.2 states them:
      * stale HIGH reading  -> retained only within `high_decay_window_s` (default 0 =
        disabled, because the spec names no number); otherwise it stops scoring.
      * stale LOW reading   -> excluded. A dead sensor must never contribute "safe".
      * all stale / none    -> None, so weights renormalise and severity is unaffected.
    """
    if not readings:
        return None, (), ()

    notes: list[str] = []
    usable: list[SensorReading] = []

    for r in readings:
        # No re-validation here: SensorReading.__post_init__ already rejects a negative
        # depth or non-positive threshold at construction. Duplicating the check would be
        # unreachable code that looks like defence but can never execute.
        stale = _is_stale(r, now, stale_after_s)
        if not stale:
            usable.append(r)
            continue

        # Stale. Apply the asymmetry rule.
        ratio = r.depth_m / r.effective_threshold()
        is_high = ratio >= 0.5          # "high" = at or above half its threshold
        age_s = (now - r.observed_at).total_seconds()

        if is_high and high_decay_window_s > 0 and age_s <= high_decay_window_s:
            usable.append(r)
            notes.append(
                f"{r.sensor_id} is stale but was reading high; retained within the "
                f"{high_decay_window_s}s decay window"
            )
        elif is_high:
            notes.append(
                f"{r.sensor_id} is stale (last reading high); excluded — no decay window "
                f"approved, so it does not count toward the score"
            )
        else:
            notes.append(f"{r.sensor_id} is stale (last reading low); excluded")

    if not usable:
        return None, (), tuple(notes)

    worst = max(r.depth_m / r.effective_threshold() for r in usable)
    return clamp01(worst), tuple(usable), tuple(notes)


def trend_bonus_component(water_rise_1h_m: float | None) -> float | None:
    """§8: clamp01(max_rise_over_1h / 0.3) * 0.5.

    The 0.5 cap is spec-literal (SPEC_CONFLICT 2). Negative rise (falling water) yields 0,
    not a negative bonus: the term can only add risk, never subtract it.
    """
    if water_rise_1h_m is None:
        return None
    return clamp01(max(water_rise_1h_m, 0.0) / TREND_FAST_M_PER_H) * TREND_CAP


def report_score(verified_reports: Sequence[VerifiedReport] | None) -> float | None:
    """§8: clamp01(I / 5).

    Returns None when the report feed is unavailable (None), and 0.0 when the feed was
    available but contained no verified reports. Those are different facts: one is "we do
    not know", the other is "we looked and found none". Returning 0.0 for unavailable
    would let a dead feed quietly contribute calm.
    """
    if verified_reports is None:
        return None
    return clamp01(len(verified_reports) / REPORTS_FOR_FULL)


def road_score_component(roads: RoadState | None) -> float | None:
    if roads is None:
        return None
    return clamp01(roads.affected_fraction)


# ---------------------------------------------------------------------------
# Precaution floor (D19 / D23) — may raise, never lower
# ---------------------------------------------------------------------------


def precaution_floor(
    inputs: RiskInputs, now: datetime
) -> tuple[int | None, tuple[str, ...]]:
    """§8.4 floor as narrowed by D23.

    ACTIVE triggers only:
      * >= 3 verified reports in the last 60 min   -> >= 3
      * any operator-confirmed closure in sector   -> >= 3

    The heavy-rain trigger is deliberately ABSENT (D23: no defensible threshold exists).
    Nothing in this function may reference a rain threshold; `RISK-4d` asserts that.
    """
    floor: int | None = None
    reasons: list[str] = []

    window_start = now - timedelta(minutes=FLOOR_REPORT_WINDOW_MIN)
    reports = inputs.verified_reports or ()
    recent = [r for r in reports if window_start <= r.reported_at <= now]
    if len(recent) >= FLOOR_REPORT_COUNT:
        floor = max(floor or 0, FLOOR_REPORT_LEVEL)
        reasons.append(
            f"precaution floor {FLOOR_REPORT_LEVEL}: {len(recent)} verified reports in the "
            f"last {FLOOR_REPORT_WINDOW_MIN} min"
        )

    roads = inputs.roads
    if roads is not None and roads.closed_count > 0 and roads.closed_confirmed_by_operator:
        floor = max(floor or 0, FLOOR_CLOSURE_LEVEL)
        reasons.append(
            f"precaution floor {FLOOR_CLOSURE_LEVEL}: {roads.closed_count} "
            f"operator-confirmed closure(s) in sector"
        )

    return floor, tuple(reasons)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def assess(
    inputs: RiskInputs,
    now: datetime,
    stale_after_s: int = 300,
    previous: RiskResult | None = None,
) -> RiskResult:
    """Compute the risk assessment. Pure: same inputs + same `now` => identical result.

    `previous` carries the prior level for hysteresis. Without it, the level is the raw
    mapping from the score and no down-shift hold is applied.
    """
    components: dict[str, float | None] = {}
    missing: list[str] = []
    reasons: list[str] = []
    conflicts: list[Conflict] = []
    spec_conflicts: list[str] = []

    # ---- 1. Compute every component; None means unavailable --------------------
    r_score = rain_score(inputs.rain_6h_mm, inputs.rain_24h_mm)
    components["rain"] = r_score
    if r_score is None:
        missing.append("rain")

    s_score, used_sensors, sensor_notes = sensor_score(
        inputs.sensors, now, stale_after_s, inputs.high_decay_window_s
    )
    components["sensor"] = s_score
    if s_score is None:
        missing.append("sensor")

    t_score = trend_bonus_component(inputs.water_rise_1h_m)
    components["trend"] = t_score
    if t_score is None:
        missing.append("trend")

    i_score = report_score(inputs.verified_reports)
    components["report"] = i_score
    if i_score is None:  # pragma: no cover - defensive
        missing.append("report")

    c_score = road_score_component(inputs.roads)
    components["road"] = c_score
    if c_score is None:
        missing.append("road")

    # ---- 2. Renormalise over what is available (§8.1) --------------------------
    weights = {
        "rain": WEIGHT_RAIN,
        "sensor": WEIGHT_SENSOR,
        "trend": WEIGHT_TREND,
        "report": WEIGHT_REPORT,
        "road": WEIGHT_ROAD,
    }
    present = {k: (weights[k], components[k]) for k in weights if components[k] is not None}
    coverage = sum(w for w, _ in present.values())

    # ---- 3. Nothing usable => "Unable to assess" (RISK-6) ---------------------
    if not present:
        return RiskResult(
            score=None,
            level=None,
            coverage=0.0,
            confidence="low",
            insufficient_evidence=True,
            missing_inputs=tuple(missing),
            precaution=None,
            conflicts=(),
            reasons=(NOT_ASSESSABLE_REASON,),
            simulated=inputs.simulated,
            components=components,
            spec_conflicts=(),
            score_level=None,
        )

    score = sum(w * v for w, v in present.values()) / coverage
    score_level = level_from_score(score)

    # ---- 4. Precaution floor: may raise, never lower ---------------------------
    floor, floor_reasons = precaution_floor(inputs, now)
    level = score_level
    if floor is not None and floor > level:
        level = floor

    # ---- 5. Confidence is EVIDENCE ONLY (§8.4) --------------------------------
    if coverage >= CONFIDENCE_HIGH_COVERAGE:
        confidence: Confidence = "high"
    elif coverage >= CONFIDENCE_MEDIUM_COVERAGE:
        confidence = "medium"
    else:
        confidence = "low"
    insufficient = coverage < INSUFFICIENT_EVIDENCE_BELOW

    # ---- 6. Hysteresis on down-shift (§8) -------------------------------------
    if previous is not None and previous.level is not None and level < previous.level:
        # Every level above 1 has a documented release boundary; only level 1 is absent
        # from HYSTERESIS because nothing exists below it. A previous.level of 1 can never
        # satisfy `level < previous.level`, so the lookup is always populated here.
        boundary, hold = HYSTERESIS[previous.level]
        # Only down-shift if the score has fallen below the release boundary. Holding is
        # the honest action while the score sits between the boundary and the band edge.
        if score >= boundary:
            level = previous.level
            reasons.append(
                f"level held at {previous.level}: score {score:.3f} has not fallen "
                f"below {boundary:.2f}"
            )
        else:
            reasons.append(
                f"down-shift from {previous.level} requires score < {boundary:.2f} "
                f"for {hold}; applied because score is {score:.3f}"
            )

    # ---- 7. Conflicts (§8.3) — state them, never average them away ------------
    if r_score is not None and s_score is not None:
        if r_score >= 0.75 and s_score <= 0.25:
            conflicts.append(
                Conflict(
                    "rain_vs_sensor",
                    "Forecast suggests risk; sensors not yet responding. Both are shown; "
                    "neither is discarded.",
                )
            )
            # NOTE: the disabled rain floor means nothing lifts this case automatically.
            # See SPEC_CONFLICT 1 in the module docstring.
            spec_conflicts.append("RISK-8b:rain_dry_sensor")
        if r_score <= 0.25 and s_score >= 0.75:
            conflicts.append(
                Conflict(
                    "sensor_vs_rain",
                    "Sensors show water rising while the forecast does not; the forecast "
                    "model appears to be under-predicting.",
                )
            )
    if i_score is not None and s_score is not None:
        if i_score >= 0.6 and s_score <= 0.25:
            conflicts.append(
                Conflict(
                    "reports_vs_sensor",
                    "Verified reports indicate flooding where sensors read low. Crowd "
                    "evidence is retained, not overruled.",
                )
            )
    if s_score is not None and used_sensors:
        ratios = [r.depth_m / r.effective_threshold() for r in used_sensors]
        if len(ratios) >= 2 and max(ratios) >= 0.6 and min(ratios) <= 0.2:
            conflicts.append(
                Conflict(
                    "sensor_cluster",
                    "Sensors disagree strongly; the outlier is shown rather than averaged "
                    "into the cluster.",
                )
            )

    # ---- 8. Reason lines (top contributors, no fabricated precision) ----------
    if r_score is not None:
        # r_score is not None only when at least one horizon was supplied, so `parts`
        # cannot be empty here. The list is still built conditionally so a caller that
        # supplies only one horizon gets only that horizon named.
        parts = []
        if inputs.rain_6h_mm is not None:
            parts.append(f"{inputs.rain_6h_mm:.0f} mm forecast in 6 h")
        if inputs.rain_24h_mm is not None:
            parts.append(f"{inputs.rain_24h_mm:.0f} mm in 24 h")
        reasons.append("rain: " + ", ".join(parts))
    if s_score is not None and used_sensors:
        worst = max(used_sensors, key=lambda r: r.depth_m / r.effective_threshold())
        pct = 100.0 * worst.depth_m / worst.effective_threshold()
        reasons.append(f"sensor {worst.sensor_id} at {pct:.0f} % of threshold")
        if any(r.simulated for r in used_sensors):
            reasons.append("sensor data is SIMULATED, not measured")
    reasons.extend(sensor_notes)
    if i_score is not None and inputs.verified_reports:
        reasons.append(f"{len(inputs.verified_reports)} verified report(s)")
    if c_score is not None and inputs.roads is not None:
        if inputs.roads.closed_count:
            reasons.append(f"{inputs.roads.closed_count} operator-confirmed closure(s)")
        reasons.append(f"{inputs.roads.affected_fraction * 100:.0f} % of roads affected")
    reasons.extend(floor_reasons)

    # ---- 9. Honesty about the model itself -----------------------------------
    reasons.append(
        "risk level is an unvalidated heuristic based on forecast, sensors and reports; "
        "it does not predict actual flood depth"
    )

    if missing:
        reasons.append(
            "based on "
            f"{len(present)} of 5 inputs; missing: {', '.join(sorted(missing))}"
        )
    if insufficient:
        reasons.append(
            f"insufficient evidence: only {coverage * 100:.0f} % of the input weight is "
            f"available; confidence is low but severity is NOT reduced"
        )

    return RiskResult(
        score=score,
        level=level,
        coverage=coverage,
        confidence=confidence,
        insufficient_evidence=insufficient,
        missing_inputs=tuple(sorted(missing)),
        precaution=floor,
        conflicts=tuple(conflicts),
        reasons=tuple(reasons),
        simulated=inputs.simulated,
        components=components,
        spec_conflicts=tuple(spec_conflicts),
        score_level=score_level,
    )
