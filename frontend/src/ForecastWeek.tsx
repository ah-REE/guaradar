/**
 * Seven-day forecast view: a daily rainfall chart, daily detail cards, and a next-24h hourly chart.
 *
 * NO CHART LIBRARY
 *   These are inline SVG bars. A charting dependency would add weight to a bundle that is already
 *   the largest part of the app, for two simple bar charts. SVG also keeps full control of
 *   accessibility (each bar has a title, and the figure has a text alternative).
 *
 * HOW MISSING VALUES ARE HANDLED
 *   `null` means the provider omitted the value. It is rendered as an explicit "unavailable",
 *   never as a zero-height bar, because a zero bar reads as "no rain" — a confident and possibly
 *   false statement. Days with no value are drawn as a faint dashed slot with a target label.
 *
 * WHAT THIS DELIBERATELY DOES NOT DO
 *   * No flood-risk score. Rainfall alone does not determine flooding, and D18/D27 keep severity
 *     and coverage as separate outputs of a model that is still unvalidated (O-7).
 *   * No "heavy rain" classification: no threshold is approved.
 *   * No smoothing or interpolation across a missing day.
 */

import { t, type Locale, type StringKey } from './i18n'
import { tokens } from './tokens'
import type { DailyRain, HourlyRain } from './api'

/** WMO weather interpretation codes, grouped for display. Kept intentionally coarse. */
const WMO: Record<number, { en: string; es: string }> = {
  0: { en: 'Clear sky', es: 'Cielo despejado' },
  1: { en: 'Mainly clear', es: 'Mayormente despejado' },
  2: { en: 'Partly cloudy', es: 'Parcialmente nublado' },
  3: { en: 'Overcast', es: 'Nublado' },
  45: { en: 'Fog', es: 'Niebla' },
  48: { en: 'Rime fog', es: 'Niebla con escarcha' },
  51: { en: 'Light drizzle', es: 'Llovizna ligera' },
  53: { en: 'Drizzle', es: 'Llovizna' },
  55: { en: 'Dense drizzle', es: 'Llovizna intensa' },
  61: { en: 'Slight rain', es: 'Lluvia ligera' },
  63: { en: 'Moderate rain', es: 'Lluvia moderada' },
  65: { en: 'Heavy rain', es: 'Lluvia fuerte' },
  80: { en: 'Slight showers', es: 'Chubascos ligeros' },
  81: { en: 'Moderate showers', es: 'Chubascos moderados' },
  82: { en: 'Violent showers', es: 'Chubascos violentos' },
  95: { en: 'Thunderstorm', es: 'Tormenta eléctrica' },
  96: { en: 'Thunderstorm with hail', es: 'Tormenta con granizo' },
  99: { en: 'Severe thunderstorm with hail', es: 'Tormenta severa con granizo' },
}

export function weatherLabel(code: number | null | undefined, locale: Locale): string | null {
  if (code === null || code === undefined) return null
  const entry = WMO[code]
  if (entry) return locale === 'es' ? entry.es : entry.en
  // An unknown code is reported as unknown, never guessed into a description.
  return locale === 'es' ? `Código ${code}` : `Code ${code}`
}

/** Short weekday + day/month, in Guayaquil terms (dates are calendar days, not instants). */
export function dayLabel(iso: string, locale: Locale): string {
  // Parse as a plain calendar date. `new Date('2026-10-26')` is UTC midnight, which in a
  // negative-offset zone renders as the PREVIOUS day — a classic off-by-one. Constructing from
  // parts avoids it entirely.
  const [y, m, d] = iso.split('-').map(Number)
  const dt = new Date(Date.UTC(y, (m ?? 1) - 1, d ?? 1))
  return dt.toLocaleDateString(locale === 'es' ? 'es-EC' : 'en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  })
}

const fmt = (v: number | null | undefined, digits = 1): string | null =>
  v === null || v === undefined ? null : v.toFixed(digits)

/** A single horizontal-friendly bar chart in plain SVG. */
function BarChart({
  values,
  labels,
  unit,
  ariaLabel,
  locale,
  maxOverride,
}: {
  values: (number | null)[]
  labels: string[]
  unit: string
  ariaLabel: string
  locale: Locale
  maxOverride?: number
}) {
  const present = values.filter((v): v is number => v !== null && v >= 0)
  const max = maxOverride ?? (present.length ? Math.max(...present) : 0)
  const peak = max > 0 ? max : 1

  const W = 640
  const H = 190
  const padL = 44
  const padB = 34
  const padT = 16
  const plotW = W - padL - 10
  const plotH = H - padT - padB
  const slot = plotW / Math.max(values.length, 1)
  const barW = Math.max(6, Math.min(46, slot * 0.62))

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={ariaLabel}
      style={{ width: '100%', height: 'auto', display: 'block', maxWidth: '100%' }}
    >
      {/* Axes */}
      <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke={tokens.border} strokeWidth="1" />
      <line
        x1={padL}
        y1={padT + plotH}
        x2={padL + plotW}
        y2={padT + plotH}
        stroke={tokens.border}
        strokeWidth="1"
      />
      <text x={4} y={padT + 4} fontSize="10" fill={tokens.muted}>
        {`${peak.toFixed(0)} ${unit}`}
      </text>
      <text x={4} y={padT + plotH} fontSize="10" fill={tokens.muted}>
        {`0 ${unit}`}
      </text>

      {values.map((v, i) => {
        const x = padL + i * slot + (slot - barW) / 2
        const baseY = padT + plotH
        if (v === null || v < 0) {
          // Explicit "no value" slot: dashed outline at the baseline, not a zero bar.
          return (
            <g key={i}>
              <rect
                x={x}
                y={baseY - 4}
                width={barW}
                height={4}
                fill="none"
                stroke={tokens.muted}
                strokeDasharray="2 2"
                strokeWidth="1"
              />
              <title>{`${labels[i]}: ${t('dayUnavailable', locale)}`}</title>
            </g>
          )
        }
        const h = Math.max(1, (v / peak) * plotH)
        return (
          <g key={i}>
            <rect
              x={x}
              y={baseY - h}
              width={barW}
              height={h}
              fill={tokens.infoFg}
              rx="2"
            />
            <text
              x={x + barW / 2}
              y={baseY - h - 4}
              fontSize="10"
              fill={tokens.navy700}
              textAnchor="middle"
            >
              {v.toFixed(v >= 10 ? 0 : 1)}
            </text>
            <title>{`${labels[i]}: ${v.toFixed(1)} ${unit}`}</title>
          </g>
        )
      })}

      {labels.map((lab, i) => (
        <text
          key={i}
          x={padL + i * slot + slot / 2}
          y={H - 12}
          fontSize="10"
          fill={tokens.muted}
          textAnchor="middle"
        >
          {lab}
        </text>
      ))}
    </svg>
  )
}

