# M9 — Unified Road Data Source and Stable Edge Identity: Evidence

**Date:** 2026-10-26
**Block:** M9 (source identity · mapping · repository join)
**Verdict:** **PASSED.** N-8 is **closed** with a **real OSM extract**, not synthetic fixtures.
**Scope held:** no pooling, no admin console, no deployment, no commit, no destructive migration.

---

## 1. Baseline

```
283 passed, 4 skipped
```
Confirmed before editing.

---

## 2. Source data — a genuine extract, not a fixture

The brief said to check for a real extract first, and to fetch a bounded public area if permitted.
None was cached, so I queried the Overpass API for a **1.1 km square of central Guayaquil**:

| Property | Value |
|---|---|
| Path | `data/osm-central-guayaquil.json` (125,072 bytes, committed to the workspace) |
| Provider | Overpass API, `highway` in (primary, secondary, tertiary, residential) |
| Bounding box | lat −2.2000…−2.1900, lon −79.8950…−79.8850 (~1.1 × 1.1 km) |
| OSM timestamp | **2026-10-26T01:23:40Z** |
| Contents | **148 ways, 841 nodes** |
| Licence | ODbL (© OpenStreetMap contributors) |

Fetched once, saved, and read from disk thereafter — the build has no network dependency.

**What OSM does and does not supply:** road geometry, class, and names. It says **nothing** about
flooding, closures, or safety. The build asserts this in `ExtractProvenance.notes()`, and a test
checks the phrase is present.

### The multi-edge problem, measured rather than assumed

The brief warned that an OSM way id does not uniquely identify a graph edge. Confirmed against
this extract:

```
total graph segments   994
ways split into >1     116 of 148
mean segments per way  6.7
max segments per way   47
```

So a closure on one way must propagate to exactly its segments — no more, no fewer.

---

## 3. Identity model

### Natural key

```
(source_kind, osm_way_id, segment_ordinal)
```

`segment_ordinal` is the segment's **position in the way's node sequence**, so identity derives from
source data, not from iteration order during a build.

### Router integer

```
edge_id = osm_way_id * 1000 + segment_ordinal
```

`ORDINAL_SPACE = 1000` is the only constant. It is safe because the measured maximum is 47, and
`encode()` **raises** rather than aliasing if a way ever exceeds it.

### Why not the alternatives

| Option | Verdict |
|---|---|
| Sequential counter (what `build_synthetic_grid` did) | **Rejected.** Inserting one way renumbers every later edge, so a stored mapping would silently point at a different road after a rebuild. |
| Hash of (way, ordinal) | **Rejected as primary key.** Stable but opaque and collision-prone; nothing downstream could audit a mapping it cannot read. |
| Composite natural key + invertible surrogate | **Adopted.** Both components are meaningful and `decode(encode(x)) == x` always. |

Verified in the real build:

```
edge 31097791000 -> way 31097791 ord 0  name=Avenida 1B SE
edge 31097816000 -> way 31097816 ord 0  name=Manuel de Villavicencio
edge 31097816001 -> way 31097816 ord 1  name=Manuel de Villavicencio
edge 31097816002 -> way 31097816 ord 2  name=Manuel de Villavicencio
```

One road, three edges, distinct identities — the case the brief flagged, handled by construction.

### Files

| Path | Purpose |
|---|---|
| `backend/app/routing/identity.py` | `EdgeIdentity`, encode/decode, `segments_from_way`, mapping records — **97 % coverage** |
| `backend/app/routing/osm_source.py` | extract loading, graph build, row preparation — **98 % coverage** |
| `supabase/migrations/0006_road_identity.sql` | additive identity columns, constraints, `road_edge_status` view |
| `data/osm-central-guayaquil.json` | the real extract |
| `backend/tests/unit/test_m9_identity.py` | 30 tests |
| `backend/tests/integration/test_m9_identity_pg.py` | 6 real-PostgreSQL tests |

---

## 4. Migration (forward-only, additive)

