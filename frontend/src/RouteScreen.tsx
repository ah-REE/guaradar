/**
 * Route check screen — first map in the project (M7).
 *
 * Design constraints carried from the approved stages:
 *  - Only coordinates the API actually returned are drawn. Nothing is smoothed, snapped to a
 *    real street, or extrapolated.
 *  - The synthetic nature of the network is stated in words ON the screen, not in a tooltip.
 *  - Hazard-crossing routes are visually distinct and never labelled as recommended.
 *  - Low/zero-coverage routes are marked "not recommended".
 *  - A list view is provided and is the canonical representation; the map is an optional view.
 *    That keeps the screen usable when tiles fail, which is the normal condition on a bad
 *    connection during a storm.
 *  - Leaflet is imported dynamically so it never enters first paint.
 */

import { useEffect, useRef, useState } from 'react'
import {
  fetchRoute,
  type LatLon,
  type Route,
  type RouteResponse,
  type StatusProfile,
} from './routeApi'
import { t, tf, type Locale, type StringKey } from './i18n'
import { tokens, fontStack } from './tokens'

/** Demo points = the six sensor sites, snapped to their nearest real graph node.
 *
 * These are the actual node coordinates returned by the graph, not the raw sensor lat/lon.
 * Reason: two sensor sites (SIM-02 at 63 m, SIM-05 at 63 m) fall just outside the route
 * API's 60 m snap limit, so submitting their raw coordinates produced a truthful but
 * confusing "your starting point is 63 m from the nearest road" refusal. The limit exists so
 * the app never routes from a guessed origin, and it was NOT relaxed; the UI now supplies
 * coordinates that are genuinely on the network.
 */
export const DEMO_POINTS: { id: string; label: string; at: LatLon }[] = [
  { id: 'SIM-01', label: 'Sauces 6', at: { lat: -2.142763, lon: -79.905598 } },
  { id: 'SIM-02', label: 'Samanes', at: { lat: -2.14923, lon: -79.901801 } },
  { id: 'SIM-03', label: 'Cerro Santa Ana', at: { lat: -2.196117, lon: -79.886222 } },
  { id: 'SIM-04', label: 'Cristo del Consuelo', at: { lat: -2.220429, lon: -79.908965 } },
  { id: 'SIM-05', label: 'Cisne II', at: { lat: -2.227579, lon: -79.91471 } },
  { id: 'SIM-06', label: 'Martha de Roldos', at: { lat: -2.157834, lon: -79.889898 } },
]

type Loadable =
  | { state: 'idle' }
  | { state: 'loading' }
  | { state: 'ready'; data: RouteResponse }
  | { state: 'error'; message: string }

function colorFor(route: Route): string {
  if (route.hazard_class === 'hazard_crossing') return tokens.dangerFg
  if (route.band === 'low' || route.band === 'none') return tokens.muted
  return tokens.teal700
}

function dashFor(route: Route): string {
  if (route.hazard_class === 'hazard_crossing') return '6 6'      // dashed = cross a closure
  if (route.band === 'low' || route.band === 'none') return '2 6' // dotted = poorly known
  return ''
}

/* ------------------------------------------------------------------ */
/* Measured extract facts                                              */
/* ------------------------------------------------------------------ */

interface GraphExtent {
  total_street_length_km: number
  bbox_span_km: Record<string, number>
}

/**
 * Read the measured extract size from /api/health.
 *
 * The map disclosure used to hardcode "about 50 km", which stayed on screen while the real graph
 * grew past 1,085 km. Quoting the API means the sentence cannot disagree with the data.
 */
