# Guaradar — Stage 1: Public Safety Portal

**Status:** APPROVED 2026-10-25
**Scope of this document:** the citizen-facing interface only.
**Out of scope (by instruction):** admin interface, technology architecture, remaining requirements, any implementation or code.
**Date:** 2026-10-25
**Language decision:** English is the primary UI language; Spanish is the secondary locale (owner, 2026-10-25).

---

## 0. What this document is

A behavioural specification of the public interface: layout, navigation, components, interactions,
responsive behaviour, and the data each screen needs. It fixes **what the citizen sees and how each
element behaves**. It deliberately does not fix the risk formula, the road-graph algorithm, or the
schema — those are Stage 3.

Two constraints shape every decision below:

> **Live-verified 2026-10-25:** six sample points across central-to-northern Guayaquil returned
> elevations of **3–10 m**. The city has no meaningful vertical relief; neighbourhoods that flood and
> neighbourhoods that do not can differ by a single metre. On 19 Oct 2026 the city recorded ~216 mm in a
> day and 70+ neighbourhoods flooded, with ~26 sectors already pre-identified as flood-prone (Sauces 6,
> Samanes, Martha de Roldós among them). Flatness plus rainfall is the whole mechanism — a 90 m DSM errs
> by more than the entire local elevation range, so the app must lean on sensors, reports and rainfall,
> not terrain.
> The app must work on a mid-range Android phone on a congested network, in the rain, possibly at
> night, possibly with one bar of signal.

---

## 1. Design principles

| # | Principle | What it means in the UI |
|---|---|---|
| 1 | **Answer first, evidence second** | The top of Home states one risk level in words plus a number. Detail lives one tap below. |
| 2 | **Never imply certainty we do not have** | Every data-bearing element carries a provenance chip (§3). "No reports" is never rendered as "safe". |
| 3 | **Severity is never colour alone** | Each level has its own numeral, icon shape, and word. Colour is the fourth signal, not the first. |
| 4 | **Legible in bad conditions** | Minimum 16 px body text, ≥44 px targets, contrast ≥4.5:1, no thin-light typography, no motion required to read anything. |
| 5 | **Cheap to load, honest when stale** | Text and numbers render before any map. Stale data stays visible but is visibly dated, never silently refreshed-looking. |
| 6 | **Citizens self-serve distribution** | Every alert and every route has a share link, because the real distribution channel here is WhatsApp. |

---

## 2. Home: the "now" screen

The homepage is the Safety Dashboard. It is a single column, top to bottom, in priority order.
Nothing on it is decorative.

```
┌──────────────────────────────────────┐
│ Guaradar           Guayaquil · Norte │  app bar, 56 px
├──────────────────────────────────────┤
│ ⚠ ORANGE ALERT · Heavy rain          │  alert ribbon — only when an
│   22:00–04:00 · 12 min ago         → │  alert is active
├──────────────────────────────────────┤
│ CURRENT RISK                         │
│  ❸  Level 3 — Alert                  │  risk card (hero)
│  125 mm forecast in 6 h              │
│  3 roads closed · 1 sensor rising    │
│  ▁▂▃▅▅▄▃▂  next 24 h                 │
│  Sources: Open-Meteo · INAMHI ✓      │
├──────────────────────────────────────┤
│ NEXT 12 H                            │
│  18h   21h   00h   03h   06h         │  rain strip, 3-h blocks
│  4mm   12mm  38mm  41mm  9mm         │
│  60%   85%   95%   95%  70%          │
├──────────────────────────────────────┤
│ ROADS                                │
│ Closed 3 · Reported 5 · No data 12   │
├──────────────────────────────────────┤
│ NEAREST SHELTER                      │
│ Coliseo Sauces 6 · 1.2 km · 15 min   │
│ Open · Verified 40 min ago           │
├──────────────────────────────────────┤
│ ┌──────────────────────────────────┐ │
│ │  Report flooding                 │ │  primary action
│ └──────────────────────────────────┘ │
├──────────────────────────────────────┤
│ Updated 14:32 · 6 min ago            │
│ Open-Meteo CC BY 4.0 · OSM/ODbL      │
├──────────────────────────────────────┤
│ Home  Forecast  Map  Route  More     │  tab bar, 56 px + safe area
└──────────────────────────────────────┘
```

