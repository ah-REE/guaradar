# M10 — Expanded Coverage, One-Way Directionality, Verification Gaps: Evidence

**Date:** 2026-10-26
**Block:** M10 (A: wider extract · B: directionality · C: invariants · D: reproducibility · E: browser)
**Verdict:** **PASSED** on A–D. **Part E (browser verification) NOT COMPLETED — N-5 remains open.**
**Scope held:** no pooling, no admin console, no deployment, no commit, no destructive migration.

---

## 1. Baseline

```
313 passed, 10 skipped
```
Confirmed before editing.

---

## 2. Part A — expanded extract

### What was obtained

| Property | Value |
|---|---|
| Path | `data/osm-guayaquil-demo-sectors.json` (3,468,091 bytes) |
| Provider | Overpass API (`highway` in primary/secondary/tertiary/residential) |
| Query bbox | lat −2.2350…−2.1350, lon −79.9250…−79.8800 |
| Actual node extent | lat −2.2394…−2.1245 (**12.8 km**), lon −79.9345…−79.8771 (**6.4 km**) |
| OSM timestamp | **2026-10-26T02:08:42Z** |
| Contents | **5,809 ways, 20,388 nodes** |
| Licence | ODbL (© OpenStreetMap contributors) |

Saved once, read from disk thereafter — the build needs no network.

The earlier 1.1 km central extract is retained as `osm-central-guayaquil.json` and kept as a
small fixture; `DEFAULT_EXTRACT` now points at the wider file.

### Graph statistics

```
nodes                20,386
edges                24,943
total_length_m       1,085,491.6  (1,085 km)
junctions            4,143 (20.3 %)
mean_degree          1.84
weak components      23
largest component    97.6 %
synthetic            False
build time           0.3 s
```

**Coverage improved from 50.6 km / 994 edges to 1,085 km / 24,943 edges.** All six demo sensor
sites now fall inside the extract (snap distances 4–63 m, previously 4 m–5 km with five outside).

**Honest note on the 23 components:** these are small detached fragments (8 of them under 5
nodes) whose connecting way falls outside the bounding box. They are a property of a bounded
extract, not a builder defect, and the largest component holds 97.6 % of nodes.

### Two real data-quality defects found by building it

**D-1 — DISTINCT node ids at identical coordinates.** Way `31097256` contains nodes
`411046932` and `405568714` at the same position. This aborted the build with
`edge … has non-positive length`.

**D-2 — sub-centimetre segments rounded to zero.** Way `1556835856` has an **11 mm** segment
between nodes `14160137365` and `14160134939`. `round(0.011, 1) == 0.0`, so the stored length
became zero and tripped the same invariant.

Both are handled by skipping segments shorter than **0.1 m** — chosen deliberately to match the
storage precision (1 decimal), not an arbitrary number — while **keeping the ordinal slot** so
neighbouring segment identities do not shift.

### Identity mapping statistics

| Measure | Value |
|---|---|
| Segments with source identity | **24,943 / 24,943 (100 %)** |
| Duplicate `(way, ordinal)` | 0 |
| Edge ids encoding `way*1000 + ordinal` | all verified |

---

## 3. Part B — one-way directionality

### The defect this fixed

Before M10 the graph was **undirected**: `from_edges` registered both endpoints in the
adjacency, so every segment was traversable both ways. The extract tags **2,656 of 5,809 ways
`oneway=yes`** — meaning the router could send someone the wrong way down a very large number of
real one-way streets.

**Adding a tag to metadata would not have fixed this.** The traversal itself had to change.

### Implementation

`Edge.direction ∈ {both, forward, backward}` describes **legal travel**, and the adjacency is
now **outgoing only**: a forward edge is registered at `a` and *not* at `b`. An illegal traversal
is therefore **unreachable** in Dijkstra, not merely discouraged — the same structural approach
used for closed edges.

