/**
 * Report screen — submit a road-condition report, and see what others have reported.
 *
 * WHAT THE BRIEF ASKED FOR, AND HOW EACH PART IS HONOURED
 *   camera capture        `capture="environment"` on the file input, which asks a phone for the
 *                         rear camera. Where the attribute is ignored (desktop browsers), the
 *                         same input opens a normal file picker — so the fallback is not a
 *                         separate code path that can rot, it is the same control.
 *   consent-based GPS      `navigator.geolocation` is called ONLY inside the button handler.
 *                         There is no effect, no watcher, no `watchPosition`: reading a
 *                         position without a user action is precisely what the brief forbids.
 *   pin correction         the chosen position is drawn on a small map and can be moved by
 *                         clicking, which is how a user fixes a bad fix or a denied permission.
 *   clear outcome          success and failure are distinct, translated, and never a silent
 *                         no-op. A failed submit says nothing was recorded.
 *   honest labels          an unverified report renders as UNVERIFIED, always. Nothing here can
 *                         label a report verified, and the status shown comes from the server.
 *
 * WHAT THIS SCREEN DELIBERATELY DOES NOT DO
 *   * It never claims a road is clear, safe or passable. Those words are absent from the copy.
 *   * It does not fabricate a position when geolocation fails. The map starts at the city
 *     centre and the user must place the pin themselves, because a guess would become a report
 *     about a road the user never saw.
 *   * It does not hide reports behind a login: the list is public, per the brief.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { t, type Locale, type StringKey } from './i18n'
import { tokens, fontStack } from './tokens'
import {
  REPORT_CATEGORIES,
  STATE_LABEL_KEY,
  STATE_TONE,
  ReportApiError,
  confirmReport,
  createReport,
  fetchReports,
  type PublicReport,
  type ReportCategory,
} from './reportApi'
import type { Session } from './authApi'
import type { LatLon } from './routeApi'

/** Guayaquil city centre. Only a starting view for the pin map; never used as a report position. */
const CITY_CENTRE: LatLon = { lat: -2.19, lon: -79.9 }

const CATEGORY_LABEL: Record<ReportCategory, StringKey> = {
  flooded: 'reportCategoryFlooded',
  blocked: 'reportCategoryBlocked',
  debris: 'reportCategoryDebris',
  damaged: 'reportCategoryDamaged',
  rising: 'reportCategoryRising',
  other: 'reportCategoryOther',
}

type PinState = {
  at: LatLon | null
  accuracyM: number | null
  source: 'device' | 'manual' | 'map'
}

type SubmitState =
  | { kind: 'idle' }
  | { kind: 'submitting' }
  | { kind: 'success'; messages: string[] }
  | { kind: 'error'; text: string }

const MAX_BYTES = 5 * 1024 * 1024

/* ------------------------------------------------------------------ */
/* Small pieces                                                       */
/* ------------------------------------------------------------------ */

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
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
      <h3 style={{ margin: '0 0 10px', fontSize: 15, color: tokens.navy900 }}>{title}</h3>
      {children}
    </section>
  )
}

function StatusChip({ report, locale }: { report: PublicReport; locale: Locale }) {
  const tone = STATE_TONE[report.state] ?? 'muted'
  const bg =
    tone === 'danger'
      ? tokens.dangerBg
      : tone === 'warn'
        ? tokens.warnBg
        : tone === 'ok'
          ? tokens.okBg
          : tokens.surfaceAlt
  const fg =
    tone === 'danger'
      ? tokens.dangerFg
      : tone === 'warn'
        ? tokens.warnFg
        : tone === 'ok'
          ? tokens.okFg
          : tokens.muted
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 999,
        background: bg,
        color: fg,
        border: `1px solid ${fg}`,
        fontSize: 12,
        fontWeight: 700,
        letterSpacing: 0.3,
      }}
    >
      {/* Word, not colour alone. */}
      {t(STATE_LABEL_KEY[report.state] ?? 'reportStatusUnknown', locale)}
    </span>
  )
}