In Spanish the same screen reads *Inicio · Pronóstico · Mapa · Ruta · Más*, *RIESGO ACTUAL*,
*AVISO NARANJA*, *Reportar inundación*. The layout is identical — only the string table changes.

**Component behaviour**

- **App bar.** Location chip opens the sector picker ("Use my location" plus a list of sectors).
  Changing the sector re-renders risk, rain and nearest shelter; it does not change the map viewport
  until the user asks.
- **Alert ribbon.** Hidden entirely when no alert is active — no placeholder, no "all clear" badge.
  Shows the highest active severity, its window, and its age. Tapping opens the alert detail with the
  issuer, the publication time, the affected sectors, and a share action.
- **Risk card.** Level (numeral + icon + word), one-line driver summary, and a 24-hour sparkline of
  the risk level. Tapping opens Flood Outlook (feature 4). The card always names its inputs; if a
  source is missing it says so here rather than pretending the level is complete.
- **Rain strip.** Five 3-hour blocks covering the next 12 hours — the horizon a citizen can act on.
  Millimetres above, probability below, heavy-rain blocks marked with a bracket. Tapping opens
  Rainfall Forecast.
- **Road summary.** Three counts, each a distinct state: closed (verified), reported (unverified),
  no data (unknown). Tapping opens the Map with that layer active. The "No data" count is never
  omitted, because a road with no information is a risk of its own.
- **Nearest shelter.** One result only — the closest one with a status. If its status is unverified,
  the card says so and links to the full list rather than presenting it as available.
- **Primary action.** Report a flood. Reachable without scrolling on a 360 px viewport.
- **Footer.** Absolute timestamp plus relative age, plus attribution. The absolute time is always
  present so a screenshot remains interpretable.

---

## 3. The provenance chip — one primitive, used everywhere

This is the mechanism that keeps the app honest, and it is consistent across every screen:

| Chip (EN) | Spanish | Meaning | Visual treatment |
|---|---|---|---|
| **Verified** | Verificado | Confirmed by an administrator, with a timestamp | solid outline, check icon |
| **Reported** | Reportado | Citizen-submitted, not yet reviewed | dashed outline, speech icon |
| **Estimated** | Estimado | Derived by the system (model, forecast, calculation) | dotted outline, function icon |
| **Stale** | Desactualizado | Past its freshness budget | muted fill, clock icon, age in text |
| **No data** | Sin dato | No information exists | grey, question icon — never green, never "safe" |

Rules: chips always include a word (never icon-only), always pair with a timestamp where one exists,
and "No data" is a distinct state from "Verified clear". The freshness budget per data type is set in
Stage 3; the UI treats exceeding it as a chip change, not a silent refresh.

---

## 4. Information architecture and navigation

Eight features, five tabs, everything reachable in ≤2 taps.

```
Home ────────── Safety Dashboard (1)
              ├─ Flood Outlook (4)        ← tap risk card
              └─ Shelters (6)             ← tap shelter card

Forecast ───── Rainfall Forecast (2)

Map ────────── Interactive Flood Map (3)
              ├─ Sensors · Risk zones · Roads · Shelters · Reports
              └─ Shelter sheet (6)        ← tap a shelter pin

Route ──────── Safe Route Finder (5)
              └─ Shelter & Emergency Finder (6)  ← "go to a shelter"

More ───────── Shelters & emergencies (6)
              Report flooding (7)
              Shelters, data sources, accessibility, language
```

Tab labels: **Home · Forecast · Map · Route · More**. In the Spanish locale: *Inicio · Pronóstico · Mapa ·
Ruta · Más*. The layout is identical — only the string table changes (locale policy: Stage 3 §15).