Identity is untouched: a one-way segment is still **one** physical segment with one `edge_id`.
Emitting two directed edges per segment was rejected because it would double the edge count,
break the 1:1 identity mapping, and make "which road is closed" ambiguous.

### Measured result

```
oneway: {'both': 12553, 'forward': 12390, 'backward': 0, 'oneway_total': 12390}
direction_basis: {'tagged oneway=yes': 2656,
                  'tagged oneway=no': 173,
                  'no oneway tag (not evidence of a restriction)': 2970,
                  'implied by junction=roundabout': 10}
```

**12,390 of 24,943 segments are one-way.** Note the tag is per **way**, and each way splits into
~4.3 segments, so 2,656 tagged ways become 12,390 directed segments.

Parsing is deliberately conservative:

| Tag | Direction |
|---|---|
| `oneway=yes` / `true` / `1` | forward |
| `oneway=-1` / `reverse` | backward |
| `oneway=no` / `false` / `0` | both |
| **missing** | **both** — absence is not evidence of a restriction |
| unrecognised value | both, and the basis records that it was unrecognised |
| `junction=roundabout` (no oneway tag) | forward — OSM convention |

### Proof it is enforced, not decorative

```
oneway edge 31097791000: a=410914183 -> b=405775600
  forward legal: True      backward legal: False
  edge listed at a? True   edge listed at b? False
  neighbours(b) yields the edge? False
```

And behaviourally: a chain of forward-only edges routes one way and **refuses** the reverse
direction; from a node where the short path is illegal, the router takes the 400 m legal detour
instead of the 100 m illegal shortcut.

### Turn restrictions — documented limitation, not claimed

`junction` appears in this extract only as `roundabout` (10 ways), which is handled as an implied
one-way. **No `restriction` relations are parsed or enforced.** The graph and router cannot
represent turn restrictions, so none is claimed. Implementing them safely would need an
edge-to-edge transition graph, which is a routing rewrite the brief explicitly did not ask for.

---

## 4. Part C — safety invariants preserved

| Invariant | Status |
|---|---|
| Phase 1 structurally excludes closed edges | unchanged; test `test_closure_on_a_oneway_still_excluded_in_phase1` |
| Phase 2 only when phase 1 has no eligible route | unchanged |
| Closure-crossing routes never recommended | unchanged |
| Unknown is not safe | unchanged; `test_unmapped_oneway_edge_is_unknown_not_clear` |
| Low/zero coverage never recommended | unchanged |
| Missing/stale evidence cannot improve eligibility | unchanged |
| Stale closures excluded (O-8) | unchanged; asserted through the identity path |
| D29 elevation last tie-break | unchanged; sort key untouched |
| Provenance accurate | **improved**: real OSM vs synthetic now branches correctly |
| Not described as a real-time flood map | unchanged |

One existing test had to change, and the reason matters: `test_real_graph_is_connected` asserted
`components == 1` on an **undirected** adjacency. With direction honoured, adjacency is
outgoing-only, so directed reachability is the wrong measure. Measured honestly:

```
weak connectivity:      23 components, 97.6 % largest
strong connectivity:    ~61 % of the graph reachable from a typical node (sampled)
```

A one-way road network is **not** strongly connected; that is a property of the data, not a
defect. Two tests now assert weak connectivity ≥ 95 % and *that strong connectivity is
incomplete*, so a regression that silently reverted to undirected adjacency would fail.

---

## 5. Part D — verification and reproducibility

### N-12 closed: identity-join coverage in the default run

`backend/tests/unit/test_m10_status_join.py` adds 16 deterministic fake-based tests covering
row validation, unmapped rows, all four status kinds, staleness, malformed rows, DB failure and
route integration.

```
before:  app/routing/status_repository.py   136 stmts  38 miss   48 br   0 part   70 %
after:   app/routing/status_repository.py   136 stmts   0 miss   48 br   0 part  100 %
```

**N-12 closed.** The distinction is preserved in the module docstring: these prove the *adapter
logic*; they do **not** prove PostgreSQL enforcement, which the opt-in integration tests cover.

