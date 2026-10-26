"""Persistence for road reports — the only module here that touches a database.

LAYERING
  lifecycle.py  decides what a report means
  snapping.py   decides which road it describes
  images.py     decides what bytes may be stored
  repository.py decides how it is written and read

  Keeping SQL in one place means the safety-critical logic above can be tested with no
  database at all, instantly, and the tests that do need SQL are the only ones needing a
  temp file.

CONCURRENCY AND TRANSACTIONS
  Every write opens its own connection through `store.connect()`, which sets WAL,
  `busy_timeout`, and wraps the work in an explicit transaction with rollback on error. A
  report plus its image is one transaction: half a report with no image would render as a
  broken card, and an image with no report row would be an orphan nobody can ever delete.

WHAT IS DELIBERATELY ABSENT
  * No `stale` column, and no UPDATE that rewrites a decision because time passed. Staleness
    is derived on read by the lifecycle module. See store.py for the long argument.
  * No DELETE of reports. "Rejected" is a decision, not a deletion, and the audit trail must
    survive (requirement D.4/D.5).
  * No query that returns `gps_lat`/`gps_lon` to a public caller. Those two columns are read
    only by `fetch_admin_reports` / `fetch_report_for_admin`.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from app import store
from app.reports.lifecycle import (
    DEFAULT_STALE_AFTER_MINUTES,
    Decision,
    ReportClaim,
    compute_expiry,
    validate_stale_after_minutes,
)
from app.reports.images import StoredImage

# ---------------------------------------------------------------------------
# Time discipline
# ---------------------------------------------------------------------------


def to_db(dt: datetime) -> str:
    """Store UTC ISO-8601 with an explicit offset. Never a naive string.

    A timezone-naive timestamp in a database is a bug waiting for the first deploy in another
    region: `2026-10-26T12:00:00` is a different instant depending on who reads it. Storing the
    offset means a reader never has to guess, and `from_db` can be strict.
    """
    if dt.tzinfo is None:
        raise ValueError("refusing to store a naive datetime; supply an aware UTC datetime")
    return dt.astimezone(timezone.utc).isoformat()


def from_db(text: str) -> datetime:
    """Parse a stored timestamp, insisting on an offset."""
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"stored timestamp has no offset: {text!r}")
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NewReport:
    """Everything needed to create a report, already validated by the API layer."""

    user_id: str
    category: str
    description: str | None
    gps_lat: float
    gps_lon: float
    gps_accuracy_m: float | None
    gps_source: str
    road_segment_id: int | None
    snap_distance_m: float | None
    public_lat: float
    public_lon: float
    public_is_snapped: bool
    submitted_at: datetime
    stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES
    # Only ever True for fixtures the caller has explicitly labelled. Never derived from input.
    seeded: bool = False


@dataclass(frozen=True)
class ReportRow:
    """A stored report as read back.

    Includes the raw GPS because that is what the database holds; deciding who may see it is
    the API layer's job, and there are two separate read functions for that reason.
    """

    id: str
    user_id: str
    category: str
    description: str | None
    gps_lat: float
    gps_lon: float
    gps_accuracy_m: float | None
    gps_source: str
    road_segment_id: int | None
    snap_distance_m: float | None
    public_lat: float
    public_lon: float
    public_is_snapped: bool
    decision: Decision
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None
    submitted_at: datetime
    verified_at: datetime | None
    last_confirmed_at: datetime | None
    expires_at: datetime
    stale_after_minutes: int
    seeded: bool
    confirm_count: int = 0
    challenge_count: int = 0
    has_image: bool = False

    def to_claim(self) -> ReportClaim | None:
        """Convert to a lifecycle claim. None when the report has no segment to affect.

        An unmatched report is still a real report and still shown on the map; it simply
        cannot influence any road's status, because no road has been identified.
        """
        if self.road_segment_id is None:
            return None
        return ReportClaim(
            report_id=self.id,
            road_segment_id=self.road_segment_id,
            decision=self.decision,
            submitted_at=self.submitted_at,
            verified_at=self.verified_at,
            expires_at=self.expires_at,
            last_confirmed_at=self.last_confirmed_at,
            confirm_count=self.confirm_count,
            challenge_count=self.challenge_count,
            seeded=self.seeded,
        )


class ReportStoreError(Exception):
    """Raised for a storage failure the caller must report honestly rather than swallow."""

    def __init__(self, message: str, code: str = "storage_error") -> None:
        super().__init__(message)
        self.code = code


_COLUMNS = """
    r.id, r.user_id, r.category, r.description, r.gps_lat, r.gps_lon, r.gps_accuracy_m,
    r.gps_source, r.road_segment_id, r.snap_distance_m, r.public_lat, r.public_lon,
    r.public_is_snapped, r.decision, r.decided_by, r.decided_at, r.decision_note,
    r.submitted_at, r.verified_at, r.last_confirmed_at, r.expires_at, r.stale_after_minutes,
    r.seeded,
    (select count(*) from report_confirmations c
        where c.report_id = r.id and c.kind = 'confirm') as confirm_count,
    (select count(*) from report_confirmations c
        where c.report_id = r.id and c.kind = 'challenge') as challenge_count,
    (select count(*) from report_images i where i.report_id = r.id) as has_image
