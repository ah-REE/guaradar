# Stage 3 — Final Decision Summary

**Date:** 2026-10-25
**Stage 3 status:** **APPROVED 2026-10-26** — approved on the reconciled decisions D23–D28.
**Stage 1 / Stage 2:** APPROVED 2026-10-25. **Unchanged** — O-4 was the one item that could have amended an
approved Stage 2 requirement, and the owner chose to preserve it.

---

## 1. Reconciliation of the three documents (2026-10-25)

A cross-document review found three safety defects and several inconsistencies. Full disposition in
`docs/STAGE-3-RECONCILIATION.md`; the substance is summarised here because it changes decisions.

### 1.1 The sensor cap had to be withdrawn — it suppressed emergencies

The rule "`coverage < 0.6` ⇒ cap the level at 2" was **unsafe**. Run against this project's own weights:

```
All sensors stale => available weights = 0.30 (rain) + 0.15 (report) + 0.10 (road) = 0.55

rain 1.0, reports 1.0, roads 1.0  -> score 1.00  coverage 0.55
    uncapped: 4 Emergency   capped: 2 Caution      <-- SUPPRESSED
```

Losing the sensor and trend weights makes **0.55 the maximum achievable coverage**, permanently below the
0.6 threshold. So *every* sensor outage capped the level at Caution — regardless of torrential forecast
rain, four verified reports and a closed road. Since sensors frequently fail in the very storm they
monitor, the rule let a hardware failure downgrade a genuine emergency. It was also the exact inversion of
the project's own principle: a missing input was silently *lowering* published risk.

**Replacement (D18/D19):** severity and confidence are separate outputs. Missing inputs reduce
`confidence` and set `insufficient_evidence`; they never reduce `level`. A **precautionary floor** can
raise the level from credible standalone signals, and can never lower it. The user sees both facts:

> **⚠ Level 3 — Alert** · Confidence: **low** — no current sensor data
> Heavy rain forecast (38 mm in 6 h) and 4 verified flood reports. Sensors offline, so actual water depth
> is unknown.

### 1.2 The route policy was self-contradictory

It called coverage < 60 % a "rejection criterion", then served Marginal routes at 40–59 %, then served
Unknown-only routes at 0 % verified coverage. Three facts were being conflated: *does a path exist*, *does
it cross a closure*, *how much of it is verified*. Resolved by describing a route with a **pair** —
(hazard class, coverage band) — and defining all eight combinations (D20, Stage 3 §9.1).

Key consequence: **"rejection" now means only** no-path or snap > 60 m. Low and None coverage routes are
**served but never recommended, never called verified, and always labelled**.

### 1.3 The rain-versus-sensor rule was unsafe

The text said the level is "driven by the sensor, because it is the observation". That let one low reading
outvote heavy rain, verified reports and closures. Corrected (D21): every input contributes to the score,
floors can only raise, and disagreement is **stated, never averaged** (`RISK-8b`, `RISK-8c`).

### 1.4 Language: English primary, Spanish secondary — and both complete

English-first is the intended and approved policy (D8) and is **not** treated as a contradiction. Spanish
is a complete secondary locale, not a best-effort one: the people who need a flood warning in Guayaquil
read Spanish. New Stage 3 §15 defines the toggle, URL locales, fallback-with-label, a build gate on key
parity (`I18N-1`), and a requirement that severity words, chips, alert text, route copy and refusal
reasons exist in **both** languages before they render (`I18N-2`).

Stage 1's illustrative strings were partly Spanish-first in the mockup. Corrected to English-with-Spanish
labels; **no behavioural requirement was reopened**.

### 1.5 Two gaps closed

- **LIVE/SIMULATED/MIXED** was required by approved Stage 2 §13 but absent from Stage 3. Now specified
  (§10.1), computed server-side, with `SIM-3` asserting `LIVE` is unreachable here because every sensor
  is simulated — an unguarded unreachable state is how a demo accidentally claims live data.
- **Safety-property count 32 → 43.** Every addition guards a defect found in this review: the withdrawn cap
  (`RISK-3/4/4c/8b/8c`), the route policy repair (`ROUTE-2b/2c/2d`), and the missing i18n requirements
  (`I18N-1…4`, `SIM-3`).

### 1.6 Routing penalty — refuted by probe, as established earlier

