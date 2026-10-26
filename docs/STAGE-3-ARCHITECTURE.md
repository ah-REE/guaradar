# Guaradar — Stage 3: Technology Stack and Architecture

**Status:** **APPROVED 2026-10-26** on the reconciled decisions D23–D28.
**Approved predecessors:** Stage 1 Public Interface and Stage 2 Admin Interface, both approved 2026-10-25
**Decision history:** eight review points addressed (`docs/STAGE-3-REVIEW-RESPONSE.md`); three-document
reconciliation with three safety defects corrected (`docs/STAGE-3-RECONCILIATION.md`); all six outstanding
decisions O-1…O-6 resolved by the owner on 2026-10-25 and recorded as **D23–D28**; **Stage 3 approved
2026-10-26.**
**Scope of this document:** architecture and technical design only.
**Out of scope (by instruction):** the implementation plan, event-requirement mapping, and any code.
**Date:** 2026-10-25

---

## 0. What this document must do

Specify the system clearly enough that Stage 5 can be built without re-deciding anything, and honestly
enough that no claim here outruns what has been measured. Every performance, limit, or integration
statement is marked **verified** (tested during this review) or **planned** (asserted, unproven).

A short note on where the hard thinking went: the terrain measurement changed the risk model. §7 and §8
are therefore *smaller* and more conservative than a naive flood app would be, and that is deliberate.

---

## 1. The confirmed stack — kept, with four recorded exceptions

The brief fixes the stack. It is accepted **as-is** except for four points, each declared here rather
than silently substituted:

| Layer | Brief says | This design uses | Why |
|---|---|---|---|
| Frontend | React + Vite + TypeScript | **Same** | No change |
| Maps | Leaflet + OpenStreetMap | **Same**, with a tile-source decision (§13) | No change to library |
| Backend | Python + FastAPI | **Same** | No change |
| Database | Supabase PostgreSQL | **Same**, using PostgREST + PostGIS | No change |
| Routing | OSM + NetworkX | **Same** | No change |
| Rainfall | Open-Meteo, INAMHI cross-check | **Same**; INAMHI is manual entry (§11) | INAMHI has no public API |
| Elevation | SRTM 30 m DEM | **SRTM 1-arcsec, 30 m** — honoured | Fetchable and tested; see §7 |
| Design | Light, teal/navy, responsive | **Same** | No change |

**Declared deviations (none change a confirmed technology):**

1. **INAMHI integration is manual, not automated.** The brief says "cross-check when accessible".
   It is not accessible as an API, so an operator records the bulletin. Documented in §11.
2. **GEOGloWS modelled discharge is added** as the river signal, per owner decision 2026-10-25. It is
   an addition, not a replacement, and it is labelled as modelled.
3. **Terrain is downgraded to static context.** The brief nominates elevation as a data input; the
   measurements in §7 show it cannot support street-level inference. The dataset is kept and used
   honestly rather than cut.
4. **Return-period framing is unavailable** because GEOGloWS `returnperiods` returns HTTP 500. The UI
   shows absolute flow and ensemble spread instead; no "1-in-N-year" claim will be made.

Nothing else in the confirmed stack is changed. If any further change becomes necessary at
implementation time, it will be raised for approval before use.

---

## 2. Runtime environment — a real constraint worth stating

**Measured on this machine:** Python **3.14.8**, Node **24.20.0**, npm **11.19.0**, no `pip` on the
PATH (available via `python3 -m ensurepip --version` → pip 26.2.1), no `uv`.

**Verified wheel availability** on PyPI for Python 3.14:

| Package | Latest | cp314 / pure-python wheels |
|---|---|---|
| pydantic-core | 2.50.1 | 31 |
| asyncpg | 0.32.0 | 18 |
| numpy | 2.5.4 | 21 |
| shapely | 2.2.0 | 18 |
| osmnx | 2.1.1 | pure-python |
| geopandas | 1.2.0 | pure-python |

So the stack is *installable* on 3.14. But 3.14 is very new, and the risk is not installation — it is
subtle library bugs discovered mid-hackathon.

**Decision:** build inside a **`venv` created with `python3 -m venv`**, pin exact versions in
`requirements.txt`, and keep **Python 3.12/3.13 as the documented fallback**. If any core dependency
misbehaves at Stage 5, the response is to pin down to 3.13 — not to swap libraries.

**Also recorded:** `pip` is absent from PATH and must be bootstrapped with `ensurepip` inside the venv.
Stage 5 must not assume a working `pip`.

---

## 3. System architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Browser                                                             │
│  ┌────────────────────┐   ┌──────────────────────────────────────┐   │
│  │ Public app (React) │   │ Admin console (React, /admin)        │   │
│  │ 8 features         │   │ 12 required items                    │   │
│  └─────────┬──────────┘   └───────────────┬──────────────────────┘   │
│            │  TanStack Query (cache + staleness)                     │
│            │  Service Worker (offline shell, cached payloads)        │
└────────────┼─────────────────────────────┼──────────────────────────┘
             │ HTTPS/JSON                  │ HTTPS/JSON + JWT
             ▼                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI (Python)                                                    │
│  ┌──────────┬──────────┬──────────┬──────────┬────────────────────┐  │
│  │ /alerts  │ /roads   │ /sensors │ /forecast│ /route  /reports   │  │
│  └──────────┴──────────┴──────────┴──────────┴────────────────────┘  │
│  ┌────────────────────┐ ┌──────────────────┐ ┌───────────────────┐   │
│  │ Risk engine        │ │ Route engine     │ │ Scheduler         │   │
│  │ (pure, testable)   │ │ (NetworkX graph) │ │ (ingest + sim)    │   │
│  └────────────────────┘ └──────────────────┘ └───────────────────┘   │
└───────┬──────────────────────┬──────────────────────┬────────────────┘
        │                      │                      │
        ▼                      ▼                      ▼
┌───────────────┐   ┌────────────────────┐   ┌──────────────────────┐
│ Supabase      │   │ Upstream APIs      │   │ Static assets        │
│ PostgreSQL    │   │ · Open-Meteo       │   │ · OSM extract (.graphml│
│ + PostGIS     │   │ · GEOGloWS         │   │   or pgRouting tables)│
│ + RLS + Auth  │   │ · (INAMHI: manual) │   │ · SRTM tiles (cached) │
│ + Storage     │   │                    │   │ · shelter seed CSV    │
└───────────────┘   └────────────────────┘   └──────────────────────┘
```

**Three deliberate separations**

1. **The risk engine is pure and dependency-free.** Given inputs, it returns a level plus a reason list.
   No database, no network, no clock injection. This makes the one piece of logic that must never be
   wrong unit-testable without mocks — and it is the piece the public and admin screens both read.
2. **The route engine reads a single graph artifact, not live OSM.** OSM is extracted once, versioned,
   and loaded; status overlays are applied at query time. No per-request Overpass call (§13).
3. **The frontend never talks to upstream APIs directly.** All external data is proxied and cached
   server-side, so one citizen with a broken network can still be served a dated answer, and so API
   limits are enforced in one place.

---

## 4. Directory structure

```
GuaRadar/
├── AGENT.md
├── PHASES.md
├── docs/                          # stage proposals + data-source notes (planning artefacts)
├── research/                      # feasibility probes, NOT application code
├── .env.example                   # names only, never values
├── frontend/
│   ├── index.html
│   ├── vite.config.ts
│   ├── package.json
│   ├── public/
│   │   ├── manifest.webmanifest
│   │   └── sw.js                  # offline shell + payload cache
│   └── src/
│       ├── main.tsx
│       ├── App.tsx                # router: /public and /admin trees
│       ├── i18n/
│       │   ├── en.json            # authored first
│       │   └── es.json            # translated second
│       ├── lib/
│       │   ├── api.ts             # typed fetch client, single base URL
│       │   ├── query.ts           # TanStack Query client, staleness rules
│       │   ├── offline.ts         # queue + cache read/write
│       │   └── format.ts          # numbers, timestamps, relative age
│       ├── components/            # ProvenanceChip, SeverityBadge, Timestamp,
│       │                          # StatTile, EmptyState, ErrorState, Skeleton
│       ├── features/
│       │   ├── dashboard/
│       │   ├── forecast/
│       │   ├── map/
│       │   ├── outlook/
│       │   ├── route/
│       │   ├── shelters/
│       │   ├── report/
│       │   └── admin/
│       │       ├── overview/  sensors/  alerts/  incidents/
│       │       ├── roads/     shelters/ audit/   users/
│       └── styles/
│           ├── tokens.css         # colour/space/type tokens from Stages 1–2
│           └── global.css
├── backend/
│   ├── requirements.txt          # exact pins
│   ├── pyproject.toml            # tooling config only
│   ├── app/
│   │   ├── main.py               # FastAPI app, routers, CORS, error handlers
│   │   ├── config.py             # pydantic-settings, env validation
│   │   ├── deps.py               # auth dependencies, role guards
│   │   ├── api/
│   │   │   ├── public.py         # citizen endpoints
│   │   │   ├── admin.py          # operator endpoints (role-guarded)
│   │   │   └── health.py
│   │   ├── domain/               # pure logic, no I/O
│   │   │   ├── risk.py           # risk levels + reason generation
│   │   │   ├── trend.py          # slope, time-to-threshold, sufficiency gate
│   │   │   ├── priority.py       # severity × exposure × recency
│   │   │   └── provenance.py     # chip state derivation + staleness budgets
│   │   ├── routing/
│   │   │   ├── graph.py          # load/build graph, cache in memory
│   │   │   └── search.py         # alternative routes + coverage metric
│   │   ├── ingest/
│   │   │   ├── openmeteo.py
│   │   │   ├── geoglows.py
│   │   │   └── terrain.py        # SRTM sample → per-segment elevation
│   │   ├── simulate/
│   │   │   └── sensors.py        # deterministic, seeded sensor simulator
│   │   └── db/
│   │       ├── client.py         # Supabase client (service role, server only)
│   │       └── queries.py
│   ├── scripts/
│   │   ├── extract_graph.py      # OSM → graph artifact (run once)
│   │   ├── seed.py               # deterministic demo fixtures
│   │   └── sample_terrain.py     # SRTM → per-segment elevation
│   └── tests/
│       ├── unit/                 # domain logic, no I/O
│       ├── integration/          # DB + API, test project
│       └── fixtures/
└── supabase/
    ├── migrations/
    │   ├── 0001_init.sql
    │   ├── 0002_rls.sql
    │   └── 0003_functions.sql
    └── seed.sql
