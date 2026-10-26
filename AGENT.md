# AGENT.md — Guaradar Persistent Handover Guide

**Last updated:** 2026-10-25
**Purpose:** let any agent, in any future session, continue this project with no access to prior chat.

Read this file first, then `PHASES.md`, then inspect the repository.

---

## 1. Project identity

| Field | Value |
|---|---|
| Name | Guaradar |
| Event | HACK2IMPACT 2026 |
| Track | Nu Zeta Track 1 — Heavy Rain & Flood Resilience in Guayaquil, Ecuador |
| Tagline | Detect Early. Navigate Safely. |
| Users | Citizens of Guayaquil (public portal); authorised city staff (admin centre) |
| Language | **English primary UI, Spanish secondary via toggle** (owner decision 2026-10-25). Author strings in English first, then translate. Spanish-only strings in the primary locale are a defect. |
| Constraint | Minimal, fast-loading, mobile-friendly, usable on unreliable networks |

Guayaquil is flat, sits on the Guayas estuary, and floods when rainfall overwhelms urban drainage.
On 2026-10-19 the city recorded ~216 mm in about a day and 70+ neighbourhoods flooded, with ~26
sectors already pre-identified as flood-prone (incl. Sauces 6, Samanes, Martha de Roldós).

---

## 2. Absolute rules (do not violate, do not ask to violate)

1. **Never run `git commit`** — not normal, amend, empty, scripted, or milestone. Do not ask another
   agent or tool to commit. Inspecting status/diff is allowed. Do not reset, clean, discard, or
   overwrite user work without explicit permission. Do not push or deploy without explicit permission.
2. **Approval sequence is mandatory and ordered:**
   `PUBLIC INTERFACE → ADMIN INTERFACE → TECHNOLOGY STACK → OTHER REQUIREMENTS → IMPLEMENTATION`.
   Stop and obtain explicit approval at each stage. Never combine, reorder, or skip.
3. **No application code, no package installs, no repository modification** before all four planning
   stages are approved.
4. **Never claim something works until it has been tested.** No unverified API integration, DB
   connection, or route calculation may be described as working.
5. **Do not invent** live water levels, official alerts, verified road closures, or shelter
   availability. Simulated sensor data is always labelled simulated.
6. **Missing information is not good news.** No flood report does not mean a road is safe.
   Never present a route as "safe" — only "no known hazards", with coverage stated.
7. **English is the primary UI language; Spanish is the secondary locale.** Do not write Spanish-first
   strings and assume translation later — the string table is authored in English.

---

## 3. Features

**Public: 8, approved 2026-10-25** (Stage 1). Specification: `docs/STAGE-1-PUBLIC-INTERFACE.md`.

1. Safety Dashboard · 2. Rainfall Forecast (mandatory) · 3. Interactive Flood Map ·
4. Flood Outlook · 5. Safe Route Finder · 6. Shelter & Emergency Finder ·
7. Citizen Flood Reporting · 8. Low-network experience.

**Admin: 12 required items, proposed 2026-10-25, awaiting approval** (Stage 2). Specification:
`docs/STAGE-2-ADMIN-INTERFACE.md`. Overview dashboard; flood intelligence map; 5+ simulated water-level
nodes with depth/threshold/trend/timestamp/health; rainfall forecasts and risk intelligence; river and
tidal observations; full alert lifecycle; citizen incident review; road-status management; shelter
management; basic risk prioritisation; authentication and permissions; plus an append-only audit log.

Note the intentional semantics: the brief's alert "verify" is implemented as **approve**, and
"publish" is the transition that makes an alert visible to citizens. The two are separate roles.

---

## 4. Confirmed technology stack

Confirmed as the *intended* starting stack by the brief, and **accepted unchanged in Stage 3** with four
declared exceptions (Stage 3 §1). **Nothing installed yet.**

| Layer | Choice |
|---|---|
| Frontend | React + Vite + TypeScript (TanStack Query, react-router, Leaflet) |
| Maps | Leaflet + OpenStreetMap (tile source unresolved — Stage 3 TQ1) |
| Backend | Python + FastAPI, `venv`, exact pins in `requirements.txt` |
| Database | Supabase PostgreSQL + PostGIS + RLS + Auth |
| Routing | OSM extract as versioned graph artifact + NetworkX |
| Rainfall | Open-Meteo API (live-verified), INAMHI cross-check **by manual bulletin entry** |
| River | GEOGloWS ECMWF modelled discharge (live-verified), labelled Estimated |
| Elevation | **SRTM 1-arcsec 30 m** (honoured; fetchable and measured) — static context only |
| Design | Minimal light theme, teal + navy, mobile-first, English-primary |

