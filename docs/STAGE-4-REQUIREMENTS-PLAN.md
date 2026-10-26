# Guaradar — Stage 4: Other Requirements and Implementation Plan

**Status:** **APPROVED 2026-10-26** — approved with **R-17 = option (a)** and a **one-day time constraint**.
**Approved predecessors:** Stage 1 (2026-10-25), Stage 2 (2026-10-25), Stage 3 (2026-10-26, on D23–D28)
**Scope of this document:** event requirements, work classification, milestones, acceptance criteria,
implementation order, demo plan. **No code.**
**Out of scope (by instruction):** implementation, dependency installation, schema application, services,
deployment.
**Date:** 2026-10-26 · **§16 added: one-day schedule**

> **Execution boundary in force:** this approval covers **Stage 4 planning only**. Stage 5 / milestone M0 has
> **not** started and must not start until the owner gives explicit Stage 5 approval.

---

## 0. The single most important qualification

**The official HACK2IMPACT 2026 handbook does not exist as far as this project can determine.** It was
searched for on 2026-10-25 and not found; you confirmed it is unavailable (recorded as **B2**).

Therefore:

- **Every requirement in §2 is drawn from your master instructions only.** Nothing is attributed to the
  event, a rubric, a judging form, or a track description.
- **No claim of event compliance is made anywhere in this project.** Where this document says "required",
  it means "required by your master instructions", not "required to win".
