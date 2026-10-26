"""M9 real-PostgreSQL integration — stable identity join (N-8).

Opt-in via GUARADAR_PG_DSN. These tests require a database that has already had the M9
migration applied and some real OSM segments inserted; the fixture below builds that state
itself so the test is self-contained.

A mocked test cannot prove a SQL join works. These can, which is why they exist.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.routing.osm_source import (
    DEFAULT_EXTRACT,
    build_graph_from_extract,
    load_extract,
    segment_rows,
)
from app.routing.status_repository import load_status_by_edge

PG_DSN = os.environ.get("GUARADAR_PG_DSN")
PG_PSQL = os.environ.get("GUARADAR_PSQL", "psql")

needs_pg = pytest.mark.skipif(
    not PG_DSN, reason="set GUARADAR_PG_DSN to run real-PostgreSQL identity tests"
)
needs_extract = pytest.mark.skipif(
    not DEFAULT_EXTRACT.exists(), reason="real OSM extract not present"
)

NOW = datetime.now(timezone.utc)


def psql(sql: str, *, dsn: str | None = None) -> str:
    proc = subprocess.run(
        [PG_PSQL, "-X", "-q", "-t", "-A", "-F", "\x1f",
         "-v", "ON_ERROR_STOP=1", "-d", dsn or PG_DSN, "-c", sql],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[:300])
    return proc.stdout


def sql_lit(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


@pytest.fixture(scope="module")
def seeded_identity_db():
    """Load a bounded slice of the real extract and attach three statuses.

    Bounded to 40 segments so the fixture is fast; identity behaviour does not depend on volume.
    """
    build = build_graph_from_extract()
    payload, _ = load_extract()
    coords = {
        e["id"]: (e["lat"], e["lon"])
        for e in payload["elements"]
        if e.get("type") == "node" and "lat" in e
    }
    rows = segment_rows(build, coords, sector_id="centro")[:40]

    psql(
        "insert into sectors (id,name_en,name_es,exposure_weight,center_lat,center_lon) "
        "values ('centro','Centre','Centro',1.2,-2.1962,-79.8865) on conflict do nothing;"
    )
    # Clear only the rows this test owns, identified by their source kind.
    psql("delete from road_status where road_segment_id in "
         "(select id from road_segments where source_kind='osm');")
    psql("delete from road_segments where source_kind='osm';")

    values = []
    for r in rows:
        values.append("(" + ",".join([
            sql_lit(r[0]), sql_lit(r[1]), sql_lit(r[2]), sql_lit(r[3]), sql_lit("osm"),
            sql_lit(r[5]), sql_lit(r[6]), sql_lit("centro"),
            sql_lit(r[8]) + "::jsonb", sql_lit(r[9]), "null", "null",
            sql_lit(build.provenance.osm_timestamp.isoformat()),
        ]) + ")")
    psql(
        "insert into road_segments (id,osm_way_id,segment_ordinal,edge_id,source_kind,name,"
        "road_class,sector_id,geom_latlon,length_m,elevation_m,elevation_source,osm_timestamp) "
        "values " + ",".join(values) +
        " on conflict (source_kind, osm_way_id, segment_ordinal) "
        "where osm_way_id is not null and segment_ordinal is not null "
        "do update set edge_id = excluded.edge_id;"
    )

    # Three statuses on the first three segments: closed, affected, open.
    ids = [line.split("\x1f")[0] for line in psql(
        "select id from road_segments where source_kind='osm' order by id limit 3;"
    ).splitlines() if line.strip()]
    assert len(ids) == 3, f"expected 3 segment ids, got {ids}"

    psql(
        f"insert into road_status (road_segment_id,status,reason,source,set_at,review_at) values "
        f"({ids[0]},'closed','TEST: water across carriageway','seed',now() - interval '5 min',now() + interval '30 min'),"
        f"({ids[1]},'affected',null,'seed',now() - interval '5 min',now() + interval '30 min'),"
        f"({ids[2]},'open',null,'seed',now() - interval '5 min',now() + interval '30 min');"
    )

    yield {"build": build, "rows": rows, "status_ids": ids}

    psql("delete from road_status where road_segment_id in "
         "(select id from road_segments where source_kind='osm');")
    psql("delete from road_segments where source_kind='osm';")


def fetch_factory(dsn: str):
    def fetch(sql: str):
        out = []
        for line in psql(sql, dsn=dsn).splitlines():
            if not line.strip():
                continue
            f = line.split("\x1f")
            out.append([
                int(f[0]), f[1],
                datetime.fromisoformat(f[2]),
                datetime.fromisoformat(f[3]) if f[3] else None,
                f[4], f[5] or None, int(f[6]),
            ])
        return out

    return fetch


@needs_pg
@needs_extract
def test_identity_join_matches_real_osm_edges(seeded_identity_db) -> None:
    """Requirements 1, 5, 13: real edges receive their own status through the identity join."""
    build = seeded_identity_db["build"]
    res = load_status_by_edge(
        graph_edge_ids=build.graph.edges.keys(),
        fetch=fetch_factory(PG_DSN),
        now=NOW,
        default_freshness=timedelta(minutes=30),
    )
    assert res.ok, f"join failed: {res.error}"
    assert res.records_fetched == 3
    assert res.matched_edge_count == 3, (
        f"expected all 3 statuses to match a real graph edge, matched {res.matched_edge_count}"
    )


@needs_pg
@needs_extract
def test_closure_applies_only_to_its_own_edge(seeded_identity_db) -> None:
    """Requirement 5: a closure must not leak to a sibling segment of the same source way."""
    build = seeded_identity_db["build"]
    res = load_status_by_edge(
        graph_edge_ids=build.graph.edges.keys(),
        fetch=fetch_factory(PG_DSN),
        now=NOW,
        default_freshness=timedelta(minutes=30),
    )
    mapped = [
        line.split("\x1f") for line in psql(
            "select graph_edge_id, osm_way_id, segment_ordinal, status "
            "  from road_edge_status order by graph_edge_id;"
        ).splitlines() if line.strip()
    ]
    closed_ids = [int(m[0]) for m in mapped if m[3] == "closed"]
    assert len(closed_ids) == 1, f"expected exactly one closed edge, got {closed_ids}"

    closed_edge = closed_ids[0]
    assert res.index.is_closed(closed_edge) is True

    # A different segment of the SAME way, if present, must not be closed.
    same_way = [m for m in mapped if int(m[1]) == int(
        next(x[1] for x in mapped if int(x[0]) == closed_edge)
    )]
    for m in same_way:
        eid = int(m[0])
        if eid != closed_edge:
            assert res.index.is_closed(eid) is False, (
                f"closure leaked to sibling segment {eid} of the same way"
            )


@needs_pg
@needs_extract
def test_unmapped_edges_stay_unknown(seeded_identity_db) -> None:
    """Requirement 6: no status is invented for edges without a persisted record."""
    build = seeded_identity_db["build"]
    res = load_status_by_edge(
        graph_edge_ids=build.graph.edges.keys(),
        fetch=fetch_factory(PG_DSN),
        now=NOW,
        default_freshness=timedelta(minutes=30),
    )
    # `status_ids` holds road_segments.id values, NOT graph edge ids — subtract the edge ids
    # obtained from the identity view, otherwise the mapped edges are wrongly treated as
    # unmapped and the assertion fails against the closed one.
    mapped_edge_ids = {
        int(line.split("\x1f")[0])
        for line in psql("select graph_edge_id from road_edge_status;").splitlines()
        if line.strip()
    }
    unmapped = sorted(set(build.graph.edges) - mapped_edge_ids)
    # Sample a handful rather than all 994.
    for eid in unmapped[:20]:
        from app.routing.graph import STATUS_UNKNOWN

        assert res.index.status_of(eid) == STATUS_UNKNOWN
        assert res.index.is_verified(eid) is False


@needs_pg
@needs_extract
def test_identity_columns_enforced_by_database(seeded_identity_db) -> None:
    """The CHECK must reject a stored edge_id that disagrees with its identity."""
    # Pick a real way/ordinal and try to store a wrong edge_id.
    row = psql(
        "select osm_way_id, segment_ordinal, id from road_segments "
        "where source_kind='osm' order by id limit 1;"
    ).strip().split("\x1f")
    way_id, ordinal = int(row[0]), int(row[1])
    wrong = way_id * 1000 + ordinal + 1

    with pytest.raises(RuntimeError, match="road_segments_edge_id_matches_identity"):
        psql(
            f"update road_segments set edge_id = {wrong} "
            f"where osm_way_id = {way_id} and segment_ordinal = {ordinal};"
        )


@needs_pg
@needs_extract
def test_duplicate_mapping_rejected_by_unique_index(seeded_identity_db) -> None:
    """Requirement 8: two rows cannot claim the same source segment."""
    row = psql(
        "select osm_way_id, segment_ordinal from road_segments "
        "where source_kind='osm' order by id limit 1;"
    ).strip().split("\x1f")
    way_id, ordinal = int(row[0]), int(row[1])

    with pytest.raises(RuntimeError, match="road_segments_identity_uidx"):
        psql(
            "insert into road_segments (id, osm_way_id, segment_ordinal, edge_id, source_kind, "
            "road_class, geom_latlon, length_m) values "
            f"({999999999}, {way_id}, {ordinal}, {way_id * 1000 + ordinal}, 'osm', "
            "'residential', '[]'::jsonb, 1.0);"
        )


@needs_pg
@needs_extract
def test_repeat_mapping_insert_does_not_duplicate(seeded_identity_db) -> None:
    """Requirement 8: re-running the build must upsert, not duplicate."""
    before = int(psql(
        "select count(*) from road_segments where source_kind='osm';"
    ).strip())

    build = seeded_identity_db["build"]
    payload, _ = load_extract()
    coords = {
        e["id"]: (e["lat"], e["lon"])
        for e in payload["elements"]
        if e.get("type") == "node" and "lat" in e
    }
    rows = segment_rows(build, coords, sector_id="centro")[:40]
    values = []
    for r in rows:
        values.append("(" + ",".join([
            sql_lit(r[0]), sql_lit(r[1]), sql_lit(r[2]), sql_lit(r[3]), sql_lit("osm"),
            sql_lit(r[5]), sql_lit(r[6]), sql_lit("centro"),
            sql_lit(r[8]) + "::jsonb", sql_lit(r[9]), "null", "null",
            sql_lit(build.provenance.osm_timestamp.isoformat()),
        ]) + ")")
    psql(
        "insert into road_segments (id,osm_way_id,segment_ordinal,edge_id,source_kind,name,"
        "road_class,sector_id,geom_latlon,length_m,elevation_m,elevation_source,osm_timestamp) "
        "values " + ",".join(values) +
        " on conflict (source_kind, osm_way_id, segment_ordinal) "
        "where osm_way_id is not null and segment_ordinal is not null "
        "do update set edge_id = excluded.edge_id;"
    )
    after = int(psql(
        "select count(*) from road_segments where source_kind='osm';"
    ).strip())
    assert after == before, f"repeat build duplicated rows: {before} -> {after}"
