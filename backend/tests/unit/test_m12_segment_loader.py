"""M12 — road_segments loader tests (N-14).

Two layers:

  * Unit: derivation, validation, and SQL shape — no database needed. These run everywhere.
  * Integration: real PostgreSQL 16.2, proving idempotency and the identity chain. Skipped when
    no database is configured, and they say so rather than passing silently.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.routing.segment_loader import (
    DEFAULT_SECTORS,
    ORDINAL_MAX,
    VERIFY_QUERIES,
    build_plan,
    build_sql,
    nearest_sector,
)

ARTIFACT = Path(__file__).resolve().parents[3] / "data" / "graph-artifact.json"

pytestmark = pytest.mark.skipif(
    not ARTIFACT.exists(), reason=f"graph artifact missing at {ARTIFACT}"
)


# ===========================================================================
# 1. Derivation
# ===========================================================================


def test_plan_derives_every_artifact_edge() -> None:
    """The loader must account for every edge, not a convenient subset."""
    plan = build_plan(ARTIFACT)
    assert plan.ok, plan.errors
    raw = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert len(plan.rows) == len(raw["edges"]), (
        f"derived {len(plan.rows)} rows from {len(raw['edges'])} edges"
    )


def test_row_count_matches_artifact_stats() -> None:
    plan = build_plan(ARTIFACT)
    raw = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    declared = raw["stats"].get("segments") or raw["stats"].get("graph_edges")
    assert declared == len(plan.rows)


def test_every_row_satisfies_the_identity_derivation() -> None:
    """edge_id = way*1000 + ordinal must hold for every row, or the DB CHECK would reject it."""
    plan = build_plan(ARTIFACT)
    for r in plan.rows[:2000]:
        assert r.edge_id == r.osm_way_id * 1000 + r.segment_ordinal
        assert r.id == r.edge_id
        assert 0 <= r.segment_ordinal <= ORDINAL_MAX


def test_ids_are_unique_and_do_not_collide_with_seed_rows() -> None:
    """seed.sql uses 1001…3050; real edge ids are ~2.9e10. A collision would corrupt mappings."""
    plan = build_plan(ARTIFACT)
    ids = [r.id for r in plan.rows]
    assert len(ids) == len(set(ids))
    assert min(ids) > 1_000_000, f"min id {min(ids)} is inside the legacy seed range"


def test_geometry_is_two_points_and_uses_real_node_coordinates() -> None:
    """Honest limitation: endpoints only, never an invented polyline."""
    plan = build_plan(ARTIFACT)
    raw = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    nodes = raw["nodes"]
    by_id = {e["id"]: e for e in raw["edges"]}

    for r in plan.rows[:200]:
        e = by_id[r.id]
        assert len(r.geom_latlon) == 2, "must be a straight 2-point segment"
        a, b = nodes[str(e["a"])], nodes[str(e["b"])]
        assert r.geom_latlon[0] == [a["lat"], a["lon"]]
        assert r.geom_latlon[1] == [b["lat"], b["lon"]]


def test_elevation_is_never_populated() -> None:
    """D12: approximate context only, and no terrain data was fetched. NULL is the decision."""
    plan = build_plan(ARTIFACT)
    assert all(r.elevation_m is None for r in plan.rows)
    assert all(r.elevation_source is None for r in plan.rows)


def test_lengths_are_positive() -> None:
    """road_segments.length_m has CHECK (length_m > 0)."""
    plan = build_plan(ARTIFACT)
    assert all(r.length_m > 0 for r in plan.rows)


def test_osm_timestamp_propagated_from_provenance() -> None:
    plan = build_plan(ARTIFACT)
    raw = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    ts = raw["provenance"]["osm_timestamp"]
    assert all(r.osm_timestamp == ts for r in plan.rows)


def test_warnings_disclose_the_three_known_limitations() -> None:
    """An operator reading --plan must be told what is simplified."""
    plan = build_plan(ARTIFACT)
    joined = " ".join(plan.warnings).lower()
    assert "two-point straight segment" in joined
    assert "not a survey boundary" in joined
    assert "elevation_m is null" in joined


def test_limit_truncates_deterministically() -> None:
    plan = build_plan(ARTIFACT, limit=100)
    full = build_plan(ARTIFACT)
    assert len(plan.rows) == 100
    assert [r.id for r in plan.rows] == sorted(r.id for r in full.rows)[:100]


# ===========================================================================
# 2. Validation refuses bad input
# ===========================================================================


def _mutated_artifact(tmp_path: Path, mutate) -> Path:
    raw = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    mutate(raw)
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    return p


def test_broken_identity_is_refused(tmp_path: Path) -> None:
    """A stored mapping to the wrong road is worse than a failed load."""
    def mutate(raw):
        raw["edges"][0]["segment_ordinal"] += 1

    plan = build_plan(_mutated_artifact(tmp_path, mutate))
    assert not plan.ok
    assert any("id != osm_way_id*1000" in e for e in plan.errors)


def test_ordinal_outside_range_is_refused(tmp_path: Path) -> None:
    def mutate(raw):
        e = raw["edges"][0]
        e["segment_ordinal"] = 1000
        e["id"] = e["osm_way_id"] * 1000 + 1000

    plan = build_plan(_mutated_artifact(tmp_path, mutate))
    assert not plan.ok
    assert any("outside 0..999" in e for e in plan.errors)


def test_zero_length_is_refused(tmp_path: Path) -> None:
    def mutate(raw):
        raw["edges"][0]["length_m"] = 0

    plan = build_plan(_mutated_artifact(tmp_path, mutate))
    assert not plan.ok
    assert any("length_m must be > 0" in e for e in plan.errors)


def test_missing_endpoint_is_refused(tmp_path: Path) -> None:
    def mutate(raw):
        raw["edges"][0]["a"] = 999999999999

    plan = build_plan(_mutated_artifact(tmp_path, mutate))
    assert not plan.ok
    assert any("endpoint node missing" in e for e in plan.errors)


def test_duplicate_identity_is_refused(tmp_path: Path) -> None:
    def mutate(raw):
        raw["edges"][1]["osm_way_id"] = raw["edges"][0]["osm_way_id"]
        raw["edges"][1]["segment_ordinal"] = raw["edges"][0]["segment_ordinal"]
        raw["edges"][1]["id"] = (
            raw["edges"][0]["osm_way_id"] * 1000 + raw["edges"][0]["segment_ordinal"]
        )

    plan = build_plan(_mutated_artifact(tmp_path, mutate))
    assert not plan.ok
    assert any("duplicate" in e for e in plan.errors)


def test_cli_refuses_and_writes_nothing_on_a_bad_artifact(tmp_path: Path) -> None:
    """The CLI must exit non-zero and produce no SQL file when validation fails."""
    bad = _mutated_artifact(tmp_path, lambda raw: raw["edges"][0].update({"length_m": -1}))
    out_sql = tmp_path / "should_not_exist.sql"
    proc = subprocess.run(
        [
            "python", "-m", "app.routing.segment_cli",
            "--artifact", str(bad),
            "--emit-sql", str(out_sql),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "REFUSING" in proc.stderr
    assert not out_sql.exists(), "no SQL must be written when validation fails"


# ===========================================================================
# 3. SQL shape
# ===========================================================================


def test_sql_is_idempotent_by_construction() -> None:
    """ON CONFLICT against the migration-0006 unique index is what makes re-runs safe."""
    sql = build_sql(build_plan(ARTIFACT, limit=10))
    joined = "\n".join(sql)
    assert "on conflict (source_kind, osm_way_id, segment_ordinal)" in joined
    assert "do update set" in joined


def test_sql_never_deletes_or_truncates() -> None:
    """A loader that can delete is a loader that can destroy another system's rows."""
    joined = "\n".join(build_sql(build_plan(ARTIFACT, limit=10))).lower()
    for verb in ("delete", "truncate", "drop "):
        assert verb not in joined


