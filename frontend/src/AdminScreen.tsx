/**
 * Admin control centre — READ-ONLY PROTOTYPE.
 *
 * DESIGN CONSTRAINT (see adminData.ts for the long version)
 *   The backend has no admin routes, no incidents, alerts or shelters tables, and no mutation
 *   verb. So this screen does two honest things and refuses to do a third:
 *
 *     derives   road-status counts from the legs of real route responses, labelled as a SAMPLE
 *     states    plainly that incidents, alerts and shelters have no data source at all
 *     refuses   to fabricate records, to fake a save, or to imply a role check that does not exist
 *
 *   A blank panel with "no data source" is the truthful rendering of a missing feature. A panel
 *   full of invented incidents would demo better and be a lie, which is the one thing this
 *   project has refused to do at every stage.
 *
 * ACCESSIBILITY
 *   Disabled controls are real `disabled` buttons carrying their reason in visible text, not
 *   `title`-only tooltips. Colour is never the only channel: every status also carries a word.
 */

import { useCallback, useEffect, useState } from 'react'
import { t, type Locale, type StringKey } from './i18n'
import { tokens, fontStack } from './tokens'
import { fetchRoute, type RouteResponse } from './routeApi'
import {
  DISABLED_ACTIONS,
  SAMPLE_PAIRS,
  SAMPLE_POINTS,
  deriveStatusSample,
  type DerivedStatusSample,
} from './adminData'

type Loadable<T> =
  | { state: 'loading' }
  | { state: 'ready'; data: T }
  | { state: 'error'; message: string }

/* ------------------------------------------------------------------ */
/* Small pieces                                                        */
/* ------------------------------------------------------------------ */

function Panel({
  title,
  subtitle,
  children,
  tone = 'plain',
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
  tone?: 'plain' | 'warning' | 'empty'
}) {
  const bg =
    tone === 'warning' ? tokens.warnBg : tone === 'empty' ? tokens.surfaceAlt : tokens.surface
  const border = tone === 'warning' ? tokens.warnFg : tokens.border
  return (
    <section
      style={{
        background: bg,
        border: `1px solid ${border}`,
        borderRadius: 12,
        padding: 16,
        marginBottom: 16,
      }}
    >
      <h2 style={{ margin: '0 0 4px', fontSize: 16, color: tokens.navy900 }}>{title}</h2>
      {subtitle && (
        <p style={{ margin: '0 0 10px', fontSize: 12, color: tokens.muted }}>{subtitle}</p>
      )}
      {children}
    </section>
  )
}

function Chip({ text, fg, bg }: { text: string; fg: string; bg: string }) {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 999,
        background: bg,
        color: fg,
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: 0.4,
        textTransform: 'uppercase',
      }}
    >
      {text}
    </span>
  )
}

/** Honest empty state: says what is missing and why, never a fake row. */
function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div
      role="status"
      style={{
        border: `1px dashed ${tokens.border}`,
        borderRadius: 8,
        padding: 14,
        background: tokens.surface,
      }}
    >
      <p style={{ margin: '0 0 6px', fontSize: 13, fontWeight: 700, color: tokens.navy700 }}>
        {title}
      </p>
      <p style={{ margin: 0, fontSize: 12, lineHeight: 1.6, color: tokens.muted }}>{body}</p>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Road status sample                                                  */
/* ------------------------------------------------------------------ */

function statusColour(key: string): { fg: string; bg: string } {
  switch (key) {
    case 'closed':
      return { fg: tokens.dangerFg, bg: tokens.dangerBg }
    case 'affected':
      return { fg: tokens.warnFg, bg: tokens.warnBg }
    case 'open':
      return { fg: tokens.okFg, bg: tokens.teal50 }
    default:
      return { fg: tokens.muted, bg: tokens.surfaceAlt }
  }
}

