# M12 — Manual Visual Verification Checklist (N-5)

**Why you have this instead of screenshots:** there is no browser on the machine this project is
being built on. Checked: `chromium`, `chromium-browser`, `google-chrome`, `firefox`, `brave`,
`microsoft-edge`, `epiphany`, `wkhtmltoimage`, `cutycapt`, `xvfb-run` — none present. No flatpak
browser. No `playwright`, `puppeteer`, `jsdom` in `node_modules`. The automation tool refuses
`127.0.0.1` as a private target.

So **N-5 remains open**. Nothing below has been seen rendered. These checks are the ones I cannot
perform and can only be done by you in a real browser.

**Estimated time:** 15–20 minutes. **Do not skip §6** — it is the check most likely to reveal a
real defect.

---

## Start the app

```bash
# Terminal 1
cd /home/ahree/Projects/GuaRadar
.venv/bin/python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --app-dir backend

# Terminal 2
cd /home/ahree/Projects/GuaRadar/frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Open **http://127.0.0.1:5173/**

> Use `127.0.0.1` rather than `localhost`. They are different origins, and the Vite proxy is the
> only thing bridging `/api` to the backend.

---

## §1 — Status tab (the bug that was fixed)

Select the **Status** tab.

| # | Check | Expected | ✗ |
|---|---|---|---|
| 1.1 | Page renders at all | Full page, no blank screen | |
| 1.2 | Forecast timestamps | Local Guayaquil time (UTC−5), **not** your machine's zone | |
| 1.3 | Timestamp shape | Something like `26 Oct, 09:00` — no `Invalid option` text, no `NaN` | |
| 1.4 | Offline sensor rows | Show an em dash `—` or "unavailable", **never `0.00`** | |
| 1.5 | Sensor labels | Every sensor marked SIMULATED | |
| 1.6 | `model_run_at` | Shown as unavailable/unknown, not invented |
| 1.6b | **Limitations list no longer says routing is unavailable** | It should say routing **IS** available on the Route tab |
| 1.6c | **Limitations distance is current** | Should read about `1,084.5 km`, not `50 km` |
| 1.6d | **Street length read as length** | The sentence must say it is street LENGTH, not a share of the city | |
| 1.7 | Browser console | No red errors (**F12 → Console**) | |

> If timezone 1.2 is wrong, the `America/Guayaquil` pin is not reaching the formatter — that is a
> real regression and worth reporting with the exact rendered string.

---

## §2 — Map framing and attribution

Go to the **Route** tab. If a map is not shown, press the view toggle to switch to map.

| # | Check | Expected | ✗ |
|---|---|---|---|
| 2.1 | Map renders | Tiles load; no grey void | |
| 2.2 | Framing | Shows the three demo sectors in Guayaquil, **not** the whole world or a grey ocean | |
| 2.3 | **Attribution visible** | "© OpenStreetMap contributors" legible, **not** hidden behind a button | |
| 2.4 | ODbL notice | Present in the map area |
| 2.4b | **No hardcoded distance** | The banner quotes a figure like `1,084.5 km`. If you see `50 km`, the correction did not load | |
| 2.5 | Route line | Drawn between your two chosen points | |
| 2.6 | Route style | Visually distinct from the basemap; readable at default zoom | |
| 2.7 | Marker positions | Start and destination markers sit **on** roads | |

**2.3 matters legally** — OSM's licence requires visible attribution. If it is obscured, that is a
compliance defect, not a cosmetic one.

---

## §3 — Scenario selector (new in M12)

Above the start/destination pickers.

| # | Check | Expected | ✗ |
|---|---|---|---|
| 3.1 | Selector present | Labelled "Road-status scenario" | |
| 3.2 | Default | **Baseline** selected on first load | |
| 3.3 | Help text | Explains the "one road in twenty-nine" vs "six closures" difference | |
| 3.4 | Switching to demo refetches | Results change; a loading state appears briefly | |
| 3.5 | **Demo warning appears** | Orange-bordered banner on selecting the demo scenario | |
| 3.6 | Warning text | Says closures are **simulated** and **not verified real-world reports** | |
| 3.7 | Warning is not dismissible | No close button, no × | |
| 3.8 | Warning disappears | Switching back to baseline removes it | |
| 3.9 | Selector is keyboard-usable | Tab to it, change with arrow keys | |

---

## §4 — The four route outcomes

Use **SIM-01 → SIM-04** for all of these, which is the default pair.

### 4a. Baseline (default)

| # | Check | Expected | ✗ |
|---|---|---|---|
| 4a.1 | All routes labelled hazard-crossing | Yes | |
| 4a.2 | **No route recommended** | Every card shows recommended = false | |
| 4a.3 | Explanatory label | Something like "crosses a closed road" | |
| 4a.4 | Overall banner | Says every option crosses a closure | |
| 4a.5 | Coverage shown | Around 54 % | |

### 4b. Demo scenario

Switch the selector to demo. Wait for refetch.

| # | Check | Expected | ✗ |
|---|---|---|---|
| 4b.1 | Top route is **clear** | hazard_class = clear, not hazard-crossing | |
| 4b.2 | **Recommended = true** | Exactly one route recommended | |
| 4b.3 | Coverage above 60 % | Around 84 % | |
| 4b.4 | Band reads high/moderate | Not "low" | |
| 4b.5 | Demo banner still visible | Disclosure stays while results are shown |
| 4b.6 | **Duration labelled an estimate** | Directly under the minutes value: "estimate, not live travel time" | |

### 4c. Low coverage

Switch back to **baseline**, set destination **SIM-06**.

| # | Check | Expected | ✗ |
|---|---|---|---|
| 4c.1 | Routes still listed | Served for transparency | |
| 4c.2 | **Not recommended** | recommended = false | |
| 4c.3 | Low-coverage warning visible | Warns coverage is insufficient | |
| 4c.4 | Warning explains why | Says coverage is low, not that roads are closed | |

### 4d. Refused request

This one is easier from the API, but check the UI handles it:

```bash
curl -s "http://127.0.0.1:5173/api/public/route?from_lat=-2.40&from_lon=-80.00&to_lat=-2.220429&to_lon=-79.908965" \
  | python3 -m json.tool | head -20