- A look-alike event (*HackTech El Niño 2026*, IEEE Region 9, Track 1 "Telecommunications & Early Warning
  Systems in Crisis") was found during research and **rejected** as a substitute. It closed in September
  2026 and is not this event. Using its rules would have manufactured false compliance.
- If you later supply the handbook, §2 gets re-derived against it and any gap is reported as a gap.

This qualification is not boilerplate. It is the reason §3's traceability matrix has a "source" column
that says *master instructions* on every row.

---

## 1. What Stage 4 must deliver, and how this document maps to it

Your brief's Stage 4 clause requires twelve topics and a three-way work split. Mapping:

| Brief requirement | Section here |
|---|---|
| Official hackathon requirements | §2, §3 |
| Rainfall forecast integration | §5.2 |
| Five or more simulated sensor nodes | §5.3 |
| Elevation-aware routing that avoids flooded road segments | §4 (needs your decision) |
| Alert-dispatch prototype | §5.4 |
| Public/admin data consistency | §5.5 |
| Data quality and uncertainty | §6 |
| Offline and low-network behaviour | §7 |
| Security and input validation | §8 |
| Accessibility | §9 |
| Testing and deployment | §10 |
| Demo scenario and presentation preparation | §11 |
| Split: MVP / secondary / future | §12 |
| Stop and request approval | §15 |

---

## 2. Requirements as stated by the master instructions

Extracted verbatim in intent, deduplicated, and numbered so §3 can trace them. **Source: master
instructions only.**

### Mandatory (stated as must / mandatory / required)

| ID | Requirement |
|---|---|
| **R-01** | Rainfall forecasting is mandatory |
| **R-02** | Open-Meteo is the planned initial forecast integration |
| **R-03** | Cross-check with INAMHI when accessible and practical |
| **R-04** | Clearly distinguish forecasts from actual observations |
| **R-05** | Clearly label simulated sensor data |
| **R-06** | Never invent live water levels, official alerts, verified road closures, or shelter availability |
| **R-07** | Do not treat a missing flood report as evidence that a road is safe |
| **R-08** | Identify road conditions as verified, reported, estimated, stale, or unknown |
| **R-09** | Never claim exact time-to-flood predictions without sufficient measurements and a suitable method |
| **R-10** | Explain uncertainty in risk estimates |
| **R-11** | Do not recommend a route as safe when reliable information is insufficient |
| **R-12** | Protect administrative operations with authentication and authorization |
| **R-13** | Validate citizen submissions and protect sensitive information |
| **R-14** | Secrets only via environment variables or secret management |
| **R-15** | Respect API terms, rate limits, and dataset licences |
| **R-16** | Five or more simulated water-level sensor nodes |
| **R-17** | Elevation-aware routing that avoids flooded road segments |
| **R-18** | Alert-dispatch prototype |
| **R-19** | Public/admin data consistency — reuse shared data, no conflicting copies |
| **R-20** | Public app must be minimal, fast-loading, mobile-friendly, usable on unreliable networks |
| **R-21** | Never communicate severity through colour alone |
| **R-22** | Display data source and freshness |
| **R-23** | Keep the public interface simpler than the admin interface |
| **R-24** | Lazy-load maps and heavy components; small production bundles |
| **R-25** | Maintain `AGENT.md` and `PHASES.md` as persistent, accurate documentation |

### Design-and-performance constraints

| ID | Requirement |
|---|---|
| **R-26** | Minimal light theme, teal and navy accents |
| **R-27** | Clean typography, consistent spacing |
| **R-28** | Responsive, mobile-first |
| **R-29** | Avoid unnecessary animation libraries and large UI dependencies |
| **R-30** | Keep essential warnings prominent and accessible |
| **R-31** | Do not sacrifice functionality or safety for visual impressiveness |

### Process constraints (already in force, restated so Stage 5 cannot drift)

| ID | Requirement |
|---|---|
| **R-32** | Never run `git commit` in any form. Absolute. |
| **R-33** | Report actual test results; never claim untested things work |
| **R-34** | Do not push or deploy without explicit authorisation |

---

## 3. Traceability matrix — requirement to acceptance criterion

Every mandatory requirement, with how it will be demonstrated and **what evidence level that demonstration
would reach**. Levels per `docs/EVIDENCE-STATUS.md`: E2 probed · E3 tested (committed test with output) ·
E4 demonstrated end-to-end.

| ID | Design response | Acceptance criterion | Evidence when met |
|---|---|---|---|
| R-01 | Open-Meteo hourly `precipitation` + `precipitation_probability` via server proxy, cached with `model_run_at` | Forecast screen renders 24 hourly bars and an accessible list; both variables present; run time displayed | E4 |
| R-02 | `backend/app/ingest/openmeteo.py` | Integration test asserts parsed hourly series and units `mm`/`%` | E3 |
| R-03 | Manual INAMHI bulletin entry by an operator | Bulletin renders with its own issue date, labelled *manual entry*, visually distinct from the machine chip | E4 |
| R-04 | Separate `Estimated` vs `Verified` chips; "Forecast, not observation" text | Contract test asserts every forecast payload carries `chip=estimated`; weather screen contains the observation disclaimer | E3 + E4 |
| R-05 | `simulated` boolean, DB default true; SIMULATED badge on marker, row, drawer, export | `SIM-1` DB-constraint test; visual check that badge appears on public map marker | E3 + E4 |
| R-06 | Only stored rows are rendered; no generative content | Manual review + `RISK-6` (no fabricated level); seed data marked `simulated`/`seeded` | E3 + review |
| R-07 | "No data" is a first-class chip; empty states carry the caution sentence | Snapshot test of empty-state copy; `ROUTE-2c` ensures 0 %-coverage is not recommended | E3 |
| R-08 | Five-state provenance model, computed server-side (`PROV-1`) | Contract test: every public read carries a provenance envelope | E3 |
| R-09 | Time-to-threshold only with ≥3 readings in 60 min + consistent trend + threshold in range; range output ("≈45 min, ±20") | `RISK-7`-adjacent unit test on the sufficiency gate; UI shows "No estimate" otherwise | E3 |
| R-10 | Confidence line (high/medium/low) + reason line + coverage figure + conflict list | `RISK-3`/`RISK-4` assert confidence and `insufficient_evidence` are independent of level | E3 |
| R-11 | Banned vocabulary lint (`ROUTE-4`); coverage shown; Low/None never recommended (`ROUTE-2c`) | Lint returns zero banned words; unit test asserts non-recommendation | E3 |
| R-12 | Supabase Auth + roles + RLS; MFA for Publisher/Admin | Integration test: unauthenticated request to admin route is rejected; Viewer cannot mutate | E3 |
| R-13 | Server-side validation, size/type limits, EXIF strip, rate limit, anonymous reporter code | Tests for rejected oversized/wrong-type payloads and rate-limit 429 | E3 |
| R-14 | `.env` only; service-role key never in frontend | `COST-1`: build output grepped for key pattern ⇒ zero | E3 |
| R-15 | Attribution rendered; self-throttled ingestion; no scraping; ODbL notice | Manual review of attributions + code review of polling intervals | E3 + review |
| R-16 | Six nodes `SIM-01…SIM-06` across four sectors | Seed script creates 6; admin list shows 6 with SIMULATED badge | E3 + E4 |
| R-17 | **See §4 — requires your decision.** Two-phase routing guarantees closure avoidance; elevation's role is undecided | To be set by §4 decision | — |
| R-18 | In-app publication only, with an explicit "no external dispatch" statement at the moment of publishing | Test asserting the publication confirmation contains the non-dispatch sentence; manual review | E3 + E4 |
| R-19 | `road_status` keyed 1:1 to segment; derived values never cached; `SYNC-1` asserts propagation | Integration test: admin PATCH changes public read **and** route coverage in one cycle | E3 |
| R-20 | Text-first render, no web font, lazy map, ≤60 KB CSS/first paint target | Measure with Lighthouse/build output at Stage 5 — **target, not yet measured** | E3 (measured) |
| R-21 | Numeral + word + shape + colour per level | Unit test that severity renders all four; manual axe/manual check | E3 |
| R-22 | Absolute timestamp + relative age + source name on every data block | `PROV-1` contract test; UI review | E3 |
| R-23 | Admin grid ≥1280 px; public single column | Visual review at both viewports | E4 |
| R-24 | No icon/chart/animation library; Leaflet lazy-loaded | Bundle report shows no such deps; map chunk separate | E3 |
| R-25 | Update both files after each milestone | Files current at each gate | review |
| R-26–R-31 | Token file from Stage 1 §14; system font stack; `prefers-reduced-motion` honoured; mobile-first breakpoints (360 / 768 / 1024 px); no icon, chart or animation library | Style review; reduced-motion test; visual check at all three breakpoints; `npm ls` shows no such dependencies | E3 |
| R-32 | Not executed at any point | Absence of commits verified by inspection | review |
| R-33 | Every milestone reports real output or states "not run" | Milestone records in `PHASES.md` quote actual command output | review |
| R-34 | No push or deployment without explicit authorisation | Deployment only occurs at M12 **after** explicit authorisation is recorded; until then the project has no remote and no deploy target configured | review |

**Nothing in this table is currently met.** Every "evidence when met" cell is a promise about what Stage 5
must produce. The project's evidence ceiling today is **E2**, and this table does not change that.

---

## 4. Requirement R-17 and D12 — **RESOLVED 2026-10-26 → option (a)**

The brief requires **"Elevation-aware routing that avoids flooded road segments."**

Stage 3 measured Guayaquil's terrain and approved **D12**: elevation is **static context only** — it may not
rank streets, predict depth, or act as a live signal, because a 90 m DSM errs by more than the city's entire
~10 m relief, and SRTM 30 m differs from it by 1–4 m on a 10 m range.

Taken literally, "elevation-aware routing" could mean *prefer lower/higher ground when choosing a route* —
which is exactly what D12 forbids, because elevation cannot distinguish a street that floods from one that
does not.

**Three ways to satisfy R-17 without breaking D12.** This is a product and safety call, not a technical one:

| Option | What it means | Trade-off |
|---|---|---|
| **(a) Elevation as a disclosed tie-breaker** ← **CHOSEN 2026-10-26** | Routing still orders by (hazard class, coverage, duration). Elevation enters **only** to break exact ties inside the same class *and* same coverage band. The UI states that the tie-break used approximate terrain. | Genuinely "elevation-aware"; cannot move a route across a class or coverage boundary, so no safety claim rests on terrain. |
| **(b) Elevation as route metadata, not ordering** | Each route shows mean elevation and low-lying share as **displayed context**; ordering ignores elevation entirely. | Most defensible against D12. Arguably does not satisfy "elevation-*aware* routing" at all. |
| **(c) Elevation as a static vulnerability prior** | Segments below a sector-relative elevation percentile flagged as more likely to pond, raising their `unknown` penalty. | Uses terrain as a street-level hazard inference — **what D12 measured as unsound.** Rejected. |

### 4.1 The owner's decision — recorded as **D29**

Elevation may be used **only as a disclosed, approximate tie-breaker**, subject to five binding limits:

| # | Limit |
|---|---|
| 1 | Elevation is **only** a disclosed, approximate tie-breaker |
| 2 | It must **never override** known road closures, verified hazards, or road-status coverage |
| 3 | Approximate elevation **must not independently determine** which route is recommended |
| 4 | The UI must clearly state elevation is **approximate** and **does not establish street-level safety** |
| 5 | If the tie-breaker would violate D12 or create misleading safety claims, **omit elevation from ranking entirely and document the limitation** |

### 4.2 How D29 is enforced — by construction, not by discipline

- Ordering key: `(hazard_class, coverage_band, duration, ±elevation)`. Elevation is the **last** term and can
  only separate routes already equal on the first three.
- Because class and band are compared **before** duration and elevation, limit 2 and limit 3 hold structurally:
  elevation cannot lift a route out of a worse class or band.
- **New tests:** `ROUTE-8` (elevation never crosses a class or coverage boundary) and `ROUTE-9` (elevation is the
  last sort term; removing it changes ordering only among otherwise-equal routes).
- **Limit 5 is a real escape hatch:** if `ROUTE-8` cannot be made to pass, elevation is removed from ranking and
  the limitation is documented. No partial compliance.
- **UI copy** on any route whose position the tie-break affected: *"Tie broken using approximate terrain
  (SRTM 30 m, ±4 m). This does not establish that the route is safe."*
- D12 remains in force: terrain still may not rank streets, predict depth, or act as a live signal.

**Status of R-17: satisfied under option (a), conditional on `ROUTE-8`/`ROUTE-9` passing.** Until those tests
run, R-17 is *specified*, not *met*.

---

## 5. Required integration detail

### 5.1 What is already verified (E2) — do not re-derive

| Fact | Value |
|---|---|
| Open-Meteo forecast | HTTP 200, 24 hourly `precipitation` (mm) + `precipitation_probability` (%) |
| SRTM 30 m | fetchable, decodable with stdlib; Guayaquil 4–14 m |
| OSM graph | 6,202 ways, 22,499 nodes, 1,184.9 km, 96.9 % one component, 1.34× detour |
| GEOGloWS | `getriverid` → `670068009`; `forecaststats` 120 ensemble + 240 hourly rows, 5,050–8,844 m³/s |
| GEOGloWS `returnperiods` | **HTTP 500** — no return-period claims, ever |
| Routing penalty design | refuted (1 violation/1,201); two-phase adopted |

### 5.2 Rainfall forecast integration

- Server-side fetch every 15 min per sector; cache with `fetched_at` **and** upstream `model_run_at`.
- Both timestamps displayed — a fresh fetch of an old model run is still old information.
- Heavy-rain label **omitted** until a sourced threshold exists (**B13**, **D23**). Bars and probability
  still render; only the label is withheld.
- Degradation: timeout/429/5xx ⇒ last cached payload, `Stale` chip, absolute age shown. Never a blank chart.

### 5.3 Five or more simulated sensor nodes

Six nodes, four sectors, per approved Stage 2 §6: `SIM-01` Sauces 6, `SIM-02` Samanes, `SIM-03` Cerro Santa
Ana, `SIM-04` Cristo del Consuelo, `SIM-05` Cisne II, `SIM-06` Martha de Roldós.

- Seeded, deterministic, profile-driven (`dry` / `steady` / `heavy` / `surge`), reading the real forecast so
  simulated water rises when real rain is forecast.
- Thresholds are prototype values (**D28**), labelled SIMULATED everywhere including exports.
- Health derived from reading cadence; a gap is drawn as a gap, never interpolated.

### 5.4 Alert-dispatch prototype — what it is, and what it must never claim

Your brief requires an "alert-dispatch prototype". Given **R-06** (never invent official alerts) and the
standing prohibition on claiming external dispatch, this is implemented as:

1. **Compose → approve → publish** lifecycle with a Publisher role (approved Stage 2 §8).
2. Publication makes the alert visible **inside Guaradar only**.
3. At the moment of publishing, the UI states in words: *"No message has been sent to any external emergency
   service, mailing list, or SMS gateway."*
4. A share link is offered so a human can distribute it — but the app does not claim to have done so.

**This is the honest maximum.** If judging expects a real SMS/email dispatch, that requires credentials, cost
and authorisation this project does not have, and inventing it would break R-06. Flagged in §14.

### 5.5 Public/admin data consistency

- One record, one source of truth: `road_status` keyed by `road_segment_id`; no parallel public table.
- Provenance chip computed server-side, in the response envelope.
- No caching of derived aggregates; status changes propagate in the same request cycle.
- `SYNC-1`…`SYNC-3` as the executable contract.

---

## 6. Data quality and uncertainty

The project's honesty rules, expressed as buildable requirements:

| Rule | Implementation | Test |
|---|---|---|
| Missing ≠ safe | `No data` chip; empty states carry the caution sentence | snapshot |
| Missing ≠ lower risk | coverage affects confidence only (**D27**) | `RISK-3`, `RISK-4` |
| Stale is visible | freshness budget per source; chip flips automatically | `PROV-1` |
| Disagreement is shown | conflict list; INAMHI vs Open-Meteo ⇒ `Discrepant`, never averaged | `RISK-8` |
| Simulated is labelled | DB default + marker badge + export header | `SIM-1`, `SIM-3` |
| Modelled is labelled | GEOGloWS line reads "modelled discharge" + run time | `GEO-4` |
| Heuristic is labelled | risk card states it is an estimate on forecast + sensors + reports | review |
| No fabricated precision | time-to-threshold as a range, only when sufficient | unit |
| Provenance is per-value | chip on every data-bearing element | `PROV-2` |

**The one thing no test can establish** (from `EVIDENCE-STATUS.md`): that the risk score predicts real
flooding. It is an unvalidated heuristic. This is stated in the product, not only in the docs.

---

## 7. Offline and low-network behaviour

| Concern | Commitment | Verified how |
|---|---|---|
| First paint | text + numbers before any chart; no web font | Lighthouse, bundle size |
| Map | never in first paint; loaded on tap; timeout fallback to text list | throttled manual test |
| Cached essentials | dashboard, 24 h forecast, shelters, road summary, with original timestamps | offline mode test |
| Stale display | dated banner + `Stale` chips, real age shown | offline mode test |
| Offline | banner; reporting queues locally with capture time preserved | DevTools offline |
| Slow network | skeleton + 10 s timeout + cached fallback; never an infinite spinner | throttled test |
| Report queue | IndexedDB, flushed on reconnect, `capture_at` preserved | manual test |

---

## 8. Security and input validation

| Area | Requirement |
|---|---|
| Admin auth | Supabase Auth; JWT verified on every admin request; roles in DB, not only in the token |
| MFA | TOTP required for Publisher and Admin |
| RLS | public read limited to published, non-expired alerts and non-sensitive tables; `incidents` photos hidden while `pending` |
| Audit log | insert-only for all roles; no UPDATE/DELETE grants |
| Service-role key | server only; `COST-1` build-time grep |
| Citizen submissions | server-side validation: type allow-list, ≤5 MB pre-compression target ≤300 KB, ≤280 chars, enum depth bands, rate limit per IP+device, duplicate suppression |
| EXIF | stripped on upload |
| PII | none collected; opaque `reporter_code` |
| Secrets | `.env` only; `.env*` gitignored before any value exists |
| Headers | HSTS, `X-Content-Type-Options`, restrictive CSP once tile source is fixed |

**Explicit non-claims:** no penetration test, no load test, no third-party security review. Single-tenant
demo. Not hardened for hostile internet exposure.

---

## 9. Accessibility

- WCAG 2.2 AA as the target for the public interface; AA-minus-dense-tables for admin (32 px targets
  permitted only there, recorded as a trade-off in Stage 2 §15).
- Severity: numeral + word + shape + colour — any one sufficient (R-21).
- Keyboard traversal of both interfaces; visible focus; semantic headings and real `<table>` semantics.
- Charts always paired with the canonical accessible list.
- `prefers-reduced-motion` fully honoured.
- Live region announces alert ribbon changes.
- Contrast ≥4.5:1 for text.
- **Verification plan:** manual keyboard pass, automated axe run, screen-reader pass over the alert ribbon
  and one route result. **Not yet performed** — scheduled as milestone M7.

---

## 10. Testing and deployment

### 10.1 Test strategy (from approved Stage 3 §17)

- 44 named safety properties; **none has run**.
- `domain/` at 100 % branch coverage **and** every `RISK-*` property present — coverage without the property
  does not pass.
- Property-based tests for monotonicity (`RISK-5`) and determinism (`RISK-10`).
- Static-analysis gates: `TERR-1`, `PROV-2`, `COST-1`, banned vocabulary, i18n key parity.
- Integration: `SYNC-*`, `ROUTE-3`, RLS denials, report validation.

**Recommendation (TQ4): tests-first for `domain/`, before any UI.** That module is pure, has no I/O, and is
where silent wrongness costs lives.

### 10.2 Deployment

- Frontend: static host. Backend: free-tier web service. DB: Supabase free tier.
- **Known constraints, not guarantees:** Render free spins down after 15 min idle (~1 min cold start);
  Supabase pauses after 1 week idle; free Render Postgres expires 30 days after creation.
- Mandatory runbook before any demo: warm-up request, Supabase re-wake, `/api/health` check.
- No SLA is claimed. **The $0 cost is a description of current published terms, not a guarantee.**

---

## 11. Demo scenario and presentation preparation

**Setting:** a re-run of the 19 Oct 2026 pattern — heavy continuous rain overnight, drainage overwhelmed,
northern sectors flooding first.

| Beat | What is shown | Why it matters |
|---|---|---|
| 1. Calm before | Public dashboard, Level 1, no alert ribbon (nothing invented) | Shows the app does not manufacture alarm |
| 2. Forecast arrives | Open-Meteo predicts a heavy window; forecast screen with model run time | R-01, R-04 visible |
| 3. Sensors rise | SIM-01/03 rising, thresholds shown, SIMULATED badges visible | R-05, R-16 |
| 4. Sensor fails | SIM-05 goes offline; confidence drops to **low**, level does **not** drop | The D18/D27 correction, live |
| 5. Citizen reports | 6 reports cluster; admin verifies 3 as an aggregate | R-13, Stage 2 §9 |
| 6. Road closed | Operator closes Vía a Daule with reason + review timer | R-08, Stage 2 §10 |
| 7. Route re-plan | Route finder avoids the closure; coverage % shown; a low-coverage alternative is served but **not recommended** | D24/D25 |
| 8. Hazard crossing | Remove all alternatives ⇒ "no route avoids all closures" | Two-phase phase 2, labelled |
| 9. Alert published | Level 3 alert, bilingual, with the non-dispatch statement | R-18 honesty |
| 10. Offline | Throttle to offline; app shows dated cache, reporting queues | R-20 |
| 11. Honesty close | Point at the confidence line, the SIMULATED badges, the "modelled" river label | The differentiator |

**Deliberate demo choices:** no fake live sensor data in screenshots; MIXED mode banner visible throughout;
seeded data labelled; a "reset scenario" action so a rehearsal is reproducible.

**Preparation needed:** a rehearsal on throttled network; screenshots captured with timestamps; a one-page
runbook including warm-up steps; a fallback path if the venue network fails (recorded walkthrough).

---

## 12. Work classification

### 12.1 Required MVP — the minimum that satisfies R-01…R-25 without dishonesty

| # | Item | Why it is MVP |
|---|---|---|
| 1 | Data model + RLS + seed (sectors, 6 sensors, roads, shelters) | Everything else depends on it |
| 2 | Pure risk engine + tests (`RISK-*`) | The safety core |
| 3 | Open-Meteo ingestion + cache + provenance envelope | R-01, R-02, R-04 |
| 4 | Sensor simulation (6 nodes) + retention | R-16, R-05 |
| 5 | Public dashboard + forecast + outlook | Stage 1 features 1, 2, 4 |
| 6 | Map with road/sensor/shelter/report layers | Stage 1 feature 3 |
| 7 | Two-phase routing + coverage + classifications | R-17, D16, D24 |
| 8 | Citizen reporting + validation + offline queue | Stage 1 feature 7 |
| 9 | Admin: overview, roads, incidents, alerts, shelters | Stage 2 required items |
| 10 | Auth + roles + audit log | R-12 |
| 11 | i18n EN/ES complete | D22, D26 |
| 12 | Degradation handling + timestamps | R-20, R-22 |
| 13 | Safety-property test suite executed | R-33 |

### 12.2 Secondary — valuable, only after MVP is green

| # | Item | Note |
|---|---|---|
| 1 | GEOGloWS river discharge on the outlook | Adopted (D10) but not required for the core loop |
| 2 | INAMHI manual bulletin entry | Cross-check (R-03) — scoped carefully |
| 3 | Sensor detail drawer with trend + time-to-threshold | Needs sufficient readings to matter |
| 4 | Admin prioritisation queue (severity × exposure × recency) | Stage 2 §4 |
| 5 | Accessibility verification pass | Should not be secondary — see note |
| 6 | Audit-log viewer | Traceability |
| 7 | Share/deep-link for routes and alerts | Real distribution channel |

> **Note on accessibility:** it is listed as secondary only because MVP must ship functioning first. It is
> **not** optional for the public interface — R-21 and R-30 are mandatory. If time is short, cut feature depth,
> not accessibility.

### 12.3 Future enhancements — explicitly out of scope

Real sensor hardware · measured river-level gauge integration · official INAMHI feed (no public API) · SMS/push
dispatch · native apps · multi-city support · hydrological modelling · flood-depth prediction · turn-by-turn
navigation · crowd photo moderation tooling · offline map tiles for the whole city · municipal shelter API.

---

## 13. Milestones, dependencies, acceptance criteria

Order chosen so that **the safety core is proven before it is visible**, and so no milestone depends on
network access it cannot control.

| M | Milestone | Depends on | Acceptance criteria | Risk |
|---|---|---|---|---|
| **M0** | Environment + clean install | — | venv via `ensurepip`; pins installed; import smoke test; `uvicorn --version`; `npm ci`; `npm run build`; resolved freeze + lockfile captured. **If it fails → recreate on Python 3.13, pins unchanged** | Python 3.14 newness (B10) |
| **M1** | Schema + RLS + seed | M0 | Migrations apply; RLS denies anonymous admin write; 6 sensors, ≥4 sectors, shelter seed present; `simulated` defaults true (`SIM-1`) | Supabase free-tier limits |
| **M2** | Risk engine + tests | M1 | `RISK-1`…`RISK-10`, `RISK-4c`, `RISK-4d`, `RISK-8b`, `RISK-8c` all pass; 100 % branch on `domain/`; determinism property passes | None — pure logic |
| **M3** | Road graph + terrain sampling | M1 | Graph artifact built with `timestamp_osm_base`; elevation sampled per segment; `TERR-1` static check passes | OSM coverage outside centre |
| **M4** | Ingestion: Open-Meteo + sensors | M1, M2 | Forecast cached with both timestamps; 6 simulated readings persist; health derived; degradation path exercised with a forced failure | Upstream availability |
| **M5** | Public API + provenance envelope | M2, M3, M4 | All public endpoints return the envelope (`PROV-1`); error contract honoured; cached-fallback verified | — |
| **M6** | Public UI: dashboard, forecast, outlook | M5 | 360 px viewport: report action reachable without scrolling; timestamps + sources visible; empty state shows the caution sentence; text renders before any chart | — |
| **M7** | Map + shelters | M6 | Layers toggle; SIMULATED on marker; unknown hatched distinctly; tile failure degrades to text list; accessibility pass on map alternatives | Tile licensing (TQ1) |
| **M8** | Routing end-to-end | M3, M5, M7 | `ROUTE-1`…`ROUTE-7` pass; phase-1 never crosses a closure; hazard-crossing labelled and last; coverage % shown; low coverage never recommended; no route caching | — |
| **M9** | Reporting + offline | M6 | Validation rejects bad payloads; EXIF stripped; queue survives offline and preserves capture time; rate limit returns 429 | Photo storage budget |
| **M10** | Admin console | M1, M2, M4, M8 | All twelve required items reachable; operator cannot publish; audit log append-only (UPDATE/DELETE raise); reason required to close/reopen; `SYNC-1` propagation test passes (**requires M8** — it asserts a road change moves public counts *and* route coverage) | Desktop-only editing by design |
| **M11** | i18n + accessibility | M6–M10 | `I18N-1`…`I18N-4` pass; zero missing keys; safety strings bilingual; keyboard traversal complete; axe clean | — |
| **M12** | Hardening, deploy, demo prep | M0, M11 | `COST-1` clean; health endpoint green; runbook rehearsed; demo scenario runs end-to-end twice; timing budget met | Free-tier cold start; network |

**Each milestone closes with:** tests run (real output quoted), `PHASES.md` + `AGENT.md` updated, and a
statement of what remains unverified.

### 13.1 Why this order, and what can be cut

The sequence deliberately proves the safety core (M2) before anything is visible, so a silent wrongness in
the risk engine is caught by unit tests rather than by a demo.

**If time is short, cut in this order** — each step preserves an honest, working product:

1. Drop M11's axe/keyboard pass to a manual checklist (keep the four severity encodings).
2. Defer §12.2 secondary items entirely (river, INAMHI, prioritisation queue, audit viewer).
3. Merge M6 and M7 (dashboard + map in one pass) at the cost of a larger, less testable step.
4. Reduce sectors from 5 to 3 — but never below the four sectors needed to place six sensors sensibly.

**Never cut:** M2 (risk engine + its tests), the two-phase routing guarantee (M8), provenance, the
SIMULATED labelling, or the bilingual safety strings. These are the properties the whole project exists to
demonstrate; a demo without them is a different, weaker product.

**M0 is a hard gate.** If the pinned dependency set will not install on Python 3.14, fall back to 3.13 with
pins unchanged and record it — do not substitute libraries to make the install succeed.

---

## 14. What is still unresolved, and whether it blocks

### 14.1 Blocks Stage 5 work

| # | Item | Why it blocks |
|---|---|---|
| **R-17** | §4 — elevation's role in routing | Cannot build routing without knowing whether terrain participates in ordering |
| **TQ3 / Q3** | Which sectors, and how many | Seeds sensors, shelters, risk zones and the demo script |
| **TQ1** | Tile source for the demo | Determines map implementation and CSP |
| **TQ4** | Tests-first or UI-first for `domain/` | Determines milestone order M2 vs M6 (I recommend tests-first) |

### 14.2 Does not block, but must be decided before the named point

| # | Item | Needed by |
|---|---|---|
| **TQ2** | Open-Meteo commercial status | Before any public deployment |
| **TQ6 / Q7** | Photo retention policy | Before M9 ships the report form |
| **AQ1** | Admin accounts; who plays Publisher | Before M10 demo rehearsal |
| **AQ3** | Alert window default (proposed 6 h) and cap (proposed 24 h) | Before M10 alert builder |
| **AQ5** | Audit log visible to public? | Before M10 |
| **B13** | Heavy-rain threshold source | Only affects an optional label; feature stays absent meanwhile |
| **Q8** | Is a clickable prototype wanted before code? | Before M6 |

### 14.3 Known, accepted, documented

B2 handbook missing · B3 INAMHI manual only · B4 no measured river level · B6 no authoritative shelter
dataset · B8 tile policy · B9 `returnperiods` 500 · B10 Python 3.14 · B12 three fixed defects unverified ·
**B13** no heavy-rain threshold · **R9** the risk model is an unvalidated heuristic.

**A gap I cannot fill:** **there is no deadline anywhere in this project.** The brief mentions no date, no
duration, no submission window. M0–M12 is 13 milestones; whether that is two days or three weeks changes the
plan drastically. **Please tell me the time available**, or I will sequence strictly by the MVP list in §12.1
and treat everything in §12.2 as optional.

---

## 15. Approval request

Stage 4 is complete against all twelve required topics and the MVP/secondary/future split. It states what
will be built, in what order, with what acceptance criteria, and — importantly — what remains unproven.

**Nothing has been implemented.** No dependency installed, no schema applied, no service started, no code
written, no deployment, no Git operation. The evidence ceiling is still **E2**; all 44 safety properties are
still specifications that have never run.

### Decisions — status

| # | Question | Status |
|---|---|---|
| **1** | **R-17 — elevation's role** | **RESOLVED 2026-10-26 → option (a), recorded as D29** (§4.1–4.2) |
| **2** | **Time available** | **RESOLVED: approximately one day.** See §16 — the plan below supersedes §13's 13-milestone order |
| **3** | TQ3/Q3 — sectors and count | Deferred to me: 5 sectors (§16 uses **3** to fit the day; see §16.4) |
| **4** | TQ4 — tests-first for `domain/` | Yes — and it is on the critical path below |
| **5** | TQ1 — tile source | Deferred to me: self-host the demo bbox |

---

## 16. One-day schedule — the operative plan

**Constraint:** approximately **one day** remain (**D30**). §13's 13-milestone sequence does **not** fit. This
section supersedes it for execution order and is the plan to be approved.

**Honest assessment first:** the full §12.1 MVP is roughly **11–13 hours** of focused work for one developer
assisted by an agent, which is at or beyond a single working day. Therefore this plan commits to a **thin
vertical slice that is honest end-to-end**, and explicitly defers breadth. It does not pretend the whole MVP
fits.

### 16.1 Non-negotiables — excluded from every cut, by your instruction

| # | Item | Why it cannot be cut |
|---|---|---|
| 1 | **Risk engine + its tests** | The safety core; every screen reads it. Silent wrongness here is the project's worst failure mode |
| 2 | **Two-phase routing guarantee** | The one property proven by probe; the demo's centrepiece |
| 3 | **Provenance labels** | Verified / Reported / Estimated / Stale / No data — the app's honesty mechanism |
| 4 | **SIMULATED sensor labels** | Without them a prototype reads as a live municipal feed |
| 5 | **Bilingual safety strings** | Spanish is the primary audience's language; D26 blocks publication without both |

Also fixed: **M0 is a hard gate**, and the Python 3.13 fallback keeps pins unchanged.

### 16.2 Critical path — hour by hour

Assumes a single working day (8–10 focused hours). Each block names its **done** test so slippage is visible
immediately rather than discovered at the end.

| Block | Hours | Work | Done when | Cut trigger |
|---|---|---|---|---|
| **0** | 0.75 | **M0 clean install.** `ensurepip` → venv → pinned install → import smoke test → `uvicorn --version` → `npm ci` → `npm run build` | Freeze + lockfile captured; build exits 0 | **Hard gate.** If pins fail on 3.14 → recreate on 3.13, pins unchanged |
| **1** | 1.0 | **Schema + seed (trimmed).** `sectors`, `sensors`, `sensor_readings`, `road_segments`, `road_status`, `alerts`, `incidents`, `shelters`, `audit_log`. RLS on. Seed: **3 sectors**, 6 sensors, ~150 segments, 8 shelters | Migrations apply; `SIM-1` passes (`simulated` defaults true); anonymous admin write rejected | Drop `audit_log` triggers to app-level; drop PostGIS → plain lat/lon |
| **2** | 1.5 | **Risk engine + tests.** `domain/risk.py` pure; severity/confidence/floor separation; **`RISK-1`–`RISK-10`, `4c`, `4d`, `8b`, `8c`** | All named tests green; 100 % branch on `domain/` | **None.** If this slips, everything after it slips; it is never truncated |
| **3** | 0.75 | **Graph artifact + two-phase search.** Overpass extract cached; closed edges removed in phase 1; phase 2 labelled | `ROUTE-1`, `ROUTE-1b`, `ROUTE-2`, `ROUTE-5` green | Reduce bbox to 3 sectors |
| **4** | 1.0 | **Routing end-to-end + coverage + classifications.** `coverage_pct` length-weighted; bands; never-recommend low coverage | `ROUTE-2b`, `2c`, `2d`, `3`, `6`, `7` green | Elevation tie-break (D29) moves to **deferred** if behind — limits 5 permits omission |
| **5** | 0.75 | **Ingestion.** Open-Meteo fetch + cache (both timestamps); sensor simulator writing 6 nodes | Forecast cached; 6 readings persisted; `SIM-2` deterministic | Sensor sim reduced to 2 profiles (`steady`, `surge`) |
| **6** | 1.5 | **Public UI: dashboard + forecast + outlook.** Provenance chips, severity ramp, absolute timestamps | Renders at 360 px; report action above the fold; text before chart; `PROV-1` green | Drop outlook panel; keep dashboard + forecast |
| **7** | 1.0 | **Map + route screen.** Leaflet lazy-loaded; SIMULATED on markers; unknown hatched; route list with coverage % | Layers toggle; tile failure → text list; `ROUTE-4` lint clean | Static map image + text route list (still honest, just less interactive) |
| **8** | 1.25 | **Admin minimal.** Overview, road-status editor (reason + review timer), incident verify/reject, alert draft→publish with non-dispatch statement | Operator cannot publish; `SYNC-1` green; publish confirmation shows non-dispatch sentence | Drop overview tiles; keep roads + alerts (the demo needs a closure) |
| **9** | 0.5 | **i18n EN/ES + safety strings.** Key parity; severity words, chips, refusals bilingual | `I18N-1`, `I18N-2`, `I18N-3` green | **Attempted early** (see §16.3) — not cuttable |
| **10** | 0.75 | **Demo rehearsal + evidence capture.** Run the 11-beat scenario twice; screenshot; write runbook | Scenario completes twice; screenshots timestamped | Local run only; deploy deferred |

**Total: ~10.75 h.** That is a full day with no slack for debugging, and the cut triggers exist precisely
because something will overrun.

**A realism note I would rather state now than discover at hour 9:** 10.75 h of *focused* work typically
consumes **13–15 h of wall-clock** for one developer, because debugging, restarts and context switches are
not in the estimate. So the honest reading is: **this plan is optimistic, and §16.4's deferral list will
almost certainly be used.** That is why §16.4 exists and why §16.6 has decision points instead of hope.

If only 8 h are genuinely available, the realistic outcome is blocks **0–7** plus a seeded demo — no admin
console, closure driven by seed data. That still demonstrates every non-negotiable in §16.1.

### 16.3 Sequencing choices that differ from §13

| Change | Reason |
|---|---|
| **Routing (blocks 3–4) before ingestion (block 5)** | Routing is a non-negotiable and the Demo's centrepiece; ingestion is more forgiving if it slips |
| **i18n keys authored from block 6, not a separate late block** | Block 9 is verification, not translation. Retrofitting bilingual strings at hour 10 is how they get skipped |
| **Admin trimmed to roads + alerts + incidents** | Enough to drive the demo beats; the other nine Stage 2 items stay designed but unbuilt |
| **Deploy deferred to after the day** | You chose internet-hosted demo earlier (D13), but a cold-start debugging session is not affordable today. Local rehearsal first; deploy if time remains |
| **Elevation tie-break (D29) is block 4's only optional element** | D29 limit 5 explicitly authorises omitting it. Passing `ROUTE-8`/`ROUTE-9` is worth doing only if blocks 0–3 finish early |

### 16.4 Explicitly deferred — designed, not built

Recorded so nothing is quietly claimed later:

| Deferred | Consequence |
|---|---|
| 9 of 12 admin items (sensors detail, shelters CRUD, prioritisation queue, audit viewer, users, INAMHI entry, bulk actions, exports, simulation reset) | Admin shows the demo path only |
| Citizen reporting with photos + offline queue | No crowd reports; demo uses seeded verified reports labelled as seeded |
| GEOGloWS river discharge | Outlook omits the river line |
| Offline service worker | Cached-data behaviour shown by network throttling only |
| Elevation tie-breaker (D29) | If block 4 slips; R-17 then documented as omitted under limit 5 |
| Deployment to free-tier hosting | Demo runs locally; D13 remains the intent, not an achievement |
| 2 of 5 sectors | 3 sectors: Norte (Sauces 6, Samanes), Centro (Santa Ana), Sur (Cristo del Consuelo) |
| Accessibility verification pass | Four severity encodings still shipped; axe/keyboard pass deferred |
| 5 of 44 safety properties involving admin breadth | Remain specifications |

### 16.5 What the demo will honestly be able to show after one day

**Yes:** real Open-Meteo forecast with model run time · six simulated sensors with SIMULATED badges · an
offline sensor dropping confidence but **not** the level · a risk level with its inputs and coverage named ·
two-phase routing avoiding a real closure, with coverage % and low-coverage routes served but not recommended ·
a published bilingual alert stating it was not dispatched externally · provenance chips throughout.

**No:** real river data · citizen photo reports · offline queueing · full admin console · deployed URL · any
claim that the risk score predicts flooding.

### 16.6 Checkpoints — decided in advance, not in the moment

| At | If behind | Action |
|---|---|---|
| Hour 2 | Block 1 not done | Drop PostGIS, drop `audit_log` to app-level |
| Hour 4 | Block 2 not green | **Stop and report.** The safety core is not compromised to save the schedule |
| Hour 7 | Block 6 not rendering | Ship text-only UI; map becomes a deferred item |
| Hour 9 | Block 8 not working | Demo drives the closure via seeded data; label it seeded |
| Hour 10 | Not rehearsed | **Do not present.** A rehearsed thin slice beats an unrehearsed full one |

### 16.7 Standing rules for the day

- Never `git commit`, push, or deploy without explicit authorisation.
- Report actual command output at each gate; write "not run" rather than implying a pass.
- Update `PHASES.md` and `AGENT.md` at every block boundary, not at the end.
- Simulated stays labelled simulated, in every screenshot taken under time pressure.

---

## 17. Approval request for Stage 5

Stage 4 is **approved** (2026-10-26) with R-17 = (a) as **D29**, and the one-day constraint (**D30**) now
governs the schedule in §16.

**Nothing has been implemented.** No dependency installed, no schema applied, no service started, no code
written, no deployment, no Git operation. Evidence ceiling remains **E2**; all 44 safety properties are still
specifications that have never run.

**I am not starting M0 until you give explicit Stage 5 approval.** On that approval I will begin block 0,
report its real output — including a failure — and proceed block by block against the checkpoints in §16.6.
