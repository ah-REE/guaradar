"""Road-report lifecycle: statuses, freshness, and effective road status.

PURE MODULE — no database, no network, no filesystem, no clock reads. `now` is always
injected. That is what makes "a report went stale" a testable event at any instant instead of
something that only shows up in production a few hours later.

THE ONE RULE THAT SHAPES THIS WHOLE MODULE
    Requirement D.3, verbatim: "Expiration must never automatically turn a blocked road into
    a confirmed safe road."

    The tempting implementation is a `status` column holding `stale`, maintained by a job that
    rewrites old rows. Every such rewrite is a place where a closure can become an "open" and
    where an audit trail is silently edited by a scheduler.

    So `stale` is NOT a status here. It is a computed predicate over `expires_at`. A report's
    *claim* (blocked / passable / hazard) and its *freshness* are two independent facts, and
    they are kept in two independent places:

        claim      — stored, set only by an operator decision
        freshness  — derived, at read time, from `expires_at`

    Consequences that fall out for free rather than needing enforcement:
      * An expired closure still closes its edge. Age cannot open a road.
      * An expired closure stops counting as *verified evidence*, which lowers route coverage
        and pushes the router toward a cautious alternative. That is requirement D.9.
      * An expired passable claim degrades to `affected`, never to `open`. Old evidence that a
        road was fine is not current evidence that it is fine.
      * Historical reports are never deleted to make staleness go away.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
  * It does not compute a risk score. `app/domain/risk.py` owns that, and its five documented
    weights sum to 1.0. Report evidence reaches routing through edge status, not by adding a
    sixth weight to a model that was approved without one.
  * It does not call an unverified report a closure. A photograph plus a category is a claim,
    and an unverified claim may only ever produce a caution penalty (requirement: "A
    photograph alone must never cause a road to become officially blocked").
  * It does not average conflicting evidence. Blocked and passable claims on the same segment
    are both retained and reported as a conflict, per the project's standing rule (Stage 3
    §8.3, "ambiguity is displayed, not resolved").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Literal, Sequence

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# What an operator decided. `unverified` is the only value a submitter can cause.
Decision = Literal[
    "unverified",
    "potential_hazard",
    "blocked_verified",
    "passable_verified",
    "inconclusive",
    "rejected",
]

DECISIONS: tuple[Decision, ...] = (
    "unverified",
    "potential_hazard",
    "blocked_verified",
    "passable_verified",
    "inconclusive",
    "rejected",
)

# The states the brief asks to distinguish (feature D §6). `stale` appears here because it is
# a state USERS must see, but it is a *presentation* state and is never stored.
PublicState = Literal[
    "unverified",
    "potential_hazard",
    "blocked_verified",
    "passable_verified",
    "inconclusive",
    "rejected",
    "stale",
    "unknown",
]

# Report categories. Ordered most-to-least immediately dangerous for tie-breaking only; the
# order is NOT a safety model.
Category = Literal["flooded", "blocked", "debris", "damaged", "rising", "other"]
CATEGORIES: tuple[Category, ...] = ("flooded", "blocked", "debris", "damaged", "rising", "other")

# The edge status vocabulary already used by the routing engine. This module must speak it
# rather than inventing a parallel one, or the router would need a translation layer with its
# own bugs.
RoadStatus = Literal["open", "affected", "closed", "unknown"]

# Freshness policy. Requirement D.6 asks for a configurable stale-after period; these are the
# defaults, validated at the configuration boundary rather than trusted.
DEFAULT_STALE_AFTER_MINUTES = 360          # 6 hours
MIN_STALE_AFTER_MINUTES = 1
MAX_STALE_AFTER_MINUTES = 60 * 24 * 14     # two weeks


class LifecycleError(ValueError):
    """Raised for programmer error (bad arguments), never for data conditions."""


def validate_stale_after_minutes(value: int) -> int:
    """Bound the freshness window. A nonsensical value must fail at startup, not at 2 a.m.

    A negative or zero window would make every report stale the instant it is written, which
    silently disables the whole feature while looking configured. A window longer than two
    weeks makes "fresh" meaningless for a road condition.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise LifecycleError(f"stale_after_minutes must be an int, got {type(value).__name__}")
    if not MIN_STALE_AFTER_MINUTES <= value <= MAX_STALE_AFTER_MINUTES:
        raise LifecycleError(
            f"stale_after_minutes must be within "
            f"[{MIN_STALE_AFTER_MINUTES}, {MAX_STALE_AFTER_MINUTES}], got {value}"
        )
    return value


