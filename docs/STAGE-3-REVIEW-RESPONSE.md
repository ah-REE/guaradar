# Stage 3 Review Response — Disposition of the Eight Review Points

**Date:** 2026-10-25
**Review received:** conditional approval of Stage 3, with eight points to address before final approval
**Status:** all eight addressed; Stage 3 remains **AWAITING APPROVAL**, not approved
**Constraint observed:** planning only. No dependencies installed, no schema applied, no code written,
no commit, no push, no deploy.

---

## Summary of changes

| # | Review point | Disposition | Where |
|---|---|---|---|
| 1 | Risk semantics for stale/missing sensors | **Addressed** — asymmetry rule, renormalisation arithmetic, conflict matrix | S3 §8.1–8.3 |
| 2 | Deterministic risk-engine tests + safety properties | **Addressed** — 44 named safety properties with validating tests (count later grew from 32 during reconciliation); coverage policy tightened | S3 §17.1–17.2 |
| 3 | GEOGloWS provenance and parsing | **Addressed** — failure documented, parsing trap encoded as tests, modelled≠measured enforced | S3 §11, `GEO-1..4` |
| 4 | Routing safety and invalidation | **Addressed** — formal eligibility classes, mandated copy, no route caching | S3 §9.1–9.2, `ROUTE-1..7` |
| 5 | Terrain restrictions | **Addressed** — D12 kept, limitations table for both products, label requirement as a test | S3 §7.1, `TERR-1..2` |
| 6 | Runtime reproducibility | **Addressed** — exact pins + wheel audit, no installs performed | S3 §2, §17 |
| 7 | Service failures and cost | **Addressed** — degradation matrix; $0 recast as terms-description, not guarantee | S3 §17.1 |
| 8 | Document consistency | **Addressed** — cross-checked below, discrepancy log included | this document §9 |

---

## 1. Stale or missing sensors cannot create false reassurance

> **⚠ SUPERSEDED 2026-10-25 — read this first.** The disposition below *retained* a `coverage < 0.6` cap on
> the risk level. That cap was subsequently found to be **unsafe** and is **withdrawn**: with sensors
> stale, achievable coverage is capped at 0.55, so the rule downgraded *every* sensor outage to Caution
> regardless of rain, verified reports or closures. The authoritative record is now
> `docs/STAGE-3-ARCHITECTURE.md` §8.4 and `docs/STAGE-3-RECONCILIATION.md` finding **C-1**.
> This document is preserved unedited below as the historical record of what was believed at the time —
> the correction history is deliberately not laundered. Where the two disagree, §8.4 governs.
> `RISK-3`/`RISK-4` no longer assert a cap; they assert the *absence* of one.

**Agreed, and it was under-specified.** The prior text said "capped at 2" without saying what the user
*sees*. The gap was real: a Level 2 built on 30 % evidence looked identical to a Level 2 built on 95 %.

Now specified in S3 §8.1–8.2:

- **Renormalisation is explicit arithmetic**, not prose. Missing inputs are excluded and the remaining
  weights are rescaled by `w_total`, so the score is never computed over a zero-filled gap.
- **`coverage` (Σ present weights) is returned as data**, not inferred by the client. `coverage < 0.6`
  triggers a *mandatory* "insufficient evidence" state, distinct from a merely lower number.
- **Asymmetry rule.** A sensor that went high then silent is **retained for a bounded decay window**, then
  marked stale — never dropped to zero. A sensor that went low then silent is **excluded**. The two
  symmetric-looking events have opposite safety meanings: rising-then-silent is the alarming pattern in
  flood monitoring, and treating it as "no data" loses the most important signal in the system.
- **Zero inputs ⇒ "Unable to assess"**, never Level 1. Silence is not safety.
- **Monotonicity property (`RISK-5`)**: verified-low → unknown can never lower the published level.
- **UI requirement**: when `coverage < 0.6` or all sensors are stale, the level must render with a
  visible "insufficient / stale evidence" treatment and a reason line naming the missing source. A capped
  level **without** that flag is defined as a bug, and `RISK-3`/`RISK-4` assert both halves.

## 2. Deterministic unit tests for the risk engine

**Agreed, and stronger than 100 % coverage.** Coverage alone can be satisfied by a test that executes a
branch without asserting the property, so §17.1 lists **44 named safety properties** across risk,
routing, terrain, sync, provenance, GEOGloWS, simulation, and secrets — each with a stable id, the test
type, and what the test must assert.

Key additions beyond the original plan:

- **Boundary tests** (`RISK-1`): every level reachable, and one unit either side of each threshold gives
  the adjacent level — this catches off-by-one errors at exactly the places they matter.
