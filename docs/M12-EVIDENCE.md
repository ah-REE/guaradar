# M12 — Frontend-First Demo Completion: Evidence

**Date:** 2026-10-26
**Block:** M12 (frontend-first, 5-hour budget)
**Verdict:** **Priorities 1–5 addressed; Priority 6 gates green. N-5 remains OPEN — no browser
exists on this host, so nothing has been visually verified.**

| Gate | Result |
|---|---|
| Tests without PostgreSQL | **479 passed, 12 skipped** |
| Tests with PostgreSQL 16.2 | **488 passed, 3 skipped** |
| `app/domain/risk.py` branch | **100 %** (250 stmts, unchanged) |
| `app/routing/status_repository.py` branch | **100 %** (unchanged) |
| `tsc -b --force` | **exit 0** |
| `npm run build` | 257.53 kB / **80.59 kB gzip** |
| i18n guard | **77 keys**, both locales, no overclaims |
| Public mutation endpoints | **0** |
| Dependency pins | **12, unchanged** |
| Commits / pushes / deployments | **none** |

---

## The headline: two disclosures on screen were false

Priority 4 predicted this, and it was worse than a wording issue. Both sentences were being
rendered to users.

| Claim on screen | Reality | Factor |
|---|---|---|
| "about **50 km** of streets" | graph holds **1,084.5 km** of mapped street | **~21× stale** |
| "**Routing is not exposed** in this version. No route is drawn or implied here." | the Route tab beside it worked, over the same API | **flatly false** |

The second one is visible on the Status tab while the working Route tab is one click away — a
self-contradiction a judge would notice.

### Root cause, and why it will not recur

Both were **hardcoded prose** in `frontend/src/i18n.ts`. Nothing connected them to the data, so
they aged silently as the graph grew from a small fixture to a real extract.

The fix is not "write a better number". It is:

1. **`/api/health` now reports measured graph facts** (`graph_extent`): segments, nodes, total
   street length, bounding-box span, `synthetic` flag.
2. **The copy interpolates them** — `tf('syntheticGraph', …)` with `{streets}` / `{span}`.
3. **Tests assert the claims** (`test_m12_disclosures.py`, 24 tests).

Measured and now quoted: **1,084.5 km** of street over **24,924 physical segments**, inside roughly
**12.8 × 6.4 km**.

### The trap the brief warned about, avoided

> "Do not blindly substitute total edge length for geographic coverage."

I did not. The wording says street **LENGTH** inside the extract, explicitly denies it is a share
of the city, and does not present it as area coverage. Two further honesty checks:

- **Directed duplicates are excluded.** The naive sum over 24,943 directed edges is 1,085.5 km; the
  physical figure over 24,924 unique unordered pairs is 1,084.5 km. A two-way street must not be
  counted twice, and a test pins this.
- **The extent is stated as bounded**, not city-wide, and "central Guayaquil" was corrected to
  "Guayaquil" because the extract now covers three sectors, not just the centre.

### A content loss my own test caught

While rewriting `syntheticGraph` I dropped the clause "road STATUS is demo seed data, not a live
municipal feed". The new test failed on it and the clause was restored. Without that test the
sentence would have become accurate about distance while silently losing its demo-data disclosure —
a worse outcome than the bug being fixed.

**Corrected text, rendered with live API values:**

> Road geometry comes from a bounded real OpenStreetMap extract of Guayaquil — 1,084.5 km of mapped
> street inside roughly 12.8 × 6.4 km. That is street LENGTH inside the extract, not a share of the
> city; outlying districts are not included, so any coverage percentage describes this extract only.
> The road STATUS shown is demo seed data, not a live municipal feed.

> Routing **IS** available on the Route tab, and it runs over this extract only. A route existing in
> the data does not mean the road is open, passable or safe in reality.

---

## Priority 2 — Status dashboard: content was already complete

Inspected before editing, per the brief. Every item requested is already rendered:

| Required | Present |
|---|---|
| rainfall total + peak forecast, with units | yes (`totalRainfall`, `peakHourly`) |
| forecast vs measured observation | yes (`forecastNotObservation`) |
| retrieval time + model-run unavailability | yes (`fetchTime`, `modelRunUnavailable`, `modelRunNeverInferred`) |
| six sensor cards, `SIMULATED` prominent | yes (`simulatedBadge`, `simulatedExplanation`) |
| prototype vs official threshold | yes (`thresholdNote`) |
| loading / API failure / empty / missing reading | yes (`loading`, `errorBody`, `sensorFeedEmpty`, `unavailable`) |
| limitations / provenance section | yes — this is where both false claims lived |

So no rebuild was warranted. The substantive change was **fixing the false content inside** that
section, plus responsive fixes in Priority 5. No new charts were added: nothing here has measured
water data, and a chart would imply observations that do not exist.

---

## Priority 3 — Route planner

The `demo_clear` selector landed in the previous M12 pass and is unchanged: defaults to baseline,
refetches on change, keyboard-labelled, non-dismissible bilingual demo banner, unknown profile still
**422**.

Added this pass:

- **Duration now labelled where the number is.** The caveat sat three lines below the metrics,
  where nobody connects it to the value. The short note "estimate, not live travel time" now sits
  directly under the duration; the fuller sentence moved into the warnings detail. Both locales.
- Verified the card already distinguishes the four outcome classes **by text as well as colour**
  (badge text, `routePhase1`/`routePhase2`, `routeLowCoverage`, `routeAllHazard`), so colour is not
  the only channel.
- **`routeNotSafe` still rendered**, and a test forbids `is safe` / `guaranteed` / `flood-proof` /
  `risk-free` anywhere in `RouteScreen.tsx`.

**Not touched:** routing logic, closure density, coverage thresholds, one-way enforcement, O-8.

---

## Priority 5 — Responsive fixes (real overflow found)

Two genuine 375 px failures, both fixed:

| Defect | Arithmetic | Fix |
|---|---|---|
| Two `select` elements at `minWidth: 180` in a flex row | 180+180+10 gap+32 padding = **~402 px > 375** | `minWidth: 150`, `maxWidth: 100%`, `flex: 1 1 150px` |
| Sensor grid `repeat(auto-fill, minmax(230px, 1fr))` | left an empty track on narrow screens | `auto-fit` with a `180px` floor |

Touch targets already met the 44 px minimum; a test now asserts no component regresses below it.

**I could not confirm these visually** — they are arithmetic and code inspection only. The checklist
covers §7 narrow viewport for you to confirm.

---

## Priority 6 — Verification

### Five routing scenarios, live API

```
1 eligible    profile=demo_clear fixture=True  all_hazard=False rec=True
2 hazard      profile=baseline   fixture=False all_hazard=True  rec=False
3 low_coverage profile=baseline  fixture=False all_hazard=False rec=False
4 refused      refused=True routes=0  "19891 m from the nearest road (limit 60 m)"
5 unknown      coverage 54.94% < 100% => unknown edges counted as unverified, never open
```

### Test growth

```
403 passed, 10 skipped   (start of M12)
479 passed, 12 skipped   (now, without PG)   +76
488 passed,  3 skipped   (now, with PG 16.2)  +85
```

New this pass: `tests/unit/test_m12_disclosures.py` — 24 tests covering measured facts, both
corrected disclosures, placeholder resolution, route-card labelling, responsive invariants, and the
comment-discipline check below.

### Defects found in my own tests (4, all caught by running them)

| Defect | Cause |
|---|---|
| Asserted "not the whole city" against a key that words it differently | Per-key phrasing hardcoded; now asserts the *claim* |
| Same for the demo-data clause | ditto |
| Placeholder-supplier scan flagged `{name}` from `tf()`'s own implementation | Scanned the whole file instead of the catalogue region |
| **A rewrite silently dropped a disclosure clause** | Detected only because the test asserted content, not just absence |

