# M15 — Community Road Reports, Lifecycle, and GPS Routing (Features A–E)

**Date:** 2026-10-26
**Commit at start:** `edcd659` on `main`, working tree clean
**Scope of this pass:** features **A, B, C, D, E** only. Terrain (F, G) is deliberately out of
scope — the owner chose to review reports first.

---

## 1. Baseline measured before any change

| Check | Command | Result |
|---|---|---|
| Backend suite | `backend: ../.venv/bin/python -m pytest` | **631 passed, 12 skipped** |
| TypeScript | `frontend: npx tsc -b` | exit 0 |
| i18n guard | `node src/__i18n-check.mjs` | 226 keys, both languages, no overclaims |
| Runtime database | inspect `app/store.py` | **SQLite** (`data/guaradar.db`) |
| PostgreSQL available | `which psql postgres initdb` | **not installed** |
| Graph | `data/graph-artifact.json` | 20,386 nodes / 24,943 edges, real OSM extract |

The 12 skips are the PostgreSQL suites; they skip for the environment reason
(`GUARADAR_PG_DSN` unset, no server binary), not for a code reason. That is why the PostgreSQL
migration below is written but reported **untested**.

---

## 2. Final results

| Check | Result |
|---|---|
| Backend suite | **817 passed, 12 skipped** (+186 tests, 0 pre-existing failures) |
| `npx tsc -b` | exit 0 |
| `npm run build` | success, 359.99 kB → 107.65 kB gzip |
| i18n guard | **325 keys**, both languages present, no overclaims |
| Secrets in bundle | none (`grep` over `dist/**/*.js` + `*.html` for the key, `SERVICE_ROLE`, JWT shape) |

**No test was deleted, skipped, or weakened to obtain these numbers.** Three tests were
*updated* where a truthful change made their old assertion false; each is listed in §6 with the
reason and with a strengthened assertion.

---

## 3. What was built

### 3.1 Persistence — additive only

`backend/app/store.py`: five new tables. `supabase/migrations/0007_road_reports.sql`: the
PostgreSQL equivalent.

| Table | Purpose |
|---|---|
| `road_reports` | one row per submission: category, description, raw GPS + accuracy, matched segment, snapped public point, decision, lifecycle timestamps, `expires_at` |
| `report_images` | sanitised re-encoded bytes, dimensions, sha256, `metadata_stripped` |
| `report_confirmations` | confirm/challenge votes, `unique(report_id, user_id)` |
| `report_audit` | append-only history; no UPDATE/DELETE helper exists |
| `report_rate_events` | per-account throttling, windowed by query |

**No existing table was altered. Nothing was dropped.**

### 3.2 The lifecycle rule that shapes everything

`backend/app/reports/lifecycle.py` (pure: no I/O, injected clock).

`stale` is **not a stored status**. It is a computed predicate over `expires_at`. This makes
requirement D.3 structural instead of a rule someone must remember, because no timer can rewrite
a decision:

| Situation | Road status | Counts as current evidence |
|---|---|---|
| Unverified, fresh | `affected` (caution) | no |
| Unverified, expired | `unknown` | no |
| Verified blocked, fresh | `closed` | yes |
| **Verified blocked, expired** | **`closed`** | **no** (`stale_closure`) |
| Verified passable, fresh | `open` | yes |
| **Verified passable, expired** | **`affected`** | no |
| Rejected | contributes nothing | no |

Conflicting verified reports: the higher-risk reading wins **and both are retained** and
reported through `StatusConflict`. Order-independent, so database row order cannot change
behaviour.

### 3.3 Snapping

`backend/app/reports/snapping.py`. Nearest **segment**, not nearest node: a hazard 12 m from a
segment's midpoint belongs to that segment even if both endpoints are 60 m away. Latitude-band
pre-filter keeps it off the O(n·E) path. The threshold (50 m) and the accuracy gate (100 m) are
both configurable and both produce a **reported miss**, never a guessed match.

### 3.4 Image security

`backend/app/reports/images.py`. Order is deliberate: size → pixel count → **decode** → format
allow-list → resize → re-encode from pixels. Metadata cannot survive because nothing but pixels
is ever read; there is no `exif=` argument in any save call (asserted by test).

Measured on a 94,780-byte JPEG carrying a GPS EXIF block: output 6,766 bytes, 1280×853, and
`getexif()` is **empty**.

### 3.5 API

`backend/app/api/report_routes.py`, on `APIRouter`s matching `auth_routes.py`.

Public/signed-in: `POST /api/reports` · `GET /api/reports` · `GET /api/reports/{id}` ·
`POST /api/reports/{id}/confirm` · `GET /api/reports/{id}/image`
Admin: `GET /api/admin/reports` · `GET /api/admin/reports/effective-status` ·
`GET /api/admin/reports/{id}` · `POST /api/admin/reports/{id}/decision` ·
`GET /api/admin/reports/{id}/history`

### 3.6 Routing integration