Adds to `road_segments`: `source_kind`, `osm_way_id`, `segment_ordinal`, `edge_id`.

Three constraints that make the mapping trustworthy:

1. **`road_segments_identity_uidx`** — unique on `(source_kind, osm_way_id, segment_ordinal)`, partial where the identity is non-null. Two rows cannot claim the same source segment, which is how a duplicate mapping would otherwise appear across rebuilds.
2. **`road_segments_edge_id_uidx`** — the derived id must be unique.
3. **`road_segments_edge_id_matches_identity`** — `edge_id = osm_way_id * 1000 + segment_ordinal` and `segment_ordinal` in 0…999. Without this, an encoder bug could leave the database "successfully" storing a mapping to the wrong road.

Plus a read-only view making the chain explicit:

```sql
create view road_edge_status as
select rs.edge_id as graph_edge_id, rs.id as road_segment_id, rs.osm_way_id,
       rs.segment_ordinal, rs.name, st.status, ...
  from road_segments rs
  join road_status st on st.road_segment_id = rs.id
 where rs.edge_id is not null;
```

No column dropped, no type narrowed, no row deleted. Legacy rows keep NULL identity — **their true
source is unknown and was not back-filled by guesswork.**

---

## 5. Mapping statistics — no zero hidden

| Measure | Value |
|---|---|
| Graph edges built from the extract | **994** |
| Edges with a source identity | **994 (100 %)** |
| Named road segments | 988 |
| Unnamed segments | 6 |
| Graph nodes | 841 |
| Total network length | **50,642.9 m** |
| Connected components | **1** (100 % in the largest) |
| `graph.synthetic` | **False** |

Every edge carries a real identity. Previously the mapping was 0 of 260; it is now complete by
construction because graph and rows come from the same extract.

---

## 6. Real PostgreSQL verification

Schema rebuilt from scratch on PostgreSQL 16.2: `0001` → `0002` → `0005` → `0006`, all applied.

40 real OSM segments inserted, three statuses attached (one closed, one affected, one open).

### The identity chain, queried directly

```
 graph_edge_id  | osm_way_id | segment_ordinal |  status  | name
----------------+------------+-----------------+----------+----------------------
 31097791000    | 31097791   | 0               | closed   | Avenida 1B SE
 31097816000    | 31097816   | 0               | affected | Manuel de Villavicencio
 31097816001    | 31097816   | 1               | open     | Manuel de Villavicencio
```

One source way, two segments, **different statuses** — proving the identity is per-segment, not
per-road-name.

### Repository join against the real 994-edge graph

```
graph edges: 994 | records fetched: 3 | matched edge ids: 3 | ok: True
  edge 31097791000: status=closed   closed=True   verified=False
  edge 31097816000: status=affected closed=False  verified=True
  edge 31097816001: status=open     closed=False  verified=True
  unmapped edge 280374980002: status=unknown   (correct)
  same-way sibling 31097816001 closed? -> False  (closure did NOT leak)
```

Four properties at once: the closure applies to its own edge, it does not leak to a sibling segment
of the same way, it counts as **not** verified coverage, and unmapped edges stay `unknown`.

### Database-enforced integrity

| Test | Result |
|---|---|
| Store an `edge_id` that disagrees with its identity | rejected by `road_segments_edge_id_matches_identity` |
| Insert a duplicate `(source, way, ordinal)` | rejected by `road_segments_identity_uidx` |
| Re-run the build upsert | row count unchanged (idempotent) |

### RLS

On the fully seeded M9 schema:
```
0004_rls_tests.sql  →  30 PASS, "=== ALL RLS CHECKS PASSED ==="
```
(An earlier failure on the `m9` scratch database was **fixture state** — one sector instead of three — not a policy regression; verified on a properly seeded database.)

---

## 7. Counts and gates

