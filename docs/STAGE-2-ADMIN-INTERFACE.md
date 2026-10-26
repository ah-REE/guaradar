# Guaradar — Stage 2: Admin Control Center

**Status:** PRESENTED — awaiting approval
**Approved predecessor:** Stage 1 Public Interface, approved 2026-10-25
**Scope of this document:** the administrator-facing interface only.
**Out of scope (by instruction):** technology architecture, database schema, API design,
remaining requirements, any implementation or code.
**Date:** 2026-10-25
**Language decision:** English primary UI, Spanish secondary (owner, 2026-10-25).

---

## 0. What this document is

A behavioural specification of the admin interface: what an authorised operator sees, what they can
do, and — critically — **exactly how each admin action changes what the public sees**. The brief makes
public/admin consistency a requirement, so §12 is the load-bearing section of this document, not an
appendix.

The admin surface is intentionally *denser* than the public one. Stage 1 §6 said the public interface
must stay simpler than the admin interface; that permission is used here, but not as an excuse for
clutter — density is information, not decoration.

---

## 1. The governing principle: every number has an author

The public app refuses to imply certainty it doesn't have. The admin app is where certainty is
actually manufactured, so it must be equally explicit about **provenance and authorship**:

| Question | Where the answer lives |
|---|---|
| Who set this road to "closed"? | Every status change records operator, timestamp, and reason |
| Is this sensor real or simulated? | **SIMULATED** badge on the node, in the list, in exports, and on the public map |
| Was this alert sent anywhere? | The alert record says "published in app only" — it never claims external dispatch |
| Why is this incident "verified"? | Verifier identity + timestamp + optional note, visible in the audit trail |
| Why did the public risk level change? | Every published alert and status change is timestamped, so the public timestamp is explainable |

If an operator cannot answer "where did this come from?", the UI has failed.

---

## 2. Access model and authentication

### Roles

| Role | Can do | Cannot do |
|---|---|---|
| **Viewer** | Read dashboards, maps, sensors, incidents, alerts | Change anything, see citizen contact data |
| **Operator** | Verify/reject incidents, set road status, manage shelters, create **draft** alerts | Publish alerts, change sensor thresholds, manage users |
| **Publisher** | Everything Operator can, plus publish/update/expire alerts | Manage users, delete audit records |
| **Admin** | Everything, plus user management, sensor configuration, threshold changes, exports | Delete audit history (append-only) |

Rationale: separating *draft* from *publish* is the single most important permission boundary here. An
operator can prepare a warning; only a Publisher can put words in front of the public. That prevents a
single mistaken click from reaching thousands of phones.

### Authentication behaviour

- Email + password, or magic link. No social login — this is a public-safety tool, not a consumer app.
- **Mandatory MFA (TOTP)** for Publisher and Admin. Recommended for Operator.
- Session timeout **30 min idle**; re-auth required for publish, delete, and bulk road-status changes.
- Login is rate-limited and lockout-based; failures are logged with IP and timestamp.
- **Every mutating action is written to an append-only audit log** with actor, timestamp, target,
  before-value, after-value, and reason where one was required. The log is readable in the UI and not
  editable by any role.
- Admin routes are separate from public routes (`/admin/*`) and never linked from the public app.
- Password/secret handling is a Stage 3 concern, but the rule is fixed now: **no secrets in the
  frontend bundle, ever**, and no service-role key in any client.

---

## 3. Layout and navigation

Denser than public: persistent left rail, persistent top bar, content in a 12-column grid.

```
┌────────────┬──────────────────────────────────────────────────────────┐
│ GUARADAR   │  Guayaquil · Norte ▾        ⏱ 14:32  ⚠ 3 unverified  👤 │  top bar 64px
│ Admin      ├──────────────────────────────────────────────────────────┤
│            │                                                          │
│ ▸ Overview │   [ content area, 12-col grid, max 1440px ]              │
│ ▸ Map      │                                                          │
│ ▸ Sensors  │                                                          │
│ ▸ Forecast │                                                          │
│ ▸ Alerts   │                                                          │
│ ▸ Incidents│                                                          │
│ ▸ Roads    │                                                          │
│ ▸ Shelters │                                                          │
│ ▸ Audit    │                                                          │
│ ▸ Users    │                                                          │
│            │                                                          │
│ SIMULATED  │  persistent footer: data-mode indicator                  │
│ data mode  │                                                          │
└────────────┴──────────────────────────────────────────────────────────┘
```

