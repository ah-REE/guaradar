/**
 * Public dashboard — the first functional vertical slice (M6).
 *
 * Sections, per the M6 brief:
 *   A. Current data status   — availability, source, fetch time, model-run time (or its absence)
 *   B. Sensor status         — SIMULATED prominently, honest health, no green "safe" styling
 *   C. Limitations           — bounded-extract disclosure, status-is-demo-data, no risk level
 *   D. Language              — EN primary, ES via a visible toggle, both complete
 *   E. Failure states        — loading, error, unavailable, stale, empty
 *
 * Until M12 this header said section C was "purely synthetic" and that routing was "not
 * exposed". Both became FALSE — the graph is a real OSM extract and routing shipped — and the
 * stale sentences were still being rendered to users. They are now derived from /api/health
 * (see useGraphExtent) and asserted by tests in test_m12_disclosures.py.
 *
 * What this STATUS screen deliberately does NOT do:
 *   - show a combined risk level (O-7 is unresolved; presenting it as settled would
 *     contradict the project's own honesty rules)
 *   - fall back to fixture values when the API fails
 *
 * Routing lives on the separate Route tab (RouteScreen.tsx), not here.
 */

import { useCallback, useEffect, useState } from 'react'
import {
  ApiError,
  fetchForecast,
  fetchSensors,
  type ForecastResponse,
  type SensorsResponse,
} from './api'
import { STRINGS, type Locale, type StringKey, t, tf } from './i18n'
import { tokens, fontStack } from './tokens'
import RouteScreen from './RouteScreen'
import AdminScreen from './AdminScreen'
import ErrorBoundary from './ErrorBoundary'

type Loadable<T> =
  | { state: 'loading' }
  | { state: 'ready'; data: T }
  | { state: 'error'; kind: ApiError['kind']; message: string }

/* ------------------------------------------------------------------ */
/* Small presentational pieces                                         */
/* ------------------------------------------------------------------ */

function Card({
  title,
  children,
  tone = 'plain',
}: {
  title?: string
  children: React.ReactNode
  tone?: 'plain' | 'warning' | 'sim'
}) {
  const bg =
    tone === 'warning' ? tokens.warnBg : tone === 'sim' ? tokens.simBg : tokens.surface
  const border = tone === 'warning' ? tokens.warnFg : tokens.simFg
  return (
    <section
      style={{
        background: bg,
        border: `1px solid ${tone === 'plain' ? tokens.border : border}`,
        borderRadius: 12,
        padding: 16,
        marginBottom: 16,
      }}
    >
      {title && (
        <h2
          style={{
            margin: '0 0 10px',
            fontSize: 16,
            color: tokens.navy900,
            letterSpacing: 0.2,
          }}
        >
          {title}
        </h2>
      )}
      {children}
    </section>
  )
}

function Badge({ text, fg, bg }: { text: string; fg: string; bg: string }) {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 999,
        background: bg,
        color: fg,
        fontSize: 12,
        fontWeight: 700,
        letterSpacing: 0.4,
        textTransform: 'uppercase',
      }}
    >
      {text}
    </span>
  )
}

function Muted({ children }: { children: React.ReactNode }) {
  return <p style={{ margin: '4px 0', color: tokens.muted, fontSize: 13 }}>{children}</p>
}

/** Absolute timestamp with locale formatting and an explicit offset. */
/** Safe numeric formatting.
 *
 * `value.toFixed(n)` throws `TypeError: Cannot read properties of null` when the API returns
 * null — which it does for `latest` on an offline sensor. That would crash the render and blank
 * the page (the same failure mode as the timestamp bug). A missing number must render as "—",
 * never as a crash and never as a fabricated 0.
 */
function num(value: number | null | undefined, digits: number): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toFixed(digits)
}