```

---

## 5. Data model

PostgreSQL via Supabase, with PostGIS for geometry. Row counts are for the demo scale (one city,
~5–8 sectors, 5–6 sensors, a few hundred reportable roads).

### Core tables

```sql
-- geography ---------------------------------------------------------------
sectors(id, name_en, name_es, geom polygon, exposure_weight int, created_at)

-- monitored network -------------------------------------------------------
road_segments(
  id, osm_way_id bigint, name, class,
  geom geometry(LineString, 4326),
  length_m numeric,
  elevation_m numeric,           -- SRTM sample, static context only
  elevation_source text,         -- 'SRTM1' | null
  sector_id references sectors
)

sensors(
  id, code, name, sector_id,
  geom geometry(Point,4326),
  threshold_m numeric,           -- depth that counts as flooding here
  expected_interval_s int,       -- for health derivation
  stale_after_s int,
  simulated boolean NOT NULL DEFAULT true
)

sensor_readings(
  id bigserial, sensor_id, depth_m numeric,
  observed_at timestamptz,       -- when it claims to be
  ingested_at timestamptz default now(),
  quality smallint,              -- 0 ok, 1 suspect
  simulated boolean NOT NULL DEFAULT true
)  -- index on (sensor_id, observed_at desc)

-- operational state -------------------------------------------------------
road_status(
  road_segment_id primary key, status text,   -- open|affected|closed|unknown
  depth_band text,                              -- <15|15-40|40-80|>80|unknown
  reason text, evidence_url text,
  set_by uuid, set_at timestamptz,
  review_at timestamptz,                        -- staleness timer
  source text                                   -- operator|system|report
)

alerts(
  id uuid, severity smallint,                   -- 1..4
  headline_en, headline_es, body_en, body_es,
  instructions_en, instructions_es,
  starts_at, ends_at timestamptz,
  status text,                                  -- draft|review|published|expired
  source_basis text[], created_by, published_by, published_at,
  version int
)
alert_sectors(alert_id, sector_id)
alert_versions(id, alert_id, snapshot jsonb, changed_by, changed_at)

incidents(                                       -- citizen reports
  id uuid, geom geometry(Point,4326), accuracy_m numeric,
  depth_band text, description text, photo_path text,
  capture_at, submitted_at timestamptz,
  status text,                                   -- pending|verified|rejected|duplicate
  reviewed_by uuid, reviewed_at timestamptz, review_note text,
  reporter_code text, duplicate_of uuid
)

shelters(
  id uuid, name, type,                           -- shelter|hospital|fire|police
  geom geometry(Point,4326), address, phone,
  capacity int, accessibility text[],
  status text, status_hold_until timestamptz,
  authorised_source text, updated_by, updated_at
)

-- traceability -----------------------------------------------------------
audit_log(
  id bigserial, actor uuid, action text, target_table text, target_id text,
  before jsonb, after jsonb, reason text, at timestamptz default now()
)  -- append-only: no UPDATE/DELETE grants for any role

-- ingestion cache ---------------------------------------------------------
weather_cache(lat, lon, fetched_at, model_run_at, payload jsonb,
              primary key (lat, lon))
river_cache(river_id bigint, fetched_at, model_run_at, payload jsonb,
            primary key (river_id))
inamhi_bulletins(id, issued_at, headline, url, entered_by, entered_at)

-- thresholds are admin-editable, so they are data not code
thresholds(key text primary key, value numeric, description, updated_by, updated_at)
```

### Relationships that matter

- `sensors → sectors` and `road_segments → sectors` give the sector rollup the dashboard needs.
- `road_status` is **1:1 with road_segments** by primary key — this is how "one record, one source of
  truth" (Stage 2 §12) is enforced structurally rather than by convention. There is no second copy for
  the public app to drift from.
- `incidents.duplicate_of` supports merging without deleting the original.
- `alert_versions` is append-only, so an update never destroys what was previously published.

### Deliberate exclusions

- **No `public_alerts` view duplicating `alerts`.** A view is fine; a second table is not.
- **No user profile table for citizens.** Reports are anonymous by design; `reporter_code` is a random
  opaque code, not an identity.
- **No time-series hypertable.** At demo volume, a plain indexed table is sufficient. Recording the
  non-choice prevents someone adding TimescaleDB "for completeness".

### Supabase free-tier constraint (verified from published pricing)

Free tier: **500 MB database**, 1 GB file storage, 5 GB egress, projects **paused after 1 week of
inactivity**. Consequences:

- Report photos are **compressed client-side** (target ≤300 KB) and the DB stores only a path.
- Sensor readings are **pruned** by a retention job (keep 30 days); the simulator does not grow forever.
- The demo must be re-woken before a pitch — a paused project reads as a broken app.
- The OSM graph is **not** stored in Postgres. At 22,499 nodes for a 10×8 km box it would fit, but a
  city-wide graph plus PostGIS indexes is unnecessary pressure on a 500 MB budget. It lives as a
  versioned artifact loaded into memory (§9).

---

## 6. API design

Two routers, one base URL, JSON only. Public read endpoints are unauthenticated; every mutation requires
a JWT with the right role.

### Public

| Method | Path | Returns |
|---|---|---|
| GET | `/api/public/dashboard?sector=` | risk level, reason lines, active alerts, road counts, nearest shelter, fetched_at |
| GET | `/api/public/forecast?sector=` | hourly precipitation + probability, model run, INAMHI bulletin status |
| GET | `/api/public/map?sector=&layers=` | road statuses, sensors, shelters, verified incidents, risk zones |
| GET | `/api/public/outlook?sector=` | contributing factors, sensor trends, discharge + tide context, or "no estimate" + reason |
| GET | `/api/public/shelters?near=` | shelter list with status + distance |
| GET | `/api/public/route?from=&to=&mode=` | up to 3 routes with geometry, length, time, hazards avoided, **coverage %** |
| POST | `/api/public/reports` | create a report (validated, rate-limited, queued offline) |
| GET | `/api/public/reports/{code}` | reporter's own status lookup |

### Admin (role-guarded)

| Method | Path | Role |
|---|---|---|
| GET | `/api/admin/overview` | viewer+ |
| GET/PATCH | `/api/admin/roads/{id}` | operator+ |
| PATCH | `/api/admin/roads/bulk` | admin |
| GET | `/api/admin/sensors`, `/{id}` | viewer+ |
| PATCH | `/api/admin/sensors/{id}` (threshold, profile) | admin |
| GET | `/api/admin/incidents` | viewer+ |
| POST | `/api/admin/incidents/{id}/verify` \| `/reject` \| `/duplicate` | operator+ |
| POST | `/api/admin/alerts` (draft) | operator+ |
| POST | `/api/admin/alerts/{id}/submit` \| `/approve` \| `/publish` \| `/expire` | publisher for publish |
| POST | `/api/admin/inamhi` | operator+ |
| GET/PATCH | `/api/admin/shelters/{id}` | operator+ |
| GET | `/api/admin/audit` | admin |
| POST | `/api/admin/simulate/reset` | admin |

### Response envelope — every read carries its own honesty

```json
{
  "data": { "...": "..." },
  "provenance": {
    "chip": "estimated",
    "fetched_at": "2026-10-25T14:32:11Z",
    "stale_after_s": 600,
    "sources": [{"name": "Open-Meteo", "model_run_at": "2026-10-25T12:00:00Z"}],
    "simulated": true
  }
}
```

**The chip is computed server-side, never in the component.** A frontend that decides staleness itself
will eventually disagree with another screen; computing it once, next to the data, makes the three
interfaces unable to contradict each other. This is the enforcement mechanism for Stage 2 §12.

### Error contract

```json
{"error": {"code": "UPSTREAM_UNAVAILABLE", "source": "open-meteo",
           "message": "Forecast unavailable; showing cached data from 13:50.",
           "retryable": true}}
```

Every error names its source and says what the client may still trust. `4xx` for client mistakes,
`5xx` only for genuine server faults; upstream failures return **`200` with cached data plus a
`provenance.chip = "stale"`** where a cached answer exists, because a dated answer is more useful than
an error page during a flood.

---

## 7. Terrain — measured, and therefore downgraded

This is the section where the measurement changed the design.

**What was measured** (`research/terraincheck.py`, stdlib only, decoding raw SRTM `.hgt.gz`):

| Location | SRTM 30 m | Copernicus 90 m DSM | Delta |
|---|---|---|---|
| Cerro Santa Ana (Centro) | 14 m | 10 m | +4 |
| Norte / Sauces | 9 m | 7 m | +2 |
| Sur / Cisne II | 9 m | 7 m | +2 |
| Martha de Roldós | 7 m | 6 m | +1 |
| NW outskirts | 4 m | 3 m | +1 |
| Guayas estuary edge | 14 m | — | — |

**City-wide relief: 4–14 m.** The whole urban area occupies about ten metres of vertical space.

**Conclusions, stated plainly:**

1. **30 m SRTM is fetchable and usable**, so the brief's dataset is honoured rather than replaced
   (AWS `elevation-tiles-prod`, tiles named by SW corner — Guayaquil is in `S03W080`).
2. **30 m vs 90 m changes the answer by 1–4 m**, which sounds small but is 10–40 % of the entire local
   range. So resolution matters here more than it would in a hilly city.
3. **Neither dataset is a DTM.** SRTM in dense forest and Copernicus DSM both include canopy and
   structures, biasing upward exactly where people walk.
4. **Therefore elevation cannot rank streets by flood risk.** A 1 m difference between two adjacent
   cells is inside the error budget of both products.

**Design consequence — elevation is used for exactly three static things:**

| Use | Acceptable? |
|---|---|
| Displaying "this sector sits ~7 m above sea level" as context | Yes, labelled *estimated, SRTM 30 m* |
| Identifying the estuary-adjacent low band as a *vulnerability* attribute | Yes, as a coarse static flag |
| Ranking two streets by flood likelihood | **No.** Forbidden. |
| Predicting water depth on a street | **No.** Forbidden. |
| Live flood signal from terrain | **No.** Rainfall + sensors + reports lead. |

### 7.1 Documented limitations of both terrain products

| Property | SRTM 1-arcsec (used) | Copernicus GLO-90 DSM (rejected) |
|---|---|---|
| Nominal grid | 30 m (~1 arc-second), 3601×3601 per 1° tile | 90 m |
| Surface represented | **DSM-like**: canopy and structures bias values upward | **DSM** by definition: buildings, infrastructure, vegetation |
| Absolute vertical accuracy | ~16 m LE90 globally (varies; worse in steep or vegetated terrain) | ~4 m LE90 (better absolute accuracy, coarser grid) |
| Provenance date | Feb 2000 shuttle mission — pre-dates most of Guayaquil's recent construction | 2011–2015 TanDEM-X |
| Urban suitability | **Poor**: 30 m resolves street blocks, but canopy/structure bias and 2000-era surface defeat block-level inference | **Poor differently**: 90 m cannot resolve a street at all |
| Verdict for this project | Usable as coarse context only | Unusable for even that purpose at street scale |

**Both products share one disqualifying property:** their error is comparable to or larger than the city's
entire 10 m relief. Therefore neither may be used to differentiate neighbouring locations. This is
asserted as a **test**, not merely as prose — see §16 safety property `TERR-1`.

**UI labelling requirement:** any elevation figure rendered anywhere must carry the literal text
"approximate, SRTM 30 m" (or Spanish equivalent) adjacent to the number. A bare elevation value is a
defect. This is a testable string requirement (`TERR-2`).

Implementation: `scripts/sample_terrain.py` reads the SRTM tile once, samples each road segment's
midpoint, and stores `elevation_m` + `elevation_source`. It runs offline at seed time. No runtime
elevation API calls, no per-request cost, no licence question beyond attribution.

---

## 8. Flood-risk calculation

The risk level is a **transparent weighted score with a hard cap rule**, not a hydrological model. It is
deliberately simple because a hackathon cannot validate a hydrological model, and a complex one would
imply precision that does not exist.

### Inputs (each with a provenance chip)

| Input | Symbol | Source | Chip |
|---|---|---|---|
| Forecast rain, next 6 h | `R6` | Open-Meteo | estimated |
| Forecast rain, next 24 h | `R24` | Open-Meteo | estimated |
| Sensor depth vs threshold | `S` | simulated sensors | estimated + **simulated** |
| Sensor trend (m/h) | `T` | derived from readings | estimated |
| Verified incidents in sector (last 60 min) | `I` | citizen reports, verified | verified |
| Closed/affected road share | `C` | road_status | verified |
| Modelled discharge percentile | `Q` | GEOGloWS | estimated |
| Terrain context | `E` | SRTM 30 m | estimated, **static** |

### Formula

```
rain_score   = clamp01(max(R6/40, R24/80))                # 40 mm/6h, 80 mm/24h = full marks
sensor_score = clamp01(max(depth/threshold across nodes))
trend_bonus  = clamp01(max_rise_over_1h / 0.3) * 0.5      # 0.3 m/h = fast
report_score = clamp01(I / 5)
road_score   = clamp01(C)

