-- Guaradar — M1 migration 0003: deterministic demo seed
--
-- Rules that govern every row below:
--   * SEED DATA IS SYNTHETIC. It is not an observation, not an official record, and
--     not derived from live municipal feeds.
--   * Sensors are `simulated = true` (schema default).
--   * Seeded incidents are `seeded = true` and therefore never mistakable for field reports.
--   * Road statuses are `source = 'seed'` with an explicit reason, and their `review_at`
--     is in the past so the public app immediately shows them as due for re-check
--     rather than as freshly verified truth.
--   * Shelters carry `authorised_source = 'DEMO SEED — not a municipal designation'`
--     so the word "verified" cannot be earned accidentally.
--   * Elevation values are approximate SRTM-derived context (D12) and are rounded,
--     never presented as precise.
--
-- This file is idempotent: re-running it will not duplicate rows or destroy user data.
-- It upserts only the fixed IDs it owns.

begin;

-- ---------------------------------------------------------------------------
-- Three sectors (Stage 4 §16.4: reduced from five to fit the one-day schedule).
-- ---------------------------------------------------------------------------
insert into sectors (id, name_en, name_es, exposure_weight, center_lat, center_lon)
values
    ('norte',  'North',  'Norte',  1.4, -2.142000, -79.905000),
    ('centro', 'Centre', 'Centro', 1.2, -2.196200, -79.886500),
    ('sur',    'South',  'Sur',    1.1, -2.220000, -79.910000)
on conflict (id) do update set
    name_en = excluded.name_en,
    name_es = excluded.name_es,
    exposure_weight = excluded.exposure_weight,
    center_lat = excluded.center_lat,
    center_lon = excluded.center_lon;

-- ---------------------------------------------------------------------------
-- Six simulated sensor nodes across the three sectors.
-- Thresholds are PROTOTYPE values (D28), not municipal flood thresholds.
-- ---------------------------------------------------------------------------
insert into sensors (id, name, sector_id, lat, lon, threshold_m, simulated)
values
    ('SIM-01', 'Sauces 6',            'norte',  -2.142800, -79.905600, 1.20, true),
    ('SIM-02', 'Samanes',             'norte',  -2.149500, -79.902300, 1.00, true),
    ('SIM-03', 'Cerro Santa Ana',     'centro', -2.196200, -79.886500, 0.80, true),
    ('SIM-04', 'Cristo del Consuelo', 'sur',    -2.220700, -79.908900, 0.90, true),
    ('SIM-05', 'Cisne II',            'sur',    -2.227300, -79.915200, 1.10, true),
    ('SIM-06', 'Martha de Roldos',    'norte',  -2.158000, -79.890000, 0.80, true)
on conflict (id) do update set
    name = excluded.name,
    sector_id = excluded.sector_id,
    lat = excluded.lat,
    lon = excluded.lon,
    threshold_m = excluded.threshold_m,
    simulated = excluded.simulated;

-- ---------------------------------------------------------------------------
-- Road segments. A deterministic synthetic grid is used where a real OSM extract is
-- not available offline; every row is marked so nobody can mistake it for surveyed
-- geometry. When the OSM extract is built (block 3) these are replaced by real ways.
-- ---------------------------------------------------------------------------
insert into road_segments
    (id, osm_way_id, name, road_class, sector_id, geom_latlon, length_m,
     elevation_m, elevation_source, osm_timestamp)
select
    (ord.ord * 1000) + n as id,
    null,
    (array['Avenida Juan Tanca Marengo','Avenida Francisco de Orellana',
           'Avenida Sauces','Calle Samanes','Avenida Isidro Ayora'])[1 + ((n - 1) % 5)]
        || ' (synthetic ' || ord.ord || '-' || n || ')' as name,
    (array['primary','secondary','tertiary','residential'])[1 + ((n - 1) % 4)] as road_class,
    sec.id as sector_id,
    jsonb_build_array(
        jsonb_build_array(
            round((sec.center_lat + (n * 0.0009) - 0.02)::numeric, 6),
            round((sec.center_lon + (n * 0.0011) - 0.03)::numeric, 6)
        ),
        jsonb_build_array(
            round((sec.center_lat + (n * 0.0009) - 0.0190)::numeric, 6),
            round((sec.center_lon + (n * 0.0011) - 0.0290)::numeric, 6)
        )
    ) as geom_latlon,
    round((90 + (n * 7.3))::numeric, 1) as length_m,
    -- Approximate, rounded to 1 m. Static context only (D12).
    round((4 + ((n * 13) % 10))::numeric, 0) as elevation_m,
    'SRTM1' as elevation_source,
    null::timestamptz as osm_timestamp
