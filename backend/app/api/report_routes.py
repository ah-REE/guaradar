"""HTTP layer for community road reports (features A–E).

ROUTER, NOT DIRECTLY ON THE APP
  These endpoints are mounted on `APIRouter`s for the same reason `auth_routes.py` is: the
  project has a standing test that no mutation verb is declared directly on the application
  object, which was how it encoded "no unauthenticated mutation path". Declaring mutations on a
  router keeps that test meaningful — it still fails if someone bolts a mutation straight onto
  the app — while this module makes each mutation's authorisation explicit at the point of
  declaration. Every mutation here depends on `current_user` or `require_admin`.

AUTHORISATION IS PER ROUTE AND SERVER-SIDE
  Public reads carry no dependency beyond the optional identity, so an anonymous visitor can
  see reports. Every mutation depends on `current_user`. Every admin route depends on
  `require_admin(...)`, which resolves the role from the session row.

  Crucially, NO REQUEST MODEL HERE HAS A `role` OR `status`/`decision` FIELD, and all of them
  are `extra="forbid"`. A public user cannot set their own role, and cannot promote their own
  report to `blocked_verified`, because there is no field to put it in. The 422 from
  `extra="forbid"` is the observable proof, and a test asserts it.

PRIVACY OF POSITION
  Public responses are built from `public_lat`/`public_lon` only — the snapped road point, or a
  coarsened cell centre when nothing matched. `gps_lat`/`gps_lon` are read exclusively by the
  admin endpoints. `user_id` and any email are never in a public payload. This is enforced by
  constructing two separate models rather than by remembering to omit fields.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi import status as http_status
from pydantic import BaseModel, Field

from app import auth as auth_svc
from app.api.auth_routes import current_user, current_user_optional, require_admin
from app.auth import User
from app.reports import repository as repo
from app.reports.images import (
    DEFAULT_MAX_BYTES,
    ImageRejected,
    has_exif_gps,
    process_image,
)
from app.reports.lifecycle import (
    CATEGORIES,
    DEFAULT_STALE_AFTER_MINUTES,
    DECISIONS,
    LifecycleError,
    ReportClaim,
    derive_effective_status,
    validate_stale_after_minutes,
)
from app.reports.snapping import (
    DEFAULT_MAX_ACCURACY_M,
    DEFAULT_SNAP_THRESHOLD_M,
    public_location,
    snap_to_road,
)

public_router = APIRouter(prefix="/api/reports", tags=["reports"])
admin_reports_router = APIRouter(prefix="/api/admin/reports", tags=["admin"])

# ---------------------------------------------------------------------------
# Configuration, read once from the environment and VALIDATED
# ---------------------------------------------------------------------------

# Guayaquil envelope, matching GUAYAQUIL_BOUNDS in main.py. A public report endpoint that
# accepted arbitrary coordinates would be a free geocoding service.
REPORT_BOUNDS = {
    "lat_min": -2.40,
    "lat_max": -1.90,
    "lon_min": -80.10,
    "lon_max": -79.70,
}

# Rate limiting. The brief allows "the project's existing mechanisms or a suitable minimal
# addition"; the existing SMS limiter is per-phone, so this is the minimal addition, counted
# per account in a windowing query.
RATE_WINDOW_MINUTES = 60
MAX_SUBMISSIONS_PER_WINDOW = 5
MAX_CONFIRMATIONS_PER_WINDOW = 30


def _env_int(name: str, default: int, *, low: int, high: int) -> int:
    """Read a bounded integer. Invalid configuration fails at import, not mid-request.

    Silently falling back on a malformed value would mean a typo in a deployment variable
    quietly changes a safety-relevant limit while appearing to be set.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc
    if not low <= value <= high:
        raise RuntimeError(f"{name} must be within [{low}, {high}], got {value}")
    return value


STALE_AFTER_MINUTES = _env_int(
    "ROAD_REPORT_STALE_AFTER_MINUTES",
    DEFAULT_STALE_AFTER_MINUTES,
    low=1,
    high=60 * 24 * 14,
)
MAX_IMAGE_BYTES = _env_int(
    "MAX_ROAD_REPORT_IMAGE_BYTES", DEFAULT_MAX_BYTES, low=16 * 1024, high=25 * 1024 * 1024
)
SNAP_THRESHOLD_M = float(
    os.environ.get("ROAD_REPORT_SNAP_THRESHOLD_M", DEFAULT_SNAP_THRESHOLD_M)
)
MAX_ACCURACY_M = float(os.environ.get("ROAD_REPORT_MAX_ACCURACY_M", DEFAULT_MAX_ACCURACY_M))


