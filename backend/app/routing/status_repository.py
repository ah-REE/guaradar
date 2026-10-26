"""Road-status repository — database-backed, read-only.

Purpose: stop generating road status in-process (N-7) and read it from `road_status` instead.

THE MAPPING PROBLEM, AND WHY THIS DESIGN IS THE HONEST ONE
  `road_status.road_segment_id` references `road_segments.id`, which seed.sql generates by
  ordinal arithmetic (1001…3050). The router's graph uses `Edge.id` from
  `build_synthetic_grid` (0…259). Those are **two independent synthetic generators** with no
  shared identifier and no shared geometry.

  Three ways to join them:

    (a) by index (edge 0 -> segment 1001).  REJECTED. It fabricates correspondence: segment
        1001's reason text describes a closure on a road that does not exist at that place.
        Presenting that as verified status for an unrelated edge is exactly the fabrication
        the project forbids.
    (b) by name, coordinates, or nearest-distance.  REJECTED by the M8 brief explicitly, and
        rightly: fuzzy matching silently produces false verification.
    (c) by an EXPLICIT shared identifier.  ADOPTED. The join key is
        `graph_edge.id == road_status.road_segment_id`, and it is only meaningful when both
        sides were built from the same source (real OSM way ids). `RoadGraph.from_edges`
        already preserves OSM way ids as `Edge.id`, so a real extract maps cleanly.

  Consequence for the CURRENT dataset: the join matches **zero** rows, because the two
  synthetic generators overlap in nothing. That is reported honestly via `matched_edge_count`
  rather than papered over. Edges with no record stay `unknown`, which lowers coverage and
  prevents a recommendation — the correct outcome for a system with no road observations.

AUTHORIZATION
  This module performs no writes. It takes an injected `fetch` callable so a server-side
  connection supplies the rows; it never reads a role, user id, or session setting, and it is
  not reachable from an HTTP route. N-2 remains open and is not affected either way by a
  read-only path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable, Literal, Sequence

from app.routing.graph import (
    STATUS_AFFECTED,
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_UNKNOWN,
    EdgeStatus,
    StatusIndex,
)

StatusValue = Literal["open", "affected", "closed", "unknown"]
SourceValue = Literal["operator", "system", "report", "seed"]

VALID_STATUSES: tuple[str, ...] = (STATUS_OPEN, STATUS_AFFECTED, STATUS_CLOSED, STATUS_UNKNOWN)
VALID_SOURCES: tuple[str, ...] = ("operator", "system", "report", "seed")


class RepositoryError(Exception):
    """Raised only for programmer error (bad arguments), never for a DB failure."""


@dataclass(frozen=True)
class RoadStatusRecord:
    """One persisted row, as fetched. Validation happens in `from_row`."""

    road_segment_id: int
    status: str
    set_at: datetime
    review_at: datetime | None
    source: str
    reason: str | None = None

    @classmethod
    def from_row(cls, row: Sequence[Any]) -> "RoadStatusRecord":
        """Build from a positional row: (id, status, set_at, review_at, source, reason).

        Raises RepositoryError on a shape or value the schema would not have produced —
        a malformed row means the caller passed something unexpected, and silently coercing
        it could turn an unknown state into an apparently-verified one.
        """
        if len(row) < 5:
            raise RepositoryError(f"expected >= 5 columns, got {len(row)}")
        seg_id, status, set_at, review_at, source = row[0], row[1], row[2], row[3], row[4]
        reason = row[5] if len(row) > 5 else None

        if not isinstance(seg_id, int):
            raise RepositoryError(f"road_segment_id must be int, got {type(seg_id).__name__}")
        if status not in VALID_STATUSES:
            raise RepositoryError(f"unknown status {status!r}")
        if source not in VALID_SOURCES:
            raise RepositoryError(f"unknown source {source!r}")
        if not isinstance(set_at, datetime):
            raise RepositoryError("set_at must be a datetime")
        if status == STATUS_CLOSED and not (reason and str(reason).strip()):
            # The table has a CHECK for this, so a closed row without a reason can only come
            # from a query that omitted the column. Refuse rather than lose the explanation.
            raise RepositoryError("closed record has no reason; query probably omitted it")

        return cls(
            road_segment_id=seg_id,
            status=status,
            set_at=set_at,
            review_at=review_at,
            source=source,
            reason=reason,
        )

    def is_stale(self, now: datetime, default_freshness: timedelta) -> bool:
        """Freshness from `review_at` when set, else from `set_at` + default budget.

        A row whose review deadline has passed is no longer a current claim. Note (O-8): a
        stale CLOSURE is still treated as a closure for exclusion purposes — see
        `build_status_index`.
        """
        if self.review_at is not None:
            return self.review_at < now
        return (now - self.set_at) > default_freshness


@dataclass
class StatusLoadResult:
    """Outcome of a status load, including how much of it actually applied."""

    index: StatusIndex
    records_fetched: int
    records_applied: int
    matched_edge_count: int
    error: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def unmapped(self) -> int:
        """Records that matched no edge in the graph. Zero is the honest current answer."""
        return max(self.records_fetched - self.matched_edge_count, 0)


# Two queries, deliberately separate.
#
# SELECT_SQL keeps the legacy behaviour: join on `road_segment_id`. It is retained because the
# seeded demo dataset still uses it, and removing it would change existing behaviour.
SELECT_SQL = """
select rs.road_segment_id, rs.status, rs.set_at, rs.review_at, rs.source, rs.reason
  from road_status rs
 order by rs.road_segment_id
