-- Guaradar — M1 migration 0002: roles, authorization, and Row-Level Security
--
-- This migration is security-sensitive. Every policy below is written to be VERIFIED
-- by a test in migration 0004. A policy that cannot be tested is not trusted here.
--
-- Model (from approved Stage 2 §2):
--   viewer    read-only dashboards
--   operator  verify incidents, set road status, manage shelters, draft alerts
--   publisher operator + publish/expire alerts
--   admin     everything except rewriting the audit log
--
-- Two deliberate choices:
--   1. RLS is ENABLED on every table that holds operational or personal data. Because
--      enabling RLS without policies denies everything, each table gets explicit
--      policies — none is left to "default sane behaviour", which does not exist.
--   2. The public (anon) role may read ONLY published, unexpired alerts, road status,
--      shelters, sectors and sensor readings. It may NEVER read pending incident
--      photos or any audit data.

begin;

-- ---------------------------------------------------------------------------
-- Roles mirroring Supabase's auth roles plus our own authorization roles.
-- ---------------------------------------------------------------------------
do $$ begin
    if not exists (select 1 from pg_roles where rolname = 'guaradar_anon') then
        create role guaradar_anon nologin;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'guaradar_viewer') then
        create role guaradar_viewer nologin;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'guaradar_operator') then
        create role guaradar_operator nologin;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'guaradar_publisher') then
        create role guaradar_publisher nologin;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'guaradar_admin') then
        create role guaradar_admin nologin;
    end if;
end $$;

grant usage on schema public to
    guaradar_anon, guaradar_viewer, guaradar_operator, guaradar_publisher, guaradar_admin;

-- ---------------------------------------------------------------------------
-- Which admin role does the current session hold?
-- On Supabase this reads from a user_roles table keyed by auth.uid(). Here we expose
-- a single function so the expression appears in exactly one place and can be
-- replaced without touching policies.
-- ---------------------------------------------------------------------------
create or replace function current_app_role()
returns text
language sql
stable
as $$
    -- session_setting is intentionally explicit: the application must set it after
    -- authenticating. It is NOT trusted from the client in production; the Stage 5
    -- implementation must derive it server-side from the verified JWT.
    select coalesce(nullif(current_setting('guaradar.role', true), ''), 'anon')
$$;

create or replace function is_staff()
returns boolean
language sql
stable
as $$ select current_app_role() in ('viewer','operator','publisher','admin') $$;

create or replace function has_role(minimum text)
returns boolean
language sql
stable
as $$
    select case current_app_role()
        when 'admin'     then true
        when 'publisher' then minimum in ('viewer','operator','publisher')
        when 'operator'  then minimum in ('viewer','operator')
        when 'viewer'    then minimum = 'viewer'
        else false
    end
$$;

-- ---------------------------------------------------------------------------
-- Enable RLS everywhere. Deny-by-default is the baseline; policies grant exceptions.
-- ---------------------------------------------------------------------------
alter table sectors             enable row level security;
alter table road_segments       enable row level security;
alter table road_status         enable row level security;
alter table sensors             enable row level security;
alter table sensor_readings     enable row level security;
alter table alerts              enable row level security;
alter table alert_sectors       enable row level security;
alter table alert_versions      enable row level security;
alter table incidents           enable row level security;
alter table shelters            enable row level security;
alter table audit_log           enable row level security;
alter table inamhi_bulletins    enable row level security;
alter table weather_cache       enable row level security;
alter table river_cache         enable row level security;

-- ===========================================================================
-- PUBLIC READ (anon + any staff role)
-- ===========================================================================

drop policy if exists sectors_public_read on sectors;
create policy sectors_public_read on sectors
    for select to guaradar_anon, guaradar_viewer, guaradar_operator, guaradar_publisher, guaradar_admin
    using (true);

drop policy if exists road_segments_public_read on road_segments;
create policy road_segments_public_read on road_segments
    for select to guaradar_anon, guaradar_viewer, guaradar_operator, guaradar_publisher, guaradar_admin
    using (true);

drop policy if exists road_status_public_read on road_status;
create policy road_status_public_read on road_status
    for select to guaradar_anon, guaradar_viewer, guaradar_operator, guaradar_publisher, guaradar_admin
    using (true);