- **Mobile (<768 px):** fixed bottom tab bar, 5 items, icon + label, 56 px + safe area.
- **Tablet (768–1023 px):** same tab bar, content in a 2-column grid where it helps (map + list).
- **Desktop (≥1024 px):** left rail nav (224 px) with the same five destinations, content max 1120 px.
  Map screens become map + side panel rather than map + bottom sheet.
- **Deep links:** every screen has a shareable URL carrying its state (`/en/map?layer=roads&sector=north`,
  `/en/route?from=…&to=…`). This is what makes WhatsApp sharing work, and it is a hard requirement on
  the router from day one. The locale is part of the path so a shared link opens in the sender's
  language.
- **Language:** English primary, Spanish secondary (§11, Q1 — resolved).

---

## 5. Feature 1 — Safety Dashboard

Covered in §2. Data required:

| Element | Data | Freshness target |
|---|---|---|
| Risk level + drivers | Derived risk for the selected sector | ≤10 min |
| Active alerts | Published alerts overlapping now, with severity and window | on publish |
| Selected location | Sector id + display name, or GPS fix with accuracy | session |
| Last-updated | Server fetch time + upstream model run time | always shown |
| Road counts | Road-segment statuses in the sector | ≤5 min |
| Nearest shelter | Shelter record + status + distance | ≤30 min |

Behaviour when a source fails: the affected card switches to its last cached value with a
**Stale** chip and the age in text. The risk card never silently drops an input; it names
the missing source in its driver line.

---

## 6. Feature 2 — Rainfall Forecast (mandatory)

**Purpose:** let a citizen decide *when* to travel, not just whether.

**Layout**

1. Header: sector, model run time, fetch time, source (`Open-Meteo`), and the INAMHI cross-check
   state (see below).
2. **Next 24 h chart.** Vertical bars, one per hour, height = mm, a dot per hour = probability.
   Heavy-rain threshold as a labelled horizontal line. Bars are the only chart on the page.
3. **Accessible list.** The same 24 hours as rows: time · mm · probability · heavy-rain flag.
   This is the canonical representation; the chart is a view of it, not a replacement.
4. **Daily summary.** 3 days: total mm, max hourly mm, max probability, heaviest window.
5. **Honesty block.** "Forecast, not observation" — stated in words — plus the model run time and
   the difference between forecast and measured rainfall where a measurement exists.

**Heavy-rain threshold.** Named and shown as a value in mm/h with its basis stated (e.g. an INAMHI
advisory tier or a documented product threshold). If no defensible threshold is available, the UI
shows absolute millimetres and probability and **does not** invent a "heavy rain" label.

**INAMHI cross-check.** Three visible states, and only three: *concordante* (both agree on the heavy
window), *discrepante* (they differ — show both, do not average), and *no disponible* (cannot be
retrieved; say so). Never render a check as passed because it could not be performed.

> **Updated 2026-10-25 after source research.** INAMHI does publish Guayaquil-specific products
> (`Pronóstico Extendido Guayaquil-Durán`, `Boletín Guayaquil-Durán`, `Alerta Temprana`,
> `Boletín Hidrológico`) — but as portal bulletins, with **no public API**. So the cross-check cannot be
> automated. It is an **administrator-entered bulletin** carrying its own issue time, displayed as
> *INAMHI (boletín, ingreso manual)* — visually and semantically distinct from the machine-fetched
> Open-Meteo chip. Cheapest honest version: a single admin field "cita del boletín INAMHI vigente" + URL
> + issue date. Detail: `docs/DATA-SOURCES.md` §5.

**Interactions.** Tap an hour → detail row expands with exact values and the local timestamp.
Share → text summary ("Heavy rain forecast 22:00–04:00, up to 41 mm/h").
Pull-to-refresh with a visible request time.

---

## 7. Feature 3 — Interactive Flood Map

**Purpose:** spatial truth. Where is the water, what is closed, where do I go.

**Layers** (each independently toggleable, with a legend that is always on screen):

