"""Tests for the road-report lifecycle — the status and freshness rules.

Deliberately database-free and clock-injected: every assertion here is about a RULE, and a rule
that needs a database to test is a rule that will be tested rarely. `now` is passed in, so
"three hours later" is one line rather than a sleep.

The five properties worth guarding, each from a specific clause of the brief:
  1. a new report is unverified and does not close a road        (feature B §4, C §5)
  2. expiration never turns a closure into a passable road       (feature D §6 rule 3)
  3. expiration DOES stop it counting as current evidence        (feature D §6 rule 2)
  4. an unverified report may only ever produce a caution        (feature B §4)
  5. conflicting verified reports stay visible, resolved by risk (feature C §5, D §6)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.reports.lifecycle import (
    DEFAULT_STALE_AFTER_MINUTES,
    LifecycleError,
    ReportClaim,
    compute_expiry,
    corroboration_tally,
    derive_effective_status,
    extend_expiry,
    validate_stale_after_minutes,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
SEGMENT = 544794745003


def claim(
    *,
    decision: str = "unverified",
    segment: int = SEGMENT,
    submitted: datetime | None = None,
    verified: datetime | None = None,
    expires: datetime | None = None,
    report_id: str = "r1",
    confirms: int = 0,
    challenges: int = 0,
) -> ReportClaim:
    """Build a valid claim, keeping the lifecycle's own invariants satisfied.

    Two ordering constraints must hold for ANY realistic claim, and a fixture that breaks them
    is testing an impossible state rather than a rule:
        submitted_at <= verified_at <= expires_at
    So when `expires` is supplied in the past, `verified` is placed between `submitted` and
    `expires` rather than at `submitted` — which is exactly how a real report that was once
    verified and has since expired looks.
    """
    submitted = submitted or NOW - timedelta(minutes=10)
    if expires is None:
        expires = submitted + timedelta(minutes=DEFAULT_STALE_AFTER_MINUTES)
    if expires <= submitted:
        # The caller asked for a claim that expired BEFORE it was submitted, which is not a
        # state a report can be in. Move the submission back so the timeline stays honest:
        # submitted -> verified -> expires. Testing an impossible state would prove nothing.
        submitted = expires - timedelta(minutes=DEFAULT_STALE_AFTER_MINUTES)
    if verified is None and decision not in ("unverified", "rejected"):
        verified = min(submitted, expires)
    return ReportClaim(
        report_id=report_id,
        road_segment_id=segment,
        decision=decision,  # type: ignore[arg-type]
        submitted_at=submitted,
        verified_at=verified,
        expires_at=expires,
        confirm_count=confirms,
        challenge_count=challenges,
    )


# ===========================================================================
# 1. A new report is unverified and closes nothing
# ===========================================================================


def test_unverified_report_never_closes_a_road() -> None:
    """The single most important rule: a photograph is not an administrative decision."""
    c = claim(decision="unverified")
    assert c.road_status(NOW) == "affected"
    result = derive_effective_status([c], NOW)
    found = result.get(SEGMENT)
    assert found is not None
    assert found.status == "affected"
    assert found.status != "closed"
    assert found.verified is False
    assert found.unverified_caution is True


@pytest.mark.parametrize("decision", ["unverified", "potential_hazard", "inconclusive"])
def test_non_verified_decisions_never_assert_open_or_closed(decision: str) -> None:
    """Only a verified decision may assert `closed`, and only a verified one may assert `open`."""
    c = claim(decision=decision)
    assert c.road_status(NOW) == "affected"


def test_unverified_stays_unverified_until_a_decision_exists() -> None:
    """Age alone must not promote a report to verified or demote it to stale-evidence."""
    c = claim(decision="unverified")
    assert c.public_state(NOW) == "unverified"
    later = NOW + timedelta(days=1)
    # Still unverified: nobody reviewed it, so it did not become anything else.
    assert c.public_state(later) == "unverified"
    # But it is no longer current evidence.
    assert c.road_status(later) == "unknown"
    assert c.counts_as_current_evidence(later) is False


# ===========================================================================
# 2. Expiration never turns a closure into a passable road
# ===========================================================================


def test_expired_closure_is_still_a_closure() -> None:
    """Feature D rule 3, the highest-stakes rule in the module."""
    c = claim(decision="blocked_verified", expires=NOW - timedelta(minutes=1))
    assert c.is_stale(NOW) is True
    # The claim is unchanged by age.
    assert c.decision == "blocked_verified"
    # And it still closes the edge.
    assert c.road_status(NOW) == "closed"


def test_expired_closure_loses_verification_but_not_exclusion() -> None:
    """Rule 2 (no longer current evidence) must not contradict rule 3 (still closed)."""
    c = claim(decision="blocked_verified", expires=NOW - timedelta(minutes=1))
    result = derive_effective_status([c], NOW)
    found = result.get(SEGMENT)
    assert found is not None
    assert found.status == "closed"          # excluded from routing
    assert found.verified is False           # not current evidence -> lowers coverage
    assert found.stale_closure is True       # and is disclosed as such


def test_expired_closure_is_never_described_as_passable() -> None:
    """No code path may return `open` from an expired closure."""
    for delta in (1, 60, 60 * 24, 60 * 24 * 365):
        c = claim(decision="blocked_verified", expires=NOW - timedelta(minutes=delta))
        assert c.road_status(NOW) == "closed", delta


def test_stale_closure_is_counted_in_the_derived_summary() -> None:
    claims = [
        claim(decision="blocked_verified", expires=NOW - timedelta(minutes=5), report_id="old"),
        claim(decision="blocked_verified", expires=NOW + timedelta(hours=1), report_id="new"),
    ]
    result = derive_effective_status(claims, NOW)
    assert result.segments_closed == 1
    assert result.segments_stale_closure == 0  # the fresh one wins, so not stale overall


def test_only_stale_closures_are_reported_as_stale() -> None:
    claims = [claim(decision="blocked_verified", expires=NOW - timedelta(minutes=5))]
    result = derive_effective_status(claims, NOW)
    assert result.segments_closed == 1
    assert result.segments_stale_closure == 1


# ===========================================================================
# 3. Expiration does stop it counting as current evidence
# ===========================================================================


def test_fresh_verified_closure_counts_as_verified_evidence() -> None:
    c = claim(decision="blocked_verified", expires=NOW + timedelta(hours=1))
    assert c.is_verified(NOW) is True
    assert c.counts_as_current_evidence(NOW) is True


def test_stale_passable_degrades_to_caution_not_to_open() -> None:
    """Old evidence that a road was fine is not current evidence that it is fine."""
    c = claim(decision="passable_verified", expires=NOW - timedelta(minutes=1))
    assert c.road_status(NOW) == "affected"


def test_fresh_passable_is_open() -> None:
    c = claim(decision="passable_verified", expires=NOW + timedelta(hours=1))
    assert c.road_status(NOW) == "open"
    assert c.is_verified(NOW) is True


def test_stale_only_evidence_yields_caution_and_is_hidden_when_asked() -> None:
    c = claim(decision="potential_hazard", expires=NOW - timedelta(minutes=1))
    with_stale = derive_effective_status([c], NOW)
    assert with_stale.get(SEGMENT) is not None
    assert with_stale.get(SEGMENT).status == "affected"  # type: ignore[union-attr]

    current_only = derive_effective_status([c], NOW, include_stale=False)
    assert current_only.get(SEGMENT) is None


def test_expired_reports_are_retained_not_deleted() -> None:
    """The derivation must not need a report to be removed in order to forget it."""
    c = claim(decision="blocked_verified", expires=NOW - timedelta(days=30))
    result = derive_effective_status([c], NOW)
    assert result.segments_with_reports == 1
    assert result.get(SEGMENT) is not None


# ===========================================================================
# 4. Verified decisions and public state labels
# ===========================================================================


@pytest.mark.parametrize(
    ("decision", "expected_state"),
    [
        ("unverified", "unverified"),
        ("potential_hazard", "potential_hazard"),
        ("blocked_verified", "blocked_verified"),
        ("passable_verified", "passable_verified"),
        ("inconclusive", "inconclusive"),
    ],
)
def test_public_state_matches_decision_when_fresh(decision: str, expected_state: str) -> None:
    c = claim(decision=decision, expires=NOW + timedelta(hours=1))
    assert c.public_state(NOW) == expected_state


@pytest.mark.parametrize(
    "decision",
    ["potential_hazard", "blocked_verified", "passable_verified", "inconclusive"],
)
def test_stale_claims_report_the_stale_state(decision: str) -> None:
    """A stale chip is shown instead of the decision, but `decision` is preserved."""
    c = claim(decision=decision, expires=NOW - timedelta(minutes=1))
    assert c.public_state(NOW) == "stale"
    assert c.decision == decision


def test_rejected_contributes_nothing_and_is_not_verified() -> None:
    c = claim(decision="rejected")
    assert c.road_status(NOW) == "unknown"
    assert c.is_verified(NOW) is False
    assert c.counts_as_current_evidence(NOW) is False
    # And it is dropped by the derivation entirely.
    result = derive_effective_status([c], NOW)
    assert result.get(SEGMENT) is None
    assert result.segments_with_reports == 0


# ===========================================================================
# 5. Conflicts are preserved, resolved by risk
# ===========================================================================


def test_conflicting_verified_reports_are_both_kept() -> None:
    blocked = claim(
        decision="blocked_verified", report_id="a", expires=NOW + timedelta(hours=1)
    )
    passable = claim(
        decision="passable_verified", report_id="b", expires=NOW + timedelta(hours=1)
    )
    result = derive_effective_status([blocked, passable], NOW)

    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.blocked_report_id == "a"
    assert conflict.passable_report_id == "b"
    assert "blocked" in conflict.as_text()

    found = result.get(SEGMENT)
    assert found is not None
    # The higher-risk reading wins, and both report ids remain attached.
    assert found.status == "closed"
    assert set(found.support_report_ids) == {"a"}


def test_conflict_is_deterministic_regardless_of_input_order() -> None:
    """Conflicting evidence must not behave differently depending on database row order."""
    blocked = claim(decision="blocked_verified", report_id="a", expires=NOW + timedelta(hours=1))
    passable = claim(decision="passable_verified", report_id="b", expires=NOW + timedelta(hours=1))

    first = derive_effective_status([blocked, passable], NOW)
    second = derive_effective_status([passable, blocked], NOW)
    assert first.get(SEGMENT).status == second.get(SEGMENT).status  # type: ignore[union-attr]
    assert len(first.conflicts) == len(second.conflicts) == 1


def test_stale_closure_plus_fresh_passable_still_closes() -> None:
    """An operator verifying 'passable' must do so by decision, not by the closure ageing out."""
    stale_closure = claim(
        decision="blocked_verified", report_id="a", expires=NOW - timedelta(minutes=1)
    )
    fresh_passable = claim(
        decision="passable_verified", report_id="b", expires=NOW + timedelta(hours=1)
    )
    result = derive_effective_status([stale_closure, fresh_passable], NOW)
    found = result.get(SEGMENT)
    assert found is not None
    assert found.status == "closed"
    # The conflict is surfaced so a reviewer can see the disagreement.
    assert len(result.conflicts) == 1


def test_fresh_closure_beats_fresh_passable_by_risk() -> None:
    claims = [
        claim(decision="passable_verified", report_id="b", expires=NOW + timedelta(hours=1)),
        claim(decision="blocked_verified", report_id="a", expires=NOW + timedelta(hours=1)),
    ]
    result = derive_effective_status(claims, NOW)
    assert result.get(SEGMENT).status == "closed"  # type: ignore[union-attr]


# ===========================================================================
# 6. Freshness policy
# ===========================================================================


def test_expiry_is_derived_from_the_configured_window() -> None:
    assert compute_expiry(NOW, 60) == NOW + timedelta(minutes=60)
    assert compute_expiry(NOW, DEFAULT_STALE_AFTER_MINUTES) == NOW + timedelta(
        minutes=DEFAULT_STALE_AFTER_MINUTES
    )


@pytest.mark.parametrize("bad", [0, -1, 60 * 24 * 30, True, 1.5, "60"])
def test_invalid_stale_windows_are_rejected(bad: object) -> None:
    """A zero or negative window would silently disable the whole feature."""
    with pytest.raises(LifecycleError):
        validate_stale_after_minutes(bad)  # type: ignore[arg-type]


def test_extend_expiry_never_shortens() -> None:
    future = NOW + timedelta(hours=10)
    assert extend_expiry(future, now=NOW, stale_after_minutes=60) == future
    assert extend_expiry(NOW, now=NOW, stale_after_minutes=60) == NOW + timedelta(minutes=60)


def test_corroboration_tally_clamps_negatives() -> None:
    assert corroboration_tally(-3, 2) == (0, 2)


# ===========================================================================
# 7. Claim validation
# ===========================================================================


def test_verified_decision_requires_verified_at() -> None:
    with pytest.raises(LifecycleError, match="requires verified_at"):
        ReportClaim(
            report_id="x",
            road_segment_id=1,
            decision="blocked_verified",
            submitted_at=NOW,
            verified_at=None,
            expires_at=NOW + timedelta(hours=1),
        )


def test_decision_after_its_own_expiry_is_rejected() -> None:
    """Such a claim would be born stale, which is a caller bug, not a data condition."""
    with pytest.raises(LifecycleError, match="stale the moment"):
        ReportClaim(
            report_id="x",
            road_segment_id=1,
            decision="blocked_verified",
            submitted_at=NOW - timedelta(hours=5),
            verified_at=NOW,
            expires_at=NOW - timedelta(hours=1),
        )


def test_segment_id_must_be_positive() -> None:
    with pytest.raises(LifecycleError, match="positive graph edge id"):
        claim(segment=0)


def test_unknown_decision_is_rejected() -> None:
    with pytest.raises(LifecycleError, match="unknown decision"):
        claim(decision="probably_fine")


# ===========================================================================
# 8. Multi-segment behaviour
# ===========================================================================


def test_segments_are_derived_independently() -> None:
    claims = [
        claim(decision="blocked_verified", segment=1, report_id="a", expires=NOW + timedelta(hours=1)),
        claim(decision="passable_verified", segment=2, report_id="b", expires=NOW + timedelta(hours=1)),
        claim(decision="unverified", segment=3, report_id="c", expires=NOW + timedelta(hours=1)),
    ]
    result = derive_effective_status(claims, NOW)
    assert result.get(1).status == "closed"  # type: ignore[union-attr]
    assert result.get(2).status == "open"  # type: ignore[union-attr]
    assert result.get(3).status == "affected"  # type: ignore[union-attr]
    assert result.segments_closed == 1


def test_empty_input_yields_empty_derivation() -> None:
    result = derive_effective_status([], NOW)
    assert result.by_segment == {}
    assert result.conflicts == ()
    assert result.segments_with_reports == 0