# ---------------------------------------------------------------------------
# A report as the lifecycle sees it — a value, not a database row
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportClaim:
    """One report's contribution to a road's status.

    Only the fields that can influence status. Coordinates, images and identity are
    deliberately absent: a status calculation must not be able to depend on who submitted
    something or what they photographed.
    """

    report_id: str
    road_segment_id: int
    decision: Decision
    submitted_at: datetime
    verified_at: datetime | None
    expires_at: datetime
    last_confirmed_at: datetime | None = None
    confirm_count: int = 0
    challenge_count: int = 0
    seeded: bool = False

    def __post_init__(self) -> None:
        if not self.report_id:
            raise LifecycleError("report_id must be non-empty")
        if self.road_segment_id <= 0:
            raise LifecycleError(
                f"{self.report_id}: road_segment_id must be a positive graph edge id"
            )
        if self.decision not in DECISIONS:
            raise LifecycleError(f"{self.report_id}: unknown decision {self.decision!r}")
        if self.confirm_count < 0 or self.challenge_count < 0:
            raise LifecycleError(f"{self.report_id}: counts must be >= 0")
        # An operator decision is attributable by schema constraint. Checking it here too
        # means a hand-built claim cannot smuggle in an unattributed verification.
        if self.decision not in ("unverified", "rejected") and self.verified_at is None:
            raise LifecycleError(
                f"{self.report_id}: decision {self.decision!r} requires verified_at"
            )
        # A verified decision dated after its own expiry would be born stale. Refuse it rather
        # than silently producing a claim that can never be current.
        if self.verified_at is not None and self.verified_at > self.expires_at:
            raise LifecycleError(
                f"{self.report_id}: verified_at is after expires_at; the decision would be "
                f"stale the moment it was made"
            )
        if self.expires_at < self.submitted_at:
            raise LifecycleError(f"{self.report_id}: expires_at precedes submitted_at")

    # -- freshness ---------------------------------------------------------

    def is_stale(self, now: datetime) -> bool:
        """Whether this claim's freshness window has closed.

        Note what this does NOT do: it does not touch, erase, or reinterpret `decision`. A
        stale blocked report is still a blocked report.
        """
        return now > self.expires_at

    def is_verified(self, now: datetime) -> bool:
        """Fresh AND operator-confirmed. Unverified or stale claims are never verified."""
        if self.decision in ("unverified", "rejected", "inconclusive"):
            return False
        return not self.is_stale(now)

    def public_state(self, now: datetime) -> PublicState:
        """The state label to render. Adds `stale` without removing the underlying claim.

        A stale claim reports `stale` rather than its decision because showing "Blocked —
        verified" for a two-day-old photograph would present aged evidence as current. The
        decision survives in `decision` for history and for routing.
        """
        if self.decision == "unverified":
            # An unverified report never becomes "stale evidence" in the corroborated sense;
            # it simply stays unverified. Age is still shown separately.
            return "unverified"
        if self.is_stale(now):
            return "stale"
        return self.decision  # type: ignore[return-value]

    # -- routing -----------------------------------------------------------

    def road_status(self, now: datetime) -> RoadStatus:
        """What this claim asserts about the road RIGHT NOW.

        The three asymmetries below are the whole safety design, so each is stated:

          1. A BLOCKED claim asserts `closed` whether or not it is stale. Age cannot open a
             road (matches existing project decision O-8 for persisted statuses).
          2. A PASSABLE claim asserts `open` only while fresh; once stale it asserts
             `affected`. Old evidence of passability is not current evidence of passability,
             and `affected` is the vocabulary's way of saying "travel possible, be careful".
          3. An UNVERIFIED or INCONCLUSIVE claim asserts `affected` only while fresh. It can
             never assert `closed` — a photograph is not an administrative decision — and it
             can never assert `open`, because nobody checked.
        """
        if self.decision == "rejected":
            # Rejected evidence contributes nothing. History is preserved by the caller.
            return "unknown"

        if self.decision == "blocked_verified":
            return "closed"

        if self.decision == "passable_verified":
            return "open" if not self.is_stale(now) else "affected"

        # unverified | potential_hazard | inconclusive
        return "affected" if not self.is_stale(now) else "unknown"

    def counts_as_current_evidence(self, now: datetime) -> bool:
        """Whether this report may still be presented as evidence of present conditions."""
        if self.decision == "rejected":
            return False
        if self.decision == "unverified":
            return not self.is_stale(now)
        return not self.is_stale(now)


# ---------------------------------------------------------------------------
# Effective road status
# ---------------------------------------------------------------------------

# Severity ordering used to pick the effective status. Higher wins. This is deliberately
# SEVERITY-first and not recency-first: the newest report on a closed road does not open it,
# because a driver arriving at a flooded junction is not helped by a newer optimistic post.
_SEVERITY: dict[RoadStatus, int] = {"closed": 3, "affected": 2, "open": 1, "unknown": 0}


