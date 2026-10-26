/**
 * INAMHI official bulletin panel + forecast comparison.
 *
 * THE TWO THINGS THIS COMPONENT MUST NOT DO
 *
 *  1. **Never present a comparison as verification.** When the model's daily total falls inside a
 *     published regional band, that is shown as "inside band", not as "matches", "confirms", or
 *     "is verified against". The backend already refuses to compute a percentage difference; this
 *     component must not invent one visually either.
 *  2. **Never fill a gap.** If the bulletin cannot be read, the panel shows the official link and
 *     says so. If it is qualitative (no numeric table), it is shown as an official statement —
 *     not converted into numbers, and not hidden.
 *
 * The disclaimers returned by the API are rendered verbatim. They are not summarised away,
 * because a summarised caveat is a caveat that stops constraining interpretation.
 */

import { useEffect, useState } from 'react'
import { t, type Locale, type StringKey } from './i18n'
import { tokens, fontStack } from './tokens'

export interface RegionBands {
  region: string
  bands: { level: string; low_mm: number | null; high_mm: number | null }[]
}

export interface Bulletin {
  ok: boolean
  source_url: string
  source_name: string
  bulletin_number: string | null
  status: string | null
  issued_at: string | null
  issued_text: string | null
  valid_from: string | null
  valid_until: string | null
  validity_text: string | null
  threat_level: string | null
  phenomenon: string | null
  affected_regions: string[]
  regions: RegionBands[]
  recommendations: string[]
  is_quantitative: boolean
  fetched_at: string | null
  cached: boolean
  cache_age_s: number | null
  error: string | null
  warnings: string[]
}

export interface Comparison {
  comparable: boolean
  reason: string
  explanation_en: string
  explanation_es: string
  region: string
  days: {
    date: string
    forecast_mm: number | null
    matching_levels: string[]
    published_bands: { level: string; low_mm: number | null; high_mm: number | null }[]
  }[]
  disclaimers_en: string[]
  disclaimers_es: string[]
  bulletin_source_url: string | null
  bulletin_issued_at: string | null
  bulletin_valid_from: string | null
  bulletin_valid_until: string | null
  notes: string[]
}

type Loadable<T> =
  | { state: 'loading' }
  | { state: 'ready'; data: T }
  | { state: 'error'; message: string }

/** Guayaquil local rendering, pinned — never the viewer's device zone. */
function guayaquil(iso: string | null, locale: Locale): string | null {
  if (!iso) return null
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return null
    return d.toLocaleString(locale === 'es' ? 'es-EC' : 'en-GB', {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: 'America/Guayaquil',
    })
  } catch {
    // Formatting must never throw during render: that is the exact failure that blanked the
    // Status tab once. Degrade to the raw value instead.
    return null
  }
}

const card: React.CSSProperties = {
  background: tokens.surface,
  border: `1px solid ${tokens.border}`,
  borderRadius: 12,
  padding: 16,
  marginBottom: 16,
}
const h2: React.CSSProperties = { margin: '0 0 10px', fontSize: 16, color: tokens.navy900 }
const muted = (size = 12): React.CSSProperties => ({
  margin: 0,
  fontSize: size,
  color: tokens.muted,
  lineHeight: 1.6,
})
const dtStyle: React.CSSProperties = {
  fontSize: 11,
  color: tokens.muted,
  margin: 0,
  textTransform: 'uppercase',
  letterSpacing: 0.4,
}
const ddStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 13,
  fontWeight: 600,
  color: tokens.navy900,
}

