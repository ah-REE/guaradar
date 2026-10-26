# M7 — Forecast Persistence, Route API, and Map: Evidence

**Date:** 2026-10-26
**Block:** M7 (A: forecast persistence · B: read-only route API · C: interactive map)
**Verdict:** **PASSED.** 230 tests, 2 skipped. Persistence **works end to end against real
PostgreSQL 16.2**. Route API live. Map builds; **browser rendering still not visually verified**
(N-5 persists).
**Scope held:** no admin console, no mutation endpoint, no deployment, no commit.

---

## 1. Baseline before any change

```
198 passed, 2 skipped
```
Confirmed before editing. `app/domain/risk.py` at 100 % branch.

---

## 2. Files changed

### Created

| Path | Purpose |
|---|---|
| `supabase/migrations/0005_forecast_snapshots.sql` | **additive** history table + cache link; no destructive change |
| `backend/app/ingest/persistence.py` | append-only snapshot writer; I/O-free, injected `execute` |
| `backend/app/api/route_models.py` | typed route contract with `schema_version` |
| `backend/tests/api/test_m7_persistence_route.py` | 32 tests (persistence + route API) |
| `frontend/src/routeApi.ts` | typed route client; refuses unknown `schema_version` |
| `frontend/src/RouteScreen.tsx` | route screen + lazy-loaded Leaflet map |
| `docs/M7-EVIDENCE.md` | this report |

### Modified

| Path | Change |
|---|---|
| `backend/app/api/main.py` | `GET /api/public/route`; `build_demo_status`; graph now includes sensor nodes |
| `backend/app/routing/graph.py` | `build_synthetic_grid` gained `extra_places` (additive, default `None`) |
| `frontend/src/i18n.ts` | +18 bilingual keys (43 total) |
| `frontend/src/App.tsx` | Status / Route tab navigation |
| `PHASES.md` | status rows |

### Not modified

`app/domain/risk.py` (**O-7 untouched — verified**) · `app/routing/search.py` (two-phase logic
unchanged; only consumed) · `requirements.txt` (12 pins) · `package.json` (no dependency added —
Leaflet was already pinned) · all Stage 1–4 docs · migrations 0001–0004.

---

## 3. Part A — persistence, and the schema problem it exposed

### Why the existing schema could not satisfy the requirement

`weather_cache` has `PRIMARY KEY (lat, lon)`: **one row per location.** A second fetch must
`UPDATE` that row, destroying the previous `fetched_at` and payload. That directly contradicts
the M7 requirement that duplicate fetches must not corrupt historical provenance and that
historical records must not be overwritten.

### Approach — additive only

1. **New `weather_forecast_snapshots`** — append-only, one row per validated fetch.
2. **`weather_cache` keeps its existing role** as a latest-value cache. It gains only a nullable
   `snapshot_id` pointer for traceability.
3. **No column dropped, no type narrowed, no row deleted.**

### Provenance fields now representable

| Distinction | Column | Test |
|---|---|---|
| source / provider | `source` | `test_persist_success_stores_row` |
| forecast vs observation | `kind` + `CHECK (kind='forecast')` | rejected `observation` insert (§4) |
| source timestamps | `source_first_hour_at`, `source_last_hour_at` | — |
| retrieval time | `fetched_at` | `test_persist_preserves_missing_model_run_as_null` |
| model run time | `model_run_at` (**NULL when absent**) | same test asserts `params[8] is None` |
| units | `units` (normalised) + `units_original` | `test_persist_units_recorded_both_ways` |
| validation status | `validation_status` ∈ ok/partial/failed | `test_persist_gaps_are_partial_not_zero` |
| dropped counts | `dropped_value_count` | same test asserts `== 1` |
| validation notes | `validation_notes jsonb` | — |
| stale at write | `stale_at_write` | `test_persist_stale_flag_computed_at_write` |

### Two schema bugs found by actually running the migration

**D-1 — a generated `dedupe_key` column was rejected:**
```
ERROR: generation expression is not immutable
```
Every `timestamptz` formatting function (`to_char`, `::text`, `extract(epoch)`) is **STABLE**,
not `IMMUTABLE`, so PostgreSQL refuses them in generated columns. I verified this empirically
rather than assuming.

**D-2 — the replacement had to be `UNIQUE NULLS NOT DISTINCT`.** A plain `UNIQUE` treats NULLs
as distinct, so two fetches with `model_run_at IS NULL` — **the only case this project ever
produces** (N-1) — would both insert and dedupe would silently do nothing. The constraint is
now:
```sql
unique nulls not distinct (source, lat, lon, fetched_at, model_run_at)
```
This is the correct semantic and it only works because PG15+ supports it.

