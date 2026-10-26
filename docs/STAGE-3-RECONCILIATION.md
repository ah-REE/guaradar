# Stage 3 Cross-Document Reconciliation — Final Report

**Date:** 2026-10-25
**Scope:** `docs/STAGE-3-ARCHITECTURE.md`, `docs/STAGE-3-DECISION-SUMMARY.md`, `docs/EVIDENCE-STATUS.md`
**Outcome:** reconciled. **At the time of writing, Stage 3 remained unapproved**, awaiting the owner's
decision. **Stage 3 was approved on 2026-10-26.**
**Boundaries held:** documentation only. No Stage 4, no Stage 5, no installs, no schemas, no services, no
deploys, no Git operations of any kind.

> **Later the same day:** the owner resolved all six decisions O-1…O-6 as **D23–D28** (see
> `docs/STAGE-3-DECISION-SUMMARY.md` §4). This report is preserved as the record of the reconciliation that
> raised them. Its "43 properties" figure was accurate at the time; the live count is now **44**, after a
> `RISK-4d` test was added to assert the rain floor trigger stays disabled.

---

## 1. What was inspected

Read in full before editing:

| File | Lines read | Role |
|---|---|---|
| `docs/STAGE-3-ARCHITECTURE.md` | all (≈1,400) | primary record |
| `docs/STAGE-3-DECISION-SUMMARY.md` | all (194) | decision digest |
| `docs/EVIDENCE-STATUS.md` | all (132) | evidence authority |
| `docs/STAGE-1-PUBLIC-INTERFACE.md` | relevant sections (§4, §6, §8, §9, §11, §14, §17) | approved source, checked not changed |
| `docs/STAGE-2-ADMIN-INTERFACE.md` | relevant sections (§2, §6, §9, §12, §13, §17) | approved source, checked not changed |
| `PHASES.md`, `AGENT.md` | status + decision tables | consistency check |
| `research/routing_invariant.py` | full | re-ran to confirm the earlier result |

The interaction probe and the risk arithmetic were **re-executed** during this review rather than trusted
from memory; both are reproduced below.

---

## 2. Cross-document findings

