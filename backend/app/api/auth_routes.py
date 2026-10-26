"""Auth, SMS and admin routers.

LAYERING
  These routes are registered on the same FastAPI app as the public read-only routes. That is
  fine because **authorisation is enforced per-route**, not by separation of apps: every admin
  handler calls `require_role` before touching data. Mounting a second app would not add any
  security, and it would duplicate the dependency wiring.

  Because they are mounted on the public app, the module also demonstrates that the previous
  "no mutation endpoint exists anywhere" invariant is now **intentionally** changed — with
  server-side authentication, which is what N-2 required. The M12 tests that asserted "no POST
  at all" have been updated to assert "no POST that lacks an auth dependency" instead, which is
  the stronger and now-correct claim.

IDENTITY RESOLUTION
  A token may arrive as `Authorization: Bearer <token>` or as the `guaradar_session` httpOnly
  cookie. The header exists so a test client and a future mobile client do not need cookie
  handling; the cookie is what the browser uses. Both resolve through the same server-side
  lookup, so there is one identity path and not two.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app import auth as auth_svc
from app.auth import AuthError, Forbidden, Unauthenticated, User
from app.sms import service as sms_svc
from app.sms.gateway import SmsGateway, describe_config
from app.sms.service import SmsError

SESSION_COOKIE = "guaradar_session"

# ---------------------------------------------------------------------------
# Cookie flags
# ---------------------------------------------------------------------------
#
# WHY THIS IS CONFIGURABLE
#   The flag was hardcoded to `secure=False`, which is correct for `http://localhost` and WRONG
#   for any HTTPS deployment: a browser refuses to store a non-Secure cookie on an https origin
#   in several configurations, and accepting one over plain HTTP invites session theft.
#
#   The default stays insecure ON PURPOSE, so local development over http keeps working with no
#   setup. A deployment sets GUARADAR_COOKIE_SECURE=1 and gets a Secure cookie; the value is
#   parsed strictly so a typo cannot silently leave production insecure.
#
#   SameSite stays `Lax`. That is what makes the cookie survive the Vercel -> Render proxy hop
#   (the browser only ever sees one origin) while still blocking the simple cross-site form POST.


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    # Fail loudly: a malformed flag must not quietly leave cookies insecure in production.
    raise RuntimeError(f"{name} must be one of 1/0/true/false/yes/no/on/off, got {raw!r}")


COOKIE_SECURE = _env_flag("GUARADAR_COOKIE_SECURE", default=False)


def set_session_cookie(response: Response, token: str) -> None:
    """Attach the session cookie with the deployment's flags.

    One helper so the two call sites cannot drift: a login that set a Secure cookie and a
    register that did not would be a confusing, intermittent bug.
    """
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
sms_router = APIRouter(prefix="/api/sms", tags=["sms"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Identity dependency
# ---------------------------------------------------------------------------


def current_user_optional(
    authorization: Annotated[str | None, Header()] = None,
    guaradar_session: Annotated[str | None, Cookie()] = None,
) -> User | None:
    """Resolve the caller from a bearer header or the session cookie. None when anonymous."""
    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif guaradar_session:
        token = guaradar_session
    if not token:
        return None
    return auth_svc.user_for_token(token)


def current_user(
    user: Annotated[User | None, Depends(current_user_optional)],
) -> User:
    """Require a signed-in user. This is the 401 gate."""
    if user is None:
        raise HTTPException(status_code=401, detail="sign in to continue")
    return user


def require_admin(minimum: str = "viewer"):
    """Factory: a dependency that enforces a minimum role SERVER-SIDE.

    Every admin route uses this. A hidden frontend tab is not a security control; this is.
    """

    def dependency(user: Annotated[User | None, Depends(current_user_optional)]) -> User:
        if user is None:
            raise HTTPException(status_code=401, detail="sign in to continue")
        if not user.at_least(minimum):
            raise HTTPException(
                status_code=403, detail=f"this action requires the {minimum} role"
            )
        return user

    return dependency


_admin_any = require_admin("viewer")
_admin_operator = require_admin("operator")
_admin_publisher = require_admin("publisher")


def _auth_http(exc: AuthError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _sms_http(exc: SmsError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RegisterIn(BaseModel):
    email: str
    password: str
    # NOTE: there is deliberately no `role` field. Self-registration cannot choose a role,
    # which is why an unknown field here would be rejected by pydantic's default and an
    # attacker cannot escalate by adding one.
    model_config = {"extra": "forbid"}


class LoginIn(BaseModel):
    email: str
    password: str
    model_config = {"extra": "forbid"}


class MeOut(BaseModel):
    id: str
    email: str
    role: str
    is_admin: bool
    phone: str | None
    sms_opt_in: bool


class ConsentIn(BaseModel):
    opt_in: bool
    phone: str | None = None
    model_config = {"extra": "forbid"}


class AlertIn(BaseModel):
    title_en: str
    title_es: str
    body_en: str
    body_es: str
    severity: Literal["info", "watch", "warning", "severe"]
    area: str
    idempotency_key: str | None = None
    model_config = {"extra": "forbid"}


class TestSmsIn(BaseModel):
    to: str
    text: str = Field(default="Guaradar test message. If you received this, the gateway works.")
    confirm: bool = False
    model_config = {"extra": "forbid"}


def _me(user: User) -> MeOut:
    return MeOut(
        id=user.id,
        email=user.email,
        role=user.role,
        is_admin=user.is_admin,
        phone=user.phone_e164,
        sms_opt_in=user.sms_opt_in,
    )


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


@auth_router.post("/register", response_model=MeOut, status_code=201)
def register(payload: RegisterIn, response: Response) -> MeOut:
    """Create a PUBLIC account. Admin roles cannot be requested here."""
    try:
        user = auth_svc.create_user(payload.email, payload.password, role="public")
        signed, token = auth_svc.authenticate(payload.email, payload.password)
    except AuthError as exc:
        raise _auth_http(exc) from exc
    auth_svc.audit(signed, "auth.register", subject=signed.id)
    set_session_cookie(response, token)
    return _me(signed)


@auth_router.post("/login", response_model=MeOut)
def login(payload: LoginIn, response: Response) -> MeOut:
    try:
        user, token = auth_svc.authenticate(payload.email, payload.password)
    except AuthError as exc:
        raise _auth_http(exc) from exc
    auth_svc.audit(user, "auth.login", subject=user.id)
    set_session_cookie(response, token)
    return _me(user)


@auth_router.post("/logout", status_code=204)
def logout(
    response: Response,
    authorization: Annotated[str | None, Header()] = None,
    guaradar_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif guaradar_session:
        token = guaradar_session
    if token:
        auth_svc.revoke_session(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


@auth_router.get("/me", response_model=MeOut)
def me(user: Annotated[User, Depends(current_user)]) -> MeOut:
    return _me(user)


# ---------------------------------------------------------------------------
# Public-side SMS consent
# ---------------------------------------------------------------------------


@sms_router.get("/consent")
def get_consent(user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    return {
        "sms_opt_in": user.sms_opt_in,
        "phone": user.phone_e164,
        "history": sms_svc.consent_history(user.id),
        "gateway": describe_config(),
    }


@sms_router.post("/consent")
def post_consent(
    payload: ConsentIn, user: Annotated[User, Depends(current_user)]
) -> dict[str, Any]:
    """Opt in or withdraw. Only the signed-in user can change their own consent."""
    try:
        updated = sms_svc.set_consent(
            user, opt_in=payload.opt_in, phone=payload.phone, source="web"
        )
    except AuthError as exc:
        raise _auth_http(exc) from exc
    return {
        "sms_opt_in": updated.sms_opt_in,
        "phone": updated.phone_e164,
        "history": sms_svc.consent_history(updated.id),
    }


# ---------------------------------------------------------------------------
# Admin: SMS configuration and test send
# ---------------------------------------------------------------------------


@admin_router.get("/status")
def admin_status(user: Annotated[User, Depends(_admin_any)]) -> dict[str, Any]:
    """What the admin console may know: configuration booleans, never values."""
    return {
        "actor": _me(user).model_dump(),
        "gateway": describe_config(),
        "delivery": sms_svc.delivery_summary(),
        "recipients_opted_in": len(sms_svc.opted_in_recipients()),
    }


@admin_router.get("/delivery")
def admin_delivery(
    user: Annotated[User, Depends(_admin_any)],
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    return {
        "summary": sms_svc.delivery_summary(),
        "messages": sms_svc.delivery_log(limit),
        "gateway_mode": describe_config()["mode"],
    }


@admin_router.get("/alerts")
def admin_alerts(user: Annotated[User, Depends(_admin_any)]) -> dict[str, Any]:
    return {"alerts": sms_svc.list_alerts()}


@admin_router.post("/alerts", status_code=201)
def admin_create_alert(
    payload: AlertIn, user: Annotated[User, Depends(_admin_operator)]
) -> dict[str, Any]:
    try:
        return sms_svc.create_alert(
            user,
            title_en=payload.title_en,
            title_es=payload.title_es,
            body_en=payload.body_en,
            body_es=payload.body_es,
            severity=payload.severity,
            area=payload.area,
            idempotency_key=payload.idempotency_key,
        )
    except (AuthError, SmsError) as exc:
        raise (_auth_http(exc) if isinstance(exc, AuthError) else _sms_http(exc)) from exc


@admin_router.post("/alerts/{alert_id}/approve")
def admin_approve_alert(
    alert_id: str, user: Annotated[User, Depends(_admin_publisher)]
) -> dict[str, Any]:
    try:
        return sms_svc.approve_alert(user, alert_id)
    except SmsError as exc:
        raise _sms_http(exc) from exc


@admin_router.post("/alerts/{alert_id}/send")
def admin_send_alert(
    alert_id: str,
    user: Annotated[User, Depends(_admin_publisher)],
    confirm: bool = Query(default=False),
    language: Literal["en", "es"] = Query(default="en"),
) -> dict[str, Any]:
    """Send an approved alert. `confirm=true` is mandatory and fails closed."""
    try:
        summary = sms_svc.send_alert(
            user, alert_id, language=language, gateway=SmsGateway(), confirmed=confirm
        )
    except SmsError as exc:
        raise _sms_http(exc) from exc
    return {
        "alert_id": summary.alert_id,
        "dry_run": summary.dry_run,
        "attempted": summary.attempted,
        "accepted": summary.accepted,
        "failed": summary.failed,
        "skipped_rate_limited": summary.skipped_rate_limited,
        "states": summary.states,
        "recipients": summary.recipients,
    }


@admin_router.post("/alerts/{alert_id}/refresh")
def admin_refresh_alert(
    alert_id: str, user: Annotated[User, Depends(_admin_publisher)]
) -> dict[str, Any]:
    """Poll the provider for real states. Never upgrades anything on its own say-so."""
    return {"results": sms_svc.refresh_status(alert_id, SmsGateway())}


@admin_router.post("/test-sms")
def admin_test_sms(payload: TestSmsIn, user: Annotated[User, Depends(_admin_operator)]) -> dict:
    """Admin-only test send. Requires explicit confirmation."""
    if not payload.confirm:
        raise HTTPException(
            status_code=428, detail="test send requires confirm=true"
        )
    try:
        phone = sms_svc.validate_phone(payload.to)
        text = sms_svc.validate_message(payload.text)
    except AuthError as exc:
        raise _auth_http(exc) from exc

    gateway = SmsGateway()
    result = gateway.send(phone, text)
    auth_svc.audit(
        user, "sms.test_send", subject=sms_svc.mask_phone(phone),
        detail=f"dry_run={result.dry_run} state={result.state}",
    )
    return {
        "dry_run": result.dry_run,
        "state": result.state,
        "provider_id": result.provider_id,
        "provider_state": result.provider_state,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "to": sms_svc.mask_phone(phone),
    }


@admin_router.get("/audit")
def admin_audit(
    user: Annotated[User, Depends(_admin_any)],
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    return {"entries": auth_svc.recent_audit(limit)}