**D-3 — append-only rewrite rules broke `ON CONFLICT`:**
```
ERROR: INSERT with ON CONFLICT clause cannot be used with table that has INSERT or UPDATE rules
```
The `DO INSTEAD NOTHING` rules I first copied from `audit_log` are incompatible with the
idempotent-insert design. Removed. Append-only is enforced instead by RLS (no UPDATE/DELETE
policy for any role) plus privileges (only SELECT/INSERT granted) — the same mechanism already
protecting `audit_log`, and one that composes with `ON CONFLICT`.

### Does persistence actually work end to end?

**Yes, verified against local PostgreSQL 16.2** (extracted from the `pgserver` wheel, same as M1).
Migrations 0001 → 0002 → seed → 0005 all apply cleanly, then:

```
first insert  (model_run_at NULL)  → id 1
identical insert again             → INSERT 0 0   (deduped, history untouched)
later fetch, different fetched_at  → id 3
final row count                    → 2
```

```
model_run_at IS NULL rows: 2        ← provenance preserved, never back-filled
kind='observation'  → violates check constraint "only_forecast_supported"
model_run_at > fetched_at → violates "model_run_not_after_fetch"
UPDATE as guaradar_admin → permission denied for table weather_forecast_snapshots
DELETE as guaradar_admin → permission denied for table weather_forecast_snapshots
final row count          → 2        ← nothing was rewritten
```

M1's 30-assertion RLS suite **still passes** on the M7 schema — the new table weakened nothing.

**Not tested:** Supabase-specific RLS (`auth.uid()`), PostGIS, and concurrent writers. Local
PostgreSQL only.

---

## 4. Part B — route API

`GET /api/public/route?from_lat&from_lon&to_lat&to_lon&alternatives`

### Contract (abridged)

```json
{
  "schema_version": "1",
  "routes": [{
    "id": "route-1", "rank": 1,
    "geometry": [{"lat": -2.143078, "lon": -79.906079}, ...],
    "distance_m": 4821.3, "duration_s": 438.3,
    "hazard_class": "clear", "classification": "eligible",
    "coverage_pct": 89.68, "band": "high", "recommended": true,
    "warnings": ["2 segment(s) have no road-status information at all.", ...],
    "label": "No known hazards on the verified portion · coverage 90 %",
    "legs": [{"from": {...}, "to": {...}, "length_m": 120.0,
              "status": "open", "verified": true, "synthetic": true}],
    "phase": 1, "mean_elevation_m": 6.0, "elevation_used_as_tiebreak": false,
    "synthetic": true
  }],
  "refused": false,
  "all_routes_hazard_crossing": false,
  "best_available_is_uncertain": false,
  "snap_from_m": 0.0, "snap_to_m": 0.0,
  "synthetic": true,
  "provenance": {"simulated": true, "data_mode": "SIMULATED",
                 "notes": ["road network is synthetic demo data, not Guayaquil's real streets", ...]}
}
```

`schema_version` exists so a consumer can refuse an unfamiliar shape rather than misread it.

### Safety properties, re-asserted at the API layer

| Property | Test |
|---|---|
| Phase 1 never includes a closed edge | `test_route_phase1_never_crosses_a_closure` |
| Hazard-crossing never recommended | `test_route_hazard_crossing_never_recommended` |
| Low/zero coverage never recommended | `test_route_low_coverage_never_recommended` |
| At most one recommendation | `test_route_at_most_one_recommended` |
| Geometry only from graph nodes | `test_route_geometry_is_from_the_graph_only` |
| Synthetic status propagates | `test_route_synthetic_status_propagates` |
| No overclaiming language | `test_route_no_overclaiming_language` |
| Snap > 60 m refuses | `test_route_refuses_when_snap_too_far` |
| No privileged fields | `test_route_response_excludes_privileged_fields` |
| No mutation verb exists | `test_no_mutation_routes_exist_after_m7` |

### Live verification

```
$ curl .../api/public/route?from_lat=-2.1428&from_lon=-79.9056&to_lat=-2.2207&to_lon=-79.9089
http=200
schema: 1 | refused: False | routes: 3 | synthetic: True
  route-1 phase=1 clear band=low cov= 38.6% rec=False geom=9
  route-2 phase=1 clear band=low cov= 38.9% rec=False geom=11
  route-3 phase=1 clear band=low cov= 38.9% rec=False geom=11
any banned word: False

$ curl .../route?from_lat=-2.4000&from_lon=-80.0000...        ← far from any road
refused: True
reason: Cannot calculate a route: your starting point is 21390 m from the nearest road (limit 60 m).

$ curl .../route?from_lat=-2.1428&from_lon=-79.9056&to_lat=-2.1580&to_lon=-79.8900
  phase=1 clear rec=True  cov=89.68%      ← a genuinely recommendable route
  phase=1 clear rec=False cov=90.46%
  phase=1 clear rec=False cov=77.35%
```