```
$ cd backend && ../.venv/bin/python -m pytest
313 passed, 10 skipped        (no database — what CI would run)

$ GUARADAR_PG_DSN=... ../.venv/bin/python -m pytest
320 passed, 3 skipped         (with PostgreSQL 16.2)

app/domain/risk.py                 250    0   102   0   100%
app/routing/identity.py             74    2    18   1    97%
app/routing/osm_source.py           90    1    22   1    98%
app/routing/search.py              226    1    98   2    99%
app/ingest/persistence.py           72    0    12   0   100%
app/api/models.py                   68    0     0   0   100%
app/api/route_models.py             51    0     0   0   100%
app/routing/status_repository.py   136   38    48   0    70%
app/routing/graph.py               246   37   102   1    83%
app/ingest/job.py                   72    3    18   2    94%
app/api/main.py                    185   22    64  11    85%
```

**`domain/` gate holds at 100 % branch.** `status_repository.py` dropped to 70 % because the new
`load_status_by_edge` path is exercised chiefly by the opt-in PostgreSQL tests; that is a real
coverage gap in the default run and is recorded rather than hidden.

Frontend:
```
$ npx tsc -b --force                → exit 0
$ npm run build
dist/assets/leaflet-src-*.js   148.60 kB │ gzip: 43.32 kB
dist/assets/index-*.js         251.33 kB │ gzip: 78.71 kB
$ node src/__i18n-check.mjs         → 43 keys, both languages, no overclaims
```

Other gates:
- **Dependencies:** unchanged — 12 pins, no new package.
- **Mutation verbs:** none (`@app.(post|put|patch|delete)` → empty).
- **No commits, pushes, deployments.** Still not a Git repository.
- **No destructive migration.**

---

## 8. Defects found and fixed

| # | Defect | Surfaced by | Fix |
|---|---|---|---|
| **D-1** | **`DEFAULT_EXTRACT` path resolved one level too high** (`parents[2]` from `app/routing/`) | `FileNotFoundError` | `parents[3]`; the same off-by-one appeared in a test and was fixed there too |
| **D-2** | **The synthetic-network disclosure became FALSE once the graph turned real.** The route response and two UI strings still claimed "synthetic demo data (about 43 km of generated grid)" | 4 M7 tests failed, and inspection of the bundle showed the stale string shipped | Disclosures now branch on `graph.synthetic`, and the UI copy was rewritten to say *real OSM geometry, not city-wide, status is seed data* |
| **D-3** | **`ON CONFLICT` target did not match the partial unique index.** The index includes `source_kind` and a two-part predicate | `there is no unique or exclusion constraint matching the ON CONFLICT specification` | Conflict target changed to `(source_kind, osm_way_id, segment_ordinal)` with the index predicate restated exactly |
| **D-4** | **M7 tests hardcoded sensor coordinates as route endpoints.** Against the real extract, 5 of 6 sensors are 1–5 km outside the bounded area, so every route refused | 4 test failures | Endpoints derived from real graph nodes; the sensor-snap test was rewritten to assert what actually matters — and the historical reason is recorded in the test docstring rather than erased |
| **D-5** | My assertion `body["synthetic"] is (not graph.synthetic)` was inverted | `assert False is not False` | Equality, since both describe the same graph |
| **D-6** | **A test subtracted `road_segments.id` values from graph edge ids** — different id spaces — so mapped edges looked unmapped | `assert 'closed' == 'unknown'` | Subtract edge ids from the identity view instead |

**D-2 is the significant one.** Making the data real invalidated a disclosure that was previously
correct. Had the tests not failed, the app would have told users the roads were synthetic while
drawing real OpenStreetMap geometry — a different falsehood, not a smaller one.

---

## 9. Requirements checklist (from §6 of the brief)

