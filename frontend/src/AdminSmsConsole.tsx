/**
 * Admin SMS console: alert drafting, approval, sending, and the delivery ledger.
 *
 * THE FOUR THINGS THIS SCREEN IS CAREFUL ABOUT
 *
 *  1. **It never claims delivery from acceptance.** Every state shown is the provider's own
 *     vocabulary passed through, or `dry_run`. `sent` is labelled "Sent — not confirmed
 *     delivered", because the SMS Gateway documents that a message can remain in `Sent` even
 *     after successful delivery. Presenting that as delivered would be a lie of omission.
 *  2. **Dry run is unmissable.** When no gateway credentials exist, a banner says nothing leaves
 *     the machine, and every result is labelled "Dry run — not sent".
 *  3. **Sending needs a second click and a second person.** The send button reveals an explicit
 *     confirmation; the server additionally refuses if the drafter is also the approver.
 *  4. **Every alert is marked DEMO.** There is no verified emergency feed, so no alert created
 *     here can be anything else, and the badge says so on each row.
 *
 * The screen does not enforce any of this on its own — the server does. This is the rendering of
 * what the server allows, not the mechanism that makes it true.
 */

import { useCallback, useEffect, useState } from 'react'
import { t, type Locale, type StringKey } from './i18n'
import { tokens, fontStack } from './tokens'
import {
  adminAlerts,
  adminDelivery,
  adminStatus,
  approveAlert,
  createAlert,
  errorMessage,
  sendAlert,
  testSms,
  type AlertRow,
  type DeliveryMessage,
  type GatewayInfo,
  type Session,
} from './authApi'

const SEVERITIES = ['info', 'watch', 'warning', 'severe'] as const

const inputStyle: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  padding: '9px 11px',
  minHeight: 44,
  borderRadius: 8,
  border: `1px solid ${tokens.border}`,
  background: tokens.surface,
  fontSize: 13,
  color: tokens.navy900,
  fontFamily: fontStack,
}

const btn = (primary: boolean): React.CSSProperties => ({
  padding: '9px 16px',
  minHeight: 44,
  borderRadius: 8,
  border: `1px solid ${primary ? tokens.teal700 : tokens.border}`,
  background: primary ? tokens.teal700 : tokens.surface,
  color: primary ? '#fff' : tokens.navy700,
  fontWeight: 700,
  fontSize: 13,
  cursor: 'pointer',
  fontFamily: fontStack,
})

/** Provider state -> visible label + colour. Colour is never the only channel. */
function stateLabel(state: string, tr: (k: StringKey) => string): { text: string; fg: string; bg: string } {
  switch (state) {
    case 'delivered':
      return { text: tr('stateDelivered'), fg: tokens.okFg, bg: tokens.teal50 }
    case 'sent':
      return { text: tr('stateSent'), fg: tokens.infoFg, bg: tokens.infoBg }
    case 'processed':
      return { text: tr('stateProcessed'), fg: tokens.infoFg, bg: tokens.infoBg }
    case 'pending':
      return { text: tr('statePending'), fg: tokens.watchFg, bg: tokens.watchBg }
    case 'dry_run':
      return { text: tr('stateDryRun'), fg: tokens.simFg, bg: tokens.simBg }
    case 'failed':
      return { text: tr('stateFailed'), fg: tokens.dangerFg, bg: tokens.dangerBg }
    case 'cancelled':
    case 'cancelling':
      return { text: tr('stateCancelled'), fg: tokens.muted, bg: tokens.surfaceAlt }
    default:
      return { text: tr('stateUnknown'), fg: tokens.muted, bg: tokens.surfaceAlt }
  }
}

function Chip({ label, fg, bg }: { label: string; fg: string; bg: string }) {
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
        letterSpacing: 0.3,
      }}
    >
      {label}
    </span>
  )
}

function Panel({
  title,
  children,
  tone = 'plain',
}: {
  title: string
  children: React.ReactNode
  tone?: 'plain' | 'warning'
}) {
  return (
    <section
      style={{
        background: tone === 'warning' ? tokens.warnBg : tokens.surface,
        border: `1px solid ${tone === 'warning' ? tokens.warnFg : tokens.border}`,
        borderRadius: 12,
        padding: 16,
        marginBottom: 16,
      }}
    >
      <h2 style={{ margin: '0 0 10px', fontSize: 15, color: tokens.navy900 }}>{title}</h2>
      {children}
    </section>
  )
}

