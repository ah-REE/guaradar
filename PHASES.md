# PHASES.md — Guaradar Roadmap and Progress

**Last updated:** 2026-10-25
**Source of truth for project progress.** Update whenever approvals, tasks, or significant decisions change.

---

## 1. Objective and approved scope

**Guaradar** — flood-resilience web application for Guayaquil, Ecuador.
Event: HACK2IMPACT 2026 · Track: Nu Zeta Track 1 — Heavy Rain & Flood Resilience in Guayaquil.
Tagline: *Detect Early. Navigate Safely.*

Two interfaces over one system:

1. **Public Safety Portal** — citizens: risk, forecast, map, outlook, safe routing, shelters, reporting.
2. **Admin Control Center** — authorised staff: sensors, incidents, road status, alerts, shelters, prioritisation.

Currently approved scope: **the project brief only** (identity, constraints, approval sequence).
No interface, stack, or requirement has been approved yet.

---

## 2. Approval status of planning stages

| Stage | Content | Status |
|---|---|---|
| 1 | Public Interface | **APPROVED 2026-10-25** (`docs/STAGE-1-PUBLIC-INTERFACE.md`) |
| 2 | Admin Interface | **APPROVED 2026-10-25** (`docs/STAGE-2-ADMIN-INTERFACE.md`) |
| 3 | Technology Stack and Architecture | **APPROVED 2026-10-26** (`docs/STAGE-3-ARCHITECTURE.md`; digest: `docs/STAGE-3-DECISION-SUMMARY.md`; decisions D23–D28; ledger: `docs/EVIDENCE-STATUS.md`) |
| 4 | Other Requirements and Implementation Plan | **APPROVED 2026-10-26** — with R-17 = (a) as **D29** and a **one-day constraint** (D30); one-day schedule in §16 (`docs/STAGE-4-REQUIREMENTS-PLAN.md`) |
| 5 | Implementation | **IN PROGRESS 2026-10-26** — **M0–M12 done** (464 tests w/ PG; demo selector in UI, N-14 closed); N-5 open |

---

## 3. Current phase and milestone

**Phase:** Stage 4 — Other Requirements and Implementation Plan, presented 2026-10-26.
**Milestone:** Stage 5 in progress. **M0–M11 done.** M11: Parts B/C/D/E complete; **Part A (browser) not done — N-5 open.**
**403 passed, 10 skipped**. `domain/` and `status_repository.py` both 100 % branch.

- **Demo scenarios (5):** all verified against the real API — eligible (phase 1, high coverage,
  `rec=true`), hazard_crossing (phase 2 only, never recommended), low_coverage (served, not
  recommended), refused (19891 m from a road), unknown_edge (stays `unknown`).
- **N-16 quantified then mitigated.** 3.5 % closure density → a 200-edge path avoids all closures only
  **0.089 %** of the time, so phase 1 almost never succeeded. Baseline **unchanged**; a separate labelled
  `demo_clear` profile (exactly 6 synthetic closures, `profile=demo_clear`) makes an eligible route
  demonstrable. Restoring baseline = omitting the parameter. Unknown profile → 422.
- **Graph build reproducible:** byte-identical rebuilds (`sha256 581aa7fe…` both runs), artifact
  preserved untouched, 24,943 edges / 1,085 km / 97.6 % largest weak component.
- **N-5 OPEN — could not be performed.** No browser binary, no flatpak browser, no playwright/puppeteer,
  and `browser_tool` refuses private targets. Not installed (unjustified dependency).
- **Fixed:** `status` module shadowed by a local variable in the route handler (broke the 422 path).
- **O-7 / O-8 / N-1 / N-2 / N-6 / N-13 / N-14 / N-15** all unchanged.

**M0 outcome in one line:** pinned install and build both succeed on Python 3.14.8 with no source builds;
`npm run build` produces 68.86 kB gzipped; **Python 3.13 is not installed on this host, so the documented
fallback could not be executed** — recorded, not glossed.

---

## 4. Tasks

