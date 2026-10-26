# M14 — Seven-Day Forecast, INAMHI Bulletin, Honest Comparison: Evidence

**Date:** 2026-10-26
**Block:** M14 — forecast expansion + INAMHI integration + honest comparison
**Verdict:** seven-day forecast **implemented and live**; INAMHI **genuinely integrated** by parsing
its official PDF, because **no INAMHI JSON API exists**; comparison **implemented and deliberately
capped** at band-consistency rather than verification.
**N-5 remains OPEN — no browser, so nothing has been visually verified.**

| Gate | Result |
|---|---|
| Tests without PostgreSQL | **631 passed, 12 skipped** |
| Tests with PostgreSQL 16.2 | **640 passed, 3 skipped** |
| `app/domain/risk.py` branch | **100 %** (unchanged) |
| `app/routing/status_repository.py` branch | **100 %** (unchanged) |
| `app/ingest/comparison.py` branch | **100 %** (new) |
| `tsc -b --force` | **exit 0** |
| `npm run build` | 321.46 kB / **97.20 kB gzip** |
| i18n guard | **226 keys**, both locales |
| Dependency pins | **12, unchanged** — no new dependency |

---

## 1. What INAMHI actually offers — inspected, not assumed

This determined the design, so it is reported first.

| Check | Result |
|---|---|
| `servicios.inamhi.gob.ec/pronostico/`, `/boletines/`, `/alertas/` | **HTTP 200** — all reachable |
| What are they? | **WordPress** pages |
| `robots.txt` | disallows only `/wp-admin/`; public pages crawlable |
| `/wp-json/wp/v2/posts` | **`[]`** — empty |
| `/feed/` (official RSS, advertised in `<head>`) | **0 `<item>` elements** |
| Bulletin content | **PDF links** on `www.inamhi.gob.ec`, e.g. `pronostico/advertencia.pdf` |
| That PDF | **Live**: `Last-Modified` = previous day, 590 kB, 1-page A3, text layer present |

**There is no official machine-readable INAMHI feed.** Inventing a "JSON API", or scraping HTML
tables that do not exist, would have been a fiction. The brief said to prefer an official feed, and
to say so plainly if one is unavailable — this is that case.

**What I did instead:** parsed the official PDF's text layer, which is a real, current, officially
published document. `pdftotext` is already installed, so **no dependency was added**.

### Extracted from the live bulletin, right now

```
bulletin     : 83
status       : ADVERTENCIA
threat level : MEDIO – MUY ALTO
issued       : 2026-10-25 19:00 UTC   (= 14:00 Ecuador local, UTC-5)
valid        : 2026-10-25 21:00 → 2026-10-29 04:00 UTC
phenomenon   : LLUVIAS, TORMENTAS ELÉCTRICAS Y RÁFAGAS DE VIENTO
bands (mm/24h):
  Litoral      Medio 10–18 · Alto 19–41 · Muy Alto 42–100
  Interandina  Medio  8–11 · Alto 12–30
  Amazonía     Medio 22–31 · Alto 32–54
```

Every field is independently optional. A missing field produces a `None` **plus a warning**, never
a guess. A qualitative bulletin with no numeric table returns `is_quantitative: false` and is shown
as an official statement — not converted into invented numbers.

---

## 2. Seven-day forecast

Open-Meteo's daily endpoint, verified live before coding against it:

```
daily.precipitation_sum            21.5 mm
daily.precipitation_probability_max 97 %
daily.temperature_2m_min / _max     24.8 / 30.2 °C
daily.weather_code                  81  (WMO)
```

Seven days returned, with the hourly series retained for the 24-hour chart. Units come from
`daily_units` and are **checked**: a non-mm precipitation unit aborts rather than being assumed.

### Missing data handling — the part that matters

| Situation | Behaviour |
|---|---|
| Provider returns `null` for a day | Stays `null`; UI renders "unavailable" |
| Whole `daily` block absent | `days: []` + note; 7-day view hidden, hourly still served |
| Negative precipitation | Treated as unavailable, **not clamped to 0** (hiding a provider fault) |
| Probability outside 0–100 | Treated as unavailable |
| `NaN` / `Infinity` | Treated as unavailable |
| Series shorter than the date list | **Padded**, values stay on their own day, mismatch reported |
| Wrong unit (inches) | Raises — never assumes mm |

A zero-height bar reads as "no rain", which is a confident and possibly false claim, so missing
days are drawn as a dashed slot with an explicit "unavailable" label.

---

## 3. The comparison — what it says, and what it refuses to say

Live output:

```
2026-10-26  21.5 mm  →  inside band: Alto (19–41)
2026-10-27  14.9 mm  →  inside band: Medio (10–18)
2026-10-28   7.5 mm  →  outside every published band
```

**This is not a cross-verification, and the payload says so on every response** in both languages.
The two datasets are not the same kind of quantity:

| | Open-Meteo | INAMHI bulletin |
|---|---|---|
| Space | one coordinate | a whole region (Litoral ≈ several provinces) |
| Time | calendar day, UTC | its own 24-hour accumulation window |
| Value | a single model output | a **band per threat level**, not one value |

Consequences, all enforced:

- **No percentage difference is computed.** A point versus a regional band has no meaningful
  arithmetic difference; a test asserts none is displayed.
- **Inside a band means "consistent", not "agrees".** Outside means nothing is contradicted either.
- **The words "corroborated", "validated", "confirmed by", "sources agree" never appear.** A test
  scans the shipped copy, and permits "cross-verification" only inside a denial.
