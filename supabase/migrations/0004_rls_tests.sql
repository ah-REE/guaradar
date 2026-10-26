-- Guaradar — M1 migration 0004: RLS verification harness
--
-- Purpose: prove the policies DENY what they must deny. A policy set that has never
-- been exercised is a policy set nobody knows the behaviour of.
--
-- DESIGN NOTE (learned the hard way while writing this file):
--   `SET LOCAL ROLE` and `set_config('guaradar.role', …, true)` must be changed TOGETHER.
--   An earlier draft set the role once and expected the app-role to gate access; that
--   silently kept running as admin and produced false PASSes. Every check below calls
--   `act_as()` which sets BOTH, so a check cannot accidentally inherit the wrong
--   privilege level.
--
-- Every check raises an exception on failure, so a silent pass is impossible.
-- Run with:  psql -v ON_ERROR_STOP=1 -f 0004_rls_tests.sql

\set ON_ERROR_STOP on

begin;

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------
create or replace function pg_temp.expect(label text, actual bigint, expected bigint)
returns void language plpgsql as $$
begin
    if actual is distinct from expected then
        raise exception 'FAIL: % — expected %, got %', label, expected, actual;
    end if;
    raise notice 'PASS: % (= %)', label, actual;
end $$;

-- Switch BOTH the SQL role and the application role, then assert we really changed.
create or replace function pg_temp.act_as(app_role text)
returns void language plpgsql as $$
declare
    dbrole text;
begin
    dbrole := case app_role
        when 'anon'      then 'guaradar_anon'
        when 'viewer'    then 'guaradar_viewer'
        when 'operator'  then 'guaradar_operator'
        when 'publisher' then 'guaradar_publisher'
        when 'admin'     then 'guaradar_admin'
        else 'guaradar_anon'
    end;
    execute format('set local role %I', dbrole);
    perform set_config('guaradar.role', app_role, true);
    -- Fail loudly if the switch did not take effect.
    if current_user <> dbrole then
        raise exception 'FAIL: act_as(%) did not switch role (current_user=%)', app_role, current_user;
    end if;
end $$;

-- ---------------------------------------------------------------------------
-- 0. RLS enabled on every operational table
-- ---------------------------------------------------------------------------
do $$
declare
    t text;
    missing text[] := '{}';
begin
    foreach t in array array[
        'sectors','road_segments','road_status','sensors','sensor_readings',
        'alerts','alert_sectors','alert_versions','incidents','shelters','audit_log',
        'inamhi_bulletins','weather_cache','river_cache'
    ] loop
        if not (select relrowsecurity from pg_class where relname = t and relkind = 'r') then
            missing := missing || t;
        end if;
    end loop;
    if array_length(missing, 1) > 0 then
        raise exception 'FAIL: RLS not enabled on %', missing;
    end if;
    raise notice 'PASS: RLS enabled on all 14 tables';
end $$;

-- ---------------------------------------------------------------------------
-- 1. Admin baseline
-- ---------------------------------------------------------------------------
do $$
declare n bigint;
begin
    perform pg_temp.act_as('admin');
    select count(*) into n from sectors;
    perform pg_temp.expect('admin sees 3 sectors', n, 3);
    select count(*) into n from sensors;
    perform pg_temp.expect('admin sees 6 sensors', n, 6);
    select count(*) into n from shelters;
    perform pg_temp.expect('admin sees 8 shelters', n, 8);
    select count(*) into n from road_segments;
    perform pg_temp.expect('admin sees 150 road segments', n, 150);
    select count(*) into n from alerts;
    perform pg_temp.expect('admin sees the 1 draft alert', n, 1);
end $$;

-- ---------------------------------------------------------------------------
-- 2. Public must NOT see the draft alert
-- ---------------------------------------------------------------------------
do $$
declare n bigint;
begin
    perform pg_temp.act_as('anon');
    select count(*) into n from alerts;
    perform pg_temp.expect('anon sees 0 alerts (draft invisible)', n, 0);
end $$;

-- ---------------------------------------------------------------------------
-- 3. Public sees only VERIFIED incidents, never pending ones
-- ---------------------------------------------------------------------------
do $$
declare n bigint;
begin
    perform pg_temp.act_as('anon');
    select count(*) into n from incidents;
    perform pg_temp.expect('anon sees only verified incidents', n, 2);
    select count(*) into n from incidents where status = 'pending';
    perform pg_temp.expect('anon sees 0 pending incidents', n, 0);