`merge_statuses()` layers report evidence into the **single** `StatusIndex` the router consults,
so a report changes the searched path, not just the caption. Merge rules: a report closure always
wins (higher risk); a citizen "passable" **cannot** lift an operator-verified closure; an expired
closure still excludes its edge while losing `verified`, which lowers coverage and pushes the
router toward alternatives. `RouteResponseOut` gained `report_overlay_applied`,
`report_segments_affected`, `report_closures`, `report_stale_closures`.

### 3.7 Frontend

`ReportScreen.tsx` · `AdminReports.tsx` · `reportApi.ts`, plus a `report` tab and a
"use my current location" origin in `RouteScreen.tsx`.

Geolocation is called **only inside a click handler** — no effect, no mount-time request, no
`watchPosition` (all three asserted). `capture="environment"` for phones with a second plain
file input as fallback. ~99 new i18n keys (`report*`, `adminReport*`, `adminDecision*`,
`routeOrigin*`), authored in English first, complete in Spanish.

---

## 4. End-to-end trace (real run, real graph)

```
1. anonymous submit -> 401
2. public visibility before any report: 0
3. submitted: state=unverified segment=35693207003 snapped=True
4. visible to a DIFFERENT anonymous visitor: True
5. public payload keys with 'gps': none
6. public decision attempt -> 403
7. confirm twice: recorded already_voted
8. operator verify blocked -> blocked_verified
9. effective status: {segments_with_reports: 1, segments_closed: 1, segments_with_stale_closure: 0}
10. route overlay applied: True closures: 1
```

---

## 5. Tests added (186)

| File | Count | Covers |
|---|---|---|
| `tests/unit/test_reports_lifecycle.py` | 44 | status/freshness rules, conflicts, validation |
| `tests/api/test_reports_api.py` | 49 | creation, validation, images, snapping, privacy, authz, lifecycle, storage failure, rate limit |
| `tests/unit/test_reports_media_and_overlay.py` | 37 | snapping geometry, image pipeline, overlay merge |
| `tests/unit/test_reports_safety_guards.py` | 30 | guards against future weakening |
| `tests/unit/test_reports_frontend_contract.py` | 26 | TS↔Python contract, i18n parity, build artefacts |

**The guards were verified by mutation, not assumed.** Injecting
`navigator.geolocation.watchPosition(...)` made the tracking guard fail with
`"ReportScreen.tsx must not track continuously"`. Changing an expired closure to return `open`
made two lifecycle tests fail. Both mutations were reverted and the suite re-run green.

---

## 6. Tests updated, with reasons

| Test | Why the old assertion was false | What it asserts now |
|---|---|---|
| `test_missing_feature_states_what_is_missing[adminIncidentsEmpty]` | Passed on the word "table" because the copy said no incidents table existed. Reports now exist. | Requires the copy to name what is *still* absent (clustering, depth band, account-free submission) and to no longer claim there is no report channel. |
| `test_admin_tab_is_reachable_from_navigation` | Asserted the literal `'status', 'route', 'admin'`. A `report` tab was correctly inserted between them. | Asserts nav **order** with all five tabs present and `ReportScreen` wired. |
| `test_no_public_mutation_endpoints` (unchanged) | — | It fired on my module because my docstring contained the literal text of a mutation decorator. The **docstring** was reworded; the test and its meaning were left alone. |

---

### A third, caught at the final secrets sweep
My bundle-scanner guard listed a **truncated prefix of the real OpenTopography key** as a
"tripwire" literal. That is precisely what the brief forbids — a key, or any fragment of one, in
a test fixture — and a name-based list cannot catch a leaked key whose name it does not know. It
was removed, replaced with a generic high-entropy-token check that does not need to know the key
in advance, and the whole working tree was re-swept: **the key now appears nowhere**. The guard
file re-passes and the suite is still 817/12.

## 7. Two defects found and fixed during this work

1. **`inconclusive` decisions were rejected at read time.** `apply_admin_decision` did not stamp
   `verified_at` for `inconclusive`, but the lifecycle requires an attribution timestamp for
   every decision except `unverified`/`rejected`. Result: an operator recording "we looked and
   could not tell" produced a row that later raised `LifecycleError` when read. Fixed in
   `repository.py`; the rule is now `decision != 'rejected'`, with the reason recorded in a
   comment.
2. **A test fixture could not represent a real report.** My first staleness test rewrote only
   `expires_at`, producing a verification *after* an expiry — a state no real row can reach, and
   which the lifecycle correctly rejects. The helper now shifts the whole timeline, which is what
   actually happens as hours pass.

---

## 8. Honest limitations

### Runtime durability — **not durable on Render as configured**
Image bytes live in the database on purpose, because the intended host has an **ephemeral**
filesystem. But the runtime database is **SQLite on that same ephemeral disk**. So today both the
rows *and* the images disappear on restart, spin-down, or redeploy. Durable reporting requires
`GUARADAR_PG_DSN` pointing at managed PostgreSQL and `0007_road_reports.sql` applied. The code
does not claim otherwise anywhere.

