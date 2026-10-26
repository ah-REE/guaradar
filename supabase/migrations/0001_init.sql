-- Guaradar — M1 migration 0001: core schema
--
-- Design notes
--  * No PostGIS available on the local verification host, so geometry is stored as
--    numeric lat/lon plus a JSONB polyline. This is the fallback already recorded in
--    Stage 4 §16.2 block 1. If PostGIS is available in the target Supabase project,
--    geometry columns can be added later WITHOUT changing the semantics here.
--  * Every table carries an explicit provenance story: either a `simulated` flag,
--    a `source` column, or both. Nothing is presented as a verified real observation
--    unless it was set by an administrator and carries a timestamp.
--  * `road_status` is keyed 1:1 to `road_segments` so there is exactly one source of
--    truth for road state (approved Stage 2 §12 mechanism 1).
--  * `audit_log` is append-only: no UPDATE/DELETE policies are defined for it.

begin;

-- ---------------------------------------------------------------------------
-- Sectors: the unit the public app groups by.
-- ---------------------------------------------------------------------------
create table if not exists sectors (
    id              text primary key,
    name_en         text not null,
    name_es         text not null,
    -- Coarse static vulnerability weight, set by an administrator. Never a live signal.
    exposure_weight numeric not null default 1.0
                    check (exposure_weight > 0 and exposure_weight <= 10),
    center_lat      numeric(9,6) not null,
    center_lon      numeric(9,6) not null,
    created_at      timestamptz not null default now()
);

comment on column sectors.exposure_weight is
  'Relative exposure of the sector, chosen by an operator. Not derived from data.';

-- ---------------------------------------------------------------------------
-- Road segments: topology comes from OSM, elevation is static context only (D12).
-- ---------------------------------------------------------------------------
create table if not exists road_segments (
    id              bigint primary key,
    osm_way_id      bigint,
    name            text,
    road_class      text not null,
    sector_id       text references sectors(id) on delete set null,
    geom_latlon     jsonb not null,          -- [[lat,lon], ...] polyline
    length_m        numeric not null check (length_m > 0),
    -- D12: approximate static context. May NOT rank streets or predict depth.
    elevation_m     numeric,
    elevation_source text check (elevation_source in ('SRTM1') or elevation_source is null),
    osm_timestamp   timestamptz,             -- timestamp_osm_base of the extract
    created_at      timestamptz not null default now()
);

create index if not exists road_segments_sector_idx on road_segments (sector_id);
create index if not exists road_segments_class_idx  on road_segments (road_class);

comment on column road_segments.elevation_m is
  'Approximate (SRTM 30 m, +/-4 m). Static context only. Must never be used to rank '
  'streets, predict water depth, or act as a live signal (decision D12).';

-- ---------------------------------------------------------------------------
-- Road status: exactly one row per segment. This is the single source of truth.
-- ---------------------------------------------------------------------------
create table if not exists road_status (
    road_segment_id bigint primary key
                    references road_segments(id) on delete cascade,
    status          text not null
                    check (status in ('open','affected','closed','unknown')),
    depth_band      text
                    check (depth_band in ('<15','15-40','40-80','>80','unknown')),
    reason          text,
    evidence_url    text,
    source          text not null default 'operator'
                    check (source in ('operator','system','report','seed')),
    set_by          uuid,
    set_at          timestamptz not null default now(),
    -- When this claim must be re-checked. On lapse the public chip flips to Stale
    -- automatically, so nobody has to remember to un-close a road at 3am.
    review_at       timestamptz,
    constraint closed_needs_reason
        check (status <> 'closed' or (reason is not null and length(btrim(reason)) > 0))
);

create index if not exists road_status_review_idx on road_status (review_at);
create index if not exists road_status_status_idx on road_status (status);

comment on table road_status is
  'One row per road segment. The public app never keeps a second copy of road state.';