| Task | Status |
|---|---|
| Read and internalise master brief | COMPLETE |
| Inspect repository state | COMPLETE — empty folder, **not a Git repository** |
| Verify rainfall data availability (Open-Meteo hourly precipitation + probability) | COMPLETE — available, CC BY 4.0, non-commercial free |
| Verify open questions that affect UI honesty (elevation resolution, tide source) | COMPLETE — elevation is Copernicus GLO-90 on Open-Meteo; no verified measured-river-level source found |
| Verify INAMHI integration path | COMPLETE — Guayaquil-specific bulletins exist, but **no public API**; manual entry only |
| **Live-verify** Open-Meteo rainfall (HTTP 200, 24 hourly values, mm + %) | COMPLETE — 2026-10-25 |
| **Live-verify** Open-Meteo elevation (6 Guayaquil points) | COMPLETE — 3–10 m; city has almost no relief |
| **Measure** SRTM 30 m terrain for Guayaquil (stdlib PNG/HGT decode) | COMPLETE — SRTM1 tiles readable; city spans **4–14 m**, only 1–4 m above the 90 m DSM |
| **Live-verify** GEOGloWS endpoints | COMPLETE — `getriverid` + `forecaststats`/`forecastrecords` work; `returnperiods` returns **HTTP 500** |
| **Verify** Python 3.14 wheel availability for the stack | COMPLETE — pydantic-core, asyncpg, numpy, shapely, osmnx, geopandas all ship cp314 or pure-python wheels |
| Flip Stage 1 spec to English-first UI with Spanish second | COMPLETE — mockup, chips, severity ramp, all sample copy |
| Verify river/streamflow source | COMPLETE — GEOGloWS ECMWF modelled streamflow is the only open option; it is model output, not a gauge reading |
| Search for HACK2IMPACT handbook | COMPLETE — **not found**. A plausible look-alike event was rejected, not adopted |
| Write data-source verification notes | COMPLETE — `docs/DATA-SOURCES.md` |
| Write Stage 1 public interface proposal | COMPLETE |
| Create initial `AGENT.md` and `PHASES.md` | COMPLETE |
| Obtain Stage 1 approval | COMPLETE — approved 2026-10-25 |
| Present Stage 2 admin interface | COMPLETE — approved 2026-10-25 |
| Present Stage 3 architecture | COMPLETE — delivered, revised per review |
| Address eight review points on Stage 3 | COMPLETE — `docs/STAGE-3-REVIEW-RESPONSE.md` |
| Cross-document reconciliation (3-doc package) | COMPLETE — 16 findings, 3 safety defects corrected (`docs/STAGE-3-RECONCILIATION.md`) |
| Resolve O-1…O-6 with the owner | **COMPLETE 2026-10-25** — recorded as D23–D28 |
| Record O-1…O-6 in project docs | **COMPLETE 2026-10-25** — PHASES, AGENT, decision summary, architecture §8.4 |
| **Stage 3 approval** | **COMPLETE 2026-10-26** — approved on the reconciled D23–D28 |
| Present Stage 4 requirements + implementation plan | **COMPLETE 2026-10-26** — `docs/STAGE-4-REQUIREMENTS-PLAN.md`, awaiting approval |
| **Stage 4 approval** | **COMPLETE 2026-10-26** — approved; R-17 = (a) recorded as D29 |
| Revise plan for the one-day constraint | **COMPLETE 2026-10-26** — `docs/STAGE-4-REQUIREMENTS-PLAN.md` §16 |
| **Stage 5 approval** | **COMPLETE 2026-10-26** — approved; M0 authorised |
| **M0 clean install** | **COMPLETE 2026-10-26 — PASSED** on Python 3.14.8; evidence: `docs/M0-EVIDENCE.md` |
| Block 1 — schema + seed | **COMPLETE 2026-10-26 — PASSED**, 30/30 RLS assertions; evidence: `docs/M1-EVIDENCE.md` |
| Block 2 — risk engine + tests | **COMPLETE 2026-10-26 — PASSED**, 41 tests, 100 % branch coverage on `domain/`; evidence: `docs/M2-EVIDENCE.md` |
| Block 3 — graph artifact + two-phase search | **COMPLETE 2026-10-26 — PASSED** |
| Block 4 — routing, coverage, classifications | **COMPLETE 2026-10-26 — PASSED**; 86 tests, `ROUTE-1`…`ROUTE-9` green; evidence: `docs/M3-EVIDENCE.md` |
| Block 5 — ingestion (Open-Meteo + sensor sim) | **COMPLETE 2026-10-26 — PASSED**; adapters + 68 tests; live smoke test ran; evidence: `docs/M4-M5-EVIDENCE.md` |
| Block 6 — public UI (dashboard, forecast, outlook) | **COMPLETE 2026-10-26 — PASSED** (read-only API + dashboard); evidence: `docs/M6-EVIDENCE.md` |
| Block 7 — provenance persistence + route read endpoint | **COMPLETE 2026-10-26 — PASSED**; persistence proven on real PostgreSQL 16.2; evidence: `docs/M7-EVIDENCE.md` |
| Block 8 — wire read path to PostgreSQL (closes N-6/N-7) | **COMPLETE 2026-10-26 — PARTIAL PASS**; read path proven on real PG 16.2 but maps **0** records to synthetic graph edges (N-8); ingestion writes disabled by default (N-2); evidence: `docs/M8-EVIDENCE.md` |
| Block 9 — unify road data source (closes N-8) | **COMPLETE 2026-10-26 — PASSED**; **real OSM extract** builds a 994-edge graph with stable, invertible edge identity; identity join proven on PG 16.2; evidence: `docs/M9-EVIDENCE.md` |
| Block 10 — operationalise OSM pipeline, widen extract, one-ways | **COMPLETE 2026-10-26 — PASSED (A–D)**; N-10/N-11/N-12 closed, N-13 partial; **browser check (Part E) NOT done — N-5 open**; evidence: `docs/M10-EVIDENCE.md` |
| Block 11 — demo status tuning (N-16), repo load step (N-14) | **PARTIAL — M11 done**; `demo_clear` fixture added (N-16 mitigated); N-14 still open; **N-5 still open (no browser)**; evidence: `docs/M11-EVIDENCE.md` |
| Block 12 — demo selector (M12 Part A), N-14 loader, visual checklist | **DONE — M12**; N-14 closed (idempotent, proven 3x on PG 16.2); **N-5 open**; evidence: `docs/M12-EVIDENCE.md` |
| Block 13 — N-5 manual checklist, or N-13 turn restrictions | NEXT — not started |

