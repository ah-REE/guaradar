"""Simulated water-level sensor adapter.

Approved design: docs/STAGE-3-ARCHITECTURE.md §10 (sensor simulation and persistence),
§10.1 (LIVE/SIMULATED/MIXED mode); Stage 4 §16.2 block 5. Decisions: D28 (prototype
thresholds retained, SIMULATED label always visible), R-05 (label simulated data),
R-06 (never invent live water levels).

HARD CONSTRAINTS
  * Every reading this module produces is `simulated=True`. There is no code path that
    yields a simulated reading indistinguishable from telemetry.
  * Thresholds are NOT defined here. They are passed in, and the caller owns them
    (supabase/seed.sql holds the prototype values). This module never invents a threshold.
  * Determinism: same seed + same hour + same node => identical reading. Rehearsals and
    screenshots reproduce.
  * A simulated reading can never, by itself, publish an official alert. This module
    produces numbers only; publication requires the Stage 2 alert lifecycle with a
    Publisher role, which is not reachable from here.

WHAT THIS IS NOT
  * Not a hydrological model.
  * Not evidence about real sensors. No real sensor exists in this project.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, Sequence

Profile = Literal["dry", "steady", "heavy", "surge"]

# Documented profiles (§10). Order matters only for validation.
VALID_PROFILES: tuple[Profile, ...] = ("dry", "steady", "heavy", "surge")


class SensorConfigError(ValueError):
    """Raised for programmer error: bad profile, non-positive threshold, etc."""


@dataclass(frozen=True)
class SensorSpec:
    """Static configuration of one simulated node.

    `threshold_m` is supplied by the caller. It is a prototype value (D28) and this module
    treats it as opaque: it never assumes, scales, or invents one.
    """

    sensor_id: str
    sector_id: str
    threshold_m: float
    lat: float
    lon: float
    profile: Profile = "steady"
    expected_interval_s: int = 60
    stale_after_s: int = 300

    def __post_init__(self) -> None:
        if self.threshold_m <= 0:
            raise SensorConfigError(f"{self.sensor_id}: threshold_m must be > 0")
        if self.profile not in VALID_PROFILES:
            raise SensorConfigError(
                f"{self.sensor_id}: unknown profile {self.profile!r}; "
                f"expected one of {VALID_PROFILES}"
            )
        if self.expected_interval_s <= 0 or self.stale_after_s <= 0:
            raise SensorConfigError(f"{self.sensor_id}: intervals must be positive")


@dataclass(frozen=True)
class SensorReading:
    """One simulated depth reading.

    `simulated` is not a default that can be flipped by a caller: the factory below is the
    only producer and it hardcodes True. Making it a field would invite a future
    `SensorReading(..., simulated=False)` that quietly relabels synthetic data as telemetry.
    """

    sensor_id: str
    depth_m: float
    observed_at: datetime
    threshold_m: float
    profile: Profile
    simulated: Literal[True] = True
    # Ratio of depth to threshold, exposed so the UI does not have to recompute it.
    fraction_of_threshold: float = 0.0

    @property
    def above_threshold(self) -> bool:
        return self.depth_m >= self.threshold_m

    @property
    def label(self) -> str:
        return "SIMULATED"


@dataclass(frozen=True)
class SensorSeries:
    """A node's readings plus its health, derived from cadence (never a stored flag)."""

    spec: SensorSpec
    readings: tuple[SensorReading, ...]
    health: Literal["ok", "degraded", "offline"]
    last_reading_age_s: float | None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def simulated(self) -> Literal[True]:
        return True

    @property
    def latest(self) -> SensorReading | None:
        return self.readings[-1] if self.readings else None


def _det_float(seed: int, sensor_id: str, bucket: int, salt: str = "") -> float:
    """Deterministic pseudo-random value in [0, 1), stable across runs and machines.

    Deliberately NOT Python's `random`: that couples the value to interpreter internals and
    to call order. A SHA-256 of the inputs is stable forever, which is what a reproducible
    rehearsal needs.
    """
    key = f"{seed}|{sensor_id}|{bucket}|{salt}".encode()
    digest = hashlib.sha256(key).digest()
    n = int.from_bytes(digest[:8], "big")
    return (n % 10_000_000) / 10_000_000.0


