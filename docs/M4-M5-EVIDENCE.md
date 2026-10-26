# M4 + M5 — Evidence Report

**Date:** 2026-10-26
**Block:** M4 (routing integration) + M5 (rainfall ingestion + simulated sensors)
**Verdict:** **M4 PASSED. M5 PASSED.** One new limitation discovered and recorded (§7).
**O-7 remains OPEN. O-8 remains OPEN and provisional.** Neither was resolved, as instructed.

---

## 1. Baseline before any change

```
86 passed, 1 skipped in 0.13s
```

Confirmed before editing, per hard rule 1.

---

## 2. Files changed

### Created

| Path | Purpose |
|---|---|
| `backend/app/ingest/openmeteo.py` | Open-Meteo adapter — injected HTTP, unit normalisation, no invention on failure |
| `backend/app/ingest/__init__.py` | package marker |
| `backend/app/simulate/sensors.py` | deterministic simulated sensor adapter, health from cadence, data-mode helper |
| `backend/app/simulate/__init__.py` | package marker |
| `backend/tests/integration/test_routing_integration.py` | 14 cross-module routing safety tests |
| `backend/tests/integration/__init__.py` | package marker |
| `backend/tests/unit/test_openmeteo.py` | 40 adapter tests, offline by default |
| `backend/tests/unit/test_sensors.py` | 28 simulation tests |
| `docs/M4-M5-EVIDENCE.md` | this report |

### Modified

| Path | Change |
|---|---|
| `backend/tests/unit/test_openmeteo.py` | one helper fixed (`is None` vs truthiness) — see §9, D-1 |
| `PHASES.md` | status rows updated |

### Not modified

`backend/app/domain/risk.py` (no weight, formula, renormalisation, trend cap or floor touched),
`backend/app/routing/graph.py` and `search.py` (no behaviour change — M4 added tests only),
`backend/requirements.txt` (pins unchanged), `frontend/*` (no feature work), all Stage 1–4 documents.

---

## 3. Commands run and real results

```
$ cd backend && ../.venv/bin/python -m pytest
159 passed, 2 skipped in 0.23s
```

```
$ ../.venv/bin/python -m coverage run --branch -m pytest -q
$ ../.venv/bin/python -m coverage report --include="app/*"
Name                       Stmts   Miss Branch BrPart  Cover
app/domain/risk.py           250      0    102      0   100%
app/ingest/openmeteo.py      206     23     68      9    88%
app/routing/graph.py         229     23     90      0    88%
app/routing/search.py        226      3     98      6    97%
app/simulate/sensors.py      123      4     34      4    95%
TOTAL                       1034     53    392     19    94%
```

**The `domain/` 100 % branch gate still holds** — untouched and still green.

```
$ cd frontend && npx tsc -b --force    → exit 0
$ npm run build
✓ 15 modules transformed.
dist/assets/index-B7Nm3CQx.js  220.03 kB │ gzip: 68.86 kB
✓ built in 126ms
```

Frontend builds unchanged; no new frontend features added, per instruction.

### Counts

| | Count |
|---|---|
| Passed | **159** |
| Failed | **0** |
| Skipped | **2** (both named and justified in §8) |
| Test files | 5 (`test_risk`, `test_routing`, `test_openmeteo`, `test_sensors`, `test_routing_integration`) |

---

## 4. M4 — routing integration

### What was already correct (verified, not assumed)

The M3 implementation already satisfied M4-A and M4-B. I re-inspected rather than trusting the prior
report:

- Phase 1 excludes closed edges by an **edge predicate**, not a cost multiplier; `cost_factor()` raises
  if asked to price a closure.
- Phase 2 runs only when phase 1 is empty; phase-1 variants are generated within phase 1.
- Route label uses the exact permitted phrase **"no known hazards"**.
- Coverage is length-weighted on verified-and-fresh status only; closed and unknown never count as
  verified.
- D29 sort key is `(class_rank, band_rank, duration_s, ±elevation)`; tie-break is detected and disclosed
  via `elevation_used_as_tiebreak`.
- Synthetic provenance appears in both `Route.notes` and `RouteResponse.notes`.

### What M4 added — 14 cross-module tests

The audit found these behaviours **implemented but untested**, which is the same as unverified:

| Gap found | Test added |
|---|---|
| Nothing asserted that a phase-2 route never coexists with a phase-1 route | `test_phase2_never_mixed_with_phase1`, `test_phase2_response_is_homogeneous` |
| **Nothing tested the dangerous direction of evidence loss** — that withdrawing verified status cannot *promote* a route to recommended | `test_removing_verified_status_never_improves_eligibility` (walks coverage from 100 % down to 0 % in 5 steps and asserts recommendation never reappears) |
| `unknown` vs `affected` ranking unverified | `test_unknown_status_is_not_better_than_affected` |
| Stale closure exclusion implied but not asserted end-to-end | `test_stale_closure_still_excluded_from_phase1`, `test_stale_closure_lowers_coverage_even_in_phase2` |
| Synthetic flag on refusals unverified | `test_refusal_also_carries_synthetic_flag` |
| Disconnected vs "closed-only connection" not distinguished by test | `test_disconnected_graph_refuses_with_no_path_reason`, `test_closed_only_connection_is_not_reported_as_no_path` |
| Elevation overriding class/band only unit-tested | `test_elevation_cannot_make_a_closure_route_eligible`, `test_elevation_tiebreak_direction_only_affects_equal_routes` |
| No guard against *stronger* language than the banned list | `test_no_stronger_than_supported_language` (also checks "guaranteed", "flood-proof", "risk-free") |

**The second row is the one that mattered.** It is the route-level analogue of the risk bug fixed in M2:
losing evidence must never improve an outcome. It passes, and it would have caught the reverse.

### M4-C preservation items

- `build_from_osm_json` **remains marked unverified** — the skipped test is kept and its reason names this
  document. No OSM extract was invented or run.
- No test was weakened. The only test edits were one helper bug (§9 D-1) and one wrong premise from M3.

---

## 5. M5 — Open-Meteo adapter

### Design

- **Injected HTTP**: `fetch_forecast(..., http_get=...)`. Production default is `urllib_get`; tests inject
  a fake, so **the suite never touches the network**.
- **One normalisation point**: `_normalise_units` converts to mm and records the original unit. An unknown
  or missing unit is an **error**, never a guess.
- **Forecast is never an observation**: every `HourlyRain.kind` is `"forecast"`, hardcoded. The URL never
  requests `past_days`.
- **Failure never invents**: `ForecastResult(ok=False, hours=())` with an honest error and the note *"no
  values were invented; caller must show cached data or nothing"*.
- **No heavy-rain classification** anywhere (B13). `describe()` states forecast status, total mm, peak
  hourly mm and fetch age — nothing more.

### Validation cases covered (40 tests)

| Category | Cases |
|---|---|
| Normal | parse shape, 3 values, totals, probability, units |
| Units | mm pass-through; inch → mm conversion with note; **missing unit raises**; **unknown unit raises** |
| Missing values | nulls preserved as gaps and excluded from totals; negative precip dropped; absurd precip dropped; out-of-range probability dropped |
| Empty | empty `time` array raises |
| Malformed | provider error object; missing hourly; missing both variables; non-object payload; length mismatch; unparseable timestamp |
| Transport | status 0 (network), 429 (rate limit), 500, 404, empty body, non-JSON body, unusable payload — **all returned, never raised** |
| Provenance | source, fetch time, coordinates, original unit survive failure |
| Staleness | `age_seconds` measures fetch age, distinct from model age |
| Presentation | `describe()` says "forecast (not an observation)", shows mm, never says "heavy"; failure shows no millimetres |
| URL | requests probability + `timezone=UTC`, never `past_days`; rejects out-of-range coords and absurd horizons |

---

## 6. M5 — Simulated sensor adapter

### Design

- **`simulated=True` is not a default a caller can flip.** `SensorReading.simulated` is typed
  `Literal[True]` and hardcoded by the single factory. A test asserts assignment raises.
- **Thresholds are the caller's.** `SensorSpec.threshold_m` must be positive; the module never scales or
  invents one. A test proves the same profile keeps the same *fraction* of threshold when the threshold
  changes, so a threshold edit reformulates nothing silently.
- **Determinism via SHA-256**, not `random` — stable across interpreter versions and call order.
- **Health derived from cadence**, never a stored flag: `ok` / `degraded` / `offline`.
- **Gaps preserved** (`include_gaps=True`), never interpolated.
- **No publication path**: a test scans the module's public API for `publish`, `create_alert`, `dispatch`,
  `notify` and asserts none exist.

### Tests (28)

Determinism (same inputs → identical output; different seeds differ; series and bulk deterministic) ·
SIMULATED labelling on readings, series, and before any number in `describe_series` · threshold
pass-through and rejection of non-positive values · unknown profile rejected · profile behaviour (`dry`
never exceeds threshold over 24 h; `surge` exceeds somewhere; no negative depths across 48 h) · gaps
preserved · health transitions (no readings → offline; old → offline; recent → ok; 5-minute-old with 60 s
expected interval → degraded) · **`SIM-3`: `LIVE` unreachable while any sensor is simulated**.

---

## 7. ⚠ Live API smoke test — **ran, and found a real gap**