score = 0.30*rain_score + 0.30*sensor_score + 0.15*trend_bonus
      + 0.15*report_score + 0.10*road_score              # weights sum to 1.0

# Elevation enters only as a static vulnerability multiplier on the threshold,
# never as a live term: a lower sector reaches "flooding" at a smaller depth.
effective_threshold = threshold_m * (1 + 0.15 * elevation_percentile_in_city)
```

**Level mapping** (hysteresis applied so a flickering sensor cannot flap the public banner):

| Level | Word | Score | Hysteresis (down-shift requires) |
|---|---|---|---|
| 1 | Watch | < 0.25 | — |
| 2 | Caution | 0.25–0.45 | score < 0.22 for 10 min |
| 3 | Alert | 0.45–0.70 | score < 0.42 for 10 min |
| 4 | Emergency | ≥ 0.70 | score < 0.66 for 10 min |

### Hard rules layered on top

1. **Sensor-staleness rule — REVISED 2026-10-25 (was: "cap the level at 2").** The previous cap was
   **unsafe** and has been withdrawn. See §8.4 for the worked arithmetic and the replacement. In short:
   missing evidence must never *lower* published risk. It raises stated uncertainty and triggers
   precautionary language, while genuine danger signals remain free to raise the level.
2. **Missing input is not zero.** Each missing input is excluded from the sum and **weights are
   renormalised**, with a visible note: "Risk based on 4 of 5 inputs (no sensor data)". Treating a
   dead sensor as 0.0 depth would silently lower the score — the exact failure mode the brief warns
   about.
3. **Every level ships with its reason line**, generated from the top two contributors:
   "Level 3 — Alert: 38 mm forecast in 6 h; sensor SIM-01 at 68 % of threshold."
4. **Operator override is recorded as a separate field**, with actor, reason, and expiry. The computed
   score continues to be stored so an override can be seen against what the data actually said.
5. **Uncertainty is stated, not hidden.** Below the reason line: "Confidence: medium — 4 sensors active,
   forecast single-model."

### 8.1 Missing-input renormalisation — the exact arithmetic

```python
PRESENT_INPUTS = {
  "rain":   (0.30, rain_score),
  "sensor": (0.30, sensor_score),
  "trend":  (0.15, trend_bonus),
  "report": (0.15, report_score),
  "road":   (0.10, road_score),
}

present = {k: (w, s) for k, (w, s) in PRESENT_INPUTS.items() if s is not None}
assert present, "no inputs -> level UNKNOWN, never a number"

w_total  = sum(w for w, _ in present.values())
score    = sum(w * s for w, s in present.values()) / w_total     # weights renormalise to 1.0
coverage = w_total                                              # 0.0..1.0, exposed to the UI
```

**Three guarantees this encodes:**

- `score` is never computed over a missing input treated as zero.
- Dropping an input **raises** the influence of the remaining ones rather than lowering the score —
  which is the honest direction during a partial outage.
- **`coverage` is returned as data** and drives *confidence and messaging*, **not** the numeric level.
  The earlier rule ("coverage < 0.6 ⇒ cap the level at 2") was **withdrawn as unsafe** — see §8.4.
  A missing input must never reduce published severity.
- **If no inputs are present at all**, the result is `level = None` rendered as **"Unable to assess"** —
  never Level 1. Silence must never be dressed as safety. (This is safety property `RISK-6`.)

> **Note on what `coverage` is and is not.** It is the sum of the weights of *available* inputs — a
> measure of how complete the evidence is. It is **not** a measure of danger, and it is deliberately
> not a multiplier, divisor or gate on severity. Conflating "we know little" with "things are fine" is
> the single most dangerous mistake available to this system.

### 8.2 Stale sensors cannot reassure — the asymmetry rule

There are two ways to be wrong about a sensor, and they are **not** symmetric:

| Situation | Treated as | Why |
|---|---|---|
| Sensor reports high water, then goes offline | **Retain its last reading for a bounded decay window, then mark stale** — never silently drop to zero | A rising-then-silent sensor is the most alarming pattern in flood monitoring, not the least |
| Sensor reports low water, then goes offline | **Excluded from the score**, flagged stale | A dead sensor must not contribute "0.05 m ⇒ safe" |
| All sensors stale | `sensor_score = None`, weights renormalise, **severity unaffected**; confidence drops to *low*, precautionary notice raised | Absence of evidence ≠ evidence of absence. Withdrawing a sensor must not withdraw a warning |
| Fresh reading contradicts a stale-high reading | Fresh wins for the score; the stale-high value and its age are shown beside it | The operator must see both; the public sees the fresh one plus a note |

**Explicit statement of the safety property** (`RISK-5`): *a transition from verified-low to unknown can
never lower the published level.* Losing information may hold the level, raise uncertainty, or escalate
precaution — never quietly reduce risk. This is directly from the brief's "do not treat a missing flood
report as evidence that a road is safe", applied to sensors.

### 8.3 What happens when signals conflict

Conflicts are normal in a flood (rain forecast but dry sensors; a citizen reports water where the sensor
sits high and dry). **The earlier wording here was unsafe and has been corrected:** it said the level is
"driven by the sensor, because it is the observation", which silently let one low sensor outvote heavy
forecast rain, verified reports and closed roads. Observations are generally stronger evidence than
forecasts — but "generally" cannot become "always" when the consequence of being wrong is someone
driving into floodwater.

**Corrected rule — three layers, in order:**

1. **The weighted score sees every input.** No input is discarded because another disagrees. The sensor's
   0.30 weight already expresses that observations are strong evidence; it is not given a veto.
2. **Precautionary floors can raise the level** (§8.4), so a credible danger signal is never outvoted by
   a single low reading.
3. **The disagreement is stated, never averaged away.** The output carries a conflict list; the UI shows
   it; the reason line names both sides.

| Conflict | Resolution | Why not the alternative |
|---|---|---|
| High rain forecast + low/falling sensors | Score reflects both; sensor weight dominates the arithmetic; **precaution floor ≥ 2** if the rain threshold is met. Copy: "Forecast suggests risk; sensors not yet responding" | Letting the sensor decide outright would hide an imminent hazard. Letting rain decide outright would ignore a real observation. Both are shown. |
| Low rain forecast + rising sensors | Score reflects both; rising sensor gives a strong `sensor_score` **plus `trend_bonus`**; forecast panel notes the model under-predicted | A rise is an observation and outranks a forecast in practice, but the forecast is still displayed as the reason it may worsen |
| Sensors high + no verified reports | Level from score; confidence downgraded; copy "no verified reports yet" | Reports are corroboration, not a requirement. Absence of reports is not evidence against a sensor. |
| Verified reports + low sensors | Reports raise `report_score`; **precaution floor ≥ 3** at 3+ recent verified reports; conflict shown in the Outlook factor list | Silently trusting the sensor would discard crowd evidence, which is often the *only* street-level signal available |
| INAMHI bulletin contradicts Open-Meteo | Both shown, verdict `Discrepant`, **never averaged** | An average of "heavy rain" and "no rain" describes neither |
| One low sensor among several high sensors | Outlier is **flagged and shown**, not averaged into oblivion; no single sensor can mask a cluster of high readings | Averaging a lone low value into a cluster of high values is the exact suppression path the review warned about |
| Operator override vs computed score | Both stored, both visible; public sees the override with author and time; **override can raise unimpeded and can only lower with a mandatory written justification** | Lowering published risk is the higher-consequence direction, so it gets friction |

**Principle:** the engine produces a level, a confidence, a disagreement list, and a reason line. It does
not resolve disagreement into a single confident voice. Averaging is prohibited wherever two sources
disagree.

**Explicit anti-suppression property** (`RISK-8b`): no single input may reduce the level below what the
remaining inputs alone would produce. Stated as a test, not a promise.

### 8.4 Severity vs. evidence coverage — the withdrawn cap and its replacement

**This section records a correction.** The earlier design said: if `coverage < 0.6`, cap the level at 2.
That rule was **unsafe** and is withdrawn. The arithmetic, run on the project's own weights:

```
All sensors stale (sensor + trend missing) => available weights = 0.30 + 0.15 + 0.10 = 0.55

