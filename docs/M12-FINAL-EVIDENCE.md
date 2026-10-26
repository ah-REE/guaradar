# M12 (final) — Frontend Polish + Read-Only Admin Panel: Evidence

**Date:** 2026-10-26
**Commit:** `3dda617` on branch `main` — **committed locally, PUSH BLOCKED (no credentials)**
**Verdict:** frontend polished, Admin panel added as an honest read-only prototype, all gates green.
**N-5 remains OPEN — no browser exists on this host.**

| Gate | Result |
|---|---|
| Tests without PostgreSQL | **501 passed, 12 skipped** |
| Tests with PostgreSQL 16.2 | **510 passed, 3 skipped** |
| `app/domain/risk.py` branch | **100 %** |
| `app/routing/status_repository.py` branch | **100 %** |
| `tsc -b --force` | **exit 0** |
| `npm run build` | 274.80 kB / **85.39 kB gzip** |
| i18n guard | **112 keys**, both locales, no overclaims |
| Public mutation endpoints | **0** |
| Dependency pins | **12, unchanged** |

---

## 1. Push blocked — the exact blocker

The remote is configured and the commit exists. `git push` fails:

```
$ git remote -v
origin  https://github.com/ah-REE/guaradar (fetch)
origin  https://github.com/ah-REE/guaradar (push)

$ GIT_TERMINAL_PROMPT=0 git push -u origin main
fatal: could not read Username for 'https://github.com': terminal prompts disabled
```

**Why:** this host has no GitHub credentials at all — no `gh` CLI, no `GH_TOKEN`/`GITHUB_TOKEN`,
no `~/.netrc`, no `~/.git-credentials`, no SSH key, no credential helper.

```
$ https://github.com/ah-REE/guaradar   -> HTTP 404 unauthenticated
$ api.github.com/repos/ah-REE/guaradar -> Not Found
```

404 rather than 451/403 means the repo is **private or does not exist yet**; either way an
authenticated push is required and none is possible from here.

**To finish the push, run one of these where credentials exist:**

```bash
# from the project directory
git push -u origin main

# or with a token
git push https://<TOKEN>@github.com/ah-REE/guaradar main
```

Nothing was force-pushed, no history was rewritten, and no existing user work was touched — the
repository did not exist locally before this block, so `3dda617` is the root commit.

---

## 2. Admin panel — what it actually does

**Read-only. No write action is possible, because no mutation endpoint exists.**

### What it shows (real data)

Road-status counts derived from the legs of **real route responses**. Verified against the live API:

```
routes sampled : 4
edges sampled  : 3,752
tally          : open 1,757 · unknown 1,731 · affected 243 · closed 21
verified share : 53.3%
status_source  : seed_generator (matched 0)
```

- Labelled a **SAMPLE**, with the sample size and route count displayed. 24,943 edges exist; four
  routes cannot census them, and the panel says so in both languages.
- `status_source` is echoed **verbatim** from the API. It reads `seed_generator` with
  `0 persisted records matched` — the panel does not upgrade that to anything friendlier.
- **Unknown is never counted as open** and never counts toward the verified share. A test enforces
  this, and mutation-testing confirms it (counting unknown as open fails the suite).
- Data mode `MIXED` is shown with the explanation that forecast may be real while sensors are
  simulated and road status is seed data — matching approved Stage 2 §13.

### What it refuses to show

| Panel | Why it is empty |
|---|---|
| **Incidents** | No incidents table, endpoint or citizen-report channel exists |
| **Alerts** | No alerts table or publication endpoint; the approved bilingual approval flow is unbuilt |
| **Shelters** | No shelter register — and simulating shelter availability would misdirect someone in a flood |

Each renders a dashed **honest empty state** naming the missing component. No invented rows.

### What it prevents

- **No fake authentication.** No login form, no role switcher, no `isLoggedIn`. N-2 is open
  (`current_app_role()` trusts a session setting), so a role selector would imply access control
  that does not exist.
- **Non-dismissible `role="alert"` prototype banner** stating nothing here can change public data.
- **Four approved write actions rendered disabled with visible reasons** (`publish_alert`,
  `verify_incident`, `set_road_status`, `manage_users`) — not hidden, not faked. A control that
  appears to work and silently does nothing is worse than an honestly disabled one.
- **No "changes saved" message anywhere.** A test forbids it, and mutation-testing injects one to
  prove the test bites.

---

## 3. Frontend polish

| Change | File |
|---|---|
| Admin tab added to navigation via bilingual `TAB_LABEL` map, wrapped in `ErrorBoundary` | `App.tsx` |
| Duration caveat moved from three lines below the number to directly beneath it | `RouteScreen.tsx` |
| Two selects: `minWidth: 180` → `150` + `maxWidth: 100%` + `flex: 1 1 150px` (was ~402 px at 375 px viewport) | `RouteScreen.tsx` |
| Sensor grid `auto-fill minmax(230px)` → `auto-fit minmax(180px)` | `App.tsx` |
| `seed_generator` code token made wrappable (`overflowWrap: anywhere`) | `AdminScreen.tsx` |
| Admin data derivation + disabled-action register | `adminData.ts` (new) |
| Admin screen | `AdminScreen.tsx` (new) |
| 34 new bilingual strings | `i18n.ts` |

