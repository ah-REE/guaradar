# M6 — Read-Only API + Public Dashboard: Evidence

**Date:** 2026-10-26
**Block:** M6 (read-only API + first functional public dashboard)
**Verdict:** **PASSED** — 198 tests, 2 skipped; API→dashboard verified live end to end.
**Scope held:** no mutation endpoints, no admin console, no map, no risk level displayed.

---

## 1. Baseline before any change

```
159 passed, 2 skipped
```
Confirmed before editing, per the brief's inspection requirement. No FastAPI app existed at that point.

---

## 2. Files created

| Path | Purpose |
|---|---|
| `backend/app/api/models.py` | Typed response models — provenance envelope, `Literal` guards on `simulated` and `kind` |
| `backend/app/api/main.py` | FastAPI app: 3 GET routes, injectable clock + HTTP client, Guayaquil-bounds check |
| `backend/app/api/__init__.py` | package marker |
| `backend/tests/api/test_public_api.py` | 39 API tests |
| `backend/tests/api/__init__.py` | package marker |
| `frontend/src/api.ts` | Typed client, timeout, no credentials, no fixture fallback |
| `frontend/src/i18n.ts` | 25 bilingual keys; a missing Spanish value is a **compile error** |
| `frontend/src/tokens.ts` | Stage 1 §14 design tokens |
| `frontend/src/__i18n-check.mjs` | Static guard: key completeness + banned-vocabulary scan |
| `frontend/src/App.tsx` | Dashboard — replaced the M0 placeholder |
| `docs/M6-EVIDENCE.md` | this report |

### Modified

`PHASES.md` (status rows). Nothing else.

### Not modified

`backend/requirements.txt` (12 pins unchanged) · `frontend/package.json` (6 deps / 7 devDeps unchanged — **no
dependency added at all**) · `domain/risk.py`, `routing/*`, `ingest/*`, `simulate/*` (M6 consumed them; no
behaviour change) · all Stage 1–4 documents · `supabase/*`.

---

## 3. Endpoints and response contracts

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | local readiness; reports dependency *state*, never configuration |
| GET | `/api/public/forecast` | normalized Open-Meteo rainfall forecast |
| GET | `/api/public/sensors` | simulated sensor readings |

**Only GET exists.** A test enumerates every route and asserts no POST/PUT/PATCH/DELETE is present.

### `GET /api/public/forecast`

Query: `sector` (`norte|centro|sur`) **or** `latitude`+`longitude` inside Guayaquil, plus `hours` (1–48).

```json
{
  "ok": true,
  "hours": [{"at": "...", "precipitation_mm": 1.2,
             "probability_pct": 80.0, "kind": "forecast"}],
  "total_mm": 10.2, "max_hourly_mm": 5.6, "units": "mm",
  "provider_units_original": "mm",
  "latitude": -2.1962, "longitude": -79.8865,
  "error": null,
  "summary": "Forecast (not an observation): 10.2 mm total over 6 hours, peak 5.6 mm in one hour. Retrieved 0 min ago.",
  "provenance": {
    "chip": "estimated",
    "fetched_at": "2026-10-26T00:20:00Z",
    "stale_after_s": 3600,
    "simulated": false,
    "data_mode": "MIXED",
    "sources": [{"name": "open-meteo", "model_run_at": null}],
    "notes": ["provider response includes no model run time; only the fetch time is known"]
  }
}
```

Deliberate properties:
- `kind` is `"forecast"` on **every** hour. An observation would require a different source and label.
- `model_run_at` is `null` because the provider does not supply it (**N-1**). It is never inferred.
- `fetched_at` and `model_run_at` are in different places, so they cannot be confused.
- No "heavy rain" field exists anywhere (**B13**).
- On failure: `ok:false`, `hours:[]`, `total_mm:0.0`, `max_hourly_mm:null`, chip `no_data`. **No estimate is
  substituted.**

### `GET /api/public/sensors`