- **Property-based tests** (`RISK-5`, `RISK-10`): monotonicity and determinism over randomised inputs,
  not just hand-picked cases.
- **Time injection** (`RISK-7`): hysteresis verified to change level at most once per hold window under
  a rapid oscillation, since the engine takes `now` as a parameter.
- **Conflict tests** (`RISK-8`): assert the conflict is *surfaced*, and assert INAMHI-vs-Open-Meteo
  returns `Discrepant` rather than a mean.
- **Coverage policy tightened** (§17.2): 100 % branch coverage on `domain/` remains the target, but a
  missing `RISK-*` test **fails the gate even at 100 % coverage**. The properties are the contract; the
  percentage is a proxy. This is written as an anti-goal so nobody games it later.

## 3. GEOGloWS provenance and parsing

**Agreed.** Recorded in S3 §11 with the observed evidence:

- `GET /api/v2/returnperiods/{river_id}` → **HTTP 500**, body
  `{"error":"...No variable named 'logpearson3'. Variables on the dataset include ['gumbel', ...]"}`.
  This is a server-side defect, reproduced 2026-10-25.
- **Fallback:** the Outlook renders absolute modelled discharge and the ensemble band, states that the
  return-period product is unavailable, and **invents no substitute number** (`GEO-3`).
- **No return-period language anywhere**, enforced by grep-based test `GEO-2` rather than by good
  intentions.
- **Parsing trap encoded as a test** (`GEO-1`): `forecaststats` returns a single CSV mixing 3-hourly
  ensemble rows (120) with hourly high-res rows (240, values only on the hour). Blank ensemble cells
  must be filtered, not coerced. I hit this mistake myself during review — the first parse looked like a
  flatline at 5050 m³/s. The fixture asserts 120 ensemble rows, 240 hourly rows, and units m³/s.
- **Modelled ≠ measured** (`GEO-4`): a string test fails the build if "measured" appears in the same
  payload context as a GEOGloWS value. The permitted wording is "Estimated · modelled discharge" with
  model run time.
- Return periods will only be used if the source becomes valid **and** is independently verified — not
  merely if the endpoint starts returning 200.

## 4. Routing safety

**Agreed.** S3 §9.1–9.2 now define a formal classification rather than a presentation hint:

| Class | Served | Mandated copy |
|---|---|---|
| Eligible | First | "Avoids N known hazards · coverage 78 %" |
| Marginal | Demoted, never first | "Route with high uncertainty · coverage 47 %" |
| Hazard-crossing | Last, explicitly flagged | "No route avoids all closures." |
| Refused | Not served | Reason + nearest shelter + emergency numbers |

- **A successful graph search is never called safe.** Banned vocabulary: "safe", "clear", "secure",
  "flood-free". Permitted: "no known hazards" + coverage. Enforced by `ROUTE-4`, a lint+build test over
  the i18n route namespace.
- **Immediate invalidation** (`ROUTE-3`): status is read fresh per request, the graph holds topology only,
  and **route results are never cached** — no memoisation, no route table, no ETag. A cached route is a
  stale hazard map, so caching it is defined as a defect rather than a performance question.
- **Closed edges use a large finite penalty, not removal.** Rationale recorded: the app must be able to
  say "the only route is flooded" instead of "no route exists" — a materially different message during an
  evacuation. Classification prevents it from ever being recommended.
- **Staleness affects eligibility** (`ROUTE-7`): > 50 % of path beyond freshness ⇒ at most Marginal.
- **Unknown nudges, never bars** (`×1.15`), but does lower coverage — barring unknown edges in a city with
  30–40 % unverified segments would yield no routes at all.
- **Snap > 60 m refuses** (`ROUTE-5`) rather than routing from a guessed origin.

## 5. Terrain restrictions

**Agreed — D12 unchanged and now testable.** Additions:

- §7.1 adds a **limitations table for both products**: SRTM 1-arcsec (30 m, DSM-like canopy/structure
  bias, ~16 m LE90 absolute accuracy, acquired Feb 2000 — predating much recent construction) versus
  Copernicus GLO-90 (better absolute accuracy, grid far too coarse). Both share the disqualifying
  property: **their error exceeds the city's entire ~10 m relief.**
- **`TERR-1` is a static-analysis test**, not a promise: elevation may not be read by the scoring function
  or by route ranking, except via the documented static threshold modifier.
- **`TERR-2` requires the literal label** "approximate, SRTM 30 m" adjacent to any rendered elevation. A
  bare elevation number is a defect.
- Test plan retains the prohibition explicitly (§17.1), so a future contributor cannot quietly reintroduce
  terrain ranking while the prose still says not to.

## 6. Runtime reproducibility

**Agreed, and done without installing anything** — pins resolved from PyPI metadata only.