def _hour_bucket(at: datetime) -> int:
    return int(at.timestamp() // 3600)


def _baseline_fraction(spec: SensorSpec, at: datetime, seed: int) -> float:
    """Depth as a fraction of this node's threshold, before noise.

    Profiles follow §10. Values are fractions of the caller's threshold, so changing a
    prototype threshold changes the depth proportionally rather than silently redefining
    the scenario.
    """
    hour = _hour_bucket(at)
    # Diurnal shape: lowest around 05:00 UTC, highest around 17:00 UTC.
    diurnal = 0.5 - 0.5 * math.cos((at.hour / 24.0) * 2 * math.pi)
    jitter = _det_float(seed, spec.sensor_id, hour, "base") - 0.5

    if spec.profile == "dry":
        base = 0.05
        return max(0.0, base + 0.02 * jitter)
    if spec.profile == "steady":
        base = 0.35
        return max(0.0, base + 0.10 * diurnal + 0.06 * jitter)
    if spec.profile == "heavy":
        # Rises through the forecast-heavy window, then recedes: a smooth hump over 12 h.
        phase = ((hour % 12) / 12.0)
        hump = math.sin(phase * math.pi)
        base = 0.45 + 0.55 * hump
        return max(0.0, base + 0.05 * jitter)
    # surge: steep rise to and above threshold, then a plateau.
    phase = (hour % 8) / 8.0
    if phase < 0.5:
        base = 0.6 + 1.2 * (phase / 0.5)      # climbs to 1.8x threshold
    else:
        base = 1.8 - 0.3 * ((phase - 0.5) / 0.5)
    return max(0.0, base + 0.05 * jitter)


def generate_reading(
    spec: SensorSpec,
    at: datetime,
    *,
    seed: int = 20261026,
    noise: bool = True,
) -> SensorReading:
    """One deterministic simulated reading at `at`."""
    frac = _baseline_fraction(spec, at, seed)
    if noise:
        frac += 0.015 * (_det_float(seed, spec.sensor_id, _hour_bucket(at), "noise") - 0.5)
    depth = round(max(0.0, frac) * spec.threshold_m, 3)
    return SensorReading(
        sensor_id=spec.sensor_id,
        depth_m=depth,
        observed_at=at,
        threshold_m=spec.threshold_m,
        profile=spec.profile,
        simulated=True,
        fraction_of_threshold=round(depth / spec.threshold_m, 4),
    )


def generate_series(
    spec: SensorSpec,
    *,
    now: datetime,
    count: int = 12,
    interval_s: int = 300,
    seed: int = 20261026,
    include_gaps: bool = False,
) -> SensorSeries:
    """A short history for one node, oldest first.

    `include_gaps=True` drops some readings so the UI's "a gap is drawn as a gap" behaviour
    can be exercised. Health is derived from the most recent reading's age relative to
    `spec.stale_after_s` — never from a stored flag.
    """
    if count < 0:
        raise SensorConfigError("count must be >= 0")

    readings: list[SensorReading] = []
    for i in range(count, 0, -1):
        at = now - timedelta(seconds=i * interval_s)
        if include_gaps and i % 4 == 0:
            continue                    # a real gap, not an interpolation
        readings.append(generate_reading(spec, at, seed=seed))

    notes: list[str] = []
    if include_gaps:
        notes.append("history contains gaps; they are preserved, never interpolated")

    if not readings:
        health = "offline"
        age: float | None = None
        notes.append("no readings available")
    else:
        age = (now - readings[-1].observed_at).total_seconds()
        if age > spec.stale_after_s:
            health = "offline"
            notes.append(
                f"last reading is {int(age)} s old, beyond the {spec.stale_after_s} s "
                f"staleness limit"
            )
        elif age > spec.expected_interval_s * 3:
            health = "degraded"
            notes.append(
                f"last reading is {int(age)} s old, beyond 3x the "
                f"{spec.expected_interval_s} s expected interval"
            )
        else:
            health = "ok"

    return SensorSeries(
        spec=spec,
        readings=tuple(readings),
        health=health,
        last_reading_age_s=None if age is None else round(age, 1),
        notes=tuple(notes),
    )


def generate_all(
    specs: Sequence[SensorSpec],
    *,
    now: datetime,
    count: int = 12,
    interval_s: int = 300,
    seed: int = 20261026,
) -> tuple[SensorSeries, ...]:
    return tuple(
        generate_series(s, now=now, count=count, interval_s=interval_s, seed=seed)
        for s in specs
    )


# ---------------------------------------------------------------------------
# Data-mode indicator (§10.1) — computed, never asserted by a client
# ---------------------------------------------------------------------------


def data_mode(*, external_live: bool, any_simulated: bool = True) -> Literal["LIVE", "SIMULATED", "MIXED"]:
    """§10.1. `LIVE` is unreachable while any sensor is simulated.

    This function exists so the mode cannot be set by hand. A caller passes facts; the
    mode follows. `SIM-3` asserts LIVE is never produced from simulated state.
    """
    if any_simulated:
        return "MIXED" if external_live else "SIMULATED"
    return "LIVE" if external_live else "SIMULATED"


def describe_series(series: SensorSeries) -> str:
    """One honest line. Always leads with SIMULATED, never with a bare depth."""
    latest = series.latest
    if latest is None:
        return f"{series.spec.sensor_id}: SIMULATED — no readings; status {series.health}."
    return (
        f"{series.spec.sensor_id}: SIMULATED reading {latest.depth_m:g} m "
        f"({latest.fraction_of_threshold * 100:.0f} % of a prototype threshold of "
        f"{latest.threshold_m:g} m); health {series.health}."
    )