| Layer | Content | Default |
|---|---|---|
| Vías | Road segments coloured + patterned by status: closed, affected, reported, unknown | on |
| Zonas de riesgo | Historical / modelled flood-prone areas, low elevation tint | on |
| Sensores | 5+ nodes, each labelled **SIMULADO**, sized by trend | on |
| Shelters | Verified safe zones, open/unknown status | off |
| Reportes | Citizen reports with photo + age | on |

**Interaction model**

- Mobile: map fills the viewport under a 56 px header; a draggable bottom sheet holds the legend and
  the selected feature. Tapping a road segment or pin raises the sheet — no popups, because popups
  are unreadable one-handed.
- Sheet content for a road: name, status chip, who set it and when, any photo, and "evitar esta vía"
  which pre-fills the Route Finder.
- Sheet content for a sensor: node name, current depth (labelled simulated), threshold, trend arrow,
  last reading time, health.
- Desktop: map left, 360 px panel right, same content.

**Honesty rules**

- Sensor markers say **SIMULADO** on the marker itself, not only in a footnote.
- Unknown roads are drawn with a distinct grey hatch, not left blank and not drawn as clear.
- The legend explains what "unknown" means in one sentence, in place.

**Low-network degradation.** The map is the single heaviest element in the app and is never part of
first paint. If tiles or JS fail, the map region is replaced by a text list of the same findings
("Vías cerradas cerca de ti: …") plus a retry. The user loses the picture, not the information.

---

## 8. Feature 4 — Flood Outlook

**Purpose:** explain the risk number so a citizen can judge it, and refuse to predict what cannot be
predicted.

**Layout**

1. **Current estimate:** level (numeral + icon + word), one-sentence driver, confidence stated as
   *alta / media / baja* with the reason ("alta: 5 sensores activos, pronóstico concordante").
2. **Contributing factors**, each as a row with its value and its chip:
   predicted rainfall 6 h / 24 h · measured water level and trend per nearby sensor · sector
   elevation and its relation to the estuary · active reports · tide window.
3. **Trend:** 6 h of sensor depth as a sparkline per node, with the threshold line drawn.
4. **Time to threshold:** shown *only* when the method is supported — at least three consecutive
   readings within the last hour, a consistent rising trend, and a threshold inside the sensor's
   measured range. Otherwise the panel reads "No estimate: insufficient data" with the reason.
   When shown, it is a range ("≈45 min, ±20 min"), never a point.
5. **Water context:** tide phase and next high tide as **astronomical prediction**, explicitly not a
   measured river level, with the station/source named.
6. **What this does not tell you:** a short, permanent list — no street-level depth, no drainage
   capacity, no guarantee for any specific address.

**River and tidal data.** Guayaquil's ~3.9 m tidal range is real context, but no verified free
measured-river-level feed for the city was found. The proposal shows tide *predictions* as context and
labels them as such, and does not claim a measured river level.

> **Updated 2026-10-25.** Two refinements. (a) Tide stays *astronomical prediction*; INOCAR's
> programmatic access is unverified. (b) The only open river signal is **GEOGloWS ECMWF streamflow** —
> 10-day horizon, ~3-hour interval, global, with a documented REST service, and notably already linked
> from INAMHI's own portal. It is **hydrological model output, not a gauge reading**. It may appear in
> the Outlook as an *Estimated* "modelled discharge" line naming the model and its run time. It must never
> be labelled "nivel del río medido". Detail: `docs/DATA-SOURCES.md` §4.

---

## 9. Feature 5 — Safe Route Finder

**Purpose:** get from A to B without entering known hazard — and say plainly what is not known.

**Inputs.** Origin and destination from: map pick, "my location", or a shortcut (Home, Work, Shelter,
Hospital). Origin defaults to current location with its accuracy shown; if accuracy is worse than ~50 m
the field says so, because routing from a wrong origin is worse than no route.

**Results.** Up to 3 alternatives, each a row:

```
Route 1  · 4.2 km · 14 min (estimated)
Avoids 3 closures and 2 flooded roads
Information coverage: 62 % verified · 38 % no data   ⚠
[ View on map ]   [ Share ]
```

