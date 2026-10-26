"""Local persistence for auth, SMS consent, alerts and delivery logs.

WHY SQLITE RATHER THAN POSTGRESQL
  The project already has a PostgreSQL schema (`supabase/migrations`) and it is the intended
  target. But at this point in the build there is no PostgreSQL instance attached to the running
  API: `STATUS_PERSISTENCE_ENABLED = False`, no `GUARADAR_PG_DSN` is configured, and the M12
  PostgreSQL instance was a throwaway test harness. The brief for this block also says explicitly:

      "Do not pretend that changes are saved when the backend cannot persist them."

  So there are two honest options:

    (a) build the auth/SMS/alert tables in PostgreSQL only, and have every endpoint return 503
        until someone provisions a database — a demo that cannot demonstrate anything
        (b) persist to a local SQLite file, state plainly that it is a single-node prototype
        store, and keep the PostgreSQL path open

  This module takes (b). SQLite is in the standard library, so it adds no dependency.

WHAT THIS IS NOT
  * **Not production storage.** One process, one file, no replication, no connection pooling,
    no row-level security. `docs/SMS-AND-AUTH-EVIDENCE.md` says so and the Admin UI repeats it.
  * **Not a substitute for the PostgreSQL schema.** The Postgres tables remain the design of
    record; these are the tables this prototype can actually write to today.
  * **Not a secrets store.** SMS credentials are read from the environment, never stored here.
    Password *hashes* are stored; passwords and tokens are not.

CONCURRENCY
  SQLite is opened per-operation with `check_same_thread=False` and `journal_mode=WAL`, and every
  write uses an explicit transaction. FastAPI's test client and uvicorn both exercise this; the
  test suite runs requests concurrently in places, so a single shared connection would be wrong.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# Overridable so tests get an isolated database per run and never touch a developer's file.
#
# The default is anchored to the REPOSITORY ROOT (the parent of the `app` package), not to the
# process working directory. A cwd-relative default looked fine but produced two different
# databases: uvicorn started from the repo root wrote `data/guaradar.db`, while `python -m
# app.admin_cli` started from `backend/` wrote `backend/data/guaradar.db`. Accounts created by
# the CLI were then invisible to the server, which presented as "wrong password" — a confusing
# bug caused purely by path resolution. Anchoring removes the ambiguity.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = Path(os.environ.get("GUARADAR_DB_PATH", str(_REPO_ROOT / "data" / "guaradar.db")))

SCHEMA = """
-- Users: one row per account. `role` is the authorisation claim; it is set server-side only.
create table if not exists users (
    id              text primary key,
    email           text not null unique,
    password_hash   text not null,
    role            text not null check (role in ('public', 'viewer', 'operator', 'publisher', 'admin')),
    phone_e164      text,
    sms_opt_in      integer not null default 0 check (sms_opt_in in (0, 1)),
    sms_opted_in_at text,
    sms_opted_out_at text,
    created_at      text not null,
    disabled        integer not null default 0 check (disabled in (0, 1))
);

-- Sessions: the server stores only a HASH of the token, so a database leak does not hand out
-- live sessions. Expiry is enforced on read, not by a cron job.
create table if not exists sessions (
    token_hash  text primary key,
    user_id     text not null references users(id) on delete cascade,
    created_at  text not null,
    expires_at  text not null
);
create index if not exists sessions_user_idx on sessions (user_id);

-- Consent history: append-only. A withdrawal is recorded as an event, never as a silent
-- overwrite of the original opt-in, so the audit question "did they consent when we sent?"
-- has an answer.
create table if not exists sms_consent_events (
    id          integer primary key autoincrement,
    user_id     text not null references users(id) on delete cascade,
    action      text not null check (action in ('opt_in', 'opt_out')),
    phone_e164  text,
    source      text not null,
    at          text not null
);
create index if not exists consent_user_idx on sms_consent_events (user_id, at);

-- Alerts: draft -> (review) -> send. `status` records what the OPERATOR did; delivery state
-- lives per-recipient in sms_messages, because one alert has many outcomes.
create table if not exists alerts (
    id             text primary key,
    title_en       text not null,
    title_es       text not null,
    body_en        text not null,
    body_es        text not null,
    severity       text not null check (severity in ('info', 'watch', 'warning', 'severe')),
    area           text not null,
    status         text not null check (status in ('draft', 'approved', 'sending', 'sent', 'failed', 'cancelled')),
    is_demo        integer not null default 1 check (is_demo in (0, 1)),
    created_by     text not null references users(id),
    created_at     text not null,
    approved_by    text references users(id),
    approved_at    text,
    sent_at        text,
    -- Dedupe: the same operator must not fire the same alert body twice within the cooldown.
    idempotency_key text
);
create unique index if not exists alerts_idem_idx on alerts (idempotency_key)
    where idempotency_key is not null;

-- One row per recipient per alert: the delivery ledger.
--
-- `state` mirrors the provider's own vocabulary (Pending/Processed/Sent/Delivered/Failed/
-- Cancelled/Cancelling) plus two local values: `dry_run` and `unknown`. `unknown` exists
-- because the provider documents that a message can remain `Sent` even after delivery, so
-- "we do not know" is a real, reportable state and must not be collapsed into success.
create table if not exists sms_messages (
    id             text primary key,
    alert_id       text references alerts(id) on delete cascade,
    user_id        text references users(id) on delete set null,
    phone_e164     text not null,
    body_hash      text not null,
    provider_id    text,
    state          text not null,
    provider_state text,
    error_code     text,
    error_message  text,
    dry_run        integer not null default 0 check (dry_run in (0, 1)),
    created_at     text not null,
    updated_at     text not null
);
create index if not exists sms_messages_alert_idx on sms_messages (alert_id);
create index if not exists sms_messages_phone_idx on sms_messages (phone_e164, created_at);

-- Rate limiting: counted per phone number and per operator, windowed in the query rather than
-- by a scheduler.
create table if not exists sms_rate_events (
    id          integer primary key autoincrement,
    subject     text not null,
    kind        text not null,
    at          text not null
);
create index if not exists rate_subject_idx on sms_rate_events (subject, at);

-- Audit log: append-only, per the approved Stage 2 §2. Never deleted by the application.
create table if not exists audit_log (
    id          integer primary key autoincrement,
    actor_id    text,
    actor_role  text,
    action      text not null,
    subject     text,
    detail      text,
    at          text not null
);
create index if not exists audit_at_idx on audit_log (at);
"""


def db_path() -> Path:
    """Resolved at call time so a test can point `GUARADAR_DB_PATH` at a temp file.

    Defaults to a repository-anchored absolute path, so the CLI and the server always agree no
    matter which directory they were started from.
    """
    return Path(os.environ.get("GUARADAR_DB_PATH", str(DEFAULT_PATH)))


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection with sane pragmas, commit on success, roll back on failure."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("pragma journal_mode = WAL")
        conn.execute("pragma foreign_keys = ON")
        conn.execute("pragma busy_timeout = 10000")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if absent. Safe to call on every start."""
    with connect() as conn:
        conn.executescript(SCHEMA)


def reset_for_tests() -> None:
    """Drop everything. Test-only; never called from application code."""
    path = db_path()
    if path.exists():
        with connect() as conn:
            for table in (
                "audit_log",
                "sms_rate_events",
                "sms_messages",
                "alerts",
                "sms_consent_events",
                "sessions",
                "users",
            ):
                conn.execute(f"drop table if exists {table}")
    init_db()