function RoadStatusPanel({ sample, locale }: { sample: DerivedStatusSample; locale: Locale }) {
  const tr = (k: StringKey) => t(k, locale)
  const rows: { key: string; label: StringKey; count: number }[] = [
    { key: 'open', label: 'adminStatusOpen', count: sample.tally.open },
    { key: 'affected', label: 'adminStatusAffected', count: sample.tally.affected },
    { key: 'closed', label: 'adminStatusClosed', count: sample.tally.closed },
    { key: 'unknown', label: 'adminStatusUnknown', count: sample.tally.unknown },
  ]

  return (
    <Panel title={tr('adminRoadStatusTitle')} subtitle={tr('adminRoadStatusExplain')}>
      <dl
        style={{
          margin: '0 0 12px',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
          gap: 10,
        }}
      >
        <div>
          <dt style={dtStyle}>{tr('adminSampleSize')}</dt>
          <dd style={ddStyle}>{sample.tally.total.toLocaleString()}</dd>
        </div>
        <div>
          <dt style={dtStyle}>{tr('adminRoutesSampled')}</dt>
          <dd style={ddStyle}>{sample.routesSampled}</dd>
        </div>
        <div>
          <dt style={dtStyle}>{tr('adminVerifiedShare')}</dt>
          <dd style={ddStyle}>{sample.verifiedPct.toFixed(1)}%</dd>
        </div>
      </dl>

      <ul style={{ listStyle: 'none', margin: '0 0 12px', padding: 0 }}>
        {rows.map((r) => {
          const c = statusColour(r.key)
          const pct = sample.tally.total === 0 ? 0 : (r.count / sample.tally.total) * 100
          return (
            <li
              key={r.key}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '6px 0',
                borderBottom: `1px solid ${tokens.border}`,
              }}
            >
              <Chip text={tr(r.label)} fg={c.fg} bg={c.bg} />
              <span style={{ fontSize: 13, color: tokens.navy700, fontWeight: 600 }}>
                {r.count.toLocaleString()}
              </span>
              <span style={{ fontSize: 12, color: tokens.muted }}>({pct.toFixed(1)}%)</span>
            </li>
          )
        })}
      </ul>

      <p style={{ margin: '0 0 8px', fontSize: 12, color: tokens.muted, lineHeight: 1.6 }}>
        {tr('adminUnknownNote')}
      </p>

      <p style={{ margin: 0, fontSize: 12, color: tokens.muted }}>
        <strong>{tr('adminStatusSource')}:</strong>{' '}
        <code style={{ fontFamily: 'ui-monospace, monospace', wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
          {sample.statusSource ?? 'unknown'}
        </code>{' '}
        — {sample.statusRecordsMatched === 0
          ? locale === 'es'
            ? 'ningún registro persistido coincidió; se usó el generador de demostración'
            : 'no persisted record matched; the demo generator was used'
          : locale === 'es'
            ? `${sample.statusRecordsMatched} registros persistidos coincidieron`
            : `${sample.statusRecordsMatched} persisted record(s) matched`}
      </p>
    </Panel>
  )
}

const dtStyle: React.CSSProperties = {
  fontSize: 11,
  color: tokens.muted,
  margin: 0,
  textTransform: 'uppercase',
  letterSpacing: 0.4,
}
const ddStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 20,
  fontWeight: 700,
  color: tokens.navy900,
}

/* ------------------------------------------------------------------ */
/* Screen                                                              */
/* ------------------------------------------------------------------ */

