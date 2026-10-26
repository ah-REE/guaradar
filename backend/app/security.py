"""Password hashing and session tokens.

DESIGN NOTES THAT MATTER
  * **PBKDF2-HMAC-SHA256, 600,000 iterations.** Chosen because it is in the standard library
    (`hashlib.pbkdf2_hmac`), so adding real password hashing costs no new dependency — the brief
    says to avoid unnecessary ones. The iteration count follows OWASP's current guidance for
    PBKDF2-SHA256. bcrypt/argon2 would be preferable but would add a dependency.
  * **Sessions are opaque random tokens, stored only as SHA-256 hashes.** The database never
    holds a usable token, so a dump of the file does not yield live sessions. Hashing is fast
    on purpose: the token is 256 bits of `secrets.token_urlsafe`, not a low-entropy password, so
    a slow KDF would add latency without adding security.
  * **Constant-time comparison** on both the password hash and any token lookup, via
    `hmac.compare_digest`, so a wrong password cannot be distinguished from a right one by timing.
  * **No JWT for app sessions.** A JWT would be stateless, which sounds attractive, but it cannot
    be revoked — and "withdraw consent / sign out everywhere / disable an account" are requirements
    here. Server-side sessions can be deleted; that is the point.

WHAT IS DELIBERATELY NOT HERE
  * No password-reset flow (needs email delivery, which does not exist).
  * No MFA. Not claimed anywhere in the UI.
  * No "remember me" beyond the fixed session TTL.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

PBKDF2_ITERATIONS = 600_000
PBKDF2_ALGORITHM = "sha256"
SALT_BYTES = 16
SESSION_BYTES = 32
SESSION_TTL = timedelta(hours=12)

# Stored form: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
# Self-describing so an iteration-count change can verify old hashes instead of invalidating them.
_PREFIX = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    """Return a self-describing hash string. Never store the password itself."""
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM, password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"{_PREFIX}${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification. Returns False on any malformed stored value."""
    try:
        prefix, iterations_s, salt_hex, hash_hex = stored.split("$")
        if prefix != _PREFIX:
            return False
        iterations = int(iterations_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False

    candidate = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM, password.encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(candidate, expected)


def new_session_token() -> str:
    """256 bits of entropy, URL-safe."""
    return secrets.token_urlsafe(SESSION_BYTES)


def hash_token(token: str) -> str:
    """What goes in the database. Fast hash is correct here — the token is already random."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry(now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    return base + SESSION_TTL


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def from_iso(text: str) -> datetime:
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