rain 1.0, reports 1.0, roads 1.0   score 1.00  coverage 0.55
   uncapped: 4 Emergency   capped: 2 Caution        <-- SUPPRESSED
rain 1.0, reports 0.8, roads 0.8   score 0.91  coverage 0.55
   uncapped: 4 Emergency   capped: 2 Caution        <-- SUPPRESSED
```

Because losing the sensor and trend weights caps achievable coverage at **0.55 — permanently below the
0.6 threshold** — *every* scenario with fully stale sensors was capped at Caution, no matter how heavy
the forecast rain, how many verified reports, or how many closed roads. Worse, stale sensors often
coincide with the storm that damaged them. The rule let a hardware failure downgrade a genuine emergency,
and it was the exact inversion of the governing principle: a missing input was silently *lowering*
published risk.

**Replacement design — severity and confidence are separate outputs.**

```python
RiskResult(
    score: float | None,          # renormalised weighted score, or None if nothing usable
    level: int | None,            # 1..4 from score, or None -> "Unable to assess"
    coverage: float,              # sum of available weights, 0..1  -- EVIDENCE ONLY
    confidence: "high" | "medium" | "low",
    insufficient_evidence: bool,  # coverage < 0.6  -> messaging flag, NOT a level cap
    missing_inputs: list[str],
    precaution: int | None,       # floor level implied by a credible danger signal
    conflicts: list[Conflict],
    reasons: list[str],
    override: Override | None,
)

# SEVERITY: never reduced by missing evidence.
level = level_from_score(score)                    # if score is None -> None
level = max(level, precaution)                     # precaution may RAISE only (floor)

# CONFIDENCE: reduced by missing evidence, never by severity.
confidence = "high" if coverage >= 0.85 else "medium" if coverage >= 0.6 else "low"
insufficient_evidence = coverage < 0.6
```

**Precautionary floor — how a danger signal survives a sensor outage.** A *floor* can raise the level and
can never lower it. Its scope was **decided by the owner on 2026-10-25 (D23)** and is narrower than first
proposed:

| Signal present even with no sensor data | Precaution floor | Status |
|---|---|---|
| ≥ 3 verified reports in the last 60 min in the sector | **≥ 3** | **ACTIVE** — number provisional, unvalidated |
| Any road in the sector marked `closed` by an operator | **≥ 3** | **ACTIVE** — number provisional, unvalidated |
| Forecast rain reaching the heavy-rain threshold within 6 h | ~~≥ 2~~ | **DISABLED (D23)** — no defensible threshold or source exists. The 40 mm/6 h figure in the scoring formula is a **risk-scoring input, not an approved public warning threshold**. |
| Rain threshold **and** ≥ 3 reports / ≥ 1 closure | ~~≥ 3~~ | **DISABLED** — depends on the disabled rain trigger |

**Consequence for the public forecast UI:** until a sourced heavy-rain threshold is approved, the forecast
panel shows absolute millimetres and probability **without** a "heavy rain" label. This is the fallback
already mandated by Stage 1 §6 ("if no defensible threshold is available … **does not** invent a 'heavy
rain' label"). Tracked as blocker **B13** in `PHASES.md`.

**Everything in this table is provisional.** No measurement supports the ≥3 thresholds or the 60-minute
window; the false-alarm rate is unknown and untested. They are product judgement, recorded as such in
`docs/STAGE-3-DECISION-SUMMARY.md` §4a. What *is* principled is the **direction**: a floor may raise risk,
never lower it.

**What the user sees, and why both facts must appear.** "High risk, low confidence" is a legitimate and
important message; a single number cannot carry it:

> **⚠ Level 3 — Alert** · Confidence: **low** — no current sensor data
> Heavy rain forecast (38 mm in 6 h) and 4 verified flood reports. Sensors offline, so actual water
> depth is unknown.

This is materially more useful — and more honest — than showing Caution, which would have told a citizen
the opposite of what the available evidence says.

**Why not simply remove the cap and say nothing?** Because then a 30 %-coverage Emergency would look
identical to a 95 %-coverage Emergency. The fix is not to hide severity but to state confidence
separately. Risk of crying wolf is real and is handled by the confidence line plus the `PRECAUTION-*`
tests, not by suppressing the level.

**One case still caps nothing but changes the message entirely:** zero usable inputs ⇒ `level = None` ⇒
"Unable to assess", never Level 1 and never a confident figure (`RISK-6`).

### 8.5 Determinism

`domain/risk.py` is a pure function:

```python
def assess(inputs: RiskInputs, now: datetime, config: RiskConfig) -> RiskResult
```

No globals, no I/O, no implicit clock — `now` is injected, so hysteresis and staleness are testable at any
simulated instant. Same inputs + same `now` ⇒ byte-identical `RiskResult`. This is what makes §16's
deterministic test suite possible at all.

**What this model does not do**, and must never be described as doing: hydrological routing of water,
street-level depth prediction, drainage-capacity modelling, or return-period estimation.

---

## 9. Road graph and route avoidance

### Graph construction (`scripts/extract_graph.py`, run once)

- Overpass query over the demo bbox, highway classes as in `research/graphcheck.py`.
- **Measured basis:** 6,202 ways → 22,499 nodes, 27,435 segments, 1,184.9 km, **96.9 % in one connected
  component**, 32.8 % junctions, mean degree 2.44.
- Persist as a versioned artifact (`.graphml` or a compact adjacency `.npz` + node table) alongside the
  `timestamp_osm_base`, so the graph is reproducible and its vintage is displayable.
- Load into memory at startup; a 22k-node graph is trivial (tens of MB), so no Neo4j, no Postgres graph
  extension, no per-request Overpass.

### Route search (`app/routing/search.py`)

1. Snap origin/destination to nearest graph node. **If snap distance > 60 m, refuse and say so** —
   routing from a wrong origin is worse than no route (Stage 1 §9).
2. Apply per-edge cost factors. **Note the asymmetry:** three statuses are *penalised*, while one is
   *removed*. That difference is the whole safety argument (§9.3) and must not be flattened into a
   single "weight" list at implementation time.
   - `closed` → **edge removed from the phase-1 search graph** (not a weight — see §9.3)
   - `affected` → ×2.5
   - `unknown` → ×1.15 (a nudge, not a wall — unknown is not proof of hazard)
   - `stale` → ×1.1
3. **Run the two-phase search (§9.3), not a single weighted search.** Phase 1 on the closed-free graph;
   phase 2 only if phase 1 yields nothing, and its output is labelled `Hazard-crossing`.
4. Generate up to 3 alternatives via `shortest_path` then edge-penalty iteration (a simple
   k-shortest-paths substitute: run, penalise the used edges, rerun; cheap and adequate at this scale).
   Alternatives are generated **within a phase**, so a phase-2 route can never displace a phase-1 route.
5. Compute for each route:
   - `distance_m`, `duration_s` (labelled **estimated**, assuming unimpeded travel)
   - `hazards_avoided` count by class
   - **`coverage_pct`** = share of route length whose `road_status` is verified and inside its freshness
     window.
   - `phase` (`1` or `2`) and `classification` — carried in the response so the client cannot recompute
     a friendlier one.
6. **Return the coverage number as a first-class field.** Coverage drives the **Recommended /
   Not-recommended** boundary at 60 % (§9.1) — it is not a serve/don't-serve gate. Computed
   server-side and length-weighted so the client cannot style it away.
7. **Never cache route results.** Explicit non-feature: no memoisation, no route cache table, no ETag on
   route responses. A cached route is a stale hazard map. Status is read **fresh on every request** and
   the graph is never mutated with status (§12.4).

### 9.1 Route eligibility, rejection, and what the citizen is told

**Corrected 2026-10-25.** The previous table was internally contradictory: it made coverage < 60 % a
"rejection criterion", then permitted Marginal routes at 40–59 %, then allowed Unknown-status-only routes
at 0 % verified coverage to be served. Those cannot all be true. This section replaces them with one
policy built on **three independent facts** that were being conflated.

**The three facts, kept separate:**

| Fact | Question answered | Produced by |
|---|---|---|
| **Connectivity** | Does a path exist at all? | Graph search |
| **Hazard crossing** | Does the path contain a known closed road? | Phase used + edge statuses |
| **Verified coverage** `coverage_pct` | What share of route *length* carries fresh, verified status? | Length-weighted arithmetic, server-side |

A route is therefore described by a **pair** — (hazard class, coverage band) — not by a single threshold.
The earlier single-threshold design is what produced the contradiction.

**Coverage bands** (length-weighted, using only status that is verified *and* inside its freshness window):

| Band | `coverage_pct` | Meaning |
|---|---|---|
| **High** | ≥ 80 % | Most of the route is known |
| **Moderate** | 60 – 79 % | Majority known |
| **Low** | 1 – 59 % | Minority known |
| **None** | 0 % | Nothing about this route is verified |

**Hazard classes** (from §9.3's two-phase search):

| Class | Condition |
|---|---|
| **Clear** | From phase 1; no closed edge on path |
| **Hazard-crossing** | From phase 2 only; contains ≥ 1 closed edge |

**The complete policy — every combination, defined:**

| Hazard class | Coverage band | Served? | Recommended? | Public treatment |
|---|---|---|---|---|
| Clear | High (≥ 80 %) | Yes | **Yes** — rank 1 | Normal. "Avoids N known hazards · coverage 84 %" |
| Clear | Moderate (60–79 %) | Yes | Yes, rank 1 if no High exists | Normal, coverage shown |
| Clear | Low (1–59 %) | Yes | **No** — demoted below any Moderate+ route | "High uncertainty · coverage 42 %" + grey treatment, never first |
| Clear | None (0 %) | Yes | **No** — last among Clear routes | "Conditions on this route are unknown." Explicitly **not** a verified or safe route |
| Hazard-crossing | Any | Yes, **last of all** | **Never** | "No route avoids all closures. This route crosses a closed road." |
| — (disconnected or snap > 60 m) | — | **No route returned** | — | "Cannot calculate a route: [reason]" + nearest shelter + emergency numbers |

**Boundary behaviour, stated exactly** (so implementation cannot drift):

- `coverage_pct` comparisons are on the rounded, length-weighted value, and band edges are **inclusive at
  the bottom**: 80.0 ⇒ High; 79.99 ⇒ Moderate; 60.0 ⇒ Moderate; 59.99 ⇒ Low; 0.0 ⇒ None.
- **"Recommended" means rank 1 and normal visual weight.** A route may be *served* without being
  *recommended* — that distinction is the repair for the original contradiction, which had no middle
  state between "reject" and "recommend".
- **`unknown`-dominant routes are served, never recommended, and never described as verified.** Serving
  them is a deliberate product choice, decided 2026-10-25 (**D24**): refusing to show a route does not stop
  someone travelling, it only stops them seeing what *is* known. The honest middle is to show the route and
  label its ignorance. *(Note: the "30–40 % of segments unverified" figure used earlier in this project was
  never measured — see §9.4.)*
- If **every** available route is Low/None coverage, all are demoted and the response carries
  `best_available_is_uncertain: true`, so the client must lead with the uncertainty rather than a route.
- If **every** route is Hazard-crossing, `all_routes_hazard_crossing: true` and the warning replaces the
  route list header.

**What "rejection criterion" now means.** The earlier phrase was too blunt. The 60 % figure is retained,
but as the **Recommended / Not-recommended boundary** — not a serve/don't-serve gate. Nothing is refused
for low coverage alone; routes are refused only for **no path** or **snap > 60 m**.

> **RESOLVED 2026-10-25 → D24/D25.** The owner chose to **serve but never recommend** Low/None-coverage
> routes, with a prominent uncertainty warning, the actual coverage percentage and the unknown/stale status
> detail. Known closures remain excluded from ordinary eligible routes. The 60 % boundary is retained
> **provisionally** as a recommendation boundary (not a serve/withhold gate) and is documented as an
> **unvalidated product decision, not a measured safety threshold**. No document may claim it is
> empirically established.

**Ordering is a safety decision, not a UI preference:** all Clear routes before any Hazard-crossing route;
within Clear, higher coverage before lower; ties broken by duration. A Low-coverage route is never
presented as the recommendation even if it is shortest.

**Staleness affects coverage, not presentation only.** Status past its freshness window stops counting as
verified, so stale closures automatically push a route into a lower coverage band.

**Closed-edge handling, final.** The original "large finite penalty" is **withdrawn** — see §9.3 for the
counterexample that refutes it. Closed edges are removed in phase 1 and restored only in phase 2, where
the result is labelled `Hazard-crossing`. Removing the edge in phase 1 does not make the app say "no
route exists" when the truth is "the only route is flooded": phase 2 answers that case explicitly.

**Staleness affects eligibility, not just presentation.** If > 50 % of a route's length is beyond its
freshness window, the route is `Marginal` at best, because most of what justifies it has expired.

### 9.2 What "unknown" may and may not do

- `unknown` **nudges** (`×1.15`) — it does not bar. Unknown is not proof of hazard, and barring unknown
  roads would produce no routes at all wherever status coverage is thin. *(The "30–40 % unverified" figure
  cited in earlier drafts was never measured — see §9.4. The argument holds regardless of the exact
  number, but the number itself must not be quoted as evidence.)*
- `unknown` **does** lower `coverage_pct`, which is what ultimately demotes the route.
- A route may **never** be described as safe on the basis of a successful graph search. Success means
  "found a path", nothing more. The words "safe", "clear", "secure", and "flood-free" are banned from
  route copy; the permitted vocabulary is "no known hazards" plus the coverage figure. This is enforced
  as a lint rule over user-facing strings (`ROUTE-4`).

### 9.3 The closed-road guarantee — proven, not asserted

**This replaces the original design.** Stage 3 first said closed edges get "a large finite penalty".
The review asked for a demonstration that this cannot present a closed-crossing route as eligible.
It cannot be demonstrated, because **it is false**. `research/routing_invariant.py` refutes it:

```
Suite: 1201 graphs (1200 random incl. elongated 2x20 grids + 1 adversarial)
Invariant: a route crossing a CLOSED edge must never be served as Eligible

