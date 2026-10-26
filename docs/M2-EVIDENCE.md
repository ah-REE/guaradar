# M2 — Risk Engine + Tests: Evidence

**Date:** 2026-10-26
**Milestone:** M2 (Stage 4 §16.2 block 2) — **the hour-4 checkpoint**
**Verdict:** **PASSED** — 41 tests, 100 % branch coverage on `domain/`, zero I/O.
**Two specification conflicts were found and are reported, not silently resolved** (§4).

---

## 1. Files

| Path | Purpose |
|---|---|
| `backend/app/domain/risk.py` | the engine — 250 statements, pure, deterministic |
| `backend/tests/unit/test_risk.py` | 41 tests named after the safety properties they defend |
| `backend/pyproject.toml` | pytest config (`pythonpath`, strict markers) |
| `backend/app/__init__.py`, `app/domain/__init__.py`, `tests/**/__init__.py` | package markers |
| `docs/M2-EVIDENCE.md` | this file |

**One dependency added:** `coverage`, to measure the 100 % branch-coverage gate required by the approved
Stage 3 §17.2. It is a test-only tool and was declared here before use.

---

## 2. Behaviour implemented — traceable to the approved spec

Every constant in the module is traceable; none was invented.

| Spec source | Implemented as |
|---|---|
| §8 Formula | `rain_score` = clamp01(max(R6/40, R24/80)); `sensor_score` = clamp01(max depth/eff-threshold); `trend_bonus` = clamp01(rise/0.3)*0.5; `report_score` = clamp01(I/5); `road_score` = clamp01(affected fraction) |
| §8 weights | 0.30 / 0.30 / 0.15 / 0.15 / 0.10, sum checked = 1.0 |
| §8 level mapping | 1 <0.25 · 2 0.25–0.45 · 3 0.45–0.70 · 4 ≥0.70, inclusive at the bottom of each band |
| §8 hysteresis | release boundaries 0.66 / 0.42 / 0.22 with a 10-minute hold |
| §8 Formula (elevation) | `effective_threshold = threshold_m * (1 + 0.15 * percentile)` — a static multiplier only (D12) |
| §8.1 | missing inputs excluded, weights renormalised by present-weight sum; `coverage` returned as data |
| §8.2 | stale-high vs stale-low asymmetry; all-stale ⇒ `sensor_score = None` |
| §8.3 | conflicts surfaced as a list, never averaged |
| §8.4 | severity and confidence computed independently; `insufficient_evidence` when coverage < 0.6, **never** a cap |
| §8.4 / D23 | floor from **verified reports (≥3 in 60 min)** and **operator-confirmed closures** only; rain trigger **absent from the code** |
| D18/D27 | no code path can lower severity because evidence is missing |
| RISK-6 | zero usable inputs ⇒ `score=None, level=None`, message "Unable to assess" |
| D28 | `simulated` defaults `True` on every reading, propagated into the result and named in the reasons |

### Design decisions worth naming

- **`now` is injected.** The engine never reads a clock, so hysteresis and staleness are testable at any
  instant without mocking. This is what makes the determinism property checkable at all.
- **`verified_reports=None` vs `()` are different facts.** `None` means the feed is unavailable (excluded,
  weights renormalise). `()` means the feed worked and contained no verified reports (scores 0.0). This
  distinction was tightened during M2 after a test exposed that an empty `RiskInputs()` was returning
  **Level 1 "Watch"** instead of "Unable to assess" — a real safety bug, fixed (see §5, D-1).
- **Validation moved to construction.** `SensorReading.__post_init__` rejects negative depth, NaN, and
  non-positive thresholds. Duplicated checks inside scoring were removed because they were unreachable —
  dead defensive code that looks like safety but never executes.
- **`HYSTERESIS[previous.level]` instead of `.get(...)`.** A `previous.level` of 1 can never satisfy
  `level < previous.level`, so the lookup is always populated. The `.get()` fallback was unreachable.

---

## 3. Exact test command and real results

```
$ cd backend && ../.venv/bin/python -m pytest tests/unit/test_risk.py
.........................................                                [100%]
41 passed in 0.07s
```

