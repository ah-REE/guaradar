# M1 — Database Schema + Seed: Evidence

**Date:** 2026-10-26
**Milestone:** M1 (Stage 4 §16.2 block 1)
**Verdict:** **PASSED** — schema, RLS and seed applied and verified against a real PostgreSQL 16.2
instance. Two defects were found and fixed during the milestone; both are recorded in §7.

---

## 1. The environment problem, and how it was solved honestly

M1 needs a database. This host has **no** PostgreSQL client, no server, no Docker, no Supabase CLI, and
**no credentials** (`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL` all
unset; no `.env` file).

Rather than write SQL that was never executed, the binaries were extracted from the `pgserver` wheel
(bundles PostgreSQL for linux-x86_64) and run locally:

```
postgres (PostgreSQL) 16.2 on x86_64-pc-linux-gnu
initdb (PostgreSQL) 16.2
psql (PostgreSQL) 16.2
```

**Consequence:** every claim below about schema and RLS behaviour is **E3-tested against real PostgreSQL
16.2**, not merely written. What is *not* tested is Supabase-specific behaviour (§8).

**PostGIS is not available** in these binaries. Geometry is therefore stored as `numeric` lat/lon plus a
`jsonb` polyline — the fallback already recorded in Stage 4 §16.2 block 1. Semantics are unchanged; a
PostGIS deployment can add geometry columns later.

---

## 2. Files created

| Path | Purpose |
|---|---|
| `supabase/migrations/0001_init.sql` | 14 tables, constraints, indexes, append-only audit rules |
| `supabase/migrations/0002_rls.sql` | 5 roles, 5 authorization functions, RLS on all 14 tables, 30 policies, grants |
| `supabase/migrations/0004_rls_tests.sql` | 30 executable RLS/provenance assertions |
| `supabase/seed.sql` | deterministic demo seed, idempotent |
| `docs/M1-EVIDENCE.md` | this file |

`0004` is a test harness, not a migration — it runs inside a transaction and `rollback`s, so it changes
nothing.

---

## 3. Schema

14 tables. Every table has a provenance story: a `simulated` flag, a `source` column, a `seeded` flag, or
an `authorised_source` field.

| Table | Rows after seed | Provenance mechanism |
|---|---|---|
| `sectors` | 3 | `exposure_weight` is operator-chosen, commented as such |
| `road_segments` | 150 | `elevation_source='SRTM1'`; `osm_timestamp` null for synthetic geometry |
| `road_status` | 5 | `source ∈ {operator,system,report,seed}` |
| `sensors` | 6 | `simulated boolean NOT NULL DEFAULT true` |
| `sensor_readings` | 72 | `simulated boolean NOT NULL DEFAULT true` |
| `alerts` | 1 (draft) | `published_by` / `published_at` required to publish |
| `alert_sectors` | 1 | — |
| `incidents` | 4 | `seeded boolean NOT NULL DEFAULT false`; all 4 are `true` |
| `shelters` | 8 | `authorised_source` = `'DEMO SEED — not a municipal designation'` |
| `audit_log` | 0 | append-only rules (see §5) |
| `inamhi_bulletins` | 0 | `entered_by` + `issued_at` (manual entry) |
| `weather_cache`, `river_cache`, `alert_versions` | 0 | cached payloads carry `fetched_at` + `model_run_at` |

### Constraints that encode approved decisions

| Constraint | Decision enforced |
|---|---|
| `alerts.published_requires_bilingual` | **D26** — an alert cannot be published unless `headline_es` and `body_es` are non-empty **and** `published_by`/`published_at` are set. Enforced in the database, not only the UI. |
| `road_status.closed_needs_reason` | Stage 2 §5 — closing a road requires a non-empty reason |
| `shelters.open_requires_hold` | Stage 2 §11 — "Open" is time-boxed, cannot persist indefinitely |
| `incidents.review_requires_reviewer` | A non-pending status requires a reviewer and timestamp |
| `road_status.review_at` index | Stage 2 §5 — staleness timers, so a closure lapses to *Stale* without human action |
| `sensors.simulated DEFAULT true` | **D28** — the honest default; a real sensor must explicitly opt out |
| `road_segments.elevation_m` comment | **D12** — documented as approximate static context, forbidden from ranking |

---

## 4. RLS design and the authorization model

Five roles: `guaradar_anon`, `guaradar_viewer`, `guaradar_operator`, `guaradar_publisher`,
`guaradar_admin`. RLS is **enabled on all 14 tables** — deny-by-default — and every table received
explicit policies, because enabling RLS without policies denies everything, which is a silent outage
rather than security.

Deliberate policy positions:

- **Draft and expired alerts are invisible to `anon`.** The policy is
  `status = 'published' AND now() BETWEEN starts_at AND ends_at`. This is the mechanism that keeps an
  unpublished instruction from reaching a citizen.
- **Only `verified` incidents are public.** Pending reports — and their photos — are not.
- **`anon` may INSERT a report but never a verified one**, enforced by
  `WITH CHECK (status = 'pending' AND reviewed_by IS NULL AND reviewed_at IS NULL)`.
- **`audit_log` is append-only for every role including admin.** No UPDATE or DELETE policy exists, so
  RLS denies both; migration 0001 additionally installs `DO INSTEAD NOTHING` rules so an accidental write
  is discarded rather than applied.
- **Grants and policies are both set.** A missing grant and an over-permissive policy are equally capable
  of producing an insecure or unusable configuration, so `revoke all ... from public` precedes explicit
  grants.

---

## 5. Commands executed and actual outcomes

```
$ initdb -D /tmp/pgdata -U postgres --auth=trust --encoding=UTF8 --locale=C
  → Success. You can now start the database server...
$ pg_ctl -D /tmp/pgdata -o "-p 55432 -k /tmp -c listen_addresses=''" start
  → server started
$ psql -c "create database guaradar;"
  → CREATE DATABASE
$ psql -d guaradar -f supabase/migrations/0001_init.sql     → exit 0
$ psql -d guaradar -f supabase/migrations/0002_rls.sql      → exit 0
$ psql -d guaradar -f supabase/seed.sql                     → exit 0  (after fixing defect D-1)
$ psql -d guaradar -f supabase/migrations/0004_rls_tests.sql
  → 30 PASS, 0 FAIL, "=== ALL RLS CHECKS PASSED ==="
```

### Test results — 30/30

```
PASS: RLS enabled on all 14 tables
PASS: admin sees 3 sectors (= 3)
PASS: admin sees 6 sensors (= 6)
PASS: admin sees 8 shelters (= 8)
PASS: admin sees 150 road segments (= 150)
PASS: admin sees the 1 draft alert (= 1)
PASS: anon sees 0 alerts (draft invisible) (= 0)
PASS: anon sees only verified incidents (= 2)
PASS: anon sees 0 pending incidents (= 0)
PASS: anon sees 5 road_status rows (= 5)
PASS: anon sees 8 shelters (= 8)
PASS: anon sees 72 simulated readings (= 72)
PASS: anon sees 150 road segments (= 150)
PASS: anon denied on audit_log
PASS: anon cannot insert a verified incident
PASS: anon report stored, visible to admin (= 1)
PASS: anon denied UPDATE on road_status
PASS: viewer denied UPDATE on road_status
PASS: operator published 0 alerts
PASS: D26 enforced — bilingual fields required to publish
PASS: anon now sees 1 published alert (= 1)
PASS: anon sees 0 alerts once expired (= 0)
PASS: closed status requires a reason
PASS: audit_log UPDATE affects 0 rows (= 0)
PASS: audit_log DELETE leaves the row intact (= 1)
PASS: readings claiming to be real (= 0)
PASS: sensors claiming to be real (= 0)
PASS: demo reports not marked seeded (= 0)
PASS: shelters labelled as demo seed (= 8)
PASS: road statuses with lapsed review timer (= 1)
```

The suite was re-run against a **clean rebuild** (`guaradar2`) and again produced 30/30, so it is not
dependent on residual state from earlier attempts.

### Idempotency

Seed run three times against a fresh database:

| Run | `sensor_readings` | All other counts |
|---|---|---|
| 1 | 72 | stable |
| 2 | 72 | stable |
| 3 | 72 | stable |

Migrations 0001 and 0002 use `IF NOT EXISTS` / `DROP POLICY IF EXISTS`, so re-running them is a no-op
(verified: second run emitted only "already exists, skipping" notices).

---

## 6. What is verified vs merely implemented

| Claim | Status |
|---|---|
| Schema applies to real PostgreSQL 16.2 | **Verified** (exit 0) |
| RLS blocks anon from drafts, pending incidents, audit log | **Verified** by test |
| RLS blocks anon/viewer/operator writes where intended | **Verified** by test |
| D26 bilingual publication block works | **Verified** — monolingual publish raised `check_violation`; bilingual publish succeeded and became public |
| Expired alert disappears from public view | **Verified** |
| Closed road requires a reason | **Verified** — `check_violation` raised |
| Audit log resists UPDATE and DELETE | **Verified** — 0 rows changed, row intact |
| All sensor data marked simulated | **Verified** — 0 rows claim otherwise |
| Seed is idempotent | **Verified** — 72 readings across 3 runs |
| **Application code reads/writes these tables** | **NOT implemented.** No API, no ORM layer yet |
| **Supabase RLS behaves identically** | **NOT verified.** See §8 |
| **`current_app_role()` is safe in production** | **NOT verified.** See §8 — it trusts a session setting |