function useExtentVars(locale: Locale): Record<string, string | null> {
  const [extent, setExtent] = useState<GraphExtent | null>(null)
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const res = await fetch('/api/health')
        if (!res.ok) return
        const data = (await res.json()) as { graph_extent?: GraphExtent }
        if (!cancelled && data.graph_extent) setExtent(data.graph_extent)
      } catch {
        // null -> tf() renders "unknown", never a guessed number.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])
  const km =
    extent === null
      ? null
      : `${extent.total_street_length_km.toLocaleString(locale === 'es' ? 'es-EC' : 'en-US', {
          minimumFractionDigits: 1,
          maximumFractionDigits: 1,
        })} km`
  const ns = extent?.bbox_span_km?.north_south
  const ew = extent?.bbox_span_km?.east_west
  const span = ns === undefined || ew === undefined ? null : `${ns} \u00d7 ${ew} km`
  return { streets: km, span }
}

/* ------------------------------------------------------------------ */
/* Map (lazy Leaflet)                                                  */
/* ------------------------------------------------------------------ */

function RouteMap({
  data,
  locale,
  onTileFailure,
}: {
  data: RouteResponse
  locale: Locale
  onTileFailure: () => void
}) {
  const holder = useRef<HTMLDivElement | null>(null)
  const [failed, setFailed] = useState(false)
  const extentVars = useExtentVars(locale)

  useEffect(() => {
    let disposed = false
    let map: import('leaflet').Map | null = null

    void (async () => {
      try {
        const L = await import('leaflet')
        // Leaflet ships its stylesheet separately; injecting it here keeps it out of first paint.
        if (!document.getElementById('leaflet-css')) {
          const link = document.createElement('link')
          link.id = 'leaflet-css'
          link.rel = 'stylesheet'
          link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'
          link.onerror = () => {
            setFailed(true)
            onTileFailure()
          }
          document.head.appendChild(link)
        }
        if (disposed || !holder.current) return

        map = L.map(holder.current, {
          zoomControl: true,
          attributionControl: true,
        }).setView([-2.19, -79.9], 13)

        const tiles = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 18,
          attribution: '&copy; OpenStreetMap contributors',
        })
        tiles.on('tileerror', () => {
          setFailed(true)
          onTileFailure()
        })
        tiles.addTo(map)

        for (const route of data.routes) {
          if (route.geometry.length < 2) continue
          const latlngs = route.geometry.map((p) => [p.lat, p.lon] as [number, number])
          L.polyline(latlngs, {
            color: colorFor(route),
            weight: route.rank === 1 ? 5 : 3,
            opacity: route.hazard_class === 'hazard_crossing' ? 0.6 : 0.9,
            dashArray: dashFor(route),
          })
            .addTo(map)
            .bindTooltip(`${route.id} · ${route.label}`, { sticky: true })
        }

        const bounds = L.latLngBounds(
          data.routes.flatMap((r) => r.geometry.map((p) => [p.lat, p.lon] as [number, number])),
        )
        if (bounds.isValid()) map.fitBounds(bounds, { padding: [24, 24] })
      } catch {
        if (!disposed) {
          setFailed(true)
          onTileFailure()
        }
      }
    })()

    return () => {
      disposed = true
      map?.remove()
    }
  }, [data, onTileFailure])

  return (
    <div>
      {failed && (
        <p
          style={{
            background: tokens.warnBg,
            color: tokens.warnFg,
            padding: '8px 12px',
            borderRadius: 8,
            fontSize: 13,
            margin: '0 0 8px',
          }}
        >
          {t('mapUnavailable', locale)}
        </p>
      )}
      <div
        ref={holder}
        role="img"
        aria-label={tf('mapNotRealStreets', locale, extentVars)}
        style={{
          height: 320,
          borderRadius: 10,
          border: `1px solid ${tokens.border}`,
          background: tokens.surfaceAlt,
        }}
      />
      <p style={{ fontSize: 12, color: tokens.muted, margin: '8px 0 0' }}>
        {tf('mapNotRealStreets', locale, extentVars)}
      </p>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Route card (the canonical, accessible view)                         */
/* ------------------------------------------------------------------ */

function RouteCard({ route, locale }: { route: Route; locale: Locale }) {
  const tr = (k: StringKey) => t(k, locale)
  const isHazard = route.hazard_class === 'hazard_crossing'

  return (
    <article
      style={{
        border: `1px solid ${isHazard ? tokens.dangerFg : tokens.border}`,
        borderLeft: `5px solid ${colorFor(route)}`,
        borderRadius: 10,
        padding: 12,
        marginBottom: 10,
        background: tokens.surface,
      }}
    >
      <header style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
        <strong style={{ fontSize: 14, color: tokens.navy900 }}>{route.id}</strong>
        {route.recommended ? (
          <span style={pill(tokens.teal50, tokens.teal700)}>{tr('routeRecommended')}</span>
        ) : (
          <span style={pill('#F1F5F9', tokens.muted)}>{tr('routeNotRecommended')}</span>
        )}
        {isHazard && (
          <span style={pill(tokens.dangerBg, tokens.dangerFg)}>{tr('routeHazardCrossing')}</span>
        )}
        {route.band === 'low' || route.band === 'none' ? (
          <span style={pill(tokens.warnBg, tokens.warnFg)}>{tr('routeLowCoverage')}</span>
        ) : null}
      </header>

      <p style={{ margin: '8px 0 4px', fontSize: 13, color: tokens.navy700 }}>{route.label}</p>

      <dl style={{ margin: '8px 0 0', display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(120px,1fr))', gap: 8 }}>
        <div>
          <dt style={dt}>{tr('routeDistance')}</dt>
          <dd style={dd}>{(route.distance_m / 1000).toFixed(2)} km</dd>
        </div>
        <div>
          <dt style={dt}>{tr('routeDuration')}</dt>
          <dd style={dd}>{Math.round(route.duration_s / 60)} min</dd>
          <dd style={{ margin: '2px 0 0', fontSize: 11, color: tokens.muted, fontWeight: 400 }}>
            {tr('routeEstimatedShort')}
          </dd>
        </div>
        <div>
          <dt style={dt}>{tr('routeCoverage')}</dt>
          <dd style={dd}>{route.coverage_pct.toFixed(0)}%</dd>
        </div>
        <div>
          <dt style={dt}>{tr('routePhase')}</dt>
          <dd style={{ ...dd, fontSize: 13, fontWeight: 600 }}>
            {route.phase === 1 ? tr('routePhase1') : tr('routePhase2')}
          </dd>
        </div>
      </dl>

      {route.elevation_used_as_tiebreak && (
        <p style={{ fontSize: 12, color: tokens.warnFg, margin: '6px 0 0' }}>
          {tr('routeElevationTiebreak')}
        </p>
      )}

      {route.warnings.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary style={{ cursor: 'pointer', fontSize: 13, color: tokens.navy700 }}>
            {tr('routeWarningsTitle')}
          </summary>
          <ul style={{ margin: '6px 0 0 16px', padding: 0, fontSize: 12, color: tokens.muted }}>
            <li>{tr('routeEstimatedTime')}</li>
            {route.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </details>
      )}
    </article>
  )
}

const pill = (bg: string, fg: string): React.CSSProperties => ({
  background: bg,
  color: fg,
  borderRadius: 999,
  padding: '2px 8px',
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: 0.3,
  textTransform: 'uppercase',
})
const dt: React.CSSProperties = { fontSize: 11, color: tokens.muted, margin: 0, textTransform: 'uppercase', letterSpacing: 0.4 }
const dd: React.CSSProperties = { margin: 0, fontSize: 18, fontWeight: 700, color: tokens.navy900 }

/* ------------------------------------------------------------------ */
/* Screen                                                              */
/* ------------------------------------------------------------------ */

export default function RouteScreen({ locale }: { locale: Locale }) {
  const tr = (k: StringKey) => t(k, locale)
  const [fromId, setFromId] = useState(DEMO_POINTS[0].id)
  const [toId, setToId] = useState(DEMO_POINTS[3].id)
  // Defaults to 'baseline' so the form's out-of-the-box behaviour is unchanged.
  const [profile, setProfile] = useState<StatusProfile>('baseline')
  const [load, setLoad] = useState<Loadable>({ state: 'idle' })
  const [view, setView] = useState<'list' | 'map'>('list')
  const [tileFailure, setTileFailure] = useState(false)
  const extentVars = useExtentVars(locale)

  const run = async () => {
    const from = DEMO_POINTS.find((p) => p.id === fromId)
    const to = DEMO_POINTS.find((p) => p.id === toId)
    if (!from || !to) return
    if (from.id === to.id) {
      setLoad({ state: 'error', message: 'Start and destination must differ.' })
      return
    }
    setLoad({ state: 'loading' })
    try {
      const data = await fetchRoute(from.at, to.at, 3, profile)
      setLoad({ state: 'ready', data })
    } catch (err) {
      setLoad({ state: 'error', message: (err as Error).message })
    }
  }

  useEffect(() => {
    void run()
    // Re-run whenever the scenario changes: a selector that does not refetch would leave stale
    // results on screen under the wrong scenario label. Also runs once on mount with the default
    // pair so the screen is never empty.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile])

  return (
    <section
      style={{
        background: tokens.surface,
        border: `1px solid ${tokens.border}`,
        borderRadius: 12,
        padding: 16,
        marginBottom: 16,
      }}
    >
      <h2 style={{ margin: '0 0 6px', fontSize: 16, color: tokens.navy900 }}>{tr('mapTitle')}</h2>
      <p style={{ margin: '0 0 10px', fontSize: 13, color: tokens.warnFg, fontWeight: 600 }}>
        {tf('mapNotRealStreets', locale, extentVars)}
      </p>
      <p style={{ margin: '0 0 10px', fontSize: 13, color: tokens.muted }}>{tr('mapPickPoints')}</p>

      {/* ---------------------------------------------------------------- */}
      {/* M12: road-status scenario selector.                              */}
      {/* Defaults to baseline; demo_clear is an explicitly labelled demo.  */}
      {/* ---------------------------------------------------------------- */}
      <div style={{ marginBottom: 14 }}>
        <label
          htmlFor="scenario-select"
          style={{ display: 'block', fontSize: 12, color: tokens.muted, marginBottom: 4 }}
        >
          {tr('scenarioLabel')}
        </label>
        <select
          id="scenario-select"
          value={profile}
          onChange={(e) => setProfile(e.target.value as StatusProfile)}
          aria-describedby="scenario-help"
          style={selectStyle}
        >
          <option value="baseline">{tr('scenarioBaseline')}</option>
          <option value="demo_clear">{tr('scenarioDemoClear')}</option>
        </select>
        <p
          id="scenario-help"
          style={{ margin: '6px 0 0', fontSize: 12, color: tokens.muted, maxWidth: 620 }}
        >
          {tr('scenarioHelp')}
        </p>
      </div>

      {/* Disclosure is rendered ONLY for the demo scenario, and is worded so it cannot be
          read as a claim about real roads. It is not dismissible: a dismissible warning about
          simulated data is a warning people stop seeing. */}
      {profile === 'demo_clear' && (
        <div
          role="status"
          style={{
            marginBottom: 14,
            padding: '10px 12px',
            borderLeft: `4px solid ${tokens.warnFg}`,
            background: tokens.warnBg,
            borderRadius: 4,
            fontSize: 13,
            color: tokens.warnFg,
            fontWeight: 600,
            maxWidth: 620,
          }}
        >
          {tr('scenarioDemoWarning')}
        </div>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'end' }}>
        <label style={{ fontSize: 12, color: tokens.muted }}>
          {tr('mapStart')}
          <select
            value={fromId}
            onChange={(e) => setFromId(e.target.value)}
            style={selectStyle}
          >
            {DEMO_POINTS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.id} — {p.label}
              </option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: 12, color: tokens.muted }}>
          {tr('mapDestination')}
          <select value={toId} onChange={(e) => setToId(e.target.value)} style={selectStyle}>
            {DEMO_POINTS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.id} — {p.label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={() => void run()} style={buttonStyle}>
          {tr('mapFindRoute')}
        </button>        {load.state === 'ready' && (
          <button
            type="button"
            onClick={() => setView(view === 'list' ? 'map' : 'list')}
            style={{ ...buttonStyle, background: tokens.surface, color: tokens.teal700, border: `1px solid ${tokens.teal700}` }}
          >
            {view === 'list' ? tr('viewMap') : tr('viewList')}
          </button>
        )}
      </div>

      <div style={{ marginTop: 14 }}>
        {load.state === 'loading' && <p style={{ fontSize: 13, color: tokens.muted }}>{tr('mapLoading')}</p>}

        {load.state === 'error' && (
          <div style={{ background: tokens.warnBg, color: '#7C2D12', borderRadius: 8, padding: 12 }}>
            <strong style={{ fontSize: 13 }}>{tr('errorTitle')}</strong>
            <p style={{ margin: '4px 0 0', fontSize: 13 }}>{tr('errorBody')}</p>
            <p style={{ margin: '4px 0 0', fontSize: 12, opacity: 0.8 }}>{load.message}</p>
          </div>
        )}

        {load.state === 'ready' && (
          <>
            {load.data.refused && (
              <div style={{ background: tokens.warnBg, color: '#7C2D12', borderRadius: 8, padding: 12, marginBottom: 10 }}>
                <strong style={{ fontSize: 13 }}>{tr('mapNoRoute')}</strong>
                <p style={{ margin: '4px 0 0', fontSize: 13 }}>{load.data.refusal_reason}</p>
              </div>
            )}

            {load.data.all_routes_hazard_crossing && (
              <p style={{ background: tokens.dangerBg, color: tokens.dangerFg, borderRadius: 8, padding: '8px 12px', fontSize: 13, fontWeight: 600, margin: '0 0 10px' }}>
                {tr('routeAllHazard')}
              </p>
            )}
            {load.data.best_available_is_uncertain && (
              <p style={{ background: tokens.warnBg, color: tokens.warnFg, borderRadius: 8, padding: '8px 12px', fontSize: 13, fontWeight: 600, margin: '0 0 10px' }}>
                {tr('routeUncertainBest')}
              </p>
            )}

            {view === 'map' && load.data.routes.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <RouteMap
                  data={load.data}
                  locale={locale}
                  onTileFailure={() => setTileFailure(true)}
                />
              </div>
            )}

            {load.data.routes.map((r) => (
              <RouteCard key={r.id} route={r} locale={locale} />
            ))}

            <p
              style={{
                fontSize: 12,
                color: tokens.muted,
                borderTop: `1px solid ${tokens.border}`,
                paddingTop: 8,
                margin: '10px 0 0',
              }}
            >
              {tr('routeNotSafe')}
              {tileFailure ? ` ${tr('mapUnavailable')}` : ''}
            </p>
          </>
        )}
      </div>
    </section>
  )
}

const selectStyle: React.CSSProperties = {
  display: 'block',
  marginTop: 4,
  padding: '8px 10px',
  minHeight: 44,
  borderRadius: 8,
  border: `1px solid ${tokens.border}`,
  background: tokens.surface,
  fontSize: 13,
  color: tokens.navy900,
  fontFamily: fontStack,
  // Was a hard 180px: two of these side by side plus gap and page padding came to ~402px and
  // overflowed a 375px viewport. `maxWidth: 100%` with a smaller floor lets them shrink.
  minWidth: 150,
  maxWidth: '100%',
  flex: '1 1 150px',
}

const buttonStyle: React.CSSProperties = {
  padding: '10px 16px',
  minHeight: 44,
  borderRadius: 8,
  border: `1px solid ${tokens.teal700}`,
  background: tokens.teal700,
  color: '#fff',
  fontWeight: 600,
  fontSize: 13,
  cursor: 'pointer',
  fontFamily: fontStack,
}
