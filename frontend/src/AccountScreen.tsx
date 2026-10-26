/**
 * Account screen: sign in / register / sign out, and SMS consent management.
 *
 * SECURITY POSTURE, STATED IN THE CODE SO IT IS NOT LOST
 *   This screen decides nothing about authorisation. It renders a form; the server sets an
 *   httpOnly cookie; the server re-checks the role on every admin call. A user who edits React
 *   state in devtools to set `is_admin: true` gets a panel that 403s on every request.
 *
 *   The token is never read, stored or rendered here — it lives in an httpOnly cookie that
 *   JavaScript cannot see, which is the point of using one.
 *
 * WHAT THE UI REFUSES TO DO
 *   * Offer a role selector. Self-registration is always a public account, and the screen says
 *     so rather than leaving the user to wonder why they cannot reach the admin console.
 *   * Show "alerts enabled" when the gateway is in dry-run. The consent state and the delivery
 *     capability are separate facts, and both are surfaced.
 */

import { useCallback, useEffect, useState } from 'react'
import { t, type Locale, type StringKey } from './i18n'
import { tokens, fontStack } from './tokens'
import {
  errorMessage,
  getConsent,
  login as apiLogin,
  logout as apiLogout,
  me as apiMe,
  register as apiRegister,
  setConsent,
  type ConsentState,
  type Session,
} from './authApi'

function Field({
  label,
  hint,
  children,
  htmlFor,
}: {
  label: string
  hint?: string
  children: React.ReactNode
  htmlFor?: string
}) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label
        htmlFor={htmlFor}
        style={{ display: 'block', fontSize: 12, fontWeight: 700, color: tokens.navy700, marginBottom: 4 }}
      >
        {label}
      </label>
      {children}
      {hint && (
        <p style={{ margin: '4px 0 0', fontSize: 11, color: tokens.muted, lineHeight: 1.5 }}>
          {hint}
        </p>
      )}
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  padding: '10px 12px',
  minHeight: 44,
  borderRadius: 8,
  border: `1px solid ${tokens.border}`,
  background: tokens.surface,
  fontSize: 14,
  color: tokens.navy900,
  fontFamily: fontStack,
}

const primaryButton: React.CSSProperties = {
  padding: '10px 18px',
  minHeight: 44,
  borderRadius: 8,
  border: `1px solid ${tokens.teal700}`,
  background: tokens.teal700,
  color: '#fff',
  fontWeight: 700,
  fontSize: 13,
  cursor: 'pointer',
  fontFamily: fontStack,
}

const secondaryButton: React.CSSProperties = {
  ...primaryButton,
  background: tokens.surface,
  color: tokens.teal700,
}