```
$ ../.venv/bin/python -m coverage run --branch -m pytest tests/unit/test_risk.py
$ ../.venv/bin/python -m coverage report --include="app/domain/*"
Name                     Stmts   Miss Branch BrPart  Cover
----------------------------------------------------------
app/domain/__init__.py       0      0      0      0   100%
app/domain/risk.py         250      0    102      0   100%
----------------------------------------------------------
TOTAL                      250      0    102      0   100%
```

**100 % statement and branch coverage on `domain/`**, which is the gate approved in Stage 3 §17.2.

### Purity verification

```
$ rg -n "^import |^from " backend/app/domain/risk.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, Sequence

$ rg -n "datetime\.now|time\.time|utcnow" backend/app/domain/risk.py
  (no implicit clock reads — now is injected)
```

No `os`, `sys`, `json`, `random`, `socket`, `httpx`, `requests`, `pathlib`. No filesystem, network,
database, or clock access. The engine is I/O-free as specified.

---

## 4. ⚠ Two specification conflicts — reported, not resolved

Both were found by running the documented formula **before** writing the implementation. Neither was
silently patched; the code follows the spec literally and the conflict is surfaced at runtime where it
matters.

### CONFLICT 1 — `RISK-8b` prose contradicts the documented formula

**Prose** (§17.1): *"no single input may reduce the level below what the remaining inputs alone would
produce."*

**Test row** (§17.1): *"removing any one input never lowers `level`."*

These point in opposite directions, and the documented formula satisfies one while violating the other:

```
heavy rain, sensors report DRY          -> score 0.312 -> level 2
heavy rain, sensors ABSENT (stale)      -> score 0.545 -> level 3

Adding the dry sensor LOWERS the level  3 -> 2   : PROSE VIOLATED
Removing the sensor RAISES the level    2 -> 3   : TEST ROW SATISFIED
```

The cause is renormalisation: removing the sensor's 0.30 weight removes a *low* value, so the remaining
inputs gain weight and the score rises. That is arithmetically correct and morally surprising.

**Why this matters today:** D23 **disabled the heavy-rain precaution floor**. That floor was the mechanism
that would have lifted this scenario back to ≥ 2 or ≥ 3. With it disabled, **nothing** prevents heavy
forecast rain from being outvoted by a single dry sensor. The engine reports it:

```
result.spec_conflicts  ->  ("RISK-8b:rain_dry_sensor",)
result.conflicts       ->  ("rain_vs_sensor", "Forecast suggests risk; sensors not yet responding...")
```

**What I did not do:** invent a precedence rule, add a rain floor, or change a weight. All three would
contradict D23 or §8.

**What needs your decision** — see §8, O-7.

### CONFLICT 2 — `trend_bonus` saturation makes the weights not sum to usable maximum

§8 says *"weights sum to 1.0"* and lists trend weight 0.15, but defines
`trend_bonus = clamp01(...) * 0.5`, capping that term at 0.5. So trend contributes at most **0.075**, and
the maximum achievable score is **0.925**, not 1.0.

```
$ every input saturated -> score == 0.925
```

Implemented literally. `test_max_score_is_below_one_because_trend_is_capped` asserts 0.925 and explains
why, so a future reader sees the anomaly rather than rediscovering it. "Fixing" it would invent a weight,
which the brief forbids.

**Consequence:** none for level mapping — 0.925 still maps to Emergency. It matters only if someone later
treats the score as a calibrated probability, which it is not.

### Undefined values, parameterised rather than invented

| Gap | Resolution |
|---|---|
| §8.2 "bounded decay window" for high-then-silent sensors — **no number given** | `high_decay_window_s` parameter, **default 0 = disabled**. A test proves the mechanism works when a window is supplied; the default keeps the unapproved behaviour off. |
| §8 "max_rise_over_1h" — ambiguous between rainfall and water level | Read as **water-level rise in m/h**, because the 0.3 m/h constant only makes sense for water. Documented in the module docstring and here. |

---

## 5. Defects found and fixed during M2

