# M11 — Demo Readiness, Reproducible Scenarios: Evidence

**Date:** 2026-10-26
**Block:** M11 (A: browser · B: demo scenarios · C: reproducible build · D: phase-2 review · E: gates)
**Verdict:** **Parts B, C, D and E complete. Part A (browser visual verification) NOT done — N-5
remains open.**
**Scope held:** no pooling, no admin console, no deployment, no commit, no destructive migration.

---

## 1. Baseline before any change

```
366 passed, 10 skipped
```
Status-tab fix confirmed intact (`America/Guayaquil` present 4×, `ErrorBoundary.tsx` present,
both services responding). Nothing was reverted or refactored.

---

## 2. Part A — browser: **NOT AVAILABLE, N-5 stays OPEN**

Searched systematically before declaring this:

| Check | Result |
|---|---|
| `chromium`, `chromium-browser`, `google-chrome`, `google-chrome-stable`, `firefox`, `firefox-esr`, `brave`, `microsoft-edge`, `epiphany`, `wkhtmltoimage`, `cutycapt`, `xvfb-run` | **none found** |
| `flatpak list --app` for any browser | none |
| `playwright` / `puppeteer` / `jsdom` in `frontend/node_modules` | none |
| `playwright` / `selenium` in system Python | both `ModuleNotFoundError` |
| `browser_tool` → `http://127.0.0.1:5173/` | `browser_private_target_denied` |

**No browser exists on this host and the automation tool refuses private-network targets.** I did
not install one: the brief says not to add large dependencies or change the system environment
without justification, and "so I can screenshot it" is not that justification.

**N-5 therefore remains open.** Specifically still unverified by me: map framing and the
three-sector extent, OSM attribution legibility, route line styling, hazard-crossing visual
distinction, low-coverage warnings in situ, tile-load failure behaviour, Spanish strings rendered,
and mobile layout.

The user has manually confirmed the Status tab and route checking work. That is real evidence for
those two behaviours, but it does not establish the map, tile failures, or mobile layout.

**What was verified instead** (transport-level, not visual): the dev server proxies `/api` to
FastAPI; every endpoint returns typed JSON through that proxy; the production build compiles under
strict TypeScript. That is deliberately not called visual verification.

---

## 3. Part B — demo scenarios: **COMPLETE**

### The N-16 mechanism, quantified first

Before changing anything, the reason phase 2 dominates was measured rather than assumed:

```
edges: 24,943   closed: 861 (3.5 % density)

path of  50 edges avoids every closure: 17.27 %
path of 100 edges:                       2.98 %
path of 200 edges:                       0.089 %
path of 300 edges:                       0.0026 %
```

A cross-sector route traverses 200–300 edges, so the probability it avoids all closures is
**0.09 %–0.003 %**. Phase 1 almost never succeeds. That is the two-phase guarantee working
correctly on dense demo status — not a bug.

### The five scenarios, with actual API outcomes

| # | Scenario | Profile | Actual result |
|---|---|---|---|
| 1 | **eligible** — avoids all closures, recommended | `demo_clear` | `refused=false`, `rec=true`, `phase=1`, `clear`, band **high**, cov **84.5 %** |
| 2 | **hazard_crossing** — phase 1 fails, phase 2 labelled | `baseline` | `all_routes_hazard_crossing=true`, every route `phase=2`, `rec=false`, label *"crosses a closed road"* |
| 3 | **low_coverage** — served, not recommended | `baseline` | `refused=false`, routes present, band `low`, `rec=false` |
| 4 | **refused** — outside the extract | `baseline` | `refused=true`, `routes=[]`, *"starting point is 19891 m from the nearest road (limit 60 m)"* |
| 5 | **unknown_edge** — no record stays unknown | `baseline` | index-level: `status_of=unknown`, `is_verified=false`, `is_closed=false` |

Scenario 1 measured end to end through the dev-server proxy:

```
profile: demo_clear | fixture: True
  route-1 phase=1 clear band=high cov= 84.5% rec=True
  route-2 phase=1 clear band=high cov= 87.2% rec=False
  route-3 phase=1 clear band=high cov= 86.0% rec=False
```

Baseline on the same pair, for contrast:

```
profile: baseline | fixture: False
  route-1 phase=2 hazard_crossing band=low cov=54.9% rec=False
  route-2 phase=2 hazard_crossing band=low cov=54.4% rec=False
  route-3 phase=2 hazard_crossing band=low cov=53.9% rec=False
```

### Why two profiles, and why that is not a cop-out

Scenarios 1 and 2–3 are **mutually exclusive on one dataset**: with 3.5 % closures an eligible
route is essentially unreachable, and with 6 closures a forced phase-2 case is unreachable (all 30
sensor pairs become eligible). Rather than tune one generator to fake both — which would have
weakened the honesty of every other result — each scenario uses the profile that genuinely produces
it, and the response **discloses which profile was used**.