**Navigation destinations** (10, mapped to the brief's 12 required items):

| Nav item | Covers brief requirement |
|---|---|
| Overview | 1. Overview dashboard, 11. Basic risk prioritisation |
| Map | 2. Interactive flood intelligence map |
| Sensors | 3, 4. Five+ simulated nodes: depth, thresholds, trend, timestamps, health |
| Forecast | 5, 6. Rainfall forecasts, flood-risk intelligence, river and tidal observations |
| Alerts | 7. Alert creation, verification, publication, updating, expiry |
| Incidents | 8. Citizen incident review and verification |
| Roads | 9. Road-status management |
| Shelters | 10. Shelter management |
| Audit | (not required, but required by consequence) |
| Users | 12. Administrative authentication and permissions |

**Persistent indicators** (non-dismissible): current sector scope, server time, count of items awaiting
review, and the data mode (**LIVE / SIMULATED / MIXED**). The data mode indicator is the single most
important chrome element in the product — see §13.

**Responsive:** the admin console targets **≥1280 px** as the design case. At 1024–1279 px the rail
collapses to icons and the grid drops to 8 columns. Below 1024 px it is **read-and-acknowledge only**
(alerts, incidents, sensor status) with an explicit banner: "Full editing requires a larger screen."
This is deliberate — road-status editing on a phone in the rain is how wrong closures happen.

---

## 4. Overview dashboard

Purpose: answer "what needs me right now?" in under five seconds.

**Row 1 — four stat tiles**, each clickable into the filtered list:

| Tile | Shows | Alarm condition |
|---|---|---|
| Public risk level | Current derived level per sector, mini-map of sectors | Level 3+ in any sector |
| Unverified incidents | Count + oldest age | Any older than 2 h |
| Roads | Closed / affected / no-data counts | No-data share > 30 % |
| Sensors | Healthy / degraded / offline / **rising** | Any node offline, or 2+ rising simultaneously |

**Row 2 — two panels side by side**

- **Rain next 24 h** (compact, same data as public §6, denser): hourly bars, heavy-rain threshold line,
  max-block callout, INAMHI bulletin status.
- **Sensor depth, 6 h sparklines**: one row per node with threshold line, trend arrow, last-reading age,
  SIMULATED tag. Rising nodes sort to the top automatically — the ordering *is* the prioritisation.

**Row 3 — action queue**, the operational heart:

| Priority | Item | Age | Action |
|---|---|---|---|
| ▲ | Sensor *Sauces-6* rising 0.14 m/h, 0.8 m below threshold | 4 min | View |
| ▲ | 6 reports clustered near Av. Juan Tanca Marengo | 18 min | Review |
| ▲ | Road *Vía a Daule* closed, no re-check in 3 h | 3 h | Re-check |
| ○ | Alert *Heavy rain* expires in 45 min | — | Extend / Expire |

**Risk prioritisation method (basic, as the brief asks).** A transparent score, shown as a sort order
with its inputs visible on hover — never as an unexplained number:

```
priority = severity_weight × exposure_weight × recency_weight
```

- `severity_weight`: from the highest current signal (closed road 2, rising sensor 3, active report
  cluster 2, expired alert 1 …)
- `exposure_weight`: rough population/route importance of the sector (sectors tagged once by an admin,
  not computed)
- `recency_weight`: decays with age, so stale items rise so they get re-checked rather than forgotten

Every weight is visible in the UI and editable by an Admin. If the weights are tuned during the demo,
that is fine — as long as the formula is on screen. An operator who cannot see why an item is top of the
queue will stop trusting the queue.

---

## 5. Interactive flood intelligence map

Same geography as the public map, plus the controls an operator needs.

**Difference from public map:**

| Capability | Public | Admin |
|---|---|---|
| Layers | 5 fixed | Same 5 + elevation tint + sensor catchments + report density heat |
| Sampling | No | Click a road → status editor; click a sensor → detail drawer |
| Bulk actions | No | Box-select road segments → set status for all |
| Editing | No | Road status, sensor thresholds, shelter records |
| Simulated markers | Labelled | Labelled **and** colour-coded so a demo never reads as live |

**The road-status editor** (opened from a segment) is the most-used control in the console:

```
Vía a Daule  ·  segment 4471  ·  currently: CLOSED (verified, 3 h ago, by k.mendoza)
────────────────────────────────────────────────────────────
Status   ( ) Open  ( ) Affected  (•) Closed  ( ) Unknown
Depth    ( ) <15cm  ( ) 15–40cm  ( ) 40–80cm  ( ) >80cm  ( ) unknown
Reason   [ water across carriageway, both lanes        ]
Evidence [ attach photo ]  [ link to verified report ]
Review in [ 30 min ▾ ]
────────────────────────────────────────────────────────────
        [ Cancel ]              [ Save + log ]
```

- **`Unknown` is a first-class status**, not the absence of one. Operators are trained to reset
  unverifiable roads to Unknown rather than leaving a stale "Closed" that nobody will remember to lift.
- **"Review in"** sets an automatic staleness reminder. When it lapses, the public chip flips to
  *Stale* automatically — no operator action required for the public to stop trusting it.
- **Saving requires a reason** for `Closed` and for any change that *removes* a hazard (open/affected),
  because un-closing a road is the higher-risk direction.

---

## 6. Sensors — five or more simulated nodes

**The node list** (one row per sensor):

| Node | Sector | Depth | Threshold | Trend | Last reading | Health | |
|---|---|---|---|---|---|---|---|
| SIM-01 Sauces 6 | Norte | 0.82 m | 1.20 m | ▲ +0.14 m/h | 2 min ago | OK | Detail |
| SIM-02 Samanes | Norte | 0.31 m | 1.00 m | → 0.00 | 4 min ago | OK | Detail |
| SIM-03 Cerro Santa Ana | Centro | 0.64 m | 0.80 m | ▲ +0.09 m/h | 3 min ago | **Degraded** | Detail |
| SIM-04 Cristo del Consuelo | Sur | 0.18 m | 0.90 m | ▼ −0.02 | 1 min ago | OK | Detail |
| SIM-05 Cisne II | Sur | 1.34 m | 1.10 m | ▲ +0.21 m/h | **38 min ago** | **Offline** | Detail |
| SIM-06 Martha de Roldós | Norte | 0.07 m | 0.80 m | → 0.00 | 5 min ago | OK | Detail |

**Every row and every detail view carries `SIMULATED`.** Not a footnote, not a tooltip — a badge in the
row, in the drawer, on the public map marker, in the CSV export header, and in any screenshot the demo
produces.

**Node detail drawer**

- Current depth, threshold, and the gap between them, in metres **and** as a percentage of threshold.
- 24 h depth chart with the threshold line and the heavy-rain periods shaded behind it — so a rise can
  be read against what actually fell.
- Trend: slope over the last 15 / 60 min, with the method stated (linear fit on N readings). Trend is
  shown as a rate, never as a countdown.
- **Rate of rise + threshold + ≥3 readings in the last hour → "estimated time to threshold ≈ 45 min
  (±20)"**. If any condition is unmet, the panel reads **"No estimate: insufficient data"** with the
  specific missing condition named. This matches the public rule in Stage 1 §8 — the admin sees the
  same number and the same refusal, so the two interfaces cannot contradict each other.
- **Health**: `OK` (readings inside expected interval) · `Degraded` (late or noisy) · `Offline` (no
  reading past a limit) · `Maintenance`. Health is derived from reading cadence, not from a manual flag,
  so it cannot silently lie.
- Readings table: timestamp, depth, quality flag — and an explicit note that **simulated readings are
  generated, not measured.**

**Configuration** (Admin only): threshold per node, expected reporting interval, staleness limit,
simulation profile (dry / steady / heavy / surge). Changing a threshold is an audited action and takes
effect for the public "time to threshold" immediately.

**What the console must never do:** backfill, smooth, or interpolate readings to hide gaps. A gap is
drawn as a gap. An offline sensor is visible as offline rather than dropped from the average.

---

## 7. Forecast and flood-risk intelligence

- **Rainfall**: hourly bars, 48 h horizon, probability as a second series, heavy-rain threshold, model
  run time, fetch time.
- **Source comparison**: Open-Meteo (machine-fetched, chip = Estimated) beside the INAMHI bulletin
  (manually entered, chip = Reported + *ingreso manual*). State one of three verdicts —
  *Concordant* / *Discrepant* / *Unavailable* — and when discrepant, show both and never average.
- **Risk intelligence panel**: the derived level per sector, with each contributing factor listed and
  its weight shown. This is the same calculation the public sees described in words; the admin sees the
  arithmetic. If the numbers and the public sentence ever disagree, that is a bug with a name: see §12.
- **River and tidal observations** (per owner decision 2026-10-25):
  - **Modelled discharge** from GEOGloWS ECMWF, labelled **"Estimated · modelled discharge"** with model
    name and run time. A sparkline of the next 10 days with a percentile band.
  - **Tide prediction** labelled **"Prediction · astronomical"** with station and source.
  - Both are visually separated from measured sensor depths, because they are different classes of
    thing and must never be read as a single "river level" figure.

---

## 8. Alerts — create, verify, publish, update, expire

**The alert lifecycle, explicit and enforced:**

```
DRAFT ──submit──▶ REVIEW ──approve──▶ PUBLISHED ──▶ EXPIRED
  ▲                  │                    │
  └────reject────────┘                    └──update──▶ PUBLISHED (new version)
```

The brief's word "verify" is implemented as **approve**, and the brief's word "publish" as the
transition that makes it visible to citizens. Every transition is audited.

**Composer fields**

| Field | Notes |
|---|---|
| Severity | Level 1–4, same ramp as public (word + numeral + shape) |
| Headline | ≤80 chars, shown in the public ribbon |
| Body | ≤400 chars, plain text, no HTML |
| Affected sectors | Multi-select; drives who sees it |
| Window | Start + end; **end is mandatory** |
| Instructions | What to do / not do — short list, not prose |
| Source basis | What justifies this: forecast, sensor, reports, INAMHI bulletin (multi-select + free text) |
| Language | EN + ES both required before publish |

**Publish gate — the checklist that must pass:**

1. Headline and body present in **both** languages.
2. End time in the future, and window ≤ 24 h (longer alerts go stale and stop being believed).
3. At least one affected sector.
4. A source basis recorded.
5. Publisher role present (operator cannot self-publish).

**On publish**, the UI shows exactly what happens — and what does not:

> **Published in Guaradar.** Visible now on the public app and in shared links for the selected sectors.
> **No message has been sent to any external emergency service, mailing list, or SMS gateway.** This
> publication is internal to the application.

That sentence is not optional and is not a tooltip. The brief forbids claiming external dispatch, and
the moment of publication is when a reader would wrongly assume otherwise.

**Update & expire.** Updates keep a version history with author and time; the public sees the newest
version but its *published* timestamp, not the edit time, so citizens can see how long a warning has
been standing. Expiry can be automatic (at end time) or manual; expired alerts move to an archive and
disappear from the public ribbon, with the public timestamp showing the last update.

---

## 9. Incidents — citizen report review

**Queue** with saved views: *Unreviewed · Nearest to a sensor alert · Duplicates suspected · Rejected by
others*.

Each card: photo (click to enlarge), description, chosen depth band, map location with accuracy circle,
capture time vs. submit time (so the two are distinguishable), reporter reference code, current status.

**Three actions, each with a required consequence:**

| Action | Effect on public app |
|---|---|
| **Verify** | Report shows *Verified* chip, counts toward hazard clustering, can be linked as evidence to a road status |
| **Reject** | Hidden from the public map, reason recorded, reporter sees the reason via their code |
| **Mark duplicate** | Merged into a canonical report; the duplicate's photo can be attached to the original |

- **Bulk verification is disabled by default.** Clustered reports are the easiest way to inject a false
  picture, so verifying 20 pins at once requires Admin and is audited as a single bulk action.
- Reviewers see **clusters**, not raw pins: 6 reports within 150 m are presented as one item ("6 reports,
  span 18 min, depths: knee/waste/knee") because that is the actual signal.
- **A rejected report is not deleted.** It stays in the audit trail with its reason, so a pattern of
  false reporting is visible rather than erased.

---

## 10. Road status management

Beyond the map editor (§5), a **table view** for bulk work and re-checking:

| Road | Segment | Status | Depth | Set by | Age | Review in | |
|---|---|---|---|---|---|---|---|
| Vía a Daule | 4471 | Closed | >80 cm | k.mendoza | 3 h | **overdue** | Edit |
| Av. Juan Tanca Marengo | 2290 | Affected | 15–40 cm | a.vera | 25 min | 30 min | Edit |
| Av. Francisco de Orellana | 1102 | No data | — | — | — | — | Edit |

- Sort by **age** to find the stalest claims — the console's most valuable sort, because stale closures
  are how a map becomes untrustworthy.
- **No-data share** is a headline metric, not a footnote: if 40 % of a sector's roads are unknown, the
  public route finder will say so, and the console should nag about the same number.
- Every save is audited with before/after values.

---

## 11. Shelter management

CRUD over shelter records: name, type (shelter / hospital / fire / police), address, coordinates,
capacity, accessibility flags (ramp, pets, family space), contact, and status.

- Status: **Open · Unverified · Full · Closed · No data** — mirroring the public vocabulary exactly.
- A record cannot be published as a shelter without coordinates, a contact, and a named authorising
  source. The brief requires *verified designated* zones; this field is where that claim is earned.
- **"Open" is time-boxed.** An operator sets how long the status holds (default 6 h); after that it
  reverts to *Unverified* automatically. Nobody has to remember to un-open a shelter at 3 a.m.
- Bulk import from CSV is Admin-only and shows a diff before applying.

---

## 12. How admin actions reach the public app

This is the consistency contract. Each admin action names its public consequence, the latency at which
it becomes visible, and what the public sees if the action is *not* taken.

| Admin action | Public surface affected | Visible in | If not taken |
|---|---|---|---|
| Publish alert | Alert ribbon (Home), alert detail, affected-sector risk uplift | ≤ 30 s, or on next fetch for offline clients | No warning shown; risk level reflects other signals only |
| Update alert | Ribbon text + published timestamp | ≤ 30 s | Citizens see out-of-date instructions with an old timestamp |
| Expire alert | Ribbon disappears; alert moves to archive | at expiry | Stale warning erodes trust in every future warning |
| Set road Closed | Map geometry + Home road count + **route finder avoidance** | ≤ 30 s | Route finder leads people into water |
| Set road Open | Reverse of above, chip → Verified | ≤ 30 s | Unnecessary detours; routes look worse than reality |
| Set road Unknown | Map hatch + route coverage % drops | ≤ 30 s | Coverage number stays falsely high — the specific failure the brief warns about |
| Road staleness lapse (**automatic**) | Chip → Stale; route coverage % drops | at review expiry | A closure nobody re-checked silently looks verified |
| Verify report | Map pin + hazard cluster + route coverage % | ≤ 30 s | Real hazard stays invisible in routing |
| Reject report | Pin removed, reporter notified by code | ≤ 30 s | Noise entrenches; map becomes untrustworthy |
| Change sensor threshold | Public "time to threshold", sensor card state | ≤ 30 s | Public thresholds silently disagree with the admin's mental model |
| Shelter status change | Shelter list + Home nearest-shelter card | ≤ 30 s | Citizens travel to a full shelter |
| Shelter status lapse (**automatic**) | Status → Unverified | at hold expiry | A shelter that closed hours ago still reads "Open" |

**Three mechanisms enforce consistency rather than hoping for it:**

1. **One record, one source of truth.** Road status, alert state and shelter state are single records
   read by both interfaces. The public app never maintains its own copy of a status. (Brief §6:
   "reuse shared data instead of maintaining separate conflicting versions.")
2. **The public timestamp is the *published/verified* time, never the edit time.** So a public screen
   can always be traced to an audited event.
3. **Derived values are recomputed, never cached across a status change.** Risk level, road counts and
   route coverage percentages invalidate on write. The specific bug this prevents: a road flips to
   *Closed* but the route finder still routes through it because its coverage number was cached. That
   bug would be lethal in a real deployment, so the invalidation rule is stated here, at design time,
   and must be tested at Stage 5.

**Deliberate asymmetry, stated openly:** the admin can set a road to *Unknown*; the public cannot see
*why*. If an operator marks a road unknown because the sensor is offline, the public only learns
"unknown". Explanations leak operational state, so they stay in the console — but the public UI must
never compensate by guessing.

---

## 13. Simulation mode — the honesty mechanism

Because every sensor is simulated, the console has a **data-mode banner** that is always visible and
cannot be dismissed:

- **LIVE** — all displayed environmental data is fetched from real external sources; sensor values are
  simulated (always true for this project, so LIVE is effectively never shown alone).
- **SIMULATED** — sensors and any seeded incidents/roads are synthetic.
- **MIXED** — real forecast + simulated sensors. **This is the normal state for the demo.**

Rules:

- Screenshot and export headers carry the mode and the timestamp.
- Seeded demo data is marked in the database so it can be distinguished from anything entered live
  during a demo — and so it never masquerades as an observation.
- A **reset** action restores the seeded scenario (Admin only, audited), so a demo can be re-run
  reproducibly.
- The banner is present on the public app too (Stage 1 §14 footer area): a citizen must be able to tell
  this is a prototype, not an official municipal service.

---

## 14. Global states

Every admin surface is specified in five states: **loading · empty · error · partial · full**.

- **Partial is the default state of an emergency console.** Offline sensors, unreviewed incidents and
  unknown roads are normal, not edge cases. Partial is designed, not degraded.
- **Empty queues get a reason, not a celebration.** "No unreviewed incidents" is paired with the age of
  the last review and the count of reports rejected in the last hour — an empty queue that is empty
  because a filter is wrong must look different from an empty queue that is genuinely clear.
- **Error copy names the failed source** and what is still trustworthy on screen.
- **Destructive actions** (expire alert early, bulk close, reset simulation, user removal) require typed
  confirmation and are audited.

---

## 15. Accessibility and the operator context

- Contrast ≥ 4.5:1, keyboard-navigable throughout, visible focus, semantic headings and tables.
- Severity never by colour alone — same numeral/shape/word ramp as public.
- The console is used under stress: no animation required to perceive a state change; no toast as the
  only notification of a destructive result; no auto-dismissing confirmation.
- Tables use real `<table>` semantics with sortable headers announced to assistive tech.
- Target sizes ≥ 32×32 px in dense tables (the one place the public 44 px rule is relaxed, deliberately,
  because operator is at a desk, not in the rain — recorded as a trade-off, not an oversight).

---

## 16. Assumptions

1. **All sensors are simulated**, labelled as such everywhere, including exports and screenshots.
2. **Alerts are published inside Guaradar only.** No SMS, email, push or emergency-service dispatch is
   claimed or implied. The publish confirmation says so in words.
3. **The admin is trusted-but-audited**: roles exist to prevent accidents and limit blast radius, not
   to defend against a malicious insider with database access.
4. **Single municipality, single tenant.** No multi-city support in scope.
5. **Operators work on desktop** for editing; phones are read-only by design.
6. **INAMHI bulletins are entered by hand** by an operator, with their own issue time (Stage 1 §6).
7. **Basic prioritisation** means an explicit weighted score, visible and editable — not a trained model.
8. **The demo scenario is seeded and resettable** so the pitch is reproducible.

---

## 17. Open questions

| # | Question | Why it matters |
|---|---|---|
| AQ1 | How many admin accounts, and who plays Publisher in the demo? | Determines whether MFA is demo-feasible in the time available, or whether it is implemented but shown in a rehearsed state. |
| AQ2 | Should the public risk level be auto-derived from sensor thresholds, or publisher-confirmed? | **RESOLVED 2026-10-25:** auto-derive, with a visible reason line and an audited operator override. Rationale: auto is honest and fast but can publish a level nobody reviewed; manual is safer but slower. Operator oversight is preserved through the audited override rather than by gating every update. |
| AQ3 | Alert window default and hard cap (proposed: 6 h default, 24 h cap)? | Affects the publish gate and the stale-alert problem. |
| AQ4 | Is bilingual EN/ES required for *every* alert before publish, or may a Spanish-only alert publish with a warning? | **RESOLVED 2026-10-25 → D26:** the hard bilingual block **stands** and no override is introduced. Stage 2's publish gate is unchanged. Original analysis retained: blocking every publish on translation can delay a real warning; publishing untranslated safety text is worse for the primary audience. The owner chose the approved requirement over the override. |
| AQ5 | Do you want the audit log exposed read-only to the public app (transparency), or kept internal? | Affects whether the audit trail is a public trust feature or operational data. |
| AQ6 | Sensor thresholds: who owns the real values, if this were deployed? | Currently invented for the prototype; must be stated as invented. |

---

## 18. Approval request

Stage 2 covers all twelve required admin items — overview, intelligence map, 5+ simulated sensors with
depth/threshold/trend/timestamp/health, forecasts and risk intelligence, river and tidal observations,
full alert lifecycle, incident verification, road-status management, shelter management, basic risk
prioritisation, and authentication/permissions — plus the consistency contract in §12 and the
simulation-honesty mechanism in §13.

Nothing beyond planning has been done: no architecture, no schema, no API design, no code, no
dependencies, and no Git operations.

**Approve Stage 2 and I will present Stage 3: Technology Stack and Architecture.**
Or tell me what to change — the role model, the publish gate, the priority formula, the table-first
road management, or any of the assumptions and questions in §16–17.