export function BulletinPanel({ locale }: { locale: Locale }) {
  const tr = (k: StringKey) => t(k, locale)
  const [load, setLoad] = useState<Loadable<Bulletin>>({ state: 'loading' })

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const res = await fetch('/api/public/bulletin', { credentials: 'same-origin' })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = (await res.json()) as Bulletin
        if (!cancelled) setLoad({ state: 'ready', data })
      } catch (err) {
        if (!cancelled) setLoad({ state: 'error', message: (err as Error).message })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  if (load.state === 'loading') {
    return (
      <section style={card}>
        <h2 style={h2}>{tr('bulletinTitle')}</h2>
        <p role="status" style={muted()}>
          {tr('bulletinLoading')}
        </p>
      </section>
    )
  }

  // A failed fetch and a failed parse look the same to the reader: no values, official link.
  const b = load.state === 'ready' ? load.data : null
  const unavailable = load.state === 'error' || (b !== null && !b.ok)

  if (unavailable) {
    return (
      <section style={{ ...card, borderColor: tokens.warnFg, background: tokens.warnBg }}>
        <h2 style={{ ...h2, color: tokens.warnFg }}>{tr('bulletinTitle')}</h2>
        <p role="alert" style={{ ...muted(13), color: tokens.warnFg }}>
          {tr('bulletinUnavailable')}
        </p>
        {b?.error && <p style={{ ...muted(11), color: tokens.warnFg, marginTop: 6 }}>{b.error}</p>}
        <a
          href={b?.source_url ?? 'https://www.inamhi.gob.ec/pronostico/advertencia.pdf'}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'inline-block',
            marginTop: 10,
            padding: '9px 14px',
            minHeight: 44,
            borderRadius: 8,
            border: `1px solid ${tokens.warnFg}`,
            color: tokens.warnFg,
            fontWeight: 700,
            fontSize: 13,
            textDecoration: 'none',
            fontFamily: fontStack,
          }}
        >
          {tr('bulletinOpenOfficial')}
        </a>
      </section>
    )
  }

  if (!b) return null

  const issued = guayaquil(b.issued_at, locale)
  const from = guayaquil(b.valid_from, locale)
  const until = guayaquil(b.valid_until, locale)

  return (
    <section style={card}>
      <h2 style={h2}>{tr('bulletinTitle')}</h2>
      <p style={{ ...muted(), marginBottom: 10 }}>
        <strong>{b.source_name}</strong>
        {b.cached && b.cache_age_s !== null && (
          <span style={{ marginLeft: 6, fontStyle: 'italic' }}>
            ({tr('bulletinCached')}, {Math.round(b.cache_age_s)}s)
          </span>
        )}
      </p>

      <dl
        style={{
          margin: '0 0 12px',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
          gap: 8,
        }}
      >
        {b.bulletin_number && (
          <div>
            <dt style={dtStyle}>{tr('bulletinNumber')}</dt>
            <dd style={ddStyle}>{b.bulletin_number}</dd>
          </div>
        )}
        {b.status && (
          <div>
            <dt style={dtStyle}>{tr('bulletinStatus')}</dt>
            <dd style={{ ...ddStyle, color: tokens.warnFg }}>{b.status}</dd>
          </div>
        )}
        {b.threat_level && (
          <div>
            <dt style={dtStyle}>{tr('bulletinThreat')}</dt>
            <dd style={{ ...ddStyle, color: tokens.warnFg }}>{b.threat_level}</dd>
          </div>
        )}
        {issued && (
          <div>
            <dt style={dtStyle}>{tr('bulletinIssued')}</dt>
            <dd style={ddStyle}>{issued}</dd>
          </div>
        )}
        {(from || b.validity_text) && (
          <div style={{ gridColumn: '1 / -1' }}>
            <dt style={dtStyle}>{tr('bulletinValid')}</dt>
            <dd style={ddStyle}>
              {from && until ? `${from} → ${until}` : b.validity_text}
            </dd>
          </div>
        )}
        {b.phenomenon && (
          <div style={{ gridColumn: '1 / -1' }}>
            <dt style={dtStyle}>{tr('bulletinPhenomenon')}</dt>
            <dd style={ddStyle}>{b.phenomenon}</dd>
          </div>
        )}
      </dl>

      {b.regions.length > 0 ? (
        <div style={{ marginBottom: 12 }}>
          <p style={{ ...muted(12), fontWeight: 700, color: tokens.navy700, marginBottom: 4 }}>
            {tr('bulletinBands')}
          </p>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, minWidth: 320 }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', padding: '4px 6px', color: tokens.muted }}>—</th>
                  {b.regions[0].bands.map((x) => (
                    <th
                      key={x.level}
                      style={{ textAlign: 'left', padding: '4px 6px', color: tokens.muted }}
                    >
                      {x.level}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {b.regions.map((r) => (
                  <tr key={r.region} style={{ borderTop: `1px solid ${tokens.border}` }}>
                    <td style={{ padding: '4px 6px', fontWeight: 700, color: tokens.navy900 }}>
                      {r.region}
                    </td>
                    {r.bands.map((x, i) => (
                      <td key={`${x.level}-${i}`} style={{ padding: '4px 6px', color: tokens.navy900 }}>
                        {x.low_mm === null && x.high_mm === null
                          ? '—'
                          : `${x.low_mm ?? '?'} – ${x.high_mm ?? '?'} mm`}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p style={{ ...muted(11), marginTop: 4 }}>{tr('bulletinBandsNote')}</p>
        </div>
      ) : (
        <p style={{ ...muted(12), marginBottom: 12, color: tokens.warnFg, fontWeight: 600 }}>
          {tr('bulletinQualitative')}
        </p>
      )}

      {b.affected_regions.length > 0 && (
        <p style={{ ...muted(12), marginBottom: 8 }}>
          <strong>{tr('bulletinRegions')}:</strong> {b.affected_regions.join(', ')}
        </p>
      )}

      {b.recommendations.length > 0 && (
        <details style={{ marginBottom: 8 }}>
          <summary style={{ cursor: 'pointer', fontSize: 12, color: tokens.navy700 }}>
            {tr('bulletinRecommendations')}
          </summary>
          <ul style={{ margin: '6px 0 0 16px', padding: 0, ...muted(11) }}>
            {b.recommendations.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </details>
      )}

      <a
        href={b.source_url}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          display: 'inline-block',
          padding: '9px 14px',
          minHeight: 44,
          borderRadius: 8,
          border: `1px solid ${tokens.teal700}`,
          color: tokens.teal700,
          fontWeight: 700,
          fontSize: 13,
          textDecoration: 'none',
          fontFamily: fontStack,
        }}
      >
        {tr('bulletinOpenOfficial')}
      </a>

      {b.warnings.length > 0 && (
        <ul style={{ margin: '10px 0 0 16px', padding: 0, ...muted(11) }}>
          {b.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function ComparisonPanel({ locale }: { locale: Locale }) {
  const tr = (k: StringKey) => t(k, locale)
  const [load, setLoad] = useState<Loadable<Comparison>>({ state: 'loading' })

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const res = await fetch('/api/public/comparison?region=Litoral', {
          credentials: 'same-origin',
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = (await res.json()) as Comparison
        if (!cancelled) setLoad({ state: 'ready', data })
      } catch (err) {
        if (!cancelled) setLoad({ state: 'error', message: (err as Error).message })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  if (load.state === 'loading') {
    return (
      <section style={card}>
        <h2 style={h2}>{tr('comparisonTitle')}</h2>
        <p role="status" style={muted()}>
          {tr('bulletinLoading')}
        </p>
      </section>
    )
  }

  if (load.state === 'error') {
    return (
      <section style={{ ...card, borderColor: tokens.warnFg, background: tokens.warnBg }}>
        <h2 style={{ ...h2, color: tokens.warnFg }}>{tr('comparisonTitle')}</h2>
        <p role="alert" style={{ ...muted(13), color: tokens.warnFg }}>
          {tr('comparisonRefused')} {load.message}
        </p>
      </section>
    )
  }

  const c = load.data
  const explanation = locale === 'es' ? c.explanation_es : c.explanation_en
  const caveats = locale === 'es' ? c.disclaimers_es : c.disclaimers_en

  return (
    <section style={card}>
      <h2 style={h2}>{tr('comparisonTitle')}</h2>

      {!c.comparable && (
        <p role="status" style={{ ...muted(13), color: tokens.warnFg, fontWeight: 600 }}>
          {tr('comparisonRefused')} {explanation}
        </p>
      )}

      {c.comparable && (
        <>
          <p style={{ ...muted(13), marginBottom: 10 }}>{explanation}</p>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, minWidth: 380 }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', padding: '5px 6px', color: tokens.muted }}>—</th>
                  <th style={{ textAlign: 'left', padding: '5px 6px', color: tokens.muted }}>
                    {tr('comparisonModelRow')}
                  </th>
                  <th style={{ textAlign: 'left', padding: '5px 6px', color: tokens.muted }}>
                    {tr('comparisonBulletinRow')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {c.days.map((d) => (
                  <tr key={d.date} style={{ borderTop: `1px solid ${tokens.border}` }}>
                    <td style={{ padding: '5px 6px', color: tokens.navy700, fontWeight: 600 }}>
                      {d.date}
                    </td>
                    <td style={{ padding: '5px 6px', color: tokens.navy900 }}>
                      {d.forecast_mm === null
                        ? tr('dayUnavailable')
                        : `${d.forecast_mm.toFixed(1)} mm`}
                    </td>
                    <td style={{ padding: '5px 6px', color: tokens.navy900 }}>
                      {d.matching_levels.length > 0 ? (
                        <span style={{ color: tokens.okFg, fontWeight: 700 }}>
                          {tr('comparisonInside')}: {d.matching_levels.join(', ')}
                        </span>
                      ) : (
                        <span style={{ color: tokens.muted }}>{tr('comparisonOutside')}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p style={{ ...muted(11), marginTop: 8 }}>
            {c.region}
            {c.bulletin_issued_at ? ` · INAMHI ${guayaquil(c.bulletin_issued_at, locale) ?? ''}` : ''}
          </p>
        </>
      )}

      {caveats.length > 0 && (
        <details style={{ marginTop: 10 }} open>
          <summary
            style={{ cursor: 'pointer', fontSize: 12, fontWeight: 700, color: tokens.warnFg }}
          >
            {tr('comparisonCaveats')}
          </summary>
          <ul style={{ margin: '6px 0 0 16px', padding: 0, ...muted(11), color: tokens.warnFg }}>
            {caveats.map((x, i) => (
              <li key={i} style={{ marginBottom: 4 }}>
                {x}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}

export function ForecastSafetyNotes({ locale }: { locale: Locale }) {
  const tr = (k: StringKey) => t(k, locale)
  return (
    <div
      style={{
        background: tokens.warnBg,
        border: `1px solid ${tokens.warnFg}`,
        borderLeft: `4px solid ${tokens.warnFg}`,
        borderRadius: 8,
        padding: '10px 12px',
        marginBottom: 16,
      }}
    >
      <p style={{ ...muted(12), color: tokens.warnFg, fontWeight: 600, marginBottom: 4 }}>
        {tr('forecastNotFloodWarning')}
      </p>
      <p style={{ ...muted(12), color: tokens.warnFg, fontWeight: 600 }}>
        {tr('forecastNoRiskScore')}
      </p>
    </div>
  )
}
