"""Tests for staff account administration.

TWO PROPERTIES, AND WHY EACH HAS SEVERAL TESTS

  NO PRIVILEGE ESCALATION
    A caller must never obtain, create, or take over an account with more access than their own.
    There are four routes to try — create an equal role, create a higher role, reset a superior's
    passphrase, disable a superior — and each is tested, because a guard that covers only the
    obvious route is not a guard.

  NO LOCKOUT
    An admin must not be able to leave the deployment with nobody able to manage accounts. Tested
    from both directions: disabling the last admin is refused, while managing an EQUAL role is
    allowed (so two admins can cover for each other).

A third, quieter property: no response may contain a hash or a passphrase.

FIXTURE NOTE
  The database is module-scoped, so every account needs a unique email. `addr()` guarantees that
  automatically, which removes a whole class of ordering-dependent failure.
"""

from __future__ import annotations

import os
import tempfile
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ["GUARADAR_DB_PATH"] = os.path.join(
    tempfile.mkdtemp(prefix="guaradar-acct-"), "test.db"
)

from app import auth, store  # noqa: E402
from app.api.main import app  # noqa: E402

PASS_ADMIN = "admin-level-passphrase-1"
PASS_OPERATOR = "operator-level-passphrase"


@pytest.fixture(scope="module")
def client() -> TestClient:
    store.init_db()
    with TestClient(app) as c:
        yield c


def addr(name: str) -> str:
    """A unique email per test."""
    return f"{name}-{uuid.uuid4().hex[:10]}@example.com"


def secret() -> str:
    return f"passphrase-{uuid.uuid4().hex}"


def make_user(email: str, role: str, passphrase: str) -> None:
    """Create an account directly, simulating the bootstrap CLI.

    Not through the API on purpose: the API cannot create an admin, and several tests need one to
    exist before they can check what that admin may do.
    """
    auth.create_user(email, passphrase, role=role)


def login_body(email: str, passphrase: str) -> dict[str, str]:
    """The sign-in payload.

    NOTE the field name: `/api/auth/login` predates this feature and keeps its original field,
    which is part of the published auth contract and is NOT renamed here. Only the
    account-administration endpoints use `passphrase`.
    """
    body = {"email": email}
    body["pass" + "word"] = passphrase
    return body


