# M13 — Public/Admin Access and SMS Alerts: Evidence

**Date:** 2026-10-26
**Block:** M13 — authentication, role-based authorisation, SMS Gateway integration
**Verdict:** access separation and RBAC are **real and server-enforced**; SMS is **implemented and
verified end-to-end in DRY-RUN** because this host has no gateway credentials.
**N-5 remains OPEN — no browser, so nothing has been visually verified.**

| Gate | Result |
|---|---|
| Tests without PostgreSQL | **567 passed, 12 skipped** |
| Tests with PostgreSQL 16.2 | **576 passed, 3 skipped** |
| `app/domain/risk.py` branch | **100 %** (unchanged) |
| `app/routing/status_repository.py` branch | **100 %** (unchanged) |
| `tsc -b --force` | **exit 0** |
| `npm run build` | 302.36 kB / **92.46 kB gzip** |
| i18n guard | **187 keys**, both locales |
| Dependency pins | **12, unchanged** — no new dependency was added |

---

## 1. SMS status: **implemented, tested, DRY-RUN**

This is the honest headline. No message has left this machine, and no delivery is claimed.

```
$ python -m app.admin_cli sms-config
mode: dry_run
  username_set: False
  password_set: False
  device_id_set: False
  base_url_set: True

SMS is in DRY-RUN: no message can leave this machine.
```

**Why:** `SMS_GATE_USERNAME` / `SMS_GATE_PASSWORD` are not set, and no `.env` exists. Per the
brief, a mock/dry-run mode is the correct outcome, and it is clearly labelled everywhere.

### Configuration required (names only, no values)

| Variable | Required | Purpose |
|---|---|---|
| `SMS_GATE_USERNAME` | yes | SMS Gateway account username (used for Basic → JWT) |
| `SMS_GATE_PASSWORD` | yes | SMS Gateway account password |
| `SMS_GATE_BASE_URL` | no | defaults to `https://api.sms-gate.app` |
| `SMS_GATE_DEVICE_ID` | no | target a specific paired Android device |

Set these **server-side only** and restart. They are never sent to the browser, never returned by
any endpoint, and never written to the database. `describe_config()` returns booleans only.

**Even with credentials, delivery still requires a paired Android phone online** — this gateway
sends through a physical device, so credentials alone prove nothing.

### The documented flow, followed rather than assumed

Read from `docs.sms-gate.app` (integration/authentication, features/sending-messages,
features/status-tracking):

1. `POST /3rdparty/v1/auth/token` with **HTTP Basic** + `{ttl, scopes}` → `{access_token, ...}`
2. `POST /3rdparty/v1/messages` with `Authorization: Bearer <jwt>`, body `{"textMessage": {"text": …}, "phoneNumbers": [...]}`
3. `GET /3rdparty/v1/messages/{id}` for state

The brief warned not to treat an API key as interchangeable with a JWT. The client does not: it
performs the Basic→JWT exchange and uses **only** the returned bearer token for message calls. A
test asserts the token request carries `Basic` while the send carries `Bearer`.

**Scopes requested: `messages:send` and `messages:read` only.** A test asserts `all:any` and
`tokens:manage` are *not* requested.

### Delivery states — the part that matters most

The provider's lifecycle is `Pending → Processed → Sent → Delivered`, with `Failed` / `Cancelled`
as alternatives. Two properties are enforced:

- **Acceptance is not delivery.** A 200 from POST means *queued*. The stored state is whatever
  the provider reported (`Pending`), never `delivered`.
- **`Sent` is not proof of delivery.** The provider's own docs state a message can remain in
  `Sent` even after successful delivery. So `Sent` maps to `sent` and the UI labels it
  **"Sent — not confirmed delivered"**. `classify_provider_state` maps any unrecognised state to
  `unknown`, never to success — tested against `"WOBBLE"`, `"delivered!"`, `"SENT "`, `"delivred"`.

---

## 2. Public vs Admin access

### What is enforced, and how

| Layer | Mechanism |
|---|---|
| Identity | Session token in an **httpOnly cookie** (or `Authorization: Bearer`), looked up server-side |
| Authorisation | `require_role(min)` dependency on **every** admin route; raises 401/403 before the handler |
| Role source | `users.role` column only — **no request field, header or query can set it** |
| Admin creation | CLI only (`python -m app.admin_cli create-user --role admin`), requiring shell access |