The instruction allowed a small read-only smoke test if safe. It was safe, so it was run:

```
GUARADAR_LIVE_API=1 pytest tests/unit/test_openmeteo.py::test_live_open_meteo_smoke  → 1 passed
```

Direct verification against the real provider (`api.open-meteo.com`, Guayaquil −2.17/−79.92, 6 h):

```
LIVE OK: True | hours: 6 | source: open-meteo
units original: mm | model_run_at: None
total_mm: 3.6 | max_hourly: 1.3
all kind=forecast: {'forecast'}
first 3: [('2026-10-25T19:00:00+00:00', 0.1, 38.0),
          ('2026-10-25T20:00:00+00:00', 0.1, 54.0),
          ('2026-10-25T21:00:00+00:00', 0.4, 67.0)]
describe: Forecast (not an observation): 3.6 mm total over 6 hours, peak 1.3 mm in one hour.
          Retrieved 0 min ago.
notes: ('provider response includes no model run time; only the fetch time is known',)
```

### The gap this exposed — **N-1 (new limitation)**

**Stage 3 §11 requires the UI to display both `fetched_at` and the upstream `model_run_at`,** on the
reasoning that "a fresh fetch of an old model run is still old information". The default Open-Meteo
forecast response **does not include a model run time**. `model_run_at` is therefore `None`, and the
adapter says so explicitly rather than implying it knows the model vintage.

Consequences, stated plainly:

- The "model run age" distinction **cannot be shown** with the current endpoint.
- The interface therefore displays fetch age only. That is weaker than the approved design promised.
- Options are (a) accept fetch-age-only and amend Stage 3 §11, (b) probe a different Open-Meteo product
  that does expose run metadata, or (c) compare successive fetches to infer model rollover. **(c) invents
  an inference and should not be done.** This needs an owner decision; it is recorded, not resolved.

**The live test is opt-in** (`GUARADAR_LIVE_API=1`) and skipped by default so the suite stays
network-independent, per hard rule 12.

---

## 8. Skipped tests — both named and justified

| Test | Reason |
|---|---|
| `test_live_open_meteo_smoke` | opt-in live call; run manually once (§7), disabled by default so the suite needs no network |
| `test_build_from_osm_json_real_payload` | **no OSM extract was ever run.** The importer remains unverified. A skipped test is not evidence that it works. |

---

## 9. Defects found and fixed

| # | Defect | Surfaced by | Fix |
|---|---|---|---|
| **D-1** | My test helper `payload()` used `times or [...]`, so passing `[]` (the meaningful "no hours" case) silently substituted three default timestamps. The empty-payload test then asserted the wrong error | `test_empty_time_array_raises` expected "time missing or empty", got "length mismatch" | Helper changed to `is None` checks. **Test bug, not code bug** — the adapter correctly rejected both shapes. |
| **D-2** | `DEFAULT_FRESHNESS` imported from `search` but defined in `graph` | import error on collection | Import corrected |
| **D-3** | `INSUFFICIENT_EVIDENCE_BELOW`/`BAND_MOD` style stray import in the integration file | collection error | Removed |

No implementation defect was found in M3's routing code during the M4 audit. That is worth stating as a
result rather than a relief: the two-phase design held under 14 new cross-module tests without change.

---

## 10. Provenance and freshness — what is represented, and the gaps

Represented (schema in `supabase/migrations/0001_init.sql` plus the new adapters):

| Property | Where |
|---|---|
| source / provider | `ForecastResult.source`; `weather_cache` row identity |
| forecast vs observation | `HourlyRain.kind`; never blurred |
| source timestamp | `HourlyRain.at` (UTC, tz-aware) |
| retrieval timestamp | `ForecastResult.fetched_at` |
| unit | `provider_units_original`, plus normalised mm |
| validation status | dropped-value counts in `notes` |
| simulated flag | `SensorReading.simulated` (hardcoded `True`), `simulated` column default `true` |
| stale / unknown | `StatusIndex` staleness; sensor `health`; `age_seconds` |

**Schema gaps identified, not fixed** (no destructive migration was run, per instruction):

1. **No `model_run_at` available from the provider** — column exists and stays `NULL`. See N-1.
2. **No validation-status column.** Dropped-value counts live in the in-memory result `notes` only. If the
   API is to persist "we discarded 2 implausible hours", a nullable `validation_notes jsonb` on
   `weather_cache` would carry it. **Proposed, not applied.**
3. **No `ingested_by` on `sensor_readings`** to record which process wrote a simulated value. The
   `simulated` default covers the honesty requirement; this is an audit nicety.