| # | Defect | How it surfaced | Fix |
|---|---|---|---|
| **D-1** | **`RiskInputs()` with no arguments returned Level 1 "Watch" instead of "Unable to assess"** — because `verified_reports` defaulted to an empty tuple, which scored 0.0 and counted as a present input | `test_RISK_6_no_inputs_is_not_assessable` failed with `assert 0.0 is None` | `verified_reports` default changed to `None`; `None` = feed unavailable, `()` = feed worked with zero reports. This distinction is now documented and tested. |
| **D-2** | Validation duplicated inside `sensor_score` was unreachable after `__post_init__` validation | Coverage showed 4 unreachable statement lines | Removed the duplicate; validation lives at construction |
| **D-3** | `_is_stale` and threshold/depth checks were unreachable in the `iterable` loop for the same reason | Coverage report | Consolidated |
| **D-4** | Hysteresis used `.get(previous.level, (None, None))` with an unreachable `None` branch | Coverage showed a partial branch | Replaced with direct indexing; the reasoning is in a comment |
| **D-5** | Rain reason builder had an unreachable `if parts:` guard | Coverage partial branch | Removed; `r_score is not None` already guarantees at least one horizon |
| **D-6** | My own test expected `score == 1.0` for a sensor-absent case while `water_rise_1h_m=0.02` was still present | Test failed with `0.4357 != 0.5455` | Test corrected to compute the documented formula exactly, not approximately |

**D-1 is the important one.** It was a genuine violation of RISK-6 — the engine would have published
"Level 1 — Watch" to a citizen when it had no information at all. Exactly the failure mode the project
exists to prevent, caught by a test that asserted the right thing.

---

## 6. `RISK-*` property status — every property, honestly

| Property | Test(s) | Status |
|---|---|---|
| `RISK-1` | `test_RISK_1_level_boundaries` (8 parametrised cases), `test_RISK_1_clamp01_edges` | **PASSED** |
| `RISK-2` | `test_RISK_2_missing_input_renormalises_not_zero`, `test_RISK_2_coverage_equals_sum_of_present_weights` | **PASSED** |
| `RISK-3` | `test_RISK_3_all_sensors_stale_does_not_lower_level` | **PASSED** |
| `RISK-4` | `test_RISK_4_low_coverage_does_not_cap_level`, `test_RISK_4_identical_score_different_coverage_same_level`, `test_RISK_4_confidence_bands` | **PASSED** |
| `RISK-4c` | `test_RISK_4c_floor_raises_never_lowers` | **PASSED** |
| `RISK-4d` | `test_RISK_4d_rain_floor_is_disabled`, `test_RISK_4d_floor_function_ignores_rain_entirely` | **PASSED** |
| `RISK-5` | `test_RISK_5_masking_inputs_never_lower_level`, `test_RISK_5_stale_high_reading_is_not_silently_zeroed` | **PASSED** |
| `RISK-6` | `test_RISK_6_no_inputs_is_not_assessable` | **PASSED** (after fixing D-1) |
| `RISK-7` | `test_RISK_7_hysteresis_holds_on_small_dip`, `test_hysteresis_holds_when_score_stays_above_boundary` | **PASSED** |
| `RISK-8` | `test_RISK_8_high_rain_low_sensor_is_surfaced`, `test_RISK_8_low_rain_high_sensor_is_surfaced`, `test_RISK_8_reports_versus_sensor_cluster_outlier` | **PASSED** |
| `RISK-8b` | `test_RISK_5_masking_inputs_never_lower_level` | **PASSED for the testable form**; **prose violated** — see CONFLICT 1 |
| `RISK-8c` | `test_RISK_8c_sensor_cannot_veto_the_floor` | **PASSED** |
| `RISK-9` | `test_RISK_9_override_fields_exist_and_default_false` | **PARTIAL** — engine represents the override; persistence and auditing are a later milestone (§7) |
| `RISK-10` | `test_RISK_10_identical_inputs_identical_output`, `test_RISK_10_determinism_over_random_inputs` (500 randomised sets) | **PASSED** |

**12 of 13 fully passed; `RISK-9` partial by design; `RISK-8b` is passing-on-its-testable-form while its
prose is contradicted by the approved formula.** I am not claiming `RISK-8b` is satisfied.

### Boundary coverage of every specified threshold