| # | Finding | Files / sections | Status | Basis |
|---|---|---|---|---|
| **C-1** | **The sensor-coverage cap suppressed emergencies.** `coverage < 0.6 ⇒ level capped at 2` is unsatisfiable with stale sensors, because losing sensor+trend weights caps coverage at **0.55** — permanently below the threshold. Every sensor outage therefore capped the level at Caution regardless of rain, reports or closures. | S3 §8 hard rule 1, §8.1, §8.2; S3 §17.1 `RISK-3`/`RISK-4`; DECISION-SUMMARY §2 | **RESOLVED** | Safety defect, proven by arithmetic. Replacement: severity/confidence separation + precaution floor (D18, D19). Cap withdrawn; `RISK-3`/`RISK-4` rewritten to assert its absence. |
| **C-2** | **Route coverage policy was self-contradictory.** "Rejection criterion at 60 %" coexisted with Marginal at 40–59 % and Unknown-only at 0 % verified. Three distinct facts (connectivity, hazard crossing, verified coverage) were collapsed into one threshold. | S3 §9 route-search step 6, §9.1; DECISION-SUMMARY §1.1 | **RESOLVED** | Logical contradiction. Replaced by (hazard class × coverage band) with all 8 combinations defined; "rejection" narrowed to no-path or snap > 60 m (D20). |
| **C-3** | **Rain-versus-sensor rule was unsafe.** "Level driven by the sensor, because it is the observation" let one low reading outvote heavy rain, verified reports and closures. | S3 §8.3 | **RESOLVED** | Safety defect. All inputs now contribute; floors may raise; disagreement stated not averaged; `RISK-8b`/`RISK-8c` added (D21). |
| **C-4** | **Stage 1 sample strings were partly Spanish-first** while the approved policy is English-primary. Tabs, `RIESGO ACTUAL`, `AVISO NARANJA`, `Reportar inundación`, route sample rows. | S1 §2 mockup, §4 nav, §6, §9, §11, §13; S3 (no i18n section existed) | **RESOLVED** — illustrative strings corrected to English-first. **No approved behavioural requirement changed.** | Approved D8 + owner's explicit instruction not to reinterpret it. Stage 1 §4/§11 already state English-primary, so there was no approved-requirement conflict to escalate. |
| **C-5** | **No i18n specification existed in Stage 3** despite approved English-primary/Spanish-secondary policy and a bilingual publish gate in Stage 2. Fallback, locale files, locale-sensitive formatting and completeness were unspecified. | S3 (absent); S2 §8 publish gate | **RESOLVED** — new S3 §15 | Approved Stage 2 gate required it; absence was a documentation gap. |
| **C-6** | **LIVE/SIMULATED/MIXED indicator required by approved Stage 2 §13 was absent from Stage 3** — no server-side definition of how the mode is produced. | S2 §13; S3 (absent) | **RESOLVED** — new S3 §10.1 + `SIM-3` | Approved Stage 2 requirement. Noted that `LIVE` is **unreachable** in this project because every sensor is simulated. |
| **C-7** | **Safety-property count was stale.** Documents cited "32 properties" but the list had drifted. | S3 §17.1; DECISION-SUMMARY; EVIDENCE-STATUS; AGENT.md | **RESOLVED** — recounted mechanically: **43** ids. All citations updated. | Mechanical count of stable ids. Growth explained: every addition guards a defect found in this review. |
| **C-8** | **Section numbering was out of order** (§8.5 before §8.3; earlier §9.3 before §9.1) and a duplicate `## 16` existed after inserting the i18n section. | S3 §8, §9, §15–§21 | **RESOLVED** — §8.1–8.5 sequential, §15 i18n, §16 offline, §17 testing, §18 env/costs, §19–21. | Readability for review; a reviewer must not meet a conclusion before the rule it justifies. |
| **C-9** | **`RISK-4b` was defined then deleted** during editing, leaving a gap in the id sequence. | S3 §17.1 | **RESOLVED** — merged into `RISK-4`; `RISK-4c` added for the floor. Sequence now contiguous. | Self-inflicted during editing; recorded rather than hidden. |
| **C-10** | Two overreaching phrasings: "`[standard]` is safe" (a metadata observation, not a safety proof). | S3 §18; REVIEW-RESPONSE §6 | **RESOLVED** — reworded as "has an install path on 3.14 (E1); installation unproven until M0". | E0–E4 discipline. |
| **C-11** | `AQ2` in Stage 2 was still formatted as an open question although resolved. | S2 §17 | **RESOLVED** — labelled `RESOLVED 2026-10-25` with rationale retained. | Consistency with PHASES D11. Not a redesign. |
| **C-12** | GEOGloWS `returnperiods` HTTP 500 was documented in S3 and EVIDENCE-STATUS but not in DECISION-SUMMARY's verified list. | DECISION-SUMMARY §2 | **RESOLVED** — added to the E2 list. | Existing evidence, unchanged. |
| **C-13** | Terminology drift: "Eligible / Marginal / Hazard-crossing / Refused / Unknown-status-only" vs the new pair model. | S3 §9.1, §9.3; DECISION-SUMMARY §1.1 | **RESOLVED** — one vocabulary: hazard class ∈ {Clear, Hazard-crossing}, band ∈ {High, Moderate, Low, None}, plus "Recommended" as a rank property. | Removes the ambiguity that produced C-2. |
| **C-14** | **OPEN — no approved requirement decides** serve-vs-withhold for Low/None coverage beyond "visually demoted". | S1 §9; S3 §9.1 | **OPEN (O-2)** | Stage 1 says demote, not withhold, so the current proposal is consistent with approved text; but whether a hard floor should exist is a product call. Flagged, not decided. |
| **C-15** | **OPEN — the precautionary floor thresholds** (heavy rain ⇒ ≥2, 3+ reports ⇒ ≥3) are invented. | S3 §8.4 | **OPEN (O-1)** | No validated flood threshold exists in the approved material and none is claimed. Proposed only. |
| **C-16** | **OPEN — the 60 % boundary itself** is a round number, not evidence-derived. | S1 §9; S3 §9.1 | **OPEN (O-3)** | Stage 1 approved "demoted", not the number. Kept, flagged as arbitrary. |

---

## 3. The arithmetic behind C-1 (re-executed during this review)