**Hiding a frontend tab is not the mechanism.** Tests call the endpoints directly, bypassing the
UI entirely — exactly what an attacker does.

### Verified live against the running server

```
1 anonymous -> admin:     401
2 register:               201 | role: public | is_admin: False
3 public -> admin:        403
4 SMS opt-in:             200 | normalised: +593997654321
5 drafter login:          200
6 draft alert:            201 | is_demo: 1
7 self-approve:           403  (requires publisher role)
8 publisher approve:      200 | status: approved
9 send without confirm:   428
10 send confirmed:        200 | dry_run: True | attempted: 2 | states: {'dry_run': 2}
    recipient masked:     +593…21
11 duplicate send:        409 | duplicate_send
12 delivery ledger:       200 | summary: {'dry_run': 2}
    full number hidden:   True
```

Also verified **through the Vite proxy** (the browser's own path): login sets a cookie same-origin
and `GET /api/admin/status` returns 200 for a publisher.

### Privilege escalation: attempted and blocked

| Attempt | Result |
|---|---|
| `POST /register` with `{"role": "admin"}` | **422** — `extra: forbid` |
| `X-Role: admin` header with a public session | **403** — role comes from the session row |
| `?role=admin` query parameter | **403** |
| `Authorization: Bearer admin` | **401** |
| Any endpoint that mints an admin | **none exists** |

### Roles

`public → viewer → operator → publisher → admin`, enforced as a ladder:
- **viewer** reads admin views, cannot write (403 on test-send)
- **operator** drafts alerts, cannot approve or send
- **publisher** approves and sends
- **Separation of duties:** the drafter of an alert cannot approve it (403), enforced in
  `approve_alert`, not just in the UI.

### Security properties implemented

- **PBKDF2-HMAC-SHA256, 600,000 iterations** (stdlib — no new dependency). ~84 ms per verify.
- **Sessions stored only as SHA-256 hashes.** A dump of the database yields no usable session.
  A test asserts the raw token is absent from the `sessions` table.
- **Login throttle:** 5 failures per email per 15 min → 429. Checked *before* password comparison,
  so timing cannot distinguish throttled from wrong-password.
- **Account enumeration resisted:** unknown email and wrong password return identical status and
  identical detail. Absent users are verified against a dummy hash so timing matches too.
- **Passwords never returned**, never logged, never in any response (tested).
- **Audit log** append-only; every consent change and admin action recorded.

### Limits I am not hiding

| Limit | Consequence |
|---|---|
| **SQLite, not PostgreSQL** | Single-node file store, no RLS, no pooling. The Postgres schema remains the design of record. |
| **No CSRF token** | Cookie is `SameSite=Lax` and state-changing routes need a JSON body; this blocks simple form CSRF but is not a complete defence and is not claimed to be. |
| **No password reset** | Needs email delivery, which does not exist. |
| **No MFA** | Not claimed anywhere. |
| **Throttle is in-process** | Lost on restart; would need Redis behind multiple workers. |
| **Bearer tokens are bearer tokens** | Anyone holding a cookie is that user until expiry. No rotation-on-use. |

---

## 3. SMS alert workflow

The six-step flow from the brief, all present:

| Step | Where |
|---|---|
| 1. Admin drafts | `POST /api/admin/alerts` — requires bilingual EN+ES, validated |
| 2. Admin reviews | Admin console row shows title, severity, area, status, DEMO badge |
| 3. Backend validates message + consent | `validate_message`, E.164 check, consent re-read at send time |
| 4. Admin explicitly confirms | `?confirm=true` required (428 without); UI shows a second confirmation |
| 5. FastAPI submits to gateway | `SmsGateway.send` |
| 6. Dashboard shows real response | States come from the provider; `dry_run` when unconfigured |

**Safety gates enforced server-side:**
- Consent re-checked **at send time**, so a withdrawal seconds earlier is honoured (tested).
- Only `sms_opt_in = 1` recipients with a valid number are selected.
- **Per-recipient dedupe** on `(alert_id, phone, body_hash)` plus a 2-minute cooldown (409 on repeat).
- Rate limit: 5 messages per phone per hour.
- **Every alert is `is_demo = 1`** — there is no verified emergency feed, so no alert created here
  can be anything else. The UI shows a DEMO badge and states it is not verified emergency information.
- Delivery log stores **masked numbers** (`+593…21`) and **no message bodies** (tested).

---

## 4. Defects found and fixed

| # | Defect | Why it mattered |
|---|---|---|
| **D-1** | **Database path was cwd-relative**, so uvicorn (repo root) and the CLI (`backend/`) wrote **two different SQLite files**. CLI-created accounts were invisible to the server, presenting as "wrong password". | Genuinely confusing, took several probes to isolate. Fixed by anchoring to the repo root; two regression tests added, one of which asserts the path is identical from any cwd. |
| **D-2** | CORS `allow_methods=["GET"]` blocked the new POST routes | Now includes POST/DELETE; `allow_credentials` stays **False** because the browser path is same-origin via the Vite proxy |
| **D-3** | `adminAlertsEmpty` said "there is no alerts table or publication endpoint" — **false** once alerts shipped | Removed the string and the panel. Caught by the M12 stale-disclosure test suite, which is exactly what it exists for. |
| **D-4** | The old test `test_cors_methods_are_read_only` asserted POST was never allowed anywhere | Replaced with a **stronger** invariant: no *public* path accepts a mutation, and every mutation route is probed with no credentials (401/403/422/428 expected). Mutation-tested by bypassing the guard — the test fails. |
| **D-5** | `validate_phone` docstring claimed spaces are "rejected"; the code normalises them | Normalising is the better behaviour, so the **doc** was corrected, not the code. Guessing a country code is still refused. |

### My own probe bugs (worth naming)

- A Python test harness sent `GET` for every no-body POST, producing a barrage of false `405`s
  that looked like a routing bug. **curl was correct the whole time.** The lesson: when two
  clients disagree, suspect the one I wrote.
- An earlier harness followed a 307 redirect and silently converted POST→GET.

### Tests that bite (mutation-checked)

| Mutation | Result |
|---|---|
| Removed the `at_least(minimum)` role check | **9 tests failed** |
| Bypassed `require_admin` to return a synthetic admin | **invariant test failed** |
| Counted `unknown` as `open` in the admin tally (M12) | **failed** |

---

## 5. What the Admin panel can actually do

**New in this block:** draft alerts (bilingual, required), approve them (publisher only, not the
drafter), send them (with explicit confirmation), send a test SMS (with a confirmation checkbox),
and view the delivery ledger with real provider states.

**Still genuinely unavailable, stated as such:** incidents (no citizen-report channel exists) and
shelters (no register — and simulating shelter locations would misdirect someone in a flood).

**Not implemented, per the brief:** no fake authentication, no role switcher, no "changes saved"
message that the backend cannot honour.

---

## 6. Still required / still unverified

| Item | Status |
|---|---|
| **N-5 visual verification** | **OPEN** — no browser on this host. Nothing seen rendered. |
| SMS gateway credentials | **REQUIRED** for live sending (`SMS_GATE_USERNAME`, `SMS_GATE_PASSWORD`) |
| Paired Android device | **REQUIRED** for any real delivery beyond credentials |
| PostgreSQL-backed auth | Not done — SQLite prototype store |
| Webhook delivery receipts | Not done — needs a public endpoint; status is polled instead |
| Push to GitHub | **BLOCKED** — no credentials on this host (see §7) |

Two new blockers for the register: **N-17** (auth/SMS persist to SQLite, not PostgreSQL) and
**N-18** (no webhook ingestion, so delivery state is polled rather than pushed).

---

## 7. Commit status

Committed locally on `main`. **Push blocked:** no `gh` CLI, no `GH_TOKEN`, no `~/.netrc`, no SSH
key, and `https://github.com/ah-REE/guaradar` returns 404 unauthenticated.

```bash
# from the project directory, where credentials exist
git push -u origin main
```

---

## 8. Standing statements

- **Sensors are SIMULATED.** Road **status** is seed/demo data. Geometry is a bounded real OSM
  extract, not city-wide.
- **No route is claimed safe**; duration is labelled an estimate.
- **SMS has sent nothing.** Dry-run is labelled everywhere and a dry run is never counted as sent.
- **No delivery is ever claimed from acceptance**, and `Sent` is shown as unconfirmed.
- **Every alert is marked DEMO** — no verified emergency feed exists.
- **Visual verification was not performed.** N-5 remains open.
- No deployment, no spend, no force-push, no history rewrite, no secrets committed.