Spanish locale renders the same row as *Ruta 1 · 4,2 km · 14 min (estimado)*, *Evita 3 cierres y 2 vías
inundadas*, *Cobertura: 62 % verificada · 38 % sin dato*. Decimal separator and labels follow locale;
the classification and coverage numbers do not change.

- **Never "safe".** The vocabulary is "no known hazards". A route is
  described by what was avoided and what is unknown.
- **Coverage metric is mandatory**, not optional. It is the share of route length whose segment
  status is verified within the freshness budget. A route at 40 % coverage is not offered as a
  recommendation; it is offered as "route with high uncertainty", visually demoted.
- **Per-segment strip:** a horizontal bar of the route showing each segment's chip, so the unknown
  stretches are visible before the user commits.
- **When every option is exposed:** show the least-exposed route with its hazards listed and
  labelled, plus the nearest shelter. Do not present a hazard-crossing route as a success.
- **When no route exists:** state why (network disconnected in the graph, closed segment cutting the
  area) and offer the nearest shelter and emergency numbers.

**Data.** Road graph with per-edge status and timestamps, distances, assumed speeds. Travel time is
labelled *estimado* always — it assumes no flooding delay, and the UI says that in one line.

---

## 10. Feature 6 — Shelter and Emergency Finder

**List**, sorted by distance: name, type (shelter / hospital / fire / police), status chip,
distance, walking time, capacity where known, accessibility flags (ramp, pets, family space), and
"go here" → Route Finder with the destination pre-filled.

- Status values: Open · Unverified · Full · Closed · No data. Only **Open** may imply
  availability, and only when set by an administrator with a timestamp.
- A hospital row shows whether emergency services are reported available, with the same chip logic.
- Calling is a plain `tel:` link with the number shown next to it.
- Empty state: "No shelters registered in this sector" plus the emergency numbers. Never an
  empty list with no guidance.

---

## 11. Feature 7 — Citizen Flood Reporting

**Purpose:** turn citizens into sensors, without turning the map into noise.

**Flow — four steps, one screen each, each step skippable except location**

1. **Ubicación.** GPS fix with accuracy radius drawn on a small map, or drag the pin. "Usar
   ubicación aproximada" for privacy (coarsens to sector centroid).
2. **Foto.** Camera or gallery, compressed client-side before upload, optional. EXIF stripped on
   upload.
3. **Profundidad.** Visual selector — tobillo (<15 cm), rodilla (15–40 cm), cintura (40–80 cm),
   sobre el capó (>80 cm) — not a numeric field. Optional.
4. **Descripción.** ≤280 characters, optional. Then: submit.

**After submit.** Confirmation shows a reference code and the status **Pendiente**, with a plain
sentence: "Your report will be reviewed by the team. It is not shown publicly as verified."
(Spanish: "Tu reporte será revisado por el equipo. No se muestra públicamente como verificado.")
The user can track the report by code without an account.

**Behaviour and rules**

- **Offline queue:** submissions are stored locally and sent when connectivity returns, with a
  visible "queued" state and the capture time preserved.
- **Privacy:** no account, no name, no phone number. Location coarsening offered by default for
  public display. Retention policy stated in one line on the form.
- **Self-evident status:** pending / verified / rejected, each with a reason on rejection.
- **Anti-abuse:** rate limit per device, duplicate detection near the same point within 30 min, and
  the photo's capture timestamp shown so old photos are not mistaken for current conditions.

---

## 12. Feature 8 — Low-network experience

Budgets and behaviour, treated as a feature with acceptance criteria:

| Concern | Commitment |
|---|---|
| First paint | HTML + CSS ≤ 60 KB gzipped; no web font; system font stack; text and numbers before any chart |
| Map | Never loaded on first paint; loaded on tap with a visible placeholder and a timeout fallback |
| Cached essentials | Last dashboard payload, last 24 h forecast, shelter list, road summary — service-worker cached with their original timestamps |
| Stale display | A dated banner above the content: "Data from 14:32 · 41 min ago" plus the affected cards chipped **Stale** |
| Offline | Banner "Sin conexión · mostrando datos guardados"; reporting still works into the queue; map degrades to the text list |
| Slow network | Skeletons with a source label, a 10 s timeout, then cached content with an explicit retry — never an infinite spinner |
| Failure copy | Every error names what failed and what the user can still do |
| Data cost | No polling on hidden tabs; refresh only on user action or visible staleness; no background video or animation libraries |

---

## 13. Global states

Every screen is specified in five states, not one: **loading · empty · error · partial · full**.

The two that matter most here:

- **Empty is not safe.** "No reports in this sector" is rendered neutrally with the *No data* chip
  and the sentence "The absence of reports does not confirm that the road is clear."
- **Partial is normal.** With five sensors and intermittent networks, most of the time some data will
  be missing. Partial is a designed state with its own layout, not a degraded accident.

---

## 14. Visual direction

**Light, minimal, teal + navy.** Deliberately closer to a public utility than a startup dashboard:
flat surfaces, thin borders, generous whitespace, one accent colour doing the work.

| Token | Value | Use |
|---|---|---|
| `navy-900` | `#0A2540` | primary text, app bar text |
| `navy-700` | `#143B5C` | headings, nav active |
| `teal-700` | `#0F766E` | primary actions, links, active tab |
| `teal-50` | `#ECFDF8` | tinted surfaces, selected rows |
| `surface` | `#FFFFFF` / `#F7F9FA` | page / card inset |
| `border` | `#E3EAEF` | card and divider lines |
| `muted` | `#5B6B78` | secondary text, timestamps |
| `info` | `#0E7490` | Nivel 1 |
| `watch` | `#B45309` on `#FEF3C7` | Nivel 2 |
| `warn` | `#C2410C` on `#FFEDD5` | Nivel 3 |
| `danger` | `#B91C1C` on `#FEE2E2` | Nivel 4 |
| `ok` | `#15803D` | verified open / clear |

**Severity ramp — four levels, four redundant encodings each:**

| Level | Word (EN) | Spanish | Icon shape | Colour |
|---|---|---|---|---|
| 1 | Watch | Vigilancia | filled circle | info teal |
| 2 | Caution | Precaución | triangle | watch amber |
| 3 | Alert | Alerta | diamond | warn orange |
| 4 | Emergency | Emergencia | octagon | danger red |

Numeral, word, shape and colour — any one alone is sufficient to read the level.

**Type.** System stack (`-apple-system, "Segoe UI", Roboto, sans-serif`). Scale 12 / 13 / 14 / 16 /
18 / 22 / 28 / 34 px; body 16 px, line-height 1.5; numerals tabular in tables and metrics.
**Spacing.** 4 px base, page gutter 16 px mobile / 24 px desktop, card radius 12 px, card padding 16 px.
**Motion.** Only for state transitions that would otherwise be confusing (sheet open, layer toggle);
120–160 ms, and fully disabled under `prefers-reduced-motion`.
**Accessibility.** Contrast ≥4.5:1 for text; visible focus ring on every interactive element; semantic
headings; live region for alert changes; charts always paired with the accessible list; target
≥44×44 px; no text in images.

---

## 15. Data requirements by feature

| # | Feature | Data needed | Source (planned) | If unavailable |
|---|---|---|---|---|
| 1 | Dashboard | sector, derived risk, alerts, road counts, nearest shelter | app DB + forecast | cached + Stale chips |
| 2 | Rainfall | hourly mm + probability, model run, 48 h | Open-Meteo (`precipitation`, `precipitation_probability`) | last cached forecast, dated |
| 3 | Map | road graph + statuses, risk zones, sensors, shelters, reports | app DB, OSM | text list fallback |
| 4 | Outlook | rain, sensor depth + trend, elevation, tide prediction | app DB, elevation service, tide source | "No estimate" + reason |
| 5 | Route | road graph with per-edge status + timestamps, distances | app DB, OSM, NetworkX | refuse to route; explain |
| 6 | Shelters | shelter records, status, capacity, contacts | app DB (admin-managed) | "No data", emergency numbers |
| 7 | Reporting | submission payload, photo, status | app DB + storage | offline queue |
| 8 | Low-network | cached payloads, service worker | client | banner + dated content |