-- ---------------------------------------------------------------------------
-- Sensors: all simulated in this project (D28). `simulated` defaults true at the
-- database level so a future real sensor must explicitly opt out of the honest path.
-- ---------------------------------------------------------------------------
create table if not exists sensors (
    id                  text primary key,
    name                text not null,
    sector_id           text not null references sectors(id) on delete restrict,
    lat                 numeric(9,6) not null,
    lon                 numeric(9,6) not null,
    threshold_m         numeric not null check (threshold_m > 0),
    expected_interval_s integer not null default 60 check (expected_interval_s > 0),
    stale_after_s       integer not null default 300 check (stale_after_s > 0),
    simulated           boolean not null default true,
    created_at          timestamptz not null default now()
);

comment on column sensors.threshold_m is
  'Prototype value (decision D28). Not a real municipal flood threshold.';

comment on column sensors.simulated is
  'Defaults true. Every sensor in this project is simulated and must be labelled so.';

create index if not exists sensors_sector_idx on sensors (sector_id);

-- ---------------------------------------------------------------------------
-- Sensor readings: append-only time series. Gaps are drawn as gaps, never filled.
-- ---------------------------------------------------------------------------
create table if not exists sensor_readings (
    id          bigserial primary key,
    sensor_id   text not null references sensors(id) on delete cascade,
    depth_m     numeric not null check (depth_m >= 0),
    observed_at timestamptz not null,
    ingested_at timestamptz not null default now(),
    quality     smallint not null default 0 check (quality in (0,1)),
    simulated   boolean not null default true,
    unique (sensor_id, observed_at)
);

create index if not exists sensor_readings_sensor_time_idx
    on sensor_readings (sensor_id, observed_at desc);

-- ---------------------------------------------------------------------------
-- Alerts: full lifecycle, bilingual body required before publication (D26).
-- ---------------------------------------------------------------------------
create table if not exists alerts (
    id              uuid primary key default gen_random_uuid(),
    severity        smallint not null check (severity between 1 and 4),
    headline_en     text not null,
    headline_es     text,
    body_en         text not null,
    body_es         text,
    instructions_en text,
    instructions_es text,
    starts_at       timestamptz not null,
    ends_at         timestamptz not null,
    status          text not null default 'draft'
                    check (status in ('draft','review','published','expired')),
    source_basis    text[] not null default '{}',
    created_by      uuid,
    published_by    uuid,
    published_at    timestamptz,
    version         integer not null default 1,
    created_at      timestamptz not null default now(),
    constraint alert_window_ordered check (ends_at > starts_at),
    -- D26: an alert may not be PUBLISHED unless both languages are present.
    -- Drafts may be incomplete; publication may not.
    constraint published_requires_bilingual check (
        status <> 'published'
        or (headline_es is not null and length(btrim(headline_es)) > 0
            and body_es is not null and length(btrim(body_es)) > 0
            and published_by is not null
            and published_at is not null)
    )
);

create index if not exists alerts_status_time_idx on alerts (status, starts_at, ends_at);

comment on constraint published_requires_bilingual on alerts is
  'Decision D26: the bilingual publishing block is enforced in the database, not only in the UI.';

create table if not exists alert_sectors (
    alert_id  uuid not null references alerts(id) on delete cascade,
    sector_id text not null references sectors(id) on delete cascade,
    primary key (alert_id, sector_id)
);