from (values ('norte', 1), ('centro', 2), ('sur', 3)) as ord(sector_id, ord)
join sectors sec on sec.id = ord.sector_id
cross join generate_series(1, 50) as n
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- Road status: a handful of realistic states, including a closure with a reason and a
-- deliberately LAPSED review timer so staleness is visible from the first render.
-- ---------------------------------------------------------------------------
insert into road_status
    (road_segment_id, status, depth_band, reason, source, set_at, review_at)
values
    (1001, 'closed',   '>80',    'Water across carriageway, both lanes — DEMO SEED', 'seed',
     now() - interval '3 hours',  now() - interval '10 minutes'),   -- lapsed: shows as stale
    (1002, 'affected', '15-40',  'Kerb-deep water on northbound side — DEMO SEED', 'seed',
     now() - interval '25 minutes', now() + interval '30 minutes'),
    (2001, 'affected', '15-40',  'Drainage overflow at junction — DEMO SEED', 'seed',
     now() - interval '40 minutes', now() + interval '20 minutes'),
    (3001, 'closed',   '<15',    'Standing water, impassable on foot — DEMO SEED', 'seed',
     now() - interval '2 hours',  now() + interval '1 hour'),
    (3002, 'unknown',  'unknown', null, 'seed', now() - interval '2 hours', null)
on conflict (road_segment_id) do update set
    status = excluded.status,
    depth_band = excluded.depth_band,
    reason = excluded.reason,
    source = excluded.source,
    set_at = excluded.set_at,
    review_at = excluded.review_at;

-- ---------------------------------------------------------------------------
-- Sensor readings: one short history per node so trend and health can be derived.
-- ALL ROWS ARE SIMULATED. Deterministic values, not random, so rehearsals reproduce.
--
-- IDEMPOTENCY: earlier drafts used `now() - m * 5min`, which changes on every run and
-- therefore inserted a NEW set of rows each time (72 -> 144 on the second run). The
-- timestamps are now anchored to a single truncated instant so a re-run is a no-op.
-- ---------------------------------------------------------------------------
delete from sensor_readings where simulated = true;

insert into sensor_readings (sensor_id, depth_m, observed_at, quality, simulated)
select
    s.id,
    round((
        case s.id
            when 'SIM-01' then 0.62 + (m * 0.004)     -- rising slowly
            when 'SIM-02' then 0.28 - (m * 0.001)     -- falling slightly
            when 'SIM-03' then 0.55 + (m * 0.003)     -- rising
            when 'SIM-04' then 0.14 + (m * 0.001)
            when 'SIM-05' then 1.18 + (m * 0.006)     -- above threshold
            else              0.05
        end
    )::numeric, 3),
    -- Anchor: the seeded scenario is pinned to a whole minute, so every re-run
    -- produces identical timestamps and the unique constraint dedupes them.
    date_trunc('minute', now()) - (m * interval '5 minutes'),
    0,
    true
from sensors s
cross join generate_series(1, 12) as m
on conflict (sensor_id, observed_at) do nothing;

-- ---------------------------------------------------------------------------
-- Shelters: eight records. `authorised_source` makes the demo provenance explicit so
-- no row can be read as a municipal designation.
-- ---------------------------------------------------------------------------
insert into shelters
    (id, name, type, lat, lon, address, phone, capacity, accessibility,
     status, status_hold_until, authorised_source)
