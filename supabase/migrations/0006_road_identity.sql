-- Guaradar — M9 migration 0006: stable road identity
--
-- PROBLEM (N-8)
--   `road_segments.id` came from seed.sql ordinal arithmetic (1001…3050) while the router's
--   graph edge ids came from a sequential counter (0…259). Nothing joined them, so persisted
--   road status could never apply to a route.
--
-- WHAT THIS MIGRATION DOES — additive only
--   1. Adds the natural identity of a derived graph segment to `road_segments`:
--        source_kind, osm_way_id, segment_ordinal
--      and the derived router id (`edge_id`) those three encode.
--   2. Makes (source_kind, osm_way_id, segment_ordinal) UNIQUE so one source way cannot
--      produce two rows claiming the same segment, which is how a duplicate mapping would
--      silently appear across rebuilds.
--   3. Adds a CHECK that `edge_id` really equals osm_way_id * 1000 + segment_ordinal, so the
--      stored integer cannot drift from the identity it is supposed to represent.
--
-- WHY 1000
--   One ordinal digit-space per way. Measured against a real central-Guayaquil extract: max
--   47 segments per way. The CHECK refuses anything outside 0..999 rather than truncating.
--
-- WHAT IS NOT CHANGED
--   * No column dropped, no type narrowed, no row deleted.
--   * Existing rows keep their ids and gain NULL identity columns, because their true source
--     identity is unknown — and unknown must not be back-filled by guesswork.
--   * `road_status.road_segment_id` still points at `road_segments.id`. The identity chain
--     becomes: graph edge edge_id -> road_segments.edge_id -> road_segments.id -> road_status.
--
-- ROLLBACK: drop the added columns and constraints. Nothing else is affected.

begin;

alter table road_segments
    add column if not exists source_kind text
        check (source_kind in ('osm', 'synthetic')),
    add column if not exists osm_way_id bigint,
    add column if not exists segment_ordinal integer,
    add column if not exists edge_id bigint;

comment on column road_segments.source_kind is
    'Where this segment came from. NULL means unknown for legacy rows and must not be guessed.';
comment on column road_segments.osm_way_id is
    'The source OSM way. One way legitimately yields many segments (measured up to 47).';
comment on column road_segments.segment_ordinal is
    'This segment''s position in the source way''s node sequence. Stable across rebuilds.';
comment on column road_segments.edge_id is
    'The router''s integer edge id, derived as osm_way_id * 1000 + segment_ordinal.';

-- The identity triple must be unique: two rows claiming the same source segment would let one
-- closure apply to the wrong road. Partial index so legacy all-NULL rows are unaffected.
create unique index if not exists road_segments_identity_uidx
    on road_segments (source_kind, osm_way_id, segment_ordinal)
    where osm_way_id is not null and segment_ordinal is not null;

-- The derived id must be unique too, or the router cannot rely on it.
create unique index if not exists road_segments_edge_id_uidx
    on road_segments (edge_id)
    where edge_id is not null;

-- The stored integer must actually equal the identity it encodes. Without this, a bug in the
-- encoder could leave the database "successfully" storing a mapping to the wrong road.
alter table road_segments
    drop constraint if exists road_segments_edge_id_matches_identity;
alter table road_segments
    add constraint road_segments_edge_id_matches_identity
    check (
        edge_id is null
        or (
            osm_way_id is not null
            and segment_ordinal is not null
            and segment_ordinal between 0 and 999
            and edge_id = osm_way_id * 1000 + segment_ordinal
        )
    );

-- Fast join from a graph edge id to its status, which is the query the repository runs.
create index if not exists road_segments_edge_id_join_idx
    on road_segments (edge_id)
    where edge_id is not null;

comment on constraint road_segments_edge_id_matches_identity on road_segments is
    'edge_id must equal osm_way_id * 1000 + segment_ordinal, so the stored mapping cannot '
    'silently disagree with the identity it represents.';

-- ---------------------------------------------------------------------------
-- A view that makes the chain explicit and impossible to mis-join by accident.
-- Read-only; no new write path.
-- ---------------------------------------------------------------------------
create or replace view road_edge_status as
select
    rs.edge_id                       as graph_edge_id,
    rs.id                            as road_segment_id,
    rs.osm_way_id,
    rs.segment_ordinal,
    rs.name,
    st.status,
    st.depth_band,
    st.reason,
    st.source,
    st.set_at,
    st.review_at
from road_segments rs
join road_status st on st.road_segment_id = rs.id
where rs.edge_id is not null;

comment on view road_edge_status is
    'The identity chain made explicit: graph edge -> road_segments -> road_status. Read-only.';

commit;