**Not touched:** routing logic, closure density, coverage thresholds, one-way enforcement, O-8,
`domain/risk.py`, `status_repository.py`, dependency pins.

---

## 4. Corrected stale disclosures (carried from the previous pass)

Two sentences were **false on screen**:

| Claim | Reality |
|---|---|
| "about **50 km** of streets" | **1,084.5 km** — ~21× stale |
| "**Routing is not exposed** … No route is drawn or implied" | the Route tab worked beside it |

Both were hardcoded prose. `/api/health` now reports measured `graph_extent` and the copy
interpolates `{streets}` / `{span}`, so the figure cannot drift again. Street **length** is stated as
length inside a bounded extract, explicitly **not** a share of the city, with directed duplicates
excluded (24,943 directed edges sum to 1,085.5 km; the physical figure is 1,084.5 km over 24,924
unique pairs).

---

## 5. Tests

New this block — `tests/unit/test_admin_panel.py`, **22 tests**:

- no mutation endpoint exists to call; the screen issues no write request
- no "saved" message; every write action disabled with a bilingual reason
- no fake login, role switcher or localStorage role
- prototype banner present, `role="alert"`, not dismissible, states nothing can change public data
- incidents/alerts/shelters each state what is missing; shelter copy refuses to invent locations
- road status labelled a sample, sample size shown, source echoed verbatim
- unknown never counted as open nor as verified
- admin strings complete in both locales; tab reachable; ErrorBoundary isolation
- no safety claim anywhere in the panel

**Mutation-checked, not assumed:**

| Injected defect | Result |
|---|---|
| Added `"Changes saved successfully"` to the panel | **test failed** ✅ |
| Changed `tally.unknown += 1` → `tally.open += 1` | **test failed** ✅ |

Both restored and re-verified green.

---

## 6. What I could not verify

**N-5 — no browser.** No `chromium`/`chrome`/`firefox`/`playwright` binary, no flatpak browser,
`browser_tool` refuses `127.0.0.1`. Nothing was installed.

So the following are **code/arithmetic verified only, never seen rendered**:

- Admin panel layout at 375 px (the `minmax(150px)` grids and the wrappable code token)
- The disable-with-reason list wrapping on a phone
- Map tile-failure behaviour
- Spanish strings as rendered
- Tab bar with three tabs at 375 px

`docs/M12-VISUAL-CHECKLIST.md` covers the public screens. **Add for the Admin tab:** does the
prototype banner stay visible while scrolling; do the disabled buttons look disabled rather than
merely grey; does the empty-state text wrap without clipping.

---

## 7. Files changed

```
frontend/src/AdminScreen.tsx    new    admin view, read-only
frontend/src/adminData.ts       new    derivation + disabled-action register
frontend/src/App.tsx            mod    nav, admin tab, sensor grid, header comment
frontend/src/RouteScreen.tsx    mod    select widths, duration note, extent vars
frontend/src/i18n.ts            mod    34 admin strings + tf() interpolator
backend/app/api/models.py       mod    GraphExtent, HealthOut.graph_extent
backend/app/api/main.py         mod    measured graph facts in /api/health
backend/tests/unit/test_admin_panel.py        new  22 tests
backend/tests/unit/test_m12_disclosures.py    new  24 tests
docs/M12-EVIDENCE.md, docs/M12-VISUAL-CHECKLIST.md, .gitignore
```

106 files committed, 10.4 MB total (includes the 5.6 MB graph artifact the app needs to run).

---

## 8. Remaining limitations

| ID | Status |
|---|---|
| **N-5** | **OPEN** — no browser; nothing visually verified |
| **O-7** | OPEN — risk level unpublished; `risk.py` untouched at 100 % branch |
| **O-8** | OPEN — stale closures still excluded |
| **N-2** | OPEN — no server-side identity; that is why the admin panel has no auth |
| **N-13** | OPEN — turn restrictions not modelled |
| **N-14** | CLOSED for the load path |
| **N-15** | OPEN — `graph.py` 84 % |
| **N-16** | MITIGATED — `demo_clear` reachable from the UI |

Also deferred: real road geometry in `road_segments` (artifact has endpoints only), and the
`--load --dsn` path (needs `psycopg`, which would change pins).

---

## 9. Standing statements

- **Sensors are SIMULATED**; every reading says so.
- **Road geometry is real OSM** for a bounded extract, **not city-wide**. Road **status** is demo
  seed data; `demo_clear` closures are synthetic, never real reports.
- **No route is claimed safe**; duration is labelled an estimate.
- **The Admin panel is an unauthorised read-only prototype.** It cannot change public data.
- **Browser visual verification was not performed.** N-5 remains open.
- No deployment, no money spent, no force-push, no history rewrite, no secrets committed.
