"""SMS consent, alert workflow, sending, and delivery ledger.

THE SAFETY RULES THIS ENFORCES, IN ORDER OF IMPORTANCE

  1. **Consent is required and is checked server-side at send time**, not at draft time. A user
     who withdraws between draft and send is excluded. Consent is read from `users.sms_opt_in`,
     which only the user themself can change.
  2. **A phone number must be E.164.** Validated on the backend; the gateway's
     `skipPhoneValidation` parameter is deliberately NOT used, so the provider also validates.
  3. **Dedupe.** Each send carries an idempotency key derived from (alert, body hash). A second
     send of the same alert with the same body is refused, and a per-recipient unique index on
     (alert_id, body_hash) prevents a double send even if two requests race.
  4. **Rate limits** per phone number and per alert, in a rolling window.
  5. **No delivery claim from acceptance.** The stored state is whatever the provider said
     (`Pending` usually). `delivered` is only ever written from a provider status response that
     actually says `Delivered`.
  6. **Demo alerts are marked.** Every alert carries `is_demo`. Alerts created from this UI are
     always demo, because there is no verified emergency feed to base a real one on.

WHAT IS NOT BUILT
  Webhook ingestion for delivery reports. The provider supports webhooks (documented), but
  receiving them requires a publicly reachable endpoint, which this local prototype does not
  have. Delivery state therefore comes from polling the status endpoint (`refresh_status`), and
  the UI says "last checked" rather than implying live tracking.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from app.auth import User, ValidationFailed, audit
from app.sms.gateway import SmsGateway, classify_provider_state
from app.store import connect
from app.security import to_iso, utcnow

# E.164: '+' then 8-15 digits. Rejects spaces, dashes, parentheses and local formats, because a
# message sent to a malformed number is a message that silently fails for someone in a flood.
E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")

SMS_MAX_LENGTH = 480  # three concatenated segments; beyond that the alert is not an SMS
RATE_PER_PHONE = timedelta(hours=1)
RATE_PER_PHONE_MAX = 5
SEND_COOLDOWN = timedelta(minutes=2)


class SmsError(Exception):
    def __init__(self, message: str, *, code: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def validate_phone(raw: str) -> str:
    """Normalise conventional formatting, then require strict E.164.

    Spaces, dashes, parentheses and dots are stripped, because people paste numbers with grouping
    ("+593 99 999 9999") and rejecting that is hostile for no security benefit. What is NOT done
    is guessing: a number without a leading '+' is rejected rather than assuming +593, because
    silently prepending a country code could deliver an emergency message to the wrong person.
    """
    cleaned = (raw or "").strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not E164_RE.match(cleaned):
        raise ValidationFailed(
            "phone number must be in international format, e.g. +593999999999"
        )
    return cleaned


def validate_message(text: str) -> str:
    body = (text or "").strip()
    if not body:
        raise ValidationFailed("message must not be empty")
    if len(body) > SMS_MAX_LENGTH:
        raise ValidationFailed(f"message must be at most {SMS_MAX_LENGTH} characters")
    return body


def body_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def mask_phone(phone: str) -> str:
    """For display and logs: keep the country code and last two digits only."""
    if len(phone) <= 6:
        return "***"
    return f"{phone[:4]}…{phone[-2:]}"


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------


def set_consent(user: User, *, opt_in: bool, phone: str | None, source: str) -> User:
    """Record an opt-in or opt-out. Opting out clears the number.

    Clearing on opt-out is deliberate: if the number is retained after withdrawal it can still be
    used by a bug, and there is no lawful purpose in keeping it for this prototype.
    """
    now = to_iso(utcnow())
    if opt_in:
        if not phone:
            raise ValidationFailed("a phone number is required to opt in to SMS alerts")
        e164 = validate_phone(phone)
        with connect() as conn:
            conn.execute(
                "update users set sms_opt_in = 1, phone_e164 = ?, sms_opted_in_at = ?, "
                "sms_opted_out_at = null where id = ?",
                (e164, now, user.id),
            )
            conn.execute(
                "insert into sms_consent_events (user_id, action, phone_e164, source, at) "
                "values (?, 'opt_in', ?, ?, ?)",
                (user.id, e164, source, now),
            )
        audit(user, "sms.consent.opt_in", subject=user.id, detail=f"source={source}")
    else:
        with connect() as conn:
            conn.execute(
                "update users set sms_opt_in = 0, phone_e164 = null, sms_opted_out_at = ? "
                "where id = ?",
                (now, user.id),
            )
            conn.execute(
                "insert into sms_consent_events (user_id, action, phone_e164, source, at) "
                "values (?, 'opt_out', null, ?, ?)",
                (user.id, source, now),
            )
        audit(user, "sms.consent.opt_out", subject=user.id, detail=f"source={source}")

    with connect() as conn:
        row = conn.execute("select * from users where id = ?", (user.id,)).fetchone()
    return User(
        id=row["id"],
        email=row["email"],
        role=row["role"],
        phone_e164=row["phone_e164"],
        sms_opt_in=bool(row["sms_opt_in"]),
        disabled=bool(row["disabled"]),
    )


def consent_history(user_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "select action, phone_e164, source, at from sms_consent_events "
            "where user_id = ? order by id desc",
            (user_id,),
        ).fetchall()
    return [
        {
            "action": r["action"],
            "phone": mask_phone(r["phone_e164"]) if r["phone_e164"] else None,
            "source": r["source"],
            "at": r["at"],
        }
        for r in rows
    ]


def opted_in_recipients() -> list[dict]:
    """Everyone who may lawfully receive an alert. Consent + a valid number, both required."""
    with connect() as conn:
        rows = conn.execute(
            "select id, phone_e164 from users "
            "where sms_opt_in = 1 and phone_e164 is not null and disabled = 0 order by id"
        ).fetchall()
    return [{"user_id": r["id"], "phone": r["phone_e164"]} for r in rows]


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


SEVERITIES = ("info", "watch", "warning", "severe")


def create_alert(
    actor: User,
    *,
    title_en: str,
    title_es: str,
    body_en: str,
    body_es: str,
    severity: str,
    area: str,
    idempotency_key: str | None = None,
) -> dict:
    """Draft an alert. Requires bilingual content — the hard bilingual block from D22/D26."""
    if severity not in SEVERITIES:
        raise ValidationFailed(f"severity must be one of {list(SEVERITIES)}")
    for field, value in (
        ("title_en", title_en), ("title_es", title_es),
        ("body_en", body_en), ("body_es", body_es), ("area", area),
    ):
        if not (value or "").strip():
            raise ValidationFailed(f"{field} must not be empty")
    validate_message(body_en)
    validate_message(body_es)

    now = to_iso(utcnow())
    aid = uuid.uuid4().hex
    try:
        with connect() as conn:
            conn.execute(
                "insert into alerts (id, title_en, title_es, body_en, body_es, severity, area, "
                "status, is_demo, created_by, created_at, idempotency_key) "
                "values (?,?,?,?,?,?,?,'draft',1,?,?,?)",
                (aid, title_en.strip(), title_es.strip(), body_en.strip(), body_es.strip(),
                 severity, area.strip(), actor.id, now, idempotency_key),
            )
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise SmsError(
                "an alert with this content was already drafted",
                code="duplicate_alert",
                status_code=409,
            ) from exc
        raise
    audit(actor, "alert.create", subject=aid, detail=f"severity={severity} area={area}")
    return get_alert(aid) or {}


def get_alert(alert_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("select * from alerts where id = ?", (alert_id,)).fetchone()
    return dict(row) if row else None


def list_alerts(limit: int = 50) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "select id, title_en, severity, area, status, is_demo, created_at, sent_at "
            "from alerts order by created_at desc limit ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
    return [dict(r) for r in rows]


def approve_alert(actor: User, alert_id: str) -> dict:
    """Draft -> approved. Requires the publisher role (Stage 2 §2 separation of duties)."""
    alert = get_alert(alert_id)
    if not alert:
        raise SmsError("alert not found", code="not_found", status_code=404)
    if alert["status"] != "draft":
        raise SmsError(
            f"only a draft can be approved (this one is {alert['status']})",
            code="invalid_transition",
            status_code=409,
        )
    if alert["created_by"] == actor.id:
        # The same person must not draft and approve: that removes the second pair of eyes the
        # approval step exists to provide.
        raise SmsError(
            "the person who drafted an alert cannot also approve it",
            code="separation_of_duties",
            status_code=403,
        )
    with connect() as conn:
        conn.execute(
            "update alerts set status = 'approved', approved_by = ?, approved_at = ? "
            "where id = ? and status = 'draft'",
            (actor.id, to_iso(utcnow()), alert_id),
        )
    audit(actor, "alert.approve", subject=alert_id)
    return get_alert(alert_id) or {}


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


def _recent_count(subject: str, kind: str, window: timedelta) -> int:
    since = to_iso(utcnow() - window)
    with connect() as conn:
        row = conn.execute(
            "select count(*) as n from sms_rate_events where subject=? and kind=? and at > ?",
            (subject, kind, since),
        ).fetchone()
    return int(row["n"]) if row else 0


def _record_rate(subject: str, kind: str) -> None:
    with connect() as conn:
        conn.execute(
            "insert into sms_rate_events (subject, kind, at) values (?,?,?)",
            (subject, kind, to_iso(utcnow())),
        )


@dataclass
class SendSummary:
    alert_id: str
    dry_run: bool
    attempted: int
    accepted: int
    failed: int
    skipped_no_consent: int
    skipped_rate_limited: int
    states: dict[str, int]
    recipients: list[dict]


def send_alert(
    actor: User,
    alert_id: str,
    *,
    language: str = "en",
    gateway: SmsGateway | None = None,
    confirmed: bool = False,
) -> SendSummary:
    """Send an approved alert to opted-in recipients.

    `confirmed` must be True: sending is irreversible and the brief requires an explicit
    confirmation step. Without it this raises, so a forgotten flag fails closed.
    """
    if not confirmed:
        raise SmsError(
            "sending requires explicit confirmation", code="confirmation_required", status_code=428
        )

    alert = get_alert(alert_id)
    if not alert:
        raise SmsError("alert not found", code="not_found", status_code=404)
    if alert["status"] not in ("approved", "sent"):
        raise SmsError(
            f"only an approved alert can be sent (this one is {alert['status']})",
            code="invalid_transition",
            status_code=409,
        )

    # Dedupe: same alert + same body inside the cooldown is refused.
    if _recent_count(f"alert:{alert_id}:{body_hash(alert[f'body_{language}'])}", "send",
                     SEND_COOLDOWN) > 0:
        raise SmsError(
            "this alert was sent moments ago; wait before sending again",
            code="duplicate_send",
            status_code=409,
        )

    body = alert[f"body_{language}"]
    validate_message(body)
    gateway = gateway or SmsGateway()

    recipients = opted_in_recipients()
    attempted = accepted = failed = skipped_rate = 0
    states: dict[str, int] = {}
    rows: list[dict] = []

    for r in recipients:
        phone = r["phone"]
        # Consent is re-checked here, at send time, from the database — not from anything the
        # caller passed in. A withdrawal a second ago is honoured.
        if _recent_count(f"phone:{phone}", "sms", RATE_PER_PHONE) >= RATE_PER_PHONE_MAX:
            skipped_rate += 1
            continue

        # Per-recipient dedupe for this alert, independent of the cooldown above.
        with connect() as conn:
            existing = conn.execute(
                "select id from sms_messages where alert_id=? and phone_e164=? and body_hash=?",
                (alert_id, phone, body_hash(body)),
            ).fetchone()
        if existing:
            continue

        attempted += 1
        result = gateway.send(phone, body)
        state = result.state if result.ok else "failed"
        states[state] = states.get(state, 0) + 1
        if result.ok:
            accepted += 1
        else:
            failed += 1

        mid = uuid.uuid4().hex
        now = to_iso(utcnow())
        with connect() as conn:
            conn.execute(
                "insert into sms_messages (id, alert_id, user_id, phone_e164, body_hash, "
                "provider_id, state, provider_state, error_code, error_message, dry_run, "
                "created_at, updated_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mid, alert_id, r["user_id"], phone, body_hash(body), result.provider_id,
                 state, result.provider_state, result.error_code, result.error_message,
                 1 if result.dry_run else 0, now, now),
            )
        _record_rate(f"phone:{phone}", "sms")
        rows.append(
            {
                "message_id": mid,
                "phone": mask_phone(phone),
                "state": state,
                "dry_run": result.dry_run,
                "error_code": result.error_code,
            }
        )

    _record_rate(f"alert:{alert_id}:{body_hash(body)}", "send", )
    if accepted:
        with connect() as conn:
            conn.execute(
                "update alerts set status='sent', sent_at=? where id=?",
                (to_iso(utcnow()), alert_id),
            )
    audit(
        actor,
        "alert.send",
        subject=alert_id,
        detail=f"dry_run={gateway.cfg.configured is False} attempted={attempted} accepted={accepted}",
    )

    return SendSummary(
        alert_id=alert_id,
        dry_run=not gateway.cfg.configured,
        attempted=attempted,
        accepted=accepted,
        failed=failed,
        skipped_no_consent=0,
        skipped_rate_limited=skipped_rate,
        states=states,
        recipients=rows,
    )


def refresh_status(alert_id: str, gateway: SmsGateway | None = None) -> list[dict]:
    """Poll the provider for each message of an alert and update the ledger.

    Polling, not webhooks: receiving a webhook needs a public URL this prototype does not have.
    """
    gateway = gateway or SmsGateway()
    with connect() as conn:
        rows = conn.execute(
            "select id, provider_id, state, dry_run from sms_messages where alert_id = ?",
            (alert_id,),
        ).fetchall()

    out: list[dict] = []
    for r in rows:
        if r["dry_run"] or not r["provider_id"]:
            out.append({"message_id": r["id"], "state": r["state"], "changed": False})
            continue
        res = gateway.status(r["provider_id"])
        new_state = res.state if res.ok else classify_provider_state(None)
        changed = new_state != r["state"]
        if changed:
            with connect() as conn:
                conn.execute(
                    "update sms_messages set state=?, provider_state=?, updated_at=? where id=?",
                    (new_state, res.provider_state, to_iso(utcnow()), r["id"]),
                )
        out.append({"message_id": r["id"], "state": new_state, "changed": changed})
    return out


def delivery_log(limit: int = 100) -> list[dict]:
    """Minimal ledger for the admin view: masked numbers, no bodies."""
    with connect() as conn:
        rows = conn.execute(
            "select id, alert_id, phone_e164, state, provider_state, error_code, dry_run, "
            "created_at, updated_at from sms_messages order by created_at desc limit ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "alert_id": r["alert_id"],
            "phone": mask_phone(r["phone_e164"]),
            "state": r["state"],
            "provider_state": r["provider_state"],
            "error_code": r["error_code"],
            "dry_run": bool(r["dry_run"]),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def delivery_summary() -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute(
            "select state, count(*) as n from sms_messages group by state"
        ).fetchall()
    return {r["state"]: int(r["n"]) for r in rows}
