# Data Sources — Verification Notes

**Status:** research note, 2026-10-25. Not a commitment; every entry states exactly what was and was
not verified. Nothing here has been integrated, called from application code, or load-tested.

Purpose: the brief forbids inventing data and requires data-quality honesty. This file records what
can honestly be claimed about each source *before* any code is written.

Legend for **Verified**: ✅ confirmed by reading the source's own documentation/portal during this
review · ⚠️ partially confirmed or with a material caveat · ❌ could not verify.

---

## 1. Rainfall — Open-Meteo Forecast API

| | |
|---|---|
| **Endpoint** | `https://api.open-meteo.com/v1/forecast` |
| **Variables** | `precipitation`, `precipitation_probability`, `rain`, `showers` (hourly) |
| **Horizon** | up to 16 days; hourly resolution |
| **Auth** | none — no API key required |
| **Licence** | data CC BY 4.0; free for non-commercial use; attribution required |
| **Verified** | ✅ documented **and called live on 2026-10-25** |

**Live call result** (Guayaquil, `-2.17, -79.92`, 1 day, `timezone=America/Guayaquil`):
HTTP 200, both variables returned 24 hourly values, units `mm` and `%`. Sample precipitation
`[1.7, 2.2, 1.6, 2.0, 3.6, 0.3]` with probability `[92, 90, 93, 99, 100, 92]`. The integration shape is
confirmed; the values are real forecast output at that time and must not be reused as demo fixtures
without re-fetching.

**Caveats to carry into the UI**

- The docs state that for precise quantities such as precipitation, *local measurements are preferable
  when available*. Guayaquil has local gauges (INAMHI, ESPOL). Open-Meteo is a gridded model product,
  not a rain gauge.
- `precipitation_probability` is a model/ensemble-derived probability, not an official warning. It
  must never be rendered as "INAMHI says X %".
- Attribution string required in the UI: *Open-Meteo.com (CC BY 4.0)*.
- Commercial use needs a paid plan. Judge whether a hackathon demo counts as non-commercial; do not
  assume.

---

## 2. Elevation — Open-Meteo Elevation API

| | |
|---|---|
| **Endpoint** | `https://api.open-meteo.com/v1/elevation` |
| **Dataset** | **Copernicus DEM 2021 GLO-90, 90 m resolution** |
| **Form** | Digital Surface Model (DSM) — includes buildings and vegetation, not bare terrain |
| **Verified** | ✅ documented, **and called live on 2026-10-25** |
| **Limit** | up to 100 coordinates per request |

**Live call result** — six points from the centre to the northern suburbs returned
`[10.0, 8.0, 7.0, 7.0, 6.0, 3.0]` metres. This is the single most important number in the whole
project: **central Guayaquil sits roughly 3–10 m above sea level across ~10 km.** There is no hillside
to climb to; a 7 m neighbourhood and a 6 m neighbourhood differ by one metre. Any elevation-based flood
reasoning has to operate inside a 1–3 m band, which is exactly the band a 90 m DSM cannot resolve and a
90 m DSM *with buildings in it* actively corrupts.

**This contradicts the brief's "SRTM 30 m".** Two separate problems, both material to routing:

1. **Resolution.** 90 m ≫ a street width. A single cell spans several blocks; local depressions that
   actually collect water are invisible.
2. **DSM, not DTM.** It measures the top of buildings and canopy. In a dense city that biases
   elevation *upward* wherever there is structure, which is exactly where people walk.

Whatever is chosen must be labelled in the UI as coarse terrain context, never as street-level depth.
If 30 m is required, a separate DEM must be sourced and its licence checked.

---

## 3. Tides — INOCAR

| | |
|---|---|
| **Content** | Ecuadorian tide tables/predictions, Guayaquil included |
| **Verified** | ⚠️ existence confirmed; **programmatic access not verified**; no documented public REST API found during this review |
| **Legal** | terms of use not reviewed — do not scrape |

