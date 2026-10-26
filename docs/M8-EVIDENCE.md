# M8 — Persisted Road Status + Trusted Forecast Ingestion: Evidence

**Date:** 2026-10-26
**Block:** M8 (A: database-backed route status · B: controlled ingestion job)
**Verdict:** **PARTIAL PASS.** Both parts implemented and tested. **Ingestion performs no real
database write in the shipped configuration** — deliberately, because N-2 is open. Road status
read path works against real PostgreSQL but **maps to zero graph edges in the current dataset**,
for a reason that is documented rather than papered over.
**Scope held:** no admin console, no mutation endpoint, no deployment, no commit, no destructive
migration.

---

## 1. Baseline before any change

```
230 passed, 2 skipped
```
`app/domain/risk.py` at 100 % branch. Confirmed before editing.

---

## 2. Files changed

### Created

| Path | Purpose |
|---|---|
| `backend/app/routing/status_repository.py` | read-only `road_status` adapter — **100 % coverage** |
| `backend/app/ingest/job.py` | controlled server-side ingestion orchestration |
| `backend/tests/integration/test_m8_status_repository.py` | 26 tests: 24 mocked + 2 real-PostgreSQL |
| `backend/tests/integration/test_m8_ingestion.py` | 22 tests |
| `docs/M8-EVIDENCE.md` | this report |

### Modified

| Path | Change |
|---|---|
| `backend/app/api/main.py` | `load_route_status`, `get_status_fetch`, `STATUS_PERSISTENCE_ENABLED`; route response reports `status_source` |
| `backend/app/api/route_models.py` | `status_source` + `status_records_matched` fields |
| `backend/app/routing/graph.py` | `is_fresh` now honours `EdgeStatus.verified` (see §6) |
| `PHASES.md` | status rows |

### Not modified

`app/domain/risk.py` (**O-7 untouched**) · `app/routing/search.py` (**two-phase logic unchanged**;
only consumed) · `requirements.txt` (12 pins, **no dependency added**) · `package.json` ·
migrations 0001–0005 · all Stage 1–4 documents.

---

## 3. Part A — the mapping problem, and why zero matches is the honest answer

### What I found

| | Identifier range | Generator |
|---|---|---|
| Router graph `Edge.id` | **0 … 259** | `build_synthetic_grid()` |
| `road_segments.id` / `road_status.road_segment_id` | **1001 … 3050** | `seed.sql` ordinal arithmetic |

These are **two independent synthetic generators**. They share no identifier, no geometry, and no
coordinate overlap.

### The three options, and the decision

| Option | Verdict |
|---|---|
| **(a) map by index** (edge 0 ↔ segment 1001) | **REJECTED.** Fabricates correspondence: segment 1001's reason text describes a closure on a road that does not exist at that place. Presenting it as verified status for an unrelated edge is exactly the fabrication this project forbids. |
| **(b) map by name / coordinates / nearest distance** | **REJECTED by the brief**, and rightly — fuzzy matching silently manufactures false verification. |
| **(c) map by an explicit shared identifier** | **ADOPTED.** Join key is `graph_edge.id == road_status.road_segment_id`. `from_edges` already preserves OSM way ids as `Edge.id`, so a **real OSM extract maps cleanly**. |

### Consequence, stated plainly

Against the current synthetic pair the join matches **zero** rows. The API therefore reports:

```json
"status_source": "seed_generator_fallback_no_mapping",
"status_records_matched": 0
```

and a provenance note explaining that no mapping exists and none was invented.

**This is a partial pass on the letter of Part A and a full pass on its intent.** Requirement 1
of Part A says "use actual persisted records rather than silently regenerating status". The read
path does use persisted records — proven below — but for *this* dataset they all refer to segments
that are not graph edges, so applying them would leave every route at 0 % coverage. The fallback to
the labelled generator is a demo convenience, and I am recording it as a concession rather than a
success: **the response says which source it used, every time, and never claims generated status is
persisted.**

### Proven against real PostgreSQL 16.2