- Interpreter: **Python 3.14.8**, measured. `pip` is absent from PATH; bootstrap via
  `python3 -m ensurepip`.
- **Exact pins** for 12 backend packages and 10 frontend packages, with a wheel-availability audit table
  (S3 §17). All backend pins are pure-python except `numpy`, which has cp314 manylinux wheels.
- **`uvicorn[standard]`'s compiled extras were the genuine risk** — uvloop, httptools, watchfiles,
  websockets — and all four publish cp314 linux wheels, so `[standard]` has a plausible install path on
  3.14. That is metadata evidence (E1), **not** proof that installation succeeds.
- **Documented trap:** `networkx 3.7` declares `requires_python = !=3.14.1,>=3.12`. It excludes exactly
  3.14.1. Pinning the interpreter to 3.14.1 would fail with an unrelated-looking resolver error.
- **Smoke-test procedure** specified for Stage 5: venv → install → import test → `uvicorn --version` →
  `npm ci` → `npm run build` → record the **resolved** freeze and lockfile as the real pins.
- **Fallback pre-agreed:** drop the interpreter to 3.13, keep every library pin unchanged. No library
  swaps to work around an interpreter problem.

**Honest caveat:** this is metadata validation, not an install. It establishes that an install path
exists; it does not prove a clean install succeeds. That proof is Stage 5's first milestone.

## 7. Service failures and cost

**Agreed — and the $0 claim was too strong.** Recast in S3 §17 as *a description of current published
terms*, explicitly not a guarantee, with **no uptime claim made or implied**.

- **New §17.1 degradation matrix**: ten failure modes, each with detection method, public behaviour, and
  admin behaviour — Supabase pause, cold start, Open-Meteo timeout and 429, GEOGloWS 500 and timeout, tile
  failure, egress limit, upload failure, clock skew.
- Three rules make it honest: every degraded state **names its source and age**; **no fabricated
  substitute** for a missing source; `/api/health` is public and reports per-dependency last-success so
  the demo can be checked before going on stage.
- **Your choice to demo from the internet is recorded as accepted risk**, which makes two mitigations
  mandatory rather than optional: a **pre-pitch warm-up request** (Render free web services spin down
  after **15 minutes** idle and take **~1 minute** to wake) and a **Supabase re-wake** before the pitch
  (free projects pause after **1 week** idle).
- Also flagged: free Render Postgres **expires 30 days after creation** — a relevant constraint if the
  project outlives the event.

## 8. Document consistency

Cross-checked `PHASES.md`, `AGENT.md`, and S3 on every approved decision. Verified agreements: D1–D12,
the four declared stack exceptions, English-primary, SRTM 30 m honoured with D12 restrictions, GEOGloWS
adopted and return-periods excluded, risk auto-derive + audited override, the 60 % coverage threshold,
and Python 3.13 as documented fallback.

**Discrepancies found and corrected during this review** — listed because a clean report would be less
informative than an honest one:

| # | Discrepancy | Correction |
|---|---|---|
| D-1 | `AGENT.md` still described elevation only as a "conflict" and did not state the D12 restriction | Updated: SRTM 30 m accepted, static-context-only, with the measured figures |
| D-2 | `AGENT.md` listed GEOGloWS without recording the `returnperiods` 500 | Updated with the failure and its consequence |
| D-3 | `PHASES.md` had B5 marked resolved but no D12 decision row | Added D12 |
| D-4 | S3 §18 still described the tile source as "unresolved pending Stage 4/5" while §13 proposed self-hosting | Unified: self-host the demo bbox is the default; TQ1 remains open only for the judged submission |
| D-5 | S3 §19 TQ5 asked about local vs deployed demo, which you have now answered | Closed with your answer; risk accepted and mitigations made mandatory |
| D-6 | Stage 3 doc header said "awaiting approval" while the review was conditional | Header retains "AWAITING APPROVAL" — conditional approval is not approval |

No unrelated material was overwritten. Stage 1 and Stage 2 decisions are preserved unchanged.

---

## 9. Remaining risks

Ordered by consequence, not by likelihood.