`research/routing_invariant.py`, 1,201 graphs: penalty-only **1 violation**, two-phase **0**, state-space
**0**. The adversarial case serves a closed road at cost 12.50 over an open route at 246.00. Two-phase is
adopted (D16) and `ROUTE-1b` holds it as a regression test.

### 1.7 Evidence status — unchanged and re-verified

Ceiling remains **E2 (probed)**. Nothing installed, no test executed, no build attempted. The 43
properties are specifications. See `docs/EVIDENCE-STATUS.md`.

---

## 2. Final Stage 3 decision summary

### Decisions carried forward (from Stages 1 and 2, unchanged)

D1 no Git commits · D2 no code before four approvals · D3 maintain AGENT/PHASES · D4 provenance as a UI
primitive · D5 five-tab navigation · D6 no code in Stage 1 · D7 evidence markers · D8 English primary /
Spanish secondary · D9 event requirements from master instructions only · D10 GEOGloWS modelled
discharge, labelled · D11 risk auto-derives with audited override.

### Decisions added or corrected in Stage 3

| # | Decision |
|---|---|
| D12 | Terrain is **static context only** — no street ranking, no depth prediction, no live signal. Elevation always labelled "approximate, SRTM 30 m". |
| D13 | Demo runs from **deployed free-tier hosting**; cold-start and pause mitigations are mandatory runbook steps. |
| D14 | **Route results are never cached**; status read fresh per request. A cached route is a stale hazard map. |
| D15 | **Safety properties are the test contract** — **44** named ids (was 32); 100 % coverage without them does not pass. |
| D16 | **Closed roads are removed in phase 1**, not penalised. Penalty design probed and refuted. |
| D17 | **Evidence levels E0–E4 govern wording.** Project ceiling E2. |
| **D18** | **Severity and evidence coverage are separate outputs.** Missing inputs never lower the level; they lower confidence and set `insufficient_evidence`. **The old "coverage < 0.6 ⇒ cap at 2" rule is withdrawn as unsafe** (it capped every sensor outage at Caution — see §1.1). |
| **D19** | **A precautionary floor can raise the level but never lower it.** Scope and numbers fixed by **D23**. |
| **D20** | **Route coverage is a recommendation boundary, not a rejection gate.** Bands High ≥ 80 / Moderate 60–79 / Low 1–59 / None 0; all class×band combinations defined. Refusal only for no-path or snap > 60 m. |
| **D21** | **No single input may suppress the level** below what the others imply (`RISK-8b`), and a sensor cannot veto the precaution floor (`RISK-8c`). |
| **D22** | **English primary, Spanish secondary, both complete.** Missing ES strings fail the build; safety-critical strings must be present in both before an alert can publish. |
| **D23** | **Precaution floor: reports + operator-confirmed closures active; heavy-rain trigger DISABLED** pending a defensible threshold and source. Floor numbers **provisional and unvalidated**. Raises only, never lowers. |
| **D24** | **Low/zero-coverage routes: serve, never recommend** — prominent uncertainty warning, actual coverage %, unknown/stale detail. Never "verified-safe". Known closures stay excluded from ordinary eligible routes. |
| **D25** | **60 % retained provisionally** as the recommendation boundary, **not** a serve/withhold gate. Documented as an **unvalidated product decision**, not a measured safety threshold. |
| **D26** | **Hard bilingual publishing block stands** — headline *and* body in EN and ES before publication. **No override introduced**; the approved Stage 2 requirement is unchanged. |
| **D27** | **Sensor-coverage severity cap permanently removed.** Coverage affects confidence and the insufficient-evidence indicator only. "Unable to assess" preserved when no usable inputs. Replacement behaviour **specified but untested** until `RISK-3`/`RISK-4` run. |
| **D28** | **Prototype sensor thresholds retained** for SIM-01…SIM-06 as simulated demonstration inputs only, SIMULATED label visible wherever readings appear. **Unvalidated — never to be represented as real municipal thresholds.** |

### Stack, unchanged from the brief

React + Vite + TypeScript · Leaflet + OSM · Python + FastAPI · Supabase PostgreSQL + PostGIS ·
OSM graph + NetworkX · Open-Meteo (INAMHI by manual entry) · SRTM 30 m · light teal/navy, mobile-first,
English-primary.

Four declared exceptions, none a technology swap: INAMHI is manual not automated; GEOGloWS is added as
the river signal; terrain is downgraded to static context; return-period framing is unavailable.