function formatTime(iso: string | null, locale: Locale): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  try {
    return new Intl.DateTimeFormat(locale === 'es' ? 'es-EC' : 'en-GB', {
      dateStyle: 'short',
      timeStyle: 'short',
      timeZone: 'America/Guayaquil',
    }).format(d)
  } catch {
    return d.toISOString()
  }
}

/* ------------------------------------------------------------------ */
/* Pin map (lazy Leaflet, same pattern as the route screen)           */
/* ------------------------------------------------------------------ */

function PinMap({
  at,
  onPick,
  locale,
}: {
  at: LatLon | null
  onPick: (p: LatLon) => void
  locale: Locale
}) {
  const holder = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<import('leaflet').Map | null>(null)
  const markerRef = useRef<import('leaflet').Marker | null>(null)
  const [failed, setFailed] = useState(false)
  // Keep the latest callback without re-initialising the map on every render.
  const pickRef = useRef(onPick)
  pickRef.current = onPick

  useEffect(() => {
    let disposed = false
    void (async () => {
      try {
        const L = await import('leaflet')
        if (!document.getElementById('leaflet-css')) {
          const link = document.createElement('link')
          link.id = 'leaflet-css'
          link.rel = 'stylesheet'
          link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'
          link.onerror = () => setFailed(true)
          document.head.appendChild(link)
        }
        if (disposed || !holder.current || mapRef.current) return

        const map = L.map(holder.current, { zoomControl: true }).setView(
          [at?.lat ?? CITY_CENTRE.lat, at?.lon ?? CITY_CENTRE.lon],
          at ? 16 : 13,
        )
        mapRef.current = map

        const tiles = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 18,
          attribution: '&copy; OpenStreetMap contributors',
        })
        tiles.on('tileerror', () => setFailed(true))
        tiles.addTo(map)

        map.on('click', (e: import('leaflet').LeafletMouseEvent) => {
          pickRef.current({ lat: e.latlng.lat, lon: e.latlng.lng })
        })

        if (at) {
          markerRef.current = L.marker([at.lat, at.lon]).addTo(map)
        }
      } catch {
        setFailed(true)
      }
    })()

    return () => {
      disposed = true
      mapRef.current?.remove()
      mapRef.current = null
      markerRef.current = null
    }
    // Intentionally depending only on mount: the marker is moved by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Move (or create) the marker when the chosen position changes.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !at) return
    void (async () => {
      const L = await import('leaflet')
      if (markerRef.current) {
        markerRef.current.setLatLng([at.lat, at.lon])
      } else {
        markerRef.current = L.marker([at.lat, at.lon]).addTo(map)
      }
      map.setView([at.lat, at.lon], Math.max(map.getZoom(), 15))
    })()
  }, [at])

  return (
    <div>
      {failed && (
        <p style={{ background: tokens.warnBg, color: tokens.warnFg, padding: '8px 12px', borderRadius: 8, fontSize: 13 }}>
          {locale === 'es'
            ? 'El mapa no está disponible. Puedes enviar el reporte igualmente; la ubicación no se verificará.'
            : 'The map is unavailable. You can still submit; the location will not be checked.'}
        </p>
      )}
      <div
        ref={holder}
        style={{
          height: 260,
          borderRadius: 10,
          overflow: 'hidden',
          border: `1px solid ${tokens.border}`,
          background: tokens.surfaceAlt,
        }}
      />
      <p style={{ margin: '8px 0 0', fontSize: 12, color: tokens.muted }}>
        {t('reportPinInstruction', locale)}
      </p>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Report card                                                        */
/* ------------------------------------------------------------------ */

function ReportCard({
  report,
  locale,
  canConfirm,
  onConfirmed,
}: {
  report: PublicReport
  locale: Locale
  canConfirm: boolean
  onConfirmed: () => void
}) {
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const act = async (kind: 'confirm' | 'challenge') => {
    setBusy(true)
    setNotice(null)
    try {
      const out = await confirmReport(report.id, kind)
      setNotice(
        out.outcome === 'already_voted'
          ? t('reportAlreadyConfirmed', locale)
          : t('reportConfirmRecorded', locale),
      )
      onConfirmed()
    } catch {
      setNotice(t('reportConfirmFailed', locale))
    } finally {
      setBusy(false)
    }
  }

  return (
    <article
      style={{
        border: `1px solid ${tokens.border}`,
        borderRadius: 10,
        padding: 12,
        marginBottom: 12,
        background: tokens.surface,
      }}
    >
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {report.has_image && report.image_url ? (
          <img
            src={report.image_url}
            alt={t('reportPhotoAlt', locale)}
            width={128}
            height={96}
            loading="lazy"
            style={{ objectFit: 'cover', borderRadius: 8, border: `1px solid ${tokens.border}` }}
          />
        ) : (
          <div
            style={{
              width: 128,
              height: 96,
              display: 'grid',
              placeItems: 'center',
              borderRadius: 8,
              background: tokens.surfaceAlt,
              color: tokens.muted,
              fontSize: 12,
            }}
          >
            {t('reportNoPhoto', locale)}
          </div>
        )}

        <div style={{ flex: '1 1 220px', minWidth: 200 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <StatusChip report={report} locale={locale} />
            <strong style={{ fontSize: 14, color: tokens.navy900 }}>
              {t(CATEGORY_LABEL[report.category] ?? 'reportCategoryOther', locale)}
            </strong>
            {report.seeded && (
              <span style={{ fontSize: 11, color: tokens.muted }}>
                {t('reportSeededBadge', locale)}
              </span>
            )}
          </div>

          {report.description && (
            <p style={{ margin: '6px 0', fontSize: 13, color: tokens.navy700 }}>
              {report.description}
            </p>
          )}

          <dl style={{ margin: '6px 0 0', fontSize: 12, color: tokens.muted, display: 'grid', gap: 2 }}>
            <div>
              <dt style={{ display: 'inline', fontWeight: 600 }}>{t('reportReportedAt', locale)}: </dt>
              <dd style={{ display: 'inline', margin: 0 }}>{formatTime(report.submitted_at, locale)}</dd>
            </div>
            {report.verified_at && (
              <div>
                <dt style={{ display: 'inline', fontWeight: 600 }}>{t('reportVerifiedAt', locale)}: </dt>
                <dd style={{ display: 'inline', margin: 0 }}>{formatTime(report.verified_at, locale)}</dd>
              </div>
            )}
            <div>
              <dt style={{ display: 'inline', fontWeight: 600 }}>{t('reportExpiresAt', locale)}: </dt>
              <dd style={{ display: 'inline', margin: 0 }}>{formatTime(report.expires_at, locale)}</dd>
            </div>
            <div>
              {t('reportConfirmations', locale)}: {report.confirm_count} ·{' '}
              {t('reportChallenges', locale)}: {report.challenge_count}
            </div>
            <div>
              {report.road_segment_id === null
                ? t('reportNotMatched', locale)
                : `${t('reportMatchedRoad', locale)}: ${report.road_segment_id}`}
            </div>
          </dl>

          {/* A stale report gets its own explicit sentence. A muted chip alone is too easy to
              read as "fine". */}
          {report.is_stale && (
            <p
              style={{
                margin: '8px 0 0',
                padding: '6px 10px',
                background: tokens.warnBg,
                color: tokens.warnFg,
                borderRadius: 6,
                fontSize: 12,
              }}
            >
              {t('reportStaleNote', locale)}
            </p>
          )}

          {canConfirm && (
            <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
              <button
                type="button"
                disabled={busy}
                onClick={() => void act('confirm')}
                style={buttonStyle(tokens.teal700)}
              >
                {t('reportConfirmStillThere', locale)}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void act('challenge')}
                style={buttonStyle(tokens.navy700)}
              >
                {t('reportConfirmImproved', locale)}
              </button>
            </div>
          )}
          {notice && (
            <p role="status" style={{ margin: '8px 0 0', fontSize: 12, color: tokens.navy700 }}>
              {notice}
            </p>
          )}
        </div>
      </div>
    </article>
  )
}

const buttonStyle = (bg: string): React.CSSProperties => ({
  background: bg,
  color: '#fff',
  border: 'none',
  borderRadius: 8,
  padding: '9px 14px',
  fontSize: 13,
  fontWeight: 600,
  cursor: 'pointer',
  minHeight: 40,
})

/* ------------------------------------------------------------------ */
/* Screen                                                             */
/* ------------------------------------------------------------------ */

export default function ReportScreen({
  locale,
  session,
}: {
  locale: Locale
  session: Session | null
}) {
  const [pin, setPin] = useState<PinState>({ at: null, accuracyM: null, source: 'map' })
  const [category, setCategory] = useState<ReportCategory>('flooded')
  const [description, setDescription] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [geoBusy, setGeoBusy] = useState(false)
  const [geoNotice, setGeoNotice] = useState<string | null>(null)
  const [submit, setSubmit] = useState<SubmitState>({ kind: 'idle' })
  const [reports, setReports] = useState<PublicReport[]>([])
  const [listError, setListError] = useState<string | null>(null)
  const [listLoading, setListLoading] = useState(true)
  const [refreshKey, setRefreshKey] = useState(0)

  const loadReports = useCallback(async () => {
    setListLoading(true)
    try {
      const data = await fetchReports({ limit: 50, sinceHours: 24 * 7 })
      setReports(data.reports)
      setListError(null)
    } catch {
      setListError(t('reportMapFailed', locale))
      // Deliberately NOT clearing `reports`: showing the last known list beside an error is
      // more useful than an empty screen that could be misread as "nothing reported".
    } finally {
      setListLoading(false)
    }
  }, [locale])

  useEffect(() => {
    void loadReports()
  }, [loadReports, refreshKey])

  const useMyLocation = () => {
    setGeoNotice(null)
    if (!('geolocation' in navigator)) {
      setGeoNotice(t('reportLocationUnavailable', locale))
      return
    }
    setGeoBusy(true)
    // The ONLY geolocation call in this component, inside a click handler. No watch, no
    // background read, no permission prompt on mount.
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setPin({
          at: { lat: pos.coords.latitude, lon: pos.coords.longitude },
          accuracyM: Number.isFinite(pos.coords.accuracy) ? pos.coords.accuracy : null,
          source: 'device',
        })
        setGeoBusy(false)
      },
      (err) => {
        setGeoNotice(
          err.code === err.PERMISSION_DENIED
            ? t('reportLocationDenied', locale)
            : t('reportLocationUnavailable', locale),
        )
        setGeoBusy(false)
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 },
    )
  }

  const onPickFile = (f: File | null) => {
    setFileError(null)
    if (!f) {
      setFile(null)
      return
    }
    if (!f.type.startsWith('image/')) {
      setFileError(t('reportPhotoRejected', locale))
      setFile(null)
      return
    }
    if (f.size > MAX_BYTES) {
      setFileError(t('reportPhotoTooLarge', locale))
      setFile(null)
      return
    }
    setFile(f)
  }

  const canSubmit = useMemo(
    () => Boolean(session) && pin.at !== null && file !== null,
    [session, pin.at, file],
  )

  const doSubmit = async () => {
    if (!pin.at || !file) {
      setSubmit({ kind: 'error', text: t('reportPhotoRequired', locale) })
      return
    }
    setSubmit({ kind: 'submitting' })
    try {
      const out = await createReport({
        category,
        at: pin.at,
        accuracyM: pin.accuracyM,
        gpsSource: pin.source,
        description,
        image: file,
      })
      setSubmit({
        kind: 'success',
        messages: [t('reportSubmitted', locale), ...out.messages],
      })
      setFile(null)
      setDescription('')
      setRefreshKey((k) => k + 1)
    } catch (err) {
      if (err instanceof ReportApiError) {
        const map: Record<string, StringKey> = {
          rate_limited: 'reportRateLimited',
          image_too_large: 'reportPhotoTooLarge',
          image_format_unsupported: 'reportPhotoRejected',
          image_not_an_image: 'reportPhotoRejected',
          image_corrupt: 'reportPhotoRejected',
          image_empty: 'reportPhotoRequired',
          outside_service_area: 'reportSubmitFailed',
        }
        const key = map[err.code]
        setSubmit({ kind: 'error', text: key ? t(key, locale) : t('reportSubmitFailed', locale) })
      } else {
        setSubmit({ kind: 'error', text: t('reportSubmitFailed', locale) })
      }
    }
  }

  const poorAccuracy = pin.accuracyM !== null && pin.accuracyM > 100

  return (
    <div>
      <header style={{ marginBottom: 12 }}>
        <h2 style={{ margin: '0 0 4px', fontSize: 18, color: tokens.navy900 }}>
          {t('reportTitle', locale)}
        </h2>
        <p style={{ margin: 0, fontSize: 13, color: tokens.muted }}>{t('reportIntro', locale)}</p>
      </header>

      {!session && (
        <p
          style={{
            background: tokens.warnBg,
            color: tokens.warnFg,
            padding: '10px 12px',
            borderRadius: 8,
            fontSize: 13,
          }}
        >
          {t('reportSignInRequired', locale)}
        </p>
      )}

      <Section title={t('reportPhotoTitle', locale)}>
        {/*
          One input, two affordances. `capture="environment"` makes a phone offer the rear
          camera; every other browser ignores it and shows a normal picker. That is the
          "supported where available, normal fallback otherwise" requirement, achieved without
          a feature-detect that could disagree with reality.
        */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <label style={{ ...buttonStyle(tokens.teal700), display: 'inline-block', minHeight: 40 }}>
            {t('reportTakePhoto', locale)}
            <input
              type="file"
              accept="image/*"
              capture="environment"
              onChange={(e) => onPickFile(e.target.files?.[0] ?? null)}
              style={{ display: 'none' }}
            />
          </label>
          <label style={{ ...buttonStyle(tokens.navy700), display: 'inline-block', minHeight: 40 }}>
            {t('reportChoosePhoto', locale)}
            <input
              type="file"
              accept="image/*"
              onChange={(e) => onPickFile(e.target.files?.[0] ?? null)}
              style={{ display: 'none' }}
            />
          </label>
        </div>
        <p style={{ margin: '8px 0 0', fontSize: 12, color: tokens.muted }}>
          {t('reportPhotoHint', locale)}
        </p>
        {file && (
          <p style={{ margin: '6px 0 0', fontSize: 12, color: tokens.okFg }}>
            {file.name} · {(file.size / 1024).toFixed(0)} KB
          </p>
        )}
        {fileError && (
          <p role="alert" style={{ margin: '6px 0 0', fontSize: 12, color: tokens.dangerFg }}>
            {fileError}
          </p>
        )}
      </Section>

      <Section title={t('reportLocationTitle', locale)}>
        <button
          type="button"
          onClick={useMyLocation}
          disabled={geoBusy}
          style={buttonStyle(tokens.teal700)}
        >
          {geoBusy ? t('reportLocationGetting', locale) : t('reportUseMyLocation', locale)}
        </button>
        <p style={{ margin: '8px 0', fontSize: 12, color: tokens.muted }}>
          {t('reportLocationHint', locale)}
        </p>
        {geoNotice && (
          <p role="status" style={{ margin: '0 0 8px', fontSize: 12, color: tokens.warnFg }}>
            {geoNotice}
          </p>
        )}
        {pin.accuracyM !== null && (
          <p style={{ margin: '0 0 8px', fontSize: 12, color: poorAccuracy ? tokens.warnFg : tokens.muted }}>
            {t('reportAccuracy', locale)}: ±{Math.round(pin.accuracyM)} m
            {poorAccuracy ? ` — ${t('reportAccuracyPoor', locale)}` : ''}
          </p>
        )}
        <PinMap
          at={pin.at}
          locale={locale}
          onPick={(p) => {
            // A manual pick is recorded as `map` provenance, not as a GPS fix. The distinction
            // survives into the admin view, where an operator needs to know whether the point
            // came from a receiver or from a fingertip.
            setPin({ at: p, accuracyM: null, source: 'map' })
            setGeoNotice(null)
          }}
        />
        {pin.at && (
          <p style={{ margin: '6px 0 0', fontSize: 12, color: tokens.muted }}>
            {pin.at.lat.toFixed(5)}, {pin.at.lon.toFixed(5)}
            {pin.source === 'map' ? ` · ${t('adminReportSource', locale)}: map` : ''}
          </p>
        )}
      </Section>

      <Section title={t('reportCategoryTitle', locale)}>
        <div style={{ display: 'grid', gap: 6 }}>
          {REPORT_CATEGORIES.map((c) => (
            <label
              key={c}
              style={{
                display: 'flex',
                gap: 8,
                alignItems: 'center',
                fontSize: 13,
                color: tokens.navy700,
                minHeight: 32,
              }}
            >
              <input
                type="radio"
                name="report-category"
                value={c}
                checked={category === c}
                onChange={() => setCategory(c)}
              />
              {t(CATEGORY_LABEL[c], locale)}
            </label>
          ))}
        </div>

        <label htmlFor="report-description" style={{ display: 'block', marginTop: 12, fontSize: 13, fontWeight: 600, color: tokens.navy900 }}>
          {t('reportDescription', locale)}
        </label>
        <textarea
          id="report-description"
          value={description}
          maxLength={280}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          style={{
            width: '100%',
            marginTop: 4,
            padding: 8,
            fontSize: 13,
            borderRadius: 8,
            border: `1px solid ${tokens.border}`,
            fontFamily: fontStack,
            resize: 'vertical',
          }}
        />
        <p style={{ margin: '4px 0 0', fontSize: 12, color: tokens.muted }}>
          {t('reportDescriptionHint', locale)} · {description.length}/280
        </p>
      </Section>

      <Section title={t('reportPrivacyTitle', locale)}>
        <p style={{ margin: 0, fontSize: 12, color: tokens.muted }}>
          {t('reportPrivacyBody', locale)}
        </p>
      </Section>

      <button
        type="button"
        onClick={() => void doSubmit()}
        disabled={!canSubmit || submit.kind === 'submitting'}
        style={{
          ...buttonStyle(canSubmit ? tokens.teal700 : tokens.muted),
          width: '100%',
          padding: '12px 16px',
          fontSize: 15,
          opacity: canSubmit ? 1 : 0.6,
        }}
      >
        {submit.kind === 'submitting' ? t('reportSubmitting', locale) : t('reportSubmit', locale)}
      </button>

      {submit.kind === 'success' && (
        <div
          role="status"
          style={{
            marginTop: 12,
            padding: '10px 12px',
            borderRadius: 8,
            background: tokens.okBg,
            color: tokens.okFg,
            fontSize: 13,
          }}
        >
          {submit.messages.map((m) => (
            <p key={m} style={{ margin: '0 0 4px' }}>
              {m}
            </p>
          ))}
        </div>
      )}
      {submit.kind === 'error' && (
        <p
          role="alert"
          style={{
            marginTop: 12,
            padding: '10px 12px',
            borderRadius: 8,
            background: tokens.dangerBg,
            color: tokens.dangerFg,
            fontSize: 13,
          }}
        >
          {submit.text}
        </p>
      )}

      <h3 style={{ margin: '24px 0 8px', fontSize: 16, color: tokens.navy900 }}>
        {t('reportMapTitle', locale)}
      </h3>
      <p style={{ margin: '0 0 10px', fontSize: 12, color: tokens.muted }}>
        {t('reportStatusLegend', locale)}
      </p>

      {listError && (
        <p
          role="alert"
          style={{
            background: tokens.warnBg,
            color: tokens.warnFg,
            padding: '8px 12px',
            borderRadius: 8,
            fontSize: 13,
          }}
        >
          {listError}
        </p>
      )}
      {listLoading && reports.length === 0 && (
        <p style={{ fontSize: 13, color: tokens.muted }}>…</p>
      )}
      {!listLoading && reports.length === 0 && !listError && (
        <p style={{ fontSize: 13, color: tokens.muted }}>{t('reportMapEmpty', locale)}</p>
      )}

      {reports.map((r) => (
        <ReportCard
          key={r.id}
          report={r}
          locale={locale}
          canConfirm={Boolean(session)}
          onConfirmed={() => setRefreshKey((k) => k + 1)}
        />
      ))}
    </div>
  )
}