---

## 5. Completed features and test results

**None.** No application code exists. No tests have been run, no build has been attempted, and no
API integration has been verified against a live endpoint.

---

## 6. Decisions made

| # | Decision | Basis |
|---|---|---|
| D1 | No Git commits, ever | Brief §2. Absolute, includes amend/empty/scripted/milestone commits |
| D2 | No code before all four planning stages are approved | Brief §3, §7 |
| D3 | Maintain `AGENT.md` + `PHASES.md` as required project docs | Brief §4 |
| D4 | Surface provenance (verified / reported / estimated / stale / unknown) as a first-class UI primitive | Brief §5 — do not treat missing reports as evidence of safety |
| D5 | Five-tab mobile navigation covering eight public features in ≤2 taps | Stage 1 proposal §4 |
| D6 | No application code or mockup produced during Stage 1 | Brief §3 |
| D7 | Every external data claim carries an explicit verified/unverified marker in `docs/DATA-SOURCES.md`; nothing is called working before it is tested | Brief §5, §3 |
| D8 | **English is the primary UI language, Spanish secondary via toggle** | Owner decision, 2026-10-25 (Q1) |
| D9 | Event requirements will be taken **only** from the owner's master instructions; the handbook is unavailable and no substitute is accepted | Owner decision, 2026-10-25 (Q2) |
| D10 | **GEOGloWS modelled river discharge is included in the Outlook**, always labelled "Estimated · modelled discharge" with model name and run time; never described as a measured river level | Owner decision, 2026-10-25 (Q5) |
| D11 | **Public risk level auto-derives** from sensors + forecast, always with a visible reason line, plus an audited operator override | Owner decision, 2026-10-25 (AQ2) |
| D12 | Terrain is **static vulnerability context only** — never a live flood signal, never street-level depth, never a street-ranking input | Measurement + brief §5 |
| D13 | **Demo runs from deployed free-tier hosting**, not locally (owner choice) — so cold-start and pause mitigations are mandatory runbook steps | Owner decision, 2026-10-25 (TQ5) |
| D14 | **Route results are never cached**; status is read fresh per request. A cached route is a stale hazard map | Stage 3 §9.2, review point 4 |
| D15 | **Safety properties are the test contract** (44 named ids in Stage 3 §17.1); 100 % coverage without the property tests does not pass the gate | Review point 2 |
| D16 | **Closed roads are removed from the graph in phase 1**, not penalised. A finite penalty was probed and refuted (1 violation in 1201 graphs). Two-phase is the only design that holds structurally | `research/routing_invariant.py`, Stage 3 §9.3 |
| D17 | **Evidence levels E0–E4 govern wording**: nothing is called "passing" unless a committed test has run. Project ceiling is currently **E2 (probed)** | Review point 2, `docs/EVIDENCE-STATUS.md` |
| **D18** | **Severity and evidence coverage are separate outputs.** Missing inputs lower `confidence`, never `level`. The `coverage < 0.6 ⇒ cap at 2` rule is **withdrawn as unsafe** | Reconciliation C-1; 0.55 arithmetic |
| **D19** | **Precautionary floor may raise the level, never lower it** (heavy rain ≥2; 3+ verified reports ≥3; any closure ≥3) — ⚠ **proposed, needs approval O-1** | Reconciliation C-15 |
| **D20** | **Route coverage is a recommendation boundary, not a rejection gate.** Bands High≥80/Moderate 60–79/Low 1–59/None 0; refusal only for no-path or snap>60 m | Reconciliation C-2 |
| **D21** | **No single input may suppress the level**; a sensor cannot veto the precaution floor (`RISK-8b`, `RISK-8c`) | Reconciliation C-3 |
| **D22** | **English primary, Spanish secondary, both complete** — missing ES keys fail the build; safety-critical strings bilingual before render | Reconciliation C-4/C-5 |
| **D23** | **Precaution floor: reports + closures active, heavy-rain trigger DISABLED.** The floor stays (can raise, never lower) driven by verified reports and operator-confirmed closures only. **No heavy-rain trigger until a defensible threshold and source exist** — 40 mm/6h is a risk-scoring input, not an approved public warning threshold. Floor numbers are **provisional and unvalidated** | Owner decision 2026-10-25 (O-1: 1a=iii, 1b=b conditional) |
| **D24** | **Low/None-coverage routes: serve, never recommend.** Show a prominent uncertainty warning, the actual coverage %, and the unknown/stale status detail. Never described as verified-safe. Known closures stay excluded from ordinary eligible routes | Owner decision 2026-10-25 (O-2=a) |
| **D25** | **60 % retained provisionally** as the recommendation boundary, **not** a serve/withhold gate. Documented as an **unvalidated product decision, not a measured safety threshold** | Owner decision 2026-10-25 (O-3=a) |
| **D26** | **Hard publishing block stands** — headline *and* body required in EN and ES before publication. **No override introduced**; Stage 2 requirement unchanged. Emergency handling follows the approved workflow unless a separate requirement change is proposed and approved | Owner decision 2026-10-25 (O-4=a) |
| **D27** | **Sensor-coverage severity cap permanently removed.** Coverage affects confidence and the insufficient-evidence indicator only; never severity. "Unable to assess" preserved when no usable inputs. Replacement behaviour **specified but untested** until `RISK-3`/`RISK-4` actually run | Owner decision 2026-10-25 (O-5=a) |
| **D28** | **Prototype sensor thresholds retained** for SIM-01…SIM-06 as simulated demonstration inputs only. SIMULATED label visible wherever these readings appear. **Unvalidated; must never be represented as real municipal flood thresholds** | Owner decision 2026-10-25 (O-6=a) |
| **D29** | **Elevation is a disclosed, approximate tie-breaker in route ordering — nothing more.** Never overrides closures, verified hazards or coverage; must not independently determine the recommended route; UI must state it is approximate and does not establish street-level safety; **if `ROUTE-8`/`ROUTE-9` cannot pass, elevation is omitted from ranking and the limitation documented**. Enforced by sort order `(class, band, duration, ±elevation)` and by tests, not discipline. D12 remains in force | Owner decision 2026-10-26 (R-17=a) |
| **D30** | **≈One day of total remaining time.** Stage 5 executes the one-day schedule in `docs/STAGE-4-REQUIREMENTS-PLAN.md` §16, which supersedes the 13-milestone order. Non-negotiables excluded from every cut: risk engine + tests, two-phase routing, provenance labels, SIMULATED labels, bilingual safety strings | Owner constraint 2026-10-26 |