### Verified by execution (E2)

Open-Meteo rainfall and elevation · SRTM 30 m tiles · Guayaquil road-graph routability (96.9 % one
component, 1.34× detour) · GEOGloWS `getriverid` + `forecaststats`, and the `returnperiods` 500 ·
routing-invariant probe · dependency wheel availability · Overpass User-Agent requirement.

---

## 3. Remaining limitations

Ordered by consequence. **R9 is first because it cannot be engineered away.**

| # | Limitation | Can it be fixed? |
|---|---|---|
| **R9** | **The flood-risk score is an unvalidated heuristic.** Never checked against observed flood depths. It is not a hydrological model. | **No.** No ground truth exists for a hackathon. Mitigation: label it, show its inputs, show its coverage, refuse to estimate when evidence is thin. |
| R1 | Cold start ~60 s on first pitch request (Render free spins down after 15 min) | Mitigated by mandatory warm-up, not eliminated |
| R2 | Supabase pauses after 1 week idle | Mitigated by pre-pitch re-wake |
| R9b | "Safe" can never be proven about a route — only "no known hazards" | Inherent. Handled by vocabulary ban. |
| R9c | Sensors are simulated; `SIM-1` proves labelling, not reality | Inherent to the prototype |
| R5 | Python 3.14 may fail to install despite wheels existing | Fallback to 3.13, pinned libraries unchanged |
| R4 | GEOGloWS endpoints may break further (`returnperiods` already 500) | Degradation matrix; no substitute numbers |
| R6 | OSM completeness outside the sampled bbox unknown | Measure per sector before promising routes |
| R7 | Open-Meteo non-commercial licence unconfirmed | Owner decisions; attribution shipped |
| R8 | Tile source legality under judged load | Self-host the demo bbox |
| R12 | Single-developer bus factor during a hackathon | AGENT.md handover discipline |

**Not claimed anywhere:** real-world predictive accuracy, uptime, measured river level, official alert
dispatch, verified shelter availability, or municipal authority.

---

## 4. The six decisions — RESOLVED 2026-10-25

All six were put to the owner and **answered on 2026-10-25**. They are recorded as **D23–D28** and are
no longer open. The option tables are retained below as the decision record, not as pending questions.

### O-1 → **D23** — Precautionary floor: reports + closures active, heavy-rain trigger disabled

**1a — decided (iii):** the heavy-rain trigger is **not activated**. The 40 mm/6 h figure in §8's
`rain_score` is a **risk-scoring input, not an approved public warning threshold**. No defensible
threshold and source exists, so nothing is invented.

**1b — decided (b), conditionally:** the floor mechanism is retained for **verified reports** and
**operator-confirmed road closures** only, with its numbers marked **provisional and unvalidated**. It is
never presented as scientifically validated. The principle is preserved: **a floor can raise risk, never
lower it**.

| Option | Outcome |
|---|---|
| (a) no floor | rejected — would reinstate the suppression fixed by D18 |
| **(b) floor for reports + closures, rain disabled** | **ADOPTED (conditional)** |
| (c) any single trigger → ≥3 | rejected — alarm fatigue |

**Remaining consequence:** until a sourced heavy-rain threshold exists, the public forecast UI shows
absolute mm and probability **without** a "heavy rain" label (Stage 1 §6 already mandates this fallback).
Tracked as blocker **B13**.

### O-2 → **D24** — Low/zero-coverage routes: serve, never recommend

**Decided (a).** Serve low- and zero-coverage routes with a **prominent uncertainty warning**, the
**actual coverage percentage**, and the **unknown/stale status detail**. Such routes are **never described
as verified-safe**. **Known closures remain excluded from ordinary eligible routes** — the two-phase search
is unchanged.

### O-3 → **D25** — 60 % boundary retained provisionally

**Decided (a).** 60 % is the **recommendation boundary, not a serve/withhold gate**. It is documented as an
**unvalidated product decision, not a measured safety threshold**, and no document may claim it is
empirically established.

### O-4 → **D26** — Hard bilingual publishing block stands

**Decided (a).** The existing Stage 2 gate is **unchanged**: headline *and* body required in **English and
Spanish** before publication. **No override is introduced.** Emergency handling follows the currently
approved workflow unless a separate requirement change is proposed and approved.