4. **No unit column on `weather_cache`.** The payload is stored as JSONB so the original unit survives
   inside it, but it is not queryable. Acceptable for the demo; note it.

None of these blocks M4/M5. They are recorded so a later migration is deliberate rather than improvised.

---

## 11. API boundary — deliberately not built

M5-D offered an endpoint *if a pattern already existed*. **It does not**: there is no FastAPI app yet
(M0 scaffolded dependencies only). Rather than invent a public contract ahead of the approved design, the
adapters are isolated modules with typed data classes.

**Privileged ingestion was therefore kept internal.** This is also required by the `current_app_role()`
caveat: since authorization currently trusts a session setting, exposing an ingestion endpoint would be a
privileged write behind an unverified role. **Documented as a block, not patched around.**

A test (`test_simulated_module_cannot_publish`) asserts the simulation module exposes no publication path.

---

## 12. O-7 and O-8 status

### O-7 — risk formula conflict: **OPEN, unchanged**

- `backend/app/domain/risk.py` was **not edited** in this block. Verified: weights still
  `0.30/0.30/0.15/0.15/0.10`, `trend_bonus` still capped at 0.5, rain floor still absent.
- No new interpretation was added. **`RISK-8b` prose is still contradicted by the documented formula** and
  is still reported at runtime via `spec_conflicts`.
- Nothing in M4/M5 publishes or presents the risk level as an approved safety rule. The adapters supply
  inputs; they make no severity claim.

### O-8 — stale closure semantics: **OPEN, provisional, not user-approved**

- Conservative behaviour preserved: a stale closure **stays excluded from phase 1**; staleness only
  removes its verified status, lowering coverage.
- Now **locked by test** (`test_stale_closure_still_excluded_from_phase1`,
  `test_stale_closure_lowers_coverage_even_in_phase2`) so it cannot drift while awaiting a decision.
- The exact ambiguity remains: §9 route-search step 2 says `stale → ×1.1` (implying traversable), while
  line 852 says stale closures reduce coverage. The second reading was chosen because the alternative lets
  a 3-hour-old closure be served as `Eligible`.
- **Not marked resolved. Not marked approved.**

---

## 13. Gates — all eight

| Gate | Result |
|---|---|
| 1. Full suite incl. domain coverage gate and routing | ✅ 159 passed, 2 skipped; `domain/` at 100 % branch |
| 2. Strict TS + production build | ✅ `tsc -b --force` exit 0; build 68.86 kB gzip |
| 3. Dependency pins and locks unchanged without justification | ✅ `requirements.txt` untouched; no new dependency added at all |
| 4. No tests weakened, unexpectedly skipped, or network-dependent | ✅ 2 skips both justified; suite offline by injected client |
| 5. Diff reviewed for secrets, fake-real data, overclaiming language, client-controlled auth | ✅ no secrets; simulated data labelled; stronger-language test added; no new auth surface |
| 6. No commits, pushes, deployments | ✅ still not a Git repository; nothing deployed |
| 7. Evidence report | ✅ this document |
| 8. Any failure fixed or reported | ✅ three defects fixed (§9); one new limitation recorded (§7 N-1) |

---

## 14. Remaining blockers and recommended next block

| # | Blocker | Blocks |
|---|---|---|
| **O-7** | `RISK-8b` prose vs formula | publishing any risk level as a settled safety rule |
| **O-8** | stale-closure semantics | finalising routing policy (provisional behaviour is safe and tested) |
| **N-1** | no provider model-run time | the "model vintage" display Stage 3 §11 promised |
| **N-2** | `current_app_role()` trusts a session setting | any authenticated endpoint, including ingestion and admin |
| **N-3** | `build_from_osm_json` unverified | claiming the graph is Guayaquil's real network |
| **N-4** | no FastAPI app yet | any API-level integration; provenance persistence beyond the adapters |

**Recommended next block:** the smallest thing that makes the adapters visible — a FastAPI service layer
with `GET /api/public/forecast` and `GET /api/public/sensors`, both read-only, both carrying the provenance
envelope, with **no mutation endpoints** until N-2 is resolved. That unlocks the public dashboard (block 6)
without touching authorization.

**Not started:** M6, public dashboard, map screen, admin console, deployment. **Stopping here.**

---

## 15. Standing statements

- **The risk model remains an unvalidated heuristic.** It has never been checked against observed flood
  depths. Nothing in this block changes that.
- **The road graph is synthetic** — 147 nodes / 254 edges / 40.3 km generated from sector centres, not
  Guayaquil's network. Coverage percentages describe the demo dataset only.
- **All sensors are simulated.** No real telemetry exists in this project.
- **No route is safe merely because a path exists.**
- No commits, no pushes, no deployments, no external services, no destructive migrations.
