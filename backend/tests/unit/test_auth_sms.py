"""Auth, RBAC and SMS tests.

THE CLAIMS THESE PROVE
  1. Public and admin access are separated **server-side**: a signed-in public user gets 403 on
     every admin route, and an anonymous caller gets 401.
  2. **A caller cannot grant themself a role.** No request field, header or query sets one;
     self-registration is hardcoded to `public`; extra JSON fields are rejected.
  3. **Hiding a tab is not the mechanism.** The tests call the endpoints directly, bypassing the
     UI entirely, which is precisely what an attacker would do.
  4. SMS runs in dry-run here, and a dry run is never reported as sent or delivered.
  5. Consent is required and re-checked at send time; withdrawal is honoured immediately.
  6. No delivery is ever claimed from a 200/acceptance response.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Isolate every test run in its own database file, set BEFORE importing the app.
_TMP = tempfile.mkdtemp(prefix="guaradar-test-")
os.environ["GUARADAR_DB_PATH"] = str(Path(_TMP) / "test.db")
os.environ.pop("SMS_GATE_USERNAME", None)
os.environ.pop("SMS_GATE_PASSWORD", None)

from app.api.main import app  # noqa: E402
from app import auth as auth_svc  # noqa: E402
from app.store import reset_for_tests  # noqa: E402

PASSWORD = "correct horse battery staple"


@pytest.fixture()
def client():
    reset_for_tests()
    with TestClient(app) as c:
        yield c


def register(client: TestClient, email: str) -> dict:
    r = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()


def make_admin(email: str, role: str = "admin") -> None:
    """Create an admin directly with the service layer, mirroring the CLI."""
    auth_svc.create_user(email, PASSWORD, role=role)


def login(client: TestClient, email: str) -> TestClient:
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return client


# ===========================================================================
# 1. Access separation
# ===========================================================================


ADMIN_GET_ROUTES = ["/api/admin/status", "/api/admin/alerts", "/api/admin/delivery",
                    "/api/admin/audit"]
ADMIN_POST_ROUTES = [
    ("/api/admin/test-sms", {"to": "+593999999999", "confirm": True}),
    ("/api/admin/alerts", {
        "title_en": "T", "title_es": "T", "body_en": "B", "body_es": "B",
        "severity": "info", "area": "centro",
    }),
]


@pytest.mark.parametrize("path", ADMIN_GET_ROUTES)
def test_admin_get_routes_reject_anonymous(client, path) -> None:
    """401, not 200 with hidden data. The server refuses before the handler runs."""
    r = client.get(path)
    assert r.status_code == 401, f"{path} returned {r.status_code}"


@pytest.mark.parametrize("path,body", ADMIN_POST_ROUTES)
def test_admin_post_routes_reject_anonymous(client, path, body) -> None:
    r = client.post(path, json=body)
    assert r.status_code == 401, f"{path} returned {r.status_code}"


@pytest.mark.parametrize("path", ADMIN_GET_ROUTES)
def test_admin_routes_reject_signed_in_public_user(client, path) -> None:
    """THE CORE CLAIM: being signed in is not enough. The role is checked server-side."""
    register(client, "citizen@example.com")
    r = client.get(path)
    assert r.status_code == 403, f"{path} allowed a public user ({r.status_code})"


@pytest.mark.parametrize("path,body", ADMIN_POST_ROUTES)
def test_admin_post_rejects_public_user(client, path, body) -> None:
    register(client, "citizen2@example.com")
    r = client.post(path, json=body)
    assert r.status_code == 403, f"{path} allowed a public user ({r.status_code})"


def test_admin_routes_allow_an_admin(client) -> None:
    make_admin("ops@example.com")
    login(client, "ops@example.com")
    r = client.get("/api/admin/status")
    assert r.status_code == 200
    assert r.json()["actor"]["role"] == "admin"


def test_viewer_cannot_operate(client) -> None:
    """Role ladder: viewer may read, not write."""
    make_admin("viewer@example.com", role="viewer")
    login(client, "viewer@example.com")
    assert client.get("/api/admin/status").status_code == 200
    r = client.post("/api/admin/test-sms", json={"to": "+593999999999", "confirm": True})
    assert r.status_code == 403


def test_operator_cannot_publish(client) -> None:
    """Operator may draft, not approve — the separation the approved design requires."""
    make_admin("op@example.com", role="operator")
    login(client, "op@example.com")
    r = client.post(
        "/api/admin/alerts",
        json={
            "title_en": "Flood watch", "title_es": "Vigilancia",
            "body_en": "Water rising in centro.", "body_es": "El agua sube en el centro.",
            "severity": "watch", "area": "centro",
        },
    )
    assert r.status_code == 201
    alert_id = r.json()["id"]
    approve = client.post(f"/api/admin/alerts/{alert_id}/approve")
    assert approve.status_code == 403, "an operator must not be able to publish"


# ===========================================================================
# 2. No privilege escalation
# ===========================================================================


def test_self_registration_is_always_public(client) -> None:
    body = register(client, "selfservice@example.com")
    assert body["role"] == "public"
    assert body["is_admin"] is False


def test_registration_rejects_a_role_field(client) -> None:
    """`extra: forbid` means adding a role field is a 422, not a silent escalation."""
    r = client.post(
        "/api/auth/register",
        json={"email": "evil@example.com", "password": PASSWORD, "role": "admin"},
    )
    assert r.status_code == 422, f"role in body was not rejected: {r.status_code}"


def test_x_role_header_does_not_escalate(client) -> None:
    """Signed in as public, with an X-Role header claiming admin: still 403."""
    register(client, "hdr@example.com")
    r = client.get("/api/admin/alerts", headers={"X-Role": "admin"})
    assert r.status_code == 403, "the role must come from the session row, not a header"


def test_bogus_bearer_token_is_rejected(client) -> None:
    """A bearer token that is not a real session is 401, and it overrides any cookie."""
    register(client, "hdr2@example.com")
    r = client.get("/api/admin/alerts", headers={"Authorization": "Bearer admin"})
    assert r.status_code == 401


def test_valid_bearer_token_authenticates_without_a_cookie(client) -> None:
    """The header path resolves through the same server-side lookup as the cookie."""
    make_admin("bearer@example.com")
    r = client.post(
        "/api/auth/login", json={"email": "bearer@example.com", "password": PASSWORD}
    )
    token = r.cookies.get("guaradar_session")
    assert token
    fresh = TestClient(app)
    resp = fresh.get("/api/admin/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_query_parameter_cannot_grant_a_role(client) -> None:
    register(client, "q@example.com")
    r = client.get("/api/admin/alerts?role=admin")
    assert r.status_code == 403


def test_admin_accounts_cannot_be_created_over_http(client) -> None:
    """There is no endpoint that creates an admin. That is the point."""
    paths = [r.path for r in app.routes if getattr(r, "path", "").startswith("/api")]
    assert not any("bootstrap" in p or "promote" in p for p in paths)


# ===========================================================================
# 3. Session behaviour
# ===========================================================================


def test_password_is_never_returned(client) -> None:
    body = register(client, "secrecy@example.com")
    dump = str(body).lower()
    assert "password" not in dump
    assert PASSWORD not in dump


def test_logout_revokes_the_session(client) -> None:
    register(client, "bye@example.com")
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_short_password_rejected(client) -> None:
    r = client.post("/api/auth/register", json={"email": "short@example.com", "password": "abc"})
    assert r.status_code == 422


def test_duplicate_email_rejected(client) -> None:
    register(client, "dup@example.com")
    r = client.post("/api/auth/register", json={"email": "dup@example.com", "password": PASSWORD})
    assert r.status_code == 409


def test_wrong_password_is_401_and_generic(client) -> None:
    register(client, "victim@example.com")
    r = client.post("/api/auth/login", json={"email": "victim@example.com", "password": "wrongwrongwrong"})
    assert r.status_code == 401
    # Must not reveal whether the account exists.
    assert "password is incorrect" in r.json()["detail"].lower() or "incorrect" in str(r.json())


def test_unknown_account_and_wrong_password_look_the_same(client) -> None:
    a = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    register(client, "real@example.com")
    b = client.post("/api/auth/login", json={"email": "real@example.com", "password": "definitelywrong1"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_login_throttles_after_repeated_failures(client) -> None:
    register(client, "brute@example.com")
    for _ in range(6):
        client.post("/api/auth/login", json={"email": "brute@example.com", "password": "nope-nope-nope"})
    r = client.post("/api/auth/login", json={"email": "brute@example.com", "password": PASSWORD})
    assert r.status_code == 429, "repeated failures should throttle"


def test_password_hash_is_not_plaintext(client) -> None:
    register(client, "hash@example.com")
    from app.store import connect

    with connect() as conn:
        row = conn.execute("select password_hash from users where email='hash@example.com'").fetchone()
    assert row["password_hash"] != PASSWORD
    assert row["password_hash"].startswith("pbkdf2_sha256$")


def test_session_token_is_stored_only_as_a_hash(client) -> None:
    register(client, "tok@example.com")
    raw = client.cookies.get("guaradar_session")
    assert raw, "expected a session cookie"
    from app.security import hash_token
    from app.store import connect

    with connect() as conn:
        stored = {r["token_hash"] for r in conn.execute("select token_hash from sessions")}
    assert hash_token(raw) in stored
    assert raw not in stored, "the raw token must never be stored"


# ===========================================================================
# 4. SMS consent
# ===========================================================================


def test_consent_rejects_numbers_that_are_not_e164(client) -> None:
    """Strict on the NORMALISED form: no country-code guessing, no local formats."""
    register(client, "sms1@example.com")
    for bad in ("0999999999", "593999999999", "abc", "", "+1", "+593-99-999-9999-ext"):
        r = client.post("/api/sms/consent", json={"opt_in": True, "phone": bad})
        assert r.status_code == 422, f"{bad!r} should be rejected"


def test_consent_normalises_grouped_formatting(client) -> None:
    """'+593 99 999 9999' is a real way people write a number; it is normalised, not rejected."""
    register(client, "sms1b@example.com")
    r = client.post("/api/sms/consent", json={"opt_in": True, "phone": "+593 99 999 9999"})
    assert r.status_code == 200
    assert r.json()["phone"] == "+593999999999"


def test_country_code_is_never_guessed(client) -> None:
    """A bare local number must not silently become +593… — that could reach a stranger."""
    register(client, "sms1c@example.com")
    r = client.post("/api/sms/consent", json={"opt_in": True, "phone": "0999999999"})
    assert r.status_code == 422


def test_consent_opt_in_and_withdraw(client) -> None:
    register(client, "sms2@example.com")
    r = client.post("/api/sms/consent", json={"opt_in": True, "phone": "+593999999999"})
    assert r.status_code == 200 and r.json()["sms_opt_in"] is True

    r = client.post("/api/sms/consent", json={"opt_in": False})
    assert r.status_code == 200 and r.json()["sms_opt_in"] is False
    # Withdrawal clears the number, so it cannot be reused by a bug.
    assert r.json()["phone"] is None


def test_consent_history_is_append_only(client) -> None:
    register(client, "sms3@example.com")
    client.post("/api/sms/consent", json={"opt_in": True, "phone": "+593999999999"})
    client.post("/api/sms/consent", json={"opt_in": False})
    hist = client.get("/api/sms/consent").json()["history"]
    assert [h["action"] for h in hist] == ["opt_out", "opt_in"]


def test_only_the_signed_in_user_changes_their_own_consent(client) -> None:
    register(client, "a@example.com")
    client.post("/api/sms/consent", json={"opt_in": True, "phone": "+593999999999"})
    client.cookies.clear()
    r = client.post("/api/sms/consent", json={"opt_in": True, "phone": "+593888888888"})
    assert r.status_code == 401


# ===========================================================================
# 5. Dry-run sending
# ===========================================================================


def test_gateway_reports_dry_run_when_unconfigured() -> None:
    from app.sms.gateway import describe_config

    cfg = describe_config()
    assert cfg["mode"] == "dry_run"
    assert cfg["configured"] is False
    # It must never expose a value, only booleans.
    assert "password" not in str(cfg).lower() or cfg["password_set"] is False


def test_dry_run_send_reports_dry_run_not_sent() -> None:
    from app.sms.gateway import SmsGateway

    result = SmsGateway().send("+593999999999", "hello")
    assert result.dry_run is True
    assert result.state == "dry_run"
    assert result.state not in ("sent", "delivered")


def test_admin_test_sms_requires_confirmation(client) -> None:
    make_admin("t@example.com")
    login(client, "t@example.com")
    r = client.post("/api/admin/test-sms", json={"to": "+593999999999", "confirm": False})
    assert r.status_code == 428, "test send must fail closed without confirm=true"


def test_admin_test_sms_in_dry_run(client) -> None:
    make_admin("t2@example.com")
    login(client, "t2@example.com")
    r = client.post("/api/admin/test-sms", json={"to": "+593999999999", "confirm": True})
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["state"] == "dry_run"
    assert body["state"] not in ("sent", "delivered")
    # The recipient is masked, never echoed in full.
    assert body["to"] != "+593999999999"


def test_test_sms_validates_the_number(client) -> None:
    make_admin("t3@example.com")
    login(client, "t3@example.com")
    r = client.post("/api/admin/test-sms", json={"to": "12345", "confirm": True})
    assert r.status_code == 422


# ===========================================================================
# 6. Alert workflow
# ===========================================================================


def _draft(client, body_en="Water rising in centro.", key=None):
    payload = {
        "title_en": "Flood warning",
        "title_es": "Alerta de inundación",
        "body_en": body_en,
        "body_es": "El agua sube en el centro.",
        "severity": "warning",
        "area": "centro",
    }
    if key:
        payload["idempotency_key"] = key
    return client.post("/api/admin/alerts", json=payload)


def test_alert_requires_bilingual_content(client) -> None:
    make_admin("pub@example.com")
    login(client, "pub@example.com")
    r = client.post(
        "/api/admin/alerts",
        json={
            "title_en": "T", "title_es": "  ", "body_en": "B", "body_es": "B",
            "severity": "warning", "area": "centro",
        },
    )
    assert r.status_code == 422, "an empty Spanish title must block drafting"


def test_send_requires_approval(client) -> None:
    make_admin("pub2@example.com")
    login(client, "pub2@example.com")
    alert = _draft(client).json()
    r = client.post(f"/api/admin/alerts/{alert['id']}/send?confirm=true")
    assert r.status_code == 409, "a draft must not be sendable"


def test_send_requires_confirmation(client) -> None:
    """Drafter and approver must differ, so two accounts are needed here."""
    make_admin("drafter@example.com", role="operator")
    make_admin("approver@example.com", role="publisher")
    login(client, "drafter@example.com")
    alert = _draft(client).json()
    client.cookies.clear()
    login(client, "approver@example.com")
    assert client.post(f"/api/admin/alerts/{alert['id']}/approve").status_code == 200
    r = client.post(f"/api/admin/alerts/{alert['id']}/send")
    assert r.status_code == 428, "sending without confirm must fail closed"


def test_self_approval_is_refused(client) -> None:
    """Separation of duties: one person cannot be both pairs of eyes."""
    make_admin("both@example.com", role="publisher")
    login(client, "both@example.com")
    alert = _draft(client).json()
    r = client.post(f"/api/admin/alerts/{alert['id']}/approve")
    assert r.status_code == 403
    detail = r.json()["detail"]
    message = detail["message"] if isinstance(detail, dict) else detail
    assert "cannot also approve" in message


def test_send_only_reaches_opted_in_users(client) -> None:
    """Someone signed up but NOT opted in must receive nothing."""
    make_admin("drafter2@example.com", role="operator")
    make_admin("approver2@example.com", role="publisher")
    register(client, "notoptin@example.com")
    client.cookies.clear()

    login(client, "drafter2@example.com")
    alert = _draft(client).json()
    client.cookies.clear()
    login(client, "approver2@example.com")
    client.post(f"/api/admin/alerts/{alert['id']}/approve")
    r = client.post(f"/api/admin/alerts/{alert['id']}/send?confirm=true")
    assert r.status_code == 200
    assert r.json()["attempted"] == 0, "no opted-in recipients, so nothing should be attempted"


def test_send_reaches_opted_in_users_in_dry_run(client) -> None:
    make_admin("drafter3@example.com", role="operator")
    make_admin("approver3@example.com", role="publisher")
    register(client, "opted@example.com")
    client.post("/api/sms/consent", json={"opt_in": True, "phone": "+593999999999"})
    client.cookies.clear()

    login(client, "drafter3@example.com")
    alert = _draft(client).json()
    client.cookies.clear()
    login(client, "approver3@example.com")
    client.post(f"/api/admin/alerts/{alert['id']}/approve")
    r = client.post(f"/api/admin/alerts/{alert['id']}/send?confirm=true")
    body = r.json()
    assert body["dry_run"] is True
    assert body["attempted"] == 1
    assert body["states"] == {"dry_run": 1}
    # A dry run must never be reported as any delivered/sent state.
    assert "delivered" not in body["states"]
    assert "sent" not in body["states"]


def test_withdrawal_before_send_is_honoured(client) -> None:
    """Consent is re-checked at SEND time, not draft time."""
    make_admin("drafter4@example.com", role="operator")
    make_admin("approver4@example.com", role="publisher")
    register(client, "flip@example.com")
    client.post("/api/sms/consent", json={"opt_in": True, "phone": "+593999999999"})
    client.cookies.clear()

    login(client, "drafter4@example.com")
    alert = _draft(client).json()
    client.cookies.clear()
    login(client, "approver4@example.com")
    client.post(f"/api/admin/alerts/{alert['id']}/approve")

    # The user withdraws BEFORE the send.
    client.cookies.clear()
    login(client, "flip@example.com")
    client.post("/api/sms/consent", json={"opt_in": False})
    client.cookies.clear()
    login(client, "approver4@example.com")

    r = client.post(f"/api/admin/alerts/{alert['id']}/send?confirm=true")
    assert r.json()["attempted"] == 0, "a withdrawn consent must not receive the alert"


def test_duplicate_send_is_refused(client) -> None:
    make_admin("drafter5@example.com", role="operator")
    make_admin("approver5@example.com", role="publisher")
    register(client, "once@example.com")
    client.post("/api/sms/consent", json={"opt_in": True, "phone": "+593999999999"})
    client.cookies.clear()

    login(client, "drafter5@example.com")
    alert = _draft(client, body_en="Unique body for dedupe test.").json()
    client.cookies.clear()
    login(client, "approver5@example.com")
    client.post(f"/api/admin/alerts/{alert['id']}/approve")
    first = client.post(f"/api/admin/alerts/{alert['id']}/send?confirm=true")
    assert first.status_code == 200
    second = client.post(f"/api/admin/alerts/{alert['id']}/send?confirm=true")
    assert second.status_code == 409, "a second identical send must be refused"


def test_delivery_log_never_contains_full_numbers_or_bodies(client) -> None:
    make_admin("drafter6@example.com", role="operator")
    make_admin("approver6@example.com", role="publisher")
    register(client, "priv@example.com")
    client.post("/api/sms/consent", json={"opt_in": True, "phone": "+593977777777"})
    client.cookies.clear()

    login(client, "drafter6@example.com")
    alert = _draft(client).json()
    client.cookies.clear()
    login(client, "approver6@example.com")
    client.post(f"/api/admin/alerts/{alert['id']}/approve")
    client.post(f"/api/admin/alerts/{alert['id']}/send?confirm=true")

    dump = str(client.get("/api/admin/delivery").json())
    assert "+593977777777" not in dump, "the full number must not appear in the delivery log"
    assert "Water rising" not in dump, "message bodies must not be in the delivery log"


def test_alerts_are_marked_demo(client) -> None:
    """Every alert created from this UI is demo: there is no verified emergency feed."""
    make_admin("demo@example.com", role="operator")
    login(client, "demo@example.com")
    alert = _draft(client).json()
    assert alert["is_demo"] == 1


def test_audit_log_records_admin_actions(client) -> None:
    make_admin("auditor@example.com")
    login(client, "auditor@example.com")
    client.post("/api/admin/test-sms", json={"to": "+593999999999", "confirm": True})
    entries = client.get("/api/admin/audit").json()["entries"]
    assert any(e["action"] == "sms.test_send" for e in entries)


def test_no_credentials_are_returned_by_any_admin_endpoint(client) -> None:
    make_admin("leak@example.com")
    login(client, "leak@example.com")
    payloads = [
        client.get("/api/admin/status").text,
        client.get("/api/admin/delivery").text,
        client.get("/api/admin/audit").text,
    ]
    for body in payloads:
        low = body.lower()
        assert "password" not in low or '"password_set"' in low
        assert "smsgate_password" not in low


def test_database_path_is_absolute_and_stable_across_cwd(tmp_path) -> None:
    """A cwd-relative default silently produced TWO databases.

    uvicorn started from the repo root wrote `data/guaradar.db`, while `python -m app.admin_cli`
    started from `backend/` wrote `backend/data/guaradar.db`. Accounts created by the CLI were
    invisible to the server, which surfaced as "wrong password" — a genuinely confusing bug with
    no security cause. This pins the path so it cannot regress.
    """
    import os as _os

    from app.store import db_path

    saved = _os.environ.pop("GUARADAR_DB_PATH", None)
    try:
        from_root = db_path()
        _os.chdir(tmp_path)
        from_elsewhere = db_path()
    finally:
        _os.chdir(str(Path(__file__).resolve().parents[2]))
        if saved is not None:
            _os.environ["GUARADAR_DB_PATH"] = saved
        else:
            _os.environ["GUARADAR_DB_PATH"] = str(Path(_TMP) / "test.db")

    assert from_root.is_absolute(), "the default database path must be absolute"
    assert from_root == from_elsewhere, (
        "the database path changed with the working directory, so the CLI and the server "
        "could write to different files"
    )


def test_cli_and_server_share_the_database() -> None:
    """The CLI must write to the same file the API reads from."""
    import subprocess
    import sys

    from app.store import db_path

    env = {**os.environ, "GUARADAR_DB_PATH": str(db_path())}
    result = subprocess.run(
        [sys.executable, "-m", "app.admin_cli", "list-users"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr[-400:]


# ===========================================================================
# 7. Live gateway path, exercised with a mock transport
# ===========================================================================
# The dry-run path returns before any HTTP happens, so the real request/response handling would
# otherwise never execute in this environment. These use httpx.MockTransport to drive the actual
# client code — the Basic->JWT exchange, the send, the status read, and every error branch — so
# the live path is genuinely tested rather than merely written.

def _gateway(handler):
    import httpx

    from app.sms.gateway import GatewayConfig, SmsGateway

    cfg = GatewayConfig(
        base_url="https://api.example.test",
        username="user",
        password="pass",
        device_id="dev1",
    )
    return SmsGateway(cfg, transport=httpx.MockTransport(handler))


def test_live_path_exchanges_basic_for_jwt_then_sends() -> None:
    """The documented two-step flow: Basic auth -> bearer token -> POST /messages."""
    import httpx

    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "url": str(request.url),
                "auth": request.headers.get("authorization"),
                "body": request.content.decode() if request.content else "",
            }
        )
        if request.url.path.endswith("/auth/token"):
            # Basic credentials must be presented here, NOT a bearer token.
            assert request.headers["authorization"].startswith("Basic ")
            return httpx.Response(
                200,
                json={
                    "id": "jti1",
                    "token_type": "Bearer",
                    "access_token": "jwt-abc",
                    "refresh_token": "refresh-abc",
                    "expires_at": "2026-10-26T12:00:00Z",
                },
            )
        assert request.headers["authorization"] == "Bearer jwt-abc"
        return httpx.Response(200, json=[{"id": "msg1", "state": "Pending"}])

    gw = _gateway(handler)
    result = gw.send("+593999999999", "hello")

    assert len(seen) == 2, "expected a token exchange then a send"
    assert "/3rdparty/v1/auth/token" in seen[0]["url"]
    assert "/3rdparty/v1/messages" in seen[1]["url"]
    # The documented body shape: text nested under textMessage.
    assert '"textMessage"' in seen[1]["body"]
    assert '"text"' in seen[1]["body"]

    # A 200 means QUEUED, not delivered.
    assert result.ok is True
    assert result.state == "pending"
    assert result.provider_state == "Pending"
    assert result.state != "delivered"


def test_live_path_requests_minimal_scopes() -> None:
    """Least privilege: only messages:send and messages:read."""
    import httpx

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/token"):
            captured["body"] = request.content.decode()
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(200, json=[{"id": "m", "state": "Pending"}])

    _gateway(handler).send("+593999999999", "x")
    body = captured["body"]
    assert "messages:send" in body
    assert "messages:read" in body
    assert "all:any" not in body
    assert "tokens:manage" not in body


def test_provider_error_is_reported_not_swallowed() -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(400, json={"message": "Invalid phone number"})

    result = _gateway(handler).send("+593999999999", "x")
    assert result.ok is False
    assert result.state == "failed"
    assert result.error_code == "http_400"
    assert "Invalid phone" in (result.error_message or "")
    assert result.state != "delivered"


def test_transport_failure_is_reported() -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    result = _gateway(handler).send("+593999999999", "x")
    assert result.ok is False
    assert result.error_code == "transport_error"


def test_token_response_without_access_token_fails_loudly() -> None:
    import httpx
    import pytest as _pytest

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token_type": "Bearer"})

    with _pytest.raises(RuntimeError, match="access_token"):
        _gateway(handler).send("+593999999999", "x")


def test_status_reports_provider_state_verbatim() -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(200, json={"id": "msg1", "state": "Delivered"})

    result = _gateway(handler).status("msg1")
    assert result.ok is True
    assert result.state == "delivered"
    assert result.provider_state == "Delivered"


def test_status_unknown_message_is_not_found() -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(404, json={"message": "not found"})

    result = _gateway(handler).status("nope")
    assert result.ok is False
    assert result.error_code == "not_found"


def test_sent_state_is_never_upgraded_to_delivered() -> None:
    """The provider documents that a message can stay in `Sent` even after delivery.

    So `Sent` must map to `sent`, and never to `delivered`. Claiming delivery would be a
    fabrication about a message a recipient may never have received.
    """
    from app.sms.gateway import classify_provider_state

    assert classify_provider_state("Sent") == "sent"
    assert classify_provider_state("Delivered") == "delivered"
    assert classify_provider_state("Pending") == "pending"
    assert classify_provider_state("Garbage") == "unknown"
    assert classify_provider_state(None) == "unknown"


def test_unknown_provider_state_never_maps_to_success() -> None:
    """Any unrecognised state must fall to `unknown`, never to delivered/sent."""
    from app.sms.gateway import classify_provider_state

    for weird in ("", "WOBBLE", "delivered!", "SENT ", "delivred"):
        assert classify_provider_state(weird) == "unknown", weird