```
=== against SEEDED segment ids (correct join key) ===
 fetched: 5 | matched: 5 | ok: True
   seg 1001: closed
   seg 1002: affected
   seg 2001: affected
   seg 3001: closed
   seg 3002: unknown

=== against SYNTHETIC graph edge ids (the real N-7 situation) ===
 fetched: 5 | matched: 0 | unmapped: 5
 notes[0]: 5 persisted status record(s) reference segments that are not edges in this graph
           — not remapped, because guessing the correspondence would fabricate verification
```

The `unknown` on 3002 is correct: the seeded row genuinely records `unknown`, which the adapter
drops rather than upgrading.

### Provenance states carried through

| State | Behaviour | Test |
|---|---|---|
| **verified** (open/affected, fresh) | applied, counts toward coverage | `test_verified_open_counts_toward_coverage` |
| **reported** (source='report') | applied like any record; provenance column preserved | `test_record_parses_valid_row` |
| **stale** (past `review_at`) | applied but **not** verified coverage | `test_stale_record_no_longer_counts_as_verified` |
| **closed** | applied, excluded from phase 1, **never** verified coverage | `test_closed_is_not_verified_coverage` |
| **unknown** | dropped; edge stays default-unknown | `test_unknown_status_record_adds_nothing` |
| **missing** | stays `unknown`, never clear | `test_missing_record_stays_unknown` |
| **DB error** | degrades to all-unknown, reported | `test_load_db_error_degrades_to_unknown_not_clear` |
| **empty result** | all-unknown, reported | `test_load_empty_result_is_all_unknown` |

### O-8 preserved

A stale closure **still excludes the edge from phase 1**; staleness only removes its coverage
credit. Asserted directly by `test_stale_closure_remains_excluded_o8`:
```
is_closed(3) is True       ← still excluded, ageing does not reopen the road
is_verified(3) is False    ← but no coverage credit
```

---

## 4. Part B — controlled ingestion

### Shipped configuration: **writes disabled**

```python
DATABASE_WRITES_ENABLED = False   # N-2 is open
```
Guarded by `test_writes_disabled_by_default`, so the default cannot drift silently.

With writes disabled the job still performs the **entire** validate-and-normalise path, then
reports `would_persist` — never `persisted`. `test_disabled_run_reports_would_persist_not_persisted`
asserts the injected connection is **never touched** (`db.calls == 0`).

### Enabled mode works, with an injected trusted connection

```
test_enabled_run_persists                       → outcome=persisted, snapshot_id=1
test_duplicate_fetch_is_reported_as_duplicate   → outcome=duplicate, 1 row, history intact
test_enabled_without_connection_refuses...      → outcome=db_failed, refuses to no-op
```

### Authorization gate

- `current_app_role()` is **not** consulted anywhere in the ingestion path.
- No role, user id, or verification flag is accepted from a caller.
- `DATABASE_WRITES_ENABLED` is a module constant, not a request parameter.
- **No credentials in code, logs, fixtures, or this report.** `test_ingestion_result_never_contains_credentials`
  sets a secret-shaped env var and asserts it never appears in a result.
- The log line emits only `sector`, `outcome`, `hours`, `model_run_supplied`.

### Not reachable from HTTP

`test_job_is_not_exposed_through_any_http_route` walks every route and asserts no path contains
`ingest|persist|job|snapshot` and no mutation verb exists.
`test_job_module_exposes_no_web_handler` asserts the module has no `app`/`router`/`endpoint`.

### N-1 preserved

`test_model_run_not_supplied_is_reported_false` and the persistence tests from M7 confirm
`model_run_at` is persisted as NULL. No inference from `fetched_at` anywhere; the DB constraint
`model_run_not_after_fetch` remains the backstop.

### Provider and DB failure handling

| Case | Outcome | Test |
|---|---|---|
| timeout / 429 / 500 / 404 | `provider_failed`, no write | 4 parametrised cases |
| malformed body | `provider_failed`, no write | `test_malformed_provider_body_is_not_persisted` |
| empty hours | `provider_failed` (not "zero rain") | `test_empty_hours_is_nothing_usable_not_zero_rain` |
| DB failure | `db_failed`, reported not raised | `test_database_failure_is_reported_not_raised` |
| one target fails | others still run | `test_ingest_all_continues_after_one_failure` |
| adapter raises | isolated | `test_ingest_all_isolates_unexpected_exceptions` |

---

## 5. Commands and results

### Without a database (default — what CI would run)