"""


def _row_to_report(row: sqlite3.Row) -> ReportRow:
    return ReportRow(
        id=row["id"],
        user_id=row["user_id"],
        category=row["category"],
        description=row["description"],
        gps_lat=row["gps_lat"],
        gps_lon=row["gps_lon"],
        gps_accuracy_m=row["gps_accuracy_m"],
        gps_source=row["gps_source"],
        road_segment_id=row["road_segment_id"],
        snap_distance_m=row["snap_distance_m"],
        public_lat=row["public_lat"],
        public_lon=row["public_lon"],
        public_is_snapped=bool(row["public_is_snapped"]),
        decision=row["decision"],
        decided_by=row["decided_by"],
        decided_at=from_db(row["decided_at"]) if row["decided_at"] else None,
        decision_note=row["decision_note"],
        submitted_at=from_db(row["submitted_at"]),
        verified_at=from_db(row["verified_at"]) if row["verified_at"] else None,
        last_confirmed_at=from_db(row["last_confirmed_at"]) if row["last_confirmed_at"] else None,
        expires_at=from_db(row["expires_at"]),
        stale_after_minutes=row["stale_after_minutes"],
        seeded=bool(row["seeded"]),
        confirm_count=row["confirm_count"],
        challenge_count=row["challenge_count"],
        has_image=bool(row["has_image"]),
    )


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def create_report(
    new: NewReport,
    image: StoredImage | None,
    *,
    actor_role: str | None = None,
) -> ReportRow:
    """Insert a report, optionally with its image, in ONE transaction.

    Raises ReportStoreError on any storage failure so the route can answer 503 with an honest
    message instead of a stack trace.
    """
    validate_stale_after_minutes(new.stale_after_minutes)
    report_id = str(uuid.uuid4())
    expires_at = compute_expiry(new.submitted_at, new.stale_after_minutes)

    try:
        with store.connect() as conn:
            conn.execute(
                """
                insert into road_reports (
                    id, user_id, category, description, gps_lat, gps_lon, gps_accuracy_m,
                    gps_source, road_segment_id, snap_distance_m, public_lat, public_lon,
                    public_is_snapped, decision, submitted_at, expires_at,
                    stale_after_minutes, seeded
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unverified', ?, ?, ?, ?)
                """,
                (
                    report_id,
                    new.user_id,
                    new.category,
                    new.description,
                    new.gps_lat,
                    new.gps_lon,
                    new.gps_accuracy_m,
                    new.gps_source,
                    new.road_segment_id,
                    new.snap_distance_m,
                    new.public_lat,
                    new.public_lon,
                    1 if new.public_is_snapped else 0,
                    to_db(new.submitted_at),
                    to_db(expires_at),
                    new.stale_after_minutes,
                    1 if new.seeded else 0,
                ),
            )
            if image is not None:
                conn.execute(
                    """
                    insert into report_images (
                        report_id, content_type, bytes_blob, width, height, byte_size,
                        sha256, metadata_stripped, created_at
                    ) values (?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        report_id,
                        image.content_type,
                        image.data,
                        image.width,
                        image.height,
                        image.byte_size,
                        image.sha256,
                        to_db(new.submitted_at),
                    ),
                )
            _audit_in_conn(
                conn,
                report_id=report_id,
                action="report.submitted",
                actor_id=new.user_id,
                actor_role=actor_role,
                from_state=None,
                to_state="unverified",
                detail=(
                    f"category={new.category} "
                    f"segment={new.road_segment_id if new.road_segment_id is not None else 'unmatched'} "
                    f"snap_m={new.snap_distance_m if new.snap_distance_m is not None else 'n/a'} "
                    f"image={'yes' if image is not None else 'no'}"
                ),
                at=new.submitted_at,
            )
            row = conn.execute(
                f"select {_COLUMNS} from road_reports r where r.id = ?", (report_id,)
            ).fetchone()
    except sqlite3.Error as exc:
        raise ReportStoreError(
            f"could not save the report: {exc.__class__.__name__}", code="storage_failed"
        ) from exc

    if row is None:  # pragma: no cover - would mean the insert vanished
        raise ReportStoreError("report was written but could not be read back")
    return _row_to_report(row)


