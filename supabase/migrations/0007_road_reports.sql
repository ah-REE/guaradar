-- Guaradar — M15 migration 0007: community road reports
--
-- PURPOSE
--   Persist citizen road reports, their sanitised images, community corroboration, operator
--   decisions and an append-only audit trail.
--
-- WHAT IS DELIBERATELY NOT HERE
--   * **No `stale` status.** Staleness is derived from `expires_at` at read time (see
--     backend/app/reports/lifecycle.py). Storing it would mean a job has to rewrite `decision`
--     as evidence ages, and every such rewrite is a chance to write "passable" over a closure.
--     Requirement D.3 is enforced by the absence of that column.
--   * **No second source of truth for road status.** `road_status` remains authoritative for
--     what the router consumes. This migration does not add a competing column; the effective
--     status is derived in code and applied to `road_status` through the existing repository
--     path. A duplicate would eventually disagree with itself.
--   * **No deletion semantics.** Rejection is a decision, not a DELETE. The audit table is
--     append-only and nothing in the application issues UPDATE or DELETE against it.
--
-- EPHEMERAL-DISK WARNING (Render free web service)
--   Image bytes live in the database on purpose, because the intended host has an EPHEMERAL
--   filesystem: anything written to ./uploads or /tmp disappears on restart, spin-down or
--   redeploy. Storing bytes here is only durable if this database is a real managed PostgreSQL
--   instance. With the SQLite prototype store, both the rows AND the images vanish with the
--   disk. See docs/ROAD-REPORTS-EVIDENCE.md.
--
-- ROLLBACK
--   drop table report_rate_events, report_audit, report_confirmations, report_images,
--   road_reports;  (in that order — children first). No existing table is altered, so nothing
--   else is affected.

begin;

-- ---------------------------------------------------------------------------
-- Reports
-- ---------------------------------------------------------------------------
create table if not exists road_reports (
    id                  uuid primary key default gen_random_uuid(),
    -- The submitter. Kept for duplicate detection and abuse handling, never published.
    -- NOTE: no foreign key yet. These migrations contain NO users table — identity in the
    -- prototype lives in SQLite, and 0002_rls.sql only notes that Supabase would derive a
    -- role from auth.uid(). Referencing a table that does not exist would make this
    -- migration fail on first apply, so the constraint is added conditionally at the end
    -- of the file, only when an identity table is present.
    user_id             uuid not null,

    category            text not null
                        check (category in ('flooded', 'blocked', 'debris', 'damaged',
                                            'rising', 'other')),
    description         text check (description is null or length(description) <= 280),

    -- Raw submitter position. ADMIN-ONLY. Public endpoints must never select these columns.
    gps_lat             double precision not null check (gps_lat between -90 and 90),
    gps_lon             double precision not null check (gps_lon between -180 and 180),
    gps_accuracy_m      double precision check (gps_accuracy_m is null or gps_accuracy_m >= 0),
    gps_source          text not null check (gps_source in ('device', 'manual', 'map')),

    -- Snapping result. NULL means the pin was too far from any road: recorded honestly rather
    -- than assigning the nearest road anyway.
    road_segment_id     bigint,
    snap_distance_m     double precision check (snap_distance_m is null or snap_distance_m >= 0),

    -- What the public map may show. The snapped road point when matched, otherwise a coarsened
    -- cell centre. Separate columns so "publish this" is a different query from "review this".
    public_lat          double precision not null check (public_lat between -90 and 90),
    public_lon          double precision not null check (public_lon between -180 and 180),
    public_is_snapped   boolean not null default false,

    -- Operator decision. 'unverified' is the only value a submitter can cause. `stale` is
    -- absent by design; see the header.
    decision            text not null default 'unverified'
                        check (decision in ('unverified', 'potential_hazard',
                                            'blocked_verified', 'passable_verified',
                                            'inconclusive', 'rejected')),
    decided_by          uuid,
    decided_at          timestamptz,
    decision_note       text check (decision_note is null or length(decision_note) <= 500),

    submitted_at        timestamptz not null default now(),
    verified_at         timestamptz,
    last_confirmed_at   timestamptz,
    -- The ONLY source of staleness.
    expires_at          timestamptz not null,
    -- The policy in force when the row was written, so a later config change cannot silently
    -- reinterpret a historical deadline.
    stale_after_minutes integer not null check (stale_after_minutes > 0),

    seeded              boolean not null default false,

    constraint report_decision_needs_actor check (
        decision = 'unverified' or (decided_by is not null and decided_at is not null)),
    -- An expiry before submission would make the report born stale.
    constraint report_expiry_after_submission check (expires_at >= submitted_at),
    -- A verification dated after the expiry it precedes is not a reachable state.
    constraint report_verified_before_expiry check (
        verified_at is null or verified_at <= expires_at)
);

comment on column road_reports.gps_lat is
    'Raw submitter latitude. ADMIN-ONLY. Never selected by a public endpoint.';
comment on column road_reports.decision is
    'Operator decision only. Staleness is DERIVED from expires_at and is never stored here.';
comment on column road_reports.road_segment_id is
    'Graph edge id (osm_way_id * 1000 + segment_ordinal). NULL means no confident road match.';