@dataclass(frozen=True)
class StatusConflict:
    """Two verified claims that disagree. Retained, never averaged away."""

    road_segment_id: int
    blocked_report_id: str
    passable_report_id: str
    detail: str

    def as_text(self) -> str:
        return (
            f"segment {self.road_segment_id}: {self.blocked_report_id} reports blocked while "
            f"{self.passable_report_id} reports passable; both are kept and neither is "
            f"treated as settled"
        )


@dataclass(frozen=True)
class EffectiveRoadStatus:
    """The derived status of one segment, with its provenance attached."""

    road_segment_id: int
    status: RoadStatus
    # True only when a FRESH operator-verified claim supports this status. This is what the
    # routing engine counts toward coverage, so a stale closure lowers coverage rather than
    # pretending the road is known.
    verified: bool
    # How the status was decided, for the audit trail and for explaining a route.
    basis: str
    support_report_ids: tuple[str, ...] = ()
    # A verified closure that is no longer fresh: still closed, no longer current evidence.
    stale_closure: bool = False
    # An unverified hazard: caution, not closure.
    unverified_caution: bool = False
    conflicts: tuple[StatusConflict, ...] = ()

    @property
    def reports_influencing(self) -> int:
        return len(self.support_report_ids)


@dataclass(frozen=True)
class EffectiveStatusSet:
    """Result of deriving statuses for many segments at once."""

    by_segment: dict[int, EffectiveRoadStatus] = field(default_factory=dict)
    conflicts: tuple[StatusConflict, ...] = ()
    segments_with_reports: int = 0
    segments_closed: int = 0
    segments_stale_closure: int = 0

    def get(self, segment_id: int) -> EffectiveRoadStatus | None:
        return self.by_segment.get(segment_id)


def derive_effective_status(
    claims: Iterable[ReportClaim],
    now: datetime,
    *,
    include_stale: bool = True,
) -> EffectiveStatusSet:
    """Derive one status per segment from all reports on it.

    Rules, in the order they are applied:

      1. Rejected claims are ignored entirely (they are not evidence of anything).
      2. A fresh verified BLOCKED claim closes the segment, full stop. This outranks every
         other claim, including a newer passable one, because the higher-risk reading wins
         when evidence conflicts — and the conflict is recorded rather than hidden.
      3. Otherwise a fresh verified PASSABLE claim opens it.
      4. Otherwise an unverified/inconclusive fresh claim marks it `affected` (caution).
      5. Otherwise stale evidence yields `affected` for a stale closure (never `open`) and no
         status at all when `include_stale` is False.

    `include_stale=False` is used only by callers that want "current evidence only", such as
    the public "what is happening now" map. Routing always calls it with the default, because
    a stale closure must still be avoided.
    """
    grouped: dict[int, list[ReportClaim]] = {}
    for c in claims:
        if c.decision == "rejected":
            continue
        grouped.setdefault(c.road_segment_id, []).append(c)

    by_segment: dict[int, EffectiveRoadStatus] = {}
    all_conflicts: list[StatusConflict] = []
    closed = 0
    stale_closed = 0

    for segment_id, group in grouped.items():
        result, conflicts = _derive_one(segment_id, group, now, include_stale=include_stale)
        all_conflicts.extend(conflicts)
        if result is not None:
            by_segment[segment_id] = result
            if result.status == "closed":
                closed += 1
                if result.stale_closure:
                    stale_closed += 1

    return EffectiveStatusSet(
        by_segment=by_segment,
        conflicts=tuple(all_conflicts),
        segments_with_reports=len(grouped),
        segments_closed=closed,
        segments_stale_closure=stale_closed,
    )