def add_confirmation(
    report_id: str,
    user_id: str,
    kind: str,
    at: datetime,
    *,
    stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES,
) -> tuple[ReportRow | None, str]:
    """Record a confirm/challenge vote.

    Returns (report, outcome) where outcome is one of:
      'recorded'      — the vote was stored
      'already_voted' — this account already voted on this report; nothing changed
      'not_found'     — no such report

    The duplicate check is the UNIQUE(report_id, user_id) constraint, not a SELECT-then-INSERT.
    A check-then-act would let two concurrent taps both pass the read and one raise a raw
    IntegrityError; catching the constraint instead means the second tap gets a clean, correct
    answer.
    """
    if kind not in ("confirm", "challenge"):
        raise ValueError(f"unknown confirmation kind {kind!r}")
    validate_stale_after_minutes(stale_after_minutes)

    try:
        with store.connect() as conn:
            exists = conn.execute(
                "select 1 from road_reports where id = ?", (report_id,)
            ).fetchone()
            if exists is None:
                return None, "not_found"

            try:
                conn.execute(
                    """
                    insert into report_confirmations (report_id, user_id, kind, at)
                    values (?, ?, ?, ?)
                    """,
                    (report_id, user_id, kind, to_db(at)),
                )
            except sqlite3.IntegrityError:
                # Either the unique vote constraint or a stale foreign key. Distinguish them,
                # because "you already voted" and "that account is gone" are different answers.
                already = conn.execute(
                    "select 1 from report_confirmations where report_id = ? and user_id = ?",
                    (report_id, user_id),
                ).fetchone()
                if already is not None:
                    return _read_one(conn, report_id), "already_voted"
                raise

            # A confirmation only refreshes the deadline. It NEVER changes `decision`, and it
            # never sets `verified_at`: corroboration is evidence, not authority. The brief is
            # explicit that community votes "do not automatically confer administrator
            # privileges or prove a road is blocked".
            current = conn.execute(
                "select expires_at, last_confirmed_at from road_reports where id = ?",
                (report_id,),
            ).fetchone()
            candidate = at + timedelta(minutes=stale_after_minutes)
            new_expiry = max(from_db(current["expires_at"]), candidate)
            conn.execute(
                """
                update road_reports
                   set last_confirmed_at = ?, expires_at = ?
                 where id = ?
                """,
                (to_db(at), to_db(new_expiry), report_id),
            )
            _audit_in_conn(
                conn,
                report_id=report_id,
                action=f"report.{kind}",
                actor_id=user_id,
                actor_role=None,
                from_state=None,
                to_state=None,
                detail=f"community {kind}; decision unchanged",
                at=at,
            )
            row = _read_one(conn, report_id)
    except sqlite3.Error as exc:
        raise ReportStoreError(
            f"could not record the confirmation: {exc.__class__.__name__}",
            code="storage_failed",
        ) from exc

    return row, "recorded"


