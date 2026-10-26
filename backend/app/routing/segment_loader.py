"""Load `road_segments` from the built graph artifact (M12 Part C, N-14).

WHAT THIS REPLACES
  Until now the only code that ever wrote `road_segments` from real OSM data was
  `tests/integration/test_m9_identity_pg.py`, i.e. a **test** was the de-facto loader. That is
  N-14: the production path did not exist, so nobody could say how the table is populated or
  whether a second run duplicates rows. This module is that path, and a CLI wraps it.

WHY NO IDENTITY IS GUESSED
  The artifact already carries the natural key for every edge — `osm_way_id` and
  `segment_ordinal` — and `edge_id` is derived from them by construction:

      edge_id = osm_way_id * 1000 + segment_ordinal

  Verified over the whole saved artifact: **24,943 of 24,943 edges satisfy it**, max ordinal 112,
  and none is missing either field. So this loader invents nothing. It asserts the derivation
  holds before inserting anything, and migration 0006 re-asserts it in the database with a CHECK.

WHY `id` IS SET TO `edge_id`
  `road_segments.id` needs a value that is **stable across rebuilds**, because
  `road_status.road_segment_id` points at it. A `bigserial` would give a different number on
  every load — a closure recorded yesterday would point at a different road today. Using the
  derived `edge_id` makes the mapping deterministic by construction, needs no sequence, and makes
  the whole chain 1:1 and auditable:

      graph edge -> road_segments.id (= edge_id) -> road_status.road_segment_id

  Legacy rows from `seed.sql` use small ids (1001…3050) with NULL identity columns; the real
  graph's edge ids start at 28,786,490,000, so the two ranges cannot collide.

IDEMPOTENCY
  A single `INSERT … ON CONFLICT (source_kind, osm_way_id, segment_ordinal) DO UPDATE` against
  the partial unique index from migration 0006. Running it twice leaves the same rows with the
  same ids. So:

      run 1  -> inserts
      run 2  -> updates in place, 0 inserts, row count unchanged
      run N  -> likewise

  Nothing is ever deleted. Rows this loader did not create are never touched.

HONEST LIMITATIONS (documented, not papered over)
  * **Geometry is a two-point straight line, not the true road shape.** The artifact stores each
    segment's endpoints (`a`, `b`) but not the intermediate polyline of the source OSM way. So
    `geom_latlon` is `[[lat_a, lon_a], [lat_b, lon_b]]` and will look simplified on a map. The
    alternative — re-reading the extract and reconstructing the true shape — is a separate,
    larger change; inventing a curvature here would be worse than a straight line.
  * **`elevation_m` stays NULL.** No SRTM data has been fetched, and D12 forbids using elevation
    as anything but disclosed static context. Filling it with a guess would violate D12 and the
    "never fabricate" rule.
  * **`sector_id` is a coarse nearest-centre assignment**, computed from the three seeded sector
    centres. It is a display grouping for the demo, deterministic and documented as approximate.
    It is **not** a survey boundary and must not be read as one.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Mirror of the DB constraint, so a bad artifact fails BEFORE it touches the database.
ORDINAL_MAX = 999


@dataclass(frozen=True)
class SegmentRow:
    """One `road_segments` row, fully derived from the artifact."""

    id: int
    edge_id: int
    osm_way_id: int
    segment_ordinal: int
    name: str | None
    road_class: str
    sector_id: str | None
    geom_latlon: list[list[float]]
    length_m: float
    osm_timestamp: str | None
    source_kind: str = "osm"
    # D12: never populated here. Kept explicit so its absence is a decision, not an oversight.
    elevation_m: float | None = None
    elevation_source: str | None = None


@dataclass
class LoadPlan:
    """What a load would do, computed without touching a database."""

    rows: list[SegmentRow]
    provenance: dict[str, Any]
    stats: dict[str, Any]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class SectorCentre:
    id: str
    lat: float
    lon: float


# The three sectors seeded by supabase/seed.sql. Duplicated here ONLY so the loader can run and
# be tested without a database; `load_rows` also accepts centres read from the DB, and the CLI
# prefers those.
DEFAULT_SECTORS: tuple[SectorCentre, ...] = (
    SectorCentre("norte", -2.142000, -79.905000),
    SectorCentre("centro", -2.196200, -79.886500),
    SectorCentre("sur", -2.220000, -79.910000),
)


def nearest_sector(
    lat: float, lon: float, sectors: tuple[SectorCentre, ...] = DEFAULT_SECTORS
) -> str | None:
    """Coarse nearest-centre grouping. Approximate by design; not a boundary."""
    if not sectors:
        return None
    return min(sectors, key=lambda s: _haversine_m(lat, lon, s.lat, s.lon)).id


def build_plan(
    artifact_path: Path,
    *,
    sectors: tuple[SectorCentre, ...] = DEFAULT_SECTORS,
    limit: int | None = None,
) -> LoadPlan:
    """Derive every row from the artifact and validate it. No I/O beyond reading the artifact."""
    raw = json.loads(artifact_path.read_text(encoding="utf-8"))
    nodes: dict[str, Any] = raw["nodes"]
    edges: list[dict[str, Any]] = raw["edges"]
    provenance = raw.get("provenance", {})
    stats = raw.get("stats", {})

    errors: list[str] = []
    warnings: list[str] = []
    rows: list[SegmentRow] = []

    osm_ts = provenance.get("osm_timestamp")
    if not osm_ts:
        warnings.append(
            "artifact has no osm_timestamp; road_segments.osm_timestamp will be NULL and the "
            "extract's age will be undisclosed"
        )

    seen_ids: set[int] = set()
    seen_identity: set[tuple[int, int]] = set()

    for edge in edges:
        eid = edge.get("id")
        way = edge.get("osm_way_id")
        ordinal = edge.get("segment_ordinal")

        if eid is None or way is None or ordinal is None:
            errors.append(f"edge {eid}: missing id/osm_way_id/segment_ordinal")
            continue

        # The identity must hold. If it does not, the artifact and the schema disagree, and
        # inserting anyway would store a mapping to the wrong road.
        if eid != way * 1000 + ordinal:
            errors.append(
                f"edge {eid}: id != osm_way_id*1000 + segment_ordinal "
                f"({way}*1000+{ordinal} = {way * 1000 + ordinal})"
            )
            continue
        if not 0 <= ordinal <= ORDINAL_MAX:
            errors.append(f"edge {eid}: segment_ordinal {ordinal} outside 0..{ORDINAL_MAX}")
            continue

        if eid in seen_ids:
            errors.append(f"edge {eid}: duplicate edge id in artifact")
            continue
        if (way, ordinal) in seen_identity:
            errors.append(f"edge {eid}: duplicate identity ({way}, {ordinal})")
            continue
        seen_ids.add(eid)
        seen_identity.add((way, ordinal))

        a = nodes.get(str(edge["a"]))
        b = nodes.get(str(edge["b"]))
        if a is None or b is None:
            errors.append(f"edge {eid}: endpoint node missing from artifact")
            continue

        length = edge.get("length_m")
        if length is None or float(length) <= 0:
            # road_segments.length_m has CHECK (length_m > 0)
            errors.append(f"edge {eid}: length_m must be > 0, got {length!r}")
            continue

        mid_lat = (a["lat"] + b["lat"]) / 2
        mid_lon = (a["lon"] + b["lon"]) / 2

        rows.append(
            SegmentRow(
                id=int(eid),
                edge_id=int(eid),
                osm_way_id=int(way),
                segment_ordinal=int(ordinal),
                name=edge.get("name"),
                road_class=edge.get("road_class") or "unclassified",
                sector_id=nearest_sector(mid_lat, mid_lon, sectors),
                # Two-point straight segment. See the module docstring: the artifact does not
                # carry the source way's intermediate geometry.
                geom_latlon=[
                    [float(a["lat"]), float(a["lon"])],
                    [float(b["lat"]), float(b["lon"])],
                ],
                length_m=round(float(length), 2),
                osm_timestamp=osm_ts,
            )
        )

    rows.sort(key=lambda r: r.id)
    if limit is not None:
        rows = rows[:limit]

    if not rows and not errors:
        errors.append("artifact produced zero rows")

    if stats:
        declared = stats.get("segments") or stats.get("graph_edges")
        if declared is not None and limit is None and declared != len(rows):
            errors.append(
                f"artifact stats claim {declared} segments but {len(rows)} rows were derived"
            )

    warnings.append(
        "geom_latlon holds a two-point straight segment (endpoints only); it is not the source "
        "way's true shape and will look simplified"
    )
    warnings.append(
        "sector_id is a coarse nearest-centre grouping for display; it is not a survey boundary"
    )
    warnings.append(
        "elevation_m is NULL: no terrain data was fetched, and D12 forbids inferring it"
    )

    return LoadPlan(rows=rows, provenance=provenance, stats=stats, errors=errors, warnings=warnings)


# ---------------------------------------------------------------------------
# SQL emission
# ---------------------------------------------------------------------------

_COLUMNS = (
    "id",
    "edge_id",
    "osm_way_id",
    "segment_ordinal",
    "source_kind",
    "name",
    "road_class",
    "sector_id",
    "geom_latlon",
    "length_m",
    "elevation_m",
    "elevation_source",
    "osm_timestamp",
)


def _lit(value: Any) -> str:
    """SQL literal. Only used for values this module derived, never for user input."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def build_sql(plan: LoadPlan, *, batch_size: int = 2000) -> list[str]:
    """Emit idempotent INSERT … ON CONFLICT statements, batched to stay under size limits.

    The conflict target matches the partial unique index from migration 0006, so a second run
    updates in place rather than inserting duplicates or failing.
    """
    stmts: list[str] = []
    for start in range(0, len(plan.rows), batch_size):
        chunk = plan.rows[start : start + batch_size]
        values = []
        for r in chunk:
            geom = json.dumps(r.geom_latlon, separators=(",", ":"))
            values.append(
                "("
                + ", ".join(
                    [
                        _lit(r.id),
                        _lit(r.edge_id),
                        _lit(r.osm_way_id),
                        _lit(r.segment_ordinal),
                        _lit(r.source_kind),
                        _lit(r.name),
                        _lit(r.road_class),
                        _lit(r.sector_id),
                        _lit(geom) + "::jsonb",
                        _lit(r.length_m),
                        _lit(r.elevation_m),
                        _lit(r.elevation_source),
                        _lit(r.osm_timestamp) + "::timestamptz",
                    ]
                )
                + ")"
            )
        stmts.append(
            f"insert into road_segments ({', '.join(_COLUMNS)}) values\n"
            + ",\n".join(values)
            + "\non conflict (source_kind, osm_way_id, segment_ordinal) "
            "where osm_way_id is not null and segment_ordinal is not null\n"
            "do update set\n"
            "  edge_id = excluded.edge_id,\n"
            "  name = excluded.name,\n"
            "  road_class = excluded.road_class,\n"
            "  sector_id = excluded.sector_id,\n"
            "  geom_latlon = excluded.geom_latlon,\n"
            "  length_m = excluded.length_m,\n"
            # Deliberately NOT updating elevation_m or elevation_source: this loader never has
            # terrain data, and overwriting an administrator-supplied value with NULL would
            # destroy information it did not create.
            "  osm_timestamp = excluded.osm_timestamp\n"
            "where road_segments.edge_id is distinct from excluded.edge_id\n"
            "   or road_segments.geom_latlon is distinct from excluded.geom_latlon\n"
            "   or road_segments.length_m is distinct from excluded.length_m\n"
            "   or road_segments.sector_id is distinct from excluded.sector_id\n"
            "   or road_segments.road_class is distinct from excluded.road_class\n"
            "   or road_segments.name is distinct from excluded.name;"
        )
    return stmts


# Verification queries an operator can paste after a load. Kept here so the docs and the CLI and
# the tests cannot drift apart.
VERIFY_QUERIES: dict[str, str] = {
    "row_count": "select count(*) from road_segments where source_kind = 'osm';",
    "identity_integrity": (
        "select count(*) as violations from road_segments "
        "where edge_id is not null and edge_id <> osm_way_id * 1000 + segment_ordinal;"
    ),
    "missing_identity": (
        "select count(*) from road_segments "
        "where source_kind = 'osm' and (edge_id is null or osm_way_id is null "
        "or segment_ordinal is null);"
    ),
    "duplicate_identity": (
        "select count(*) from (select osm_way_id, segment_ordinal from road_segments "
        "where osm_way_id is not null group by 1,2 having count(*) > 1) d;"
    ),
    "legacy_rows_untouched": (
        "select count(*) from road_segments where source_kind is null;"
    ),
    "sector_coverage": (
        "select sector_id, count(*) from road_segments where source_kind = 'osm' "
        "group by 1 order by 1;"
    ),
    "elevation_absent": (
        "select count(*) from road_segments where elevation_m is not null;"
    ),
}