# ---------------------------------------------------------------------------
# Models — public. Note what is not here: user_id, gps_lat, gps_lon, decided_by.
# ---------------------------------------------------------------------------


class PublicReportOut(BaseModel):
    """What any visitor may see about a report.

    `lat`/`lon` are the PUBLISHED position (snapped road point, or a coarsened cell). The
    submitter's raw fix is deliberately absent: see `AdminReportOut` for where it does appear
    and why.
    """

    id: str
    category: str
    description: str | None
    lat: float
    lon: float
    location_is_snapped: bool = Field(
        description="True when lat/lon are a point on a matched road segment rather than a "
        "coarsened cell centre."
    )
    road_segment_id: int | None = Field(
        description="Matched graph edge id, or null when the pin was too far from any road. "
        "A null here means the report cannot influence any road's status."
    )
    state: str = Field(
        description="One of unverified, potential_hazard, blocked_verified, "
        "passable_verified, inconclusive, rejected, stale. `stale` is DERIVED from the "
        "freshness deadline and is never stored."
    )
    decision: str = Field(
        description="The stored operator decision, independent of freshness. A stale "
        "blocked_verified report is still a closure for routing purposes."
    )
    is_stale: bool = Field(
        description="True when the freshness deadline has passed. Staleness removes the "
        "current-evidence claim; it never means the road is passable."
    )
    submitted_at: datetime
    verified_at: datetime | None
    last_confirmed_at: datetime | None
    expires_at: datetime
    confirm_count: int
    challenge_count: int
    has_image: bool
    image_url: str | None
    seeded: bool = Field(
        default=False,
        description="True for demo fixtures. Never present on a live submission.",
    )


class ReportListOut(BaseModel):
    schema_version: str = "1"
    reports: list[PublicReportOut]
    count: int
    limit: int
    # Coverage/availability disclosure, so an empty list cannot be read as "no hazards".
    notes: list[str] = Field(default_factory=list)


class ConfirmationIn(BaseModel):
    kind: Literal["confirm", "challenge"]
    model_config = {"extra": "forbid"}


class ConfirmationOut(BaseModel):
    report_id: str
    outcome: Literal["recorded", "already_voted"]
    confirm_count: int
    challenge_count: int
    # Stated explicitly because it is the property the brief demands most loudly.
    decision_unchanged: bool = True
    note: str


class CreateReportOut(BaseModel):
    report: PublicReportOut
    messages: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Models — admin. Adds raw position and accuracy, still no email.
# ---------------------------------------------------------------------------


class AdminReportOut(PublicReportOut):
    """Admin view. Adds the raw fix and the snapping diagnostics needed to judge a report.

    `gps_lat`/`gps_lon` appear ONLY here. An operator deciding whether a closure is real needs
    to know whether the pin was 3 m from the road or 40 m from it, and whether the phone's own
    accuracy made that meaningless.
    """

    user_id: str
    gps_lat: float
    gps_lon: float
    gps_accuracy_m: float | None
    gps_source: str
    snap_distance_m: float | None
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None


class DecisionIn(BaseModel):
    """An operator decision.

    There is no `role` field and no `user_id` field, so an admin decision cannot be
    attributed to someone else or used to change privileges. `extra="forbid"` makes an
    attempt to add one a 422 rather than a silent no-op.
    """

    decision: Literal[
        "potential_hazard",
        "blocked_verified",
        "passable_verified",
        "inconclusive",
        "rejected",
    ]
    note: str | None = Field(default=None, max_length=500)
    model_config = {"extra": "forbid"}


class AuditEntryOut(BaseModel):
    action: str
    actor_id: str | None
    actor_role: str | None
    from_state: str | None
    to_state: str | None
    detail: str | None
    at: datetime


class ReportHistoryOut(BaseModel):
    report_id: str
    entries: list[AuditEntryOut]
    effective_status: str | None = Field(
        default=None,
        description="The road status this report currently supports, including `stale_closure` "
        "when an expired closure is still closing the segment.",
    )


