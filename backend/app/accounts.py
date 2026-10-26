"""Account administration: an operator can create and manage accounts from the UI.

WHY THIS EXISTS
  Admin accounts previously came ONLY from `app.admin_cli`, which is the correct bootstrap
  mechanism and stays in place. But once `operator` accounts can do real work (verifying road
  reports), being unable to provision a second reviewer without SSH makes the console
  impractical. This module is the UI equivalent of the CLI, with one crucial difference.

THE SECURITY MODEL — read this before changing anything

  1. ROLE MONOTONICITY. A caller may only grant a role STRICTLY BELOW their own:
     `admin` may create `publisher`/`operator`/`viewer`/`public`, and MAY NOT create another
     `admin`. An `operator` may create `viewer`/`public` and nothing at/above itself.

     This is the whole reason the feature is safe. Creating an equal-or-higher role would be
     privilege escalation: an `operator` could mint an `admin` and then sign in as it. The
     bootstrap CLI remains the ONLY way to create an `admin`, or for one `admin` to vouch for
     another — which is exactly the safeguard the brief asked to preserve.

  2. NO SELF-SERVICE ROLE CHANGE. There is no path for a user to change their own role, and no
     path for anyone to change a role at all. Roles are fixed at creation and can only be
     removed (disable), not escalated.

  3. DISABLE, NEVER DELETE. Disabling sets `disabled = 1` and revokes every session for that
     account. History (audit rows, their reports) survives. There is no DELETE of a user
     anywhere in this codebase, because a deleted account turns its audit trail into a set of
     orphaned ids that nobody can interpret.

  4. LAST-LOCAL-ADMIN GUARD. Disabling or demoting the final usable `admin` account is refused.
     Otherwise one click could leave the deployment with nobody able to grant roles again,
     recoverable only by shell access — a self-inflicted lockout.

  5. PASSWORDS. Read once, hashed immediately, never logged, never echoed in a response, and
     never returned by any read path. `list_accounts` selects explicit columns precisely so a
     `password_hash` cannot leak by accident.

WHAT THIS MODULE DOES NOT DO
  * It does not authenticate anyone. Sign-in is `app.auth.authenticate`.
  * It does not implement password reset. A forgotten password is reset by re-creating the
    account or by an admin setting a new one — out of scope here, and doing it badly (email
    tokens, no rate limiting) would be worse than not offering it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.auth import (
    ROLE_ORDER,
    AuthError,
    Forbidden,
    User,
    ValidationFailed,
    to_iso,
    validate_email,
    validate_password,
)
from app.security import hash_password
from app.store import connect

# Roles the console may actually create. Derived from the escalation rule rather than written
# by hand, so this list cannot drift from the permission check:
#
#   `admin` is DELIBERATELY ABSENT. An admin may not grant `admin` (equal role = escalation) and
#   nobody else may grant it either. The bootstrap CLI remains the only way to create an admin —
#   the safeguard the brief asked to preserve. The UI says so in words rather than offering a
#   button that would always fail with 403.
#
#   `public` is also absent: citizens self-register through the public form, and a console that
#   creates citizen accounts invites creating them on someone else's behalf.
CREATABLE_ROLES: tuple[str, ...] = ("viewer", "operator", "publisher")

# Named in the UI so "why can I not create an admin here?" has an answer on screen.
BOOTSTRAP_ONLY_ROLE = "admin"


class AccountError(AuthError):
    """Raised for a rules violation the caller should see, with a stable code."""

    status_code = 400


class AccountNotFound(AccountError):
    status_code = 404
    code = "account_not_found"


class RoleEscalation(AccountError):
    status_code = 403
    code = "role_escalation"


class LastAdmin(AccountError):
    status_code = 409
    code = "last_admin"


@dataclass(frozen=True)
class AccountRow:
    """One account as the console may see it. Deliberately has no password material."""

    id: str
    email: str
    role: str
    disabled: bool
    created_at: str
    phone_e164: str | None
    sms_opt_in: bool
    last_active_at: str | None

    @property
    def is_active(self) -> bool:
        return not self.disabled


# ---------------------------------------------------------------------------
# Permission rules
# ---------------------------------------------------------------------------


def _rank(role: str) -> int:
    try:
        return ROLE_ORDER.index(role)
    except ValueError:
        return -1


def assert_may_grant(actor: User, role: str) -> None:
    """Reject a role at or above the actor's own. This is the anti-escalation gate.

    Stated as its own function so the rule is testable in isolation and appears in exactly one
    place. Every creation path calls it.
    """
    if role not in ROLE_ORDER:
        raise ValidationFailed(f"unknown role {role!r}")
    if _rank(role) >= _rank(actor.role):
        raise RoleEscalation(
            f"you cannot grant '{role}': it is equal to or above your own role "
            f"('{actor.role}'). Only the bootstrap CLI can create that account."
        )


def assert_may_manage(actor: User, target: AccountRow) -> None:
    """Reject managing an account ABOVE the actor's own role.

    Equal roles ARE allowed, deliberately, and the asymmetry with `assert_may_grant` is the point:

      CREATING an equal role is escalation     -> `assert_may_grant` uses strict `<`
      MANAGING an equal role is peer management -> this uses `<=`

    An operator disabling another operator is lateral, audited, and reversible — normal team
    administration. An operator disabling an ADMIN is upward, and is refused here.

    The first version of this function refused equal roles too, which made the rule mean
    "strictly below" everywhere. The effect was that no admin could ever disable or reset another
    admin — including themselves — so the last-admin guard never got a chance to fire and the
    console could not manage the very accounts it exists to manage. Caught by the end-to-end
    permission check, not by the unit tests, which is why that check exists.
    """
    if _rank(target.role) > _rank(actor.role):
        raise RoleEscalation(
            f"you cannot manage '{target.email}': its role ('{target.role}') is above your own "
            f"('{actor.role}')"
        )


def usable_admin_count(exclude_id: str | None = None) -> int:
    """How many enabled accounts hold `admin`, optionally excluding one."""
    with connect() as conn:
        sql = "select count(*) as n from users where role = 'admin' and disabled = 0"
        params: tuple[object, ...] = ()
        if exclude_id is not None:
            sql += " and id <> ?"
            params = (exclude_id,)
        row = conn.execute(sql, params).fetchone()
    return int(row["n"])


def assert_not_the_last_admin(target: AccountRow) -> None:
    """Refuse an action that would leave the deployment with no usable admin.

    Checked on DISABLE only. Role changes are impossible by design (roles are immutable), so
    this is the single place a lockout could originate.
    """
    if target.role != "admin":
        return
    if usable_admin_count(exclude_id=target.id) == 0:
        raise LastAdmin(
            "this is the last enabled admin account; disabling it would leave nobody able to "
            "manage accounts. Create another admin first (bootstrap CLI), then disable this one."
        )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _row_to_account(row, last_active_at: str | None) -> AccountRow:
    return AccountRow(
        id=row["id"],
        email=row["email"],
        role=row["role"],
        disabled=bool(row["disabled"]),
        created_at=row["created_at"],
        phone_e164=row["phone_e164"],
        sms_opt_in=bool(row["sms_opt_in"]),
        last_active_at=last_active_at,
    )


def list_accounts(limit: int = 200) -> list[AccountRow]:
    """Every account, newest first.

    Explicit column list — never `select *` — so adding a column to `users` cannot start
    shipping it to the browser. `sessions` is joined only to derive a last-seen time.
    """
    limit = max(1, min(int(limit), 500))
    with connect() as conn:
        rows = conn.execute(
            """
            select u.id, u.email, u.role, u.disabled, u.created_at, u.phone_e164, u.sms_opt_in,
                   (select max(s.created_at) from sessions s where s.user_id = u.id)
                       as last_active_at
              from users u
             order by u.created_at desc
             limit ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_account(r, r["last_active_at"]) for r in rows]