```
$ cd backend && ../.venv/bin/python -m pytest
283 passed, 4 skipped, 1 warning in 0.90s
```
The 4 skips: 2 pre-existing (live OSM builder, live Open-Meteo opt-in) + 2 real-PostgreSQL tests.

### With real PostgreSQL 16.2 (opt-in via env)

```
$ GUARADAR_PG_DSN="postgresql://postgres@/m8?host=/tmp&port=55432" \
  GUARADAR_PSQL=/tmp/pgx/.../psql ../.venv/bin/python -m pytest
285 passed, 2 skipped, 1 warning in 0.91s
```

### PostgreSQL / RLS assertions

Schema rebuilt from scratch: `0001_init` → `0002_rls` → `0005_forecast_snapshots` → `seed` — all OK,
`road_status` holds 5 seeded rows.

```
0004_rls_tests.sql  →  30 PASS, "=== ALL RLS CHECKS PASSED ==="
```

### Coverage

```
app/domain/risk.py                 250    0   102   0   100%
app/api/models.py                   68    0     0   0   100%
app/api/route_models.py             51    0     0   0   100%
app/ingest/persistence.py           72    0    12   0   100%
app/routing/status_repository.py    96    0    30   0   100%
app/ingest/job.py                   72    3    18   2    94%
app/routing/search.py              226    1    98   4    98%
app/simulate/sensors.py            123    3    34   4    96%
app/routing/graph.py               246   23   102   1    89%
app/ingest/openmeteo.py            206   23    68   9    88%
app/api/main.py                    164   13    62  11    88%
```

**`domain/` gate holds at 100 % branch.** `status_repository.py` — the new security-relevant
module — is at **100 %**.

### Frontend

```
$ npx tsc -b --force                → exit 0
$ npm run build
dist/assets/leaflet-src-*.js   148.60 kB │ gzip: 43.32 kB
dist/assets/index-*.js         251.09 kB │ gzip: 78.57 kB
✓ built in 143ms
$ node src/__i18n-check.mjs         → 43 keys, both languages, no overclaims
```

### Diff inspection

| Check | Result |
|---|---|
| Secrets in tree | none |
| Dependency changes | **none** — 12 pins unchanged, no new package |
| Mutation verbs | **none** (`rg "@app\.(post\|put\|patch\|delete)" app/` → empty) |
| Weakened tests | none; 3 tests were **tightened** (§6) |
| Commits / pushes / deployments | **none** — still not a Git repository |
| Destructive migrations | **none** — no new migration this block at all |

---

## 6. Defects found and fixed

| # | Defect | Surfaced by | Fix |
|---|---|---|---|
| **D-1** | **The synthetic-network disclosure was silently dropped** when I appended status notes — it replaced note[0] instead of preserving the invariants | `test_route_synthetic_status_propagates` (an M7 test) failed | Invariant notes moved to a frozen `INVARIANT_NOTES` list and **prepended** unconditionally. Status notes are appended, never substituted. |
| **D-2** | **Disabled ingestion reported `duplicate` instead of `would_persist`.** `persist_forecast` returns `duplicate` whenever `execute()` returns `None`, and the no-op execute also returned `None` — so a run that never consulted the database claimed to have found a duplicate | 3 ingestion tests failed | The disabled path now stops **before** the write entirely and reports `would_persist`. A test asserts the connection is never touched. |
| **D-3** | **Two disagreeing staleness clocks.** The repository judged staleness by `review_at`; `StatusIndex` judged it by `set_at` + freshness. A record past `review_at` but recent by `set_at` counted as verified | `test_stale_record_no_longer_counts_as_verified` | `EdgeStatus.verified` existed but was never read. `StatusIndex.is_fresh` now honours it, so the repository can express per-record expiry **without back-dating `set_at`** (which would falsify a stored timestamp). |
| **D-4** | `_no_op_execute` became dead code once D-2 was fixed | manual inspection | Removed rather than left as misleading scaffolding |
| **D-5** | `fetch` was called inside the handler instead of being a FastAPI dependency, and `from app.routing.status_repository import ...` was missing | `NameError` at runtime | Both corrected; the route now takes `fetch: FetchFn \| None = Depends(get_status_fetch)` |