### Isolation guarantees

| Property | How it holds |
|---|---|
| Baseline behaviour unchanged | `test_baseline_profile_unchanged_by_the_fixture_existing` recomputes the original algorithm inline and compares 500 edges |
| Fixture writes nothing | profiles are pure functions of `(graph, now, name)`; no DB, no files |
| Cannot be mistaken for live data | `status_profile`, `profile_is_demo_fixture`, and a `DEMO FIXTURE —` provenance note on every response |
| Deactivation destroys nothing | not requesting it *is* deactivation; no state to restore |
| Closure count fixed and small | exactly 6, asserted |
| Deterministic | same inputs → same statuses, asserted |

---

## 4. Part C — reproducible build: **VERIFIED, artifact preserved**

```
$ cd backend && ../.venv/bin/python -m app.routing.build_cli --check
graph build OK
  segments                 24943
  graph_nodes              20386
  graph_edges              24943
  weak_components          23
  largest_component_pct    97.6
  total_length_m           1085491.6     (1,085 km)
  synthetic                False
  oneway                   {'both': 12553, 'forward': 12390, 'backward': 0, 'oneway_total': 12390}
  direction_basis          {'tagged oneway=yes': 2656, 'tagged oneway=no': 173,
                            'no oneway tag (not evidence of a restriction)': 2970,
                            'implied by junction=roundabout': 10}
--check: nothing written
```

| Check | Result |
|---|---|
| Works without network | yes — reads `data/osm-guayaquil-demo-sectors.json` from disk |
| Deterministic | **byte-identical** across two builds (`sha256 581aa7fe17d063e7…` both times) |
| Stable source identity | every edge decodes to `(way_id, ordinal)`; validated |
| Repeated builds do not duplicate | `rebuild_ids_identical: true` is a build gate |
| One-way adjacency correct | 12,390 `forward`, 0 `backward`, 12,553 `both` |
| Failed build leaves previous artifact | atomic `os.replace`; validator prints *"previous artifact left untouched"* |
| Provenance and extent accurate | OSM timestamp `2026-10-26T02:08:42Z`, bbox lat −2.2350…−2.1350 / lon −79.9250…−79.8800 |

**Existing artifact preserved** — `data/graph-artifact.json` still stamped `07:43:34`, unchanged.
The brief said not to regenerate unnecessarily, and `--check` proved it was already valid.

Extent wording: **a bounded extract of central Guayaquil covering three demo sectors, ~12.8 × 6.4 km
— not city-wide.** No document claims otherwise.

---

## 5. Part D — phase-2 review: **EXPLAINED, and a separate profile added**

Diagnosis in §3. The brief forbids simply lowering closure frequency, so the baseline generator is
**untouched** and a separate `demo_clear` profile was added instead.

### How to activate and how to restore

```
# Baseline (default) — unchanged behaviour
GET /api/public/route?...&profile=baseline      (or omit `profile`)

# Demo fixture — 6 synthetic closures, so an eligible route is demonstrable
GET /api/public/route?...&profile=demo_clear
```

Restoring the baseline is **omitting the parameter**. Nothing is written, so there is no data to
undo and no cleanup path that could fail. An unknown profile returns **422**, so a typo cannot
silently fall back to a demo fixture.

Every invariant preserved — the engine was not modified at all:

| Invariant | Evidence |
|---|---|
| Phase 1 structurally excludes closed edges | `test_phase1_never_crosses_a_closure_under_any_profile` (both profiles) |
| Phase 2 only when phase 1 finds nothing | baseline returns `phase=2` only; demo_clear returns `phase=1` only |
| Closure-crossing never recommended | `test_scenario_hazard_crossing_never_recommended` |
| Unknown/stale cannot improve eligibility | `test_scenario_unknown_edge_stays_unknown`, `test_stale_closure_still_excluded_under_any_profile` |
| Low/zero coverage never recommended | `test_recommendation_requires_moderate_coverage_in_every_profile` |
| One-way directionality enforced | `test_one_way_adjacency_untouched_by_profiles` |
| O-8 stale-closure behaviour unchanged | asserted under both profiles |

---

## 6. Part E — gates

```
$ cd backend && ../.venv/bin/python -m pytest
403 passed, 10 skipped          (was 366; +37 M11 tests)
```

```
app/domain/risk.py              250    0   102   0   100%     ← required gate holds
app/routing/status_repository.py 136    0    48   0   100%     ← required gate holds
app/routing/demo_profiles.py      62    3    26   3    93%
app/routing/scenarios.py          30    2     6   2    89%
```

```
$ cd frontend && npx tsc -b --force    → exit 0
$ npm run build                         → built in 122ms
dist/assets/leaflet-src-*.js   148.60 kB │ gzip: 43.32 kB
dist/assets/index-*.js         253.37 kB │ gzip: 79.31 kB
$ node src/__i18n-check.mjs             → 43 keys, both languages, no overclaims
```