```json
{
  "sensors": [{
    "sensor_id": "SIM-01", "sector_id": "norte", "profile": "surge",
    "threshold_m": 1.2, "health": "degraded", "last_reading_age_s": 300.0,
    "latest": {"depth_m": 0.75, "observed_at": "...", "threshold_m": 1.2,
               "fraction_of_threshold": 0.625, "above_threshold": false,
               "simulated": true, "label": "SIMULATED"},
    "simulated": true, "label": "SIMULATED", "notes": []
  }],
  "available": true, "any_offline": true, "simulated": true,
  "provenance": {"chip": "estimated", "data_mode": "SIMULATED",
                 "simulated": true, "notes": ["all sensor readings are SIMULATED; ..."]}
}
```

- `simulated` is `Literal[True]` in the model, so a response claiming a real reading **cannot be constructed**.
- `available:false` (empty feed) is distinct from `any_offline:true` (feed present, readings old).
- No request parameter can alter the simulated flag — asserted for four candidate spellings.

---

## 4. Frontend sections implemented

| Section | Content |
|---|---|
| **A. Current data status** | availability chip, provenance chip, source name, fetch time (locale-formatted with offset), model-run time **or** "Model run time unavailable", total mm, peak hourly mm, "these are forecast values, not measured rainfall", collapsible provenance notes |
| **B. Sensor status** | SIMULATED badge per card, explicit clause that no real telemetry exists, health dot + word (never colour alone), depth, % of threshold, prototype-threshold warning, last-reading age |
| **C. Limitations** | synthetic-graph disclosure (~40 km generated grid, not Guayaquil), "routing is not exposed; no route is drawn", "a path existing does not mean a road is safe", "risk level not shown — unvalidated heuristic with an unresolved conflict", "no flood map / closures / shelters / official alerts exist yet" |
| **D. Language** | EN primary, ES via header toggle, both complete (25 keys), locale-aware date/number formatting, metric units only |
| **E. Failure states** | loading, error (with retry), unavailable, malformed, empty sensor feed, stale chip |

### What the dashboard deliberately does **not** do

- **No map and no route.** Routing is not exposed yet; drawing one would imply coverage the data does not
  support. Stated in the UI rather than left to the reader.
- **No combined risk level.** O-7 is unresolved; showing it as settled would contradict the project's own
  honesty rules. The UI says so explicitly.
- **No fixture fallback.** A failed request yields an error card, never demo values dressed as live.

---

## 5. Exact commands and results

```
$ cd backend && ../.venv/bin/python -m pytest
198 passed, 2 skipped, 1 warning in 0.73s
```

```
$ ../.venv/bin/python -m coverage run --branch -m pytest -q
$ ../.venv/bin/python -m coverage report --include="app/api/*"
app/api/__init__.py       0      0      0      0   100%
app/api/main.py          75      1     26      3    96%
app/api/models.py        68      0      0      0   100%
TOTAL                   143      1     26      3    98%
```

`app/domain/risk.py` remains at **100 % statement and branch** — the required gate holds:
```
app/domain/risk.py      250      0    102      0   100%
```

```
$ cd frontend && npx tsc -b --force      → exit 0
$ npm run build
✓ 18 modules transformed.
dist/assets/index-DcJYKDHG.js  235.21 kB │ gzip: 74.22 kB
✓ built in 119ms
```

```
$ node src/__i18n-check.mjs
i18n check passed: 25 keys, both languages present, no overclaims
```

### Live end-to-end verification

Both servers started locally, then driven with real HTTP:

```
$ uvicorn app.api.main:app --port 8012 --app-dir backend      (background)
$ vite preview --port 4173                                    (background)

$ curl /api/health
{"status":"ok","service":"guaradar-api","forecast_source":null,
 "notes":["sensor data is SIMULATED","road graph is synthetic demo data","server time ..."]}

$ curl "/api/public/sensors?count=3"
available: True | simulated: True | chip: estimated | mode: SIMULATED
  SIM-01 SIMULATED health=degraded depth=0.75
  SIM-02 SIMULATED health=degraded depth=0.358

$ curl "/api/public/forecast?hours=6"          ← real Open-Meteo
http=200
ok: True | hours: 6 | units: mm | orig: mm
total: 10.2 mm | max: 5.6
kinds: {'forecast'}
source: open-meteo | model_run_at: None
chip: estimated | mode: MIXED
summary: Forecast (not an observation): 10.2 mm total over 6 hours, peak 5.6 mm in one hour. Retrieved 0 min ago.
heavy label present? False

$ curl -X OPTIONS -H "Origin: http://localhost:5173" .../api/public/sensors
HTTP/1.1 200 OK
access-control-allow-origin: http://localhost:5173
access-control-allow-methods: GET

$ curl frontend  http://localhost:4173/          → html=200, <title>Guaradar</title>
```