class EffectiveStatusOut(BaseModel):
    """Road status derived from reports, for diagnostics and the admin overview."""

    segments_with_reports: int
    segments_closed: int
    segments_with_stale_closure: int
    conflicts: list[str]
    stale_after_minutes: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    """The current time. A function so tests can monkeypatch one place, not many."""
    return datetime.now(timezone.utc)


def effective_stale_minutes() -> int:
    """Validated freshness window, failing closed if it was somehow corrupted at runtime."""
    try:
        return validate_stale_after_minutes(STALE_AFTER_MINUTES)
    except LifecycleError:
        return DEFAULT_STALE_AFTER_MINUTES


def _public(row: repo.ReportRow, now: datetime) -> PublicReportOut:
    """Project a stored row onto the public surface.

    Built field by field, not by `dict(row)` minus keys: an allow-list cannot accidentally
    start leaking a column that someone adds to the table later.
    """
    claim = row.to_claim()
    # Without a segment the report cannot contribute a status, so it keeps its stored
    # decision as its display state. With a segment, the lifecycle module decides.
    if claim is not None:
        state = claim.public_state(now)
        is_stale = claim.is_stale(now)
    else:
        state = row.decision
        is_stale = now > row.expires_at
    return PublicReportOut(
        id=row.id,
        category=row.category,
        description=row.description,
        lat=row.public_lat,
        lon=row.public_lon,
        location_is_snapped=row.public_is_snapped,
        road_segment_id=row.road_segment_id,
        state=state,
        decision=row.decision,
        is_stale=is_stale,
        submitted_at=row.submitted_at,
        verified_at=row.verified_at,
        last_confirmed_at=row.last_confirmed_at,
        expires_at=row.expires_at,
        confirm_count=row.confirm_count,
        challenge_count=row.challenge_count,
        has_image=row.has_image,
        image_url=f"/api/reports/{row.id}/image" if row.has_image else None,
        seeded=row.seeded,
    )


def _admin(row: repo.ReportRow, now: datetime) -> AdminReportOut:
    base = _public(row, now)
    return AdminReportOut(
        **base.model_dump(),
        user_id=row.user_id,
        gps_lat=row.gps_lat,
        gps_lon=row.gps_lon,
        gps_accuracy_m=row.gps_accuracy_m,
        gps_source=row.gps_source,
        snap_distance_m=row.snap_distance_m,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        decision_note=row.decision_note,
    )


def _store_http(exc: repo.ReportStoreError) -> HTTPException:
    """Map a storage failure to a 503 with no internal detail.

    Deliberately not a 400 or a 500 with the SQLite text: a storage failure is not the user's
    fault, and echoing driver messages leaks schema. 503 also tells a client it is worth
    retrying, which is the truthful advice here.
    """
    return HTTPException(
        status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": exc.code,
            "message": "The report could not be saved or read right now. Nothing was "
            "recorded; please try again.",
        },
    )


def _image_http(exc: ImageRejected) -> HTTPException:
    """A user-correctable image problem: 422 with a stable code and a plain sentence."""
    return HTTPException(
        status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"code": exc.code, "message": exc.message},
    )


def _validate_coords(lat: float, lon: float) -> None:
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "coordinates_out_of_range",
                "message": "Latitude must be within -90..90 and longitude within -180..180.",
            },
        )
    b = REPORT_BOUNDS
    if not (b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "outside_service_area",
                "message": "Reports are accepted only for the Guayaquil area.",
            },
        )


def _check_rate(subject: str, kind: str, cap: int, now: datetime) -> None:
    """Reject when a subject exceeded its window. Fails CLOSED on a storage error."""
    since = now - timedelta(minutes=RATE_WINDOW_MINUTES)
    try:
        used = repo.count_recent_rate_events(subject, kind, since=since)
    except repo.ReportStoreError:
        # Failing open here would let a database fault disable abuse protection entirely.
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "rate_check_unavailable",
                "message": "Submissions are temporarily unavailable; please try again.",
            },
        )
    if used >= cap:
        raise HTTPException(
            status_code=http_status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "rate_limited",
                "message": f"Too many submissions in the last {RATE_WINDOW_MINUTES} minutes. "
                f"Please wait before trying again.",
            },
        )


def report_graph():
    """The road graph, imported lazily.

    A module-level import of `app.api.main` would be circular: main imports the routers. Doing
    it inside the function keeps import order free and costs nothing after the first call
    because main caches the graph.
    """
    from app.api import main as main_module

    return main_module.get_graph()


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------