---

## 7. Outstanding decisions and blockers

**Blockers**

- **B1 — Stage 1 approval: RESOLVED 2026-10-25.** Stage 2 may now be presented. The same gate applies
  to all later stages — do not treat this approval as covering Stage 2.
- **B2 — HACK2IMPACT handbook not available.** Searched and not found. **Owner confirmed it is
  unavailable (2026-10-25); proceed without it.** Consequence: Stage 4 cites only the master
  instructions and must state plainly that event requirements are unverified. Do **not** substitute the
  IEEE HackTech El Niño 2026 material (`docs/DATA-SOURCES.md` §7).
- **B3 — INAMHI has no public API.** Real products exist (`Pronóstico Extendido Guayaquil-Durán`,
  `Boletín Guayaquil-Durán`, `Alerta Temprana`, `Boletín Hidrológico`) but are published as portal
  bulletins. Integration is **manual admin entry carrying the bulletin's issue time**, shown as such.
  No scraping without checking terms.
- **B4 — No measured river level. DECIDED 2026-10-25:** GEOGloWS *modelled* discharge is used, labelled
  "Estimated · modelled discharge" with model name and run time. Tide is astronomical prediction only.
  Neither may ever be described as "nivel medido / measured river level".
- **B5 — Elevation dataset conflict. RESOLVED 2026-10-25 by measurement.** SRTM 1-arcsecond (30 m)
  tiles are fetchable (AWS skadi `.hgt.gz` and terrarium PNGs, stdlib-decodable). Measured across six
  Guayaquil points: 30 m SRTM reads **4–14 m**, the 90 m DSM reads 3–10 m — a delta of only 1–4 m.
  **Both are DSM-ish and both span less than the city's own relief.** Decision: use SRTM 30 m (honours
  the brief, finer grid) but treat terrain as **static vulnerability context only** — never a live
  flood signal, never a street-level depth claim. See `docs/STAGE-3-ARCHITECTURE.md` §7.