Runtime measured on this machine: Python 3.14.8 (no `pip` on PATH; use `ensurepip`), Node 24.20.0.
Wheels verified available for pydantic-core, asyncpg, numpy, shapely, osmnx, geopandas. Fallback to
Python 3.13 if 3.14 misbehaves — do **not** swap libraries.

---

## 5. Architecture and design decisions

Nothing implemented. Decisions taken at proposal level only:

- **Provenance is a UI primitive** — every data point carries exactly one chip: **Verified /
  Verificado · Reported / Reportado · Estimated / Estimado · Stale / Desactualizado · No data /
  Sin dato**. Word + icon + timestamp, never colour alone.
- **Severity** — four levels, each with numeral + word + icon shape + colour (redundant encoding).
- **Text-first rendering** — the accessible list is canonical; the chart is a view of it. Map is
  never part of first paint.
- **Route honesty** — routes are "no known hazards" with a mandatory coverage percentage
  (share of route length verified within freshness budget).
- **Elevation tie-break is the last sort term** (D29): `(hazard_class, coverage_band, duration, ±elevation)`.
  It may never lift a route across a class or coverage boundary. If `ROUTE-8`/`ROUTE-9` cannot pass, elevation
  is removed from ranking and the limitation documented.
- **Ambiguity is displayed, not resolved** — disagreeing sources are both shown, never averaged.
- **Severity never suppressed by evidence volume** (D18, D27). Coverage drives confidence and the
  insufficient-evidence indicator only. A missing input can never lower the published risk level.
- **Precaution floor raises only, never lowers** (D19, D23). Driven by verified reports and
  operator-confirmed closures. **Heavy-rain trigger is disabled** — no defensible threshold exists yet.
- **Routes: serve low coverage, never recommend it** (D24, D25). 60 % is a provisional recommendation
  boundary, not a measured safety threshold. Refusal only for no path or snap > 60 m.
- **Alerts require both languages before publishing** (D26) — no override.
- **Deep-linkable state** — every screen carries its state in the URL, because WhatsApp is the real
  distribution channel.

---

## 6. Directory structure

```
GuaRadar/
├── AGENT.md                              # this handover file
├── PHASES.md                             # roadmap + progress (source of truth)
├── docs/
│   ├── STAGE-1-PUBLIC-INTERFACE.md       # Stage 1 — APPROVED 2026-10-25
│   ├── STAGE-2-ADMIN-INTERFACE.md        # Stage 2 — APPROVED 2026-10-25
│   ├── STAGE-3-ARCHITECTURE.md           # Stage 3 — APPROVED 2026-10-26 (D23–D28)
│   ├── STAGE-3-REVIEW-RESPONSE.md         # disposition of the eight review points
│   ├── STAGE-3-DECISION-SUMMARY.md        # decision digest incl. D23–D28
│   ├── STAGE-3-RECONCILIATION.md          # cross-document reconciliation history
│   ├── STAGE-4-REQUIREMENTS-PLAN.md       # Stage 4 — PRESENTED 2026-10-26, awaiting approval
│   ├── EVIDENCE-STATUS.md                 # E0–E4 ladder: what ran vs what is only specified
│   └── DATA-SOURCES.md                   # per-source verification notes and claim limits
├── research/
│   ├── graphcheck.py                     # OSM routability probe (NOT app code)
│   ├── terraincheck.py                   # SRTM 30 m vs 90 m DSM probe (NOT app code)
│   └── routing_invariant.py              # penalty-vs-two-phase safety probe (NOT app code)
└── .zwork/                               # tooling attachments, not application code
```

`research/*.py` are standalone feasibility probes, Python stdlib only. They are the only executables in
the project, are not part of the application, and must never be imported by it.

No `frontend/`, `backend/`, or `supabase/` directories exist yet. They must not be created before
Stage 5.

---

## 7. Setup, development, testing, deployment

**Not applicable yet.** Nothing is installed, no dependencies are pinned, no scripts exist, and the
directory is **not a Git repository** (`git status` → *not a git repository*).

Commands will be documented here at Stage 5. Until then, do not run `npm create`, `pip install`, or
`supabase init`.

---

## 8. API endpoints and database schema

**None defined.** Deferred to Stage 3 by instruction. Do not invent endpoints or tables before then.

---

## 9. Data sources and integration status

