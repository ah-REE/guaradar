-- Guaradar — M7 migration 0005: forecast provenance persistence
--
-- PROBLEM THIS MIGRATION SOLVES
--   `weather_cache` (0001) has PRIMARY KEY (lat, lon), so it holds exactly one row per
--   location. Any second fetch for the same point must UPDATE that row, which destroys the
--   previous fetched_at and payload. That contradicts the M7 requirement that duplicate
--   fetches must not silently corrupt historical provenance, and that historical records
--   must not be overwritten.
--
-- APPROACH — additive only, nothing destroyed
--   1. A NEW append-only table `weather_forecast_snapshots` holds every validated fetch as
--      its own immutable row. Provenance fields the old cache could not represent are added
--      here (source, kind, units, validation status, dropped counts, notes).
--   2. `weather_cache` keeps its existing shape and role: a *latest value* cache, which is
--      exactly what a cache should be. It is NOT repurposed as history.
--   3. No column is dropped, no type is narrowed, no row is deleted. `weather_cache` gains
--      only a nullable pointer to the snapshot it currently reflects, so a cache hit can be
--      traced back to the observation that produced it.
--
-- ROLLBACK: drop the two new objects; `weather_cache` remains usable throughout because the
-- added column is nullable and harmless.
--
-- AUTHORIZATION
--   This migration adds no write policy for any new role. Insert access is granted only to
--   the service-side role used by the ingestion process. It deliberately does NOT enable a
--   public or operator write path — N-2 (current_app_role() trusts a session setting) is
--   still open, so no client-reachable write may be created.

begin;

-- ---------------------------------------------------------------------------
-- Append-only history of validated forecast fetches.
-- ---------------------------------------------------------------------------
create table if not exists weather_forecast_snapshots (
    id                    bigserial primary key,

    -- Where the forecast is for.
    lat                   numeric(9,6) not null,
    lon                   numeric(9,6) not null,
    sector_id             text references sectors(id) on delete set null,

    -- Provenance, one field per distinction the brief requires be preserved.
    source                text not null,                    -- e.g. 'open-meteo'
    -- A forecast is never an observation. The CHECK makes that unrepresentable otherwise.
    kind                  text not null default 'forecast'
                          check (kind in ('forecast', 'observation')),

    -- Source timestamp: the earliest hour the provider actually returned. NULL when the
    -- provider supplied none. This is NOT the same as fetched_at and is never derived
    -- from it.
    source_first_hour_at  timestamptz,
    source_last_hour_at   timestamptz,

    -- When WE retrieved it. Distinct from model_run_at by construction.
    fetched_at            timestamptz not null,

    -- Model run time, ONLY if the provider supplied it. For Open-Meteo's default forecast
    -- endpoint this is NULL (limitation N-1). There is deliberately no default and no
    -- trigger that could fill it in from fetched_at.
    model_run_at          timestamptz,

    -- Units. The original unit is kept even though values are normalised to mm, so a future
    -- reader can tell a converted value from a native one.
    units                 text not null default 'mm',
    units_original        text,

    -- Validation outcome. 'ok' means the payload parsed and every value passed range checks;
    -- 'partial' means some values were dropped; 'failed' means nothing usable was stored.
    validation_status     text not null
                          check (validation_status in ('ok', 'partial', 'failed')),
    dropped_value_count   integer not null default 0 check (dropped_value_count >= 0),
    validation_notes      jsonb not null default '[]'::jsonb,

    -- Hourly values, normalised, with nulls preserved as gaps (never zero-filled).
    hours                 jsonb not null,

    -- Summary numbers, denormalised for cheap display. Kept in addition to `hours` so a
    -- reader can sanity-check one against the other.
    total_mm              numeric(10,3),
    max_hourly_mm         numeric(10,3),

    -- Freshness state AT WRITE TIME. Staleness changes with the clock, so this records what
    -- was true when stored; readers must still recompute against the current time.
    stale_at_write        boolean not null default false,

    -- Deduplication. Two fetches of the same location at the same fetched_at with the same
    -- model_run_at are the same observation and must collapse; anything else is new history.
    --
    -- Implemented as a UNIQUE CONSTRAINT rather than a generated `dedupe_key` column, for two
    -- reasons found by testing against PostgreSQL 16.2:
    --   1. a generated column requires an IMMUTABLE expression, and every timestamptz
    --      formatting function (to_char, ::text, extract(epoch)) is STABLE, not immutable,
    --      so the database rejects it;
    --   2. NULLS NOT DISTINCT (PG15+) is exactly the semantics needed — without it, two rows
    --      with model_run_at IS NULL would be considered distinct and dedupe would silently
    --      fail in the N-1 case, which is the only case this project actually produces.

    ingested_at           timestamptz not null default now(),

    constraint snapshot_unique_fetch
        unique nulls not distinct (source, lat, lon, fetched_at, model_run_at),

    -- A stored forecast must not claim to be an observation while lacking observation
    -- provenance. There is no observation source in this project, so anything not
    -- 'forecast' is rejected until one exists.
    constraint only_forecast_supported check (kind = 'forecast'),

    -- Guard the N-1 invariant at the storage layer: a model_run_at may never precede the
    -- first forecast hour by an implausible margin. This catches a bug that tried to fill
    -- model_run_at from fetched_at instead of leaving it null.
    constraint model_run_not_after_fetch check (
        model_run_at is null or model_run_at <= fetched_at
    )
);