/** Absolute timestamp with locale formatting, pinned to Guayaquil local time.
 *
 * WHY THIS IS BUILT BY HAND — a real browser bug found during integration:
 *   `new Date(iso).toLocaleString(locale, { dateStyle, timeStyle, timeZoneName })`
 *   throws `RangeError: Invalid option : option` in V8, because `dateStyle`/`timeStyle`
 *   may NOT be combined with a component option such as `timeZoneName`.
 *
 *   That threw during render, React unmounted the tree, and the page went blank — the
 *   "loads forever then blank" symptom. It only affected the Status tab, because that is the
 *   only place timestamps were rendered; the Route tab never called this function.
 *
 * SECOND BUG, found while fixing the first: without an explicit `timeZone`, the output used
 * the VIEWER'S timezone. On a machine in IST that rendered "08:30 GMT+5:30" for a 03:00Z
 * forecast — wrong local time for a Guayaquil app, and misleading. The timezone is now
explicitly `America/Guayaquil`, which is the only sensible interpretation of "local time" here.
 *
 * Wrapped in try/catch so a missing locale can never blank the page again.
 */
const APP_TIMEZONE = 'America/Guayaquil'

function stamp(iso: string | null, locale: Locale): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const tag = locale === 'es' ? 'es-EC' : 'en-GB'
  try {
    // Date + time without timeZoneName — that combination is what throws.
    const base = d.toLocaleString(tag, {
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: APP_TIMEZONE,
    })
    // The zone name is resolved separately; failures degrade to no suffix.
    let zone = ''
    try {
      const parts = new Intl.DateTimeFormat(tag, {
        timeZoneName: 'short',
        timeZone: APP_TIMEZONE,
      }).formatToParts(d)
      zone = parts.find((p) => p.type === 'timeZoneName')?.value ?? ''
    } catch {
      zone = ''
    }
    return zone ? `${base} ${zone}` : base
  } catch {
    // Absolute worst case: the ISO string is still honest and readable.
    return iso
  }
}

function ageLabel(seconds: number | null, locale: Locale): string {
  if (seconds === null) return '—'
  const mins = Math.round(seconds / 60)
  return locale === 'es' ? `hace ${mins} min` : `${mins} min ago`
}

/* ------------------------------------------------------------------ */
/* Section A — current data status                                     */
/* ------------------------------------------------------------------ */