Other: **dependencies unchanged** (12 pins) · **no mutation verbs** · **no commits, pushes,
deployments** · **no destructive migration**.

### Status-tab regression coverage (20 tests)

| Requirement | Test |
|---|---|
| Timestamp formatting succeeds with `America/Guayaquil` | `test_frontend_pins_guayaquil_timezone` |
| No incompatible `Intl` option combination | `test_frontend_never_combines_style_options_with_timezonename` — scans every `.ts*` file, comments stripped so the fix's own explanatory docstring is not flagged |
| Formatter cannot throw | `test_stamp_is_wrapped_against_throw` |
| Missing readings render as unavailable, not zero | `test_frontend_has_null_safe_number_formatter`, `test_num_formatter_semantics_documented` |
| Payload can legitimately contain `latest: null` | `test_sensor_payload_can_legitimately_contain_null_latest` |
| ErrorBoundary prevents a section blanking the app | `test_error_boundary_exists_and_is_wired` |
| Boundary does not fabricate values | `test_error_boundary_does_not_fabricate_values` |
| Bilingual error + retry | asserted in `test_error_boundary_exists_and_is_wired` |
| Health disclosure still matches graph source | `test_health_disclosure_still_matches_graph_source` |
| Route form and API contract do not regress | `test_route_form_demo_points_all_snap`, `test_frontend_demo_points_match_backend`, `test_route_endpoint_default_profile_is_baseline` |

---

## 7. Defects found and fixed

| # | Defect | Surfaced by | Fix |
|---|---|---|---|
| **D-1** | **`status` shadowed inside the route handler.** `from fastapi import ... status` collided with the local `status = get_route_status(...)`, so the profile-validation branch raised `UnboundLocalError` instead of a 422 | `test_unknown_profile_rejected_by_api` | FastAPI constants imported as `http_status` |
| **D-2** | My regression scanner matched **across brace boundaries**, so it flagged unrelated code | `test_frontend_never_combines_style_options…` failing on correct code | Regex restricted to a single `{…}` object; **comments stripped first**, because the fix's own docstring quotes the illegal combination while explaining it |
| **D-3** | `rf"...[^}}]..."` in an f-string: `}}` becomes a literal `}`, so the character class silently matched nothing | demo-point comparison test | Pattern built by concatenation |
| **D-4** | Expected value formatted `:.4f` then string-matched: `-2.227579` rounds to `-2.2276` but the file says `-2.2275`, so a **correct** coordinate failed | same test | Parse the literal, compare floats with tolerance |
| **D-5** | A text replacement silently did not apply, and I trusted it | test still failing after "fixed" | Replaced by line range, then re-read the file |

D-5 is the one worth naming: three of the five defects were in my own verification code, and one of
them was a "fix" that never landed. The tests are what caught all of it.

---

## 8. Blockers

| ID | Status after M11 |
|---|---|
| **O-7** | OPEN, unchanged — `risk.py` untouched at 250 statements / 100 % branch; no risk level displayed |
| **O-8** | OPEN, provisional — stale closures still excluded; now also asserted under both profiles |
| **N-1** | OPEN — `model_run_at` null, never inferred |
| **N-2** | OPEN — no mutation endpoint exists |
| **N-5** | **OPEN — Part A could not be performed. No browser on this host; automation tool refuses private targets.** |
| **N-6** | OPEN — ingestion writes disabled by default |
| **N-13** | OPEN — turn restrictions not modelled (one-way *is* enforced) |
| **N-14** | OPEN — `road_segments` loading still script-driven |
| **N-15** | OPEN — `graph.py` 84 %; no `backward` edges exist in real data |
| **N-16** | **MITIGATED, not closed** — baseline unchanged; a labelled `demo_clear` fixture now makes an eligible route demonstrable |

---

## 9. Recommended next block

**Two candidates, in this order:**

1. **Visual verification hand-off (N-5).** No browser exists here, so the only path is you viewing
   it. A short checklist would close N-5 properly: map framing, attribution visibility, the
   hazard-crossing vs clear distinction, Spanish strings, narrow viewport, and tile-failure
   behaviour with the network throttled. I can write that checklist as a document you run through.
2. **N-14 — a documented `road_segments` load step** driven by the graph artifact, so the OSM
   pipeline is genuinely end to end rather than script-driven.

Pooling (N-9) and the admin console stay blocked on N-2 until server-side identity derivation is
verified.

---

## 10. Standing statements

- **Sensors are SIMULATED**; every reading and response says so.
- **Road geometry is real OSM** for a bounded three-sector extract — **not city-wide**. Road
  **status** is seed/demo data, and `demo_clear` closures are explicitly synthetic demo data, never
  real reports.
- **No route is claimed safe.** Coverage is stated; hazard crossings are labelled; low coverage is
  never recommended.
- **Browser visual verification was not performed**, and N-5 remains open.
- No commits, pushes, deployments, or destructive migrations.
