"""Typed API response models.

Design rules encoded here, from Stage 3 §6 and the M6 brief:

  * Every public response carries a `provenance` envelope. The chip is computed
    server-side (`PROV-1`), never by the client.
  * Forecast and observation are distinguishable by a required `kind` field on every value.
  * `model_run_at` may only be non-null when the provider actually supplied it (N-1).
  * Simulated readings carry `simulated: true` and a literal "SIMULATED" label.
  * No model in this module has a field that could carry credentials, draft alerts, audit
    rows, operator identity, or internal authorization state. The models are an allow-list,
    not a redaction step — a privileged field cannot leak because there is nowhere to put it.

The `Literal` types are load-bearing: they make an accidental relabel a validation error
rather than a silent data-integrity failure.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Provenance envelope (Stage 3 §6 / PROV-1)
# ---------------------------------------------------------------------------

ProvenanceChip = Literal["verified", "reported", "estimated", "stale", "no_data"]
DataMode = Literal["LIVE", "SIMULATED", "MIXED"]


class SourceRef(BaseModel):
    """One upstream source, named so attribution is always possible."""

    name: str = Field(description="e.g. 'Open-Meteo'")
    model_run_at: datetime | None = Field(
        default=None,
        description=(
            "Model run time, ONLY if the provider supplied it. For Open-Meteo's default "
            "forecast endpoint this is null (limitation N-1); it must never be inferred "
            "from the fetch time."
        ),
    )


class Provenance(BaseModel):
    chip: ProvenanceChip
    fetched_at: datetime | None = Field(
        default=None, description="When THIS SERVICE retrieved the data."
    )
    stale_after_s: int | None = None
    simulated: bool = Field(
        default=False, description="True if any value in the payload is synthetic."
    )
    data_mode: DataMode
    sources: list[SourceRef] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------

Kind = Literal["forecast", "observation"]


class HourlyRainOut(BaseModel):
    at: datetime
    precipitation_mm: float | None = Field(
        default=None, description="None means the provider omitted this hour. Not zero."
    )
    probability_pct: float | None = None
    kind: Kind = Field(
        description="Always 'forecast' from this endpoint. An observation would need a "
        "different source and a different label."
    )


class ForecastOut(BaseModel):
    """The public forecast payload.

    Deliberately contains no 'heavy rain' classification: no threshold is approved (B13).
    """

    ok: bool
    hours: list[HourlyRainOut]
    total_mm: float
    max_hourly_mm: float | None
    units: str = "mm"
    provider_units_original: str | None
    latitude: float | None
    longitude: float | None
    error: str | None = None
    summary: str = Field(
        description="Honest one-line description produced by the adapter. Contains no "
        "invented severity classification."
    )
    provenance: Provenance


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------


class SensorReadingOut(BaseModel):
    """One simulated reading.

    `simulated` is `Literal[True]`: a response claiming a real reading cannot be
    constructed, so the API cannot be talked into relabelling synthetic data.
    """

    sensor_id: str
    depth_m: float
    observed_at: datetime
    threshold_m: float
    fraction_of_threshold: float
    above_threshold: bool
    simulated: Literal[True] = True
    label: Literal["SIMULATED"] = "SIMULATED"


class SensorOut(BaseModel):
    sensor_id: str
    sector_id: str
    profile: str
    lat: float
    lon: float
    threshold_m: float = Field(
        description="Prototype threshold (D28). Not a real municipal flood threshold."
    )
    health: Literal["ok", "degraded", "offline"]
    last_reading_age_s: float | None
    latest: SensorReadingOut | None
    simulated: Literal[True] = True
    label: Literal["SIMULATED"] = "SIMULATED"
    notes: list[str] = Field(default_factory=list)


class SensorsOut(BaseModel):
    """The public sensor payload, plus an honest summary of the feed."""

    sensors: list[SensorOut]
    available: bool = Field(
        description="False when the feed produced nothing. Distinct from 'all offline'."
    )
    any_offline: bool
    simulated: Literal[True] = True
    provenance: Provenance


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class GraphExtent(BaseModel):
    """Measured properties of the loaded road extract.

    Deliberately NOT called "coverage": 1,084 km of street length inside an 81 km2 bounding box
    is a fact about the extract, and it would be wrong to present it as a fraction of Guayaquil.
    """

    synthetic: bool
    segments: int
    nodes: int
    total_street_length_km: float = Field(
        description="Sum of unique physical segment lengths. Street length, NOT geographic area "
        "coverage and NOT a share of the city."
    )
    bbox_span_km: dict[str, float] = Field(
        default_factory=dict,
        description="N-S and E-W span of the bounding box, for honest framing of extent.",
    )
    osm_timestamp: str | None = None
    source: str | None = None


class HealthOut(BaseModel):
    """Local-development health signal. Exposes dependency *state*, never configuration."""

    status: Literal["ok", "degraded"]
    service: str = "guaradar-api"
    forecast_source: Literal["ok", "unavailable"] | None = None
    notes: list[str] = Field(default_factory=list)
    # Measured graph facts, so the UI never has to hardcode a statistic that can drift.
    # These are counts of what is IN the extract, not a claim about city coverage.
    graph_extent: GraphExtent | None = None
