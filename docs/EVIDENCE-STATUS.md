# Evidence Status — What Is Documented vs. What Has Actually Run

**Date:** 2026-10-25
**Purpose:** answer review point 2 without flattering the project. Nothing in this table may be upgraded
by argument, only by executing a test and citing its output.

**Standing rule:** a claim may only appear in this project's documentation in the form the evidence
supports. "Designed", "specified", "documented" and "passing" are different words and are not
interchangeable. No property in Stage 3 §17.1 is described as passing anywhere in this project.

---

## Evidence levels

| Level | Meaning | Permitted wording |
|---|---|---|
| **E0 — Claimed** | Stated in a planning document. No artefact. | "specified", "proposed", "designed to" |
| **E1 — Researched** | Verified against a published source or API documentation. | "documented", "per the source" |
| **E2 — Probed** | Verified by running an ad-hoc script whose output exists. | "probed", "measured on <date>", with the script named |
| **E3 — Tested** | Verified by a committed test in the project's suite, with output captured. | "passing", with the test id and date |
| **E4 — Demonstrated** | E3 plus observed end-to-end behaviour in the running application. | "verified end-to-end" |

**Current project ceiling: E2.** No committed test suite exists, because no application code exists.
Therefore **nothing in this project is at E3 or E4**, and no document claims otherwise.

---

## What has actually run

These are the only executed verifications. Each names the script and what its output showed.

| # | Verification | Script | Result observed | Level |
|---|---|---|---|---|
| 1 | Open-Meteo forecast returns hourly precipitation + probability | inline `curl`, 2026-10-25 | HTTP 200; 24 hourly values; units `mm`, `%`; sample `[1.7, 2.2, 1.6, 2.0, 3.6, 0.3]` | E2 |
| 2 | Open-Meteo elevation returns 90 m Copernicus DSM | inline `curl` | six points: `[10.0, 8.0, 7.0, 7.0, 6.0, 3.0]` m | E2 |
| 3 | SRTM 1-arcsec 30 m tiles are fetchable and decodable | `research/terraincheck.py` | 25,934,402 bytes → 3601×3601 grid; six points 4–14 m | E2 |
| 4 | 30 m SRTM differs from 90 m DSM by only 1–4 m | `research/terraincheck.py` | per-point deltas +4/+2/+2/+1/+1 m | E2 |
| 5 | Guayaquil's OSM graph is routable | `research/graphcheck.py` | 6,202 ways; 22,499 nodes; 1,184.9 km; **96.9 % in one component**; 32.8 % junctions; 1.34× detour on an 11.86 km straight-line route → 15.90 km path | E2 |
| 6 | GEOGloWS `getriverid` works for the Guayas | inline `curl` | `{"river_id": 670068009}` | E2 |
| 7 | GEOGloWS `forecaststats` / `forecastrecords` work | inline `curl` | CSV; 120 ensemble rows @3 h, 240 high-res rows @1 h; flow 5,050–8,844 m³/s | E2 |
| 8 | GEOGloWS `returnperiods` is broken | inline `curl` | **HTTP 500**, `No variable named 'logpearson3'` | E2 |
| 9 | A finite closed-road penalty is unsafe; two-phase filter is safe | `research/routing_invariant.py` | penalty-only: **1 violation / 1201 graphs**; two-phase and state-space: **0 violations / 1201**; adversarial case shows closed route at cost 12.50 beating open route at 246.00 | E2 |
| 10 | Backend dependency pins have a Python 3.14 install path | PyPI metadata queries | all pins pure-python except numpy (cp314 manylinux wheels); `uvicorn[standard]` extras all have cp314 wheels | E2 |
| 11 | `networkx 3.7` excludes exactly Python 3.14.1 | PyPI metadata | `requires_python = !=3.14.1,>=3.12` | E2 |
| 12 | Overpass requires a User-Agent | inline `curl` | HTTP **406** without UA, HTTP 200 with UA | E2 |
| 13 | INAMHI publishes Guayaquil-specific products but no public API | portal read + navigation inspection | products listed; no API documentation found | E1/E2 |
| 14 | Supabase and Render free-tier terms | published pricing/limits pages | Supabase: 500 MB, pauses after 1 week idle. Render: spins down after **15 min**, ~**1 min** cold start, 750 instance-hours/month | E1 |

---

## What is only specified — the 44 safety properties

**None of these has run.** They are test specifications. They exist so Stage 5 has an executable contract
rather than good intentions.