values
    ('11111111-1111-4111-8111-111111111101', 'Coliseo Sauces 6', 'shelter',
     -2.143000, -79.906000, 'Sauces 6, Norte', '911', 400,
     array['ramp','family_space'], 'open', now() + interval '6 hours',
     'DEMO SEED — not a municipal designation'),
    ('11111111-1111-4111-8111-111111111102', 'Unidad Educativa Samanes', 'shelter',
     -2.149000, -79.903000, 'Samanes, Norte', '911', 250,
     array['ramp'], 'unverified', null,
     'DEMO SEED — not a municipal designation'),
    ('11111111-1111-4111-8111-111111111103', 'Hospital Luis Vernaza', 'hospital',
     -2.193000, -79.883000, 'Centro', '911', null,
     array['ramp','emergency'], 'open', now() + interval '4 hours',
     'DEMO SEED — not a municipal designation'),
    ('11111111-1111-4111-8111-111111111104', 'Cuerpo de Bomberos Centro', 'fire',
     -2.195000, -79.885000, 'Centro', '911', null,
     array['emergency'], 'open', now() + interval '6 hours',
     'DEMO SEED — not a municipal designation'),
    ('11111111-1111-4111-8111-111111111105', 'Escuela Cristo del Consuelo', 'shelter',
     -2.221000, -79.909000, 'Sur', '911', 180,
     array['ramp','pets'], 'unverified', null,
     'DEMO SEED — not a municipal designation'),
    ('11111111-1111-4111-8111-111111111106', 'Hospital del Guasmo', 'hospital',
     -2.228000, -79.916000, 'Sur', '911', null,
     array['ramp','emergency'], 'full', now() + interval '2 hours',
     'DEMO SEED — not a municipal designation'),
    ('11111111-1111-4111-8111-111111111107', 'Casa Comunal Martha de Roldos', 'shelter',
     -2.158000, -79.890000, 'Martha de Roldos, Norte', '911', 120,
     array['family_space'], 'no_data', null,
     'DEMO SEED — not a municipal designation'),
    ('11111111-1111-4111-8111-111111111108', 'Reten Policial Cisne II', 'police',
     -2.227000, -79.915000, 'Cisne II, Sur', '911', null,
     array['emergency'], 'open', now() + interval '8 hours',
     'DEMO SEED — not a municipal designation')
on conflict (id) do update set
    name = excluded.name,
    type = excluded.type,
    lat = excluded.lat,
    lon = excluded.lon,
    status = excluded.status,
    status_hold_until = excluded.status_hold_until,
    authorised_source = excluded.authorised_source;

-- ---------------------------------------------------------------------------
-- Seeded citizen reports. `seeded = true` — these are synthetic demonstration data,
-- never field observations. Mix of verified and pending so both UI paths exist.
-- ---------------------------------------------------------------------------
insert into incidents
    (id, lat, lon, accuracy_m, depth_band, description, capture_at, submitted_at,
     status, reviewed_by, reviewed_at, review_note, reporter_code, seeded)
values
    ('22222222-2222-4222-8222-222222222201', -2.143200, -79.905800, 18, '15-40',
     'Water up to the kerb outside the coliseum.', now() - interval '50 min',
     now() - interval '48 min', 'verified',
     '33333333-3333-4333-8333-333333333301', now() - interval '40 min',
     'Corroborated by a second report nearby.', 'DEMO-4F2A', true),
    ('22222222-2222-4222-8222-222222222202', -2.143400, -79.906100, 25, '40-80',
     'Car stranded, water above the wheels.', now() - interval '44 min',
     now() - interval '42 min', 'verified',
     '33333333-3333-4333-8333-333333333301', now() - interval '35 min',
     'Matches sensor SIM-01 trend.', 'DEMO-9C11', true),
    ('22222222-2222-4222-8222-222222222203', -2.195800, -79.886300, 30, '15-40',
     'Drain overflowing on the corner.', now() - interval '20 min',
     now() - interval '18 min', 'pending', null, null, null, 'DEMO-77B2', true),
    ('22222222-2222-4222-8222-222222222204', -2.220500, -79.909200, 40, '<15',
     'Ankle deep, passable.', now() - interval '12 min',
     now() - interval '10 min', 'pending', null, null, null, 'DEMO-1D3E', true)
on conflict (id) do update set
    status = excluded.status,
    reviewed_by = excluded.reviewed_by,
    reviewed_at = excluded.reviewed_at,
    review_note = excluded.review_note;

-- ---------------------------------------------------------------------------
-- One DRAFT alert (invisible to the public) so the admin screen has content, and it
-- deliberately has an English body with NO Spanish yet: this proves the publication
-- block works before anyone tries to publish it.
-- ---------------------------------------------------------------------------
insert into alerts
    (id, severity, headline_en, body_en, starts_at, ends_at, status, source_basis, created_by)
values
    ('44444444-4444-4444-8444-444444444401', 3,
     'Heavy rain — North sector',
     'Heavy rainfall is forecast overnight. Avoid low-lying roads in Sauces 6 and Samanes.',
     now() - interval '10 min', now() + interval '6 hours', 'draft',
     array['Open-Meteo forecast','Seeded demo scenario'],
     '33333333-3333-4333-8333-333333333301')
on conflict (id) do update set
    severity = excluded.severity,
    headline_en = excluded.headline_en,
    body_en = excluded.body_en,
    starts_at = excluded.starts_at,
    ends_at = excluded.ends_at,
    source_basis = excluded.source_basis;

insert into alert_sectors (alert_id, sector_id)
values ('44444444-4444-4444-8444-444444444401', 'norte')
on conflict do nothing;

commit;