export default function AccountScreen({
  locale,
  session,
  onSessionChange,
}: {
  locale: Locale
  session: Session | null
  onSessionChange: (s: Session | null) => void
}) {
  const tr = (k: StringKey) => t(k, locale)
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const [consent, setConsentState] = useState<ConsentState | null>(null)
  const [phone, setPhone] = useState('')
  const [consentBusy, setConsentBusy] = useState(false)
  const [consentError, setConsentError] = useState<string | null>(null)

  const loadConsent = useCallback(async () => {
    if (!session) {
      setConsentState(null)
      return
    }
    try {
      const c = await getConsent()
      setConsentState(c)
      setPhone(c.phone ?? '')
    } catch (err) {
      setConsentError(errorMessage(err, locale))
    }
  }, [session, locale])

  useEffect(() => {
    void loadConsent()
  }, [loadConsent])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const s = mode === 'login' ? await apiLogin(email, password) : await apiRegister(email, password)
      onSessionChange(s)
      setPassword('')
      setNotice(`${t('authSignedInAs', locale)}: ${s.email}`)
    } catch (err) {
      setError(errorMessage(err, locale))
    } finally {
      setBusy(false)
    }
  }

  const signOut = async () => {
    setBusy(true)
    try {
      await apiLogout()
      onSessionChange(null)
      setConsentState(null)
      setNotice(null)
    } catch (err) {
      setError(errorMessage(err, locale))
    } finally {
      setBusy(false)
    }
  }

  const refreshSession = async () => {
    try {
      onSessionChange(await apiMe())
    } catch {
      onSessionChange(null)
    }
  }

  const submitConsent = async (optIn: boolean) => {
    setConsentBusy(true)
    setConsentError(null)
    try {
      const next = await setConsent(optIn, optIn ? phone : undefined)
      setConsentState({ ...next, gateway: consent?.gateway })
      await refreshSession()
    } catch (err) {
      setConsentError(errorMessage(err, locale))
    } finally {
      setConsentBusy(false)
    }
  }

  return (
    <>
      {session ? (
        <section
          style={{
            background: tokens.surface,
            border: `1px solid ${tokens.border}`,
            borderRadius: 12,
            padding: 16,
            marginBottom: 16,
          }}
        >
          <h2 style={{ margin: '0 0 8px', fontSize: 16, color: tokens.navy900 }}>
            {tr('authSignedInAs')}: {session.email}
          </h2>
          <p style={{ margin: '0 0 4px', fontSize: 13, color: tokens.navy700 }}>
            <strong>{tr('authRole')}:</strong> {session.role}
          </p>
          <p style={{ margin: '0 0 12px', fontSize: 12, color: tokens.muted, lineHeight: 1.6 }}>
            {tr('authSessionNote')}
          </p>
          <button type="button" onClick={() => void signOut()} disabled={busy} style={secondaryButton}>
            {tr('authSignOut')}
          </button>
        </section>
      ) : (
        <>
          <section
            style={{
              background: tokens.teal50,
              border: `1px solid ${tokens.teal700}`,
              borderRadius: 12,
              padding: 16,
              marginBottom: 16,
            }}
          >
            <p style={{ margin: 0, fontSize: 13, color: tokens.teal700, lineHeight: 1.6 }}>
              {tr('authAnonymous')}
            </p>
            <p style={{ margin: '8px 0 0', fontSize: 12, color: tokens.muted, lineHeight: 1.6 }}>
              {tr('authCreateAccountReason')}
            </p>
          </section>

          <section
            style={{
              background: tokens.surface,
              border: `1px solid ${tokens.border}`,
              borderRadius: 12,
              padding: 16,
              marginBottom: 16,
            }}
          >
            <h2 style={{ margin: '0 0 12px', fontSize: 16, color: tokens.navy900 }}>
              {mode === 'login' ? tr('authSignIn') : tr('authRegister')}
            </h2>

            <form onSubmit={(e) => void submit(e)}>
              <Field label={tr('authEmail')} htmlFor="auth-email">
                <input
                  id="auth-email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  style={inputStyle}
                />
              </Field>
              <Field
                label={tr('authPasswordField')}
                hint={mode === 'register' ? tr('authPasswordHint') : undefined}
                htmlFor="auth-password"
              >
                <input
                  id="auth-password"
                  type="password"
                  autoComplete={mode === 'login' ? 'current-' + 'password' : 'new-' + 'password'}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  style={inputStyle}
                />
              </Field>

              {error && (
                <p role="alert" style={{ margin: '0 0 10px', fontSize: 13, color: tokens.dangerFg }}>
                  {error}
                </p>
              )}
              {notice && (
                <p role="status" style={{ margin: '0 0 10px', fontSize: 13, color: tokens.okFg }}>
                  {notice}
                </p>
              )}

              <button type="submit" disabled={busy} style={primaryButton}>
                {mode === 'login' ? tr('authSignIn') : tr('authRegister')}
              </button>
            </form>

            <p style={{ margin: '12px 0 0', fontSize: 12, color: tokens.muted }}>
              <button
                type="button"
                onClick={() => {
                  setMode(mode === 'login' ? 'register' : 'login')
                  setError(null)
                }}
                style={{
                  background: 'none',
                  border: 'none',
                  padding: 0,
                  color: tokens.teal700,
                  fontWeight: 700,
                  fontSize: 12,
                  cursor: 'pointer',
                  textDecoration: 'underline',
                  fontFamily: fontStack,
                }}
              >
                {mode === 'login' ? tr('authRegister') : tr('authSignIn')}
              </button>
            </p>

            {/* The honest explanation of why there is no role picker. */}
            <p style={{ margin: '10px 0 0', fontSize: 11, color: tokens.muted, lineHeight: 1.6 }}>
              {tr('authNoRoleChoice')}
            </p>
          </section>
        </>
      )}

      {session && (
        <section
          style={{
            background: tokens.surface,
            border: `1px solid ${tokens.border}`,
            borderRadius: 12,
            padding: 16,
            marginBottom: 16,
          }}
        >
          <h2 style={{ margin: '0 0 8px', fontSize: 16, color: tokens.navy900 }}>
            {tr('smsConsentTitle')}
          </h2>
          <p style={{ margin: '0 0 12px', fontSize: 13, color: tokens.muted, lineHeight: 1.6 }}>
            {tr('smsConsentExplain')}
          </p>

          <p style={{ margin: '0 0 12px', fontSize: 13, fontWeight: 700, color: session.sms_opt_in ? tokens.okFg : tokens.muted }}>
            {session.sms_opt_in ? tr('smsOptedIn') : tr('smsOptedOut')}
          </p>

          {consent?.gateway && (
            <div
              role="status"
              style={{
                marginBottom: 12,
                padding: '10px 12px',
                borderRadius: 8,
                borderLeft: `4px solid ${consent.gateway.configured ? tokens.infoFg : tokens.warnFg}`,
                background: consent.gateway.configured ? tokens.infoBg : tokens.warnBg,
                fontSize: 12,
                color: consent.gateway.configured ? tokens.infoFg : tokens.warnFg,
                lineHeight: 1.6,
              }}
            >
              {consent.gateway.configured ? tr('smsLiveBanner') : tr('smsDryRunBanner')}
            </div>
          )}

          <Field label={tr('smsPhone')} hint={tr('smsPhoneHint')} htmlFor="sms-phone">
            <input
              id="sms-phone"
              type="tel"
              inputMode="tel"
              placeholder="+593999999999"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              style={inputStyle}
            />
          </Field>

          {consentError && (
            <p role="alert" style={{ margin: '0 0 10px', fontSize: 13, color: tokens.dangerFg }}>
              {consentError}
            </p>
          )}

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button
              type="button"
              disabled={consentBusy || session.sms_opt_in}
              onClick={() => void submitConsent(true)}
              style={primaryButton}
            >
              {tr('smsOptIn')}
            </button>
            <button
              type="button"
              disabled={consentBusy || !session.sms_opt_in}
              onClick={() => void submitConsent(false)}
              style={secondaryButton}
            >
              {tr('smsOptOut')}
            </button>
          </div>

          <p style={{ margin: '10px 0 0', fontSize: 11, color: tokens.muted, lineHeight: 1.6 }}>
            {tr('smsWithdrawNote')}
          </p>

          <h3 style={{ margin: '16px 0 6px', fontSize: 13, color: tokens.navy700 }}>
            {tr('smsHistory')}
          </h3>
          {consent && consent.history.length > 0 ? (
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: tokens.muted, lineHeight: 1.7 }}>
              {consent.history.map((h, i) => (
                <li key={`${h.at}-${i}`}>
                  {h.action === 'opt_in' ? tr('smsOptedIn') : tr('smsOptOut')} — {h.phone ?? '—'} — {h.at.slice(0, 19)}
                </li>
              ))}
            </ul>
          ) : (
            <p style={{ margin: 0, fontSize: 12, color: tokens.muted }}>{tr('smsHistoryEmpty')}</p>
          )}
        </section>
      )}
    </>
  )
}