### N-11 closed: reproducible offline build

`backend/app/routing/build_cli.py` — runnable with no network:

```
$ cd backend && ../.venv/bin/python -m app.routing.build_cli [--check] [--extract PATH] [--out PATH]

graph build OK
  segments                 24943
  graph_nodes              20386
  graph_edges              24943
  weak_components          23
  largest_component_pct    97.6
  total_length_m           1085491.6
  synthetic                False
  oneway                   {'both': 12553, 'forward': 12390, ...}
artifact written: data/graph-artifact.json (5,590,845 bytes)
```

Validation gates, all enforced before writing:

1. every segment has a positive `way_id` and a unique encoded edge id
2. `edge_id == way_id * 1000 + ordinal` for every edge
3. no synthetic node or edge is mixed into a real-OSM build
4. direction values are within the known set
5. largest weak component ≥ 90 % (guards against a truncated extract)
6. **rebuild produces identical edge ids** — checked by building twice and comparing

**Atomic write:** the artifact is written to a temp file in the same directory and `os.replace`d,
so a crash mid-write cannot destroy the last valid artifact. A validation failure exits 1 and
prints *"previous artifact left untouched"*.

Duplicate identities and mismatched encodings fail explicitly (M9's DB unique index and CHECK
remain the database-level backstop, re-verified below).

---

## 6. Part E — browser verification: **NOT COMPLETED**

| Attempt | Result |
|---|---|
| `browser_tool` navigate to `127.0.0.1:4180` | **`browser_private_target_denied`** — the tool refuses private-network targets |
| Local headless browser | `chromium`, `chromium-browser`, `google-chrome`, `firefox` **none installed**; `playwright` not present in the venv or `node_modules` |

Services *were* verified to run and serve correctly over HTTP:

```
api health          200
frontend             200
route endpoint       200, refused=false, 3 routes, synthetic=false,
                     snap 4.1 m / 32.3 m, phase 2 hazard_crossing, coverage 52.7 %
```

**N-5 stays open.** A successful build, a 200 response, and a bundle-string scan are **not**
visual verification, and I am not claiming otherwise. What remains unverified: map framing,
attribution legibility, route rendering positions, closure styling, tile-failure behaviour in a
real browser, and Spanish text rendering.

*(The route endpoint returned `phase 2 hazard_crossing` for the cross-sector pair. That is the
seed status generator closing 1-in-29 edges over a 24,943-edge network, so phase 1 almost always
finds a closure somewhere. It is correct behaviour with dense demo status, not a regression — but
it does mean the demo route list is currently dominated by hazard-crossing routes, which is worth
noting for presentation.)*

---

## 7. Gates

```
$ cd backend && ../.venv/bin/python -m pytest
364 passed, 10 skipped          (no database)

$ GUARADAR_PG_DSN=... ../.venv/bin/python -m pytest
371 passed, 3 skipped           (PostgreSQL 16.2)
```

Coverage:
```
app/domain/risk.py                 250    0   102   0   100%
app/routing/status_repository.py   136    0    48   0   100%   ← N-12 closed
app/routing/osm_source.py          112    1    32   1    99%
app/routing/search.py              226    1    98   2    99%
app/routing/identity.py             81    3    22   2    95%
app/api/models.py                   68    0     0   0   100%
app/api/route_models.py             51    0     0   0   100%
app/ingest/persistence.py           72    0    12   0   100%
app/routing/graph.py               278   40   120   3    84%
app/api/main.py                    185   22    64  11    85%
app/ingest/job.py                   72    3    18   2    94%
app/ingest/openmeteo.py            206   23    68   9    88%
```

**`domain/` gate holds at 100 % branch.**

RLS on the fully seeded schema (0001 → 0002 → 0005 → 0006 → seed):
```
0004_rls_tests.sql  →  30 PASS, "=== ALL RLS CHECKS PASSED ==="
```