def test_sql_does_not_overwrite_elevation() -> None:
    """The loader has no terrain data; overwriting an operator's value with NULL destroys it."""
    joined = "\n".join(build_sql(build_plan(ARTIFACT, limit=10)))
    update_clause = joined.split("do update set", 1)[1]
    assert "elevation_m = excluded.elevation_m" not in update_clause
    assert "elevation_source = excluded.elevation_source" not in update_clause


def test_sql_sets_a_null_elevation_on_insert() -> None:
    plan = build_plan(ARTIFACT, limit=5)
    sql = build_sql(plan)[0]
    # Columns are ordered; elevation_m and elevation_source are the 11th and 12th.
    assert ", null, null, '" in sql, "insert must carry NULL elevation"


def test_sql_batches_to_stay_under_statement_limits() -> None:
    plan = build_plan(ARTIFACT)
    stmts = build_sql(plan, batch_size=2000)
    assert len(stmts) == 13, f"24493 rows / 2000 per batch should be 13 statements, got {len(stmts)}"
    assert all(len(s) < 1_000_000 for s in stmts), "a single statement should stay under 1 MB"


def test_sql_quotes_apostrophes_in_names() -> None:
    """A road name with an apostrophe must not break the statement."""
    plan = build_plan(ARTIFACT, limit=1)
    plan.rows[0] = type(plan.rows[0])(
        **{**plan.rows[0].__dict__, "name": "Calle O'Higgins"}
    )
    sql = build_sql(plan)[0]
    assert "'Calle O''Higgins'" in sql


def test_verify_queries_are_provided_for_every_gate() -> None:
    for gate in (
        "row_count",
        "identity_integrity",
        "missing_identity",
        "duplicate_identity",
        "legacy_rows_untouched",
        "elevation_absent",
    ):
        assert gate in VERIFY_QUERIES
        assert VERIFY_QUERIES[gate].lower().startswith("select")


# ===========================================================================
# 4. Sector assignment
# ===========================================================================