A. penalty only (finite x250)      invariant held 1200/1201   VIOLATIONS 1
B. two-phase edge filter           invariant held 1201/1201   VIOLATIONS 0
C. state-space lexicographic       invariant held 1201/1201   VIOLATIONS 0
```

**The adversarial counterexample, in full:**

```
Direct edge 0->1, base 0.05, status CLOSED   -> penalised cost 0.05 x 250 =  12.50
Open chain of 41 edges, base 6.0 each        -> cost              41 x 6.0  = 246.00

A. penalty only  -> cost  12.50  worst status: Hazard-crossing   <-- closed edge won
B. two-phase     -> cost 246.00  worst status: Eligible          (41 edges)
C. state-space   -> cost 246.00  worst status: Eligible          (41 edges)
```

A penalty is **scale-relative**. It is beaten whenever the cheapest closed-free detour costs more than
`penalty × closed_edge_base`. Real base costs are travel times spanning orders of magnitude, so no single
multiplier can be safe — and raising it does not help, because it must stay finite to keep the graph
solvable, and any finite value is beatable by a long enough detour.

**Adopted design: two-phase edge filter.**

```
Phase 1  Remove every CLOSED edge from the graph.
         Run Dijkstra with affected/unknown/stale penalties.
         If a path exists, it CONTAINS NO CLOSED EDGE — by construction, not by arithmetic.
         Classification: best achievable class given the edges on that path.

Phase 2  Only if Phase 1 finds nothing: search the FULL graph (closed edges restored).
         The result is classified Hazard-crossing and MUST carry the warning.
         This is the genuine "no dry route exists" case.
```

**Why this is provable where a penalty is not:** in phase 1 the closed edges are *absent*. There is no
cost comparison to argue about, so a closed-crossing result is not merely unlikely but unrepresentable.
The guarantee is structural rather than numerical — which is the only kind that survives someone later
tuning a weight.

**Public message must distinguish three genuinely different situations:**

| Situation | Classification | Public copy |
|---|---|---|
| A closed-free route exists | Eligible / Marginal / Unknown-only | "Avoids N known hazards · coverage 78 %" |
| No closed-free route exists, but the area is connected | **Hazard-crossing** | "No route avoids all closures. This route crosses a closed road." + route shown, explicitly flagged |
| Origin/destination not connected at all, or snap > 60 m | **Refused** | "Cannot calculate a route: [reason]" + nearest shelter + emergency numbers |

"Hazard-crossing" and "Refused" must never share copy, ordering, or visual treatment: the first means
*the only way out is flooded*, the second means *no path exists in the data*. Conflating them would tell
someone no route exists when in fact the route exists and is dangerous — the wrong decision either way.

**Complexity note:** Dijkstra on 22k nodes is milliseconds. No caching of route results is needed, and
none is added — cached routes are precisely how a newly closed road keeps being recommended (§12).

### 9.4 Figures used in this section that were never measured

Recorded because they appeared in earlier drafts and must not be cited as evidence:

| Figure | Where it appeared | Actual status |
|---|---|---|
| "30–40 % of segments may be unverified" | §9.1, §9.2, `STAGE-3-REVIEW-RESPONSE.md` | **Never measured.** The graph probe (`research/graphcheck.py`) measured connectivity (96.9 % one component), junction share and detour factor — **not** the share of segments carrying verified status. Treat as an unvalidated assumption. Measuring it requires running status-seeding over a demo sector, which has not been done. |
| Coverage bands 80 / 60 / 0 | §9.1 | **Product judgement** chosen for legibility. The 60 % boundary is retained **provisionally** under **D25** and is **not** a measured safety threshold. |
| The 60 % figure being "a rejection criterion" | earlier §9 route-search step 6 | **Withdrawn** — replaced by a recommendation boundary (D20/D25). |

Why this matters: an unmeasured percentage that sounds precise is exactly the kind of claim this project
has committed not to make. The **arguments** in §9.1–9.2 stand without it (serving beats hiding, because a
refused route does not stop travel); the **number** does not.

---

## 10. Sensor simulation and persistence

**Simulator** (`app/simulate/sensors.py`): deterministic, seeded, profile-driven.

| Profile | Behaviour |
|---|---|
| `dry` | baseline drift, no rise |
| `steady` | slow sinusoidal variation around a baseline |
| `heavy` | rise during forecast-heavy-rain hours, then slow recession |
| `surge` | steep rise to threshold and above, then plateau (for the demo climax) |

- The simulator reads the **actual Open-Meteo forecast** for the sector, so simulated water rises when
  real rain is forecast — the demo is internally coherent rather than scripted nonsense.
- `simulated = true` on every row, enforced by a **database default plus a NOT NULL constraint**, so a
  future real sensor insertion must explicitly opt out. The default protects the honest path.
- Determinism: same seed + same hour ⇒ same readings, so screenshots and rehearsals reproduce.

**Persistence:** a scheduler writes one reading per node per interval (default 60 s) into
`sensor_readings`; a retention job deletes rows older than 30 days. Health is **derived** from
`observed_at` cadence at query time (Stage 2 §6), never stored as a mutable flag that could go stale.

### 10.1 Data-mode indicator — LIVE / SIMULATED / MIXED

Approved Stage 2 §13 requires a non-dismissible mode banner, and Stage 3 must state how the server
produces it. It was absent from this document until now; recorded here as a gap closed.

The flag is **computed server-side per response**, never asserted by the client:

```python
mode = "SIMULATED" if sensors_simulated and not external_live \
       else "LIVE" if external_live and not sensors_simulated \
       else "MIXED"