> This was the one item that would have amended an **approved** Stage 2 requirement. The owner chose to
> preserve the approved requirement, so **Stage 2 is untouched**.

### O-5 → **D27** — Sensor-coverage severity cap permanently removed

**Decided (a).** Coverage affects **confidence** and the **insufficient-evidence indicator only**, never
severity. "Unable to assess" is preserved when there are no usable inputs. The replacement behaviour is
**specified but untested** until `RISK-3` / `RISK-4` actually run.

### O-6 → **D28** — Prototype sensor thresholds retained, labelled

**Decided (a).** SIM-01…SIM-06 keep their prototype values as **simulated demonstration inputs only**. The
**SIMULATED label stays visible** wherever these readings appear. Documented as **unvalidated**, and they
must **never** be represented as real municipal flood thresholds.

---

## 4a. Provisional and unvalidated values — explicit register

Requirement 3 of the owner's instruction: record every provisional threshold honestly. These are **not**
evidence-backed safety values.

| Value | Where | Status |
|---|---|---|
| Floor: ≥3 for 3+ verified reports | §8.4 | **Provisional, unvalidated** — no measurement of false-alarm rate |
| Floor: ≥3 for any operator-confirmed closure | §8.4 | **Provisional, unvalidated** |
| Floor: ≥2 for heavy rain | §8.4 | **DISABLED** (D23) — no defensible threshold or source exists |
| "Heavy rain" threshold in mm/h | Stage 1 §6 | **UNDEFINED** — B13; UI must omit the label |
| Coverage bands 80 / 60 / 0 | §9.1 | **Product judgement** for legibility; 60 % provisional (D25) |
| "30–40 % of segments unverified" | §9.1, §9.2 | **Never measured** — treat as an assumption, not a figure |
| Risk weights .30/.30/.15/.15/.10 | §8 | **Unvalidated heuristic** — not fitted to any observed flood data |
| `rain_score` saturation at 40 mm/6 h, 80 mm/24 h | §8 | **Scoring input only** — not a warning threshold (D23) |
| Sensor thresholds 0.80–1.20 m (SIM-01…06) | Stage 2 §6 | **Prototype values** (D28) |
| Recommendation boundary 60 % | §9.1 | **Provisional** (D25) |

---

## 4b. Carried forward, not Stage 3 blockers

`TQ1` tile source for the judged submission · `TQ2` Open-Meteo commercial status · `TQ3` demo sectors and
count · `TQ6` photo retention (Stage 1 `Q7`) · `AQ1` admin accounts and who plays Publisher · `AQ3` alert
window default and cap · `AQ5` audit-log public visibility · Stage 1 `Q8` (mockup or not) · **B13** no
defensible heavy-rain threshold.

---

## 5. Exactly where implementation would begin

**No implementation has begun.** Nothing is installed, no schema applied, no code written, no commit,
no push, no deploy.

On your explicit approval of Stage 3, the sequence is:

1. **Record approval** — update `PHASES.md` §2 to APPROVED with the date. Nothing else changes.
2. **Present Stage 4** — other requirements and the implementation plan (MVP vs secondary vs future, demo
   scenario, milestone breakdown, risk register). **Then stop and await approval again.** Stage 4 is the
   fourth and last gate; implementation is Stage 5.
3. Only after Stage 4 approval would Stage 5 begin, and it would begin with **milestone M0**:
   ```
   python3 -m venv .venv            # pip is absent from PATH: bootstrap via ensurepip
   .venv/bin/pip install -r backend/requirements.txt
   .venv/bin/python -c "import fastapi, networkx, numpy, pydantic"   # import smoke test
   .venv/bin/uvicorn --version
   cd frontend && npm ci && npm run build
   ```
   M0 is complete only when the resolved `pip freeze` and `package-lock.json` are captured. If it fails:
   recreate the venv on Python 3.13, keep every pin unchanged, and report the failure — no silent
   library swaps.

**So the precise point where implementation would begin is:** the first shell command of milestone M0,
executed only after Stage 4 has been approved. Nothing before that.

---

## 6. Standing constraints

- Never run `git commit` — including amend, empty, scripted, or milestone commits. Enforced by D1.
- No push, no deploy, no dependency install, no schema application before Stage 4 approval.
- Stage 1 and Stage 2 decisions preserved; this revision does not reopen them.
- Nothing is described as passing, working, or secure until its test output exists and is cited.