def apply_admin_decision(
    report_id: str,
    *,
    decision: Decision,
    actor_id: str,
    actor_role: str,
    at: datetime,
    note: str | None = None,
    stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES,
) -> ReportRow | None:
    """Record an operator decision and refresh the freshness window.

    Verified decisions set `verified_at` and push `expires_at` forward from the decision time,
    because an operator who has just looked at the road has created fresh evidence. `unverified`
    is not a decision an operator makes here — reversing a decision is `inconclusive`, which
    keeps the history honest instead of pretending the review never happened.
    """
    if decision not in (
        "potential_hazard",
        "blocked_verified",
        "passable_verified",
        "inconclusive",
        "rejected",
    ):
        raise ValueError(
            f"{decision!r} is not an operator decision; use one of potential_hazard, "
            f"blocked_verified, passable_verified, inconclusive, rejected"
        )
    validate_stale_after_minutes(stale_after_minutes)

    # `verified_at` records when a HUMAN last examined this report, and every operator decision
    # except `rejected` asserts something about the road that must be attributable to a person
    # and a moment. `inconclusive` is included deliberately: "we looked and could not tell" is
    # a decision, and it needs a timestamp for ordering and for the audit trail. `rejected`
    # gets `decided_at` only, because stamping a rejection as a verification would imply the
    # evidence was checked and upheld when it was thrown out.
    stamps_verification = decision != "rejected"
    new_expiry = at + timedelta(minutes=stale_after_minutes)

    try:
        with store.connect() as conn:
            before = conn.execute(
                "select decision from road_reports where id = ?", (report_id,)
            ).fetchone()
            if before is None:
                return None

            conn.execute(
                """
                update road_reports
                   set decision = ?, decided_by = ?, decided_at = ?, decision_note = ?,
                       verified_at = coalesce(?, verified_at),
                       expires_at = ?,
                       last_confirmed_at = coalesce(last_confirmed_at, ?)
                 where id = ?
                """,
                (
                    decision,
                    actor_id,
                    to_db(at),
                    note,
                    to_db(at) if stamps_verification else None,
                    to_db(new_expiry),
                    # A decision is itself a confirmation of present conditions, so the "last
                    # confirmed" clock starts here if it was never set.
                    to_db(at) if stamps_verification else None,
                    report_id,
                ),
            )
            _audit_in_conn(
                conn,
                report_id=report_id,
                action="report.decision",
                actor_id=actor_id,
                actor_role=actor_role,
                from_state=before["decision"],
                to_state=decision,
                detail=note,
                at=at,
            )
            row = _read_one(conn, report_id)
    except sqlite3.Error as exc:
        raise ReportStoreError(
            f"could not save the decision: {exc.__class__.__name__}", code="storage_failed"
        ) from exc

    return row