create table if not exists alert_versions (
    id         bigserial primary key,
    alert_id   uuid not null references alerts(id) on delete cascade,
    snapshot   jsonb not null,
    changed_by uuid,
    changed_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Incidents: anonymous citizen reports. No PII. Opaque reporter code only.
-- ---------------------------------------------------------------------------
create table if not exists incidents (
    id            uuid primary key default gen_random_uuid(),
    lat           numeric(9,6) not null,
    lon           numeric(9,6) not null,
    accuracy_m    numeric check (accuracy_m is null or accuracy_m >= 0),
    depth_band    text check (depth_band in ('<15','15-40','40-80','>80','unknown')),
    description   text check (description is null or length(description) <= 280),
    photo_path    text,
    capture_at    timestamptz,          -- when the photo/observation was taken
    submitted_at  timestamptz not null default now(),  -- when it reached us
    status        text not null default 'pending'
                  check (status in ('pending','verified','rejected','duplicate')),
    reviewed_by   uuid,
    reviewed_at   timestamptz,
    review_note   text,
    -- Opaque reference so a reporter can check status without an account.
    reporter_code text not null,
    duplicate_of  uuid references incidents(id) on delete set null,
    -- Seed/demo rows are marked so they are never mistaken for live reports.
    seeded        boolean not null default false,
    constraint review_requires_reviewer check (
        status = 'pending' or (reviewed_by is not null and reviewed_at is not null)
    )
);

create index if not exists incidents_status_time_idx on incidents (status, submitted_at desc);
create index if not exists incidents_reporter_code_idx on incidents (reporter_code);

comment on column incidents.seeded is
  'True for synthetic demonstration reports. Must never be shown as verified field data.';

-- ---------------------------------------------------------------------------
-- Shelters: administrator-curated. "Open" is time-boxed so it cannot silently persist.
-- ---------------------------------------------------------------------------
create table if not exists shelters (
    id                uuid primary key default gen_random_uuid(),
    name              text not null,
    type              text not null check (type in ('shelter','hospital','fire','police')),
    lat               numeric(9,6) not null,
    lon               numeric(9,6) not null,
    address           text,
    phone             text,
    capacity          integer check (capacity is null or capacity >= 0),
    accessibility     text[] not null default '{}',
    status            text not null default 'unverified'
                      check (status in ('open','unverified','full','closed','no_data')),
    -- After this instant the status falls back to 'unverified' automatically.
    status_hold_until timestamptz,
    -- The brief requires VERIFIED DESIGNATED zones. This field is where that claim is earned.
    authorised_source text,
    updated_by        uuid,
    updated_at        timestamptz not null default now(),
    constraint open_requires_hold check (
        status <> 'open' or status_hold_until is not null
    )
);

create index if not exists shelters_type_idx on shelters (type);

comment on column shelters.authorised_source is
  'Who designated this as a safe zone. Without it, a record must not be presented as verified.';

-- ---------------------------------------------------------------------------
-- Audit log: append-only. No UPDATE/DELETE policy is created for any role.
-- ---------------------------------------------------------------------------
create table if not exists audit_log (
    id           bigserial primary key,
    actor        uuid,
    action       text not null,
    target_table text not null,
    target_id    text,
    before       jsonb,
    after        jsonb,
    reason       text,
    at           timestamptz not null default now()
);

create index if not exists audit_log_at_idx on audit_log (at desc);
create index if not exists audit_log_target_idx on audit_log (target_table, target_id);

-- Refuse to let anyone rewrite history, even the owner of the table.
create or replace rule audit_log_no_update as on update to audit_log do instead nothing;
create or replace rule audit_log_no_delete as on delete to audit_log do instead nothing;

comment on rule audit_log_no_update on audit_log is
  'Append-only enforcement: updates are silently discarded, not applied.';

-- ---------------------------------------------------------------------------
-- Ingested reference data: INAMHI bulletins are entered by a human, never scraped.
-- ---------------------------------------------------------------------------
create table if not exists inamhi_bulletins (
    id         bigserial primary key,
    issued_at  timestamptz not null,     -- the bulletin's own date, not our fetch time
    headline   text not null,
    url        text,
    entered_by uuid,
    entered_at timestamptz not null default now()
);

-- Cached upstream payloads, so a stale answer can still be served with its true age.
create table if not exists weather_cache (
    lat          numeric(9,6) not null,
    lon          numeric(9,6) not null,
    fetched_at   timestamptz not null,
    model_run_at timestamptz,
    payload      jsonb not null,
    primary key (lat, lon)
);

create table if not exists river_cache (
    river_id     bigint primary key,
    fetched_at   timestamptz not null,
    model_run_at timestamptz,
    payload      jsonb not null
);

commit;