> **Count changed during the 2026-10-25 reconciliation: 32 → 43, then → 44.** The growth is not inflation — it is a
> direct consequence of three corrections that each removed an unsafe rule and replaced it with testable
> guarantees: the withdrawn coverage cap (`RISK-3`, `RISK-4`, `RISK-4c`, `RISK-8b`, `RISK-8c`), the repaired
> route-coverage policy (`ROUTE-2b`, `ROUTE-2c`, `ROUTE-2d`), and the previously missing bilingual and
> data-mode requirements (`I18N-1…4`, `SIM-3`). Every added property guards a defect found in this review.

| Property group | Ids | Status | What would constitute evidence |
|---|---|---|---|
| Risk engine | `RISK-1` … `RISK-10`, `RISK-4c`, `RISK-4d`, `RISK-8b`, `RISK-8c` | **SPECIFIED, NOT EXECUTED** | `pytest backend/tests/unit/test_risk.py` output showing each id as a named test, all passing |
| Routing | `ROUTE-1`, `ROUTE-1b`, `ROUTE-2`, `ROUTE-2b`–`ROUTE-2d`, `ROUTE-3` … `ROUTE-7` | **SPECIFIED, NOT EXECUTED** (`ROUTE-1b` has an E2 probe behind it, not a committed test) | port `research/routing_invariant.py` into the suite; assert the penalty design fails and two-phase passes |
| Terrain | `TERR-1`, `TERR-2` | **SPECIFIED, NOT EXECUTED** | static-analysis job failing on an injected violation |
| Consistency | `SYNC-1`, `SYNC-2`, `SYNC-3` | **SPECIFIED, NOT EXECUTED** | integration test output |
| Provenance | `PROV-1`, `PROV-2` | **SPECIFIED, NOT EXECUTED** | contract test output |
| GEOGloWS | `GEO-1` … `GEO-4` | **SPECIFIED, NOT EXECUTED** (`GEO-1`'s parsing trap is E2-known from a manual parse, but no committed fixture test exists) | fixture CSV test output |
| Simulation | `SIM-1`, `SIM-2`, `SIM-3` | **SPECIFIED, NOT EXECUTED** | DB constraint test output; `SIM-3` asserts `LIVE` is unreachable |
| Secrets | `COST-1` | **SPECIFIED, NOT EXECUTED** | build-time grep job output |
| i18n | `I18N-1` … `I18N-4` | **SPECIFIED, NOT EXECUTED** | key-parity build gate, snapshot of §15.2 strings, Spanish-token lint, locale-format unit tests |

**Explicit statement:** no document in this project says any of these pass. The phrase "100 % branch
coverage on `domain/`" is a *gate to be enforced at Stage 5*, not an achievement.

---

## The clean-install milestone

| Claim | Actual status |
|---|---|
| "Dependencies are pinned" | **TRUE at E1** — exact versions resolved from PyPI metadata |
| "The pins have an install path on Python 3.14" | **TRUE at E2** — wheel availability inspected per package |
| "A clean install succeeds" | **NOT ESTABLISHED.** No package has been installed. No venv created. |
| "The stack runs" | **NOT ESTABLISHED.** No process has been started. |
| "The app builds" | **NOT ESTABLISHED.** No `npm ci`, no Vite build. |

**Defined as the first Stage 5 milestone** (M0): create venv → `ensurepip` → install pins → import smoke
test → `uvicorn --version` → `npm ci` → `npm run build` → capture the resolved freeze and lockfile.
**Until M0 output exists, "clean install" is a plan, never a result.** If M0 fails, the pre-agreed
response is to recreate the venv on Python 3.13 and keep all library pins unchanged.

---

## What unit tests could never establish

Even after every property passes, these remain outside their reach — stated now so no later summary can
quietly imply otherwise.

| Cannot be established by any test in this suite | Why |
|---|---|
| That the risk level predicts actual flooding | The model is an unvalidated heuristic (R9). There is no ground-truth flood-depth dataset, and none can be collected during a hackathon. |
| That a route is safe to travel | The app knows only recorded road status. A successful search means "a path exists in the data". |
| That the sensors reflect reality | All sensors are simulated. `SIM-1` proves they are *labelled* as such, not that they are real. |
| That shelters are open | Shelter status is an admin assertion with an expiry, not a confirmed fact. |
| That OSM coverage is complete outside the sampled bbox | Only central Guayaquil was measured. |
| That the system behaves correctly under real concurrent load | No load testing was designed or performed. |
| That free-tier hosting stays available | No SLA on any free plan; terms may change mid-event. |

**The distinction that matters most:** unit tests establish that *the implementation matches the
specification*. They establish nothing about whether the specification matches the world. R9 is that gap,
it is labelled in the product, and it is not reducible by testing.

---

## Downgrade log

Corrections made during this project, kept because a clean history would be less informative than an
honest one.

| # | Claim previously made | Correction |
|---|---|---|
| 1 | Elevation service returns the brief's SRTM 30 m | It is Copernicus GLO-90 (90 m) DSM. SRTM 30 m was then sourced separately. |
| 2 | Guayaquil is at 3–10 m | True for the 90 m DSM sample; SRTM 30 m reads 4–14 m. Both reported. |
| 3 | GEOGloWS `forecaststats` looked like a flatline at ~5050 | Parsing artefact — blank ensemble cells in an hourly grid. Real series varies 5,050–8,844. |
| 4 | Closed edges should carry a large finite penalty | **Refuted by probe.** Two-phase filter adopted; see `research/routing_invariant.py`. |
| 5 | SRTM tile for Guayaquil is `S02W080` | Wrong: tiles are named by SW corner. Correct tile is `S03W080`. |
| 6 | Cost for the demo is $0 | Recast as a description of current free-tier terms, not a guarantee; no uptime claim. |
| 7 | Stage 1 header contained Stage 2 text | Editing error, reverted; Stage 1 verified correct. |
| 8 | An early routing-invariant probe "proved" two-phase safe while reporting violations | That probe had a reconstruction bug; rewritten before drawing conclusions. |
| 9 | **Coverage < 0.6 caps the risk level at 2** (`RISK-3`, `RISK-4`) | **Withdrawn as unsafe.** Losing the sensor and trend weights caps achievable coverage at 0.55, permanently below the threshold, so *every* sensor outage capped the level at Caution — even with heavy rain, verified reports and closed roads. Severity and confidence are now separate outputs, with a precaution floor that can only raise. See Stage 3 §8.4. |
| 10 | **Route coverage < 60 % is a "rejection criterion"**, while Marginal 40–59 % and Unknown-only 0 % routes were also served | **Contradiction removed.** Coverage is now the *Recommended / Not-recommended* boundary at 60 %, with explicit bands (High ≥ 80, Moderate 60–79, Low 1–59, None 0) and all 8 class×band combinations defined. Rejection now means only *no path* or *snap > 60 m*. See Stage 3 §9.1. |
| 11 | **"Level driven by the sensor, because it is the observation"** on rain-vs-sensor conflict | **Correction.** That wording let one low sensor outvote heavy rain, verified reports and closures. All inputs now contribute to the score, floors can raise, and disagreement is stated rather than resolved. See Stage 3 §8.3. |
| 12 | Stage 1 mockup and sample copy were partly Spanish-first | Corrected to English-first with Spanish alongside; behavioural requirements unchanged and Stage 1 not reopened. See Stage 3 §15.4. |
| 13 | LIVE/SIMULATED/MIXED required by approved Stage 2 but absent from Stage 3 | Gap closed: Stage 3 §10.1 computes the mode server-side and adds `SIM-3`, since `LIVE` is unreachable here. |
| 14 | **Precaution floor triggered on a "heavy rain" threshold that is defined nowhere** | **Owner decision 2026-10-25 (D23): rain trigger DISABLED** until a defensible threshold and source exist. The 40 mm/6 h scoring saturation is explicitly **not** an approved warning threshold. Forecast UI omits any "heavy rain" label (Stage 1 §6 already mandated this fallback). Blocker **B13**. |
| 15 | **"30–40 % of segments unverified" cited as if measured** | **Never measured.** The graph probe measured connectivity and detour, not status coverage. Flagged in Stage 3 §9.4; the number must not be quoted as evidence. |
| 16 | **Safety-property count 43 → 44** after adding `RISK-4d` (asserts the disabled rain trigger stays disabled) | Recount applied across all live documents. `STAGE-3-RECONCILIATION.md` retains "43" because it is a dated report of that review — accurate as of its own date. |

---

## Status

Stage 1: **APPROVED** 2026-10-25.
Stage 2: **APPROVED** 2026-10-25 (unchanged; D26 preserved its publishing requirement).
Stage 3: **APPROVED 2026-10-26** on the reconciled decisions D23–D28.
Stage 4: **presented 2026-10-26, awaiting approval.** No code exists.
Implementation: **not started** — no installs, no schemas, no code, no commits, no deployments.

**Evidence ceiling remains E2.** Approval of a plan does not execute it: the 44 safety properties are still
specifications that have never run, and no dependency has been installed. Stage approval changes what is
*permitted*, not what has been *verified*.