---

## 16. Assumptions

1. **Scope is urban Guayaquil.** Durán and Samborondón are outside the demo bounding box unless
   asked; they appear only as map context.
2. **Five or more sensors are simulated** and labelled as such in the UI, in the API, and in the docs.
   Placement is representative of documented flood-prone sectors, not real infrastructure.
3. **Rainfall is the primary driver**, with water level as confirmation and tide as context — not as
   a flood measurement.
4. **Citizens are anonymous**; only administrators authenticate.
5. **The demo runs against seeded data** so the scenario is reproducible, with the live forecast
   fetch kept separate and timestamped.
6. **No official alert feed is being consumed.** Alerts originate in the admin interface and are
   published *within the app only* — never claimed as dispatched to emergency services.
7. **The map is a decision aid, not a survey instrument.** No street-level depth claims at any zoom.
8. **Text-first rendering is a product requirement**, not a fallback nicety.

---

## 17. Open questions

| # | Question | Why it blocks |
|---|---|---|
| Q1 | Primary UI language | **RESOLVED 2026-10-25: English primary, Spanish secondary via toggle.** Author in English first. Affects every string from Stage 2 onward and the demo script. |
| Q2 | Is the official HACK2IMPACT handbook available? | The brief makes it the source of truth for event requirements. Without it, Stage 4 cannot claim any requirement is met. **Searched 2026-10-25: not found.** A look-alike (IEEE HackTech El Niño 2026) was identified and rejected — see `docs/DATA-SOURCES.md` §7. **Owner's answer: unavailable; proceed without it.** Consequence: Stage 4 cites only this brief and states explicitly that event requirements are unverified. |
| Q3 | Demo bounding box and the sector list | Determines seeded sensors, shelters and risk zones. Proposal: Norte (Sauces 6, Samanes), Centro (Cerro Santa Ana), Sur (Cristo del Consuelo, Cisne II), plus Martha de Roldós. |
| Q4 | Is there an approved INAMHI source (feed, page, or manual entry)? | **Partly resolved:** products exist but there is no public API, so manual bulletin entry is the only honest path. Still needs your confirmation that hand-entered bulletins are acceptable, and that no scraping is expected. |
| Q5 | Any approved tide/water-level source for the Guayas? | **Partly resolved:** tide = prediction (INOCAR, access unverified); river = GEOGloWS *modelled* streamflow. Still needs your decision on whether a modelled river signal is acceptable in the Outlook, or whether it should be omitted entirely (see `docs/DATA-SOURCES.md` §4 for what each option displays). |
| Q6 | Elevation: the brief says SRTM 30 m, but Open-Meteo's elevation service is Copernicus GLO‑90 (90 m) | Measured context makes this sharper: central Guayaquil sits at **3–10 m**, so a 90 m DSM errs by more than the entire local elevation range. Either source a 30 m DEM/DTM, or treat elevation as coarse context only and drive risk from sensors + reports + rainfall. Flagged now; decided at Stage 3. |
| Q7 | Photo retention and moderation policy | Needed before the report form is built; affects storage and the privacy line in the UI. |
| Q8 | Does judging reward a clickable prototype before code? | If yes, I can produce a static visual mockup of Home + Map for review — still no application code, still inside Stage 1. |

---

## 18. Approval request

Stage 1 is complete as specified. Nothing else has been started: no admin screens, no architecture,
no dependencies installed, no application code, and no Git commit (the folder is not yet a repository).

**Approve Stage 1 and I will present the Admin Control Center (Stage 2).**
Or tell me what to change — layout, hierarchy, the five-tab model, the provenance chip system,
anything in §16–17.