@public_router.post(
    "",
    response_model=CreateReportOut,
    status_code=http_status.HTTP_201_CREATED,
    summary="Submit a road-condition report",
)
def create_report(
    user: Annotated[User, Depends(current_user)],
    category: Annotated[str, Form()],
    lat: Annotated[float, Form()],
    lon: Annotated[float, Form()],
    accuracy_m: Annotated[float | None, Form()] = None,
    gps_source: Annotated[Literal["device", "manual", "map"], Form()] = "device",
    description: Annotated[str | None, Form()] = None,
    image: Annotated[UploadFile | None, File()] = None,
) -> CreateReportOut:
    """Create a report. Signed-in users only, and always `unverified`.

    Form-encoded rather than JSON because the payload includes a file: a multipart request with
    the photo and the fields together is one atomic submission, whereas uploading the image
    separately would create a window where an image exists with no report.

    The geolocation is the user's decision. This endpoint does not require accuracy, does not
    require a matched segment, and never silently repositions the report: an unmatched pin is
    stored as unmatched and the response says so.
    """
    now = _now()
    _validate_coords(lat, lon)

    if category not in CATEGORIES:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_category",
                "message": f"Unknown category. Expected one of {', '.join(CATEGORIES)}.",
            },
        )
    if accuracy_m is not None and (accuracy_m < 0 or accuracy_m > 100_000):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_accuracy", "message": "GPS accuracy must be 0–100000 m."},
        )
    if description is not None:
        description = description.strip() or None
        if description is not None and len(description) > 280:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "description_too_long",
                    "message": "Keep the description to 280 characters or fewer.",
                },
            )

    _check_rate(user.id, "report_submit", MAX_SUBMISSIONS_PER_WINDOW, now)

    # ---- image: size gate, then real content validation -------------------------
    stored = None
    messages: list[str] = []
    if image is not None:
        raw = image.file.read(MAX_IMAGE_BYTES + 1)
        if len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=http_status.HTTP_413_CONTENT_TOO_LARGE,
                detail={
                    "code": "image_too_large",
                    "message": f"The photo is larger than the "
                    f"{MAX_IMAGE_BYTES // (1024 * 1024)} MB limit.",
                },
            )
        had_gps = has_exif_gps(raw)
        try:
            stored = process_image(raw, max_bytes=MAX_IMAGE_BYTES)
        except ImageRejected as exc:
            raise _image_http(exc) from exc
        if had_gps:
            # Worth saying: people are often unaware their camera records a position. Stated as
            # a removal, never as a promise about the raw upload having been kept.
            messages.append(
                "Location data embedded in the photo was removed from the published copy."
            )

    # ---- snapping ---------------------------------------------------------------
    snap = snap_to_road(
        report_graph(),
        lat,
        lon,
        accuracy_m=accuracy_m,
        threshold_m=SNAP_THRESHOLD_M,
        max_accuracy_m=MAX_ACCURACY_M,
    )
    pub_lat, pub_lon, is_snapped = public_location(lat, lon, snap)

    if not snap.matched:
        # An honest, actionable message. The report is still accepted: refusing it would throw
        # away evidence the user took the trouble to record.
        messages.append(
            f"The report was saved without a road match ({snap.reason}). "
            f"It will be shown as a nearby hazard but cannot change any road's status "
            f"until a road is identified."
        )

    new = repo.NewReport(
        user_id=user.id,
        category=category,
        description=description,
        gps_lat=lat,
        gps_lon=lon,
        gps_accuracy_m=accuracy_m,
        gps_source=gps_source,
        road_segment_id=snap.edge_id,
        snap_distance_m=snap.distance_m if snap.matched else None,
        public_lat=pub_lat,
        public_lon=pub_lon,
        public_is_snapped=is_snapped,
        submitted_at=now,
        stale_after_minutes=effective_stale_minutes(),
    )

    try:
        row = repo.create_report(new, stored, actor_role=user.role)
        repo.record_rate_event(user.id, "report_submit", now)
    except repo.ReportStoreError as exc:
        raise _store_http(exc) from exc

    # The submission is audited separately from the auth audit: one is "who signed in", the
    # other is "what evidence arrived".
    auth_svc.audit(
        user,
        "report.create",
        subject=row.id,
        detail=f"category={category} segment={snap.edge_id or 'unmatched'}",
    )

    return CreateReportOut(report=_public(row, now), messages=messages)