| # | Requirement | Evidence |
|---|---|---|
| 1 | Stable identity across repeat builds | `test_real_build_is_stable_across_rebuilds` — identical id sets and identities |
| 2 | Multiple segments from one way | `test_one_way_yields_many_segments_with_distinct_ordinals`; live: way 31097816 → ord 0,1,2 |
| 3 | Split ways and topology changes | ordinal follows node order; `test_missing_node_coords_skip_segment_but_keep_ordinal_slot` |
| 4 | Duplicate source IDs, invalid mappings | `test_duplicate_way_ids_are_deduplicated`, DB unique index test |
| 5 | Closure propagates to matching edges only | `test_closure_applies_only_to_its_own_edge`; live sibling check |
| 6 | Unmapped edges remain unknown | `test_unmapped_edges_stay_unknown`; live: edge 280374980002 → unknown |
| 7 | No status by position/name/distance | migration test asserts no `soundex`, `similarity`, `levenshtein`, `st_distance` |
| 8 | Repeat build creates no duplicate mappings | `test_repeat_mapping_insert_does_not_duplicate` (count unchanged) |
| 9 | Missing/stale status cannot improve recommendation | M8 `test_losing_evidence_via_repository_never_improves_recommendation` + `test_real_row_edge_id_matches_identity_constraint` |
| 10 | Phase 1 excludes mapped closures | `test_route_phase1_avoids_a_persisted_closure` |
| 11 | Phase 2 non-recommended and labelled | M7 `test_route_hazard_crossing_never_recommended` etc., unchanged |
| 12 | Coverage honest from mapped evidence | M8 `test_empty_repository_yields_zero_coverage_and_no_recommendation`; identity path leaves unmapped edges unverified |
| 13 | Synthetic/real provenance reaches API | `test_route_provenance_propagates`, retargeted so it asserts whichever source is active |
| 14 | RLS assertions green | 30/30 on seeded M9 schema |
| 15 | Risk/routing invariants unchanged | `domain/risk.py` 100 % branch, 250 statements; `search.py` 99 %; all `ROUTE-*` green |

---

## 10. Remaining limitations

| # | Limitation |
|---|---|
| **N-5** | Still no browser screenshot; frontend verified by build + bundle scan. |
| **N-10** (new) | **The extract is ~1.1 km of central Guayaquil.** Five of six demo sensor sites lie outside it. Routing between them correctly refuses rather than guessing; demo route endpoints are now derived from real nodes. |
| **N-11** (new) | **`road_segments` for OSM data is populated by a script, not by an automated migration/seed step.** The 40-row insert is a verification fixture, not a shipped pipeline. |
| **N-12** (new) | **`status_repository.py` coverage is 70 % in the default run** because the identity join is exercised by opt-in PostgreSQL tests. No new PostgreSQL path is covered without a database. |
| **N-13** (new) | **No one-way or turn-restriction modelling.** Directionality is preserved only as way node order; a router could route against a one-way street. Recorded, not fixed. |
| **N-6 / N-2** | Unchanged: ingestion writes still disabled; no privileged endpoint. |
| **N-1** | Unchanged: no model-run time; never inferred. |
| **O-7 / O-8** | Unchanged. `risk.py` untouched; stale-closure exclusion preserved and now asserted through the identity path too. |

---

## 11. Recommended next milestone

**M10 — operationalise the OSM pipeline and widen the extract.** Specifically:

1. A documented, repeatable script that fetches a **larger** extract (the three demo sectors, not 1.1 km), builds segments, and upserts them — closing N-11 and N-10.
2. Add one-way and turn-restriction capture (N-13) before routing is presented as usable.
3. Then connection pooling (N-9 from M8), and only after N-2 is resolved, the admin console.

---

## 12. Standing statements

- **Road geometry is now real OpenStreetMap data** for a small central-Guayaquil extract. It is **not city-wide**, and this is disclosed in the API and the UI.
- **Road status remains seed/demo data.** OSM provides no flood or closure information.
- **Risk model is an unvalidated heuristic** and is not displayed (O-7 open).
- **All sensor readings are SIMULATED.**
- **No route is claimed safe.** Coverage stated, hazard crossings labelled, low coverage never recommended.
- No commits, pushes, deployments, or destructive migrations.
