# M3 — Graph Artifact + Two-Phase Routing: Evidence

**Date:** 2026-10-26
**Milestone:** M3 (Stage 4 §16.2 blocks 3–4)
**Verdict:** **PASSED** — 86 tests pass, 1 deliberately skipped, the two-phase guarantee holds.
**The graph is synthetic and labelled as such.** It is not Guayaquil.

---

## 1. Files

| Path | Purpose |
|---|---|
| `backend/app/routing/graph.py` | immutable topology, status index with staleness rules, synthetic builder, OSM builder (untested) |
| `backend/app/routing/search.py` | two-phase search, coverage arithmetic, eligibility policy, D29 tie-break |
| `backend/tests/unit/test_routing.py` | 45 routing tests named after `ROUTE-*` properties |
| `backend/app/routing/__init__.py` | package marker |
| `docs/M3-EVIDENCE.md` | this file |

No new dependencies. No database access — M3 is pure in-memory work on top of the M1 schema shape.

---

## 2. Graph statistics (synthetic demo graph)

Built by `build_synthetic_grid` over the three approved sectors, with a spine connecting them.

```
nodes                    147
edges                    254
total_length_m           40325.5
junctions                135
junctions_pct            91.8
mean_degree              3.46
components               1
largest_component_pct    100.0
synthetic                True
```

**One component, 100 % connected.** That is deliberate: the graph must never be accidentally
disconnected, or every route would be refused and the failure would look like a routing bug.

### ⚠ This is not Guayaquil

The demo graph is a **grid generated from sector centres**, not an OSM extract. Consequences that must
not be glossed:

- Geometry is not surveyed. Streets do not exist at these coordinates.
- 40.3 km of network versus the **1,184.9 km measured from real OSM data** in `research/graphcheck.py`.
- Every edge name begins `synthetic-`, every node and edge carries `synthetic=True`, and every response
  carries a note saying so.
- **Coverage percentages describe this demo dataset only.** They are not a statement about Guayaquil.

`build_from_osm_json()` is written and present so the synthetic graph can be swapped without touching
search code — but it is **untested against a real payload** (see §6).

---

## 3. Behaviour implemented

### The two-phase guarantee (§9.3, D16)

```python
# phase 1 — closed edges are ABSENT from the search
path = _dijkstra(graph, src, dst, status, exclude_closed=True)
# phase 2 — only if phase 1 yields nothing; closures restored, result labelled
if not phase1:
    path = _dijkstra(graph, src, dst, status, exclude_closed=False)
```

The exclusion is applied to the **edge**, not to a cost multiplier:

```python
def allowed(edge_id):
    if exclude_closed and status.is_closed(edge_id):
        return False
    return True
```

So no floating-point comparison can accidentally readmit a closure. If phase 1 somehow returned a
hazard-crossing route, `find_routes` raises `AssertionError` — the invariant is asserted, not assumed.

### Cost factors (§9 step 2), and the one asymmetry

| Status | Treatment in phase 1 | Treatment in phase 2 |
|---|---|---|
| `closed` | **removed** | restored, × 50 |
| `affected` | × 2.5 | × 2.5 |
| `unknown` | × 1.15 (nudge, not a wall) | × 1.15 |
| stale (past freshness) | × 1.1 | × 1.1 |

`StatusIndex.cost_factor()` **raises** if asked to price a closed edge. That guard is what makes it
impossible to silently drift back to the refuted penalty design; `test_status_index_rejects_costing_a_closed_edge`
locks it in.

### Coverage (§9 step 5, §9.1)

Length-weighted, verified-only:

```
coverage_pct = 100 * Σ(verified edge length) / Σ(edge length)
```

Bands, inclusive at the bottom, on the rounded value: **High ≥ 80**, **Moderate 60–79**,
**Low 0.01–59**, **None 0**.

**A closed edge never counts as verified.** A closure tells you a road is impassable; it does not verify
that travelling it is fine. Same for `unknown`.

### Eligibility (§9.1, D24/D25)

| Class | Band | Served | Recommended |
|---|---|---|---|
| clear | high / moderate | yes | **yes (rank 1 only)** |
| clear | low / none | yes | **no** |
| hazard_crossing | any | yes, last | **never** |
| — | disconnected or snap > 60 m | **refused** | — |

Exactly one route can be `recommended`, and only if it is clear **and** moderate-or-better.

### D29 elevation tie-break — structural, not disciplinary

Sort key: `(hazard_class_rank, band_rank, duration_s, ±elevation)`.

Because class and band are compared **before** duration and elevation, no elevation value can move a
route across a class or band boundary. That is D29 limits 2 and 3 holding by construction.

The tie-break is **detected and disclosed**: `elevation_used_as_tiebreak=True` is set only when two
adjacent routes are identical on the first three terms and differ in elevation, so the UI can show:

> "Tie broken using approximate terrain (SRTM 30 m, ±4 m). This does not establish that the route is safe."

### Automatic refusals (§9 steps 1, D24)

Refused, with a reason, when:
- the origin is > 60 m from any node;
- the destination is > 60 m from any node;
- the graph is empty;
- no path exists even with closures restored.