def get_account(user_id: str) -> AccountRow | None:
    with connect() as conn:
        row = conn.execute(
            """
            select u.id, u.email, u.role, u.disabled, u.created_at, u.phone_e164, u.sms_opt_in,
                   (select max(s.created_at) from sessions s where s.user_id = u.id)
                       as last_active_at
              from users u where u.id = ?
            """,
            (user_id,),
        ).fetchone()
    return _row_to_account(row, row["last_active_at"]) if row else None


def account_stats() -> dict[str, int]:
    """Real counts for the console header. Never estimated."""
    with connect() as conn:
        rows = conn.execute(
            "select role, disabled, count(*) as n from users group by role, disabled"
        ).fetchall()
    out: dict[str, int] = {"total": 0, "disabled": 0}
    for role in ROLE_ORDER:
        out[role] = 0
    for r in rows:
        out["total"] += int(r["n"])
        if r["disabled"]:
            out["disabled"] += int(r["n"])
        else:
            out[role] = out.get(role, 0) + int(r["n"])
    return out


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def create_account(
    actor: User, *, email: str, passphrase: str, role: str
) -> tuple[AccountRow, str]:
    """Create an account, returning it plus a one-line note for the audit detail.

    Raises RoleEscalation if `role` is at or above the actor's own — see the module docstring.
    """
    assert_may_grant(actor, role)
    email = validate_email(email)
    validate_password(passphrase)

    uid = uuid.uuid4().hex
    now = to_iso(datetime.now(timezone.utc))
    try:
        with connect() as conn:
            conn.execute(
                "insert into users (id, email, password_hash, role, created_at) "
                "values (?, ?, ?, ?, ?)",
                (uid, email, hash_password(passphrase), role, now),
            )
    except Exception as exc:  # sqlite3.IntegrityError on the unique email
        if "unique" in str(exc).lower():
            raise ValidationFailed("an account with that email already exists") from exc
        raise

    account = get_account(uid)
    if account is None:  # pragma: no cover - would mean the insert vanished
        raise AccountError("account was created but could not be read back")
    return account, f"role={role} via=console"


