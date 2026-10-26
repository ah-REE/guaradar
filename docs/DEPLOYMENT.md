# Deployment — Vercel frontend + Render API

**Shape:** the frontend is built and served by Vercel. The FastAPI service runs on Render.
Vercel **proxies** `/api/*` to Render, so the browser only ever talks to ONE origin.

That proxy is the whole point. It is what keeps the session cookie same-origin, which is what
lets CORS stay restricted and `allow_credentials` stay `False`.

```
Browser ──► https://your-project.vercel.app  ──┬─►  static bundle (Vercel)
                                               └─►  /api/*  ──rewrite──►  Render API
```

---

## 1. Deploy the API to Render

### 1a. Create the service from the blueprint

1. Push this repository to GitHub (already done for `main`).
2. In Render: **New → Blueprint**, pick the repo. Render reads `render.yaml`.
3. Render will prompt for every `sync: false` variable. Set the ones you need now:
   - `GUARADAR_COOKIE_SECURE` — **already `"1"` in the blueprint. Leave it.**
   - `GUARADAR_CORS_ORIGINS` — your Vercel origin, e.g. `https://guaradar.vercel.app`
   - Leave `GUARADAR_PG_DSN`, `SUPABASE_*`, `SENTRY_DSN`, `OPENTOPOGRAPHY_API_KEY` blank unless
     you are actually using them.

### 1b. Verify the API before touching the frontend

```bash
curl -sS https://YOUR-SERVICE.onrender.com/api/health | head -c 400
```

You must see `"status":"ok"`. If you see a 502, read Render's build log — the usual cause is a
missing dependency, not this code.

### 1c. Create your first admin account

**There is no web path to create an admin.** That is deliberate: `POST /api/auth/register`
hardcodes `role='public'` and has no role field, so the highest role is never reachable from a
session. The only way in is the CLI, run in Render's **Shell** tab:

```bash
cd /opt/render/project/src/backend
python -m app.admin_cli create-user --email you@example.com --role admin
```

It prompts for a passphrase (12 characters minimum). Then sign in at the Vercel URL via the
**Account** tab, and the **Admin** tab appears.

> **This account will disappear whenever the service restarts**, because the database is SQLite
> on an ephemeral disk. See §4. Do not be surprised by it — and do not mistake it for a bug.

---

## 2. Deploy the frontend to Vercel

1. In Vercel: **New Project → Import** the same repo.
2. Vercel reads `vercel.json`. It builds `frontend/` and serves `frontend/dist`.
3. **Edit one line first.** In `vercel.json`, replace the placeholder:

   ```json
   "destination": "https://REPLACE-WITH-YOUR-RENDER-URL.onrender.com/api/:path*"
   ```

   with your real Render URL. Until you do, every `/api` call 404s. The placeholder is intentional
   — a wrong hardcoded host fails far less visibly than an obviously unfinished one.

4. Deploy.

### 2a. Verify the proxy

```bash
curl -sS https://YOUR-PROJECT.vercel.app/api/health | head -c 200
```

This must return JSON from FastAPI, **not** the Vercel 404 page. If it returns HTML, the rewrite
is wrong.

---

## 3. Required environment variables

| Variable | Where | Required | Why |
|---|---|---|---|
| `GUARADAR_COOKIE_SECURE` | Render | **Yes, `1`** | Without it the cookie is non-Secure and browsers refuse it on https. Sign-in appears to work, then silently does not stick. |
| `GUARADAR_CORS_ORIGINS` | Render | **Yes** | The frontend origin. Also refuses `*` at startup, because a wildcard with auth is a misconfiguration. |
| `GUARADAR_DB_PATH` | Render | Set by blueprint | Points at `/tmp`, so the ephemeral failure is honest rather than disguised. |
| `VITE_API_BASE_URL` | Vercel | **No — leave unset** | The client defaults to same-origin, which is what the proxy relies on. Setting it to an absolute Render URL re-introduces cross-origin and breaks the cookie. |
| `GUARADAR_PG_DSN` | Render | Only for durability | See §4. |
| `SUPABASE_*`, `SENTRY_DSN`, `OPENTOPOGRAPHY_API_KEY` | Render | Only if used | Terrain is not implemented yet; the key is read by nothing. |

---

## 4. Durability — the honest version

Render's free web service has an **ephemeral** filesystem. The runtime database is SQLite at
`GUARADAR_DB_PATH`, which on this plan resolves to `/tmp`.

**Consequences, stated plainly:**

- Citizen road reports and their photos are **lost on restart, spin-down, or redeploy**.
- Staff accounts are **lost too** — including the admin you created in §1c.
- Nothing in this repository claims otherwise, and `render.yaml` documents it in place.

**To make data survive:**

1. Provision managed PostgreSQL (Render's own, or Supabase).
2. Set `GUARADAR_PG_DSN` in Render's dashboard.
3. Apply `supabase/migrations/0007_road_reports.sql`, then re-run the identity `DO` block once a
   users table exists.

**None of that PostgreSQL path has been executed or tested.** There is no PostgreSQL server on the
development host, so the migration is unproven and the 12 PostgreSQL tests skip. Treat step 3 as
unverified work, not a formality.

---

## 5. Why not just point Vercel directly at Render with CORS?

You can, and it is one edit: `allow_origins`, `allow_credentials=True`, and `secure=True`. It is
also worse:

- `allow_credentials=True` across origins lets a **cross-site page send the session cookie**. The
  proxy avoids that entirely.
- CORS then has to be kept in sync with every preview deployment URL.
- The DevTools network panel shows every API call as cross-origin, which makes a CORS regression
  look like an auth bug.

The proxy costs one rewrite rule and removes all three problems.

---

## 6. What was NOT verified

Recorded so nobody reads this as a working deployment:

- **Never deployed.** No Vercel or Render CLI is installed, and no account credentials are
  available in this environment. `render.yaml` and `vercel.json` are written and unit-tested for
  structure, not executed.
- **No browser check.** Sign-in over https has not been observed in a real browser. The cookie
  fix in `auth_routes.py` is verified by tests, not by a session.
- **`GUARADAR_CORS_ORIGINS` uses a placeholder** (`https://your-project.vercel.app`).
- **PostgreSQL path untested**, as above.