```
weights: rain .30, sensor .30, trend .15, report .15, road .10
all sensors stale  =>  sensor + trend unavailable  =>  available = .55  (max achievable)

rain 1.0, reports 1.0, roads 1.0  -> score 1.00  coverage 0.55
    uncapped 4 Emergency   capped 2 Caution     SUPPRESSED
rain 1.0, reports 0.8, roads 0.8  -> score 0.91  coverage 0.55
    uncapped 4 Emergency   capped 2 Caution     SUPPRESSED
rain 0.9, reports 0.4, roads 0.4  -> score 0.67  coverage 0.55
    uncapped 3 Alert       capped 2 Caution     SUPPRESSED
```

Because **0.55 < 0.6 always** when sensors are out, the cap was not an edge case — it was the guaranteed
outcome of every sensor outage. That is why this is recorded as a defect rather than a tuning question.

---

## 4. Canonical Stage 3 decisions (reconciled)

### 4.1 Route eligibility and coverage

- Described by a **pair**: hazard class (`Clear` | `Hazard-crossing`) × coverage band (`High ≥80`,
  `Moderate 60–79`, `Low 1–59`, `None 0`), length-weighted, using only verified-and-fresh status.
- `Clear` always outranks `Hazard-crossing`; within `Clear`, higher coverage first; ties by duration.
- **Recommended** = rank 1 with normal visual weight, requires `Clear` **and** `Moderate`+ coverage.
- **Refused only** for no path or snap > 60 m. Low/None coverage routes are **served but never recommended
  and never described as verified**.
- Two-phase search preserved: phase 1 has no closed edges; phase 2 restores them and its result is always
  `Hazard-crossing`. A successful search proves a path exists — nothing more.
- No route caching (D14); status applied at query time.

### 4.2 Stale sensors, evidence coverage, risk escalation

- **Severity** ← weighted score of available inputs, plus a precaution floor that can only raise.
- **Confidence** ← `coverage` (High ≥0.85, Medium ≥0.60, Low <0.60). Coverage never modifies severity.
- **Freshness** ← per-source; expired status stops counting as verified, lowering coverage and forcing
  `Stale` chips. It does not reduce severity.
- **`Unable to assess`** ← only when zero inputs are usable. Never Level 1.
- Precaution floor is **proposed, unvalidated, needs approval (O-1)**.

### 4.3 Language

English primary (default, `/en`), Spanish complete secondary (`/es`, visible toggle, locale in URL). Both
interfaces fully bilingual. Missing ES key **fails the build**; missing-at-runtime falls back to English
**with a label**. Safety-critical strings (severity words, chips, alert text, route copy, refusals,
emergency numbers) must exist in both before rendering. Metric units only; locale number/date formatting;
timezone offset always shown. Alerts require both languages unless a logged Publisher override is used
(O-4).

### 4.4 Risk formula and conflicting inputs

Renormalised weighted sum over available inputs; **no input holds a veto**; a missing input never lowers
severity; floors may raise; conflicts are reported, never averaged; a low reading cannot mask a cluster of
high readings; operator override may raise freely but must justify any lowering. Weights unchanged
(0.30/0.30/0.15/0.15/0.10) — no new thresholds beyond the flagged floor.

### 4.5 Provenance and freshness

Chip computed **server-side** in the envelope (`PROV-1`, `PROV-2`); five states with words, not colour
alone; absolute timestamps plus relative age; source attribution per value; simulated readings labelled at
the marker, in exports and in the mode banner; alerts are app-internal only; modelled discharge always
labelled; risk level always labelled an unvalidated heuristic.

### 4.6 Terrain

SRTM 1-arcsec ≈30 m, approximate, **static context only**. Measured 4–14 m; 30 m vs 90 m differences are
comparable to the city's relief. May not rank streets, predict depth, or imply live conditions. Any
rendered elevation carries "approximate, SRTM 30 m" (`TERR-1`, `TERR-2`).

### 4.7 Evidence and feasibility

Ceiling **E2**. 43 properties specified, **none executed**. Clean install, build, run, and predictive
accuracy all **not established**. Python 3.13 fallback retained with pins unchanged. Free-tier hosting is
terms-dependent, not guaranteed.

---

## 5. Files changed