- **B6 — No authoritative designated-shelter dataset.** Shelters must be admin-curated and labelled
  app-managed; OSM POIs must never be presented as "verified safe zones".
- **B7 — OSM Guayaquil road-graph routability: RESOLVED 2026-10-25.** Measured, not assumed: central
  bbox gives 6,202 ways, 22,499 nodes, 1,184.9 km, 96.9 % of nodes in one component, 32.8 % junctions,
  and a 1.34× detour factor on an 11.9 km test route. Route finding is viable. **Residual risk:**
  peripheral/low-income districts were not sampled and are commonly thinner in OSM — measure per demo
  sector before promising routing there. One-way and turn restrictions were not evaluated.
- **B8 — OSM tile usage policy** disallows heavy/production use of `tile.openstreetmap.org`. A tile
  strategy (self-host or permitted provider) is required and licensing checked before demo.
- **B9 — GEOGloWS `returnperiods` returns HTTP 500** (`No variable named 'logpearson3'` — a server-side
  bug, not our request). Consequence: "1-in-N-year" framing **cannot** be used. The Outlook shows
  absolute modelled discharge plus ensemble spread instead. Never invent a return period.
- **B10 — Python 3.14 is very new.** Wheels exist for the whole stack (verified), but this is an
  unusual target and library bugs are likelier than on 3.12/3.13. Stage 3 §2 records the mitigation
  and the fallback.
- **B11 — Closed-road routing design was unsafe and is now fixed.** The original "large finite penalty"
  was probed and **refuted** (`research/routing_invariant.py`: 1 violation / 1201 graphs; adversarial case
  serves a closed route at cost 12.50 over an open route at 246.00). Replaced by a two-phase edge filter
  which held 1201/1201 by construction. `ROUTE-1b` will lock this in as a regression test.