function ForecastSection({ load, locale }: { load: Loadable<ForecastResponse>; locale: Locale }) {
  const tr = (k: StringKey) => t(k, locale)

  if (load.state === 'loading') {
    return (
      <Card title={tr('dataStatusTitle')}>
        <Muted>{tr('loading')}</Muted>
      </Card>
    )
  }
  if (load.state === 'error') {
    return (
      <Card title={tr('dataStatusTitle')} tone="warning">
        <p style={{ margin: '0 0 6px', fontWeight: 600, color: tokens.warnFg }}>
          {tr('forecastUnavailable')}
        </p>
        <Muted>{tr('errorBody')}</Muted>
      </Card>
    )
  }

  const d = load.data
  const chipStale = d.provenance.chip === 'stale' || d.provenance.chip === 'no_data'
  const source = d.provenance.sources[0]

  return (
    <Card title={tr('dataStatusTitle')}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
        <Badge
          text={d.ok ? tr('forecastAvailable') : tr('forecastUnavailable')}
          fg={d.ok ? tokens.okFg : tokens.warnFg}
          bg={d.ok ? tokens.teal50 : tokens.warnBg}
        />
        {chipStale && (
          <Badge text={tr('forecastStale')} fg={tokens.warnFg} bg={tokens.warnBg} />
        )}
        <Badge text={d.provenance.chip.replace('_', ' ')} fg={tokens.infoFg} bg={tokens.infoBg} />
      </div>

      {!d.ok ? (
        <Muted>{d.error ?? tr('unavailable')}</Muted>
      ) : (
        <>
          <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <div>
              <dt style={dtStyle}>{tr('totalRainfall')}</dt>
              <dd style={ddStyle}>
                {d.total_mm} {d.units}
              </dd>
            </div>
            <div>
              <dt style={dtStyle}>{tr('peakHourly')}</dt>
              <dd style={ddStyle}>
                {d.max_hourly_mm ?? '—'} {d.units}
              </dd>
            </div>
          </dl>
          <Muted>
            {d.hours.length} {tr('hoursShown')} · {tr('forecastNotObservation')}
          </Muted>
        </>
      )}

      <div style={{ marginTop: 10, borderTop: `1px solid ${tokens.border}`, paddingTop: 10 }}>
        <Muted>
          <strong>{tr('source')}:</strong> {source?.name ?? '—'}
        </Muted>
        <Muted>
          <strong>{tr('fetchTime')}:</strong> {stamp(d.provenance.fetched_at, locale)}
        </Muted>
        <Muted>
          <strong>{tr('modelRunTime')}:</strong>{' '}
          {source?.model_run_at ? stamp(source.model_run_at, locale) : tr('modelRunUnavailable')}
        </Muted>
        {!source?.model_run_at && <Muted>{tr('modelRunNeverInferred')}</Muted>}
        {d.provenance.notes.length > 0 && (
          <details style={{ marginTop: 6 }}>
            <summary style={{ cursor: 'pointer', fontSize: 13, color: tokens.muted }}>
              {locale === 'es' ? 'Notas de procedencia' : 'Provenance notes'}
            </summary>
            <ul style={{ margin: '6px 0 0 16px', padding: 0, fontSize: 13, color: tokens.muted }}>
              {d.provenance.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </Card>
  )
}

const dtStyle: React.CSSProperties = { fontSize: 12, color: tokens.muted, margin: 0 }
const ddStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 22,
  fontWeight: 700,
  color: tokens.navy900,
}

/* ------------------------------------------------------------------ */
/* Section B — sensors                                                 */
/* ------------------------------------------------------------------ */

function SensorsSection({ load, locale }: { load: Loadable<SensorsResponse>; locale: Locale }) {
  const tr = (k: StringKey) => t(k, locale)

  if (load.state === 'loading') {
    return (
      <Card title={tr('sensorsTitle')}>
        <Muted>{tr('loading')}</Muted>
      </Card>
    )
  }
  if (load.state === 'error') {
    return (
      <Card title={tr('sensorsTitle')} tone="warning">
        <Muted>{tr('errorBody')}</Muted>
      </Card>
    )
  }

  const d = load.data
  if (!d.available || d.sensors.length === 0) {
    return (
      <Card title={tr('sensorsTitle')} tone="sim">
        <Muted>{tr('sensorFeedEmpty')}</Muted>
      </Card>
    )
  }

  return (
    <Card title={tr('sensorsTitle')} tone="sim">
      <div style={{ marginBottom: 10 }}>
        <Badge text={tr('simulatedBadge')} fg={tokens.simFg} bg="#FFEDD5" />
        <p style={{ margin: '8px 0 0', fontSize: 13, color: tokens.simFg, fontWeight: 600 }}>
          {tr('simulatedExplanation')}
        </p>
      </div>

      <div
        style={{
          display: 'grid',
          // auto-fit (not auto-fill) collapses the empty track on narrow screens; 180px lets two
          // columns fit at 375px-ish widths and one below that, with no horizontal overflow.
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: 10,
        }}
      >
        {d.sensors.map((s) => {
          const healthColor =
            s.health === 'ok'
              ? tokens.okFg
              : s.health === 'degraded'
                ? tokens.watchFg
                : tokens.dangerFg
          const healthText =
            s.health === 'ok'
              ? tr('healthOk')
              : s.health === 'degraded'
                ? tr('healthDegraded')
                : tr('healthOffline')
          return (
            <article
              key={s.sensor_id}
              style={{
                background: tokens.surface,
                border: `1px solid ${tokens.border}`,
                borderRadius: 10,
                padding: 12,
              }}
            >
              <header style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                <strong style={{ fontSize: 14, color: tokens.navy900 }}>{s.sensor_id}</strong>
                <Badge text={tr('simulatedBadge')} fg={tokens.simFg} bg="#FFEDD5" />
              </header>
              <Muted>
                {s.sector_id} · {s.profile}
              </Muted>
              <Muted>
                <span style={{ color: healthColor, fontWeight: 700 }}>●</span> {healthText}
              </Muted>
              {s.latest ? (
                <>
                  <div style={{ fontSize: 20, fontWeight: 700, color: tokens.navy900 }}>
                    {num(s.latest.depth_m, 2)} m
                  </div>
                  <Muted>
                    {tr('depth')} · {num(s.latest.fraction_of_threshold * 100, 0)}% ·{' '}
                    {tr('threshold')} {num(s.threshold_m, 2)} m
                  </Muted>
                  <Muted>
                    {tr('lastReading')}: {ageLabel(s.last_reading_age_s, locale)}
                  </Muted>
                </>
              ) : (
                <Muted>{tr('sensorFeedEmpty')}</Muted>
              )}
            </article>
          )
        })}
      </div>
      <Muted>{tr('thresholdNote')}</Muted>
      <Muted>
        {tr('fetchTime')}: {stamp(d.provenance.fetched_at, locale)}
      </Muted>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* Measured extract facts                                              */
/* ------------------------------------------------------------------ */

interface GraphExtent {
  synthetic: boolean
  segments: number
  nodes: number
  total_street_length_km: number
  bbox_span_km: Record<string, number>
}

/**
 * Fetch the measured graph facts once.
 *
 * The alternative — hardcoding "1,085 km" in the copy — is exactly what produced the stale
 * "50 km" claim this replaces. Numbers quoted in disclosure text must come from the data.
 */
function useGraphExtent(): GraphExtent | null {
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
        // Leave null: tf() renders "unknown" rather than a guessed figure.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])
  return extent
}

/** "1,084.5 km (12.8 x 6.4 km)" — or sensible partial forms when a field is absent. */
function extentVars(extent: GraphExtent | null, locale: Locale) {
  const km =
    extent === null
      ? null
      : `${extent.total_street_length_km.toLocaleString(locale === 'es' ? 'es-EC' : 'en-US', {
          minimumFractionDigits: 1,
          maximumFractionDigits: 1,
        })} km`
  const ns = extent?.bbox_span_km?.north_south
  const ew = extent?.bbox_span_km?.east_west
  const span =
    ns === undefined || ew === undefined
      ? null
      : locale === 'es'
        ? `${ns} \u00d7 ${ew} km`
        : `${ns} \u00d7 ${ew} km`
  return { streets: km, span }
}

/* ------------------------------------------------------------------ */
/* Section C — limitations and provenance                              */
/* ------------------------------------------------------------------ */

function LimitationsSection({ locale }: { locale: Locale }) {
  const tr = (k: StringKey) => t(k, locale)
  const extent = useGraphExtent()
  const vars = extentVars(extent, locale)
  return (
    <Card title={tr('limitationsTitle')} tone="warning">
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.6, color: '#7C2D12' }}>
        <li>{tf('syntheticGraph', locale, vars)}</li>
        <li>{tr('noRouteApi')}</li>
        <li>{tr('pathIsNotSafety')}</li>
        <li>{tr('riskNotApproved')}</li>
        <li>{tr('noFabricatedData')}</li>
      </ul>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* App                                                                 */
/* ------------------------------------------------------------------ */

const TAB_LABEL = {
  status: 'tabStatus',
  route: 'tabRoute',
  admin: 'tabAdmin',
} as const satisfies Record<'status' | 'route' | 'admin', StringKey>

export default function App() {
  const [locale, setLocale] = useState<Locale>('en')
  const [tab, setTab] = useState<'status' | 'route' | 'admin'>('status')
  const [forecast, setForecast] = useState<Loadable<ForecastResponse>>({ state: 'loading' })
  const [sensors, setSensors] = useState<Loadable<SensorsResponse>>({ state: 'loading' })

  const tr = useCallback((k: StringKey) => t(k, locale), [locale])

  const loadAll = useCallback(async () => {
    setForecast({ state: 'loading' })
    setSensors({ state: 'loading' })

    try {
      const data = await fetchForecast(24)
      setForecast({ state: 'ready', data })
    } catch (err) {
      const e = err as ApiError
      setForecast({ state: 'error', kind: e.kind ?? 'network', message: e.message })
    }

    try {
      const data = await fetchSensors(6)
      setSensors({ state: 'ready', data })
    } catch (err) {
      const e = err as ApiError
      setSensors({ state: 'error', kind: e.kind ?? 'network', message: e.message })
    }
  }, [])

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  const anyError = forecast.state === 'error' && sensors.state === 'error'

  return (
    <div
      style={{
        fontFamily: fontStack,
        color: tokens.navy900,
        background: tokens.surfaceAlt,
        minHeight: '100vh',
        padding: '0 0 32px',
      }}
    >
      <a
        href="#main"
        style={{
          position: 'absolute',
          left: -9999,
          top: 0,
        }}
        onFocus={(e) => {
          e.currentTarget.style.left = '8px'
          e.currentTarget.style.top = '8px'
        }}
        onBlur={(e) => {
          e.currentTarget.style.left = '-9999px'
        }}
      >
        Skip to content
      </a>

      <header
        style={{
          background: tokens.navy900,
          color: '#fff',
          padding: '14px 16px',
          marginBottom: 16,
        }}
      >
        <div
          style={{
            maxWidth: 960,
            margin: '0 auto',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 12,
          }}
        >
          <div>
            <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: 0.3 }}>
              {tr('appName')}
            </div>
            <div style={{ fontSize: 12, opacity: 0.85 }}>{tr('tagline')}</div>
          </div>
          <button
            type="button"
            onClick={() => setLocale(locale === 'en' ? 'es' : 'en')}
            aria-label={`Switch language to ${locale === 'en' ? 'Spanish' : 'English'}`}
            style={{
              background: 'transparent',
              color: '#fff',
              border: '1px solid rgba(255,255,255,0.5)',
              borderRadius: 8,
              padding: '6px 12px',
              fontSize: 13,
              cursor: 'pointer',
              minHeight: 44,
            }}
          >
            {tr('languageLabel')}
          </button>
        </div>
      </header>

      <main id="main" style={{ maxWidth: 960, margin: '0 auto', padding: '0 16px' }}>
        <div
          style={{
            background: tokens.infoBg,
            color: tokens.infoFg,
            borderRadius: 8,
            padding: '8px 12px',
            fontSize: 13,
            fontWeight: 600,
            marginBottom: 16,
          }}
          role="status"
        >
          {tr('prototypeBanner')}
        </div>

        {anyError && (
          <Card tone="warning">
            <p style={{ margin: '0 0 6px', fontWeight: 700, color: tokens.warnFg }}>
              {tr('errorTitle')}
            </p>
            <Muted>{tr('errorBody')}</Muted>
            <button
              type="button"
              onClick={() => void loadAll()}
              style={{
                marginTop: 8,
                padding: '10px 16px',
                minHeight: 44,
                borderRadius: 8,
                border: `1px solid ${tokens.teal700}`,
                background: tokens.teal700,
                color: '#fff',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {tr('retry')}
            </button>
          </Card>
        )}

        <nav
          aria-label="Sections"
          style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}
        >
          {(['status', 'route', 'admin'] as const).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              aria-current={tab === key ? 'page' : undefined}
              style={{
                padding: '10px 16px',
                minHeight: 44,
                borderRadius: 8,
                border: `1px solid ${tab === key ? tokens.teal700 : tokens.border}`,
                background: tab === key ? tokens.teal700 : tokens.surface,
                color: tab === key ? '#fff' : tokens.navy700,
                fontWeight: 600,
                fontSize: 13,
                cursor: 'pointer',
                fontFamily: fontStack,
              }}
            >
              {tr(TAB_LABEL[key])}
            </button>
          ))}
        </nav>

        {tab === 'admin' ? (
          <ErrorBoundary section="Admin" locale={locale}>
            <AdminScreen locale={locale} />
          </ErrorBoundary>
        ) : tab === 'status' ? (
          <>
            <ErrorBoundary section={locale === 'es' ? 'pronóstico' : 'forecast'} locale={locale}>
              <ForecastSection load={forecast} locale={locale} />
            </ErrorBoundary>
            <ErrorBoundary section={locale === 'es' ? 'sensores' : 'sensors'} locale={locale}>
              <SensorsSection load={sensors} locale={locale} />
            </ErrorBoundary>
          </>
        ) : (
          <ErrorBoundary section={locale === 'es' ? 'ruta' : 'route'} locale={locale}>
            <RouteScreen locale={locale} />
          </ErrorBoundary>
        )}
        <LimitationsSection locale={locale} />

        <footer style={{ fontSize: 12, color: tokens.muted, textAlign: 'center', marginTop: 8 }}>
          {tr('footerAttribution')}
        </footer>
      </main>
    </div>
  )
}

// Referenced so the compiler keeps the strings object in the bundle for the export check.
export { STRINGS }