- **The caveats are rendered verbatim, always** — including when no comparison was possible, since
  the reason it would not have been a verification is still worth stating.

When no comparison is possible, the reason is specific and rendered:
`no_bulletin` · `no_numeric_bands` · `unknown_region` · `no_overlapping_day`.

---

## 4. Safety and reliability

| Requirement | How |
|---|---|
| Rainfall ≠ flood prediction | Banner rendered **before** any figure on the Status tab, bilingual |
| No flood-risk score from rainfall | No such computation exists; stated in the banner and asserted by a test |
| Provenance preserved | Source, fetch time, cache age and data mode on every payload |
| Model run time not invented | Stays `null` with a note (N-1); fetch time reported separately |
| Caching | 15-min TTL for a successful bulletin, **60 s for a failure**, with `cached` / `cache_age_s` exposed |

The shorter failure TTL is deliberate: a transient INAMHI outage must not pin an error to the
screen for a full 15 minutes, while still not hammering their server on every request.

---

## 5. Frontend

| Component | What it shows |
|---|---|
| `ForecastSafetyNotes` | rainfall-is-not-flooding + no-risk-score, both languages |
| `SevenDaySection` | 7-day SVG bar chart + 7 daily cards (rain, probability, temp range, sky) |
| `Next24hSection` | 24 hourly bars, labels in **Guayaquil** time |
| `BulletinPanel` | bulletin number, status, threat, issue/validity in local time, bands table, regions, recommendations, official link |
| `ComparisonPanel` | model vs region per day, "inside band" / "outside every band", caveats |

**No chart library.** Two bar charts did not justify the bundle weight; inline SVG also gives
per-bar `<title>` and a text alternative.

**Off-by-one guard:** daily dates are calendar days, so `new Date('2026-10-26')` (UTC midnight)
would render as the 25th in UTC−5. They are constructed from parts with an explicit UTC basis.
A test pins this.

---

## 6. Tests — 64 new

`test_m14_forecast_bulletin.py` (37) covers daily parsing, every missing-value path, time zones,
source timestamps, bulletin field extraction, bulletin unavailability, and all four refusal reasons.
`test_m14_frontend_contract.py` (27) covers the chart's null handling, the absence of percentage
arithmetic, verification vocabulary, date/timezone handling, and the safety disclosures.

**Mutation-checked, all caught:**

| Injected defect | Result |
|---|---|
| Missing daily value → `0.0` | **5 tests failed** |
| Comparison claims "Cross-verified" | **failed** |
| Bulletin local time treated as UTC | **failed** |
| Chart draws missing values as bars | **failed** |
| Comparison says "agrees with INAMHI" | **failed** |

### A real bug these caught

A shorter value series than the date list raised **`IndexError`** — a provider truncating a series
would have 500'd the endpoint. Now padded so each value stays on its own day and the missing tail is
explicitly `None`.

---

## 7. Defects in my own verification (worth naming)

- My scanner flagged `BulletinPanel.tsx` for the banned phrase "agrees with" — because the file's
  header comment **quotes** it in order to forbid it. Fixed by stripping comments before scanning;
  same class of error as the M12 i18n scanner.
- A mutation-restore used the wrong backup path and **overwrote `BulletinPanel.tsx` with Python
  source**. Caught by line count (227 vs 503), and the component was rewritten. Two lessons: verify
  a restore, don't assume it.

---

## 8. What is implemented, linked manually, or still needs access

| Item | Status |
|---|---|
| Seven-day forecast, charts, cards | **Implemented**, live data |
| Next-24h hourly chart | **Implemented**, live data |
| INAMHI bulletin — automated read | **Implemented** via the official PDF |
| INAMHI numeric bands | **Implemented** — parsed from the published table |
| INAMHI JSON API | **Does not exist.** Nothing invented |
| INAMHI alerts page | **Linked manually** (`/alertas/`); no feed to ingest |
| INAMHI numerical-model page | **Linked manually** (`modelos-numericos`) |
| Bulletin webhook / push updates | **Not implemented** — needs a public endpoint |
| Visual verification | **Not performed — no browser (N-5)** |

If INAMHI later publishes a machine-readable feed, `inamhi.py` is the only file that changes: the
`fetch_bulletin` signature already isolates the transport, and everything downstream consumes a
`Bulletin` object.

---

## 9. Blockers

| ID | Status |
|---|---|
| **N-5** | **OPEN** — nothing visually verified |
| **O-7** | OPEN — no risk score, by design |
| **O-8** | OPEN — stale closures unchanged |
| **N-1** | OPEN — model run time still null, still not inferred |
| N-2 | Closed for this path — server-side RBAC (M13) |
| N-17 / N-18 | OPEN — SQLite store; no webhook receipts |
| **N-19** (new) | INAMHI has no machine-readable API; integration depends on a PDF layout that could change. Failure is handled honestly (link shown, no values), but it is a real fragility |

---

## 10. Standing statements

- **Forecasts are forecasts, never observations.** `kind: "forecast"` on every value.
- **INAMHI band data is regional, not a point prediction for Guayaquil**, and is labelled as such.
- **Inside a published band is consistency, not verification.** No percentage difference is
  computed anywhere.
- **Rainfall is not a flood prediction**, and no flood-risk score is derived from it.
- **Missing values are "unavailable", never zero.**
- **Visual verification was not performed.** N-5 remains open.
- No deployment, no spend, no new dependency, no commit yet (pending diff review).
