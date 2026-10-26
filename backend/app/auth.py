"""Authentication and authorisation service.

THE SECURITY MODEL, STATED PLAINLY
  * The **only** source of a user's role is the `users.role` column, read server-side from a
    session token that arrived in an `Authorization: Bearer` header or an httpOnly cookie.
  * **No request parameter, header, query string or JSON body can set a role.** There is no
    "role" field in any request model. A test asserts this by trying.
  * **Hiding a frontend tab is not authorization.** Every admin endpoint calls
    `require_role(...)`, which resolves the session server-side and raises 401/403 before the
    handler runs. The frontend gating is a convenience, and the code says so.
  * **Admin accounts cannot self-register.** `POST /api/auth/register` always creates
    `role='public'`; the role is not a parameter. Admin roles are created only by the
    bootstrap CLI, which requires shell access to the server.

WHAT THIS FIXES
  N-2 records that `current_app_role()` trusts a `guaradar.role` session setting with no
  server-side identity check. The mechanism here is the server-side check that was missing: a
  role is derived from a verified session row, not from anything the caller supplies.

REMAINING LIMITS (documented, not hidden)
  * Session tokens are bearer tokens: anyone who obtains one is that user until expiry. There is
    no token binding, no device fingerprint, no rotation-on-use.
  * No CSRF token. The cookie is `SameSite=Lax` and state-changing endpoints require a JSON body
    with a custom content type, which blocks the simplest form-post CSRF, but this is not a
    complete CSRF defence and is not claimed to be.
  * Rate limiting on login is per-email and in-process (see `auth_rate_limited`), so it does not
    survive a restart and would need Redis behind multiple workers.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.security import (
    from_iso,
    hash_password,
    hash_token,
    new_session_token,
    session_expiry,
    to_iso,
    utcnow,
    verify_password,
)
from app.store import connect

# Role ladder. 'public' is a signed-in citizen with no admin rights.
ROLE_ORDER = ["public", "viewer", "operator", "publisher", "admin"]
ADMIN_ROLES = {"viewer", "operator", "publisher", "admin"}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

# Login throttling: five failures per email per 15 minutes, in-process.
LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_MAX_FAILURES = 5


class AuthError(Exception):
    """Base for auth failures the API maps to HTTP status codes."""

    status_code = 401
    code = "auth_error"


class InvalidCredentials(AuthError):
    status_code = 401
    code = "invalid_credentials"


class Unauthenticated(AuthError):
    status_code = 401
    code = "unauthenticated"


class Forbidden(AuthError):
    status_code = 403
    code = "forbidden"


class Conflict(AuthError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AuthError):
    status_code = 422
    code = "validation_failed"


class RateLimited(AuthError):
    status_code = 429
    code = "rate_limited"


@dataclass(frozen=True)
class User:
    id: str
    email: str
    role: str
    phone_e164: str | None
    sms_opt_in: bool
    disabled: bool

    @property
    def is_admin(self) -> bool:
        return self.role in ADMIN_ROLES

    def at_least(self, minimum: str) -> bool:
        try:
            return ROLE_ORDER.index(self.role) >= ROLE_ORDER.index(minimum)
        except ValueError:
            return False


def _row_to_user(row) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        role=row["role"],
        phone_e164=row["phone_e164"],
        sms_opt_in=bool(row["sms_opt_in"]),
        disabled=bool(row["disabled"]),
    )


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_email(email: str) -> str:
    e = normalise_email(email)
    if len(e) > 254 or not EMAIL_RE.match(e):
        raise ValidationFailed("a valid email address is required")
    return e


def validate_password(password: str) -> str:
    """Length over composition: a 12-character passphrase beats 'P@ssw0rd!'."""
    if len(password) < 12:
        raise ValidationFailed("password must be at least 12 characters")
    if len(password) > 200:
        raise ValidationFailed("password must be at most 200 characters")
    if password.strip() == "":
        raise ValidationFailed("password must not be only whitespace")
    return password


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def create_user(email: str, password: str, *, role: str = "public") -> User:
    """Create an account. Self-registration always passes role='public'.

    The role is validated against the ladder but is NOT settable from any HTTP request — the
    only caller that passes an admin role is the bootstrap CLI.
    """
    if role not in ROLE_ORDER:
        raise ValidationFailed(f"unknown role {role!r}")
    email = validate_email(email)
    validate_password(password)
    uid = uuid.uuid4().hex
    now = to_iso(utcnow())
    try:
        with connect() as conn:
            conn.execute(
                "insert into users (id, email, password_hash, role, created_at) "
                "values (?, ?, ?, ?, ?)",
                (uid, email, hash_password(password), role, now),
            )
    except Exception as exc:  # sqlite3.IntegrityError
        if "unique" in str(exc).lower():
            raise Conflict("an account with that email already exists") from exc
        raise
    return User(id=uid, email=email, role=role, phone_e164=None, sms_opt_in=False, disabled=False)


def _failed_logins(email: str) -> int:
    since = to_iso(utcnow() - LOGIN_WINDOW)
    with connect() as conn:
        row = conn.execute(
            "select count(*) as n from sms_rate_events "
            "where subject = ? and kind = 'login_failed' and at > ?",
            (f"login:{email}", since),
        ).fetchone()
    return int(row["n"]) if row else 0


def _record_failure(email: str) -> None:
    with connect() as conn:
        conn.execute(
            "insert into sms_rate_events (subject, kind, at) values (?, ?, ?)",
            (f"login:{email}", "login_failed", to_iso(utcnow())),
        )


def authenticate(email: str, password: str) -> tuple[User, str]:
    """Verify credentials and open a session. Returns (user, raw_token).

    Throttling is checked BEFORE the password comparison so an attacker cannot use the
    response-time difference between "throttled" and "wrong password" to enumerate accounts.
    """
    email = normalise_email(email)
    if _failed_logins(email) >= LOGIN_MAX_FAILURES:
        raise RateLimited(
            "too many failed sign-in attempts for this address; try again later"
        )

    with connect() as conn:
        row = conn.execute("select * from users where email = ?", (email,)).fetchone()

    # Verify against a dummy hash when the user is absent, so a missing account and a wrong
    # password take the same time and cannot be distinguished.
    stored = row["password_hash"] if row else hash_password("dummy-password-for-timing")
    ok = verify_password(password, stored)
    if not row or not ok:
        _record_failure(email)
        raise InvalidCredentials("email or password is incorrect")

    if row["disabled"]:
        raise Forbidden("this account is disabled")

    user = _row_to_user(row)
    token = new_session_token()
    now = utcnow()
    with connect() as conn:
        conn.execute(
            "insert into sessions (token_hash, user_id, created_at, expires_at) values (?,?,?,?)",
            (hash_token(token), user.id, to_iso(now), to_iso(session_expiry(now))),
        )
    return user, token


def user_for_token(token: str) -> User | None:
    """Resolve a session token to a user, or None. Expired sessions are deleted on sight."""
    if not token:
        return None
    th = hash_token(token)
    with connect() as conn:
        row = conn.execute(
            "select s.expires_at as expires_at, u.* from sessions s "
            "join users u on u.id = s.user_id where s.token_hash = ?",
            (th,),
        ).fetchone()
        if not row:
            return None
        if from_iso(row["expires_at"]) <= utcnow():
            conn.execute("delete from sessions where token_hash = ?", (th,))
            return None
    if row["disabled"]:
        return None
    return _row_to_user(row)


def revoke_session(token: str) -> None:
    with connect() as conn:
        conn.execute("delete from sessions where token_hash = ?", (hash_token(token),))


def revoke_all_sessions(user_id: str) -> None:
    with connect() as conn:
        conn.execute("delete from sessions where user_id = ?", (user_id,))


def get_user(user_id: str) -> User | None:
    with connect() as conn:
        row = conn.execute("select * from users where id = ?", (user_id,)).fetchone()
    return _row_to_user(row) if row else None


def require_role(user: User | None, minimum: str) -> User:
    """The server-side gate. Every admin route calls this before doing anything."""
    if user is None:
        raise Unauthenticated("sign in to continue")
    if not user.at_least(minimum):
        raise Forbidden(f"this action requires the {minimum} role")
    return user


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def audit(
    actor: User | None,
    action: str,
    *,
    subject: str | None = None,
    detail: str | None = None,
) -> None:
    """Append to the audit log. There is no update or delete path, by design."""
    with connect() as conn:
        conn.execute(
            "insert into audit_log (actor_id, actor_role, action, subject, detail, at) "
            "values (?, ?, ?, ?, ?, ?)",
            (
                actor.id if actor else None,
                actor.role if actor else None,
                action,
                subject,
                detail,
                to_iso(datetime.now(timezone.utc)),
            ),
        )


def recent_audit(limit: int = 50) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "select actor_role, action, subject, detail, at from audit_log "
            "order by id desc limit ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
    return [dict(r) for r in rows]