"""

# SELECT_BY_EDGE_SQL is the M9 identity path (N-8). It joins graph edge ids to status through
# `road_segments.edge_id`, which is `osm_way_id * 1000 + segment_ordinal` on both sides because
# the graph and the rows come from the SAME extract. No position, name or distance matching.
SELECT_BY_EDGE_SQL = """
select rs.edge_id, st.status, st.set_at, st.review_at, st.source, st.reason, rs.id
  from road_segments rs
  join road_status st on st.road_segment_id = rs.id
 where rs.edge_id is not null
 order by rs.edge_id
"""

FetchFn = Callable[[str], Sequence[Sequence[Any]]]


def load_status_by_edge(
    *,
    graph_edge_ids: Iterable[int],
    fetch: FetchFn,
    now: datetime,
    default_freshness: timedelta,
) -> StatusLoadResult:
    """Load status using the STABLE EDGE IDENTITY join (N-8).

    Row shape: (edge_id, status, set_at, review_at, source, reason, road_segment_id).

    The join is done in SQL on `road_segments.edge_id`, so an edge receives status only if a
    persisted row genuinely encodes that exact source segment. Unmatched edges stay unknown.
    """
    edge_id_set = set(graph_edge_ids)

    try:
        rows = fetch(SELECT_BY_EDGE_SQL)
    except Exception as exc:  # noqa: BLE001 - degrade to unknown, never to clear
        return StatusLoadResult(
            index=StatusIndex([], now=now, freshness=default_freshness),
            records_fetched=0,
            records_applied=0,
            matched_edge_count=0,
            error=f"{type(exc).__name__}: {exc}",
            notes=("edge-identity status feed unavailable; all edges treated as unknown",),
        )

    usable: list[EdgeStatus] = []
    matched = 0
    unmapped = 0
    stale_count = 0
    notes: list[str] = []

    for row in rows:
        if len(row) < 7:
            notes.append(f"skipped malformed row: expected >= 7 columns, got {len(row)}")
            continue
        edge_id, status, set_at, review_at, source, reason, _seg_id = row[:7]

        if not isinstance(edge_id, int):
            notes.append(f"skipped row with non-integer edge_id: {edge_id!r}")
            continue
        if status not in VALID_STATUSES:
            notes.append(f"skipped row with unknown status {status!r}")
            continue

        if edge_id not in edge_id_set:
            # The database knows about a segment this graph does not contain. Drop it: the
            # alternative is guessing which edge it was meant for.
            unmapped += 1
            continue

        matched += 1
        if status == STATUS_UNKNOWN:
            continue

        rec = RoadStatusRecord(
            road_segment_id=int(_seg_id),
            status=status,
            set_at=set_at,
            review_at=review_at,
            source=source if source in VALID_SOURCES else "operator",
            reason=reason,
        )
        is_stale = rec.is_stale(now, default_freshness)
        if is_stale:
            stale_count += 1
        # Staleness via the `verified` flag, never by back-dating set_at (see M8 D-3).
        usable.append(EdgeStatus(edge_id, status, set_at, verified=not is_stale))

    if unmapped:
        notes.append(
            f"{unmapped} persisted status row(s) reference a segment absent from this graph; "
            f"dropped rather than remapped"
        )
    if stale_count:
        notes.append(
            f"{stale_count} record(s) past their review deadline; no coverage credit, and a "
            f"stale closure remains excluded from phase 1 (O-8)"
        )
    notes.append("edges with no persisted record remain unknown — not clear")

    return StatusLoadResult(
        index=StatusIndex(usable, now=now, freshness=default_freshness),
        records_fetched=len(rows),
        records_applied=matched,
        matched_edge_count=matched,
        error=None,
        notes=tuple(notes),
    )


def load_status(
    *,
    graph_edge_ids: Iterable[int],
    fetch: FetchFn,
    now: datetime,
    default_freshness: timedelta,
    enabled: bool = True,
) -> StatusLoadResult:
    """Read persisted status and adapt it to the routing engine's inputs.

    `enabled=False` returns an empty index and says so — the explicit switch for "the
    database integration is not configured", which is the honest default when no trusted
    connection exists (N-2 / deployment prerequisite).

    Never raises for a database failure: a missing status feed must degrade to `unknown`,
    not to "clear" and not to a crash.
    """
    edge_id_set = set(graph_edge_ids)

    if not enabled:
        return StatusLoadResult(
            index=StatusIndex([], now=now, freshness=default_freshness),
            records_fetched=0,
            records_applied=0,
            matched_edge_count=0,
            notes=(
                "road-status persistence is not enabled; every edge is unknown",
                "unknown is not the same as clear: coverage is 0 % and nothing is recommended",
            ),
        )

    try:
        rows = fetch(SELECT_SQL)
    except Exception as exc:  # noqa: BLE001 - converted to a degraded result by design
        return StatusLoadResult(
            index=StatusIndex([], now=now, freshness=default_freshness),
            records_fetched=0,
            records_applied=0,
            matched_edge_count=0,
            error=f"{type(exc).__name__}: {exc}",
            notes=("status feed unavailable; all edges treated as unknown",),
        )

    records: list[RoadStatusRecord] = []
    notes: list[str] = []
    for raw in rows:
        try:
            records.append(RoadStatusRecord.from_row(raw))
        except RepositoryError as exc:
            notes.append(f"skipped malformed row: {exc}")

    index, matched, applied_notes = build_status_index(
        records, edge_id_set, now=now, default_freshness=default_freshness
    )
    notes.extend(applied_notes)

    return StatusLoadResult(
        index=index,
        records_fetched=len(records),
        records_applied=matched,
        matched_edge_count=matched,
        error=None,
        notes=tuple(notes),
    )


def build_status_index(
    records: Iterable[RoadStatusRecord],
    known_edge_ids: set[int],
    *,
    now: datetime,
    default_freshness: timedelta,
) -> tuple[StatusIndex, int, tuple[str, ...]]:
    """Adapt records into the engine's `StatusIndex`.

    Returns (index, matched_count, notes).

    Behaviour worth stating explicitly:

      * A record whose `road_segment_id` is not an edge in this graph is DROPPED, not
        remapped. Fuzzy remapping is how false verification gets invented.
      * A stale record still contributes its status for EXCLUSION purposes (O-8): a stale
        closure stays closed. `StatusIndex` handles the coverage consequence by treating it
        as unverified.
      * A record with status `unknown` is dropped: there is nothing to add over the default,
        which is already `unknown` for every edge with no record.
    """
    usable: list[EdgeStatus] = []
    matched = 0
    unmatched_statuses = 0
    stale_count = 0

    for rec in records:
        if rec.road_segment_id not in known_edge_ids:
            unmatched_statuses += 1
            continue
        matched += 1
        if rec.status == STATUS_UNKNOWN:
            continue
        is_stale = rec.is_stale(now, default_freshness)
        if is_stale:
            stale_count += 1
        # `set_at` is passed through UNCHANGED. Staleness is communicated via the `verified`
        # flag rather than by back-dating the timestamp — rewriting `set_at` would falsify a
        # stored value to influence a downstream calculation, and would make a stale closure
        # look freshly confirmed.
        #
        # Note the deliberate asymmetry (O-8): an expired CLOSURE stays in the index so it is
        # still excluded from phase 1; `verified=False` only removes its coverage credit.
        usable.append(
            EdgeStatus(
                rec.road_segment_id,
                rec.status,
                rec.set_at,
                verified=not is_stale,
            )
        )

    notes: list[str] = []
    if unmatched_statuses:
        notes.append(
            f"{unmatched_statuses} persisted status record(s) reference segments that are "
            f"not edges in this graph — not remapped, because guessing the correspondence "
            f"would fabricate verification"
        )
    if stale_count:
        notes.append(
            f"{stale_count} record(s) are past their review deadline; they no longer count "
            f"as verified coverage, and a stale closure remains excluded from phase 1"
        )
    notes.append(
        "edges with no persisted record remain unknown — that is not the same as clear"
    )

    return (
        StatusIndex(usable, now=now, freshness=default_freshness),
        matched,
        tuple(notes),
    )