`all_routes_hazard_crossing` and `best_available_is_uncertain` are returned as first-class flags so a
client cannot omit them (§9.1).

---

## 4. Test results — actual output

```
$ cd backend && ../.venv/bin/python -m pytest
........................................................................ [ 82%]
..............s                                                          [100%]
86 passed, 1 skipped in 0.18s
```

```
$ ../.venv/bin/python -m coverage run --branch -m pytest -q
$ ../.venv/bin/python -m coverage report --include="app/domain/*,app/routing/*"
app/domain/risk.py        250      0    102      0   100%
app/routing/graph.py      229     23     90      0    88%   111, 444-478
app/routing/search.py     226      5     98      8    96%
TOTAL                     705     28    290      8    95%
```

The **100 % branch gate applies to `domain/` only** (Stage 3 §17.2) and still holds. Routing is at
88 %/96 %; the uncovered lines are named in §6 rather than hidden.

### `ROUTE-*` property status

| Property | Test(s) | Status |
|---|---|---|
| `ROUTE-1` | `test_ROUTE_1_phase1_never_crosses_a_closure`, `test_ROUTE_1_phase2_only_when_phase1_fails`, `test_ROUTE_1_no_dry_route_is_distinct_from_no_path` | **PASSED** |
| `ROUTE-1b` | `test_ROUTE_1b_two_phase_beats_finite_penalty` | **PASSED** — asserts the penalty design would have chosen the 5 m closed edge over 41 × 600 m, and that the implementation does not |
| `ROUTE-2` | `test_ROUTE_2_coverage_is_length_weighted` (4.2 km / 1.8 km → 42.86 %), `test_ROUTE_2_coverage_not_edge_count` | **PASSED** |
| `ROUTE-2b` | `test_ROUTE_2b_band_boundaries_exact` (7 parametrised cases), `test_ROUTE_2b_closed_edges_do_not_count_as_verified` | **PASSED** |
| `ROUTE-2c` | `test_ROUTE_2c_zero_coverage_served_but_not_recommended`, `test_ROUTE_2c_low_coverage_is_demoted_below_moderate` | **PASSED** |
| `ROUTE-2d` | `test_ROUTE_2d_clear_outranks_hazard_crossing_always` | **PASSED** |
| `ROUTE-3` | `test_status_change_affects_routing_without_cache` | **PASSED (engine-side)** — no cache exists by construction (D14); the API-level test lands in a later milestone |
| `ROUTE-4` | `test_ROUTE_4_route_labels_never_say_safe`, `test_ROUTE_4_no_known_hazards_phrasing_available` | **PASSED** |
| `ROUTE-5` | `test_ROUTE_5_snap_beyond_limit_refuses`, `test_ROUTE_5_snap_within_limit_proceeds` | **PASSED** |
| `ROUTE-6` | `test_ROUTE_6_all_hazard_crossing_flag`, `test_hazard_crossing_never_recommended_even_if_only_option` | **PASSED** |
| `ROUTE-7` | `test_ROUTE_7_stale_status_removes_verification`, `test_ROUTE_7_stale_majority_is_not_eligible` | **PASSED** |
| `ROUTE-8` | `test_ROUTE_8_elevation_cannot_cross_a_class_boundary`, `test_ROUTE_8_elevation_cannot_cross_a_band_boundary` | **PASSED** |
| `ROUTE-9` | `test_ROUTE_9_elevation_is_last_sort_term`, `test_ROUTE_9_removing_elevation_changes_nothing_but_ties` | **PASSED** |

**R-17 is now satisfied under option (a):** D29 conditional on `ROUTE-8`/`ROUTE-9` passing, and both pass.
Elevation remains a disclosed final tie-break. D12 is untouched — terrain still cannot rank streets.

---

## 5. The one judgement call I had to make — and flag

**Does a stale closure still exclude the edge in phase 1?**

The spec says two things that pull apart:

- §9 step 2: `stale → ×1.1` (a penalty — implying the edge stays in the graph)
- line 852: *"stale closures automatically push a route into a lower coverage band"*

If a stale closure were restored to the phase-1 graph with a ×1.1 penalty, then **a road closed three
hours ago and never re-checked could be served as `Eligible`**. That would gut `ROUTE-1` and the entire
two-phase guarantee.

**I chose the conservative reading:** a closure excludes the edge **regardless of freshness**; staleness
only removes its *verified* status, which lowers coverage. Rationale: lifting a closure is the
higher-risk direction, and the cost of a wrongly-open road is worse than the cost of a wrongly-closed one.

`test_ROUTE_7_stale_status_removes_verification` asserts exactly this: stale closures still produce
`all_routes_hazard_crossing=True` with 0 % coverage.

**This is a safety-relevant interpretation, recorded rather than buried.** If you want stale closures to
stop excluding edges after some window, that is a decision for you — see §8, O-8.

---

## 6. Uncovered code, named

23 uncovered lines in `graph.py`, 5 in `search.py`:

| Where | What | Why uncovered |
|---|---|---|
| `graph.py` 444–478 (`build_from_osm_json`) | OSM payload → graph | **No network extraction was run in M3.** Untested against real data. Marked with a skipped test so it cannot quietly look verified. |
| `graph.py` 111 | `Edge.mean_elevation()` | convenience accessor never called by search |
| `search.py` 120, 195, 218 | internal defensive returns (`_dijkstra` early exits) | reachable only in states the public API cannot produce |
| `search.py` 526, 533 | alternative-loop `break` paths | need a graph with fewer routes than `max_alternatives` |
| partial branches | `if graph.synthetic:` false path | every graph in this project is synthetic; a real extract would exercise it |

**Not claimed:** these are covered. They are listed so nobody assumes the routing module is fully tested.

---

## 7. Live behaviour sample

Sparse closures (1 in 40 edges), three sectors, 5-minute-old statuses:

```
refused: False   all_hazard: False   uncertain: True
  phase=1 clear  band=low  cov=43.7%  rec=False  closed=[]
  phase=1 clear  band=low  cov=42.7%  rec=False  closed=[]
  phase=1 clear  band=low  cov=44.8%  rec=False  closed=[]
PHASE-1 ROUTES CROSSING A CLOSURE: 0
distinct edge-sets: 3 of 3
```

Three genuinely distinct alternatives, zero closures crossed, and **none recommended** because coverage
is Low — which is D24 working: served, never recommended.

Dense closures (1 in 7 edges) forces phase 2:

```
refused: False   all_hazard: True
  phase=2 hazard_crossing band=low cov=44.8% rec=False closed_edges=1
   No route avoids all closures. This route crosses a closed road.
```

---

## 8. Blockers and decisions

### O-8 — stale closures (see §5)

Should a closure older than its freshness window still exclude the edge in phase 1?

| Option | Effect |
|---|---|
| **(a) Keep as implemented** — a closure always excludes; staleness only removes verification | Never serves a stale closure as traversable. Cost: a re-opened road stays closed in the graph until an operator updates it. |
| (b) Honour ×1.1 literally — stale closures become penalised-but-traversable | Matches the §9 step-2 table literally. Cost: a 3-hour-old closure can be served as `Eligible`, weakening `ROUTE-1`. |

**My recommendation: (a).** But it is a safety-relevant reading of an ambiguous spec, so it is yours to
confirm or overrule.

### Carried forward

- **O-7** (`docs/M2-EVIDENCE.md` §8) — `RISK-8b` prose vs formula. **Untouched by M3.** No weight, formula
  or floor was changed. Recorded as an integration dependency: the public risk level must not be
  published as a settled safety rule until O-7 is decided.
- **`current_app_role()`** still trusts a session setting. M3 does no database work and neither fixes nor
  worsens it.
- **No OSM extract was run.** `build_from_osm_json` is unverified. Real network geometry would also change
  every coverage percentage quoted here.

---

## 9. Boundaries held

- Worked on **M3 only**. M4 not started.
- No deploy, no push, no remote, **no `git commit`** (still not a Git repository).
- No dependencies added.
- No test was weakened to make the milestone green: two failing tests were traced to **my own wrong
  assumptions** (§10) and corrected, and one label was changed to match the spec's required phrase rather
  than relaxing the assertion.
- **The risk model remains an unvalidated heuristic** and M3 makes no routing safety claim beyond
  "no known hazards in the data".

---

## 10. Defects found and fixed

| # | Defect | How it surfaced | Fix |
|---|---|---|---|
| **D-1** | **Phase 2 crashed on any closed edge.** `cost_factor()` raises when asked to price a closure (by design), but phase 2 legitimately prices them | Live run raised `ValueError: edge 0 is closed and must be filtered out, not costed` | Added `COST_FACTOR_CLOSED_PHASE2` and an explicit `allow_closed` path in `_edge_cost`, used only when `exclude_closed=False` |
| **D-2** | Route label said "Avoids known hazards" — the spec requires the exact permitted phrase **"no known hazards"** | `test_ROUTE_4_no_known_hazards_phrasing_available` failed | Label changed in the code, not the test |
| **D-3** | Synthetic-provenance note was only attached per-route, so `RouteResponse.notes` could omit it | `test_synthetic_graph_is_labelled_in_notes` failed | Note now also appended at response level for both phases |
| **D-4** | My test closed an edge in a 2-edge chain, leaving no clear path, then asserted phase 1 — wrong premise | `assert 2 == 1` | Test rebuilt with a genuine detour |
| **D-5** | My "far" snap point was 0.001° from node 0 but right next to node 1 | `assert False is True` | Test uses a point 1.1 km from every node |
| **D-6** | Stray `BAND_MOD` import referenced a constant that does not exist | collection error | Removed |

---

## 11. Budget and next

**~5.0 h of 10.75 h consumed** (blocks 0–4). Ahead of the §16.6 checkpoints.

**Next: M5 equivalent — ingestion** (Open-Meteo + sensor simulator), then public UI. Blocks 5 and 6 are the
remaining critical path; the admin console (block 8) is now the most likely cut.

Per instruction, **stopping after M3.**