| Source | Purpose | Status |
|---|---|---|
| Open-Meteo Forecast API | hourly `precipitation`, `precipitation_probability`, model run time | **Live-verified 2026-10-25** (HTTP 200, 24 hourly values). Not integrated into any app |
| Open-Meteo Elevation API | terrain elevation | 90 m Copernicus GLO-90 **DSM**. **Rejected** in favour of SRTM 30 m (Stage 3 §7) |
| SRTM 1-arcsec (30 m) | terrain elevation — **chosen** | Fetchable via AWS `elevation-tiles-prod` skadi/terrarium; decoded with stdlib only; live-verified across six Guayaquil points (**4–14 m**). Static context only (D12) |
| GEOGloWS ECMWF streamflow | modelled river discharge, 10-day horizon | **Live-verified + adopted 2026-10-25** as "Estimated · modelled discharge". `getriverid` + `forecaststats`/`forecastrecords` work; **`returnperiods` returns HTTP 500** so no return-period claims |
| OpenStreetMap / Overpass | road graph, shelters, POIs | Licence ODbL; tile usage policy must be respected; **routability measured 2026-10-25** (96.9 % single component, 1.34× detour on a test route, central bbox only); not integrated |
| INAMHI | official rainfall cross-check | **No public API.** Guayaquil-specific bulletins exist; integration is manual admin entry with the bulletin's issue time |
| INOCAR | Ecuadorian tide tables (incl. Guayaquil) | Existence confirmed; programmatic access **not** verified — tide is *prediction only*, never a measured river level |

Attribution obligations to carry into the UI: Open-Meteo (CC BY 4.0), NASA/USGS for SRTM,
OpenStreetMap contributors (ODbL).

---

## 10. Known bugs, limitations, security concerns

- **Elevation: RESOLVED as D12.** SRTM 1-arcsec 30 m is used (honours the brief, finer grid), measured
  at 4–14 m across the city. **Terrain is static context only** — it may not rank streets, predict depth,
  or act as a live signal, because its error exceeds the city's entire ~10 m relief. Any rendered
  elevation must carry "approximate, SRTM 30 m". Both SRTM and the 90 m Copernicus product are DSM-like.
- **GEOGloWS `returnperiods` is broken** (HTTP 500, `No variable named 'logpearson3'`). Never make a
  "1-in-N-year" claim. Show absolute modelled discharge + ensemble band, or omit the line.
- **GEOGloWS CSV parsing trap.** `forecaststats` mixes 120 three-hourly ensemble rows with 240 hourly
  high-res rows; blank ensemble cells must be filtered or the series looks like a flatline.
- **No measured river level.** Tide is astronomical prediction. GEOGloWS modelled streamflow is an
  *Estimated* river signal at most. Do not present either as a flood measurement.
- **INAMHI is manual.** No API. Never render an automated "INAMHI agrees" indicator from a hand-entered
  bulletin without labelling it as editor-entered.
- **No authoritative shelter list.** Admin-curated records only, labelled app-managed.
- **HACK2IMPACT handbook missing.** A look-alike IEEE hackathon (HackTech El Niño 2026, Track 1:
  Telecommunications & Early Warning Systems in Crisis) surfaced in search and is **not** this event.
  Do not import its rules or judge criteria.
- **No official alert feed.** All alerts are app-internal. Never claim an alert reached emergency
  services or the public at large.
- **Not under version control.** Irreversible mistakes cannot be reverted. Fix requires explicit
  permission; initialising a repo must never be followed by a commit.
- **Access control unknown.** Admin authentication is a Stage 2/3 design item. Supabase anon keys are
  public by design — RLS must be correct, and service-role keys must never reach the client.
- **Photo upload risk.** EXIF may carry location metadata; strip on upload, validate type and size,
  and rate-limit submissions.
- **Seeded demo data vs real conditions.** Oct 2026 flooding is live news; seeded scenarios must be
  visibly labelled so no one mistakes them for current reality.

---

## 11. Outstanding approvals and decisions

- **Stage 1 — APPROVED** 2026-10-25. **Stage 2 — APPROVED** 2026-10-25. Do not re-present either.
- **Stage 3 — APPROVED 2026-10-26** on the reconciled decisions D23–D28. Do not re-present it.
- **Stage 4 — APPROVED 2026-10-26.** R-17 = (a) recorded as **D29**; one day remaining recorded as **D30**.
  The operative schedule is `docs/STAGE-4-REQUIREMENTS-PLAN.md` **§16**, which supersedes §13's 13-milestone
  order.
- **Stage 5 — NOT STARTED.** Awaiting explicit approval. M0 is a hard gate.
- **D29 in force:** elevation is a **disclosed approximate tie-breaker only**. Sort order is
  `(hazard_class, coverage_band, duration, ±elevation)`; elevation can never lift a route across a class or
  coverage boundary (`ROUTE-8`, `ROUTE-9`). If those tests cannot pass, **omit elevation from ranking** and
  document it.
- **D30 in force:** ≈one day remains. Non-negotiables never cut: risk engine + tests, two-phase routing,
  provenance labels, SIMULATED labels, bilingual safety strings.