export default function AdminSmsConsole({
  locale,
  session,
}: {
  locale: Locale
  session: Session
}) {
  const tr = (k: StringKey) => t(k, locale)

  const [gateway, setGateway] = useState<GatewayInfo | null>(null)
  const [optedIn, setOptedIn] = useState(0)
  const [alerts, setAlerts] = useState<AlertRow[]>([])
  const [messages, setMessages] = useState<DeliveryMessage[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionNotice, setActionNotice] = useState<string | null>(null)

  const [draft, setDraft] = useState({
    title_en: '',
    title_es: '',
    body_en: '',
    body_es: '',
    severity: 'warning' as (typeof SEVERITIES)[number],
    area: 'centro',
  })
  const [confirmSend, setConfirmSend] = useState<string | null>(null)

  const [testTo, setTestTo] = useState('')
  const [testConfirm, setTestConfirm] = useState(false)
  const [testResult, setTestResult] = useState<{ state: string; dry_run: boolean } | null>(null)

  const reload = useCallback(async () => {
    setLoadError(null)
    try {
      const [status, alertsRes, delivery] = await Promise.all([
        adminStatus(),
        adminAlerts(),
        adminDelivery(),
      ])
      setGateway(status.gateway)
      setOptedIn(status.recipients_opted_in)
      setAlerts(alertsRes.alerts)
      setMessages(delivery.messages)
    } catch (err) {
      setLoadError(errorMessage(err, locale))
    }
  }, [locale])

  useEffect(() => {
    void reload()
  }, [reload])

  const saveDraft = async () => {
    setBusy(true)
    setActionError(null)
    setActionNotice(null)
    try {
      await createAlert({ ...draft })
      setDraft({ ...draft, title_en: '', title_es: '', body_en: '', body_es: '' })
      setActionNotice(tr('adminAlertStatusDraft'))
      await reload()
    } catch (err) {
      setActionError(errorMessage(err, locale))
    } finally {
      setBusy(false)
    }
  }

  const approve = async (id: string) => {
    setBusy(true)
    setActionError(null)
    try {
      await approveAlert(id)
      await reload()
    } catch (err) {
      setActionError(errorMessage(err, locale))
    } finally {
      setBusy(false)
    }
  }

  const doSend = async (id: string) => {
    setBusy(true)
    setActionError(null)
    setActionNotice(null)
    try {
      const res = await sendAlert(id, 'en')
      setActionNotice(
        `${res.dry_run ? tr('stateDryRun') : tr('stateSent')} — ${res.accepted}/${res.attempted}`,
      )
      setConfirmSend(null)
      await reload()
    } catch (err) {
      setActionError(errorMessage(err, locale))
    } finally {
      setBusy(false)
    }
  }

  const runTest = async () => {
    setBusy(true)
    setActionError(null)
    setTestResult(null)
    try {
      const res = await testSms(testTo, testConfirm)
      setTestResult({ state: res.state, dry_run: res.dry_run })
    } catch (err) {
      setActionError(errorMessage(err, locale))
    } finally {
      setBusy(false)
    }
  }

  const canPublish = session.role === 'publisher' || session.role === 'admin'
  const canOperate = canPublish || session.role === 'operator'

  if (loadError) {
    return (
      <Panel title={tr('adminAlertsSection')} tone="warning">
        <p role="alert" style={{ margin: '0 0 10px', fontSize: 13, color: tokens.warnFg }}>
          {loadError}
        </p>
        <button type="button" onClick={() => void reload()} style={btn(false)}>
          {tr('retry')}
        </button>
      </Panel>
    )
  }

  return (
    <>
      {/* Gateway mode banner: unmissable, not dismissible. */}
      {gateway && (
        <div
          role="status"
          style={{
            marginBottom: 16,
            padding: '12px 14px',
            borderRadius: 10,
            borderLeft: `5px solid ${gateway.configured ? tokens.infoFg : tokens.warnFg}`,
            background: gateway.configured ? tokens.infoBg : tokens.warnBg,
            color: gateway.configured ? tokens.infoFg : tokens.warnFg,
            fontSize: 13,
            fontWeight: 600,
            lineHeight: 1.6,
          }}
        >
          {gateway.configured ? tr('smsLiveBanner') : tr('smsDryRunBanner')}
        </div>
      )}

      <Panel title={tr('adminAlertsSection')}>
        <p style={{ margin: '0 0 10px', fontSize: 12, color: tokens.muted }}>
          <strong>{tr('adminRecipientsOptedIn')}:</strong> {optedIn}
          {gateway && (
            <>
              {' · '}
              <strong>{tr('adminGatewayMode')}:</strong> {gateway.mode}
            </>
          )}
        </p>

        {actionError && (
          <p role="alert" style={{ margin: '0 0 10px', fontSize: 13, color: tokens.dangerFg }}>
            {actionError}
          </p>
        )}
        {actionNotice && (
          <p role="status" style={{ margin: '0 0 10px', fontSize: 13, color: tokens.okFg }}>
            {actionNotice}
          </p>
        )}

        {alerts.length === 0 ? (
          <p style={{ margin: 0, fontSize: 13, color: tokens.muted }}>{tr('adminAlertsEmpty')}</p>
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {alerts.map((a) => (
              <li
                key={a.id}
                style={{ borderTop: `1px solid ${tokens.border}`, padding: '10px 0' }}
              >
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                  <strong style={{ fontSize: 13, color: tokens.navy900 }}>{a.title_en}</strong>
                  <Chip
                    label={a.severity}
                    fg={tokens.warnFg}
                    bg={tokens.warnBg}
                  />
                  <Chip
                    label={
                      a.status === 'draft'
                        ? tr('adminAlertStatusDraft')
                        : a.status === 'approved'
                          ? tr('adminAlertStatusApproved')
                          : a.status === 'sent'
                            ? tr('adminAlertStatusSent')
                            : tr('adminAlertStatusFailed')
                    }
                    fg={tokens.navy700}
                    bg={tokens.surfaceAlt}
                  />
                  {a.is_demo === 1 && (
                    <Chip label="DEMO" fg={tokens.simFg} bg={tokens.simBg} />
                  )}
                </div>
                <p style={{ margin: '4px 0 0', fontSize: 11, color: tokens.muted }}>
                  {a.area} · {a.created_at.slice(0, 19)}
                </p>
                {a.is_demo === 1 && (
                  <p style={{ margin: '4px 0 0', fontSize: 11, color: tokens.simFg, fontWeight: 600 }}>
                    {tr('adminAlertDemo')}
                  </p>
                )}

                <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                  {a.status === 'draft' && canPublish && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void approve(a.id)}
                      style={btn(false)}
                    >
                      {tr('adminApprove')}
                    </button>
                  )}
                  {a.status === 'approved' && canPublish && (
                    <>
                      {confirmSend === a.id ? (
                        <>
                          <span style={{ fontSize: 12, color: tokens.warnFg, alignSelf: 'center' }}>
                            {tr('adminSendConfirm')}
                          </span>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => void doSend(a.id)}
                            style={btn(true)}
                          >
                            {tr('adminSendConfirmYes')}
                          </button>
                          <button type="button" onClick={() => setConfirmSend(null)} style={btn(false)}>
                            {tr('adminCancel')}
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => setConfirmSend(a.id)}
                          style={btn(true)}
                        >
                          {tr('adminSend')}
                        </button>
                      )}
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        {canPublish && (
          <p style={{ margin: '10px 0 0', fontSize: 11, color: tokens.muted, lineHeight: 1.6 }}>
            {tr('adminSodNote')}
          </p>
        )}
      </Panel>

      {canOperate && (
        <Panel title={tr('adminNewAlert')}>
          <p style={{ margin: '0 0 10px', fontSize: 11, color: tokens.warnFg, fontWeight: 600 }}>
            {tr('adminAlertBilingualRequired')}
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
            <div>
              <label htmlFor="t-en" style={{ fontSize: 11, fontWeight: 700, color: tokens.navy700 }}>
                {tr('adminAlertTitleEn')}
              </label>
              <input
                id="t-en"
                value={draft.title_en}
                onChange={(e) => setDraft({ ...draft, title_en: e.target.value })}
                style={inputStyle}
              />
            </div>
            <div>
              <label htmlFor="t-es" style={{ fontSize: 11, fontWeight: 700, color: tokens.navy700 }}>
                {tr('adminAlertTitleEs')}
              </label>
              <input
                id="t-es"
                value={draft.title_es}
                onChange={(e) => setDraft({ ...draft, title_es: e.target.value })}
                style={inputStyle}
              />
            </div>
            <div>
              <label htmlFor="b-en" style={{ fontSize: 11, fontWeight: 700, color: tokens.navy700 }}>
                {tr('adminAlertBodyEn')}
              </label>
              <textarea
                id="b-en"
                rows={3}
                value={draft.body_en}
                onChange={(e) => setDraft({ ...draft, body_en: e.target.value })}
                style={{ ...inputStyle, resize: 'vertical' }}
              />
            </div>
            <div>
              <label htmlFor="b-es" style={{ fontSize: 11, fontWeight: 700, color: tokens.navy700 }}>
                {tr('adminAlertBodyEs')}
              </label>
              <textarea
                id="b-es"
                rows={3}
                value={draft.body_es}
                onChange={(e) => setDraft({ ...draft, body_es: e.target.value })}
                style={{ ...inputStyle, resize: 'vertical' }}
              />
            </div>
            <div>
              <label htmlFor="sev" style={{ fontSize: 11, fontWeight: 700, color: tokens.navy700 }}>
                {tr('adminAlertSeverity')}
              </label>
              <select
                id="sev"
                value={draft.severity}
                onChange={(e) =>
                  setDraft({ ...draft, severity: e.target.value as (typeof SEVERITIES)[number] })
                }
                style={inputStyle}
              >
                {SEVERITIES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="area" style={{ fontSize: 11, fontWeight: 700, color: tokens.navy700 }}>
                {tr('adminAlertArea')}
              </label>
              <input
                id="area"
                value={draft.area}
                onChange={(e) => setDraft({ ...draft, area: e.target.value })}
                style={inputStyle}
              />
            </div>
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={() => void saveDraft()}
            style={{ ...btn(true), marginTop: 12 }}
          >
            {tr('adminAlertSaveDraft')}
          </button>
        </Panel>
      )}

      {canOperate && (
        <Panel title={tr('adminTestSms')}>
          <label htmlFor="test-to" style={{ fontSize: 11, fontWeight: 700, color: tokens.navy700 }}>
            {tr('adminTestSmsTo')}
          </label>
          <input
            id="test-to"
            type="tel"
            placeholder="+593999999999"
            value={testTo}
            onChange={(e) => setTestTo(e.target.value)}
            style={inputStyle}
          />
          <label
            style={{
              display: 'flex',
              gap: 8,
              alignItems: 'flex-start',
              margin: '10px 0',
              fontSize: 12,
              color: tokens.muted,
              lineHeight: 1.5,
            }}
          >
            <input
              type="checkbox"
              checked={testConfirm}
              onChange={(e) => setTestConfirm(e.target.checked)}
              style={{ marginTop: 3, width: 18, height: 18 }}
            />
            {tr('adminTestSmsConfirm')}
          </label>
          <button
            type="button"
            disabled={busy || !testConfirm}
            onClick={() => void runTest()}
            style={btn(true)}
          >
            {tr('adminTestSmsSend')}
          </button>

          {testResult && (
            <p role="status" style={{ margin: '10px 0 0', fontSize: 12 }}>
              <Chip
                label={stateLabel(testResult.state, tr).text}
                fg={stateLabel(testResult.state, tr).fg}
                bg={stateLabel(testResult.state, tr).bg}
              />
              {testResult.dry_run && (
                <span style={{ marginLeft: 8, color: tokens.simFg, fontWeight: 600 }}>
                  {tr('stateDryRun')}
                </span>
              )}
            </p>
          )}
        </Panel>
      )}

      <Panel title={tr('adminDeliverySection')}>
        <p style={{ margin: '0 0 10px', fontSize: 11, color: tokens.muted, lineHeight: 1.6 }}>
          {tr('adminDeliveryStateNote')}
        </p>
        {messages.length === 0 ? (
          <p style={{ margin: 0, fontSize: 13, color: tokens.muted }}>{tr('adminDeliveryEmpty')}</p>
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {messages.map((m) => {
              const s = stateLabel(m.state, tr)
              return (
                <li
                  key={m.id}
                  style={{
                    display: 'flex',
                    gap: 10,
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    borderTop: `1px solid ${tokens.border}`,
                    padding: '7px 0',
                    fontSize: 12,
                  }}
                >
                  <Chip label={s.text} fg={s.fg} bg={s.bg} />
                  <span style={{ color: tokens.navy700, fontFamily: 'ui-monospace, monospace' }}>
                    {m.phone}
                  </span>
                  {m.dry_run && <Chip label="DRY RUN" fg={tokens.simFg} bg={tokens.simBg} />}
                  {m.error_code && (
                    <span style={{ color: tokens.dangerFg }}>{m.error_code}</span>
                  )}
                  <span style={{ color: tokens.muted, marginLeft: 'auto' }}>
                    {m.created_at.slice(0, 19)}
                  </span>
                </li>
              )
            })}
          </ul>
        )}
      </Panel>

      {gateway && !gateway.configured && (
        <Panel title={tr('adminConfigRequired')} tone="warning">
          <p style={{ margin: '0 0 8px', fontSize: 12, color: tokens.warnFg, lineHeight: 1.6 }}>
            {tr('adminConfigBody')}
          </p>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: tokens.warnFg }}>
            {gateway.required_env.map((v) => (
              <li key={v}>
                <code style={{ wordBreak: 'break-word' }}>{v}</code>
              </li>
            ))}
            {gateway.optional_env.map((v) => (
              <li key={v}>
                <code style={{ wordBreak: 'break-word' }}>{v}</code> (optional)
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </>
  )
}