def _audit_in_conn(
    conn: sqlite3.Connection,
    *,
    report_id: str,
    action: str,
    actor_id: str | None,
    actor_role: str | None,
    from_state: str | None,
    to_state: str | None,
    detail: str | None,
    at: datetime,
) -> None:
    """Append one audit row inside an existing transaction.

    Append-only by design: there is no update or delete helper for this table anywhere in the
    codebase, which is what makes the trail trustworthy.
    """
    conn.execute(
        """
        insert into report_audit (
            report_id, action, actor_id, actor_role, from_state, to_state, detail, at
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (report_id, action, actor_id, actor_role, from_state, to_state, detail, to_db(at)),
    )


def record_rate_event(subject: str, kind: str, at: datetime) -> None:
    """Note one submission attempt for throttling."""
    try:
        with store.connect() as conn:
            conn.execute(
                "insert into report_rate_events (subject, kind, at) values (?, ?, ?)",
                (subject, kind, to_db(at)),
            )
    except sqlite3.Error as exc:  # pragma: no cover - throttling must not break submission
        raise ReportStoreError("could not record a rate event") from exc


def count_recent_rate_events(subject: str, kind: str, *, since: datetime) -> int:
    """How many attempts this subject made since `since`.

    A storage failure here FAILS CLOSED (returns the configured cap), because silently
    disabling a rate limit on a database error is how an abuse guard becomes decorative.
    """
    try:
        with store.connect() as conn:
            row = conn.execute(
                """
                select count(*) as n from report_rate_events
                 where subject = ? and kind = ? and at >= ?
                """,
                (subject, kind, to_db(since)),
            ).fetchone()
            return int(row["n"])
    except sqlite3.Error as exc:
        raise ReportStoreError("could not read rate events", code="storage_failed") from exc


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

MAX_PUBLIC_REPORTS = 200


def _read_one(conn: sqlite3.Connection, report_id: str) -> ReportRow | None:
    row = conn.execute(
        f"select {_COLUMNS} from road_reports r where r.id = ?", (report_id,)
    ).fetchone()
    return _row_to_report(row) if row is not None else None


def fetch_report(report_id: str) -> ReportRow | None:
    """Read one report by id. Includes raw GPS; callers must not serve this directly."""
    try:
        with store.connect() as conn:
            return _read_one(conn, report_id)
    except sqlite3.Error as exc:
        raise ReportStoreError("could not read the report", code="storage_failed") from exc


def query_reports(
    *,
    limit: int = 50,
    bbox: tuple[float, float, float, float] | None = None,
    decisions: Sequence[str] | None = None,
    since: datetime | None = None,
) -> list[ReportRow]:
    """Bounded, newest-first listing for the public map.

    The limit is clamped rather than validated-then-trusted, so no query parameter can ask for
    the entire history. `bbox` is (min_lat, min_lon, max_lat, max_lon) and filters on the
    PUBLISHED coordinate, not the private one — a bounding box that could reveal private
    positions would be an oracle for where someone stood.
    """
    limit = max(1, min(int(limit), MAX_PUBLIC_REPORTS))
    where: list[str] = []
    params: list[Any] = []

    if bbox is not None:
        min_lat, min_lon, max_lat, max_lon = bbox
        where.append("r.public_lat between ? and ? and r.public_lon between ? and ?")
        params.extend([min_lat, max_lat, min_lon, max_lon])
    if decisions:
        placeholders = ",".join("?" for _ in decisions)
        where.append(f"r.decision in ({placeholders})")
        params.extend(decisions)
    if since is not None:
        where.append("r.submitted_at >= ?")
        params.append(to_db(since))

    clause = f"where {' and '.join(where)}" if where else ""
    sql = (
        f"select {_COLUMNS} from road_reports r {clause} "
        f"order by r.submitted_at desc limit ?"
    )
    params.append(limit)

    try:
        with store.connect() as conn:
            return [_row_to_report(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.Error as exc:
        raise ReportStoreError("could not list reports", code="storage_failed") from exc


def fetch_claims(*, since: datetime | None = None) -> list[ReportClaim]:
    """Every claim that could influence a road's status.

    Only reports WITH a matched segment can influence anything, so unmatched ones are excluded
    at the query rather than silently dropped later. Rejected reports are also excluded here:
    they contribute nothing to a status, and their history is preserved in report_audit.
    """
    where = ["r.road_segment_id is not null", "r.decision <> 'rejected'"]
    params: list[Any] = []
    if since is not None:
        where.append("r.submitted_at >= ?")
        params.append(to_db(since))
    sql = (
        f"select {_COLUMNS} from road_reports r where {' and '.join(where)} "
        f"order by r.submitted_at asc"
    )
    try:
        with store.connect() as conn:
            rows = [_row_to_report(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.Error as exc:
        raise ReportStoreError("could not load report claims", code="storage_failed") from exc

    claims: list[ReportClaim] = []
    for row in rows:
        claim = row.to_claim()
        if claim is None:
            continue
        try:
            claims.append(claim)
        except Exception:  # noqa: BLE001 - a malformed row must not break routing
            # A row that cannot become a valid claim is skipped rather than crashing the route
            # endpoint. This is defensive only: the schema and create path make it unreachable.
            continue
    return claims


def fetch_image(report_id: str) -> tuple[bytes, str] | None:
    """The sanitised bytes and content type, or None when the report has no image."""
    try:
        with store.connect() as conn:
            row = conn.execute(
                "select bytes_blob, content_type from report_images where report_id = ?",
                (report_id,),
            ).fetchone()
            if row is None:
                return None
            return bytes(row["bytes_blob"]), row["content_type"]
    except sqlite3.Error as exc:
        raise ReportStoreError("could not read the image", code="storage_failed") from exc


def fetch_audit(report_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """The append-only history for one report, oldest first."""
    try:
        with store.connect() as conn:
            rows = conn.execute(
                """
                select action, actor_id, actor_role, from_state, to_state, detail, at
                  from report_audit where report_id = ? order by at asc, id asc limit ?
                """,
                (report_id, max(1, min(limit, 500))),
            ).fetchall()
    except sqlite3.Error as exc:
        raise ReportStoreError("could not read report history", code="storage_failed") from exc
    return [
        {
            "action": r["action"],
            "actor_id": r["actor_id"],
            "actor_role": r["actor_role"],
            "from_state": r["from_state"],
            "to_state": r["to_state"],
            "detail": r["detail"],
            "at": from_db(r["at"]),
        }
        for r in rows
    ]


def count_reports_by_decision() -> dict[str, int]:
    """Counts per decision, for the admin overview. Real counts, never estimates."""
    try:
        with store.connect() as conn:
            rows = conn.execute(
                "select decision, count(*) as n from road_reports group by decision"
            ).fetchall()
    except sqlite3.Error as exc:
        raise ReportStoreError("could not count reports", code="storage_failed") from exc
    return {r["decision"]: int(r["n"]) for r in rows}