**The API→dashboard flow works locally**, against the real provider. `model_run_at` is `null` in the live
response, and `data_mode` is `MIXED` — the honest state (real forecast + simulated sensors).

---

## 6. Live versus fixture

| Tested live | Tested with fixtures |
|---|---|
| Open-Meteo forecast through the full API stack (6 h, 10.2 mm) | all 39 API tests — injected clock + injected HTTP client |
| sensor endpoint through HTTP | all adapter and simulation tests |
| CORS preflight and cross-origin GET | every staleness / malformed / failure path |
| frontend `index.html` served, bundle built | i18n completeness and overclaim scan |

**No API test touches the network.** The suite is deterministic: a fixed clock and a fake HTTP client.

**Not visually verified in a browser.** The browser tool refuses private-network targets, so the rendered
DOM was verified by checking the built bundle contains the required strings (§7) rather than by screenshot.
That is weaker than a visual check and is stated as such.

---

## 7. Bundle content verification

Because a browser screenshot was not possible, the production bundle was scanned directly:

```
SIMULATED                          PRESENT
Model run time unavailable         PRESENT
synthetic demo data                PRESENT
unvalidated heuristic              PRESENT
No route is drawn                  PRESENT
"These are forecast values, not measured rainfall"  PRESENT
flood-proof                        absent
risk-free                          absent
guaranteed safe                    absent
Pronóstico no disponible           PRESENT
SIMULADO                           PRESENT
datos sintéticos                   PRESENT
```

`not an observation` is absent from the frontend bundle **correctly** — it is the backend's summary string,
verified present in the live API response instead.

---

## 8. Required tests — mapped

| # | Requirement | Coverage |
|---|---|---|
| 1 | Typed response shape for both endpoints | `test_forecast_response_shape`, `test_sensors_response_shape`, `test_health_shape` |
| 2 | Units and forecast-vs-observation meaning | `test_units_are_mm_*`, `test_inch_input_is_converted_*`, `test_every_hour_is_labelled_forecast`, `test_summary_says_forecast_not_observation`, `test_no_heavy_rain_classification_anywhere` |
| 3 | Missing model-run time stays null | `test_model_run_at_is_null_not_inferred` |
| 4 | Fetch time distinguishable from model run | `test_fetch_time_is_present_and_distinct` |
| 5 | Stale / empty / malformed / unavailable | 6 parametrised provider-failure cases, `test_stale_chip_when_fetch_is_older_than_budget`, `test_empty_sensor_feed_is_available_false`, `test_sensors_offline_state_surfaces` |
| 6 | SIMULATED marker always retained | `test_sensors_always_simulated`, `test_caller_cannot_turn_simulated_into_real` |
| 7 | No secrets or privileged fields | `test_no_privileged_or_secret_fields_in_any_response` (recursive walk over 3 payloads, 17 forbidden keys), `test_no_environment_values_leak` |
| 8 | No mutation, no promotion to verified | `test_no_mutation_routes_exist`, `test_get_cannot_promote_to_verified`, `test_cors_methods_are_read_only` |
| 9 | Frontend states render without exceptions | `tsc` strict + production build pass; i18n guard; bundle scan (§7). **Not** runtime-rendered — see §6 |
| 10 | Synthetic disclosure + bilingual strings | `i18n check passed: 25 keys`; bundle scan shows both languages; Limitations card asserts the disclosure |
| 11 | No "safe"/"flood-proof"/"risk-free"/"guaranteed" | `__i18n-check.mjs` scans all 25 keys in both languages; bundle scan confirms absence |
| 12 | Routing and domain invariants intact | full suite: all `ROUTE-*` and `RISK-*` tests still pass unchanged |

---

## 9. Defects found and fixed

