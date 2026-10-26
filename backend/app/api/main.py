"""Guaradar read-only public API.

Endpoints implemented (M6 scope only):
  GET /api/health           — local development / test readiness
  GET /api/public/forecast  — normalized Open-Meteo rainfall forecast
  GET /api/public/sensors   — simulated sensor readings

DELIBERATELY ABSENT
  Any mutation. There is no POST/PATCH/DELETE in this application. No admin route, no
  verification, no alert publication. That is not an oversight to be filled in later
  casually: N-2 records that server-side authorization is unresolved because
  `current_app_role()` trusts a session setting, so a privileged write path must not exist
  until that is fixed and verified.

CLOCK DISCIPLINE
  The current time is supplied by a dependency (`get_now`), not read ad hoc. Tests inject a
  fixed clock, so staleness and fetch ages are deterministic. No business logic calls
  `datetime.now()` directly.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi import status as http_status
from fastapi.middleware.cors import CORSMiddleware

from app.api.models import (
    GraphExtent,
    ForecastOut,
    HealthOut,
    HourlyRainOut,
    Provenance,
    SensorOut,
    SensorReadingOut,
    SensorsOut,
    SourceRef,
)
from app.api.route_models import (
    LatLon,
    RouteLegOut,
    RouteOut,
    RouteResponseOut,
)
from app.ingest.openmeteo import describe, fetch_forecast
from app.routing.graph import (
    DEFAULT_FRESHNESS,
    STATUS_AFFECTED,
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_UNKNOWN,
    Edge,
    EdgeStatus,
    RoadGraph,
    StatusIndex,
    build_synthetic_grid,
)
from app.routing.demo_profiles import build_profile_status
from app.routing.search import find_routes
from app.routing.osm_source import build_graph_from_extract
from app.routing.status_repository import (
    FetchFn,
    StatusLoadResult,
    load_status,
    load_status_by_edge,
)
from app.simulate.sensors import (
    SensorSpec,
    data_mode,
    generate_series,
)

# ---------------------------------------------------------------------------
# Configuration (env only; never logged, never returned)
# ---------------------------------------------------------------------------

OPEN_METEO_BASE_URL = os.environ.get("OPEN_METEO_BASE_URL", "https://api.open-meteo.com/v1")

# The three demo sectors, matching supabase/seed.sql. Kept in one place so the API and the
# seed cannot drift into describing different places.
DEMO_SECTOR_CENTRES: dict[str, tuple[float, float]] = {
    "norte": (-2.1420, -79.9050),
    "centro": (-2.1962, -79.8865),
    "sur": (-2.2200, -79.9100),
}

# Prototype sensor specifications. Thresholds are the D28 values from supabase/seed.sql and
# are passed in here rather than invented by the simulator.
DEMO_SENSORS: tuple[SensorSpec, ...] = (
    SensorSpec("SIM-01", "norte", 1.20, -2.1428, -79.9056, profile="surge"),
    SensorSpec("SIM-02", "norte", 1.00, -2.1495, -79.9023, profile="steady"),
    SensorSpec("SIM-03", "centro", 0.80, -2.1962, -79.8865, profile="heavy"),
    SensorSpec("SIM-04", "sur", 0.90, -2.2207, -79.9089, profile="steady"),
    SensorSpec("SIM-05", "sur", 1.10, -2.2273, -79.9152, profile="surge"),
    SensorSpec("SIM-06", "norte", 0.80, -2.1580, -79.8900, profile="dry"),
)

# Freshness budgets, in seconds. These describe how long a value stays presentable, not how
# correct it is.
FORECAST_STALE_AFTER_S = 3600        # 1 hour: the provider updates far less often than that
SENSOR_STALE_AFTER_S = 300           # 5 minutes

# A sector whose centre is the default forecast location. Callers may override lat/lon, but
# only within Guayaquil's rough envelope — this app must not become a generic weather API.
GUAYAQUIL_BOUNDS = {"lat_min": -2.40, "lat_max": -1.90, "lon_min": -80.10, "lon_max": -79.70}

APP_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Dependencies — overridable in tests
# ---------------------------------------------------------------------------


def get_now() -> datetime:
    """Current UTC time. Overridden in tests; never called directly by handlers."""
    return datetime.now(timezone.utc)


def get_http_get() -> Callable[[str, float], tuple[int, str]] | None:
    """HTTP client override. None means use the adapter's default (urllib).

    Tests return a fake so the suite never touches the network.
    """
    return None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Guaradar public API",
    version=APP_VERSION,
    description=(
        "Read-only public endpoints for the Guaradar flood-resilience prototype. "
        "Sensor data is SIMULATED. Road geometry comes from a bounded OpenStreetMap "
        "extract of central Guayaquil (not city-wide); road STATUS is seed/demo data. "
        "No response asserts that any route is safe."
    ),
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# CORS is restricted to the local dev frontend. A wildcard here would let any page read the
# responses, which is unnecessary for a demo and sets a bad precedent.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,      # no cookies/credentials cross-origin, by design
    allow_methods=["GET"],        # read-only API: GET and OPTIONS only
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/api/health", response_model=HealthOut, tags=["ops"])
def health(now: datetime = Depends(get_now)) -> HealthOut:
    """Liveness probe. Reports dependency state only — no configuration, no secrets.

    The road-graph note is derived from the actual graph rather than hardcoded. It previously
    said "synthetic demo data" unconditionally, which became FALSE once M9 switched the default
    graph to a real OSM extract — a wrong disclosure in either direction is a defect.
    """
    graph = get_graph()
    graph_note = (
        "road graph is synthetic demo data, not Guayaquil's real streets"
        if graph.synthetic
        else (
            "road geometry is a bounded OpenStreetMap extract of central Guayaquil "
            "(not city-wide); road STATUS is seed/demo data"
        )
    )
    # Measured, not declared: unique physical segments so a two-way street is not counted twice.
    unique: dict[tuple[int, int], float] = {}
    for e in graph.edges.values():
        key = (min(e.a, e.b), max(e.a, e.b))
        unique.setdefault(key, e.length_m)
    total_km = sum(unique.values()) / 1000.0

    lats = [n.lat for n in graph.nodes.values()]
    lons = [n.lon for n in graph.nodes.values()]
    span: dict[str, float] = {}
    if lats and lons:
        span = {
            "north_south": round((max(lats) - min(lats)) * 111.0, 1),
            "east_west": round(
                (max(lons) - min(lons)) * 111.0 * math.cos(math.radians(sum(lats) / len(lats))), 1
            ),
        }

    extent = GraphExtent(
        synthetic=graph.synthetic,
        segments=len(unique),
        nodes=len(graph.nodes),
        total_street_length_km=round(total_km, 1),
        bbox_span_km=span,
    )

    return HealthOut(
        status="ok",
        forecast_source=None,   # populated only by a caller that actively probes upstream
        graph_extent=extent,
        notes=[
            "sensor data is SIMULATED",
            graph_note,
            f"server time {now.isoformat()}",
        ],
    )


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------


def _validate_area(lat: float, lon: float) -> None:
    if not (GUAYAQUIL_BOUNDS["lat_min"] <= lat <= GUAYAQUIL_BOUNDS["lat_max"]):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="latitude is outside the supported Guayaquil area",
        )
    if not (GUAYAQUIL_BOUNDS["lon_min"] <= lon <= GUAYAQUIL_BOUNDS["lon_max"]):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="longitude is outside the supported Guayaquil area",
        )


@app.get("/api/public/forecast", response_model=ForecastOut, tags=["public"])
def public_forecast(
    sector: str | None = Query(
        default=None,
        description="One of: norte, centro, sur. Defaults to the city centre.",
    ),
    latitude: float | None = Query(default=None, ge=-90, le=90),
    longitude: float | None = Query(default=None, ge=-180, le=180),
    hours: int = Query(default=24, ge=1, le=48),
    now: datetime = Depends(get_now),
    http_get: Callable[[str, float], tuple[int, str]] | None = Depends(get_http_get),
) -> ForecastOut:
    """Normalized rainfall forecast.

    Never fabricates values: on provider failure the payload says `ok=false` and carries no
    hourly values. `model_run_at` is null unless the provider supplied it (N-1), and the
    fetch time is reported separately so the two cannot be confused.
    """
    # Resolve location. A named sector is the supported path; raw coordinates are allowed
    # only inside Guayaquil's envelope, so this does not become a general weather proxy.
    if sector is not None:
        if sector not in DEMO_SECTOR_CENTRES:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"unknown sector {sector!r}; known: {sorted(DEMO_SECTOR_CENTRES)}",
            )
        lat, lon = DEMO_SECTOR_CENTRES[sector]
    elif latitude is not None and longitude is not None:
        _validate_area(latitude, longitude)
        lat, lon = latitude, longitude
    elif latitude is not None or longitude is not None:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="provide both latitude and longitude, or neither",
        )
    else:
        lat, lon = DEMO_SECTOR_CENTRES["centro"]

    kwargs: dict = {
        "base_url": OPEN_METEO_BASE_URL,
        "latitude": lat,
        "longitude": lon,
        "now": now,
        "forecast_hours": hours,
    }
    if http_get is not None:
        kwargs["http_get"] = http_get

    result = fetch_forecast(**kwargs)
    summary = describe(result, now)

    age_s = result.age_seconds(now)
    if not result.ok:
        chip = "no_data"
    elif age_s is not None and age_s > FORECAST_STALE_AFTER_S:
        chip = "stale"
    else:
        chip = "estimated"     # a forecast is an estimate, never a verification

    notes = list(result.notes)
    if not result.ok:
        notes.append("no rainfall values were returned; nothing was estimated in their place")
    if result.ok and result.model_run_at is None:
        notes.append("model run time unavailable from the provider; only the fetch time is known")

    provenance = Provenance(
        chip=chip,
        fetched_at=result.fetched_at,
        stale_after_s=FORECAST_STALE_AFTER_S,
        simulated=False,       # the forecast itself is real provider output
        data_mode=data_mode(external_live=result.ok, any_simulated=True),
        sources=[
            SourceRef(name=result.source, model_run_at=result.model_run_at),
        ],
        notes=notes,
    )

    return ForecastOut(
        ok=result.ok,
        hours=[
            HourlyRainOut(
                at=h.at,
                precipitation_mm=h.precipitation_mm,
                probability_pct=h.probability_pct,
                kind=h.kind,
            )
            for h in result.hours
        ],
        total_mm=result.total_mm,
        max_hourly_mm=result.max_hourly_mm,
        units="mm",
        provider_units_original=result.provider_units_original,
        latitude=result.latitude,
        longitude=result.longitude,
        error=result.error,
        summary=summary,
        provenance=provenance,
    )


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------


@app.get("/api/public/sensors", response_model=SensorsOut, tags=["public"])
def public_sensors(
    now: datetime = Depends(get_now),
    count: int = Query(default=12, ge=0, le=48),
) -> SensorsOut:
    """Simulated sensor readings.

    There is no request parameter that can mark a reading real: `simulated` is a
    `Literal[True]` in the response model, and the simulator hardcodes it. A caller cannot
    promote data to verified status because no such field exists on the request side.
    """
    series = generate_series_for_all(now=now, count=count)

    sensors: list[SensorOut] = []
    any_offline = False
    for s in series:
        if s.health != "ok":
            any_offline = True
        latest = s.latest
        sensors.append(
            SensorOut(
                sensor_id=s.spec.sensor_id,
                sector_id=s.spec.sector_id,
                profile=s.spec.profile,
                lat=s.spec.lat,
                lon=s.spec.lon,
                threshold_m=s.spec.threshold_m,
                health=s.health,
                last_reading_age_s=s.last_reading_age_s,
                latest=(
                    None
                    if latest is None
                    else SensorReadingOut(
                        sensor_id=latest.sensor_id,
                        depth_m=latest.depth_m,
                        observed_at=latest.observed_at,
                        threshold_m=latest.threshold_m,
                        fraction_of_threshold=latest.fraction_of_threshold,
                        above_threshold=latest.above_threshold,
                        simulated=True,
                        label="SIMULATED",
                    )
                ),
                simulated=True,
                label="SIMULATED",
                notes=list(s.notes),
            )
        )

    available = any(s.latest is not None for s in sensors)

    provenance = Provenance(
        chip="estimated" if available else "no_data",
        fetched_at=now,
        stale_after_s=SENSOR_STALE_AFTER_S,
        simulated=True,
        data_mode=data_mode(external_live=False, any_simulated=True),
        sources=[SourceRef(name="Guaradar sensor simulator")],
        notes=[
            "all sensor readings are SIMULATED; no real telemetry exists in this project",
            "thresholds are prototype values, not municipal flood thresholds",
        ],
    )

    return SensorsOut(
        sensors=sensors,
        available=available,
        any_offline=any_offline,
        simulated=True,
        provenance=provenance,
    )


def generate_series_for_all(*, now: datetime, count: int):
    """Indirection so tests can monkeypatch generation without touching the route."""
    return tuple(
        generate_series(spec, now=now, count=count, interval_s=300) for spec in DEMO_SENSORS
    )


# ---------------------------------------------------------------------------
# Route (read-only)
# ---------------------------------------------------------------------------

# The demo graph is built once per process. It is immutable topology; status is applied per
# request, which is why no route result is cached (D14).
_GRAPH_CACHE: dict[str, Any] = {}


def demo_route_points() -> list[dict]:
    """Pick two real graph nodes as route endpoints.

    With the OSM extract the sensor sites mostly lie outside the bounded area, so hardcoding
    them would make every route refuse. Points are derived from actual nodes instead, and
    labelled as demo endpoints rather than claimed to be sensors.
    """
    graph = get_graph()
    ids = sorted(graph.nodes)
    if len(ids) < 2:
        return []
    a, b = graph.nodes[ids[0]], graph.nodes[ids[-1]]
    return [
        {"id": "P1", "label": "north-west node", "at": {"lat": a.lat, "lon": a.lon}},
        {"id": "P2", "label": "south-east node", "at": {"lat": b.lat, "lon": b.lon}},
    ]


def get_graph() -> RoadGraph:
    """Return the road graph: real OSM when the extract is present, else synthetic.

    M9 priority: a genuine extract of central Guayaquil now exists, so the default is a REAL
    graph whose edge ids encode source identity. The synthetic builder remains as a labelled
    fallback for environments without the extract, so the suite and a bare checkout still work.
    """
    if "graph" in _GRAPH_CACHE:
        return _GRAPH_CACHE["graph"]

    try:
        osm_build = build_graph_from_extract()
        _GRAPH_CACHE["graph"] = osm_build.graph
        _GRAPH_CACHE["source"] = "osm"          # type: ignore[assignment]
        return osm_build.graph
    except (FileNotFoundError, ValueError):
        # Extract missing or unusable: fall back, and keep the synthetic label honest.
        places = {s.sensor_id: (s.lat, s.lon) for s in DEMO_SENSORS}
        graph = build_synthetic_grid(DEMO_SECTOR_CENTRES, extra_places=places)
        _GRAPH_CACHE["graph"] = graph
        _GRAPH_CACHE["source"] = "synthetic"    # type: ignore[assignment]
        return graph


def graph_source() -> str:
    """Which source the cached graph came from. 'osm' or 'synthetic'."""
    get_graph()
    return _GRAPH_CACHE.get("source", "synthetic")  # type: ignore[return-value]


def build_demo_status(now: datetime) -> StatusIndex:
    """Deterministic demo road status — LABELLED FALLBACK ONLY.

    This is no longer the primary source. `get_route_status` reads persisted records via the
    repository (closing N-7) and falls back to this generator only when persistence is not
    configured, the feed fails, or no persisted record matches a graph edge. Every fallback is
    reported in the response, never silent.

    Pattern, walked by edge index:
      * every 29th edge: closed          (a genuine obstruction to avoid)
      * every 13th edge: affected        (passable, penalised x2.5)
      * every other edge: verified open  (counts toward coverage)
      * otherwise:        no record       (stays `unknown`, which lowers coverage)
    """
    graph = get_graph()
    statuses: list[EdgeStatus] = []
    for i, eid in enumerate(sorted(graph.edges)):
        if i % 29 == 0:
            statuses.append(EdgeStatus(eid, STATUS_CLOSED, now - timedelta(minutes=10)))
        elif i % 13 == 0:
            statuses.append(EdgeStatus(eid, STATUS_AFFECTED, now - timedelta(minutes=5)))
        elif i % 2 != 0:
            statuses.append(EdgeStatus(eid, STATUS_OPEN, now - timedelta(minutes=5)))
    return StatusIndex(statuses, now=now, freshness=DEFAULT_FRESHNESS)


# Set True only when a trusted server-side connection is configured. Default False mirrors
# job.DATABASE_WRITES_ENABLED: with N-2 open, nothing should assume a database is reachable.
STATUS_PERSISTENCE_ENABLED = False


def get_status_fetch() -> FetchFn | None:
    """Status row fetcher. None means 'no trusted connection configured'.

    Overridden in tests with a fake fetcher, and in deployment with a real server-side
    connection. This dependency never reads a role, session setting, or request parameter.
    """
    return None


def load_route_status(
    graph: RoadGraph,
    *,
    now: datetime,
    fetch: FetchFn | None,
    profile: str = "baseline",
) -> StatusLoadResult:
    """Load persisted status, falling back to the labelled demo generator.

    Fallback happens for three reported reasons:
      * persistence is not enabled (no trusted connection),
      * the persisted feed raised, or
      * the persisted set matched no graph edge, so applying it would leave every route at
        0 % coverage and the screen empty.

    Critique of the third case, stated openly: switching to a generator because the database
    had nothing applicable is a demo convenience, not a data-integrity win. It is acceptable
    only because the fallback is labelled as seed data in every response and never claims to
    be persisted status.
    """
    if not STATUS_PERSISTENCE_ENABLED or fetch is None:
        index, info = build_profile_status(graph, now, profile)  # type: ignore[arg-type]
        return StatusLoadResult(
            index=index,
            records_fetched=0,
            records_applied=0,
            matched_edge_count=0,
            notes=(
                f"road status comes from the labelled demo profile '{info.name}' "
                f"({info.label}), not from persisted records; a trusted database connection "
                f"is not configured (N-2)",
                ("DEMO FIXTURE — " + info.description)
                if info.is_demo_fixture
                else info.description,
                f"{info.closure_count} closure(s) in this profile; every status here is seed "
                f"or demo data, not a live municipal feed",
            ),
        )

    # M9: prefer the stable edge-identity join. `load_status` (legacy road_segment_id join) is
    # kept for the seeded demo dataset, which predates the identity columns.
    load = load_status_by_edge(
        graph_edge_ids=graph.edges.keys(),
        fetch=fetch,
        now=now,
        default_freshness=DEFAULT_FRESHNESS,
    )

    if load.error is not None:
        index, info = build_profile_status(graph, now, profile)  # type: ignore[arg-type]
        return StatusLoadResult(
            index=index,
            records_fetched=0,
            records_applied=0,
            matched_edge_count=0,
            error=load.error,
            notes=(
                f"persisted status feed failed ({load.error}); fell back to demo profile "
                f"'{info.name}'",
                ("DEMO FIXTURE — " + info.description)
                if info.is_demo_fixture
                else info.description,
                "the failure is reported rather than hidden, and nothing was marked verified",
            ),
        )

    if load.matched_edge_count == 0:
        index, info = build_profile_status(graph, now, profile)  # type: ignore[arg-type]
        return StatusLoadResult(
            index=index,
            records_fetched=load.records_fetched,
            records_applied=0,
            matched_edge_count=0,
            notes=load.notes + (
                f"{load.records_fetched} persisted record(s) fetched but none matched a graph "
                f"edge; no identifier mapping exists between the seed segment ids (1001+) and "
                f"the synthetic graph edge ids (0+), and none was invented. Using the labelled "
                f"demo generator so the screen is not empty.",
            ),
        )

    return load


def get_route_status(
    now: datetime = Depends(get_now),
    fetch: FetchFn | None = Depends(get_status_fetch),
    profile: str = "baseline",
) -> StatusIndex:
    """Status dependency for the route endpoint.

    Records the load outcome so the handler can report which source was used. Uses a plain
    dict rather than a widened return type to keep the dependency signature simple.
    """
    graph = get_graph()
    load = load_route_status(graph, now=now, fetch=fetch, profile=profile)
    _LAST_STATUS_LOAD["result"] = load
    return load.index


# Cleared and repopulated per request by get_route_status. Read by the route handler.
_LAST_STATUS_LOAD: dict[str, StatusLoadResult | None] = {"result": None}


@app.get("/api/public/route", response_model=RouteResponseOut, tags=["public"])
def public_route(
    from_lat: float = Query(alias="from_lat", ge=-90, le=90),
    from_lon: float = Query(alias="from_lon", ge=-180, le=180),
    to_lat: float = Query(alias="to_lat", ge=-90, le=90),
    to_lon: float = Query(alias="to_lon", ge=-180, le=180),
    alternatives: int = Query(default=3, ge=1, le=3),
    profile: str = Query(
        default="baseline",
        description=(
            "Status profile. 'baseline' is the default demo generator (dense closures, so most "
            "cross-sector routes must cross one). 'demo_clear' is an explicitly labelled DEMO "
            "FIXTURE with 6 synthetic closures that exists only so an eligible route can be "
            "demonstrated. It writes nothing and is isolated from persisted data."
        ),
    ),
    now: datetime = Depends(get_now),
    fetch: FetchFn | None = Depends(get_status_fetch),
) -> RouteResponseOut:
    """Two-phase route search between two points.

    Safety properties, all enforced in app/routing/search.py and asserted by tests:
      * phase 1 searches a graph with closed edges ABSENT, so a closure cannot appear in a
        clear route;
      * phase 2 runs only when phase 1 finds nothing, and every route it returns is
        `hazard_crossing` and never recommended;
      * low/zero-coverage routes are served but never recommended;
      * no route is described as safe — the permitted wording is "no known hazards".

    Origin and destination are required coordinates, not fabricated. Snapping more than
    60 m from a road is refused with a reason rather than guessed.
    """
    _validate_area(from_lat, from_lon)
    _validate_area(to_lat, to_lon)

    if profile not in ("baseline", "demo_clear"):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unknown profile {profile!r}; expected 'baseline' or 'demo_clear'",
        )

    graph = get_graph()
    status = get_route_status(now, fetch, profile)
    load = _LAST_STATUS_LOAD.get("result")

    status_source: str = "seed_generator"
    # These three disclosures are MANDATORY on every route response and are never replaced by
    # status-source notes. A regression test caught an earlier version that dropped the
    # synthetic-network disclosure when status notes were appended, so they are now kept in a
    # separate invariant list and always prepended.
    # M9: the graph is now REAL OSM geometry, so the old "synthetic demo data"
    # disclosure would be false. What remains synthetic/seed is the road STATUS.
    is_osm = not graph.synthetic
    INVARIANT_NOTES: list[str] = [
        (
            "road geometry is real OpenStreetMap data for a small central-Guayaquil "
            "extract; it is not city-wide"
            if is_osm
            else "road network is synthetic demo data, not Guayaquil's real streets"
        ),
        (
            "road STATUS is seed/demo data, not a live municipal feed"
            if is_osm
            else "coverage percentages describe this demo dataset only"
        ),
        "a path existing in the data does not mean a road is safe to travel",
    ]
    status_notes: list[str] = list(INVARIANT_NOTES)
    matched = 0
    if load is not None:
        matched = load.matched_edge_count
        if load.matched_edge_count > 0 and load.error is None:
            status_source = "persisted"
        elif load.error is not None:
            status_source = "seed_generator_fallback_after_error"
        elif load.records_fetched > 0:
            status_source = "seed_generator_fallback_no_mapping"
        # Status notes are APPENDED, never substituted: the disclosures above must survive.
        status_notes = list(load.notes) + INVARIANT_NOTES

    try:
        result = find_routes(
            graph,
            status,
            (from_lat, from_lon),
            (to_lat, to_lon),
            max_alternatives=alternatives,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    def coord(node_id: int) -> LatLon:
        n = graph.nodes[node_id]
        return LatLon(lat=n.lat, lon=n.lon)

    routes_out: list[RouteOut] = []
    for idx, r in enumerate(result.routes, start=1):
        # Geometry is derived from the legs the search actually returned. Nothing is
        # smoothed, extrapolated, or snapped to a real street network.
        points: list[LatLon] = []
        legs_out: list[RouteLegOut] = []
        for leg in r.legs:
            a = coord(leg.from_node)
            b = coord(leg.to_node)
            if not points:
                points.append(a)
            points.append(b)
            legs_out.append(
                RouteLegOut(
                    **{
                        "from": a,
                        "to": b,
                        "length_m": leg.length_m,
                        "status": leg.status,
                        "verified": leg.verified,
                        "synthetic": graph.synthetic,
                    }
                )
            )

        warnings: list[str] = []
        if r.hazard_class == "hazard_crossing":
            warnings.append(
                "This route crosses a road recorded as closed. It is shown only because no "
                "route avoids every closure."
            )
        if r.band in ("low", "none"):
            warnings.append(
                f"Only {r.coverage_pct:.0f} % of this route has verified status. Most of it "
                f"is unknown — that is not the same as clear."
            )
        unknown_count = sum(1 for leg in r.legs if leg.status == STATUS_UNKNOWN)
        if unknown_count:
            warnings.append(
                f"{unknown_count} segment(s) have no road-status information at all."
            )
        warnings.append(
            "Road conditions come from demo seed data, not a live municipal feed."
        )

        routes_out.append(
            RouteOut(
                id=f"route-{idx}",
                rank=idx,
                geometry=points,
                distance_m=r.distance_m,
                duration_s=r.duration_s,
                hazard_class=r.hazard_class,
                classification=r.classification,
                coverage_pct=r.coverage_pct,
                band=r.band,
                recommended=r.recommended,
                warnings=warnings,
                label=r.label,
                legs=legs_out,
                phase=r.phase,
                mean_elevation_m=r.mean_elevation_m,
                elevation_used_as_tiebreak=r.elevation_used_as_tiebreak,
                synthetic=graph.synthetic,
                notes=list(r.notes),
            )
        )

    provenance = Provenance(
        chip="no_data" if result.refused else "estimated",
        fetched_at=now,
        stale_after_s=int(DEFAULT_FRESHNESS.total_seconds()),
        simulated=True,          # the graph and its statuses are synthetic
        data_mode=data_mode(external_live=False, any_simulated=True),
        sources=[SourceRef(name="Guaradar synthetic demo graph")],
        notes=status_notes,
    )

    return RouteResponseOut(
        routes=routes_out,
        refused=result.refused,
        refusal_reason=result.refusal_reason,
        all_routes_hazard_crossing=result.all_routes_hazard_crossing,
        best_available_is_uncertain=result.best_available_is_uncertain,
        snap_from_m=result.snap_from_m,
        snap_to_m=result.snap_to_m,
        synthetic=graph.synthetic,
        provenance=provenance,
        notes=list(result.notes),
        status_source=status_source,
        status_records_matched=matched,
        status_profile=profile,
        profile_is_demo_fixture=(profile == "demo_clear"),
    )