@public_router.get("", response_model=ReportListOut, summary="List recent reports")
def list_reports(
    bbox: Annotated[
        str | None,
        Query(description="min_lat,min_lon,max_lat,max_lon — comma separated"),
    ] = None,
    decision: Annotated[list[str] | None, Query(description="Repeatable decision filter")] = None,
    include_stale: bool = Query(
        default=True,
        description="Include reports whose freshness deadline has passed. They are labelled "
        "stale and are never evidence of current conditions.",
    ),
    limit: int = Query(default=50, ge=1, le=repo.MAX_PUBLIC_REPORTS),
    since_hours: int | None = Query(default=None, ge=1, le=24 * 30),
) -> ReportListOut:
    """Bounded, newest-first listing for the map.

    Unverified reports appear here by design: the brief requires them visible to other users
    and clearly labelled, because a hazard nobody can see is not community reporting.
    """
    now = _now()
    parsed_bbox = _parse_bbox(bbox)
    if decision:
        unknown = [d for d in decision if d not in DECISIONS]
        if unknown:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "invalid_decision_filter",
                    "message": f"Unknown decision values: {', '.join(unknown)}",
                },
            )

    since = now - timedelta(hours=since_hours) if since_hours else None
    try:
        rows = repo.query_reports(
            limit=limit, bbox=parsed_bbox, decisions=decision, since=since
        )
    except repo.ReportStoreError as exc:
        raise _store_http(exc) from exc

    out: list[PublicReportOut] = []
    for row in rows:
        projected = _public(row, now)
        if not include_stale and projected.is_stale:
            continue
        out.append(projected)

    notes = [
        "Reports marked unverified are community submissions that no operator has reviewed. "
        "They are evidence, not a road-status decision.",
        "A stale report means its freshness window has passed. It is not evidence that the "
        "road is passable.",
        f"Only reports from the last {RATE_WINDOW_MINUTES} minutes count toward rate limits; "
        "this list is capped at "
        f"{repo.MAX_PUBLIC_REPORTS} entries.",
    ]
    return ReportListOut(reports=out, count=len(out), limit=limit, notes=notes)


def _parse_bbox(raw: str | None) -> tuple[float, float, float, float] | None:
    if raw is None or raw.strip() == "":
        return None
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 4:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_bbox",
                "message": "bbox must be four comma-separated numbers: "
                "min_lat,min_lon,max_lat,max_lon",
            },
        )
    try:
        min_lat, min_lon, max_lat, max_lon = (float(p) for p in parts)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_bbox", "message": "bbox values must be numbers."},
        ) from exc
    if min_lat > max_lat or min_lon > max_lon:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_bbox",
                "message": "bbox minimums must not exceed maximums.",
            },
        )
    return (min_lat, min_lon, max_lat, max_lon)


@public_router.get("/{report_id}", response_model=PublicReportOut)
def get_report(report_id: str) -> PublicReportOut:
    try:
        row = repo.fetch_report(report_id)
    except repo.ReportStoreError as exc:
        raise _store_http(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="report not found")
    return _public(row, _now())


@public_router.post("/{report_id}/confirm", response_model=ConfirmationOut)
def confirm_report(
    report_id: str,
    payload: ConfirmationIn,
    user: Annotated[User, Depends(current_user)],
) -> ConfirmationOut:
    """Confirm that a hazard persists, or challenge it as improved/gone.

    A signed-in user is required so one account cannot pad the counts, and the unique
    constraint makes a duplicate physically impossible rather than merely unlikely.

    This cannot change `decision`. Corroboration is evidence for the operator to read; the
    brief is explicit that community votes must not confer authority or prove a blockage.
    """
    now = _now()
    _check_rate(user.id, "report_confirm", MAX_CONFIRMATIONS_PER_WINDOW, now)
    try:
        row, outcome = repo.add_confirmation(
            report_id,
            user.id,
            payload.kind,
            now,
            stale_after_minutes=effective_stale_minutes(),
        )
        if row is not None and outcome == "recorded":
            repo.record_rate_event(user.id, "report_confirm", now)
    except repo.ReportStoreError as exc:
        raise _store_http(exc) from exc

    if row is None:
        raise HTTPException(status_code=404, detail="report not found")

    if outcome == "already_voted":
        return ConfirmationOut(
            report_id=report_id,
            outcome="already_voted",
            confirm_count=row.confirm_count,
            challenge_count=row.challenge_count,
            note="This account has already responded to this report. Nothing was changed.",
        )

    return ConfirmationOut(
        report_id=report_id,
        outcome="recorded",
        confirm_count=row.confirm_count,
        challenge_count=row.challenge_count,
        note="Recorded. This does not verify the report or change any road's status.",
    )