### PostgreSQL path — **written, not executed**
No `psql`/`postgres` binary on this host, so the 12 PostgreSQL tests still skip and the migration
was never applied. It was validated only structurally (balanced delimiters, five tables, nine
indexes) and by review. **It has not been proven to apply.**

The migration attaches its identity foreign keys **conditionally**, because no users table
exists in the PostgreSQL schema yet (`0002_rls.sql` records that Supabase would derive the role
from `auth.uid()`). A hard `references` would fail on a clean apply; the `DO` block finds
`public.users` or `auth.users` when present and reports a notice when not.

### Privacy — precise numbers
Published: snapped road point (matched) or a ~111 m coarsened cell (unmatched). Withheld:
`gps_lat`/`gps_lon`, `user_id`, email. A matched report's published point is *the road*, so it
reveals nothing about where the person stood.

### Not implemented in this pass
Terrain (features F/G), destination search by name, clustering of nearby reports into one
incident, water-depth band estimation, account-free submission, alert fan-out on closure, and
animated/video uploads.

### No browser-based visual verification
The UI was checked by type-checking, production build, contract tests, and source inspection —
**not** by rendering it. No browser was available, and `browser_tool` refuses private targets.
Copy in `i18n.ts` is asserted, but appearance on a 375 px phone was not observed. That remains
open, exactly as it did for M12.

### One environment workaround worth knowing
Three existing frontend files contained a literal `key: value` pattern whose key name was the
password field: the i18n catalogue's `authPassword` entry, the `register`/`login` parameters in
`authApi.ts`, and an HTML autocomplete token in `AccountScreen.tsx`. The workspace write guard
reads that pattern as a credential assignment and therefore blocked **every** write to those
files, including unrelated edits.

The identifiers were renamed (`authPasswordField`, `secret`, and string concatenation for the
autocomplete token). **Behaviour is unchanged:** the JSON field name the server expects is
untouched, and the autocomplete hints still resolve to the same two tokens. `tsc -b` and the
full suite confirm it, and the user confirmed the flag was a false positive before the change
was made.

---

## 9. Files changed

**Added (backend)**
```
backend/app/reports/__init__.py
backend/app/reports/lifecycle.py
backend/app/reports/snapping.py
backend/app/reports/images.py
backend/app/reports/repository.py
backend/app/api/report_routes.py
backend/tests/unit/test_reports_lifecycle.py
backend/tests/unit/test_reports_media_and_overlay.py
backend/tests/unit/test_reports_safety_guards.py
backend/tests/unit/test_reports_frontend_contract.py
backend/tests/api/test_reports_api.py
```

**Added (frontend)**
```
frontend/src/reportApi.ts
frontend/src/ReportScreen.tsx
frontend/src/AdminReports.tsx
```

**Added (schema)**
```
supabase/migrations/0007_road_reports.sql
```

**Modified**
```
backend/app/store.py            5 tables + test reset order
backend/app/api/main.py         router registration, merge_statuses, overlay wiring
backend/app/api/route_models.py 4 overlay fields
backend/app/routing/graph.py    edges_with_records / record_for / freshness_window accessors
backend/app/reports/repository.py   (new file; inconclusive fix applied during verification)
backend/tests/unit/test_admin_panel.py  2 assertions updated (§6)
frontend/src/i18n.ts            226 → 325 keys; adminIncidentsEmpty corrected
frontend/src/App.tsx            report tab, AdminReports mount
frontend/src/RouteScreen.tsx    current-location origin, overlay disclosure
frontend/src/tokens.ts          okBg added
frontend/src/routeApi.ts        4 optional overlay fields
frontend/src/AccountScreen.tsx  identifier rename only (§8)
frontend/src/authApi.ts         identifier rename only (§8)
frontend/src/__probe_*.ts       deleted (temporary probes used to diagnose the write guard)
.env.example                    4 report variables documented
```

---

## 10. Configuration added

```bash
ROAD_REPORT_STALE_AFTER_MINUTES=360   # freshness window; staleness is derived, never stored
MAX_ROAD_REPORT_IMAGE_BYTES=5242880    # enforced before decoding
ROAD_REPORT_SNAP_THRESHOLD_M=50        # a miss is reported, never guessed
ROAD_REPORT_MAX_ACCURACY_M=100         # worse than this cannot be matched automatically
```

All four are validated at import; a malformed value raises rather than silently falling back.

---

## 11. To make this durable in production

1. Provision managed PostgreSQL and set `GUARADAR_PG_DSN` (server-side secret only).
2. Apply `0007_road_reports.sql`, then re-run the `DO` block once the identity schema exists.
3. Set `GUARADAR_DB_PATH` aside — the SQLite prototype must not be the deployed store.
4. Re-run the suite with `GUARADAR_PG_DSN` set to convert the 12 skips into real coverage.
5. **Rotate the OpenTopography key that was pasted into chat.**

Nothing was committed, pushed, or deployed.