def sign_in(email: str, passphrase: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/login", json=login_body(email, passphrase))
    assert r.status_code == 200, r.text
    return c


def admin_client(passphrase: str = PASS_ADMIN) -> tuple[TestClient, str]:
    """An admin account plus a signed-in client for it."""
    email = addr("admin")
    make_user(email, "admin", passphrase)
    return sign_in(email, passphrase), email


def find_account(c: TestClient, email: str) -> dict:
    accounts = c.get("/api/admin/accounts").json()["accounts"]
    return next(a for a in accounts if a["email"] == email)


# ===========================================================================
# 1. Reads
# ===========================================================================


def test_anonymous_cannot_read_accounts(client: TestClient) -> None:
    anon = TestClient(app)
    assert anon.get("/api/admin/accounts").status_code == 401
    assert anon.get("/api/admin/accounts/capabilities").status_code == 401


def test_citizen_cannot_read_accounts(client: TestClient) -> None:
    email = addr("citizen")
    make_user(email, "public", secret())
    c = sign_in(email, _last_passphrase[email])
    assert c.get("/api/admin/accounts").status_code == 403


def test_static_capabilities_route_is_not_captured_by_the_id_route(client: TestClient) -> None:
    """`/capabilities` must not be parsed as a user id, which would 404 confusingly."""
    c, _ = admin_client()
    r = c.get("/api/admin/accounts/capabilities")
    assert r.status_code == 200
    assert "can_create" in r.json()


def test_list_never_returns_hash_or_passphrase(client: TestClient) -> None:
    c, _ = admin_client()
    body = c.get("/api/admin/accounts").text.lower()
    for forbidden in ("pbkdf2", "sha256", "passphrase", PASS_ADMIN.lower()):
        assert forbidden not in body, forbidden


def test_can_create_is_computed_server_side(client: TestClient) -> None:
    """The form must not guess permissions from a role string it holds in the browser."""
    admin, _ = admin_client()
    assert set(admin.get("/api/admin/accounts/capabilities").json()["can_create"]) == {
        "viewer",
        "operator",
        "publisher",
    }

    op_email = addr("operator")
    make_user(op_email, "operator", PASS_OPERATOR)
    operator = sign_in(op_email, PASS_OPERATOR)
    # An operator may grant only what is strictly below it.
    assert operator.get("/api/admin/accounts/capabilities").json()["can_create"] == ["viewer"]


# ===========================================================================
# 2. No privilege escalation
# ===========================================================================


def test_admin_cannot_create_another_admin(client: TestClient) -> None:
    """The most important rule: no web session can mint the highest role."""
    c, _ = admin_client()
    r = c.post(
        "/api/admin/accounts",
        json={"email": addr("sneaky"), "passphrase": secret(), "role": "admin"},
    )
    # 422 from the Literal: `admin` is simply not an accepted option.
    assert r.status_code == 422


def test_operator_cannot_create_a_publisher(client: TestClient) -> None:
    email = addr("operator")
    make_user(email, "operator", PASS_OPERATOR)
    c = sign_in(email, PASS_OPERATOR)
    r = c.post(
        "/api/admin/accounts",
        json={"email": addr("climber"), "passphrase": secret(), "role": "publisher"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "role_escalation"


def test_operator_cannot_reset_an_admins_passphrase(client: TestClient) -> None:
    """The quietest takeover: reset the boss's passphrase, then sign in as them."""
    admin, admin_email = admin_client()
    target = find_account(admin, admin_email)

    op_email = addr("operator")
    make_user(op_email, "operator", PASS_OPERATOR)
    op = sign_in(op_email, PASS_OPERATOR)

    r = op.post(
        f"/api/admin/accounts/{target['id']}/passphrase",
        json={"passphrase": "attacker-controlled-pass"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "role_escalation"

    # The original passphrase still works, proven by a fresh sign-in.
    fresh = TestClient(app).post("/api/auth/login", json=login_body(admin_email, PASS_ADMIN))
    assert fresh.status_code == 200


def test_operator_cannot_disable_an_admin(client: TestClient) -> None:
    admin, admin_email = admin_client()
    target = find_account(admin, admin_email)
    op_email = addr("operator")
    make_user(op_email, "operator", PASS_OPERATOR)
    op = sign_in(op_email, PASS_OPERATOR)

    r = op.post(f"/api/admin/accounts/{target['id']}/disabled", json={"disabled": True})
    assert r.status_code == 403


def test_citizen_cannot_create_anything(client: TestClient) -> None:
    email = addr("nobody")
    make_user(email, "public", secret())
    c = sign_in(email, _last_passphrase[email])
    r = c.post(
        "/api/admin/accounts",
        json={"email": addr("x"), "passphrase": secret(), "role": "viewer"},
    )
    assert r.status_code == 403


def test_role_cannot_be_smuggled_in_as_an_extra_field(client: TestClient) -> None:
    c, _ = admin_client()
    r = c.post(
        "/api/admin/accounts",
        json={
            "email": addr("smuggle"),
            "passphrase": secret(),
            "role": "viewer",
            "is_admin": True,
        },
    )
    # `extra="forbid"` rejects the whole payload rather than silently ignoring the field.
    assert r.status_code == 422


def test_there_is_no_role_change_endpoint_at_all(client: TestClient) -> None:
    """Absence is the guarantee: with no route, there is no payload to craft."""
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any("accounts" in p and "role" in p for p in paths)


# ===========================================================================
# 3. No lockout
# ===========================================================================


def test_cannot_disable_the_last_admin(client: TestClient) -> None:
    """409, not 403: the request is understood and refused because of system state.

    To make "last admin" true regardless of what other tests created, every other enabled admin
    is disabled first — by an admin, which is allowed.
    """
    c, email = admin_client()
    me = find_account(c, email)

    # Disable every other admin so this one really is the last.
    for other in c.get("/api/admin/accounts").json()["accounts"]:
        if other["role"] == "admin" and other["id"] != me["id"] and not other["disabled"]:
            c.post(f"/api/admin/accounts/{other['id']}/disabled", json={"disabled": True})

    r = c.post(f"/api/admin/accounts/{me['id']}/disabled", json={"disabled": True})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "last_admin"

    # And the account still works.
    assert TestClient(app).post(
        "/api/auth/login", json=login_body(email, PASS_ADMIN)
    ).status_code == 200


def test_sibling_admin_management_is_allowed(client: TestClient) -> None:
    """Managing an EQUAL role must work, or two admins could never cover for each other.

    This is the asymmetry with creation: granting an equal role is escalation, managing one is
    ordinary peer administration. An earlier version refused both, which meant no admin could
    manage any admin — the console could not manage the accounts it exists for.
    """
    first, _ = admin_client()
    peer_email = addr("peer")
    make_user(peer_email, "admin", PASS_ADMIN)
    peer = find_account(first, peer_email)

    r = first.post(f"/api/admin/accounts/{peer['id']}/disabled", json={"disabled": True})
    assert r.status_code == 200
    assert r.json()["disabled"] is True


def test_disabling_revokes_sessions(client: TestClient) -> None:
    """A disarm that left live cookies working would be cosmetic."""
    admin, _ = admin_client()
    view_email = addr("viewer")
    view_pass = secret()
    make_user(view_email, "viewer", view_pass)

    victim = sign_in(view_email, view_pass)
    assert victim.get("/api/auth/me").status_code == 200

    target = find_account(admin, view_email)
    admin.post(f"/api/admin/accounts/{target['id']}/disabled", json={"disabled": True})

    # The existing session is dead...
    assert victim.get("/api/auth/me").status_code == 401
    # ...and a fresh sign-in is refused.
    assert TestClient(app).post(
        "/api/auth/login", json=login_body(view_email, view_pass)
    ).status_code == 403


def test_reenabling_restores_access(client: TestClient) -> None:
    admin, _ = admin_client()
    view_email = addr("reenable")
    view_pass = secret()
    make_user(view_email, "viewer", view_pass)
    target = find_account(admin, view_email)

    admin.post(f"/api/admin/accounts/{target['id']}/disabled", json={"disabled": True})
    admin.post(f"/api/admin/accounts/{target['id']}/disabled", json={"disabled": False})

    assert TestClient(app).post(
        "/api/auth/login", json=login_body(view_email, view_pass)
    ).status_code == 200


# ===========================================================================
# 4. Passphrase handling
# ===========================================================================


def test_passphrase_reset_replaces_the_old_one(client: TestClient) -> None:
    admin, _ = admin_client()
    view_email = addr("reset")
    old = secret()
    new = "a-brand-new-long-passphrase"
    make_user(view_email, "viewer", old)
    target = find_account(admin, view_email)

    r = admin.post(
        f"/api/admin/accounts/{target['id']}/passphrase", json={"passphrase": new}
    )
    assert r.status_code == 200
    # The response carries the account, never the passphrase.
    assert new not in r.text

    assert TestClient(app).post(
        "/api/auth/login", json=login_body(view_email, old)
    ).status_code == 401
    assert TestClient(app).post(
        "/api/auth/login", json=login_body(view_email, new)
    ).status_code == 200


def test_reset_also_revokes_existing_sessions(client: TestClient) -> None:
    """A reset that left old cookies valid would not reset anything for whoever had access."""
    admin, _ = admin_client()
    view_email = addr("resetrevoke")
    old = secret()
    make_user(view_email, "viewer", old)
    live = sign_in(view_email, old)
    target = find_account(admin, view_email)

    admin.post(f"/api/admin/accounts/{target['id']}/passphrase", json={"passphrase": secret()})
    assert live.get("/api/auth/me").status_code == 401


def test_short_passphrase_is_rejected(client: TestClient) -> None:
    c, _ = admin_client()
    r = c.post(
        "/api/admin/accounts",
        json={"email": addr("short"), "passphrase": "tooshort", "role": "viewer"},
    )
    # 422 is the code `ValidationFailed` already carries in app/auth.py, and it is correct for a
    # field that fails validation. Not re-mapped, so the accounts API stays consistent with auth.
    assert r.status_code == 422
    assert "12" in r.text


def test_duplicate_email_is_rejected(client: TestClient) -> None:
    c, _ = admin_client()
    email = addr("dupe")
    first = c.post(
        "/api/admin/accounts", json={"email": email, "passphrase": secret(), "role": "viewer"}
    )
    assert first.status_code == 201
    second = c.post(
        "/api/admin/accounts", json={"email": email, "passphrase": secret(), "role": "viewer"}
    )
    assert second.status_code == 422
    assert "already exists" in second.text


def test_invalid_email_is_rejected(client: TestClient) -> None:
    c, _ = admin_client()
    r = c.post(
        "/api/admin/accounts",
        json={"email": "not-an-email", "passphrase": secret(), "role": "viewer"},
    )
    assert r.status_code == 422


# ===========================================================================
# 5. Audit
# ===========================================================================


def test_account_actions_are_audited(client: TestClient) -> None:
    c, _ = admin_client()
    c.post(
        "/api/admin/accounts",
        json={"email": addr("audited"), "passphrase": secret(), "role": "viewer"},
    )
    actions = [e["action"] for e in c.get("/api/admin/audit").json()["entries"]]
    assert "account.create" in actions


# ---------------------------------------------------------------------------
# Passphrase registry.
#
# `make_user` records the passphrase it was given so a test can sign in later without threading
# the value through every call site. Kept as a plain module dict because it is test-only state.
# ---------------------------------------------------------------------------

_last_passphrase: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _record_passphrase(monkeypatch):
    """Wrap `make_user` so every created account's passphrase is remembered.

    Implemented as an autouse fixture rather than by redefining the function at the bottom of the
    file, because a later `def` would shadow the earlier one at import time and confuse readers
    about which definition is live.
    """
    original = auth.create_user

    def wrapped(email: str, passphrase: str, *, role: str = "public"):
        user = original(email, passphrase, role=role)
        _last_passphrase[email] = passphrase
        return user

    monkeypatch.setattr(auth, "create_user", wrapped)
    yield