@public_router.get(
    "/{report_id}/image",
    summary="Serve the sanitised report image",
    response_class=Response,
)
def get_report_image(report_id: str) -> Response:
    """Serve the stored, re-encoded image.

    Safety-relevant headers:
      * `Content-Type` is the STORED type, never the client's claim.
      * `X-Content-Type-Options: nosniff` stops a browser from guessing a type of its own.
      * `Content-Security-Policy: default-src 'none'` means even if a polymath file somehow
        rendered as HTML, it could not run script.
      * `Cache-Control: private` because a report's picture must not sit in a shared proxy.

    Images are public because public reporting requires them to be: the brief asks other users
    to see the photo. What is NOT public is the submitter's identity or raw position.
    """
    try:
        found = repo.fetch_image(report_id)
    except repo.ReportStoreError as exc:
        raise _store_http(exc) from exc
    if found is None:
        raise HTTPException(status_code=404, detail="no image for this report")
    data, content_type = found
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": f'inline; filename="{report_id}.jpg"',
        },
    )


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

_admin_viewer = require_admin("viewer")
_admin_operator = require_admin("operator")


@admin_reports_router.get("", response_model=list[AdminReportOut])
def admin_list_reports(
    user: Annotated[User, Depends(_admin_viewer)],
    decision: Annotated[list[str] | None, Query()] = None,
    pending_only: bool = Query(
        default=False,
        description="Only reports no operator has decided yet (decision = 'unverified').",
    ),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AdminReportOut]:
    """Review queue. Requires at least the `viewer` role, enforced server-side."""
    now = _now()
    decisions = list(decision) if decision else (["unverified"] if pending_only else None)
    try:
        rows = repo.query_reports(limit=limit, decisions=decisions)
    except repo.ReportStoreError as exc:
        raise _store_http(exc) from exc
    return [_admin(r, now) for r in rows]


@admin_reports_router.get("/effective-status", response_model=EffectiveStatusOut)
def admin_effective_status(
    user: Annotated[User, Depends(_admin_viewer)],
) -> EffectiveStatusOut:
    """Derived road status across all reports, for diagnostics.

    Exposed so an operator (and a reviewer) can see the difference between "how many reports
    are blocked_verified" and "how many segments are actually closed right now, including
    closures that are stale but still in force".
    """
    now = _now()
    try:
        claims = repo.fetch_claims()
    except repo.ReportStoreError as exc:
        raise _store_http(exc) from exc
    derived = derive_effective_status(claims, now)
    return EffectiveStatusOut(
        segments_with_reports=derived.segments_with_reports,
        segments_closed=derived.segments_closed,
        segments_with_stale_closure=derived.segments_stale_closure,
        conflicts=[c.as_text() for c in derived.conflicts],
        stale_after_minutes=effective_stale_minutes(),
    )


@admin_reports_router.get("/{report_id}", response_model=AdminReportOut)
def admin_get_report(
    report_id: str, user: Annotated[User, Depends(_admin_viewer)]
) -> AdminReportOut:
    try:
        row = repo.fetch_report(report_id)
    except repo.ReportStoreError as exc:
        raise _store_http(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="report not found")
    return _admin(row, _now())


@admin_reports_router.post("/{report_id}/decision", response_model=AdminReportOut)
def admin_decide(
    report_id: str,
    payload: DecisionIn,
    user: Annotated[User, Depends(_admin_operator)],
) -> AdminReportOut:
    """Record an operator decision.

    Requires the `operator` role. `viewer` is read-only, because a role named "viewer" that can
    close roads would be a naming lie.

    Deciding `blocked_verified` is what turns a report into a road closure; the routing engine
    picks it up through the lifecycle derivation, so there is exactly one source of truth for
    road status rather than a closure flag on the report and a separate one on the segment.
    """
    now = _now()
    try:
        row = repo.apply_admin_decision(
            report_id,
            decision=payload.decision,
            actor_id=user.id,
            actor_role=user.role,
            at=now,
            note=payload.note,
            stale_after_minutes=effective_stale_minutes(),
        )
    except repo.ReportStoreError as exc:
        raise _store_http(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="report not found")

    auth_svc.audit(
        user,
        "report.decision",
        subject=report_id,
        detail=f"{payload.decision} segment={row.road_segment_id or 'unmatched'}",
    )
    return _admin(row, now)