drop policy if exists sensors_public_read on sensors;
create policy sensors_public_read on sensors
    for select to guaradar_anon, guaradar_viewer, guaradar_operator, guaradar_publisher, guaradar_admin
    using (true);

drop policy if exists sensor_readings_public_read on sensor_readings;
create policy sensor_readings_public_read on sensor_readings
    for select to guaradar_anon, guaradar_viewer, guaradar_operator, guaradar_publisher, guaradar_admin
    using (true);

-- Alerts: the public sees ONLY published alerts that have not yet ended.
-- Drafts and expired alerts are invisible to anon. This is the mechanism that keeps
-- an unpublished instruction from reaching a citizen.
drop policy if exists alerts_public_read_published on alerts;
create policy alerts_public_read_published on alerts
    for select to guaradar_anon
    using (status = 'published' and now() between starts_at and ends_at);

drop policy if exists alerts_staff_read on alerts;
create policy alerts_staff_read on alerts
    for select to guaradar_viewer, guaradar_operator, guaradar_publisher, guaradar_admin
    using (true);

drop policy if exists alert_sectors_public_read on alert_sectors;
create policy alert_sectors_public_read on alert_sectors
    for select to guaradar_anon, guaradar_viewer, guaradar_operator, guaradar_publisher, guaradar_admin
    using (
        exists (
            select 1 from alerts a
            where a.id = alert_sectors.alert_id
              and (
                  has_role('viewer')
                  or (a.status = 'published' and now() between a.starts_at and a.ends_at)
              )
        )
    );

-- Incident photos on PENDING reports are never public. Only verified reports surface.
drop policy if exists incidents_public_read_verified on incidents;
create policy incidents_public_read_verified on incidents
    for select to guaradar_anon
    using (status = 'verified');

drop policy if exists incidents_staff_read on incidents;
create policy incidents_staff_read on incidents
    for select to guaradar_viewer, guaradar_operator, guaradar_publisher, guaradar_admin
    using (true);

drop policy if exists shelters_public_read on shelters;
create policy shelters_public_read on shelters
    for select to guaradar_anon, guaradar_viewer, guaradar_operator, guaradar_publisher, guaradar_admin
    using (true);

drop policy if exists inamhi_public_read on inamhi_bulletins;
create policy inamhi_public_read on inamhi_bulletins
    for select to guaradar_anon, guaradar_viewer, guaradar_operator, guaradar_publisher, guaradar_admin
    using (true);

drop policy if exists weather_cache_public_read on weather_cache;
create policy weather_cache_public_read on weather_cache
    for select to guaradar_anon, guaradar_viewer, guaradar_operator, guaradar_publisher, guaradar_admin
    using (true);

drop policy if exists river_cache_public_read on river_cache;
create policy river_cache_public_read on river_cache
    for select to guaradar_anon, guaradar_viewer, guaradar_operator, guaradar_publisher, guaradar_admin
    using (true);

-- ===========================================================================
-- OPERATOR WRITES
-- ===========================================================================

drop policy if exists road_status_operator_write on road_status;
create policy road_status_operator_write on road_status
    for insert to guaradar_operator, guaradar_publisher, guaradar_admin
    with check (has_role('operator'));

drop policy if exists road_status_operator_update on road_status;
create policy road_status_operator_update on road_status
    for update to guaradar_operator, guaradar_publisher, guaradar_admin
    using (has_role('operator'))
    with check (has_role('operator'));

drop policy if exists incidents_operator_update on incidents;
create policy incidents_operator_update on incidents
    for update to guaradar_operator, guaradar_publisher, guaradar_admin
    using (has_role('operator'))
    with check (has_role('operator'));

drop policy if exists shelters_operator_write on shelters;
create policy shelters_operator_write on shelters
    for all to guaradar_operator, guaradar_publisher, guaradar_admin
    using (has_role('operator'))
    with check (has_role('operator'));

-- The public may submit a report; it may never insert a verified one.
drop policy if exists incidents_public_insert on incidents;
create policy incidents_public_insert on incidents
    for insert to guaradar_anon
    with check (status = 'pending' and reviewed_by is null and reviewed_at is null);

-- ===========================================================================
-- PUBLISHER WRITES (alerts)
-- ===========================================================================

