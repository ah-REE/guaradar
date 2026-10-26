# Backend Bring-Up and Frontend Integration — Evidence

**Date:** 2026-10-26
**Task:** get the existing backend running and connected to the existing frontend
**Verdict:** **DONE.** Root cause was that the backend was not running. Connected via a Vite
proxy, verified end to end.
**Scope held:** frontend untouched except two data/URL defaults; no new features, no admin, no
mutation endpoints, no deps added, no commits.

---

## 1. Root cause

**The backend was not running.** Nothing was listening on the port the frontend targets.

Evidence at diagnosis time:

```
$ ss -ltnp | rg "8000|5173"
LISTEN  [::1]:5173   node-MainThread        ← frontend dev server only

$ curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/health
000                                        ← connection refused

$ curl -s http://localhost:5173/api/health | head -1
<!doctype html>                            ← no proxy; Vite returned the SPA shell
```

So the browser's `fetch()` to `http://127.0.0.1:8000/api/...` was refused outright. The UI
rendered its error state correctly — `Network request failed` is the honest message for a
refused connection, and notably the app did **not** substitute fake data.

You confirmed the frontend was started with `npm run dev` from `frontend/` and otherwise
unmodified, so no frontend defect contributed to the failure.

---

## 2. What was wrong beyond "not started"

Two latent problems made the setup fragile, and both are fixed:

### 2.1 Hardcoded absolute API URL → guaranteed cross-origin

`frontend/src/api.ts` and `routeApi.ts` defaulted to `'http://127.0.0.1:8000'`. With the page
served from `localhost:5173`, every request was cross-origin. That only works when the backend's
CORS list matches exactly what the browser sends — and `localhost` and `127.0.0.1` are
*different origins*. A user opening `http://localhost:5173` while the client calls
`127.0.0.1:8000` is a silent trap.

**Fix:** the client now defaults to **same-origin** (`''`), and Vite proxies `/api` to the
backend. No cross-origin hop, no CORS dependency, one place to change the target. An absolute
override is still possible via `VITE_API_BASE_URL` for the genuinely-remote case.

### 2.2 Two route demo points exceeded the snap limit → confusing refusals

Measured against the real OSM graph:

```
SIM-01   4.1 m   OK
SIM-02  63.1 m   REFUSES (limit 60 m)
SIM-03  32.3 m   OK
SIM-04  31.0 m   OK
SIM-05  62.6 m   REFUSES
SIM-06  21.7 m   OK
```

Selecting SIM-02 or SIM-05 in the route form produced a *truthful but unhelpful* refusal:
*"your starting point is 63 m from the nearest road (limit 60 m)"*.

**Fix:** the snap limit was **not** relaxed — it exists so the app never routes from a guessed
origin. Instead the six `DEMO_POINTS` were moved onto their nearest **real graph nodes** (snap
0.0–0.1 m). A test now asserts every demo point stays inside the limit.

### 2.3 Health endpoint disclosed the wrong data source

`GET /api/health` hardcoded *"road graph is synthetic demo data"*. Since M9 the default graph is
a **real OSM extract**, so the disclosure was false — the opposite error from the one fixed in
M9. Now derived from `graph.synthetic`:

```
road geometry is a bounded OpenStreetMap extract of central Guayaquil (not city-wide);
road STATUS is seed/demo data
```

---

## 3. Files changed and why

| File | Change | Why |
|---|---|---|
| `frontend/vite.config.ts` | added `server.proxy` and `preview.proxy` for `/api` → `127.0.0.1:8000` | removes the cross-origin hop; makes the URL configurable in one place |
| `frontend/src/api.ts` | `apiBaseUrl()` defaults to same-origin instead of a hardcoded URL | same reason; keeps an explicit escape hatch |
| `frontend/src/routeApi.ts` | `routeUrlBase()` same change | consistency with `api.ts` |
| `frontend/src/RouteScreen.tsx` | six `DEMO_POINTS` coordinates changed to real graph nodes; comment explains why | SIM-02/SIM-05 were outside the snap limit |
| `backend/app/api/main.py` | health note derived from `graph.synthetic`; OpenAPI description corrected | the "synthetic" claim became false after M9 |
| `backend/tests/api/test_public_api.py` | +2 tests: health disclosure matches graph source; all demo points snap | so neither regression can return |

**No visual design, layout, text, or component structure was changed.** The `DEMO_POINTS` edit
changes six coordinate literals only.

---

## 4. Local URLs

| Service | URL | Command |
|---|---|---|
| Frontend (dev) | **http://127.0.0.1:5173/** | `cd frontend && npm run dev` |
| Backend API | **http://127.0.0.1:8000/** | `.venv/bin/python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --app-dir backend` |
| API docs | http://127.0.0.1:8000/api/docs | — |

The frontend proxies `/api` to the backend, so the browser only ever talks to port 5173.