The first edit attempt also failed silently on six string replacements (Spanish uses literal UTF-8
accents while English uses `\u2014` escapes). Caught because each replacement asserted its target
existed before writing.

---

## Priority 4 — remaining disclosure audit

Every user-visible limitation string was checked against current code and the graph artifact:

| Required statement | Status |
|---|---|
| real OSM geometry covers a bounded subset, not the whole city | **stated** (`syntheticGraph`, `mapNotRealStreets`) |
| road-status records are demo seed data, not a live feed | **stated in both** |
| sensor readings are simulated | **stated** (`simulatedBadge`, `simulatedExplanation`) |
| risk model unvalidated, O-7 unresolved | **stated** (`riskNotApproved`) |
| no verified live flood map / official alerts / shelter feed | **stated** (`noFabricatedData`) |

One additional stale claim found and fixed in a **source comment** (`App.tsx` header said "routing
is not exposed yet"), with a regression test. Comments are not rendered, but that is where the wrong
on-screen sentence was copied from.

---

## N-5 — still open, no browser

Re-checked: no `chromium` / `chrome` / `firefox` / `playwright` binary, no flatpak browser,
`browser_tool` refuses `127.0.0.1`. **No browser was installed** (no dependency change).

`docs/M12-VISUAL-CHECKLIST.md` is updated for this pass — it now also covers the scenario selector,
the estimate label placement, and the two corrected disclosures. Highest-value sections remain
**§6 tile-load failure** (the blank-page path) and **§5.1 Spanish completeness**.

**Nothing in this document claims the interface was seen.**

---

## Deferred by the 5-hour limit

| Deferred | Why |
|---|---|
| Route comparison table (sortable) | Cards already expose all five comparison fields; a table is decoration, and the brief says defer decorative work |
| `--load --dsn` path | Needs `psycopg`, which would change pins. `psql -f` is tested |
| True road geometry in `road_segments` | Artifact carries endpoints only; needs a separate extract pass |
| N-13 turn restrictions | Out of scope for a frontend block |

---

## Blockers

| ID | Status |
|---|---|
| **O-7** | OPEN — risk level still unpublished; `risk.py` untouched at 100 % branch |
| **O-8** | OPEN — stale closures still excluded, unchanged |
| **N-1** | OPEN — `model_run_at` null, never inferred |
| **N-2** | OPEN — no mutation endpoint exists |
| **N-5** | **OPEN — no browser; checklist provided, nothing seen** |
| **N-6** | OPEN — ingestion writes disabled by default |
| **N-13** | OPEN — turn restrictions not modelled |
| **N-14** | CLOSED for the load path (M12 Part C) |
| **N-15** | OPEN — `graph.py` 84 % |
| **N-16** | MITIGATED — baseline unchanged; `demo_clear` reachable from the UI |

---

## Recommended next block

**N-5 needs you** — run `docs/M12-VISUAL-CHECKLIST.md`, §6 first. It is the only remaining item that
cannot be closed from this environment, and it is the one most likely to expose a real defect.

If you would rather I continue autonomously, **N-13 turn restrictions** is the largest remaining
correctness gap: one-way travel is structurally enforced, but an illegal *turn* onto a one-way
street is still reachable. Self-contained, testable without a browser, independent of N-2.

---

## Standing statements

- **Sensors are SIMULATED**; every reading says so.
- **Road geometry is real OSM** for a bounded extract, **not city-wide**. Street length (1,084.5 km)
  is quoted as length, never as area coverage. Road **status** is demo seed data; `demo_clear`
  closures are synthetic demo data, never real reports.
- **No route is claimed safe.** Coverage is stated, hazard crossings labelled, low coverage never
  recommended, duration labelled an estimate.
- No commits, pushes, deployments, destructive migrations, or dependency changes.