create index if not exists reports_segment_idx  on road_reports (road_segment_id);
create index if not exists reports_decision_idx on road_reports (decision, submitted_at desc);
create index if not exists reports_time_idx     on road_reports (submitted_at desc);
create index if not exists reports_bbox_idx     on road_reports (public_lat, public_lon);
create index if not exists reports_user_idx     on road_reports (user_id, submitted_at desc);
create index if not exists reports_expiry_idx   on road_reports (expires_at);

-- One sanitised image per report. BYTEA rather than a file path: the intended host's disk is
-- ephemeral, so a path would be a dangling reference within hours.
create table if not exists report_images (
    report_id           uuid primary key references road_reports(id) on delete cascade,
    content_type        text not null
                        check (content_type in ('image/jpeg', 'image/png', 'image/webp')),
    bytes_blob          bytea not null,
    width               integer not null check (width > 0),
    height              integer not null check (height > 0),
    byte_size           integer not null check (byte_size > 0),
    sha256              text not null,
    -- Always true: the pipeline re-encodes from decoded pixels, so EXIF and its embedded GPS
    -- cannot survive. The flag exists so the guarantee is visible in the schema and auditable.
    metadata_stripped   boolean not null default true,
    created_at          timestamptz not null default now(),
    -- A single row per report, and a size ceiling at the database level so a miscoded path
    -- cannot store an unbounded blob.
    constraint report_image_size_limit check (byte_size <= 5 * 1024 * 1024)
);

comment on table report_images is
    'Sanitised, re-encoded image bytes. Durable only if this database is durable; on a '
    'SQLite-backed deployment these disappear with the ephemeral disk.';

-- Community corroboration. Evidence, never authority: nothing here can change `decision`.
create table if not exists report_confirmations (
    id          bigserial primary key,
    report_id   uuid not null references road_reports(id) on delete cascade,
    user_id     uuid not null,  -- see the note on road_reports.user_id
    kind        text not null check (kind in ('confirm', 'challenge')),
    at          timestamptz not null default now(),
    -- "Prevent repeated voting by the same user on the same report", enforced by the database
    -- rather than by a check-then-insert, so two concurrent taps cannot both succeed.
    constraint report_confirmation_once unique (report_id, user_id)
);

create index if not exists confirmations_report_idx on report_confirmations (report_id, at);

-- Append-only. No UPDATE or DELETE is issued against this table by the application, which is
-- what makes "preserve the history rather than permanently deleting the evidence" true.
create table if not exists report_audit (
    id          bigserial primary key,
    report_id   uuid not null,
    action      text not null,
    actor_id    uuid,
    actor_role  text,
    from_state  text,
    to_state    text,
    detail      text,
    at          timestamptz not null default now()
);

create index if not exists report_audit_report_idx on report_audit (report_id, at);

-- Submission throttling, windowed by query rather than by a scheduler.
create table if not exists report_rate_events (
    id        bigserial primary key,
    subject   text not null,
    kind      text not null,
    at        timestamptz not null default now()
);

create index if not exists report_rate_subject_idx on report_rate_events (subject, at);

-- ---------------------------------------------------------------------------
-- Conditional identity foreign keys
--
-- WHY CONDITIONAL
--   This repository's PostgreSQL schema does not yet contain an application users table:
--   `0002_rls.sql` records that Supabase would derive the role from `auth.uid()`, and the
--   working identity store is the SQLite prototype (`app/store.py`). A plain
--   `references users(id)` would therefore fail on a clean apply, and `references
--   auth_users(id)` references something that has never existed here.
--
--   So the constraints are attached only when an identity table is actually present. This
--   keeps the migration applicable today (against a schema with no users table) AND correct
--   later (against Supabase, where it will find `auth.users`). `user_id` stays NOT NULL either
--   way, so an orphan row cannot be created by omitting the column.
--
--   Recorded as an open item rather than papered over: the deployed SQLite store enforces this
--   with a real FK, and `docs/ROAD-REPORTS-EVIDENCE.md` lists the PostgreSQL path as untested
--   because no server was available.
-- ---------------------------------------------------------------------------
do $$
declare
    identity_table text;
begin
    select c.table_schema || '.' || c.table_name
      into identity_table
      from information_schema.tables c
     where c.table_type = 'BASE TABLE'
       and (
            (c.table_schema = 'public' and c.table_name = 'users')
         or (c.table_schema = 'auth'   and c.table_name = 'users')
       )
     limit 1;

    if identity_table is null then
        raise notice
            'road_reports.user_id has no foreign key: no identity table found. '
            'Re-run this block after the identity schema exists.';
        return;
    end if;

    execute format(
        'alter table road_reports add constraint road_reports_user_fk '
        'foreign key (user_id) references %s(id) on delete cascade', identity_table);
    execute format(
        'alter table road_reports add constraint road_reports_decided_by_fk '
        'foreign key (decided_by) references %s(id)', identity_table);
    execute format(
        'alter table report_confirmations add constraint report_confirmations_user_fk '
        'foreign key (user_id) references %s(id) on delete cascade', identity_table);

    raise notice 'attached report identity foreign keys to %', identity_table;
end $$;

commit;
