"""CLI for loading `road_segments` from the graph artifact (M12 Part C, N-14).

    # 1. Inspect what would happen. No database connection, no writes.
    python -m app.routing.segment_cli --plan

    # 2. Emit the SQL to a file for review or for `psql -f`.
    python -m app.routing.segment_cli --emit-sql segments.sql

    # 3. Load through a DSN (writes).
    python -m app.routing.segment_cli --load --dsn "postgresql://..."

    # 4. Print the post-load verification queries.
    python -m app.routing.segment_cli --verify-queries

`--plan` and `--emit-sql` are read-only and are the safe way to inspect. `--load` is the only
mode that writes, and it prints the row count it is about to write first.

WHY A SEPARATE CLI FROM `build_cli.py`
  Building the graph and loading the database are different operations with different failure
  modes. A builder that also wrote rows would make "the build succeeded" ambiguous. Keeping them
  apart means the artifact can be rebuilt without touching the database, and the load can be
  re-run without rebuilding.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.routing.segment_loader import VERIFY_QUERIES, build_plan, build_sql

DEFAULT_ARTIFACT = Path("data/graph-artifact.json")


def _print_plan(plan, artifact: Path) -> None:
    print(f"artifact            {artifact}")
    print(f"  rows to load      {len(plan.rows)}")
    prov = plan.provenance or {}
    print(f"  extract source    {prov.get('source', 'unknown')}")
    print(f"  osm timestamp     {prov.get('osm_timestamp', 'MISSING')}")
    bbox = prov.get("bbox") or {}
    if bbox:
        print(
            f"  bbox              lat {bbox.get('south')}..{bbox.get('north')} "
            f"lon {bbox.get('west')}..{bbox.get('east')}"
        )
    if plan.rows:
        by_sector: dict[str, int] = {}
        by_class: dict[str, int] = {}
        for r in plan.rows:
            by_sector[r.sector_id or "(none)"] = by_sector.get(r.sector_id or "(none)", 0) + 1
            by_class[r.road_class] = by_class.get(r.road_class, 0) + 1
        print(f"  by sector         {dict(sorted(by_sector.items()))}")
        print(f"  by class          {dict(sorted(by_class.items()))}")
        total = sum(r.length_m for r in plan.rows)
        print(f"  total length      {total / 1000:.1f} km")
    for w in plan.warnings:
        print(f"  ! {w}")
    for e in plan.errors:
        print(f"  ERROR {e}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load road_segments from the graph artifact.")
    parser.add_argument("--artifact", default=str(DEFAULT_ARTIFACT))
    parser.add_argument("--plan", action="store_true", help="show what would be loaded; no writes")
    parser.add_argument("--emit-sql", metavar="PATH", help="write idempotent SQL to PATH")
    parser.add_argument("--load", action="store_true", help="apply via --dsn (writes)")
    parser.add_argument("--dsn", help="PostgreSQL DSN, required with --load")
    parser.add_argument("--limit", type=int, default=None, help="only the first N rows")
    parser.add_argument("--verify-queries", action="store_true", help="print post-load queries")
    args = parser.parse_args(argv)

    if args.verify_queries:
        for name, sql in VERIFY_QUERIES.items():
            print(f"-- {name}\n{sql}\n")
        return 0

    artifact = Path(args.artifact)
    if not artifact.exists():
        print(f"ERROR artifact not found: {artifact}", file=sys.stderr)
        return 2

    plan = build_plan(artifact, limit=args.limit)
    if args.plan or not (args.emit_sql or args.load):
        _print_plan(plan, artifact)

    if not plan.ok:
        print(f"\nREFUSING: {len(plan.errors)} validation error(s). Nothing written.", file=sys.stderr)
        for e in plan.errors[:20]:
            print(f"  {e}", file=sys.stderr)
        return 1

    if args.emit_sql:
        sql = build_sql(plan)
        Path(args.emit_sql).write_text("\n\n".join(sql) + "\n", encoding="utf-8")
        print(f"\nwrote {len(sql)} statement(s) covering {len(plan.rows)} row(s) to {args.emit_sql}")
        print("apply with: psql \"$DSN\" -v ON_ERROR_STOP=1 -f " + args.emit_sql)

    if args.load:
        if not args.dsn:
            print("ERROR --load requires --dsn", file=sys.stderr)
            return 2
        try:
            import psycopg  # noqa: PLC0415
        except ImportError:
            print("ERROR psycopg is not installed; cannot load", file=sys.stderr)
            return 2

        stmts = build_sql(plan)
        print(f"\nloading {len(plan.rows)} row(s) in {len(stmts)} statement(s) ...")
        # One transaction: a failure must leave the table as it was, never half-loaded.
        with psycopg.connect(args.dsn) as conn:
            with conn.cursor() as cur:
                for n, stmt in enumerate(stmts, 1):
                    cur.execute(stmt)
                    print(f"  statement {n}/{len(stmts)} ok")
                cur.execute(
                    "select count(*) from road_segments where source_kind = 'osm';"
                )
                row = cur.fetchone()
            conn.commit()
        print(f"  rows in table now: {row[0] if row else 'unknown'}")
        print("\nrun --verify-queries and check: identity violations = 0, duplicates = 0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