| # | Risk | Severity | Mitigation | Residual |
|---|---|---|---|---|
| R1 | **Cold start of ~60 s on the first pitch request** | High | Mandatory warm-up request before stage; `/api/health` check | A forgotten warm-up is a visible failure; accepted by owner's hosting choice |
| R2 | **Supabase pauses after 1 week idle** | High | Pre-pitch re-wake step in the runbook | Demo-day pause remains possible |
| R3 | **Free-tier CPU makes the first route query slow** | Medium | Measure at Stage 5; pre-warm the graph at startup | Cold in-memory graph load is unavoidable |
| R4 | **GEOGloWS `returnperiods` broken; other endpoints could break too** | Medium | Degradation matrix; no substitute numbers; cached last-good | River context may vanish mid-demo |
| R5 | **Python 3.14 is new** — metadata shows wheels exist, install may still fail | Medium | 3.13 fallback pre-agreed; no library swaps | Untested until Stage 5 milestone 1 |
| R6 | **OSM completeness outside the sampled bbox unknown** | Medium | Per-sector validation before promising routing | Poorer districts may be unroutable |
| R7 | **Open-Meteo non-commercial licence unconfirmed** | Medium | TQ2 open; documented attribution | Terms interpretation is the owner's call |
| R8 | **Tile source legality under load** | Medium | Self-host demo bbox; attribution | Judged-submission tile source unresolved (TQ1) |
| R9 | **Risk model is unvalidated against observed flooding** | High, inherent | Explicitly labelled a heuristic; uncertainty shown; no hydrological claims | Cannot be removed by testing — it is a scope limitation |
| R10 | **Simulated sensors could be mistaken for real** | Medium | DB-level `simulated` default, badges everywhere, `SIM-1/2` | Human error in a screenshot remains possible |
| R11 | **Bilingual alerts delay a warning** | Low | AQ4 recommendation: bilingual required, documented override | Governance question, not technical |
| R12 | **Single-developer bus factor / hackathon time** | High | AGENT.md handover discipline; MVP-first ordering at Stage 4 | Unavoidable |

**The one risk that cannot be mitigated, and should be stated in the pitch:** R9. The risk number is a
transparent heuristic built on a forecast, five simulated sensors, and citizen reports. It is not a
hydrological model and has never been validated against observed flood depths. Its value is that it is
*honest* about this — every level names its inputs, its coverage, and what it does not know.

---

## 10. Tests that validate each critical safety property

Mapping from risk to test, so a reviewer can check the properties are actually guarded rather than merely
described. Full table in S3 §17.1.

| Failure this prevents | Property | Test asserts |
|---|---|---|
| A confident level built on almost no data | `RISK-3`, `RISK-4` | Level cap **and** `insufficient_evidence` flag; cap alone fails |
| A dead sensor silently reading as "no water" | `RISK-2`, `RISK-5` | Renormalised weights; monotonicity under input masking |
| Rising-then-silent sensor treated as clear | `RISK-3` + decay window | Last-high retained for window, then stale — score does not drop on going silent |
| Silence rendered as "all clear" | `RISK-6` | `level is None`; explicitly not 1 |
| Route sent through a closed road | `ROUTE-1`, `ROUTE-3`, `ROUTE-6` | Rank 1 avoids closed edge; PATCH changes coverage in the same cycle; hazard-crossing labelled last |
| Route called "safe" | `ROUTE-4` | Banned-vocabulary lint returns zero matches |
| Coverage percentage inflated by unknown roads | `ROUTE-2`, `ROUTE-7` | Hand-computed 42.9 % fixture; stale majority demoted |
| Elevation quietly used to rank streets | `TERR-1`, `TERR-2` | Import-graph assertion; mandatory approximation label |
| Public and admin showing different road states | `SYNC-1`, `SYNC-2` | PATCH propagates in one cycle; `published_at` unchanged by edits |
| Audit trail silently rewritten | `SYNC-3` | UPDATE/DELETE raise for every role |
| A public screen computing its own staleness | `PROV-1`, `PROV-2` | Envelope required; no date arithmetic on `fetched_at` in `src/` |
| GEOGloWS flatline misread as a real signal | `GEO-1` | 120 ensemble / 240 hourly rows, blanks excluded, units asserted |
| A "1-in-100-year" claim appearing from nowhere | `GEO-2` | Grep returns zero |
| Modelled flow described as measured | `GEO-4` | String test on payload context |
| Service-role key shipped to the browser | `COST-1` | Built `dist/` grep returns zero |
| Simulated readings persisted as real | `SIM-1` | Insert without column ⇒ `simulated = true` |

---

## 11. Status

Stage 3 has been revised in response to all eight points. **At the time of writing it remained unapproved
pending explicit approval** — conditional approval was treated as exactly that, and no stage advanced.

> **Update 2026-10-26:** Stage 3 was subsequently **APPROVED** on the reconciled decisions D23–D28.
> This document is preserved as the record of the eight-point review.
Still true: no dependencies installed, no schema applied, no application code, no commit, no push, no
deploy. Stage 1 and Stage 2 decisions are preserved.

**On approval of Stage 3, Stage 4 will present:** official requirements handling (with the handbook
recorded as unavailable, so requirements are drawn only from your master instructions and labelled
unverified), MVP vs secondary vs future classification, the demo scenario, and the implementation plan —
then stop again.