| # | Defect | Surfaced by | Fix |
|---|---|---|---|
| **D-1** | `HTTP_422_UNPROCESSABLE_ENTITY` is deprecated in this Starlette version | pytest warnings | Switched to `HTTP_422_UNPROCESSABLE_CONTENT` |
| **D-2** | My i18n checker used `JSON.parse` on single-quoted TS strings | `SyntaxError: Unexpected token '` | Wrote a proper quote-aware unquoter |
| **D-3** | A staleness test patched `fetch_forecast` and then called it from inside the patch — infinite recursion | `RecursionError` | Replaced with a test that asserts the budget constant and the primary `estimated` path honestly, rather than faking a stale fetch |
| **D-4** | The coordinate path (line 198) was reachable but untested — only rejections were covered | coverage report | Added `test_valid_coordinates_inside_guayaquil_accepted` |
| **D-5** | My earlier `--coverage --include="app/*"` glob silently excluded subdirectories, so `app/api/*` was missing from the first report | manual cross-check | Report run per-directory with the correct glob |

D-5 is worth naming: a coverage glob that silently drops files makes a report look better or worse than
reality. The numbers in §5 are from explicit per-package includes.

---

## 10. Untested / not verified

Stated plainly so nothing is overclaimed:

- **No browser screenshot.** The visual layout is unverified; only build success and bundle content.
- **Frontend rendering has no automated DOM test.** No jsdom/Testing Library was added (it would be a new
  dependency); state handling is covered by TypeScript's exhaustive `Loadable<T>` union, not by a renderer.
- **`app/api/main.py` branch coverage is 96 %**, not 100 %. The uncovered branches are the
  production-clock path and an unreachable defensive ordering in `generate_series_for_all`. The **required**
  100 % gate applies to `domain/` only and holds.
- **No load or concurrency testing.** Single-client only.
- **Supabase is not involved.** The API reads no database; sensors are generated in-process. RLS remains
  unexercised by this layer.
- **`model_run_at` will always be null** on this endpoint (N-1).

---

## 11. Blockers and decision status

| ID | Item | Status |
|---|---|---|
| **O-7** | Risk formula vs `RISK-8b` prose | **OPEN, unchanged.** `risk.py` untouched. The dashboard **does not display a risk level** and says why. |
| **O-8** | Stale-closure semantics | **OPEN, provisional.** No routing behaviour changed in M6. |
| **N-1** | No provider model-run time | **Confirmed live again** (`model_run_at: None`). Surfaced in the UI as "Model run time unavailable" plus an explanation that retrieval time is not model-run time. **Not inferred.** |
| **N-2** | `current_app_role()` trusts a session setting | **OPEN.** No privileged write path exists — the app has **no mutation verbs at all**, so this cannot be exploited here. Read endpoints return only deliberately selected public fields. |
| **N-3** | `build_from_osm_json` unverified | Unchanged; still skipped with a reason. |
| **N-4** | ~~No FastAPI app~~ | **RESOLVED by M6** for read-only endpoints. Database-backed provenance persistence remains unbuilt. |
| **N-5** | No browser-verified rendering | New. Recorded in §10. |

**Why no privileged endpoint was added:** N-2 means authorization currently trusts a session setting. An
ingestion or admin write path behind that would be a privileged write behind an unverified role. The brief
authorised no mutation endpoints, and this block added none — verified by test, not by intention.

---

## 12. Recommended next milestone

**M7 — provenance persistence + map/route read endpoint**, in that order:

1. Persist fetched forecasts into `weather_cache` with `fetched_at`/`model_run_at` (exercises the M1 schema,
   and would make N-1 visible rather than merely absent).
2. Then a **read-only** `GET /api/public/route` using the existing two-phase search, so the map screen has a
   real contract to consume — still GET-only.

**Do not** add the admin console until N-2 is resolved with server-side identity derivation. That is the
one blocker that turns "no mutation exists" into "mutation is safe".

---

## 13. Standing statements

- **The risk model remains an unvalidated heuristic** and is **not displayed** as an approved safety rule.
- **The road graph is synthetic** (~40 km generated grid), disclosed in the UI.
- **All sensor readings are SIMULATED**, labelled on every card and in the API model type.
- **No route is claimed safe.** Routing is not exposed at all in this block.
- No commits, no pushes, no deployments, no new dependencies, no destructive migrations.