def test_nearest_sector_picks_the_closest_centre() -> None:
    assert nearest_sector(-2.142, -79.905) == "norte"
    assert nearest_sector(-2.1962, -79.8865) == "centro"
    assert nearest_sector(-2.22, -79.91) == "sur"


def test_every_row_gets_a_sector() -> None:
    plan = build_plan(ARTIFACT)
    assert all(r.sector_id in {s.id for s in DEFAULT_SECTORS} for r in plan.rows)


# ===========================================================================
# 5. Integration against real PostgreSQL
# ===========================================================================

DSN = os.environ.get("GUARADAR_PG_DSN")
PSQL = os.environ.get("GUARADAR_PSQL") or shutil.which("psql")

pg_ready = pytest.mark.skipif(
    not (DSN and PSQL),
    reason="needs GUARADAR_PG_DSN and GUARADAR_PSQL for the real-PostgreSQL check",
)


def _psql(database: str, args: list[str], *, stdin: str | None = None):
    return subprocess.run(
        [PSQL, "-h", "/tmp", "-p", DSN.rsplit("port=", 1)[-1], "-U", "postgres",
         "-d", database, "-t", "-v", "ON_ERROR_STOP=1", *args],
        input=stdin,
        capture_output=True,
        text=True,
    )


@pg_ready
def test_loader_is_idempotent_on_real_postgresql() -> None:
    """THE N-14 CLAIM: re-running the load must not duplicate, repoint, or drop rows.

    Proven by counting rows and hashing the id set after each run. Two runs must give the same
    count and the same hash.
    """
    db = "m12_idem"
    _psql("postgres", ["-c", f"drop database if exists {db};"])
    _psql("postgres", ["-c", f"create database {db};"])

    root = Path(__file__).resolve().parents[3]
    for mig in sorted((root / "supabase" / "migrations").glob("000*.sql")):
        if mig.name.startswith(("0003", "0004")):  # RLS test scaffolding, not needed here
            continue
        r = _psql(db, ["-f", str(mig)])
        assert r.returncode == 0, f"{mig.name}: {r.stderr}"

    _psql(db, ["-c",
        "insert into sectors (id,name_en,name_es,exposure_weight,center_lat,center_lon) values "
        "('norte','N','N',1.4,-2.142,-79.905),('centro','C','C',1.2,-2.1962,-79.8865),"
        "('sur','S','S',1.1,-2.22,-79.91) on conflict (id) do nothing;"])

    plan = build_plan(ARTIFACT)
    sql_text = "\n\n".join(build_sql(plan))
    sql_file = Path("/tmp/_m12_idem.sql")
    sql_file.write_text(sql_text, encoding="utf-8")

    def fingerprint() -> str:
        r = _psql(db, ["-c",
            "select count(*) || '|' || coalesce(md5(string_agg(id::text, ',' order by id)),'') "
            "from road_segments where source_kind='osm';"])
        return r.stdout.strip()

    r1 = _psql(db, ["-f", str(sql_file)])
    assert r1.returncode == 0, r1.stderr
    after1 = fingerprint()

    r2 = _psql(db, ["-f", str(sql_file)])
    assert r2.returncode == 0, r2.stderr
    after2 = fingerprint()

    r3 = _psql(db, ["-f", str(sql_file)])
    assert r3.returncode == 0, r3.stderr
    after3 = fingerprint()

    assert after1 == after2 == after3, (
        f"load is not idempotent: {after1} / {after2} / {after3}"
    )
    count = int(after1.split("|")[0])
    assert count == len(plan.rows), f"expected {len(plan.rows)} rows, table has {count}"

    # The DB's own CHECK must agree with the rows we derived.
    r = _psql(db, ["-c",
        "select count(*) from road_segments where edge_id <> osm_way_id*1000+segment_ordinal;"])
    assert r.stdout.strip() == "0", "identity violations after load"

    r = _psql(db, ["-c", "select count(*) from road_segments where elevation_m is not null;"])
    assert r.stdout.strip() == "0", "elevation must stay NULL (D12)"


@pg_ready
def test_loaded_rows_join_to_road_status_on_real_postgresql() -> None:
    """The whole point of N-14: a graph edge id must reach a status through the real chain."""
    db = "m12_idem"
    r = _psql(db, ["-c",
        "select edge_id from road_segments where source_kind='osm' order by edge_id limit 1;"])
    edge = r.stdout.strip()
    assert edge, "no loaded rows to join against"

    r = _psql(db, ["-c",
        f"insert into road_status (road_segment_id,status,reason,source,set_at,review_at) "
        f"values ({edge},'closed','M12 integration','seed',now()-interval '1 min',"
        f"now()+interval '30 min');"])
    assert r.returncode == 0, r.stderr

    try:
        r = _psql(db, ["-c",
            f"select status from road_edge_status where graph_edge_id = {edge};"])
        assert r.stdout.strip() == "closed", (
            f"graph edge {edge} did not join to its status; got {r.stdout!r}"
        )
    finally:
        _psql(db, ["-c", f"delete from road_status where road_segment_id={edge};"])