Both the recommendation case and the refuse-to-guess case are demonstrable.

### Two demo-data problems found and fixed (engine untouched)

**D-4 — every route was hazard-crossing.** My first demo status closed 1 in 17 edges (~6 %).
Paths traverse 10–20 edges, so phase 1 almost never succeeded and the clear case — the whole
point of two-phase routing — was invisible. Fixed by a sparse lattice (1 in 29 closed), now
guarded by `test_route_demo_status_is_sparse_enough_for_phase1`.

**D-5 — sensor sites were unroutable.** A 40 km grid spans ±360 m per sector, but the sectors are
~9 km apart: SIM-05 was **502 m** from the nearest node, so `find_routes` correctly refused. I
chose **not** to widen the 60 m refusal rule (it exists because routing from a guessed origin is
worse than no route). Instead `build_synthetic_grid` gained `extra_places`, adding sensor sites as
real nodes. All six now snap at **0 m**. Guarded by `test_route_sensor_sites_are_routable`.

**On the 39 % coverage ceiling:** routes between sensor nodes must traverse synthetic connector
edges, which genuinely have **no status record** → `unknown` → not verified. That caps coverage
around 39 % for distant pairs. Marking connectors verified would fabricate road status, so it is
left alone. **This is the honest outcome for this dataset**, and it is why most demo routes are
"served but not recommended".

---

## 5. Part C — map

- Leaflet imported **dynamically**, so it is not in first paint:
  ```
  dist/assets/leaflet-src-BLsinef8.js  148.60 kB │ gzip: 43.32 kB
  dist/assets/index-DD70RIvr.js        251.09 kB │ gzip: 78.57 kB
  ```
  Main bundle **78.57 kB gzipped**, under the ≤120 kB target.
- Draws **only** API-returned coordinates. Nothing smoothed, snapped to a real street, or
  extrapolated.
- Hazard-crossing routes: **red, dashed, 60 % opacity**. Low-coverage: **grey, dotted**. Clear:
  teal solid.
- Tile failure sets a visible banner and the **list view remains fully usable** — the list is the
  canonical representation, and that matters because tile loading is exactly what fails on a bad
  connection during a storm.
- Bilingual: 43 keys, both languages complete (`i18n check passed`).
- No fabricated closures, shelters, flood depths, or official alerts are drawn.

### ⚠ N-5 persists — no browser screenshot

The browser tool refuses private-network targets, so **rendering was not visually verified**.
What *was* verified: TypeScript strict pass, production build, and a bundle scan confirming the
required strings are present:

```
NOT Guayaquil                     PRESENT
No route avoids all closures      PRESENT
Not recommended                   PRESENT
does not mean a road is safe      PRESENT
Fase 2 / No recomendada           PRESENT
approximate terrain tie-break     PRESENT
flood-proof / risk-free / guaranteed safe   absent
```

That is weaker than a screenshot and is stated as such, per the brief.

---

## 6. Commands and results

```
$ cd backend && ../.venv/bin/python -m pytest
230 passed, 2 skipped, 1 warning in 0.83s
```

```
$ ../.venv/bin/python -m coverage run --branch -m pytest -q && coverage report
app/domain/risk.py          250    0   102   0   100%
app/api/models.py            68    0     0   0   100%
app/api/route_models.py      49    0     0   0   100%
app/ingest/persistence.py    72    0    12   0   100%
app/api/main.py             133    4    48   6    94%
app/routing/search.py       226    1    98   4    98%
app/ingest/openmeteo.py     206   23    68   9    88%
app/routing/graph.py        244   23   100   1    89%
app/simulate/sensors.py     123    3    34   4    96%
```

**`domain/` gate holds at 100 % branch.** `persistence.py` and both model modules at 100 %.

```
$ cd frontend && npx tsc -b --force         → exit 0
$ npm run build                             → built in 149ms, 22 modules
$ node src/__i18n-check.mjs                 → 43 keys, both languages, no overclaims
```

Database:
```
0001_init.sql                  OK
0002_rls.sql                   OK
seed.sql                       OK
0005_forecast_snapshots.sql    OK
0004_rls_tests.sql             30 PASS, "=== ALL RLS CHECKS PASSED ==="
```

---

## 7. Requirement-to-test map (Part D, 13 items)