end $$;

-- ---------------------------------------------------------------------------
-- 4. Public MAY read roads, sensors, shelters, readings
-- ---------------------------------------------------------------------------
do $$
declare n bigint;
begin
    perform pg_temp.act_as('anon');
    select count(*) into n from road_status;
    perform pg_temp.expect('anon sees 5 road_status rows', n, 5);
    select count(*) into n from shelters;
    perform pg_temp.expect('anon sees 8 shelters', n, 8);
    select count(*) into n from sensor_readings;
    perform pg_temp.expect('anon sees 72 simulated readings', n, 72);
    select count(*) into n from road_segments;
    perform pg_temp.expect('anon sees 150 road segments', n, 150);
end $$;

-- ---------------------------------------------------------------------------
-- 5. Audit log invisible to anon
-- ---------------------------------------------------------------------------
do $$
declare n bigint;
begin
    perform pg_temp.act_as('anon');
    begin
        select count(*) into n from audit_log;
        raise exception 'FAIL: anon read audit_log (% rows)', n;
    exception
        when insufficient_privilege then
            raise notice 'PASS: anon denied on audit_log';
    end;
end $$;

-- ---------------------------------------------------------------------------
-- 6. Anon cannot insert a pre-verified incident
-- ---------------------------------------------------------------------------
do $$
begin
    perform pg_temp.act_as('anon');
    begin
        insert into incidents (lat, lon, status, reporter_code, reviewed_by, reviewed_at)
        values (-2.14, -79.90, 'verified', 'TEST-0001',
                '33333333-3333-4333-8333-333333333301', now());
        raise exception 'FAIL: anon inserted a pre-verified incident';
    exception
        when insufficient_privilege or check_violation then
            raise notice 'PASS: anon cannot insert a verified incident';
    end;
end $$;

-- ---------------------------------------------------------------------------
-- 7. Anon can submit a legitimate pending report
-- ---------------------------------------------------------------------------
do $$
declare n bigint;
begin
    perform pg_temp.act_as('anon');
    insert into incidents (lat, lon, status, reporter_code, depth_band)
    values (-2.1401, -79.9001, 'pending', 'TEST-0002', '15-40');
    -- Verify as admin, because anon is correctly NOT allowed to read pending rows back.
    perform pg_temp.act_as('admin');
    select count(*) into n from incidents where reporter_code = 'TEST-0002';
    perform pg_temp.expect('anon report stored, visible to admin', n, 1);
end $$;

-- ---------------------------------------------------------------------------
-- 8. Anon cannot modify road_status (most safety-critical write)
-- ---------------------------------------------------------------------------
do $$
declare n bigint;
begin
    perform pg_temp.act_as('anon');
    begin
        update road_status set status = 'open' where road_segment_id = 1001;
        get diagnostics n = row_count;
        if n > 0 then
            raise exception 'FAIL: anon modified % road_status rows', n;
        end if;
        raise notice 'PASS: anon modified 0 road_status rows';
    exception
        when insufficient_privilege then
            raise notice 'PASS: anon denied UPDATE on road_status';
    end;
end $$;

-- ---------------------------------------------------------------------------
-- 9. Viewer cannot write anything
-- ---------------------------------------------------------------------------
do $$
declare n bigint;
begin
    perform pg_temp.act_as('viewer');
    begin
        update road_status set status = 'open' where road_segment_id = 1001;
        get diagnostics n = row_count;
        if n > 0 then
            raise exception 'FAIL: viewer modified % road_status rows', n;
        end if;
        raise notice 'PASS: viewer modified 0 road_status rows';
    exception
        when insufficient_privilege then
            raise notice 'PASS: viewer denied UPDATE on road_status';
    end;
end $$;

-- ---------------------------------------------------------------------------
-- 10. Operator cannot publish an alert
-- ---------------------------------------------------------------------------
do $$
declare n bigint;
begin
    perform pg_temp.act_as('operator');
    begin
        update alerts set status = 'published' where id = '44444444-4444-4444-8444-444444444401';
        get diagnostics n = row_count;
        if n > 0 then
            raise exception 'FAIL: operator published an alert';
        end if;
        raise notice 'PASS: operator published 0 alerts';
    exception
        when insufficient_privilege then
            raise notice 'PASS: operator denied alert publication';
    end;
end $$;

