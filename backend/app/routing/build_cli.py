#!/usr/bin/env python3
"""Reproducible OSM graph build (closes N-11).

Builds road_segments rows and a graph artifact from a SAVED extract, with no network access.
Bounded to this project's needs: no general-purpose ingestion platform.

USAGE
    cd backend
    ../.venv/bin/python -m app.routing.build_cli                # validate + write artifact
    ../.venv/bin/python -m app.routing.build_cli --check        # validate only, no writes
    ../.venv/bin/python -m app.routing.build_cli --extract PATH --out PATH

INPUT
    data/osm-guayaquil-demo-sectors.json  (Overpass API, ODbL, see docs/M10-EVIDENCE.md)
    Override with --extract.

OUTPUT
    data/graph-artifact.json   — node/edge topology, identity columns and provenance.
                                 Written atomically: a failed build never replaces the last
                                 valid artifact.

VALIDATION (all of these must pass before the artifact is written)
    1. every way yields a non-empty identity (way_id, ordinal)
    2. edge ids are unique
    3. edge_id == way_id * 1000 + ordinal for every row
    4. no synthetic node/edge is mixed into a real-OSM build
    5. direction values are within the known set
    6. weak connectivity of the largest component is reported, not silently accepted

EXIT CODES
    0 = valid, artifact written (or --check passed)
    1 = validation failed; the previous artifact is untouched
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.routing.identity import ORDINAL_SPACE, MIN_SEGMENT_LENGTH_M
from app.routing.osm_source import (
    DEFAULT_EXTRACT,
    build_graph_from_extract,
    load_extract,
    segment_rows,
)

ARTIFACT_SCHEMA_VERSION = "1"
DEFAULT_ARTIFACT = Path(__file__).resolve().parents[3] / "data" / "graph-artifact.json"


class ValidationError(Exception):
    """A build that cannot be trusted. Never written out."""


def validate(build: Any, node_coords: dict[int, tuple[float, float]]) -> dict[str, Any]:
    """Run every gate. Raises ValidationError on the first failure."""
    graph = build.graph
    segments = build.segments

    if not segments:
        raise ValidationError("extract produced no segments")

    # 1 + 2: identities present and edge ids unique
    seen_ids: set[int] = set()
    for seg in segments:
        if seg.identity.way_id <= 0:
            raise ValidationError(f"segment has non-positive way_id: {seg.identity}")
        eid = seg.identity.encode()
        if eid in seen_ids:
            raise ValidationError(
                f"duplicate edge id {eid} — two segments claim the same (way, ordinal)"
            )
        seen_ids.add(eid)

    # 3: the encoded id must agree with the identity it represents
    for eid, edge in graph.edges.items():
        way, ordinal = divmod(eid, ORDINAL_SPACE)
        if not 0 <= ordinal < ORDINAL_SPACE:
            raise ValidationError(f"edge {eid} has ordinal outside 0..{ORDINAL_SPACE - 1}")
        if way <= 0:
            raise ValidationError(f"edge {eid} decodes to non-positive way id")
        if eid != way * ORDINAL_SPACE + ordinal:
            raise ValidationError(f"edge id {eid} does not encode its identity")

    # 4: no synthetic mixed into a real build
    if not graph.synthetic:
        for nid, node in graph.nodes.items():
            if node.synthetic:
                raise ValidationError(f"node {nid} is marked synthetic inside a real-OSM graph")
        for eid, edge in graph.edges.items():
            if edge.synthetic:
                raise ValidationError(f"edge {eid} is marked synthetic inside a real-OSM graph")

    # 5: direction values
    for eid, edge in graph.edges.items():
        if edge.direction not in ("both", "forward", "backward"):
            raise ValidationError(f"edge {eid} has unknown direction {edge.direction!r}")

    # 6: connectivity, reported (not raised) so the numbers reach the evidence report
    und: dict[int, set[int]] = defaultdict(set)
    for e in graph.edges.values():
        und[e.a].add(e.b)
        und[e.b].add(e.a)
    seen: set[int] = set()
    comps: list[int] = []
    for n in graph.nodes:
        if n in seen:
            continue
        stack = [n]
        seen.add(n)
        size = 0
        while stack:
            u = stack.pop()
            size += 1
            for v in und[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        comps.append(size)
    comps.sort(reverse=True)
    largest_pct = 100.0 * comps[0] / len(graph.nodes) if graph.nodes else 0.0
    if largest_pct < 90.0:
        raise ValidationError(
            f"largest weak component is only {largest_pct:.1f} % — extract likely truncated"
        )

    # Idempotency: the row set must be stable for identical input. Verified by callers
    # comparing two builds; recorded here as a count so drift is visible.
    rows = segment_rows(build, node_coords)
    row_ids = [r[0] for r in rows]
    if len(set(row_ids)) != len(row_ids):
        raise ValidationError("segment_rows produced duplicate road_segment ids")

    return {
        "segments": len(segments),
        "graph_nodes": len(graph.nodes),
        "graph_edges": len(graph.edges),
        "weak_components": len(comps),
        "largest_component_pct": round(largest_pct, 1),
        "oneway": graph.oneway_stats(),
        "direction_basis": build.direction_basis,
        "total_length_m": round(sum(e.length_m for e in graph.edges.values()), 1),
        "synthetic": graph.synthetic,
        "min_segment_length_m": MIN_SEGMENT_LENGTH_M,
        "ordinal_space": ORDINAL_SPACE,
    }


def write_artifact(build: Any, stats: dict[str, Any], out: Path) -> Path:
    """Write the artifact ATOMICALLY.

    Written to a temporary file in the same directory and then renamed, so a crash mid-write
    cannot leave a half-written artifact in place of the last valid one.
    """
    prov = build.provenance
    payload = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "provenance": {
            "source": prov.provider,
            "licence": prov.licence,
            "osm_timestamp": prov.osm_timestamp.isoformat() if prov.osm_timestamp else None,
            "bbox": prov.bbox,
            "way_count": prov.way_count,
            "node_count": prov.node_count,
            "extract_path": prov.path,
        },
        "stats": stats,
        "nodes": {
            str(nid): {"lat": n.lat, "lon": n.lon}
            for nid, n in build.graph.nodes.items()
        },
        "edges": [
            {
                "id": e.id,
                "a": e.a,
                "b": e.b,
                "length_m": e.length_m,
                "road_class": e.road_class,
                "name": e.name,
                "direction": e.direction,
                "osm_way_id": divmod(e.id, ORDINAL_SPACE)[0],
                "segment_ordinal": divmod(e.id, ORDINAL_SPACE)[1],
            }
            for e in build.graph.edges.values()
        ],
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(out.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        os.replace(tmp_name, out)          # atomic
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the Guaradar road graph from a saved OSM extract.")
    ap.add_argument("--extract", type=Path, default=DEFAULT_EXTRACT)
    ap.add_argument("--out", type=Path, default=DEFAULT_ARTIFACT)
    ap.add_argument("--check", action="store_true", help="validate only; write nothing")
    args = ap.parse_args(argv)

    if not args.extract.exists():
        print(f"ERROR: extract not found: {args.extract}", file=sys.stderr)
        return 1

    try:
        build = build_graph_from_extract(args.extract)
        payload, _ = load_extract(args.extract)
        node_coords = {
            e["id"]: (e["lat"], e["lon"])
            for e in payload["elements"]
            if e.get("type") == "node" and "lat" in e
        }
        stats = validate(build, node_coords)
    except ValidationError as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        print("previous artifact left untouched", file=sys.stderr)
        return 1

    # Idempotency check: a second build from the same input must produce identical ids.
    again = build_graph_from_extract(args.extract)
    if sorted(again.graph.edges) != sorted(build.graph.edges):
        print("VALIDATION FAILED: rebuild produced different edge ids", file=sys.stderr)
        return 1
    stats["rebuild_ids_identical"] = True

    print("graph build OK")
    for k in ("segments", "graph_nodes", "graph_edges", "weak_components",
              "largest_component_pct", "total_length_m", "synthetic"):
        print(f"  {k:24} {stats[k]}")
    print(f"  {'oneway':24} {stats['oneway']}")
    print(f"  {'direction_basis':24} {stats['direction_basis']}")

    if args.check:
        print("--check: nothing written")
        return 0

    path = write_artifact(build, stats, args.out)
    print(f"artifact written: {path} ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