def _derive_one(
    segment_id: int,
    group: Sequence[ReportClaim],
    now: datetime,
    *,
    include_stale: bool,
) -> tuple[EffectiveRoadStatus | None, list[StatusConflict]]:
    """Resolve one segment. Separate function so each rule stays readable."""
    conflicts: list[StatusConflict] = []

    blocked = [c for c in group if c.decision == "blocked_verified"]
    passable = [c for c in group if c.decision == "passable_verified"]
    hazard = [c for c in group if c.decision in ("unverified", "potential_hazard", "inconclusive")]

    fresh_blocked = [c for c in blocked if not c.is_stale(now)]
    stale_blocked = [c for c in blocked if c.is_stale(now)]
    fresh_passable = [c for c in passable if not c.is_stale(now)]

    # ---- conflict detection: any co-existing evidence of opposing verdicts ----------
    # Recorded whenever verified blocked and verified passable both exist, fresh or stale,
    # because "an admin said closed and another said open" is a fact a reviewer must see.
    if blocked and passable:
        newest_block = max(blocked, key=lambda c: (c.verified_at or c.submitted_at))
        newest_pass = max(passable, key=lambda c: (c.verified_at or c.submitted_at))
        conflicts.append(
            StatusConflict(
                road_segment_id=segment_id,
                blocked_report_id=newest_block.report_id,
                passable_report_id=newest_pass.report_id,
                detail=(
                    "verified blocked and verified passable claims both exist for this "
                    "segment"
                ),
            )
        )

    # ---- rule 2: a closure, fresh or stale, still closes ----------------------------
    if fresh_blocked:
        winner = max(fresh_blocked, key=lambda c: (c.verified_at or c.submitted_at))
        return (
            EffectiveRoadStatus(
                road_segment_id=segment_id,
                status="closed",
                verified=True,
                basis="fresh verified closure",
                support_report_ids=tuple(sorted({c.report_id for c in fresh_blocked})),
                conflicts=tuple(conflicts),
            ),
            conflicts,
        )

    # ---- rule 5a: an expired closure is STILL a closure, but not current evidence ----
    # This is requirement D.9's conservative routing policy: stop representing it as freshly
    # confirmed, keep the exclusion and the caution, never call the road safe.
    if stale_blocked:
        if not include_stale:
            return None, conflicts
        winner = max(stale_blocked, key=lambda c: (c.verified_at or c.submitted_at))
        return (
            EffectiveRoadStatus(
                road_segment_id=segment_id,
                status="closed",
                verified=False,          # NOT current evidence -> lowers coverage
                basis="expired verified closure; still excluded from routes, no longer current",
                support_report_ids=tuple(sorted({c.report_id for c in stale_blocked})),
                stale_closure=True,
                conflicts=tuple(conflicts),
            ),
            conflicts,
        )

    # ---- rule 3: fresh verified passable -------------------------------------------
    if fresh_passable:
        winner = max(fresh_passable, key=lambda c: (c.verified_at or c.submitted_at))
        return (
            EffectiveRoadStatus(
                road_segment_id=segment_id,
                status="open",
                verified=True,
                basis="fresh verified passable",
                support_report_ids=tuple(sorted({c.report_id for c in fresh_passable})),
                conflicts=tuple(conflicts),
            ),
            conflicts,
        )

    # ---- rule 4: unverified / inconclusive hazard, fresh only ----------------------
    fresh_hazard = [c for c in hazard if not c.is_stale(now)]
    if fresh_hazard:
        # An unverified report can only ever produce a caution. It cannot close the segment —
        # that is the administrative decision this module refuses to make on a photo's behalf.
        return (
            EffectiveRoadStatus(
                road_segment_id=segment_id,
                status="affected",
                verified=False,
                basis="unverified report: caution only, not a closure",
                support_report_ids=tuple(sorted({c.report_id for c in fresh_hazard})),
                unverified_caution=True,
                conflicts=tuple(conflicts),
            ),
            conflicts,
        )

    # ---- nothing current ------------------------------------------------------------
    if not include_stale:
        return None, conflicts

    # Only stale passable / stale hazard evidence exists. Neither may become `open`.
    stale_others = [c for c in group if c.is_stale(now)]
    if stale_others:
        return (
            EffectiveRoadStatus(
                road_segment_id=segment_id,
                status="affected",
                verified=False,
                basis="only expired evidence remains; conditions unknown, treated with caution",
                support_report_ids=tuple(sorted({c.report_id for c in stale_others})),
                conflicts=tuple(conflicts),
            ),
            conflicts,
        )

    return None, conflicts


# ---------------------------------------------------------------------------
# Freshness window
# ---------------------------------------------------------------------------


def compute_expiry(
    submitted_at: datetime, stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES
) -> datetime:
    """Freshness deadline for a newly submitted report.

    Deliberately NOT adjusted by weather. Requirement D.6 allows weather-adaptive freshness
    only if the rule is explainable and testable; tying it to a forecast would need a
    validated relationship between rainfall and reporting validity, and no such relationship
    has been established in this project. A fixed, configurable window is the honest choice,
    and inventing a weather multiplier would be exactly the "arbitrary" rule D.6 forbids.
    """
    validate_stale_after_minutes(stale_after_minutes)
    return submitted_at + timedelta(minutes=stale_after_minutes)


def extend_expiry(
    current_expiry: datetime,
    *,
    now: datetime,
    stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES,
) -> datetime:
    """New deadline after a corroborating event (an operator re-verification, or a fresh
    confirmation that genuinely re-observes the hazard).

    Never shortens the deadline: a confirmation cannot make evidence expire sooner, and a
    stale window that could be pulled forward by an unrelated event would be surprising.
    """
    validate_stale_after_minutes(stale_after_minutes)
    candidate = now + timedelta(minutes=stale_after_minutes)
    return candidate if candidate > current_expiry else current_expiry


def corroboration_tally(confirms: int, challenges: int) -> tuple[int, int]:
    """Return (confirms, challenges) with negatives clamped, for display.

    Community votes are EVIDENCE and never privilege. Nothing consumes this to change
    `decision`; it exists so the counts can be shown transparently next to the state.
    """
    return (max(0, confirms), max(0, challenges))