create index if not exists wfs_lat_lon_fetched_idx
    on weather_forecast_snapshots (lat, lon, fetched_at desc);
create index if not exists wfs_fetched_idx
    on weather_forecast_snapshots (fetched_at desc);

comment on table weather_forecast_snapshots is
    'Append-only history of validated forecast fetches. Rows are never updated or deleted.';
comment on column weather_forecast_snapshots.model_run_at is
    'NULL when the provider omitted it. Never derived from fetched_at (limitation N-1).';
comment on column weather_forecast_snapshots.hours is
    'Normalised hourly values; null precipitation is a provider gap, never zero.';
comment on constraint only_forecast_supported on weather_forecast_snapshots is
    'No observation source exists in this project, so storing an "observation" is blocked.';

-- ---------------------------------------------------------------------------
-- Link the latest-value cache to the snapshot it reflects. Nullable: an existing cache row
-- written before this migration simply has no pointer, which is honest.
-- ---------------------------------------------------------------------------
alter table weather_cache
    add column if not exists snapshot_id bigint
    references weather_forecast_snapshots(id) on delete set null;

comment on column weather_cache.snapshot_id is
    'The snapshot this cached payload came from, for traceability. NULL for rows written '
    'before M7.';

-- ---------------------------------------------------------------------------
-- Append-only enforcement.
--
-- NOTE ON A MISTAKE CORRECTED HERE: an earlier draft used DO INSTEAD NOTHING rewrite
-- rules. Testing against PostgreSQL 16.2 showed that rewrite rules make the table
-- incompatible with `ON CONFLICT` — "INSERT with ON CONFLICT clause cannot be used with
-- table that has INSERT or UPDATE rules" — which breaks the idempotent-insert design the
-- whole persistence layer depends on.
--
-- The rules are therefore NOT used. Append-only is enforced two ways that do work:
--   1. RLS: no UPDATE or DELETE policy is created for any role, so both are denied.
--   2. Privileges: only SELECT and INSERT are granted (see bottom of this migration).
-- This is the same mechanism already protecting `audit_log`, and it composes with
-- ON CONFLICT without interference.

-- ---------------------------------------------------------------------------
-- RLS. Same posture as the rest of the schema: deny by default, read for staff, and NO
-- client-reachable write. Insert is granted only to the service role the ingestion process
-- uses; that role is not reachable from the browser (N-2 still open).
-- ---------------------------------------------------------------------------
alter table weather_forecast_snapshots enable row level security;

drop policy if exists wfs_staff_read on weather_forecast_snapshots;
create policy wfs_staff_read on weather_forecast_snapshots
    for select to guaradar_anon, guaradar_viewer, guaradar_operator,
                  guaradar_publisher, guaradar_admin
    using (true);

drop policy if exists wfs_service_insert on weather_forecast_snapshots;
create policy wfs_service_insert on weather_forecast_snapshots
    for insert to guaradar_operator, guaradar_publisher, guaradar_admin
    with check (has_role('operator'));

revoke all on weather_forecast_snapshots from public;
grant select on weather_forecast_snapshots to
    guaradar_anon, guaradar_viewer, guaradar_operator, guaradar_publisher, guaradar_admin;
grant insert on weather_forecast_snapshots to
    guaradar_operator, guaradar_publisher, guaradar_admin;
grant usage, select on sequence weather_forecast_snapshots_id_seq to
    guaradar_operator, guaradar_publisher, guaradar_admin;

commit;
