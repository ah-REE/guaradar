/**
 * Admin report-review panel.
 *
 * THE AUTHORISATION MODEL, RESTATED BECAUSE IT IS THE POINT
 *   This component renders read-only when the signed-in role cannot decide. That is a courtesy,
 *   not a control: every decision call goes to `POST /api/admin/reports/{id}/decision`, which
 *   resolves the role server-side and answers 403 for anything below `operator`. If this file
 *   were edited in devtools to enable the buttons, the server would still refuse. Nothing here
 *   claims otherwise, and there is no client-side "role" state that could be forged into access.
 *
 * WHAT IT SHOWS AN OPERATOR, AND WHY EACH FIELD IS THERE
 *   photo            what the reporter actually saw
 *   raw position     `gps_lat`/`gps_lon` — admin-only, because judging a report requires knowing
 *   accuracy         where the phone was and how well it knew it
 *   snap distance    whether the pin was 3 m from a road or 40 m from one
 *   segment id       the exact edge the decision will affect
 *   timestamps       reported / verified / fresh-until, so staleness is visible rather than felt
 *   confirmations    community corroboration counts, labelled as evidence
 *   history          the append-only record of what has already been decided, and by whom
 *
 * WHAT IT REFUSES TO DO
 *   * No "verify" button that silently also publishes an alert: closing a road and alarming the
 *     city are separate decisions.
 *   * No optimistic success message. The row is replaced with the SERVER's response, and a
 *     failure says nothing was changed — because an operator who believes a closure was saved
 *     when it was not is the worst failure mode this screen has.
 */

import { useCallback, useEffect, useState } from 'react'
import { t, type Locale, type StringKey } from './i18n'
import { tokens, fontStack } from './tokens'
import {
  STATE_LABEL_KEY,
  STATE_TONE,
  ReportApiError,
  decideReport,
  fetchAdminReports,
  fetchReportHistory,
  type AdminReport,
  type AuditEntry,
  type Decision,
  type ReportState,
} from './reportApi'
import type { Session } from './authApi'

type Loadable =
  | { state: 'loading' }
  | { state: 'ready'; reports: AdminReport[] }
  | { state: 'error'; text: string }

/** Decisions an operator may record, with the label and the consequence stated. */
const DECISION_ACTIONS: {
  decision: Exclude<Decision, 'unverified'>
  labelKey: StringKey
  tone: 'danger' | 'ok' | 'warn' | 'muted'
}[] = [
  { decision: 'blocked_verified', labelKey: 'adminDecisionVerifyBlocked', tone: 'danger' },
  { decision: 'passable_verified', labelKey: 'adminDecisionVerifyPassable', tone: 'ok' },
  { decision: 'potential_hazard', labelKey: 'adminDecisionPotential', tone: 'warn' },
  { decision: 'inconclusive', labelKey: 'adminDecisionInconclusive', tone: 'muted' },
  { decision: 'rejected', labelKey: 'adminDecisionReject', tone: 'muted' },
]

function toneColors(tone: 'danger' | 'ok' | 'warn' | 'muted' | 'info') {
  switch (tone) {
    case 'danger':
      return { bg: tokens.dangerBg, fg: tokens.dangerFg }
    case 'ok':
      return { bg: tokens.okBg, fg: tokens.okFg }
    case 'warn':
      return { bg: tokens.warnBg, fg: tokens.warnFg }
    case 'info':
      return { bg: tokens.infoBg, fg: tokens.infoFg }
    default:
      return { bg: tokens.surfaceAlt, fg: tokens.muted }
  }
}

function formatTime(iso: string | null, locale: Locale): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return new Intl.DateTimeFormat(locale === 'es' ? 'es-EC' : 'en-GB', {
    dateStyle: 'short',
    timeStyle: 'short',
    timeZone: 'America/Guayaquil',
  }).format(d)
}

function History({ reportId, locale }: { reportId: string; locale: Locale }) {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const h = await fetchReportHistory(reportId)
        if (alive) setEntries(h.entries)
      } catch {
        if (alive) setFailed(true)
      }
    })()
    return () => {
      alive = false
    }
  }, [reportId])

  if (failed) {
    return (
      <p style={{ margin: '6px 0 0', fontSize: 12, color: tokens.warnFg }}>
        {t('adminReportsFailed', locale)}
      </p>
    )
  }
  if (entries === null) return null
  if (entries.length === 0) {
    return (
      <p style={{ margin: '6px 0 0', fontSize: 12, color: tokens.muted }}>
        {t('adminReportNoHistory', locale)}
      </p>
    )
  }
  return (
    <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12, color: tokens.muted }}>
      {entries.map((e, i) => (
        <li key={`${e.at}-${i}`}>
          {formatTime(e.at, locale)} · {e.action}
          {e.from_state && e.to_state ? ` · ${e.from_state} → ${e.to_state}` : ''}
          {e.actor_role ? ` · ${e.actor_role}` : ''}
          {e.detail ? ` · ${e.detail}` : ''}
        </li>
      ))}
    </ul>
  )
}