drop policy if exists alerts_operator_draft on alerts;
create policy alerts_operator_draft on alerts
    for insert to guaradar_operator, guaradar_publisher, guaradar_admin
    with check (has_role('operator') and status in ('draft','review'));

drop policy if exists alerts_publisher_write on alerts;
create policy alerts_publisher_write on alerts
    for update to guaradar_publisher, guaradar_admin
    using (has_role('publisher'))
    with check (has_role('publisher'));

drop policy if exists alert_sectors_publisher_write on alert_sectors;
create policy alert_sectors_publisher_write on alert_sectors
    for all to guaradar_operator, guaradar_publisher, guaradar_admin
    using (has_role('operator'))
    with check (has_role('operator'));

drop policy if exists alert_versions_staff_insert on alert_versions;
create policy alert_versions_staff_insert on alert_versions
    for insert to guaradar_operator, guaradar_publisher, guaradar_admin
    with check (has_role('operator'));

drop policy if exists alert_versions_staff_read on alert_versions;
create policy alert_versions_staff_read on alert_versions
    for select to guaradar_viewer, guaradar_operator, guaradar_publisher, guaradar_admin
    using (has_role('viewer'));

-- ===========================================================================
-- ADMIN ONLY
-- ===========================================================================

drop policy if exists sectors_admin_write on sectors;
create policy sectors_admin_write on sectors
    for all to guaradar_admin using (has_role('admin')) with check (has_role('admin'));

drop policy if exists sensors_admin_write on sensors;
create policy sensors_admin_write on sensors
    for all to guaradar_admin using (has_role('admin')) with check (has_role('admin'));

drop policy if exists sensor_readings_admin_insert on sensor_readings;
create policy sensor_readings_admin_insert on sensor_readings
    for insert to guaradar_admin with check (has_role('admin'));

drop policy if exists road_segments_admin_write on road_segments;
create policy road_segments_admin_write on road_segments
    for all to guaradar_admin using (has_role('admin')) with check (has_role('admin'));

drop policy if exists inamhi_operator_insert on inamhi_bulletins;
create policy inamhi_operator_insert on inamhi_bulletins
    for insert to guaradar_operator, guaradar_publisher, guaradar_admin
    with check (has_role('operator'));

-- audit_log: INSERT and SELECT only. There is deliberately no UPDATE or DELETE policy,
-- so RLS denies both for every role including admin. Combined with the rewrite rules in
-- migration 0001, history cannot be altered even by accident.
drop policy if exists audit_log_staff_insert on audit_log;
create policy audit_log_staff_insert on audit_log
    for insert to guaradar_operator, guaradar_publisher, guaradar_admin
    with check (has_role('operator'));

drop policy if exists audit_log_admin_read on audit_log;
create policy audit_log_admin_read on audit_log
    for select to guaradar_admin using (has_role('admin'));

-- ===========================================================================
-- Table privileges. RLS filters rows; grants decide whether the table is reachable
-- at all. Both are required — a missing grant and a permissive policy are equally
-- capable of producing an insecure or unusable configuration.
-- ===========================================================================

revoke all on all tables in schema public from public;

grant select on
    sectors, road_segments, road_status, sensors, sensor_readings,
    shelters, inamhi_bulletins, weather_cache, river_cache
    to guaradar_anon;

grant select on alerts, alert_sectors to guaradar_anon;
grant select on incidents to guaradar_anon;
grant insert on incidents to guaradar_anon;

grant select on all tables in schema public to guaradar_viewer;

grant select, insert, update on
    road_status, incidents, shelters, alerts, alert_sectors, alert_versions,
    inamhi_bulletins to guaradar_operator;

grant select, insert, update on alerts to guaradar_publisher;
grant select, insert on alert_versions to guaradar_publisher;

grant select, insert, update, delete on
    sectors, road_segments, road_status, sensors, sensor_readings,
    shelters, alerts, alert_sectors, alert_versions, incidents,
    inamhi_bulletins, weather_cache, river_cache
    to guaradar_admin;

-- Append-only: even admin gets only SELECT and INSERT on the audit log.
grant select, insert on audit_log to guaradar_admin;

grant usage, select on all sequences in schema public to guaradar_admin;

commit;