| Threshold | Test |
|---|---|
| 0.25 / 0.45 / 0.70 level bands | parametrised exactly at and either side of each |
| 0.66 / 0.42 / 0.22 hysteresis release | `test_hysteresis_holds_when_score_stays_above_boundary` hits 0.67; the release path is hit by `test_RISK_7` |
| 40 mm/6 h, 80 mm/24 h rain saturation | `test_rain_score_saturation` |
| 0.3 m/h trend, 0.5 cap | `test_trend_bonus_capped_and_never_negative` |
| 5 reports | `test_report_score_saturation` |
| 0.85 / 0.60 confidence bands | `test_RISK_4_confidence_bands` |
| 0.60 insufficient-evidence line | `test_RISK_4_low_coverage_does_not_cap_level` |
| ≥3 reports / 60 min floor | `test_RISK_4c_floor_raises_never_lowers` |
| 0.15 elevation coefficient | `test_elevation_lowers_effective_threshold` |

---

## 7. Security limitations carried forward — unchanged

The M1 limitation is **not resolved** by M2, and M2 does not touch it.

- **`current_app_role()` still trusts the `guaradar.role` session setting.** RLS is only as strong as how
  that setting is populated. The application must derive authorization from a verified identity
  **server-side**; untrusted client input must never choose a role.
- **Supabase-specific RLS behaviour remains unverified.** M1 used local PostgreSQL roles, not Supabase's
  `auth.uid()` / `authenticated` / `anon` model.
- **M2 is independent of database authorization by design.** The risk engine performs no I/O, reads no
  session, and cannot be used to escalate privilege. It neither fixes nor worsens the RLS concern.
- **No credentials were exposed and no RLS policy was weakened.** No policy was touched in M2.

Recorded as an open integration requirement for the API/authentication milestone (M5/M10 per Stage 4 §13).

---

## 8. Unresolved safety issue requiring a decision

### O-7 — `RISK-8b` prose vs the documented formula (blocking for a safety claim, not for M2)

**The question:** when heavy forecast rain and a single dry fresh sensor disagree, which wins?

| Option | Effect | Trade-off |
|---|---|---|
| **(a) Keep as implemented** — formula decides; conflict surfaced in `conflicts` and `spec_conflicts`; level may be 2 | Honest to the documented formula; no invented rule | Leaves the prose `RISK-8b` unmet, and a dry sensor can hold the level at 2 during a heavy-rain forecast |
| **(b) Re-enable the rain floor at a sourced threshold** | Restores the intended protection | Requires the threshold that **B13** says does not exist; D23 disabled it for exactly this reason |
| **(c) Allow any single danger signal to set a floor ≥ 2** | Satisfies prose | Invents a precedence rule the spec does not define, and may cry wolf |
| **(d) Amend the prose** to the testable form ("removing an input never lowers the level") | Makes documents internally consistent | Decides that a dry sensor *should* be able to outvote rain, which is a safety position I should not take alone |

**My reading:** (a) is the only option that neither invents policy nor contradicts a recorded decision, so
it is what the code does. But a citizen seeing "Level 2 — Caution" during a 60 mm/6 h forecast, because one
sensor reads dry, is a real scenario the project should not ship without your explicit choice.

**This does not block M3.** It blocks any claim that `RISK-8b` is satisfied and it must be resolved before
the public risk level is shown to anyone.

---

## 9. Hour-4 checkpoint

| Checkpoint condition (Stage 4 §16.6) | Result |
|---|---|
| Hour 4: risk engine green, or stop and report | **MET.** 41 tests pass, 100 % branch coverage, zero I/O. |

The safety core is green. Two specification conflicts are documented with options rather than papered over,
and one genuine RISK-6 violation was caught and fixed before it could ship.

---

## 10. Boundaries held

- Worked on **M2 only**. M3 not started.
- No deploy, no push, no remote configured, **no `git commit`** (still not a Git repository).
- One dependency added (`coverage`), declared for the branch-coverage gate.
- No credentials exposed; no RLS policy weakened.
- **The risk model is an unvalidated heuristic.** It has never been checked against observed flood depths.
  Nothing in this milestone establishes that it predicts real flooding, and no such claim is made.

**Budget:** ~3.25 h of 10.75 h consumed (blocks 0, 1, 2). Next: **M3 — graph artifact + two-phase search**.