Frontend:
```
$ npx tsc -b --force      → exit 0
$ npm run build           → built in 134ms
dist/assets/leaflet-src-*.js   148.60 kB │ gzip: 43.32 kB
dist/assets/index-*.js         251.33 kB │ gzip: 78.71 kB
$ node src/__i18n-check.mjs      → 43 keys, both languages, no overclaims
```

Other: **dependencies unchanged** (12 pins, no new package) · **no mutation verbs** ·
**no commits, pushes, deployments** · **no destructive migration**.

---

## 8. Defects found and fixed

| # | Defect | Surfaced by | Fix |
|---|---|---|---|
| **D-1** | Build aborted on distinct node ids at identical coordinates (way 31097256) | `edge … has non-positive length` | skip zero-length segments, keep the ordinal slot |
| **D-2** | **A 11 mm segment rounded to 0.0 and tripped the same invariant** (way 1556835856). My first threshold (0.01 m) was still above the rounding boundary | same error again after D-1 | threshold set to **0.1 m**, matched to storage precision, and applied via `round(length, 1)` |
| **D-3** | `test_real_graph_is_connected` asserted undirected connectivity, which is false once direction is honoured | test failure | split into weak-connectivity (≥ 95 %) and "strong connectivity is incomplete" assertions |
| **D-4** | A stale placeholder line in `build_cli.validate` computed a nonsense intermediate | self-review while writing the validator | removed |

**D-2 is the instructive one.** The obvious fix (skip exactly-zero length) was wrong because the
*symptom* was zero while the *cause* was rounding. Fixing the cause required matching the
threshold to the storage precision.

---

## 9. Limitations and blocker IDs

| ID | Status after M10 |
|---|---|
| **N-5** | **OPEN.** Browser verification not possible: tool refuses private targets, no local browser installed. |
| **N-11** | **CLOSED.** `build_cli.py` gives a documented, offline, validated, atomic build. |
| **N-12** | **CLOSED.** `status_repository.py` at 100 % branch coverage in the default run. |
| **N-13** | **PARTIALLY CLOSED.** One-way directionality is enforced by traversal and covered by 34 tests. **Turn restrictions are not modelled** and are documented as a limitation. |
| **N-10** | **CLOSED.** Extract now covers all three demo sectors; 1,085 km. |
| **N-14** (new) | **OsmBuild/repo integration is still script-driven.** `build_cli` writes an artifact; loading those rows into `road_segments` is still the verification-script path from M9. |
| **N-15** (new) | **`graph.py` coverage dropped to 84 %** — the new directed-adjacency branches (`backward` in particular) are exercised by unit tests, but the real extract contains **zero `backward`** edges, so that path has no production data behind it. |
| **N-16** (new) | **Demo route results are dominated by phase-2 hazard crossings** on the larger network, because the seed status generator closes 1-in-29 edges. Correct behaviour, awkward demo. |
| **O-7 / O-8 / N-1 / N-2 / N-6** | **Unchanged.** `risk.py` untouched at 100 % branch; no mutation endpoint; ingestion writes still disabled. |

---

## 10. Recommended next milestone

1. **Fix N-16** — tune the demo status lattice so a clear, recommendable route is reachable in
   the larger network. This is demo data, not engine behaviour.
2. **Fix N-14** — a documented `road_segments` load step driven by the artifact, so the pipeline
   is genuinely end to end.
3. **Only then** pooling (N-9), and the admin console last, after N-2.

---

## 11. Standing statements

- **Road geometry is real OpenStreetMap data** for a 12.8 × 6.4 km extract around three
  Guayaquil sectors. **Not city-wide.** Disclosed in the API and the UI.
- **Road status remains seed/demo data.** OSM provides no flood or closure information.
- **One-way directionality is enforced by traversal.** Turn restrictions are not modelled.
- **Risk model is an unvalidated heuristic** and is not displayed (O-7 open).
- **All sensor readings are SIMULATED.**
- **No route is claimed safe.**
- No commits, pushes, deployments, or destructive migrations.