---

## 7. Defects found and fixed during M1

Recorded because a clean report would be less useful than an honest one.

| # | Defect | How it surfaced | Fix |
|---|---|---|---|
| **D-1** | Seed referenced `s.center_lat` from a `VALUES` list that does not expose those columns | `ERROR: column s.center_lat does not exist` on first run | Joined `sectors` instead of reusing the values list |
| **D-2** | **RLS test harness produced false PASSes.** `SET LOCAL ROLE` was set once, so later "anon" checks still executed as admin — and passed because admin *can* see drafts | Test 2 failed with "expected 0, got 1", exposing that the earlier checks had not actually switched role | `act_as()` now sets BOTH the SQL role and the app role, and asserts `current_user` really changed, raising if not |
| **D-3** | **Seed was not idempotent for readings.** `now() - m*5min` changes every run, so `ON CONFLICT` never matched and re-running doubled the history (72 → 144) | Explicit 3-run idempotency check | Anchored timestamps to `date_trunc('minute', now())` and added a scoped `delete ... where simulated = true` before insert |

**D-2 is the most important of these.** The first version of the security test would have certified an
unverified policy set. It was caught only because one assertion had an expected value that happened to
contradict the false assumption.

---

## 8. Security and provenance limitations — read before trusting this milestone

- **`current_app_role()` trusts a session setting.** It reads `current_setting('guaradar.role')`, which the
  application must set after authenticating. If the application sets it from client input, every policy
  here is bypassed. **The Stage 5 implementation must derive the role server-side from a verified JWT**, and
  this function must be treated as a seam that requires review — not a solved problem.
- **Supabase-specific behaviour is untested.** Supabase uses `auth.uid()` and its own `authenticated` /
  `anon` role names. This schema defines its own roles for local verification. Adapting it to Supabase is
  real work and is **not** done.
- **Not tested under concurrency.** No simultaneous-writer test. RLS correctness under race conditions is
  unestablished.
- **No RLS test for UPDATE on `alerts` by publisher with incomplete Spanish** — D26 is enforced by
  constraint, which is stronger, but the interaction with the publisher policy path is not separately
  asserted.
- **Geometry is not geospatial.** Lat/lon numbers plus a JSONB polyline. No spatial indexing, no distance
  operations, no `ST_*` functions. Route search will need its own graph structure.
- **Road geometry is synthetic.** The 150 segments are generated from sector centres, not extracted from
  OSM. Segment names include `(synthetic N-M)` so they cannot be mistaken for surveyed roads. Real
  geometry arrives in block 3.
- **Elevation values are generated, not sampled.** `4 + (n*13) % 10` metres — plausible but invented, and
  therefore labelled as SRTM-sourced only in the sense that the *column* is that type. Real sampling
  happens in block 3.
- **`audit_log` rules are PostgreSQL rewrite rules**, which are silently ignored by some tooling. The RLS
  absence-of-policy is the primary defence; the rules are belt-and-braces.
- **No backup, no migration versioning table.** Migrations are numbered files applied manually. There is no
  `schema_migrations` tracking, no down-migrations, and no rollback path other than dropping the database.

---

## 9. Acceptance criteria — M1 (Stage 4 §16.2 block 1)

| Criterion | Result |
|---|---|
| Migrations apply | ✅ on PostgreSQL 16.2 |
| RLS enabled and checked | ✅ 30/30 assertions |
| `SIM-1` — `simulated` defaults true | ✅ 0 rows claim otherwise |
| 6 sensors, 3 sectors, 150 segments, 8 shelters seeded | ✅ |
| Anonymous admin write rejected | ✅ tested for road_status, incidents, alerts |
| Seed reproducible | ✅ 3 runs, identical counts |

**M1 PASSED.**

---

## 10. Remaining blockers and next milestone

**Blockers carried into M2:**

- No Supabase project exists, so nothing is deployed or remotely verifiable.
- `current_app_role()` must be replaced with JWT-derived derivation before any real user touches this.
- Geometry is synthetic until block 3.

**Next: M2 — risk engine + tests.** Pure Python, no I/O, no database. It is the safety core and the
hour-4 checkpoint in Stage 4 §16.6: if `RISK-*` is not green, stop and report rather than compromise it.

**Budget:** ~1.75 h of the 10.75 h plan consumed (blocks 0 and 1). Proceeding to M2.