export function SevenDaySection({
  days,
  locale,
}: {
  days: DailyRain[]
  locale: Locale
}) {
  const tr = (k: StringKey) => t(k, locale)
  if (days.length === 0) {
    return (
      <p role="status" style={{ margin: 0, fontSize: 13, color: tokens.muted }}>
        {tr('weekUnavailable')}
      </p>
    )
  }

  const labels = days.map((d) => dayLabel(d.date, locale))
  const rain = days.map((d) => d.precipitation_sum_mm)
  const anyValue = rain.some((v) => v !== null)

  return (
    <>
      <h3 style={{ margin: '0 0 8px', fontSize: 14, color: tokens.navy900 }}>
        {tr('weekChartHeading')}
      </h3>
      {anyValue ? (
        <BarChart
          values={rain}
          labels={labels}
          unit="mm"
          ariaLabel={tr('chartLabel')}
          locale={locale}
        />
      ) : (
        <p role="status" style={{ margin: 0, fontSize: 13, color: tokens.muted }}>
          {tr('chartNoData')}
        </p>
      )}

      <h3 style={{ margin: '16px 0 8px', fontSize: 14, color: tokens.navy900 }}>
        {tr('weekCardsHeading')}
      </h3>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          gap: 8,
        }}
      >
        {days.map((d) => {
          const rainTxt = fmt(d.precipitation_sum_mm)
          const probTxt = fmt(d.probability_max_pct, 0)
          const tmin = fmt(d.temperature_min_c)
          const tmax = fmt(d.temperature_max_c)
          return (
            <div
              key={d.date}
              style={{
                border: `1px solid ${tokens.border}`,
                borderRadius: 8,
                padding: '8px 10px',
                background: tokens.surface,
              }}
            >
              <p style={{ margin: '0 0 6px', fontSize: 12, fontWeight: 700, color: tokens.navy900 }}>
                {dayLabel(d.date, locale)}
              </p>
              <p style={{ margin: '0 0 3px', fontSize: 11, color: tokens.muted }}>
                {tr('dayRain')}:{' '}
                <strong style={{ color: tokens.navy700 }}>
                  {rainTxt === null ? tr('dayUnavailable') : `${rainTxt} mm`}
                </strong>
              </p>
              <p style={{ margin: '0 0 3px', fontSize: 11, color: tokens.muted }}>
                {tr('dayProbability')}:{' '}
                <strong style={{ color: tokens.navy700 }}>
                  {probTxt === null ? tr('dayUnavailable') : `${probTxt}%`}
                </strong>
              </p>
              <p style={{ margin: '0 0 3px', fontSize: 11, color: tokens.muted }}>
                {tr('dayTemp')}:{' '}
                <strong style={{ color: tokens.navy700 }}>
                  {tmin === null || tmax === null
                    ? tr('dayUnavailable')
                    : `${tmin}–${tmax} °C`}
                </strong>
              </p>
              <p style={{ margin: 0, fontSize: 11, color: tokens.muted }}>
                {tr('dayWeather')}:{' '}
                <strong style={{ color: tokens.navy700 }}>
                  {weatherLabel(d.weather_code, locale) ?? tr('dayUnavailable')}
                </strong>
              </p>
            </div>
          )
        })}
      </div>
    </>
  )
}

export function Next24hSection({
  hours,
  locale,
}: {
  hours: HourlyRain[]
  locale: Locale
}) {
  const tr = (k: StringKey) => t(k, locale)
  const slice = hours.slice(0, 24)
  if (slice.length === 0) {
    return (
      <p role="status" style={{ margin: 0, fontSize: 13, color: tokens.muted }}>
        {tr('chartNoData')}
      </p>
    )
  }
  const labels = slice.map((h) => {
    const d = new Date(h.at)
    return d.toLocaleTimeString(locale === 'es' ? 'es-EC' : 'en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'America/Guayaquil',
    })
  })
  const values = slice.map((h) => h.precipitation_mm)
  const anyValue = values.some((v) => v !== null)

  return (
    <>
      <h3 style={{ margin: '0 0 8px', fontSize: 14, color: tokens.navy900 }}>
        {tr('next24Title')}
      </h3>
      {anyValue ? (
        <BarChart
          values={values}
          labels={labels}
          unit="mm"
          ariaLabel={tr('hourlyChartLabel')}
          locale={locale}
        />
      ) : (
        <p role="status" style={{ margin: 0, fontSize: 13, color: tokens.muted }}>
          {tr('chartNoData')}
        </p>
      )}
    </>
  )
}