@admin_reports_router.get("/{report_id}/history", response_model=ReportHistoryOut)
def admin_history(
    report_id: str, user: Annotated[User, Depends(_admin_viewer)]
) -> ReportHistoryOut:
    """Append-only history, plus what the report currently implies for its road.

    The history is returned even for a report that is now rejected, because "we rejected this,
    and here is when and by whom" is exactly the audit trail the brief requires be preserved.
    """
    now = _now()
    try:
        row = repo.fetch_report(report_id)
        if row is None:
            raise HTTPException(status_code=404, detail="report not found")
        entries = repo.fetch_audit(report_id)
        claims = repo.fetch_claims()
    except repo.ReportStoreError as exc:
        raise _store_http(exc) from exc

    effective: str | None = None
    if row.road_segment_id is not None:
        derived = derive_effective_status(claims, now)
        found = derived.get(row.road_segment_id)
        if found is not None:
            effective = found.status
            if found.stale_closure:
                effective = (
                    f"{found.status} (stale closure: excluded from routes, "
                    f"no longer current evidence)"
                )

    return ReportHistoryOut(
        report_id=report_id,
        entries=[
            AuditEntryOut(
                action=e["action"],
                actor_id=e["actor_id"],
                actor_role=e["actor_role"],
                from_state=e["from_state"],
                to_state=e["to_state"],
                detail=e["detail"],
                at=e["at"],
            )
            for e in entries
        ],
        effective_status=effective,
    )


# ---------------------------------------------------------------------------
# Routing overlay — used by main.py
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportOverlay:
    """Statuses derived from reports, plus what a caller needs to disclose about them."""

    by_segment: dict[int, tuple[str, bool]]
    segments_with_reports: int
    segments_closed: int
    stale_closures: int
    conflicts: tuple[str, ...]
    applied: bool
    notes: tuple[str, ...] = ()


def build_report_overlay(
    now: datetime,
    *,
    enabled: bool = True,
    claims: list[ReportClaim] | None = None,
) -> ReportOverlay | None:
    """Derive a routing overlay from persisted reports.

    Returns None when the overlay is disabled or no report can influence a road, so the caller
    can skip merging entirely and the response says the overlay was not applied. That matters:
    a route that silently mixes demo seed status with citizen reports, without saying so, is
    exactly the provenance failure the project has been careful to avoid.

    A storage error is NOT fatal. Routing must keep working when the report store is broken, so
    the error becomes a note and the base status is used unchanged.
    """
    if not enabled:
        return None
    try:
        if claims is None:
            claims = repo.fetch_claims()
    except repo.ReportStoreError:
        return ReportOverlay(
            by_segment={},
            segments_with_reports=0,
            segments_closed=0,
            stale_closures=0,
            conflicts=(),
            applied=False,
            notes=(
                "report evidence could not be read; route used road status only, and "
                "community reports were NOT considered",
            ),
        )

    derived = derive_effective_status(claims, now)
    if not derived.by_segment:
        return ReportOverlay(
            by_segment={},
            segments_with_reports=derived.segments_with_reports,
            segments_closed=0,
            stale_closures=0,
            conflicts=(),
            applied=False,
            notes=(),
        )

    by_segment = {
        seg: (s.status, s.verified) for seg, s in derived.by_segment.items()
    }
    notes: list[str] = [
        f"community reports affect {len(by_segment)} road segment(s); "
        f"{derived.segments_closed} are closed by a verified report"
    ]
    if derived.segments_stale_closure:
        notes.append(
            f"{derived.segments_stale_closure} closure(s) come from expired evidence: they are "
            f"still avoided, but are no longer current verification"
        )
    if derived.conflicts:
        notes.append(
            f"{len(derived.conflicts)} road segment(s) have conflicting verified reports; the "
            f"higher-risk reading is used and both are retained for review"
        )

    return ReportOverlay(
        by_segment=by_segment,
        segments_with_reports=derived.segments_with_reports,
        segments_closed=derived.segments_closed,
        stale_closures=derived.segments_stale_closure,
        conflicts=tuple(c.as_text() for c in derived.conflicts),
        applied=True,
        notes=tuple(notes),
    )