- **B12 — Three safety defects found in the Stage 3 reconciliation are fixed in documentation but
  unverified.** (1) the coverage cap that downgraded every sensor outage to Caution — removed (D18/D27);
  (2) the contradictory route-coverage policy — replaced with class×band (D20/D24/D25);
  (3) the "sensor decides" conflict rule — replaced with no-veto + floor (D21). The replacement
  behaviour has **never executed** and is unproven until Stage 5.
- **B13 — No defensible "heavy rain" threshold exists (OPEN).** Stage 3 §8.4's floor originally triggered
  on forecast rain reaching a heavy-rain threshold, but no value is defined anywhere, and Stage 1 §6
  requires such a threshold to be *named with its basis stated*. Per **D23** the heavy-rain floor trigger
  is **disabled**. The public forecast UI must therefore show absolute mm and probability **without** a
  "heavy rain" label until a sourced threshold (e.g. an INAMHI advisory tier) is approved. Does **not**
  block Stage 3; blocks a public warning feature.

**Open questions carried from Stage 1** — see `docs/STAGE-1-PUBLIC-INTERFACE.md` §17.
Resolved: Q1 (English primary, Spanish secondary), Q2 (no handbook), Q5 (GEOGloWS modelled discharge
accepted, clearly labelled), Q4 (INAMHI = manual entry).
Still open: Q3 demo area and sectors, Q7 photo retention, Q8 mockup.

**Stage 3 decisions — RESOLVED by the owner 2026-10-25** (recorded as D23–D28; full text in
`docs/STAGE-3-DECISION-SUMMARY.md` §4):

- **O-1 → D23** floor kept for reports + closures; **heavy-rain trigger disabled** pending a defensible
  threshold and source; numbers provisional
- **O-2 → D24** serve low/zero-coverage routes, never recommend, prominent uncertainty warning
- **O-3 → D25** 60 % retained provisionally, explicitly unvalidated
- **O-4 → D26** hard bilingual publishing block stands, no override
- **O-5 → D27** severity cap permanently removed; replacement specified but untested
- **O-6 → D28** prototype sensor thresholds retained, labelled simulated and unvalidated

**Still open from earlier stages:** `TQ1`–`TQ3`, `TQ6`, `AQ1`, `AQ3`, `AQ5`. These are **not** Stage 3
blockers — they are Stage 4/5 inputs and are carried forward.

---

## 8. Known issues

- Repository is not initialised. Nothing is under version control; reverting mistakes is currently
  impossible. Not remedied without explicit permission, and initialising never implies committing.
- Oct 2026 Guayaquil flooding was severe and ongoing in the news cycle; any seeded demo scenario must
  avoid implying it reflects current real conditions.
- INAMHI's portal rendered a "Pronóstico del día" widget dated 28 ago 2026 during this review. Either
  the page is cached or the widget is stale — never trust that portal content is current; always show
  the bulletin's own issue date.
- Open-Meteo is free for **non-commercial** use only; commercial use needs a paid plan. Whether the
  demo qualifies has not been determined.

---

## 9. Deferred features

Deferred until Stage 4 classifies the work (MVP / secondary / future). Candidates noted in the brief:
native app, push notifications, real sensor hardware, official emergency-service integration,
measured river-level ingestion.

---

## 10. Exact next actions

1. **Await explicit Stage 5 implementation approval.** Do **not** start M0 before it.
2. **On Stage 5 approval** → execute the one-day schedule in `docs/STAGE-4-REQUIREMENTS-PLAN.md` §16,
   block 0 → 10, against the pre-agreed checkpoints in §16.6.
3. **Non-negotiables that must survive every cut** (D30): risk engine + tests, two-phase routing guarantee,
   provenance labels, SIMULATED labels, bilingual safety strings.
4. **M0 is a hard gate.** If pins fail on Python 3.14 → recreate the venv on 3.13, pins unchanged, and record
   it. Never substitute a library to make an install succeed.
5. Update `PHASES.md` and `AGENT.md` at every block boundary, not at the end of the day.

**Time available: ≈ one day (D30).** The 13-milestone order in Stage 4 §13 is superseded by §16.