**D-1 is the important one.** It was a regression against an *existing* M7 test: my rewiring
quietly removed the disclosure that the road network is synthetic. The test caught it, and the fix
makes the disclosure structurally un-droppable rather than relying on me remembering.

**D-3 is the subtle one.** Two modules each had a defensible staleness rule that disagreed. The
resolution deliberately avoids the tempting shortcut of rewriting `set_at`.

---

## 7. Explicit status of tracked items

| ID | Status after M8 |
|---|---|
| **O-7** | **OPEN, unchanged.** `app/domain/risk.py` not edited — verified 250 statements, 100 % branch. No risk level displayed anywhere. |
| **O-8** | **OPEN, provisional, unapproved.** Stale closures still excluded from phase 1; now asserted through the **database path** as well (`test_stale_closure_remains_excluded_o8`). `routing/search.py` unchanged. |
| **N-1** | **OPEN, preserved.** `model_run_at` persisted as NULL; never inferred; DB constraint `model_run_not_after_fetch` remains the backstop. |
| **N-2** | **OPEN, not fixed, not claimed fixed.** No mutation endpoint exists. Ingestion writes are disabled by default and gated behind a module constant. `current_app_role()` was not consulted or modified. |
| **N-5** | **OPEN.** No browser screenshot; frontend verified by build + bundle scan only. |
| **N-6** | **PARTIALLY CLOSED.** The ingestion job exists, is tested, and works with an injected trusted connection. **It performs no real write in the shipped configuration** because enabling writes requires a trusted connection that does not yet exist. |
| **N-7** | **PARTIALLY CLOSED.** The read path exists and is proven against real PostgreSQL, but maps **zero** records to graph edges in the current dataset (§3). Reported in every response as `status_source` + `status_records_matched`. |
| **N-8** (new) | **`road_segments` and the routing graph are two unrelated synthetic datasets.** Until a single source feeds both — i.e. a real OSM extract that yields both the graph and the `road_segments` rows — persisted status cannot apply to routes. **This is the blocker for a real N-7 fix**, and it is a data-source task, not a code task. |
| **N-9** (new) | **Persistence and status reads run through `psql` subprocesses in tests**, not a driver. Adequate for verification, not for production. A real deployment needs a connection pool. |

---

## 8. What is functional versus partial

**Functional and verified:**
- status repository: fetch, validate, map, staleness, all failure paths — 100 % coverage
- real-PostgreSQL read of 5 seeded records, correct statuses (closed/affected/unknown)
- refusal to remap unmatched segments, with a reported count
- ingestion job: full validate path, disabled-mode honesty, enabled-mode write, dedupe, all
  provider/DB failure modes
- no mutation endpoint; job not reachable from HTTP
- O-8 stale-closure rule asserted through the database path
- invariant disclosures (synthetic network, no-known-hazards, coverage scope) structurally preserved

**Partial:**
- **N-6:** ingestion is wired but writes are off by design
- **N-7:** read path works; **zero mapping** for the current dataset (N-8)

**Not done:**
- browser verification (N-5)
- any Supabase-specific behaviour — **local PostgreSQL only**; this is not evidence that Supabase
  RLS is secure
- concurrency, load, connection pooling

---

## 9. Recommended next milestone

**M9 — unify the road data source (closes N-8, which unblocks N-7).** The single highest-value
step is for the graph and `road_segments` to come from **one** OSM extract, so `Edge.id` is an OSM
way id on both sides and persisted status applies to routes by construction. Without that, the
status read path will keep matching zero rows no matter how good it gets.

Only after that: wire a trusted pooled connection for ingestion (closes the remainder of N-6), then
the admin console once N-2 is resolved with server-side identity derivation.

---

## 10. Standing statements

- **Risk model is an unvalidated heuristic** and is not displayed (O-7 open).
- **Road graph is synthetic** — and now also demonstrably *disjoint* from `road_segments` (N-8).
- **All sensor readings are SIMULATED.**
- **No route is claimed safe.** Coverage stated, hazard crossings labelled, low coverage never
  recommended.
- **No real road status, closures, sensor stations, or Guayaquil-wide coverage** is invented or
  implied.
- Ingestion performed **no real database write** in the shipped configuration.
- No commits, pushes, deployments, or destructive migrations.
