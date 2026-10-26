# Status Tab Blank Page — Root Cause and Fix

**Date:** 2026-10-26
**Symptom:** the Status section ("loads and loads and turns into a blank page")
**Cause:** a formatter threw during React render, so React unmounted the entire tree.
**Verdict:** **FIXED**, plus two related defects found while fixing it.

---

## 1. Root cause

`frontend/src/App.tsx` formatted timestamps like this:

```js
d.toLocaleString(locale === 'es' ? 'es-EC' : 'en-GB', {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZoneName: 'short',   // ← illegal combination
})
```

V8 rejects `dateStyle` / `timeStyle` combined with a component option such as `timeZoneName`:

```
$ node -e "new Date('2026-10-26T03:00:00Z').toLocaleString('en-GB',
    {dateStyle:'medium', timeStyle:'short', timeZoneName:'short'})"
TypeError: Invalid option : option
```

The thrown error happened **during render**. React's behaviour on an uncaught render error is to
unmount the whole component tree — which is exactly the reported symptom: the loading state shows,
then the page goes completely blank with nothing to diagnose.

### Why only the Status tab

`stamp()` had exactly three call sites, all inside the Status tab's forecast and sensor cards:

```
App.tsx:193   {stamp(d.provenance.fetched_at, locale)}      ← forecast card
App.tsx:197   {stamp(source.model_run_at, locale)}           ← forecast card
App.tsx:327   {stamp(d.provenance.fetched_at, locale)}       ← sensor card
```

`RouteScreen.tsx` never formats a date, so the Route tab was unaffected. **That asymmetry is what
the symptom reported, and it is fully explained by this single cause.**

Note the API was never at fault: the backend returned 200 with valid JSON throughout (14 forecast
and 14 sensor requests, all `200 OK`). The data arrived; the page could not draw it.

---

## 2. Second defect found while fixing it — wrong timezone

With the exception removed, timestamps rendered in the **viewer's** timezone, not Guayaquil's:

```
on a host in IST:   26 Oct 2026, 08:30 GMT+5:30   ← for a 03:00Z forecast
correct (Guayaquil): 25 Oct 2026, 22:00 GMT-5
```

For an app whose entire subject is one city, showing the user's own timezone as "local time" is
wrong and quietly misleading. The timezone is now pinned explicitly:

```js
const APP_TIMEZONE = 'America/Guayaquil'
```

---

## 3. Third defect — a latent crash on offline sensors

`.toFixed()` throws on `null`:

```
$ node -e "null.toFixed(2)"
TypeError: Cannot read properties of null (reading 'toFixed')
```

The sensor card calls `s.latest.depth_m.toFixed(2)` and similar. `latest` **is** `null` whenever a
sensor is offline, so the current data happened to avoid the crash but the offline path would have
blanked the page in exactly the same way.

Replaced with a guard that renders `—` for a missing number — never a crash, and never a
fabricated `0`, which would be worse:

```js
function num(value, digits) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toFixed(digits)
}
```

---

## 4. Structural fix — an error boundary

Fixing the three bugs is not enough; a blank page is such a useless failure mode that it should be
unreachable. `frontend/src/ErrorBoundary.tsx` now wraps each section:

```jsx
<ErrorBoundary section="forecast" locale={locale}><ForecastSection … /></ErrorBoundary>
<ErrorBoundary section="sensors"  locale={locale}><SensorsSection  … /></ErrorBoundary>
<ErrorBoundary section="route"    locale={locale}><RouteScreen      … /></ErrorBoundary>
```

A failure now renders a visible, bilingual notice — *"This section could not be displayed / Esta
sección no se pudo mostrar"* — with the error name and message, and a retry button. It
**deliberately does not substitute estimated values**, because inventing numbers to fill a failed
render would be worse than showing nothing.

---

## 5. Files changed

| File | Change |
|---|---|
| `frontend/src/App.tsx` | `stamp()` rewritten (no conflicting options, timezone pinned, wrapped in try/catch); added `num()` guard; replaced `toFixed` calls; wrapped sections in boundaries |
| `frontend/src/ErrorBoundary.tsx` | **new** — bilingual boundary that reports instead of vanishing |

No backend changes for this fix. No dependencies added. No design, layout, or copy changes beyond
the new boundary notice.

---

## 6. Verification

### Formatter verified against real API payloads, both locales

A script replaying every formatting call the Status section makes, using the actual live payloads:

```
forecast line sample: total 19 mm | peak 5.6 | 25 Oct 2026, 22:17 GMT-5 | model run unavailable | 24 hours
sensor sample: SIM-01 1.80 m, 150%
offline sensor renders: — / —

RESULT: 6 formatting passes, 0 throws
```

The offline case (`latest: null`) is included and renders `—` rather than throwing.

### The old code provably threw

```
old code THROWS: TypeError: Invalid option : option
=> React unmounts the tree -> blank page. Matches the reported symptom.
```

### Build and gates

```
$ npx tsc -b --force        → exit 0
$ npm run build             → built in 129ms
dist/assets/index-*.js        253.37 kB │ gzip: 79.31 kB
$ node src/__i18n-check.mjs   → 43 keys, both languages, no overclaims
$ cd backend && pytest        → 366 passed, 10 skipped
```

### Dev server serving the fix

```
/src/App.tsx            contains America/Guayaquil   (4 occurrences)
/src/ErrorBoundary.tsx  HTTP 200
proxy /api/health       HTTP 200
```

---

## 7. What is verified, and what is not

**Verified:** no formatter in the Status path throws for any current payload, in either locale,
including the offline-sensor case; TypeScript compiles under `strict`; the dev server serves the
corrected modules; the API returns valid JSON through the proxy.

**Not verified by me:** the rendered pixels. No browser is available here (`browser_tool` refuses
private-network targets, no local browser installed), so **N-5 remains open**. Reload
http://localhost:5173/ to confirm visually.

If the Status tab still misbehaves, the boundary will now display the error name and message
instead of a blank page — please paste that text and I can locate it immediately.

---

## 8. Standing statements

- Sensors remain **SIMULATED**; road geometry is a bounded real OSM extract, road **status** is
  seed/demo data.
- **No route is claimed safe.**
- No mutation endpoints. No commits, pushes, or deployments.
- Demo routes are still dominated by phase-2 hazard crossings (**N-16**), which is correct
  behaviour with dense demo closures but poor for a demo. It is the natural next step.