-- ---------------------------------------------------------------------------
-- 11. D26 — database refuses a monolingual publication
-- ---------------------------------------------------------------------------
do $$
begin
    perform pg_temp.act_as('admin');
    begin
        update alerts
           set status = 'published',
               published_by = '33333333-3333-4333-8333-333333333301',
               published_at = now()
         where id = '44444444-4444-4444-8444-444444444401';
        raise exception 'FAIL: monolingual alert published (D26 violated)';
    exception
        when check_violation then
            raise notice 'PASS: D26 enforced — bilingual fields required to publish';
    end;
end $$;

-- ---------------------------------------------------------------------------
-- 12. D26 — publication succeeds once Spanish is present, and anon then sees it
-- ---------------------------------------------------------------------------
do $$
declare n bigint;
begin
    perform pg_temp.act_as('admin');
    update alerts
       set headline_es = 'Lluvia intensa — sector Norte',
           body_es = 'Se prevé lluvia intensa durante la noche. Evite las vías bajas en Sauces 6 y Samanes.',
           status = 'published',
           published_by = '33333333-3333-4333-8333-333333333301',
           published_at = now()
     where id = '44444444-4444-4444-8444-444444444401';

    perform pg_temp.act_as('anon');
    select count(*) into n from alerts;
    perform pg_temp.expect('anon now sees 1 published alert', n, 1);
end $$;

-- ---------------------------------------------------------------------------
-- 13. Expired alert disappears from the public view
-- ---------------------------------------------------------------------------
do $$
declare n bigint;
begin
    perform pg_temp.act_as('admin');
    update alerts set ends_at = now() - interval '1 minute'
     where id = '44444444-4444-4444-8444-444444444401';

    perform pg_temp.act_as('anon');
    select count(*) into n from alerts;
    perform pg_temp.expect('anon sees 0 alerts once expired', n, 0);
end $$;

-- ---------------------------------------------------------------------------
-- 14. Closed road requires a reason
-- ---------------------------------------------------------------------------
do $$
begin
    perform pg_temp.act_as('admin');
    begin
        insert into road_status (road_segment_id, status, source)
        values (1999, 'closed', 'seed');
        raise exception 'FAIL: closed status accepted without a reason';
    exception
        when check_violation then
            raise notice 'PASS: closed status requires a reason';
    end;
end $$;

-- ---------------------------------------------------------------------------
-- 15. Audit log is append-only for ADMIN as well
-- ---------------------------------------------------------------------------
do $$
declare n bigint; changed bigint;
begin
    perform pg_temp.act_as('admin');
    insert into audit_log (actor, action, target_table, target_id, after)
    values ('33333333-3333-4333-8333-333333333301', 'test.audit', 'road_status', '1001',
            '{"status":"closed"}'::jsonb);

    update audit_log set action = 'TAMPERED' where action = 'test.audit';
    select count(*) into changed from audit_log where action = 'TAMPERED';
    perform pg_temp.expect('audit_log UPDATE affects 0 rows', changed, 0);

    delete from audit_log where action = 'test.audit';
    select count(*) into n from audit_log where action = 'test.audit';
    perform pg_temp.expect('audit_log DELETE leaves the row intact', n, 1);
end $$;

-- ---------------------------------------------------------------------------
-- 16. Provenance: nothing claims to be real
-- ---------------------------------------------------------------------------
do $$
declare n bigint;
begin
    perform pg_temp.act_as('admin');
    select count(*) into n from sensor_readings where simulated = false;
    perform pg_temp.expect('readings claiming to be real', n, 0);
    select count(*) into n from sensors where simulated = false;
    perform pg_temp.expect('sensors claiming to be real', n, 0);
    select count(*) into n from incidents where seeded = false and reporter_code like 'DEMO-%';
    perform pg_temp.expect('demo reports not marked seeded', n, 0);
    select count(*) into n from shelters where authorised_source like 'DEMO SEED%';
    perform pg_temp.expect('shelters labelled as demo seed', n, 8);
end $$;

-- ---------------------------------------------------------------------------
-- 17. Staleness is visible from seed: a lapsed review_at exists
-- ---------------------------------------------------------------------------
do $$
declare n bigint;
begin
    perform pg_temp.act_as('admin');
    select count(*) into n from road_status where review_at < now();
    perform pg_temp.expect('road statuses with lapsed review timer', n, 1);
end $$;

do $$ begin raise notice '=== ALL RLS CHECKS PASSED ==='; end $$;

rollback;