```

| # | Check | Expected | ✗ |
|---|---|---|---|
| 4d.1 | `refused` is true | `true` | |
| 4d.2 | Reason is specific | Mentions metres from the nearest road and the 60 m limit | |
| 4d.3 | No fabricated route | `routes` is empty | |

> The UI only offers the six demo points, all of which snap, so you cannot trigger this from the
> pickers. That is a **UI gap**, not a bug — note whether you think a demo "outside the extract"
> option would be worth adding.

---

## §5 — Spanish locale

Toggle to Spanish.

| # | Check | Expected | ✗ |
|---|---|---|---|
| 5.1 | Every string translated | **No English left** in labels, buttons, warnings | |
| 5.2 | Scenario selector | Spanish labels present | |
| 5.3 | Demo warning | Spanish, still explicit that data is simulated | |
| 5.4 | Error messages | Spanish, and still name the actual problem | |
| 5.5 | No truncation | Longer Spanish text does not overflow buttons | |
| 5.6 | Safety messages | Disclaimers still present in Spanish, not dropped | |

**5.1 is the one to look hardest at.** Any untranslated string is a hole in a bilingual
requirement that was approved as *complete*, not best-effort.

---

## §6 — Tile-load failure behaviour ⚠️ highest value

**This is the check most likely to reveal a real defect**, because it exercises a path no automated
test here can reach.

1. Open **F12 → Network**.
2. Set throttling to **Offline**.
3. Switch to the map view (or reload the Route tab).
4. Observe. Then set back to **Online**.

| # | Check | Expected | ✗ |
|---|---|---|---|
| 6.1 | Page **does not** go blank | The app survives; the ErrorBoundary catches it | |
| 6.2 | A message appears | Says the map could not be loaded | |
| 6.3 | Message is honest | Does **not** claim the area is fine, or that there are no closures | |
| 6.4 | Rest of the page still works | Route list still readable, tabs still switch | |
| 6.5 | Recovery | Going online and retrying restores the map | |
| 6.6 | Console | Failure logged, not swallowed silently | |

> A blank page here is the **exact failure mode** the Status tab had. If the app blanks, that is a
> significant finding — please report the error name and message.

---

## §7 — Narrow viewport / mobile

Use DevTools device toolbar (**Ctrl+Shift+M**), iPhone SE (375×667).

| # | Check | Expected | ✗ |
|---|---|---|---|
| 7.1 | No horizontal scroll | Content fits 375 px | |
| 7.2 | Tab bar | All 5 tabs reachable, none cut off | |
| 7.3 | Scenario selector | Usable, not squeezed to nothing | |
| 7.4 | Demo warning | Wraps, stays readable, not clipped | |
| 7.5 | Route cards | Stack vertically, text legible | |
| 7.6 | **Tap targets ≥ 44 px** | Buttons and selects are finger-sized |
| 7.6b | **Selects shrink, not overflow** | The two point pickers sit side by side without pushing the page wide | |
| 7.7 | Map at 375 px | Still usable, attribution still visible | |
| 7.8 | No overlap | Nothing collides or hides another control | |

---

## §8 — What to report back

For each ✗, give me: **check number · what you saw · what you expected**.

The three most useful, in order:

1. **§6 tile failure** — does the app blank or degrade?
2. **§5.1 Spanish completeness** — any English leaking through?
3. **§2.3 attribution** — is the OSM credit actually legible?

---

## What this checklist cannot fix

Passing every box means the interface has been *inspected*. It does not make the demo data real,
and it does not close O-7, O-8, N-2, N-13 or N-14. It closes **N-5 only**.
