"""Route API models.

Only fields the public map needs. Deliberately absent: any internal edge ids, operator
identity, authorization state, or raw cost internals.

`classification` and `hazard_class` are carried as server-computed values so the client
cannot recompute a friendlier one (Stage 3 §9 step 5).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.api.models import Provenance

HazardClass = Literal["clear", "hazard_crossing"]
Band = Literal["high", "moderate", "low", "none"]
Classification = Literal["eligible", "marginal", "hazard_crossing"]


class LatLon(BaseModel):
    lat: float
    lon: float


class RouteLegOut(BaseModel):
    """One segment, with its status and whether it is verified evidence.

    `status` uses the same vocabulary as the database: open / affected / closed / unknown.
    `unknown` is never presented as safe — the client must label it.
    """

    from_: LatLon = Field(alias="from", serialization_alias="from")
    to: LatLon
    length_m: float
    status: Literal["open", "affected", "closed", "unknown"]
    verified: bool
    synthetic: bool

    model_config = {"populate_by_name": True}


class RouteOut(BaseModel):
    id: str = Field(description="Stable identifier for this response's ordering, e.g. 'route-1'")
    rank: int = Field(description="1-based position in the ranked list. 1 is the recommendation.")
    geometry: list[LatLon] = Field(
        description="Ordered coordinates actually returned by the search. Nothing is invented."
    )
    distance_m: float
    duration_s: float = Field(
        description="Estimated assuming unimpeded travel. Never presented as a live ETA."
    )
    hazard_class: HazardClass
    classification: Classification
    coverage_pct: float = Field(
        description="Length-weighted share of the route carrying verified, fresh status."
    )
    band: Band
    recommended: bool = Field(
        description="True only for rank 1 when the route is clear and coverage is "
        "moderate-or-better. A hazard-crossing or low-coverage route is never recommended."
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Honest, non-reassuring statements about what is unknown.",
    )
    label: str = Field(
        description="One-line characterisation using the permitted vocabulary only."
    )
    legs: list[RouteLegOut]
    phase: Literal[1, 2] = Field(
        description="1 = searched without closed edges; 2 = closures restored because no "
        "clear route existed. Phase 2 routes are always hazard_crossing."
    )
    mean_elevation_m: float | None = Field(
        default=None,
        description="Approximate static context (SRTM 30 m, +/-4 m). Used only as a final "
        "tie-break; never to rank streets or predict depth.",
    )
    elevation_used_as_tiebreak: bool = False
    synthetic: bool
    notes: list[str] = Field(default_factory=list)


class RouteResponseOut(BaseModel):
    schema_version: str = Field(
        default="1",
        description="Bumped when a field changes meaning. Present so a consumer can refuse "
        "an unfamiliar shape rather than silently misread it.",
    )
    routes: list[RouteOut]
    refused: bool
    refusal_reason: str | None = None
    all_routes_hazard_crossing: bool = False
    best_available_is_uncertain: bool = False
    snap_from_m: float | None = None
    snap_to_m: float | None = None
    synthetic: bool
    provenance: Provenance
    notes: list[str] = Field(default_factory=list)

    # Which road-status source actually produced these results. Reported so a consumer can
    # tell persisted, database-backed status from the labelled demo generator — the two are
    # never silently interchangeable.
    status_source: Literal[
        "persisted",
        "seed_generator",
        "seed_generator_fallback_after_error",
        "seed_generator_fallback_no_mapping",
    ] = "seed_generator"
    status_records_matched: int = Field(
        default=0,
        description="How many persisted road-status records matched a graph edge. Zero means "
        "no persisted status applied, so a labelled demo profile was used.",
    )
    status_profile: Literal["baseline", "demo_clear"] = Field(
        default="baseline",
        description="Which status profile produced these results. 'demo_clear' is an explicitly "
        "labelled demo fixture, not live road-status evidence.",
    )
    profile_is_demo_fixture: bool = Field(
        default=False,
        description="True when the profile exists purely to make a demonstration legible. Its "
        "closures are synthetic demo data, never real reports.",
    )