| # | Requirement | Coverage |
|---|---|---|
| 1 | Persistence preserves provenance and missing model-run | `test_persist_preserves_missing_model_run_as_null`, `test_persist_keeps_model_run_when_supplied` |
| 2 | Forecasts distinct from observations | `test_persist_always_kind_forecast` + DB `CHECK` rejecting `observation` (§4) |
| 3 | Duplicate fetches don't corrupt history | `test_persist_duplicate_is_idempotent`, `test_persist_different_fetch_time_creates_new_row` + live SQL (§3) |
| 4 | Route API schema and error handling | `test_route_response_shape`, `test_route_requires_all_coordinates`, `test_route_rejects_coordinates_outside_guayaquil` |
| 5 | Synthetic status propagates | `test_route_synthetic_status_propagates` |
| 6 | Phase 1 never includes closed edges | `test_route_phase1_never_crosses_a_closure` |
| 7 | Phase-2 closure routes never recommended | `test_route_hazard_crossing_never_recommended` |
| 8 | Low/zero coverage never recommended | `test_route_low_coverage_never_recommended` |
| 9 | Elevation final tie-break only | `ROUTE-8`/`ROUTE-9` still green (unchanged); API exposes `elevation_used_as_tiebreak` |
| 10 | No secrets or privileged fields | `test_route_response_excludes_privileged_fields` + M6 recursive walk |
| 11 | Map loading/unavailable/error/normal | Loading + error + refusal states implemented; **render not browser-verified** (N-5) |
| 12 | EN/ES safety strings complete | `i18n check passed: 43 keys` |
| 13 | O-7/O-8 constraints unchanged | `risk.py` untouched (100 % cov, same 250 statements); routing search unchanged |

---

## 8. Explicit status of the tracked items

| ID | Status after M7 |
|---|---|
| **O-7** | **OPEN, unchanged.** `app/domain/risk.py` not edited — verified 250 statements, 100 % branch. No risk level displayed anywhere. |
| **O-8** | **OPEN, provisional.** Stale-closure rule preserved. `app/routing/search.py` unchanged; `test_ROUTE_7_stale_status_removes_verification` still green. |
| **N-1** | **OPEN, now correctly persisted.** `model_run_at` stored as NULL; DB constraint prevents it exceeding `fetched_at`; no fallback to fetch time. |
| **N-2** | **OPEN.** No mutation endpoint exists in the app at all (`test_no_mutation_routes_exist_after_m7`). Persistence is a **library**, not a route — deliberately not wired to HTTP while authorization trusts a session setting. |
| **N-3** | **OPEN.** `build_from_osm_json` still skipped with a reason. Graph remains synthetic. |
| **N-5** | **OPEN.** No browser screenshot possible; verified by build + bundle scan only. |
| **N-6** (new) | **Persistence is not connected to the API.** The service is implemented and proven against PostgreSQL, but no HTTP route writes to it. That is intentional given N-2 — a privileged write behind an unverified role would be exactly the bug the project keeps warning about. |
| **N-7** (new) | **Demo status is generated, not read from `road_status`.** No database read path exists in the API yet, so route statuses come from a deterministic in-process lattice. They are labelled seed data in the response; they are not a live feed. |

---

## 9. What is functional versus merely scaffolded

**Functional (verified):**
- persistence service — insert, dedupe, partial validation, failure handling, append-only
- the SQL that backs it, proven against PostgreSQL 16.2
- route API end to end, including refusal and recommendation paths
- bilingual dashboard + route screen, TypeScript strict, production build
- Leaflet code-split out of first paint

**Scaffolded or unverified:**
- **map rendering visually** — not screenshot-verified (N-5)
- **persistence wired to HTTP** — service exists, route does not (N-6)
- **status from the database** — generated in-process instead (N-7)
- Supabase/PostGIS behaviour, concurrency, load

---

## 10. Recommended next milestone

**M8 — wire the read path to PostgreSQL.** Two things, in this order:

1. **Read `road_status` for the route API** (closes N-7). Read-only, no authorization risk
   beyond what already exists, and it makes the demo statuses real database rows.
2. **A server-side ingestion job** that calls `persist_forecast` with a trusted connection
   (closes N-6 without adding an HTTP write path).

**Do not** add the admin console or any HTTP mutation until N-2 is resolved with server-side
identity derivation.

---

## 11. Standing statements

- **Risk model is an unvalidated heuristic** and is not displayed (O-7 open).
- **Road graph is synthetic** — 153 nodes / 260 edges / 43.1 km of generated grid, disclosed on
  the route screen and in every response.
- **All sensor readings are SIMULATED.**
- **No route is claimed safe.** Coverage is stated; hazard crossings are labelled; low coverage
  is never recommended.
- **No live flood map, closures, shelters, or official alerts** exist in this project.
- No commits, pushes, deployments, or destructive migrations. Still not a Git repository.