**Classification: astronomical prediction, not observation.** Guayaquil's tidal range is large
(~3.9 m at springs), so tide genuinely modulates drainage outfall, but a predicted tide is *not* a
measured river level and must never be displayed as one.

---

## 4. River / streamflow — GEOGloWS ECMWF

| | |
|---|---|
| **Content** | global modelled streamflow forecast, 10-day horizon, ~3-hour interval |
| **Access** | REST API service documented at `geoglows.ecmwf.int`; training docs at `training.geoglows.org` |
| **Verified** | ⚠️ API existence stated on the project's own site; response schema and per-reach retrieval **not** tested |
| **INAMHI link** | INAMHI's own portal exposes a "GeoGlows" menu entry — i.e. the national service already points at this model |

**Classification: hydrological *model output*, not a gauge observation.** This is the closest thing to
a river signal that is openly reachable, and it is still a model. If used, it is an **Estimado** chip
with the model name and run time, and it does not satisfy "measured water level".

It may, however, be a defensible *substitute for a measured river level* in the Outlook, provided the
UI says "caudal modelado (GEOGloWS/ECMWF)", not "nivel del río medido". Decide at Stage 3.

---

## 5. Official meteorology — INAMHI

**What actually exists (verified by reading the portal's own navigation):**

- `Pronóstico Extendido Guayaquil-Durán` — Guayaquil/Durán-specific extended forecast
- `Boletín Guayaquil-Durán`, `Boletín Climático Mensual Guayaquil-Durán`
- `Alerta Temprana` (early warning) and `Alerta Corto Plazo Zona Sur`
- `Boletín Hidrológico` (hydrological bulletin)
- `Pronóstico Guayas-Galápagos`, `Pronóstico Nacional`
- `Visor Hidrometeorológico`, `Monitor de Sequía`, `GeoGlows`

**This is excellent news for the cross-check:** there *is* a Guayaquil-specific INAMHI product, so the
"concordante / discrepante" comparison has something real to compare against.

**The problem:** these are published as **web portal bulletins (documents/pages), not a documented
public REST API.** Verified: no API documentation was found on the portal.

**Therefore the only honest integration is:**

- Admin opens the bulletin and records its headline manually (rain window, level, bulletin ID, issue
  time) → stored with a source URL and an *editor-entered* timestamp.
- The UI shows it as *INAMHI (boletín, ingreso manual)* with the bulletin's issue time — distinct from
  the machine-fetched Open-Meteo chip.
- **No scraping** unless terms explicitly permit it. No automated "INAMHI agrees ✅" claim.

**Freshness caveat:** at fetch time on 2026-10-25 the portal's "Pronóstico del día" widget rendered
**28 ago 2026**. Either the page was cached or the widget is stale. Do not assume that portal content
is current; always display the bulletin's own issue date.

---

## 6. Roads and POIs — OpenStreetMap

| | |
|---|---|
| **Data** | road network, hospitals, fire/police stations, potential shelters |
| **Licence** | ODbL — attribution "© OpenStreetMap contributors" required, share-alike on derived DB |
| **Tiles** | `tile.openstreetmap.org` **usage policy forbids heavy/production use**; a demo may be borderline. Alternatives: self-host, or a permitted provider |
| **Verified** | ✅ **road-graph routability measured on 2026-10-25** (see below); tile policy is well-established |

### 6a. Routability — measured, not assumed

A feasibility probe (`research/graphcheck.py`, not application code) queried Overpass for central
Guayaquil, bbox `-2.23,-79.93` to `-2.14,-79.86` (~10 × 8 km), highway classes
motorway/trunk/primary/secondary/tertiary/residential/unclassified/living_street:

| Metric | Result |
|---|---|
| OSM data timestamp | 2026-10-25T17:27:26Z |
| Ways returned | 6,202 |
| Graph nodes | 22,499 |
| Undirected segments | 27,435 |
| Total network length | **1,184.9 km** |
| Segments missing coordinates | 0 |
| Connected components | 12 |
| **Largest component** | **21,803 nodes = 96.9 %** |
| Second largest | 333 nodes |
| Junctions (degree ≥ 3) | 7,381 = 32.8 % |
| Mean degree | 2.44 |
| Route test (BFS) | 11.86 km straight line → **15.90 km network, 318 nodes, detour 1.34×** |

**Conclusion: the network is routable.** A 1.34× detour factor is realistic for a gridded city, so
paths are following real streets rather than teleporting. The route finder is technically viable, and
B7 is resolved.

**Caveats that survive this result**

- **Coverage is measured for central Guayaquil only.** Peripheral and low-income districts (where
  flooding is worst) were not sampled and are commonly thinner in OSM. Must be measured per demo sector
  before promising routing there.
- **Connectivity ≠ correctness for routing.** One-way restrictions, turn restrictions, barriers, gated
  communities and access tags were not evaluated. A hackathon route finder can ignore them only if the
  UI does not claim road-legal navigation.
- **Overpass is a public shared resource.** It rejects requests without a User-Agent (HTTP 406) and
  rate-limits aggressively. Extract once, cache locally, never query per user request.
- **Extraction is versioned data, not live conditions.** `timestamp_osm_base` must be displayed.

**Shelters must not be auto-derived from OSM POIs and called "verified safe zones".** The brief
requires *verified designated* safe zones — an authoritative municipal/civil-defence list, or
admin-curated records labelled as app-managed. A coliseum in OSM is not a designated shelter.

---

## 7. Event requirements — HACK2IMPACT 2026

| | |
|---|---|
| **Handbook** | ❌ **not found.** No handbook, rulebook, or judging rubric for "HACK2IMPACT 2026 / Nu Zeta Track 1" was located. |
| **Consequence** | Stage 4 must not claim compliance with event requirements beyond those stated in the brief. |

**Trap to avoid — a plausible false match.** Searching surfaced *HackTech El Niño 2026: Tech for
Climate Resilience*, an IEEE Region 9 / RS LAC 2026 hackathon (28 Aug – 5 Sep 2026, registrations
closed), whose **Track 1** is "Telecommunications & Early Warning Systems in Crisis" and mentions heavy
rainfall and flooding. It is **not** HACK2IMPACT 2026 and its track is not named "Nu Zeta Track 1".

It must **not** be used as the source of truth for this project. If the brief's event is separate, its
rules are unknown. Note that this IEEE event also maps well onto Guaradar's problem space — which makes
the confusion easy and the discipline necessary.

If the two events are in fact related, the user must say so; requirements will not be inferred.

---

## 8. Summary — what can be claimed today

| Claim | Status |
|---|---|
| Hourly rainfall + probability are obtainable free with attribution | ✅ can claim |
| Elevation is available at 90 m DSM, not 30 m | ✅ can claim (and must, given the brief says SRTM 30) |
| Guayaquil's central districts lie at only ~3–10 m elevation | ✅ can claim — measured live across six points |
| Hourly rainfall + probability integration shape works | ✅ can claim — HTTP 200, 24 values, correct units |
| Central Guayaquil's OSM road graph is routable | ✅ can claim — 96.9 % in one component, 1.34× detour on a test route |
| Tide *predictions* for Guayaquil exist | ✅ can claim (as prediction) |
| A measured Guayas river level is available to this app | ❌ cannot claim |
| Modelled streamflow (GEOGloWS) is reachable | ⚠️ plausible, untested |
| INAMHI publishes Guayaquil-specific forecasts and warnings | ✅ can claim |
| INAMHI exposes a public API | ❌ cannot claim — manual entry only |
| OSM has a complete, routable Guayaquil road graph | ✅ routable in the central bbox; **peripheral districts unmeasured** |
| Designated shelters exist as an authoritative dataset | ❌ not found — must be curated |
| Official HACK2IMPACT 2026 requirements are known | ❌ unknown |

**Nothing above is verified beyond what is stated.** Rainfall, elevation and road-graph findings were
verified by live calls on 2026-10-25. Tide, streamflow and INAMHI remain documentation-only readings —
no code has been written, and nothing has been integrated into an application.