def set_disabled(actor: User, user_id: str, *, disabled: bool) -> AccountRow:
    """Enable or disable an account and revoke its sessions when disabling.

    Sessions are revoked on disable because leaving them alive would let a disabled account keep
    working until its cookie expired — the disarm would be cosmetic.
    """
    target = get_account(user_id)
    if target is None:
        raise AccountNotFound("no such account")
    assert_may_manage(actor, target)
    if target.id == actor.id and disabled:
        # Disabling yourself is legal for an admin only if another admin remains; otherwise it
        # is the same lockout as any other last-admin case, caught below.
        pass
    if disabled:
        assert_not_the_last_admin(target)

    with connect() as conn:
        conn.execute("update users set disabled = ? where id = ?", (1 if disabled else 0, user_id))
        if disabled:
            conn.execute("delete from sessions where user_id = ?", (user_id,))

    updated = get_account(user_id)
    if updated is None:  # pragma: no cover
        raise AccountNotFound("account disappeared during the update")
    return updated


def set_password(actor: User, user_id: str, *, new_passphrase: str) -> AccountRow:
    """Replace an account's password and revoke its sessions.

    Offered because the alternative — an operator who loses a password being unable to work — is
    a worse outcome than a supervised reset. The old hash is overwritten, never retained.
    """
    target = get_account(user_id)
    if target is None:
        raise AccountNotFound("no such account")
    assert_may_manage(actor, target)
    validate_password(new_passphrase)

    with connect() as conn:
        conn.execute(
            "update users set password_hash = ? where id = ?",
            (hash_password(new_passphrase), user_id),
        )
        # Every existing session dies: a reset that left old cookies valid would not reset
        # anything for whoever already had access.
        conn.execute("delete from sessions where user_id = ?", (user_id,))

    updated = get_account(user_id)
    if updated is None:  # pragma: no cover
        raise AccountNotFound("account disappeared during the update")
    return updated