```

| Mode | Condition | Appearance in this project |
|---|---|---|
| `LIVE` | All environmental data from real external sources, sensors real | **Never achievable here** — every sensor is simulated. Showing it would be a lie. |
| `SIMULATED` | Sensors simulated, no live external data | Occurs when Open-Meteo/GEOGloWS are unreachable and only seeded data renders |
| `MIXED` | Real external forecast + simulated sensors | **The normal state for this project** |

Rules:

- The mode is carried in the response envelope alongside `provenance.simulated`, so both public and admin
  read the same value from the same place (§12).
- Screenshot and CSV-export headers include the mode **and** the timestamp.
- `LIVE` is unreachable by construction. Because it is listed in the vocabulary for completeness, a test
  (`SIM-3`) asserts that seeding and simulation cannot produce it — an unreachable state that nobody
  guards is how a demo accidentally claims live sensor data.

---

## 11. Rainfall and river ingestion, and the INAMHI reality

### Open-Meteo (verified working)

- **Verified live 2026-10-25:** `precipitation` + `precipitation_probability`, 24 hourly values, units
  `mm` / `%`, `timezone=America/Guayaquil`.
- Server fetches on a schedule (every 15 min is ample; the model updates far less often), caches into
  `weather_cache` with **both** `fetched_at` and the upstream `model_run_at`. The UI shows both — a
  fresh fetch of an old model run is still old information, and that distinction is invisible unless
  displayed.
- Attribution `Open-Meteo (CC BY 4.0)` is rendered in the footer and in the forecast panel.
- **Licence caveat:** free for non-commercial use. A hackathon demo is plausibly non-commercial but this
  has not been confirmed with Open-Meteo's terms for commercial derivatives. Flagged, not resolved.
- Rate limits: no key, but self-throttled to one request per 15 min per location regardless.

### GEOGloWS (verified working, with one broken product)

- **Verified live 2026-10-25:**
  - `GET /api/v2/getriverid?lat=&lon=` → `{"river_id": 670068009}` for the Guayas at Guayaquil.
  - `GET /api/v2/forecastrecords/{river_id}` → CSV, `datetime,average_flow` (3-hourly).
  - `GET /api/v2/forecaststats/{river_id}` → CSV with `flow_max/75p/avg/med/25p/min` **at 3-hour
    intervals (120 rows)** and `high_res` at 1-hour intervals (240 rows, values only on the hour).
  - Measured flow range across the ensemble window: **5,050 → 8,844 m³/s**.
- **`GET /api/v2/returnperiods/{river_id}` returns HTTP 500** (`No variable named 'logpearson3'`). This
  is a server-side defect. **Consequence: no return-period / "1-in-N-year" language anywhere.** The
  Outlook shows absolute modelled discharge + the ensemble percentile band instead.
- **Parsing trap recorded:** the CSVs mix 3-hourly ensemble rows with hourly high-res rows, so naive
  row-by-row parsing produces near-duplicate values and apparent flatlines. The correct approach is to
  filter rows where the ensemble columns are non-empty. (This exact mistake was made and corrected
  during this review — hence it is written down.)
- Labelled in the UI as **"Estimated · modelled discharge"** with model run time. Never a measured level.

### INAMHI (no API — manual entry)

Products exist and are Guayaquil-specific (`Pronóstico Extendido Guayaquil-Durán`, `Boletín
Guayaquil-Durán`, `Alerta Temprana`, `Boletín Hidrológico`) but are published as portal bulletins.

**Integration:** an admin records `issued_at`, headline, and URL into `inamhi_bulletins`. The public
forecast panel shows it as *Reported · manual entry* with the bulletin's own issue date, visually
separate from the Open-Meteo chip.

**Observed caveat:** during review the portal rendered a "Pronóstico del día" widget dated **28 ago
2026**. Whether cached or stale, it demonstrates why the bulletin's own date — not the fetch date —
must be displayed.

**Legal:** no scraping. Manual entry only unless terms explicitly permit automated access.

---

## 12. Consistency: how the two interfaces cannot diverge

Architecture-level enforcement of the Stage 2 §12 contract:

1. **Single source of truth by schema.** `road_status` is keyed by `road_segment_id`; there is no
   parallel public table.
2. **Chip computed server-side** in the response envelope (§6) from `fetched_at` + `stale_after_s`.
3. **No caching of derived aggregates.** Risk level, road counts, and route coverage are computed per
   request from current rows. Deliberately: at demo scale the cost is negligible, and a stale aggregate
   is a correctness bug, not a performance win.
4. **Mutation invalidates by construction.** Because nothing derived is cached, a road flipping to
   `closed` is visible to the next request. The failure mode "route finder keeps using a closed road"
   therefore cannot arise from caching — only from in-memory graph state, which is why the graph stores
   *topology* and status is applied at query time (§9.2).
5. **Timestamps are event timestamps.** `set_at`, `published_at`, `reviewed_at` — never `updated_at`
   in public copy. An editable timestamp is a way to lie by accident.
6. **Integration test as the guard:** `tests/integration/test_consistency.py` asserts that an admin
   PATCH to a road changes the public `/map` AND the `/route` coverage figure within the same request
   cycle. This test is the contract's executable form and must exist before the contract is called
   satisfied.

---

## 13. Map tiles, OSM licensing, and external service limits

| Concern | Decision |
|---|---|
| Base tiles | **Do not** ship `tile.openstreetmap.org` in a demo that could be judged as production use — the OSM tile policy forbids heavy use. **Default decision: self-host a raster extract of the demo bbox**, which is small and defensible. A permitted third-party provider is the alternative. Open only as TQ1 for the *judged submission* URL, not for the demo. |
| Attribution | `© OpenStreetMap contributors` displayed on every map view, plus ODbL note in an about screen. |
| Data licence | ODbL: derived databases inherit share-alike. The graph artifact is a derived database, so it is redistributed under ODbL terms if published. |
| Overpass | **Extract once, never per request.** Public endpoint returned HTTP 406 without a User-Agent and throttles aggressively. |
| Open-Meteo | Self-throttled to 1 request / 15 min / location; cached server-side. |
| GEOGloWS | Fetch 3-hourly at most; cache; one river reach only. |
| SRTM | Public domain (NASA/USGS); AWS terrarium/skadi as delivery. Attribution is courteous and cheap. |
| Supabase | Free tier: 500 MB DB, 1 GB storage, 5 GB egress, **pauses after 1 week idle**. |

---

## 14. Authentication and authorization

- **Citizens:** no accounts. Reports are anonymous and tracked by an opaque `reporter_code`.
- **Admins:** Supabase Auth (email + password / magic link), JWT verified by FastAPI on every request.
- **Roles** in a `user_roles` table (not in the JWT claim alone, so revocation is immediate), enforced by
  FastAPI dependencies *and* by Postgres RLS as defence in depth.
- **RLS:** public read is allowed only on published, non-expired alerts and on non-sensitive tables.
  `incidents` exposes no photos of `pending` reports to the public. `audit_log` is **insert-only** for all
  roles; no role gets `UPDATE`/`DELETE`.
- **The service-role key never leaves the server.** No `SUPABASE_SERVICE_ROLE` in any frontend env var,
  ever. The anon key is public by design and is safe only because RLS is correct — which is why RLS is
  tested, not assumed.
- **MFA (TOTP)** for Publisher/Admin, per Stage 2 §2.
- **Rate limiting** on `POST /reports` (per IP + per device fingerprint) and on auth endpoints.

---

## 15. Internationalisation — English primary, Spanish secondary

**Policy (approved, D8):** **English is the primary UI language**; **Spanish is a complete secondary
locale** reachable by a visible EN/ES toggle. This is a deliberate product decision — the owner reads
English more comfortably — and it is **not** a contradiction to be reconciled away. It also does not
mean Spanish may be partial: the primary audience of a Guayaquil flood warning reads Spanish, so Spanish
safety content must be **complete, not best-effort**.

### 15.1 Behaviour

| Concern | Rule |
|---|---|
| Default locale | English, unless a stored preference or URL locale says otherwise |
| Toggle | Visible on every screen (persistent control), not buried in settings |
| Locale in URL | `/en/...` and `/es/...`; a shared link opens in the **sender's** locale |
| Public interface | Fully bilingual, EN and ES both complete |
| Admin interface | Fully bilingual, EN and ES both complete |
| Fallback | If an ES string is missing, **fall back to English and label it** — never render a blank or a raw key |
| Completeness gate | A locale file with missing keys **fails the build** (see `I18N-1`) |
| Storage | `i18n/en.json` authored first, `i18n/es.json` translated second, flat key namespaces (`public.home.*`, `admin.roads.*`, `route.copy.*`) |

### 15.2 Safety-critical content is strictly bilingual

Numbers and colours are language-neutral; words are not. The following must be complete in **both**
locales before they may render at all, and are covered by `I18N-2`:

- severity words (Watch/Caution/Alert/Emergency · Vigilancia/Precaución/Alerta/Emergencia)
- provenance chips (Verified/Reported/Estimated/Stale/No data · Verificado/Reportado/Estimado/Desactualizado/Sin dato)
- alert headline, body and instructions
- route classification and coverage copy
- "Unable to assess", "no known hazards", and every refusal reason
- emergency numbers and shelter status

**Rule:** an alert may not be published unless **both** languages are present (this is the Stage 2 publish
gate). If a real emergency requires publishing fast, the Publisher override records who published
monolingually and why, and the missing translation becomes a visible admin task — the override is logged,
not silent.

### 15.3 Locale-sensitive values

| Value | Rule |
|---|---|
| Dates / timestamps | Rendered in the active locale's format, **always with an explicit timezone offset** and an absolute time alongside any relative one |
| Numbers | Decimal separator follows locale (`4.2 km` EN / `4,2 km` ES) — via `Intl`, never hand-formatted |
| Units | **Metric only** (mm, m, km, m³/s). No unit conversion; Guayaquil uses metric and mixed units invite misreading |
| Severity | Word + numeral + shape + colour, so a locale error can never be the sole carrier of meaning |
| River discharge | Always suffixed "modelled" in both locales — "caudal modelado", never "medido" |

### 15.4 The conflict this review found

Stage 1 (approved) already states English-primary at §4 and §11 Q1, so **no approved requirement
conflicts** with the policy. However, Stage 1's *illustrative* strings were partly Spanish-first in the
mockup (tab labels, `RIESGO ACTUAL`, `AVISO NARANJA`, `Reportar inundación`, sample route rows, shelter
type names). Those have been corrected to English with Spanish shown alongside; the **behavioural
requirements are unchanged** and nothing in Stage 1 is reopened. Recorded as correction **C-4** in
`docs/STAGE-3-RECONCILIATION.md`.

---

## 16. Offline and low-network architecture

- **Service worker** caches: app shell, `en.json`/`es.json`, last `/dashboard`, `/forecast`, `/shelters`,
  and `/map` payloads — each with its original `fetched_at` preserved.
- **Stale rendering is a data property**, not a client guess: the cached response still carries its
  envelope, so the UI shows the true age offline.
- **Report queue** in IndexedDB, flushed on reconnect, with `capture_at` preserved so a queued report is
  not mistaken for a fresh one (Stage 1 §11).
- **Bundle discipline:** no icon library (inline the ~15 SVGs needed), no animation library, no web font,
  Leaflet **lazy-loaded** on first map interaction. Target: public first-load JS ≤ 120 KB gzipped
  excluding the map chunk — a target to be *measured* at Stage 5, not asserted now.
- **TanStack Query** for caching with explicit `staleTime` per resource, matching the server-side
  freshness budgets so the two never disagree.

---

## 17. Testing and quality gates

Every safety property carries a stable id so the test suite and this document can be cross-checked. These
are the properties that matter; ordinary UI tests are not listed here.

**Current count: 44 properties** across nine groups — `RISK` (14), `ROUTE` (13), `I18N` (4), `GEO` (4),
`TERR` (2), `SYNC` (3), `PROV` (2), `SIM` (3), `COST` (1). The set grew from 32 during the 2026-10-25
reconciliation, when the sensor-cap correction (§8.4), the coverage-policy repair (§9.1) and the new
language policy (§15) each required testable guarantees that did not previously exist.

### 17.1 Safety properties and their validating tests

| ID | Safety property | Test type | Test must assert |
|---|---|---|---|
| `RISK-1` | Every level 1–4 is reachable at its documented boundary | unit, deterministic | Exact boundary inputs ⇒ exact level; one unit either side ⇒ the adjacent level |
| `RISK-2` | Missing input renormalises weights, never sums as zero | unit | Dropping an input **raises** `w_total`-normalised influence; `score` changes by the renormalised formula, not by treating the value as 0 |
| `RISK-3` | All-sensor-stale **does not lower** the level; it lowers confidence | unit | 6/6 stale with high rain + reports ⇒ `level` equals or exceeds the same scenario with sensors present; `confidence == "low"`; `insufficient_evidence is True`; reason line names the cause. **Asserts the withdrawn cap is gone.** |
| `RISK-4` | `coverage < 0.6` affects **messages only**, never the level | unit | Same score with coverage 0.30 vs 0.95 ⇒ **identical `level`**; differing `confidence`; `insufficient_evidence` true only in the former |
| `RISK-4c` | Precautionary floor raises, never lowers | unit | 3 verified reports + 1 closed road, no sensors ⇒ `level >= 3`; assert the floor can never produce a value below `level_from_score(score)` |
| `RISK-4d` | **Rain floor trigger is disabled (D23)** | unit | Heavy rain present + no reports + no closures, sensors stale ⇒ level reflects **score only**; assert **no floor is applied from rain**, and the reason line contains no "heavy rain" warning claim |
| `RISK-5` | Verified-low → unknown **cannot** lower the published level | unit, monotonicity | For every pair of input sets where set B masks a subset of A's fields, `level(B) >= level(A)` |
| `RISK-6` | Zero usable inputs ⇒ `None` ("Unable to assess"), never level 1 | unit | Assert `level is None`; explicitly assert `level != 1` |
| `RISK-7` | Hysteresis prevents flapping | unit, time-injected | Oscillate score across a boundary at 1-minute intervals; level changes at most once per hold window |
| `RISK-8` | Conflicting signals are surfaced, never averaged | unit | High-rain + dry-sensor ⇒ reason contains the conflict marker; INAMHI-vs-Open-Meteo returns `Discrepant`, not a mean |
| `RISK-8b` | **No single input can suppress the level below what the others imply** | unit, property-based | For randomised input sets, removing any one input never lowers `level`; assert over ≥ 1,000 cases. Catches the "one low sensor outvotes everything" path. |
| `RISK-8c` | A sensor cannot veto the precautionary floor | unit | Sensor reading 0.0 with 3 verified reports + a closed road ⇒ floor still applies (`level >= 3`) |
| `RISK-9` | Operator override is stored separately and audited | integration | Computed score **and** override both persisted; audit row has actor + reason + expiry |
| `RISK-10` | Engine is pure and deterministic | unit, property-based | Same inputs + same `now` ⇒ byte-identical result across 1,000 randomised cases; no I/O monkeypatching needed |
| `ROUTE-1` | A closed edge is never in the first-ranked route | integration + adversarial fixture | Two-phase: assert phase-1 result contains no closed edge on the 41-edge adversarial graph; assert phase 2 is only reached when phase 1 fails |
| `ROUTE-1b` | The two-phase filter is chosen over a finite penalty | regression | Port `research/routing_invariant.py` as a test; assert the penalty design FAILS the adversarial case and the two-phase design PASSES it |
| `ROUTE-2` | Coverage arithmetic is correct and length-weighted | unit, hand-built 10-node graph | Known fixture: 4.2 km path, 1.8 km verified ⇒ `coverage_pct == 42.9` within tolerance; assert **length-weighted**, not edge-count |
| `ROUTE-2b` | Coverage band boundaries are exact | unit | 80.0 ⇒ High; 79.99 ⇒ Moderate; 60.0 ⇒ Moderate; 59.99 ⇒ Low; 0.0 ⇒ None |
| `ROUTE-2c` | Low/None-coverage routes are never recommended | unit | Build a graph where a 0 %-coverage route is shortest; assert it is **served but not rank 1**, and `recommended is False` |
| `ROUTE-2d` | Clear routes always outrank Hazard-crossing routes | unit | Mixture graph ⇒ every Clear route precedes every Hazard-crossing route regardless of duration |
| `ROUTE-3` | Status change immediately affects routing and coverage | integration | PATCH road → `/route` coverage decreases **in the same request cycle**; no cache to wait out |
| `ROUTE-4` | Banned vocabulary never reaches user-visible route copy | lint + unit | Scan all i18n strings for "safe/clear/secure/flood-free" in route namespace ⇒ zero matches; "no known hazards" required present |
| `ROUTE-5` | Snap > 60 m refuses rather than guesses | unit | Origin 61 m from nearest node ⇒ `Refused` with reason, **not** a route |
| `ROUTE-6` | Hazard-crossing routes are labelled and last | unit | When only closed-crossing paths exist, `all_routes_hazard_crossing is True` and each carries the flag |
| `ROUTE-7` | Stale-majority routes cannot be `Eligible` | unit | > 50 % beyond freshness ⇒ classification is at most `Marginal` |
| `TERR-1` | Elevation is never an input to level or route ranking | static analysis + unit | Import-graph assertion: `routing/` and the `score` computation may not read `elevation_m` except via the documented threshold modifier; attempted ranking raises |
| `TERR-2` | Every rendered elevation string carries the approximation label | unit, i18n snapshot | Any component rendering `elevation_m` includes "approximate, SRTM 30 m" |
| `SYNC-1` | Admin PATCH → public read consistency | integration | Road status change reflected in `/map` counts and `/route` coverage within one request |
| `SYNC-2` | Public timestamps are event timestamps, not edit times | integration | Editing an alert body does not change `published_at` exposed to the public |
| `SYNC-3` | `audit_log` rejects UPDATE and DELETE | integration, DB-level | Both operations raise for every role, including service role |
| `PROV-1` | Every public read carries a `provenance` envelope | contract | Response-schema assertion across all public endpoints; missing envelope fails |
| `PROV-2` | Chip state is computed server-side only | static analysis | Frontend may not compute staleness; assert no date arithmetic on `fetched_at` in `src/` |
| `GEO-1` | Mixed 3-hourly ensemble + hourly high-res rows parse correctly | unit, fixture CSV | Blank ensemble cells excluded; ensemble count == 120; hourly count == 240; units m³/s |
| `GEO-2` | No return-period claim anywhere | lint + unit | Grep i18n and API payloads for "return period / 1-in-N / recurrence" ⇒ zero |
| `GEO-3` | `returnperiods` failure degrades, not breaks | integration, mocked 500 | Outlook renders discharge + band, states the product is unavailable, no fake numbers |
| `GEO-4` | Modelled discharge is never labelled measured | lint | String assertion on "measured" co-occurring with GEOGloWS payload ⇒ zero |
| `SIM-1` | `simulated` defaults true at DB level | integration | Insert without the column ⇒ row has `simulated = true` |
| `SIM-2` | Simulator is deterministic | unit | Same seed + same hour ⇒ identical readings |
| `SIM-3` | `LIVE` mode is unreachable in this project | unit | Every constructed response yields `MIXED` or `SIMULATED`; assert `LIVE` never emitted from seeded/simulated state |
| `I18N-1` | Both locale files have identical key sets | build-time | `en.json` and `es.json` keys compare equal; any missing key fails the build |
| `I18N-2` | Safety-critical strings are complete in both locales | unit, snapshot | The §15.2 list (severity, chips, route copy, "Unable to assess", refusal reasons) has no empty ES value and no EN fallback marker |
| `I18N-3` | No Spanish-first string ships in the English locale | lint | English locale values contain no untranslated Spanish UI tokens from the banned list (e.g. "Reportar inundación", "Sin dato") |
| `I18N-4` | Numbers and dates use locale formatting, units stay metric | unit | `4.2 km` under `en`, `4,2 km` under `es`; both `mm`/`m³/s`; timestamps carry an offset |
| `COST-1` | No secret reaches the frontend bundle | build-time check | Grep the built `dist/` for service-role key pattern ⇒ zero |

### 17.2 Coverage policy

- `backend/app/domain/` — **100 % branch coverage required**, and coverage alone is insufficient: every
  row in §17.1's `RISK-*` set must exist as a named test. A covered line with no property assertion does
  not count as tested.
- Everything else — coverage reported, not enforced.
- Anti-goal recorded: `pytest --cov` reporting 100 % on `domain/` while a `RISK-*` property is missing
  must fail the gate. The properties are the contract; the percentage is a proxy.

### 17.3 Test layers

| Layer | What | Gate |
|---|---|---|
| Unit (no I/O) | `risk.py`, `trend.py`, `priority.py`, `provenance.py`, `search.py` classification | Must pass; `domain/` at 100 % branch |
| Property-based | `RISK-5` monotonicity, `RISK-10` determinism over randomised inputs | Must pass |
| Integration | `SYNC-*`, `ROUTE-3`, RLS denials, report validation | Must pass before UI work is called done |
| Contract | `PROV-1`, response envelopes, error shapes | Schema-asserted |
| Static analysis | `TERR-1`, `PROV-2`, `COST-1`, banned vocabulary | CI-level, fails the build |
| E2E (scripted manual) | Demo scenario at mobile viewport on a throttled connection | Rehearsed before the pitch |
| Accessibility | Keyboard traversal, contrast, screen-reader pass on the alert ribbon | No severity by colour alone |

### 17.4 Not tested — and admitted

Hydrological correctness (there is no hydrological model), real sensor behaviour (all simulated),
municipal shelter authority, OSM completeness outside the sampled bbox, and behaviour under genuine
concurrent load.

---

## 18. Environment variables, dependencies, costs

### Environment variables (names only — values never committed)

```
SUPABASE_URL
SUPABASE_ANON_KEY            # frontend
SUPABASE_SERVICE_ROLE_KEY    # backend only, never shipped to the browser
DATABASE_URL                 # optional, for direct asyncpg access
OPEN_METEO_BASE_URL
GEOGLOWS_BASE_URL
GEOGLOWS_RIVER_ID
DEMO_SEED
SIM_PROFILE
TILE_PROVIDER_URL
SENTRY_DSN                   # optional
```

`.env.example` holds these names with empty values. `.gitignore` must exclude `.env*` before any real
value exists.

### Dependencies — exact pins, validated without installing

**Target interpreter: Python 3.14.8** (measured on this machine). All pins below were resolved from PyPI
metadata on 2026-10-25 and checked for a Python 3.14 / manylinux x86_64 install path. **No package was
installed** — installing is Stage 5 work, and approval has not yet been given.

`backend/requirements.txt` (proposed):

```
fastapi==0.162.0
uvicorn[standard]==0.54.0
pydantic==2.14.1            # pulls pydantic-core==2.50.1 (31 cp314 wheels)
pydantic-settings==2.16.1
httpx==0.28.1
networkx==3.7
numpy==2.5.4
supabase==2.33.0
pyjwt==2.15.1
python-multipart==0.0.32
pytest==9.1.1
pytest-asyncio==1.4.0
```

**Wheel-availability audit (2026-10-25):**

| Package | Pin | Install path on 3.14 |
|---|---|---|
| fastapi | 0.162.0 | pure-python |
| uvicorn | 0.54.0 | pure-python |
| pydantic | 2.14.1 | pure-python (+ pydantic-core 2.50.1, cp314 wheels present) |
| pydantic-settings | 2.16.1 | pure-python |
| httpx | 0.28.1 | pure-python |
| networkx | 3.7 | pure-python |
| numpy | 2.5.4 | cp314 manylinux x86_64 wheels present |
| supabase | 2.33.0 | pure-python |
| pyjwt | 2.15.1 | pure-python |
| python-multipart | 0.0.32 | pure-python |
| pytest | 9.1.1 | pure-python |
| pytest-asyncio | 1.4.0 | pure-python |

**`uvicorn[standard]` compiled extras, all with cp314 linux wheels:** uvloop 0.23.0, httptools 0.9.0,
watchfiles 1.3.0, websockets 17.3. So `[standard]` has an install path on 3.14; it was the main 3.14
risk. This is PyPI metadata evidence (E1) — installation itself is unproven until M0 runs.

**One metadata detail worth recording:** `networkx 3.7` declares `requires_python = !=3.14.1,>=3.12` —
it excludes only 3.14.1 specifically. 3.14.8 satisfies it. If the interpreter is ever pinned to exactly
3.14.1, installation will fail with an apparently unrelated resolver error.

**Frontend pins (npm, latest as of 2026-10-25):** react 19.3.1 · react-dom 19.3.1 · vite 8.3.5 ·
typescript 7.0.2 · react-router-dom 7.18.4 · @tanstack/react-query 5.104.5 · leaflet 1.9.4 ·
react-leaflet 5.0.0 · vitest 5.0.5. Vite 8 and TypeScript 7 are recent majors; if they collide at
Stage 5, pin down one major rather than swapping tools.

**Reproducibility procedure (Stage 5, requires approval):**

1. `python3 -m venv .venv` — note `pip` is **not** on PATH here; bootstrap with `python3 -m ensurepip`.
2. `pip install -r backend/requirements.txt` into the venv.
3. Smoke test: `python -c "import fastapi, networkx, numpy, pydantic"` and `uvicorn --version`.
4. `npm ci` in `frontend/`, then `npm run build`.
5. Record the resolved `pip freeze` and `package-lock.json` — the *resolved* set is the real pin.

**Fallback, pre-agreed:** if 3.14 causes failures, create the venv with **Python 3.13** and keep every
library pin unchanged. Verified: all listed pins declare `requires_python` compatible with 3.13. Do not
swap a library to fix an interpreter problem.

### Costs — verified terms, and explicitly not a guarantee

| Service | Published free-tier terms (verified 2026-10-25) | Risk to the demo |
|---|---|---|
| Supabase | 500 MB DB, 1 GB storage, 5 GB egress; **pauses after 1 week of inactivity**; 2 active projects | Paused project on demo day = broken app |
| Render (web service) | Free web services **spin down after 15 min without inbound traffic** and take **~1 minute** to spin up; **750 free instance-hours/month**; ephemeral filesystem; free Postgres **expires 30 days after creation** | Cold start of ~60 s on the first request of the pitch |
| Vercel (static) | Free tier for static hosting, with documented per-plan request limits | Low, for static assets only |
| Open-Meteo | Free for non-commercial use; paid plans otherwise | Licence question unresolved (TQ2) |
| GEOGloWS | Free, no documented SLA | Endpoint already returning HTTP 500 on one product |
| OSM tiles | Free but policy-limited | Would be a terms violation under load |

**The $0 figure is a description of current published terms, not a guarantee.** Specifically:

- No free tier provides an availability commitment. **No uptime claim is made or implied.**
- The owner has chosen to **demo from the internet** (2026-10-25), which accepts the Render cold start
  and the Supabase pause risk. The mitigations in §17.1 are therefore mandatory, not optional.
- Terms can change mid-event; a re-check before the pitch is a required step, not diligence theatre.

### 18.1 Degradation behaviour — every service failure has a defined response

| Failure | Detected by | Public behaviour | Admin behaviour |
|---|---|---|---|
| Supabase project **paused** | Connection error / 5xx on startup | Static shell + cached payloads render, banner: "Service unavailable — showing data from <time>" | Same, with an explicit banner naming the cause and a re-wake instruction |
| **Backend cold start** | Request > 3 s | Skeleton with source label, then the response; **never an infinite spinner**; cached payload after 10 s | Same |
| **Open-Meteo timeout / 5xx** | 5 s HTTP timeout | Last cached forecast, chip **Stale**, absolute age shown, forecast panel says the source is unreachable | Same + retry button |
| Open-Meteo **rate-limited (429)** | status code | Cached data, `Stale`; ingestion backs off exponentially | Banner on ingestion health |
| **GEOGloWS 500** (already observed) | status code | River line omitted with "modelled discharge unavailable"; **no substitute number** | Same |
| **GEOGloWS timeout** | 8 s | Same as above | Same |
| **OSM tile failure** | tile error events | Map region replaced by the text list of findings (Stage 1 §7) | Same |
| **Supabase egress limit hit** | 429 from PostgREST | Cached-only mode, banner | Banner |
| **Report upload fails** | network error | Queued locally with "queued" state, retried | n/a |
| **Clock skew** | server vs client delta > 60 s | Timestamps shown from server values only; relative ages computed server-side | Same |

**Rules that make this honest rather than optimistic:**

1. **Every degraded state names its source and its age.** No silent fallback.
2. **No fabricated substitute** for a missing source — the line is omitted, not estimated.
3. **`/api/health` is public** and reports each dependency's last-success timestamp, so the demo can be
   checked before going on stage rather than discovered on it.
4. **A pre-pitch warm-up request is a required demo step** (Render cold start), documented in the demo
   runbook at Stage 4.

---

## 19. Assumptions

1. One city, one tenant, one demo bounding box (~10 × 8 km central Guayaquil).
2. All sensors simulated; `simulated` defaults to true at the database level.
3. No external alert dispatch — ever claimed.
4. River data is modelled, labelled as such, and never converted into a return period.
5. Terrain is static context only (§7).
6. Report photos are compressed client-side and pruned; no PII retained.
7. Admin console is desktop-first; mobile is read-only.
8. The graph is extracted once at build/seed time and versioned.
9. Python may need to drop to 3.13 if 3.14 causes trouble; the stack itself does not change.
10. The demo will be rehearsed on a throttled connection, because that is the intended user's reality.

---

## 20. Open questions

| # | Question | Impact |
|---|---|---|
| TQ1 | Which tile source for the demo — self-hosted bbox extract, or a provider with a permitting free tier? | Legal exposure of the demo; also a fetch/caching task in Stage 5. |
| TQ2 | Is the hackathon judged non-commercial for Open-Meteo's licence? | Determines whether the free endpoint may be used at all, and whether a paid plan is needed. |
| TQ3 | Which sectors exactly, and how many (5–8 proposed)? | Seeds sensors, shelters, risk zones, and the demo script. Outstanding from Stage 1 Q3. |
| TQ4 | Do you want pytest unit tests for the risk engine before any UI, or UI-first and tests after? | I recommend tests-first for `domain/`, because that is where silent wrongness costs lives. |
| TQ5 | ~~Is a backend cold start acceptable in the pitch, or should the demo run fully local?~~ | **CLOSED 2026-10-25: owner chose to demo from the internet.** Risk accepted; §18.1 mitigations (pre-pitch warm-up, Supabase re-wake, `/api/health` check) are therefore mandatory runbook steps. |
| TQ6 | Photo retention policy (Stage 1 Q7, still open) | Affects storage budget, privacy copy, and the pruning job. |
| **B13** | **No defensible "heavy rain" threshold exists** — what value in mm/h, sourced from where? | **Partially blocking.** Per **D23** the heavy-rain floor trigger is disabled and the forecast UI omits any "heavy rain" label. Resolving this needs an INAMHI advisory tier or other documented source; until then the feature is simply absent, which is the honest state. Does **not** block Stage 3 approval. |

**Resolved in this stage (kept for the record):** the six O-1…O-6 decisions are closed as D23–D28.

---

## 21. Approval request

This document specifies architecture and directory structure, frontend organisation, every API endpoint,
the data model with relationships, authentication and authorization including RLS, sensor simulation and
persistence, rainfall and river ingestion with live-verified endpoints, terrain processing and its
measured limitations, the risk calculation with its honesty rules, graph construction and route
avoidance with the coverage metric, tile and licensing decisions, testing strategy, and environment
variables, dependencies, limits and costs — as the brief requires.

No code has been written, no dependency installed, no schema applied, and no Git operation performed.

**Approve Stage 3 and I will present Stage 4: Other Requirements and Implementation Plan.**

> **APPROVED 2026-10-26.** The owner approved this stage on the reconciled decisions D23–D28. Stage 4 has
> been presented at `docs/STAGE-4-REQUIREMENTS-PLAN.md`. Nothing in this document is reopened; changes
> would require a new approval.

**Still unvalidated, by design, and not to be described otherwise:** the risk weights, the precaution-floor
numbers, the 60 % coverage boundary, the "heavy rain" threshold (undefined — B13), and the prototype
sensor thresholds. See `docs/STAGE-3-DECISION-SUMMARY.md` §4a for the register and
`docs/EVIDENCE-STATUS.md` for what has actually been executed.
