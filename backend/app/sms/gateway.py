"""SMS Gateway for Android client.

DOCUMENTED FLOW (read from docs.sms-gate.app, not assumed)
  1. `POST /3rdparty/v1/auth/token` with **HTTP Basic** credentials (username/password) and a
     JSON body `{"ttl": <seconds>, "scopes": [...]}` returns `{access_token, refresh_token,
     expires_at}`. The Basic credentials are NOT usable as a bearer token and vice versa — the
     brief's warning about treating an API key as interchangeable with a JWT is exactly this.
  2. `POST /3rdparty/v1/messages` with `Authorization: Bearer <access_token>` and a body whose
     text payload is nested under `textMessage.text` sends the message.
  3. `GET /3rdparty/v1/messages/{id}` returns the per-message state.

  Scopes requested: `messages:send` and `messages:read` only. `messages:read` is needed to report
  delivery state honestly; nothing else is requested (the docs' own least-privilege guidance).

PROVIDER STATES AND WHAT THEY MEAN FOR US
  The provider's lifecycle is Pending → Processed → Sent → Delivered, with Cancelling, Cancelled
  and Failed as terminal alternatives. Two things follow that this module refuses to blur:

  * **"Accepted" is not "delivered".** A 200 from POST means the server queued the message. The
    row starts at whatever state the provider reported (`Pending` normally) and is only ever
    upgraded from the provider's own status response.
  * **`Sent` is not proof of delivery either.** The provider's own documentation says a message
    can remain in `Sent` even after successful delivery when the Android OS does not report the
    final status. So `Sent` is reported as `sent` — never as `delivered` — and the UI says so.

DRY-RUN MODE
  When credentials are absent, `SmsGateway` runs in dry-run: it validates everything it would
  have validated, returns a synthetic `dry_run` state, and **never opens a socket**. This is the
  default on this machine, where no credentials exist. The UI labels every result accordingly, and
  a dry-run message is never counted as sent.

CREDENTIAL HANDLING
  Credentials come from the environment only (`SMS_GATE_USERNAME`, `SMS_GATE_PASSWORD`,
  optionally `SMS_GATE_BASE_URL`, `SMS_GATE_DEVICE_ID`). They are read at call time, never logged,
  never returned by any endpoint, and never written to the database. `describe_config()` reports
  whether they are *present* — booleans only — so the UI can explain what is missing without
  revealing values.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

DEFAULT_BASE_URL = "https://api.sms-gate.app"
SCOPES = ["messages:send", "messages:read"]
TOKEN_TTL = 3600

# Provider state -> our state. Anything unrecognised maps to 'unknown', never to success.
_PROVIDER_MAP: dict[str, str] = {
    "Pending": "pending",
    "Processed": "processed",
    "Sent": "sent",
    "Delivered": "delivered",
    "Failed": "failed",
    "Cancelled": "cancelled",
    "Cancelling": "cancelling",
}

OurState = Literal[
    "dry_run", "pending", "processed", "sent", "delivered", "failed", "cancelled",
    "cancelling", "unknown",
]


@dataclass(frozen=True)
class SendResult:
    ok: bool
    state: OurState
    provider_id: str | None
    provider_state: str | None
    dry_run: bool
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class GatewayConfig:
    base_url: str
    username: str | None
    password: str | None
    device_id: str | None

    @property
    def configured(self) -> bool:
        """True only when real credentials exist. Device ID is optional (multi-device accounts)."""
        return bool(self.username and self.password)


def load_config() -> GatewayConfig:
    return GatewayConfig(
        base_url=(os.environ.get("SMS_GATE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        username=os.environ.get("SMS_GATE_USERNAME") or None,
        password=os.environ.get("SMS_GATE_PASSWORD") or None,
        device_id=os.environ.get("SMS_GATE_DEVICE_ID") or None,
    )


def describe_config() -> dict[str, Any]:
    """What the UI may know about configuration. Booleans only — never the values."""
    cfg = load_config()
    return {
        "configured": cfg.configured,
        "base_url_set": bool(cfg.base_url),
        "username_set": bool(cfg.username),
        "password_set": bool(cfg.password),
        "device_id_set": bool(cfg.device_id),
        "mode": "live" if cfg.configured else "dry_run",
        "required_env": [
            "SMS_GATE_USERNAME",
            "SMS_GATE_PASSWORD",
        ],
        "optional_env": ["SMS_GATE_BASE_URL", "SMS_GATE_DEVICE_ID"],
        "scopes_requested": SCOPES,
    }


def classify_provider_state(raw: str | None) -> OurState:
    """Map a provider state string to ours. Unknown input is 'unknown', never 'delivered'."""
    if not raw:
        return "unknown"
    return _PROVIDER_MAP.get(raw, "unknown")  # type: ignore[return-value]


class SmsGateway:
    """Thin client. One instance per operation; it holds a token in memory only."""

    def __init__(self, config: GatewayConfig | None = None, *, transport=None) -> None:
        self.cfg = config or load_config()
        self._token: str | None = None
        self._transport = transport  # injectable for tests

    # -- auth ---------------------------------------------------------------
    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.cfg.base_url,
            timeout=20.0,
            transport=self._transport,
        )

    def fetch_token(self) -> str:
        """Exchange Basic credentials for a JWT. Never returns the password."""
        if not self.cfg.configured:
            raise RuntimeError("gateway is not configured")
        with self._client() as client:
            resp = client.post(
                "/3rdparty/v1/auth/token",
                auth=(self.cfg.username or "", self.cfg.password or ""),
                json={"ttl": TOKEN_TTL, "scopes": SCOPES},
            )
            resp.raise_for_status()
            data = resp.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError("token response contained no access_token")
        self._token = token
        return token

    def _headers(self) -> dict[str, str]:
        if self._token is None:
            self.fetch_token()
        return {"Authorization": f"Bearer {self._token}"}

    # -- send ---------------------------------------------------------------
    def send(self, phone_e164: str, text: str, *, dry_run_id: str | None = None) -> SendResult:
        """Send one message. Returns the state the provider reported, or a dry-run result."""
        if not self.cfg.configured:
            # Dry run: validate shape, open no socket, claim nothing.
            if not phone_e164.startswith("+") or len(phone_e164) < 8:
                return SendResult(
                    ok=False,
                    state="failed",
                    provider_id=None,
                    provider_state=None,
                    dry_run=True,
                    error_code="invalid_phone",
                    error_message="phone number is not E.164",
                )
            return SendResult(
                ok=True,
                state="dry_run",
                provider_id=dry_run_id or f"dry-{uuid.uuid4().hex[:12]}",
                provider_state=None,
                dry_run=True,
                error_message=None,
            )

        body: dict[str, Any] = {
            "textMessage": {"text": text},
            "phoneNumbers": [phone_e164],
            "withDeliveryReport": True,
        }
        if self.cfg.device_id:
            body["deviceId"] = self.cfg.device_id

        try:
            with self._client() as client:
                resp = client.post("/3rdparty/v1/messages", json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            return SendResult(
                ok=False,
                state="failed",
                provider_id=None,
                provider_state=None,
                dry_run=False,
                error_code="transport_error",
                error_message=type(exc).__name__,
            )

        if resp.status_code >= 400:
            return SendResult(
                ok=False,
                state="failed",
                provider_id=None,
                provider_state=None,
                dry_run=False,
                error_code=f"http_{resp.status_code}",
                error_message=_safe_provider_message(resp),
            )

        # The provider accepts an array of messages; take the first.
        try:
            data = resp.json()
        except ValueError:
            return SendResult(
                ok=False, state="unknown", provider_id=None, provider_state=None,
                dry_run=False, error_code="bad_json",
                error_message="provider returned a non-JSON body",
            )

        item = data[0] if isinstance(data, list) and data else data
        if not isinstance(item, dict):
            return SendResult(
                ok=False, state="unknown", provider_id=None, provider_state=None,
                dry_run=False, error_code="unexpected_shape",
                error_message="provider response had an unexpected shape",
            )

        provider_state = item.get("state") or "Pending"
        # A 200 means QUEUED. We record the provider's own state and never infer delivery.
        return SendResult(
            ok=True,
            state=classify_provider_state(provider_state),
            provider_id=item.get("id"),
            provider_state=provider_state,
            dry_run=False,
        )

    # -- status -------------------------------------------------------------
    def status(self, provider_id: str) -> SendResult:
        """Fetch the current provider state. Used to upgrade/replace our stored state."""
        if not self.cfg.configured:
            return SendResult(
                ok=False, state="dry_run", provider_id=provider_id, provider_state=None,
                dry_run=True, error_code="dry_run",
                error_message="gateway not configured; no delivery status is available",
            )
        try:
            with self._client() as client:
                resp = client.get(
                    f"/3rdparty/v1/messages/{provider_id}", headers=self._headers()
                )
        except httpx.HTTPError as exc:
            return SendResult(
                ok=False, state="unknown", provider_id=provider_id, provider_state=None,
                dry_run=False, error_code="transport_error",
                error_message=type(exc).__name__,
            )
        if resp.status_code == 404:
            return SendResult(
                ok=False, state="unknown", provider_id=provider_id, provider_state=None,
                dry_run=False, error_code="not_found",
                error_message="provider does not know this message id",
            )
        if resp.status_code >= 400:
            return SendResult(
                ok=False, state="unknown", provider_id=provider_id, provider_state=None,
                dry_run=False, error_code=f"http_{resp.status_code}",
                error_message=_safe_provider_message(resp),
            )
        try:
            data = resp.json()
        except ValueError:
            return SendResult(
                ok=False, state="unknown", provider_id=provider_id, provider_state=None,
                dry_run=False, error_code="bad_json", error_message="non-JSON status body",
            )
        raw = data.get("state")
        return SendResult(
            ok=True,
            state=classify_provider_state(raw),
            provider_id=provider_id,
            provider_state=raw,
            dry_run=False,
        )


def _safe_provider_message(resp: httpx.Response) -> str:
    """A short, non-secret summary of a provider error.

    Deliberately does not echo the full body: error payloads can contain the recipient's number,
    and the brief says to keep logs minimal and never log unnecessary personal data.
    """
    try:
        data = resp.json()
        if isinstance(data, dict):
            msg = data.get("message") or data.get("error") or data.get("code")
            if msg:
                return str(msg)[:200]
    except ValueError:
        pass
    return f"HTTP {resp.status_code}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