- **Stage 3 decisions, as approved (do not reopen without the owner):**
  - **D23** precaution floor: reports + closures active, **heavy-rain trigger disabled** (no defensible
    threshold); floor numbers provisional and unvalidated
  - **D24** low/zero-coverage routes: serve, never recommend, prominent uncertainty warning
  - **D25** 60 % recommendation boundary retained **provisionally**, explicitly unvalidated
  - **D26** hard bilingual publishing block stands; **no override**, Stage 2 requirement unchanged
  - **D27** sensor-coverage severity cap permanently removed; replacement specified but untested
  - **D28** prototype sensor thresholds SIM-01…SIM-06 retained, labelled simulated and unvalidated
- **Carried into Stage 4/5** (not Stage 3 blockers): `TQ1`–`TQ3`, `TQ6`, `AQ1`, `AQ3`, `AQ5`; Stage 1
  `Q3` (demo sectors), `Q7` (photo retention), `Q8` (mockup); plus blocker **B13** — no defensible
  "heavy rain" threshold exists, so no public heavy-rain label until one is sourced and approved.
- HACK2IMPACT handbook — unavailable (owner confirmed). Stage 4 cites only the master instructions and
  must state that event requirements are unverified.

---

## 12. Current status and next steps

**Status:** Stages 1–4 **approved**. Stage 5 in progress: **M0–M12 done**.
**464 passed, 3 skipped** with PostgreSQL 16.2; **455 passed, 12 skipped** without a database.
`domain/risk.py` and `status_repository.py` both at **100 % branch coverage**.
No repo, no commits, no deployment.

**M12 (2026-10-26):** scenario selector added to the route form (defaults to baseline, discloses the
demo fixture bilingually, non-dismissible). `road_segments` load path documented and made idempotent —
**N-14 closed for the load path**, proven across three runs on real PostgreSQL 16.2 with an identical
row count and identical id-set hash. The i18n guard was found to be validating only 45 of 76 keys;
fixed, now 76/76 with a full-coverage assertion and negation awareness. **N-5 remains open — no
browser exists on this host, so nothing has been visually verified.**

**Evidence discipline (D17):** the project ceiling is **E2 = probed**. Nothing is called passing,
working, or secure. The 43 safety properties in Stage 3 §17.1 are **specifications that have never run**.
Read `docs/EVIDENCE-STATUS.md` before asserting anything about this project's correctness.

**Verified by live calls on 2026-10-25** (E2 probes only — nothing integrated, no test suite exists):

- Open-Meteo forecast: HTTP 200, `precipitation` + `precipitation_probability` return 24 hourly values
  in `mm` and `%`.
- Open-Meteo elevation: six Guayaquil points return **3–10 m** on the 90 m DSM; SRTM 30 m reads **4–14 m**.
  The city has effectively no vertical relief, which shapes every risk decision in this project.
- GEOGloWS: `getriverid` → `670068009`; `forecaststats` yields 120 ensemble rows @3 h + 240 high-res @1 h,
  flow 5,050–8,844 m³/s; **`returnperiods` returns HTTP 500**.
- Routing invariant: a finite closed-road penalty **failed** (1 violation / 1201 graphs); a two-phase edge
  filter held 1201/1201. See D16.
- OSM road graph: central bbox → 6,202 ways, 22,499 nodes, 1,184.9 km, **96.9 % in one connected
  component**, 32.8 % junctions, **1.34× detour** on an 11.9 km test route. Routing is viable.

**Next steps, in order:**

1. **Block 1 — schema + seed** (trimmed): `sectors`, `sensors`, `sensor_readings`, `road_segments`,
   `road_status`, `alerts`, `incidents`, `shelters`, `audit_log`; RLS on; seed 3 sectors, 6 sensors, ~150
   segments, 8 shelters.
2. Then blocks 2 → 10 per Stage 4 §16.2, honouring the §16.6 checkpoints (hour 4: risk engine not green →
   stop and report rather than compromise the safety core).
3. Update `PHASES.md` and `AGENT.md` at every block boundary.

Stages 1–4 are **approved**. M0 is **PASSED** (`docs/M0-EVIDENCE.md`). Do not re-present them.

**Host constraint (recorded at M0):** only Python 3.14.8 is installed — **no 3.13 fallback exists on this
machine**. Pins installed cleanly on 3.14 with no source builds, so the fallback was not needed; if a later
block hits a 3.14-only failure, installing 3.13 or changing a pin both require the owner's approval.

**On every new session:** read this file → read `PHASES.md` → inspect the repository → compare docs to
code → list discrepancies → continue from the documented next step. If either file is missing, create
it to reflect the true current state; never overwrite valid existing content.

---

## 13. Reminder

**Never commit. Never claim untested things work. Never let silence look like safety.**