export default function AdminScreen({ locale }: { locale: Locale }) {
  const tr = (k: StringKey) => t(k, locale)
  const [load, setLoad] = useState<Loadable<DerivedStatusSample>>({ state: 'loading' })

  const sample = useCallback(async () => {
    setLoad({ state: 'loading' })
    try {
      // Spread across sectors so the sample is not one corridor. A refused pair simply
      // contributes nothing; it is not an error.
      const settled = await Promise.all(
        SAMPLE_PAIRS.map(async ([a, b]) => {
          const from = SAMPLE_POINTS[a]
          const to = SAMPLE_POINTS[b]
          try {
            return await fetchRoute(
              { lat: from.lat, lon: from.lon },
              { lat: to.lat, lon: to.lon },
              3,
              'baseline',
            )
          } catch {
            return null as RouteResponse | null
          }
        }),
      )
      const responses = settled.filter((r): r is RouteResponse => r !== null)
      if (responses.length === 0) {
        setLoad({ state: 'error', message: 'no route responses' })
        return
      }
      setLoad({ state: 'ready', data: deriveStatusSample(responses, 'baseline') })
    } catch (err) {
      setLoad({ state: 'error', message: (err as Error).message })
    }
  }, [])

  useEffect(() => {
    void sample()
  }, [sample])

  return (
    <>
      {/* Prototype banner — always visible, not dismissible. A dismissible notice about an
          unauthorised panel is a notice operators stop reading. */}
      <div
        role="alert"
        style={{
          background: tokens.warnBg,
          border: `1px solid ${tokens.warnFg}`,
          borderLeft: `5px solid ${tokens.warnFg}`,
          borderRadius: 10,
          padding: '12px 14px',
          marginBottom: 16,
        }}
      >
        <p style={{ margin: '0 0 6px', fontSize: 14, fontWeight: 800, color: tokens.warnFg }}>
          {tr('adminPrototype')}
        </p>
        <p style={{ margin: 0, fontSize: 13, lineHeight: 1.6, color: tokens.warnFg }}>
          {tr('adminPrototypeBody')}
        </p>
      </div>

      <Panel title={tr('adminOverviewTitle')}>
        <dl
          style={{
            margin: 0,
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
            gap: 10,
          }}
        >
          <div>
            <dt style={dtStyle}>{tr('adminDataMode')}</dt>
            <dd style={{ margin: 0 }}>
              <Chip text="MIXED" fg={tokens.simFg} bg={tokens.simBg} />
            </dd>
          </div>
          <div>
            <dt style={dtStyle}>{tr('adminRoadStatusTitle')}</dt>
            <dd style={{ margin: 0, fontSize: 13, color: tokens.navy700 }}>
              {load.state === 'ready'
                ? `${load.data.tally.total.toLocaleString()} ${
                    locale === 'es' ? 'tramos' : 'edges'
                  }`
                : load.state === 'loading'
                  ? tr('adminLoading')
                  : '—'}
            </dd>
          </div>
          <div>
            <dt style={dtStyle}>{tr('adminIncidentsTitle')}</dt>
            <dd style={{ margin: 0 }}>
              <Chip text={tr('adminNotAvailable')} fg={tokens.muted} bg={tokens.surfaceAlt} />
            </dd>
          </div>
          <div>
            <dt style={dtStyle}>{tr('adminAlertsTitle')}</dt>
            <dd style={{ margin: 0 }}>
              <Chip text={tr('adminNotAvailable')} fg={tokens.muted} bg={tokens.surfaceAlt} />
            </dd>
          </div>
        </dl>
        <p style={{ margin: '10px 0 0', fontSize: 12, color: tokens.muted, lineHeight: 1.6 }}>
          {tr('adminMixedExplain')}
        </p>
      </Panel>

      {load.state === 'loading' && (
        <Panel title={tr('adminRoadStatusTitle')}>
          <p role="status" style={{ margin: 0, fontSize: 13, color: tokens.muted }}>
            {tr('adminLoading')}
          </p>
        </Panel>
      )}

      {load.state === 'error' && (
        <Panel title={tr('adminRoadStatusTitle')} tone="warning">
          <p role="alert" style={{ margin: '0 0 10px', fontSize: 13, color: tokens.warnFg }}>
            {tr('adminSampleFailed')}
          </p>
          <button
            type="button"
            onClick={() => void sample()}
            style={{
              padding: '10px 16px',
              minHeight: 44,
              borderRadius: 8,
              border: `1px solid ${tokens.warnFg}`,
              background: tokens.surface,
              color: tokens.warnFg,
              fontWeight: 700,
              fontSize: 13,
              cursor: 'pointer',
              fontFamily: fontStack,
            }}
          >
            {tr('retry')}
          </button>
        </Panel>
      )}

      {load.state === 'ready' && (
        <>
          <RoadStatusPanel sample={load.data} locale={locale} />
          <div style={{ marginBottom: 16 }}>
            <button
              type="button"
              onClick={() => void sample()}
              style={{
                padding: '10px 16px',
                minHeight: 44,
                borderRadius: 8,
                border: `1px solid ${tokens.teal700}`,
                background: tokens.surface,
                color: tokens.teal700,
                fontWeight: 700,
                fontSize: 13,
                cursor: 'pointer',
                fontFamily: fontStack,
              }}
            >
              {tr('adminRefresh')}
            </button>
          </div>
        </>
      )}

      <Panel title={tr('adminIncidentsTitle')} tone="empty">
        <EmptyState title={tr('adminNotAvailable')} body={tr('adminIncidentsEmpty')} />
      </Panel>

      <Panel title={tr('adminAlertsTitle')} tone="empty">
        <EmptyState title={tr('adminNotAvailable')} body={tr('adminAlertsEmpty')} />
      </Panel>

      <Panel title={tr('adminSheltersTitle')} tone="empty">
        <EmptyState title={tr('adminNotAvailable')} body={tr('adminSheltersEmpty')} />
      </Panel>

      <Panel title={tr('adminWritesTitle')} subtitle={tr('adminWritesExplain')} tone="warning">
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {DISABLED_ACTIONS.map((a) => (
            <li
              key={a.id}
              style={{
                padding: '10px 0',
                borderBottom: `1px solid ${tokens.border}`,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <button
                  type="button"
                  disabled
                  aria-describedby={`${a.id}-reason`}
                  style={{
                    padding: '8px 14px',
                    minHeight: 44,
                    borderRadius: 8,
                    border: `1px solid ${tokens.border}`,
                    background: tokens.surfaceAlt,
                    color: tokens.muted,
                    fontWeight: 700,
                    fontSize: 13,
                    cursor: 'not-allowed',
                    fontFamily: fontStack,
                  }}
                >
                  {locale === 'es' ? a.labelEs : a.labelEn}
                </button>
                <Chip text={tr('adminDisabled')} fg={tokens.muted} bg={tokens.surfaceAlt} />
              </div>
              <p
                id={`${a.id}-reason`}
                style={{ margin: '6px 0 0', fontSize: 12, lineHeight: 1.6, color: tokens.muted }}
              >
                {locale === 'es' ? a.reasonEs : a.reasonEn}
              </p>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title={tr('adminRolesTitle')}>
        <p style={{ margin: 0, fontSize: 13, lineHeight: 1.6, color: tokens.muted }}>
          {tr('adminRolesBody')}
        </p>
      </Panel>
    </>
  )
}