| Path | Change |
|---|---|
| `docs/STAGE-3-ARCHITECTURE.md` | §8 rule 1 rewritten (cap withdrawn); §8.1 coverage semantics; §8.2 stale-sensor table; §8.3 conflict rules rewritten; **new §8.4 severity-vs-coverage with arithmetic and precaution floor**; §8.5 determinism renumbered; §9.1 replaced with class×band policy; route-search steps 2/3/6 corrected; **new §10.1 LIVE/SIMULATED/MIXED**; **new §15 internationalisation**; §16 offline; §17 testing renumbered with `RISK-3/4/4c/8b/8c`, `ROUTE-2b/2c/2d`, `SIM-3`, `I18N-1…4`; §18–21 renumbered; dependency-risk wording corrected; property count stated as 43 |
| `docs/STAGE-3-DECISION-SUMMARY.md` | §1 rewritten as reconciliation of C-1…C-5; D18–D22 added; verified list gains GEOGloWS `returnperiods`; **new §4 decisions requiring approval (O-1…O-6 + carried items)**; §5 implementation entry point; §6 standing constraints |
| `docs/EVIDENCE-STATUS.md` | property section 32→43 with explanation; downgrade log gains entries **9–13** (cap withdrawal, route contradiction, sensor-veto, Spanish-first strings, missing data-mode) |
| `AGENT.md` | "32 safety properties" → 43; §17.1 reference corrected |
| `docs/STAGE-1-PUBLIC-INTERFACE.md` | **illustrative strings only** corrected to English-first with Spanish labels; header status set to APPROVED. No behavioural requirement altered. |
| `docs/STAGE-2-ADMIN-INTERFACE.md` | `AQ2` marked RESOLVED with rationale retained. No requirement altered. |

**Not modified:** `PHASES.md` beyond status wording, `docs/DATA-SOURCES.md`, `research/*.py` (inspected and
re-run, unchanged), `.zwork/` attachments. No application code exists to modify.

**Correction history preserved:** `EVIDENCE-STATUS.md` §Downgrade log retains all eight prior entries and
gains five more. Nothing was removed to make the project look cleaner.

---

## 6. Decisions requiring approval

Summarised here; full trade-offs in `docs/STAGE-3-DECISION-SUMMARY.md` §4.

| # | Decision | Proposal | Why it needs you |
|---|---|---|---|
| **O-1** | Precautionary floor (may a credible signal raise the level when sensors are absent?) | Floor: heavy rain ≥2; 3+ verified reports ≥3; any closure ≥3 | Invents a policy. Restores a warning the old cap suppressed, at the cost of possible labelled false alarms. |
| **O-2** | Low/None-coverage routes: serve-but-demote or withhold | Serve, never recommend | Approved Stage 1 says "demote", not "withhold" — so this follows approved text, but a hard floor is a real alternative. |
| **O-3** | Is the 60 % Recommended boundary right? | Keep 60 %, flagged arbitrary | Not evidence-derived; a product judgement. |
| **O-4** | Publishing with a missing translation | Logged Publisher override | Stage 2 currently blocks publication; blocking can delay a real warning. |
| **O-5** | Any narrower resurrection of the coverage cap | No | Confirming the withdrawal is permanent. |
| **O-6** | Invented sensor thresholds | Keep, labelled | No real Guayaquil threshold data available to this project. |

Carried and still open: `TQ1`–`TQ4`, `TQ6`, `AQ1`, `AQ3`, `AQ5`.

---

## 7. Final status

| Stage | Status |
|---|---|
| **Stage 1 — Public Interface** | **APPROVED** (2026-10-25). Behavioural requirements unchanged; only illustrative copy corrected. |
| **Stage 2 — Admin Interface** | **APPROVED** (2026-10-25). Requirements unchanged; one resolved question relabelled. |
| **Stage 3 — Architecture** | **RECONCILED — awaiting the owner's approval.** Not self-approved; three safety defects were found and fixed, and six decisions (O-1…O-6) still need your call. |
| **Stage 4 — Requirements + Plan** | **NOT STARTED.** |
| **Stage 5 — Implementation** | **NOT STARTED.** |

**Confirmed factually true for this task:** no dependencies were installed; no virtualenv created; no
schema created or applied; no service started; no build run; no deployment performed; no `git commit`,
amend, or any other Git write operation executed. No application code was written. The only executions were
read-only arithmetic and the existing `research/*.py` probes, run to re-confirm earlier findings.

**Not claimed:** that Guaradar is safe, validated, tested, deployable, or that its risk model predicts
flooding. It is a planning package at evidence level **E2** with three previously unsafe rules now
withdrawn and six decisions awaiting the owner.

**Stopping here** per the stop condition. Awaiting explicit approval before Stage 4.