function ReportRow({
  report,
  locale,
  canDecide,
  onDecided,
}: {
  report: AdminReport
  locale: Locale
  canDecide: boolean
  onDecided: (updated: AdminReport) => void
}) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)

  const act = async (decision: Exclude<Decision, 'unverified'>) => {
    setBusy(true)
    setMessage(null)
    try {
      const updated = await decideReport(report.id, decision, note)
      onDecided(updated)
      setMessage({ kind: 'ok', text: t('adminDecisionSaved', locale) })
      setNote('')
    } catch (err) {
      const text =
        err instanceof ReportApiError && err.status === 403
          ? t('adminDecisionNeedsOperator', locale)
          : t('adminDecisionFailed', locale)
      setMessage({ kind: 'err', text })
    } finally {
      setBusy(false)
    }
  }

  const chip = toneColors(STATE_TONE[report.state as ReportState] ?? 'muted')

  return (
    <article
      style={{
        border: `1px solid ${tokens.border}`,
        borderRadius: 10,
        padding: 14,
        marginBottom: 14,
        background: tokens.surface,
      }}
    >
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        {report.image_url ? (
          <img
            src={report.image_url}
            alt={t('reportPhotoAlt', locale)}
            width={180}
            height={135}
            style={{ objectFit: 'cover', borderRadius: 8, border: `1px solid ${tokens.border}` }}
          />
        ) : (
          <div
            style={{
              width: 180,
              height: 135,
              display: 'grid',
              placeItems: 'center',
              background: tokens.surfaceAlt,
              color: tokens.muted,
              borderRadius: 8,
              fontSize: 12,
            }}
          >
            {t('reportNoPhoto', locale)}
          </div>
        )}

        <div style={{ flex: '1 1 320px', minWidth: 260 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span
              style={{
                background: chip.bg,
                color: chip.fg,
                border: `1px solid ${chip.fg}`,
                borderRadius: 999,
                padding: '2px 8px',
                fontSize: 12,
                fontWeight: 700,
              }}
            >
              {t(STATE_LABEL_KEY[report.state] ?? 'reportStatusUnknown', locale)}
            </span>
            <strong style={{ fontSize: 14, color: tokens.navy900 }}>{report.category}</strong>
            {report.is_stale && (
              <span style={{ fontSize: 12, color: tokens.warnFg }}>
                {t('reportStatusStale', locale)}
              </span>
            )}
            {report.seeded && (
              <span style={{ fontSize: 12, color: tokens.muted }}>{t('adminReportSeeded', locale)}</span>
            )}
          </div>

          {report.description && (
            <p style={{ margin: '8px 0', fontSize: 13, color: tokens.navy700 }}>
              {report.description}
            </p>
          )}

          <table style={{ fontSize: 12, color: tokens.muted, borderCollapse: 'collapse' }}>
            <tbody>
              <tr>
                <th style={{ textAlign: 'left', paddingRight: 8, fontWeight: 600 }}>
                  {t('adminReportSegment', locale)}
                </th>
                <td>
                  {report.road_segment_id === null
                    ? t('reportNotMatched', locale)
                    : report.road_segment_id}
                </td>
              </tr>
              <tr>
                <th style={{ textAlign: 'left', paddingRight: 8, fontWeight: 600 }}>
                  {t('adminReportSnapDistance', locale)}
                </th>
                <td>{report.snap_distance_m === null ? '—' : `${report.snap_distance_m} m`}</td>
              </tr>
              <tr>
                <th style={{ textAlign: 'left', paddingRight: 8, fontWeight: 600 }}>
                  {t('adminReportAccuracy', locale)}
                </th>
                <td>
                  {report.gps_accuracy_m === null ? '—' : `±${Math.round(report.gps_accuracy_m)} m`}
                </td>
              </tr>
              <tr>
                <th style={{ textAlign: 'left', paddingRight: 8, fontWeight: 600 }}>
                  {t('adminReportSource', locale)}
                </th>
                <td>{report.gps_source}</td>
              </tr>
              <tr>
                <th style={{ textAlign: 'left', paddingRight: 8, fontWeight: 600 }}>
                  {t('adminReportSegment', locale)} · raw
                </th>
                <td>
                  {report.gps_lat.toFixed(5)}, {report.gps_lon.toFixed(5)}
                </td>
              </tr>
              <tr>
                <th style={{ textAlign: 'left', paddingRight: 8, fontWeight: 600 }}>
                  {t('reportReportedAt', locale)}
                </th>
                <td>{formatTime(report.submitted_at, locale)}</td>
              </tr>
              <tr>
                <th style={{ textAlign: 'left', paddingRight: 8, fontWeight: 600 }}>
                  {t('reportVerifiedAt', locale)}
                </th>
                <td>{formatTime(report.verified_at, locale)}</td>
              </tr>
              <tr>
                <th style={{ textAlign: 'left', paddingRight: 8, fontWeight: 600 }}>
                  {t('reportExpiresAt', locale)}
                </th>
                <td>{formatTime(report.expires_at, locale)}</td>
              </tr>
              <tr>
                <th style={{ textAlign: 'left', paddingRight: 8, fontWeight: 600 }}>
                  {t('reportConfirmations', locale)}
                </th>
                <td>
                  {report.confirm_count} · {t('reportChallenges', locale)}: {report.challenge_count}
                </td>
              </tr>
            </tbody>
          </table>

          <p style={{ margin: '8px 0 0', fontSize: 12, color: tokens.muted }}>
            {t('adminUnverifiedIsNotClosure', locale)}
          </p>

          {canDecide && (
            <div style={{ marginTop: 10 }}>
              <label
                htmlFor={`note-${report.id}`}
                style={{ display: 'block', fontSize: 12, fontWeight: 600, color: tokens.navy900 }}
              >
                {t('adminDecisionNote', locale)}
              </label>
              <input
                id={`note-${report.id}`}
                value={note}
                maxLength={500}
                onChange={(e) => setNote(e.target.value)}
                style={{
                  width: '100%',
                  margin: '4px 0 8px',
                  padding: 7,
                  fontSize: 13,
                  borderRadius: 8,
                  border: `1px solid ${tokens.border}`,
                  fontFamily: fontStack,
                }}
              />
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {DECISION_ACTIONS.map((a) => {
                  const c = toneColors(a.tone)
                  return (
                    <button
                      key={a.decision}
                      type="button"
                      disabled={busy}
                      onClick={() => void act(a.decision)}
                      style={{
                        background: c.fg,
                        color: '#fff',
                        border: 'none',
                        borderRadius: 8,
                        padding: '9px 12px',
                        fontSize: 12,
                        fontWeight: 600,
                        cursor: busy ? 'default' : 'pointer',
                        minHeight: 40,
                      }}
                    >
                      {t(a.labelKey, locale)}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {message && (
            <p
              role={message.kind === 'err' ? 'alert' : 'status'}
              style={{
                margin: '8px 0 0',
                padding: '6px 10px',
                borderRadius: 6,
                fontSize: 12,
                background: message.kind === 'ok' ? tokens.okBg : tokens.dangerBg,
                color: message.kind === 'ok' ? tokens.okFg : tokens.dangerFg,
              }}
            >
              {message.text}
            </p>
          )}

          <p style={{ margin: '10px 0 0', fontSize: 12, fontWeight: 600, color: tokens.navy900 }}>
            {t('adminReportHistory', locale)}
          </p>
          <History reportId={report.id} locale={locale} />
        </div>
      </div>
    </article>
  )
}

export default function AdminReports({ locale, session }: { locale: Locale; session: Session | null }) {
  const [load, setLoad] = useState<Loadable>({ state: 'loading' })

  const canDecide = session !== null && session.role !== 'public' && session.role !== 'viewer'

  const reload = useCallback(async () => {
    setLoad({ state: 'loading' })
    try {
      const reports = await fetchAdminReports({ limit: 100 })
      setLoad({ state: 'ready', reports })
    } catch (err) {
      const text =
        err instanceof ReportApiError && (err.status === 401 || err.status === 403)
          ? t('adminReportsNeedRole', locale)
          : t('adminReportsFailed', locale)
      setLoad({ state: 'error', text })
    }
  }, [locale])

  useEffect(() => {
    void reload()
  }, [reload])

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
      <h2 style={{ margin: '0 0 4px', fontSize: 16, color: tokens.navy900 }}>
        {t('adminReportsTitle', locale)}
      </h2>
      <p style={{ margin: '0 0 12px', fontSize: 12, color: tokens.muted }}>
        {t('adminReportsExplain', locale)}
      </p>

      {!canDecide && (
        <p
          style={{
            background: tokens.warnBg,
            color: tokens.warnFg,
            padding: '8px 12px',
            borderRadius: 8,
            fontSize: 12,
          }}
        >
          {t('adminReportsNeedRole', locale)}
        </p>
      )}

      <button
        type="button"
        onClick={() => void reload()}
        style={{
          background: tokens.navy700,
          color: '#fff',
          border: 'none',
          borderRadius: 8,
          padding: '9px 14px',
          fontSize: 13,
          fontWeight: 600,
          cursor: 'pointer',
          minHeight: 40,
          marginBottom: 12,
        }}
      >
        {locale === 'es' ? 'Actualizar' : 'Refresh'}
      </button>

      {load.state === 'loading' && (
        <p style={{ fontSize: 13, color: tokens.muted }}>
          {locale === 'es' ? 'Cargando…' : 'Loading…'}
        </p>
      )}
      {load.state === 'error' && (
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
          {load.text}
        </p>
      )}
      {load.state === 'ready' && load.reports.length === 0 && (
        <p style={{ fontSize: 13, color: tokens.muted }}>{t('adminReportsEmpty', locale)}</p>
      )}
      {load.state === 'ready' &&
        load.reports.map((r) => (
          <ReportRow
            key={r.id}
            report={r}
            locale={locale}
            canDecide={canDecide}
            onDecided={(updated) =>
              setLoad((prev) =>
                prev.state === 'ready'
                  ? {
                      state: 'ready',
                      reports: prev.reports.map((x) => (x.id === updated.id ? updated : x)),
                    }
                  : prev,
              )
            }
          />
        ))}
    </section>
  )
}
