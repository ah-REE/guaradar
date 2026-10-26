# M0 — Clean-Install Gate: Evidence

**Date:** 2026-10-26
**Milestone:** M0 (Stage 4 §16.2 block 0)
**Verdict:** **PASSED**, with one documented constraint (§5)

This file records what was actually executed and observed. Everything below is quoted from real command
output. Nothing in this milestone is a claim about application functionality — there is no application yet.

---

## 1. Environment

| Item | Value |
|---|---|
| Platform | linux (x86_64) |
| Python | **3.14.8** (only 3.14 present) |
| Node | 24.20.0 |
| npm | 11.19.0 |
| `pip` on PATH | **absent** — bootstrapped via `python3 -m venv` (bundled pip 26.2.1) |
| Network | pypi 200, npm registry 200 |

---

## 2. Python installation — PASSED on 3.14.8

```
$ python3 -m venv .venv          # exit 0
$ .venv/bin/python -V
Python 3.14.8
$ .venv/bin/pip --version
pip 26.2.1 ... (python 3.14)
$ .venv/bin/pip install -r backend/requirements.txt
Successfully installed annotated-doc-0.0.5 annotated-types-0.8.0 anyio-4.15.1 ... uvicorn-0.54.0
uvloop-0.23.0 watchfiles-1.3.0 websockets-15.0.1 yarl-1.25.1
```

**No source builds were required.** Every package resolved to a published wheel, including the compiled
extras pulled by `uvicorn[standard]` (uvloop, httptools, watchfiles, websockets) — the exact risk flagged
in Stage 3 §2.

### Import smoke test — PASSED

```
$ .venv/bin/python -c "import fastapi, networkx, numpy, pydantic, httpx, supabase, jwt, pytest; ..."
fastapi       0.162.0
pydantic      2.14.1
networkx      3.7
numpy         2.5.4
httpx         0.28.1
pyjwt         2.15.1
pytest        9.1.1
supabase      2.33.0
ALL IMPORTS OK
```

### Uvicorn — PASSED

```
$ .venv/bin/uvicorn --version
Running uvicorn 0.54.0 with CPython 3.14.8 on Linux
```

### Resolved set

51 packages frozen to `backend/requirements.lock.txt`. The **documented pins are unchanged**; the lock file
records the transitive resolution alongside them.

Notable resolved transitives: `pydantic-core==2.50.1`, `starlette==1.10.0`, `cryptography==50.0.2`,
`websockets==15.0.1`, `opentelemetry-api==1.45.1`.

---

## 3. Frontend installation — PASSED

```
$ npm install     → added 55 packages, audited 56 packages in 12s, found 0 vulnerabilities
$ npm ci          → added 55 packages, audited 56 packages in 1s,  found 0 vulnerabilities
```

`npm ci` requires a lockfile, which does not exist on a first run — so `npm install` generated
`package-lock.json` and `npm ci` was then run as the real gate. Both succeeded with **0 vulnerabilities**.

### Installed versions — exact, per the documented pins

```
@tanstack/react-query@5.104.5
@types/leaflet@1.9.20
@types/react-dom@19.2.1
@types/react@19.2.2
@vitejs/plugin-react@6.1.2
leaflet@1.9.4
react-dom@19.3.1
react-leaflet@5.0.0
react-router-dom@7.18.4
react@19.3.1
typescript@7.0.2
vite@8.3.5
vitest@5.0.5
```

### Build — PASSED

```
$ npm run build
> tsc -b && vite build
vite v8.3.5 building client environment for production...
✓ 15 modules transformed.
dist/index.html                  0.31 kB │ gzip:  0.23 kB
dist/assets/index-B7Nm3CQx.js  220.03 kB │ gzip: 68.86 kB
✓ built in 129ms
```

- TypeScript (`tsc -b`) passed with `strict: true`, no errors.
- **68.86 kB gzipped** first load — under the ≤120 KB target from Stage 3 §15.
- Leaflet is **absent** from the first-paint bundle (verified: 0 occurrences), satisfying the lazy-load
  requirement before the map is even written.

---

## 4. What was created

| Path | Purpose |
|---|---|
| `backend/requirements.txt` | the 12 documented pins, unchanged |
| `backend/requirements.lock.txt` | 51-package resolved freeze (the *real* pin) |
| `frontend/package.json`, `package-lock.json` | documented versions, lockfile captured |
| `frontend/tsconfig.json`, `vite.config.ts`, `index.html` | build config |
| `frontend/src/main.tsx`, `src/App.tsx` | **placeholder shell only** — see §6 |
| `.gitignore` | excludes `.venv/`, `node_modules/`, `dist/`, `.env*` |
| `.env.example` | variable **names only**, no values |

---

## 5. ⚠ Constraint: the documented fallback is unavailable on this machine

Stage 3 §2 and every stage since specified: *if Python 3.14 fails, recreate the venv on 3.13 with pins
unchanged.* **Python 3.13 is not installed here and 3.12 is not either.**

```
$ for p in python3 python3.14 python3.13 python3.12; do ... done
python3    Python 3.14.8
python3.14 Python 3.14.8
python3.13 NOT FOUND
python3.12 NOT FOUND
```

**Consequence:** the fallback could not be executed, and could not have been executed, because the target
interpreter does not exist. This did not matter — 3.14 succeeded — but the fallback is presently
**untested and untestable on this host**.

**This is not a blocker for M0**, which passed on 3.14. It is a real gap in the documented contingency and
is recorded here rather than glossed. If a later block hits a genuine 3.14-only failure, the options are
(a) install 3.13, or (b) accept a pin change — and (b) requires the owner's explicit approval because it
contradicts the standing rule.

---

## 6. What this milestone does **not** establish

Stated plainly so no later summary can inflate it.

- **No application exists.** `App.tsx` is a placeholder that renders the project name and a sentence saying
  the app is not functional. It displays no flood data, no severity colour, and no simulated reading —
  deliberately, so a screenshot of it cannot be mistaken for a working product.
- **No database, no schema, no seed data.**
- **No API, no endpoints, no authentication.**
- **No safety property has run.** All 44 remain *specified, not executed*. The evidence ceiling is still
  **E2**.
- **No deploy, no push, no commit.** The directory is still not a Git repository.
- **Nothing here shows that the risk model, the routing guarantee, or the provenance system works.** M0
  proves only that the toolchain installs and builds.

---

## 7. Gate status

| Criterion (Stage 4 §16.2 block 0) | Result |
|---|---|
| venv created via bundled pip (no PATH pip) | ✅ |
| pinned install succeeds | ✅ on 3.14.8 |
| import smoke test | ✅ all modules |
| `uvicorn --version` | ✅ 0.54.0 / CPython 3.14.8 |
| `npm ci` | ✅ 55 packages, 0 vulnerabilities |
| `npm run build` | ✅ 129 ms, 68.86 kB gzip |
| resolved freeze + lockfile captured | ✅ |
| Python 3.13 fallback available if needed | ❌ **not installed on this host** (§5) |

**M0 PASSED.** Proceeding to block 1 (schema + seed) is permitted; awaiting the owner's checkpoint decision
per the Stage 4 §16.6 discipline is not required — hour-2 and hour-4 checkpoints are the decision points.