---

## 5. Endpoint verification (all through the dev-server proxy, i.e. the browser's path)

| # | Check | Result |
|---|---|---|
| 1 | `GET /api/health` | **200, JSON** — `status: ok`, notes name SIMULATED sensors and the real-OSM/seed-status split |
| 2 | `GET /api/public/forecast?hours=3` | **200, JSON** — `ok: true`, provenance envelope present |
| 3 | `GET /api/public/forecast?hours=24` | **200** — 24 hours, `kind: {forecast}`, `model_run_at: null`, mode `MIXED` |
| 4 | `GET /api/public/sensors?count=2` / `count=6` | **200, JSON** — `simulated: true`, every label `SIMULATED` |
| 5 | `GET /api/public/route` (valid pair) | **200** — `refused: false`, 3 routes, snap 0.1 / 0.0 m |
| 6 | `GET /api/public/route` (outside extract) | **200** — `refused: true`, *"starting point is 19891 m from the nearest road (limit 60 m)"* |
| 7 | All 30 sensor-pair permutations | **30 / 30 routed**, 0 refusals |
| 8 | No mutation endpoints | `rg "@app\.(post\|put\|patch\|delete)"` → **none** |

Note on 6: the API returns **200 with `refused: true`**, not a 4xx. That is intentional — an
unroutable point is a valid answer to a valid question, and the frontend renders
`refusal_reason` rather than treating it as a transport error.

---

## 6. Was database access required?

**No.** All public endpoints operate without PostgreSQL:

- forecast — live Open-Meteo (network only)
- sensors — in-process simulator
- routes — graph artifact + the labelled seed status generator

`GET /api/health` returns `status: ok` with no database. The health check does not probe upstream
services, by design (it reports dependency *state* only, and `forecast_source` stays `null`
unless a caller actively probes).

Privileged writes remain **disabled** (`DATABASE_WRITES_ENABLED = False`) because N-2 is open.
Read-only functionality does not bypass RLS; it simply does not touch the database.

---

## 7. Tests and build

```
$ cd backend && ../.venv/bin/python -m pytest
366 passed, 10 skipped          (was 364; +2 new tests)

app/domain/risk.py                 250    0   102   0   100%     ← gate holds
app/routing/status_repository.py   136    0    48   0   100%     ← gate holds

$ cd frontend && npx tsc -b --force     → exit 0
$ npm run build
dist/assets/leaflet-src-*.js   148.60 kB │ gzip: 43.32 kB
dist/assets/index-*.js         251.43 kB │ gzip: 78.72 kB
✓ built in 145ms
```

Dependencies unchanged (12 pins, no new package). No commits, no pushes, no deployment.

---

## 8. Browser verification — **NOT performed**

`browser_tool` refuses private-network targets (`browser_private_target_denied`) and this host
has no browser installed. **N-5 remains open.**

What *is* verified is the exact HTTP path the browser takes: `localhost:5173/api/...` returns
real JSON for every endpoint the UI calls, and the production build compiles under strict
TypeScript. That is transport verification, **not** visual verification — map framing, tile
load failure, route line rendering, and Spanish text remain unseen by me.

**You have a browser** — please reload http://127.0.0.1:5173/ and tell me what you see. If
anything still shows an error card, the browser devtools Network tab will show the failing URL
directly.

---

## 9. Remaining limitations

| ID | Status |
|---|---|
| **N-5** | **OPEN** — no visual verification possible from here. |
| **N-13** | Turn restrictions not modelled (one-way *is* enforced). |
| **N-14** | `road_segments` loading still script-driven. |
| **N-15** | `graph.py` at 84 % branch; no `backward` edges exist in real data. |
| **N-16** | Demo routes are dominated by phase-2 hazard crossings — the seed generator closes 1-in-29 edges over 24,943, so phase 1 rarely finds a clear path. **This is why the route cards you see will mostly say "crosses a closed road".** Correct behaviour, poor demo. |
| **O-7** | Risk formula conflict — unchanged, risk level not displayed. |
| **O-8** | Stale-closure policy provisional — unchanged. |
| **N-1 / N-2 / N-6** | Unchanged. |

N-16 is the most visible one for a demo and is the natural next step: a deterministic demo
scenario profile with a handful of labelled synthetic closures, kept separate from the default
generator, so a clear recommendable route is reachable. That is demo data, not engine behaviour.

---

## 10. Standing statements

- **Sensors are SIMULATED.** Every reading and every API response says so.
- **Road geometry is real OSM** for a bounded central-Guayaquil extract — **not city-wide**.
  Road **status** is seed/demo data, not a live municipal feed.
- **No route is claimed safe.** Coverage is stated; hazard crossings are labelled; low coverage
  is never recommended.
- **No mutation endpoint exists.** Ingestion writes stay disabled while N-2 is open.
