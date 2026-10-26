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

-- ===========================================================================
-- Community road reports (features A-E)
--
-- STATUS MODEL — read this before changing anything here.
--
--   `decision` stores ONLY what an operator decided, or that nobody has decided.
--   `stale` is DELIBERATELY NOT a stored value. It is derived from `expires_at` at read
--   time (see app/reports/lifecycle.py). That is what makes requirement D.3 structural
--   rather than a rule somebody has to remember:
--
--     "Expiration must never automatically turn a blocked road into a confirmed safe road."
--
--   If `stale` were a stored status, a timer or a cron job would have to rewrite `decision`
--   from 'blocked_verified' to something else, and every such rewrite is an opportunity to
--   write 'passable'. Deriving staleness instead means an expired closure still closes its
--   edge; it loses only its freshness claim. The two are different questions and they are
--   answered in different places on purpose.
--
-- LOCATION PRIVACY
--   `gps_lat`/`gps_lon` are the submitter's raw coordinates and are ADMIN-ONLY. The public
--   endpoints never read them. `public_lat`/`public_lon` are the snapped road point when the
--   report matched a segment, otherwise a deliberately coarsened (rounded) coordinate. Keeping
--   both columns means the raw position is available for review without ever being served.
-- ===========================================================================
create table if not exists road_reports (
    id                text primary key,
    user_id           text not null references users(id) on delete cascade,
    category          text not null check (category in (
                          'flooded', 'blocked', 'debris', 'damaged', 'rising', 'other')),
    description       text,
    -- Raw submitter position. Never served on a public endpoint.
    gps_lat           real not null check (gps_lat between -90 and 90),
    gps_lon           real not null check (gps_lon between -180 and 180),
    gps_accuracy_m    real check (gps_accuracy_m is null or gps_accuracy_m >= 0),
    gps_source        text not null check (gps_source in ('device', 'manual', 'map')),
    -- Snapping result. NULL edge_id means the pin was too far from any road; that is
    -- recorded honestly rather than assigning the nearest road anyway.
    road_segment_id   integer,
    snap_distance_m   real check (snap_distance_m is null or snap_distance_m >= 0),
    -- What the public map may show.
    public_lat        real not null check (public_lat between -90 and 90),
    public_lon        real not null check (public_lon between -180 and 180),
    public_is_snapped integer not null default 0 check (public_is_snapped in (0, 1)),
    -- Operator decision. 'unverified' is the only value a submitter can produce.
    decision          text not null default 'unverified' check (decision in (
                          'unverified', 'potential_hazard', 'blocked_verified',
                          'passable_verified', 'inconclusive', 'rejected')),
    decided_by        text references users(id),
    decided_at        text,
    decision_note     text,
    -- Lifecycle timestamps, all UTC.
    submitted_at      text not null,
    verified_at       text,
    last_confirmed_at text,
    -- Freshness deadline. The ONLY source of staleness; there is no `stale` column.
    expires_at        text not null,
    -- Stale-threshold minutes in force when the row was written, so a later policy change
    -- cannot silently reinterpret a historical deadline.
    stale_after_minutes integer not null check (stale_after_minutes > 0),
    seeded            integer not null default 0 check (seeded in (0, 1)),
    -- Admin decision must be attributable.
    constraint report_decision_needs_actor check (
        decision = 'unverified' or (decided_by is not null and decided_at is not null))
);
create index if not exists reports_segment_idx on road_reports (road_segment_id);
create index if not exists reports_decision_idx on road_reports (decision, submitted_at desc);
create index if not exists reports_time_idx on road_reports (submitted_at desc);
create index if not exists reports_bbox_idx on road_reports (public_lat, public_lon);
create index if not exists reports_user_idx on road_reports (user_id, submitted_at desc);
create index if not exists reports_expiry_idx on road_reports (expires_at);

-- One sanitised image per report. Bytes live here rather than on disk because the intended
-- deployment (Render free web service) has an EPHEMERAL filesystem. Storage in the database
-- survives a restart; a file under /tmp or ./uploads does not.
--
-- This is NOT durable on Render while the runtime database is SQLite, because that SQLite
-- file is itself on the ephemeral disk. See docs/ROAD-REPORTS-EVIDENCE.md.
create table if not exists report_images (
    report_id     text primary key references road_reports(id) on delete cascade,
    content_type  text not null check (content_type in ('image/jpeg', 'image/png', 'image/webp')),
    bytes_blob    blob not null,
    width         integer not null check (width > 0),
    height        integer not null check (height > 0),
    byte_size     integer not null check (byte_size > 0),
    sha256        text not null,
    -- Always 1: the pipeline re-encodes from pixels, so EXIF and its embedded GPS are gone.
    metadata_stripped integer not null default 1 check (metadata_stripped = 1),
    created_at    text not null
);

-- Community corroboration. Its purpose is EVIDENCE, never authority: nothing in this table
-- can change `decision`. The unique constraint is the database-level enforcement of
-- "prevent repeated voting by the same user on the same report", so a race between two
-- requests cannot slip a duplicate through.
create table if not exists report_confirmations (
    id          integer primary key autoincrement,
    report_id   text not null references road_reports(id) on delete cascade,
    user_id     text not null references users(id) on delete cascade,
    kind        text not null check (kind in ('confirm', 'challenge')),
    at          text not null,
    unique (report_id, user_id)
);
create index if not exists confirmations_report_idx on report_confirmations (report_id, at);

-- Append-only history for every report. Never updated, never deleted by the application, so
-- a rejected or obsolete report keeps its audit trail instead of vanishing.
create table if not exists report_audit (
    id          integer primary key autoincrement,
    report_id   text not null,
    action      text not null,
    actor_id    text,
    actor_role  text,
    from_state  text,
    to_state    text,
    detail      text,
    at          text not null
);
create index if not exists report_audit_report_idx on report_audit (report_id, at);

-- Submission throttling, counted in a windowing query rather than by a scheduler.
create table if not exists report_rate_events (
    id        integer primary key autoincrement,
    subject   text not null,
    kind      text not null,
    at        text not null
);
create index if not exists report_rate_subject_idx on report_rate_events (subject, at);
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
            # Child tables first: foreign keys are ON, so a parent dropped ahead of its
            # children would raise instead of cascading.
            for table in (
                "report_rate_events",
                "report_audit",
                "report_confirmations",
                "report_images",
                "road_reports",
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
