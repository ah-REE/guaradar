/**
 * Accounts console — create and manage staff accounts.
 *
 * WHAT THIS SCREEN IS FOR
 *   Before this, a second reviewer could only be provisioned by SSH-ing into the server and
 *   running `python -m app.admin_cli create-user`. That is the correct *bootstrap* path and it
 *   stays, but it makes ordinary team administration impossible. This screen is the UI
 *   equivalent for everything except creating an admin.
 *
 * WHAT IT CANNOT DO, AND WHY THAT IS SHOWN RATHER THAN HIDDEN
 *   * It cannot create an `admin`. The server refuses any grant at or above the caller's own
 *     role, so an admin cannot mint another admin — that is the privilege-escalation guard. The
 *     screen states this in a sentence instead of offering a button that would always 403.
 *   * It cannot change a role. Roles are fixed at creation, which is what makes "no escalation"
 *     structural rather than a rule to remember.
 *   * It never deletes. Disabling keeps the account and its history.
 *
 * AUTHORISATION IS SERVER-SIDE
 *   The list of grantable roles comes from `GET /api/admin/accounts/capabilities`, computed by
 *   the same rule the write path enforces. The UI never derives permissions from a role string
 *   it holds in the browser, so the form cannot disagree with the server about what is allowed.
 *   A user who edits this file to enable a button still gets 403 from the API.
 *
 * NEVER ECHOES CREDENTIALS
 *   The passphrase field is write-only. Nothing returned by the API is displayed, and there is no
 *   "show password" affordance that would put one on screen during a screen-share.
 */

import { useCallback, useEffect, useState } from 'react'
import { t, type Locale, type StringKey } from './i18n'
import { tokens, fontStack } from './tokens'
import type { Session } from './authApi'

/* ------------------------------------------------------------------ */
/* API                                                                */
/* ------------------------------------------------------------------ */

export interface AccountRow {
  id: string
  email: string
  role: string
  disabled: boolean
  created_at: string
  phone_e164: string | null
  sms_opt_in: boolean
  last_active_at: string | null
}

interface AccountList {
  accounts: AccountRow[]
  stats: Record<string, number>
  can_create: string[]
  actor_role: string
  notes: string[]
}

class AccountApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message)
    this.name = 'AccountApiError'
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, { credentials: 'same-origin', ...init })
  } catch {
    throw new AccountApiError(0, 'network_error', 'Could not reach the server.')
  }
  if (!res.ok) {
    let code = `http_${res.status}`
    let message = res.statusText || 'Request failed.'
    try {
      const body = await res.json()
      const detail = body?.detail
      if (typeof detail === 'string') message = detail
      else if (detail && typeof detail === 'object') {
        code = String(detail.code ?? code)
        message = String(detail.message ?? message)
      } else if (Array.isArray(detail) && detail[0]?.msg) {
        // pydantic validation shape
        code = 'validation_failed'
        message = String(detail[0].msg)
      }
    } catch {
      /* keep status-derived code */
    }
    throw new AccountApiError(res.status, code, message)
  }
  return (await res.json()) as T
}

const listAccounts = () => call<AccountList>('/api/admin/accounts')

const createAccount = (email: string, passphrase: string, role: string) =>
  call<AccountRow>('/api/admin/accounts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, passphrase, role }),
  })

const setDisabled = (id: string, disabled: boolean) =>
  call<AccountRow>(`/api/admin/accounts/${encodeURIComponent(id)}/disabled`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ disabled }),
  })

const resetPassphrase = (id: string, passphrase: string) =>
  call<AccountRow>(`/api/admin/accounts/${encodeURIComponent(id)}/passphrase`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ passphrase }),
  })

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

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

/** Role descriptions, so an operator knows what they are granting before granting it. */
const ROLE_KEY: Record<string, StringKey> = {
  viewer: 'acctRoleViewer',
  operator: 'acctRoleOperator',
  publisher: 'acctRolePublisher',
  admin: 'acctRoleAdmin',
  public: 'acctRolePublic',
}

/** What each role may actually do, stated in the selector so a grant is informed. */
const ROLE_WHAT: Record<string, StringKey> = {
  viewer: 'acctRoleWhatViewer',
  operator: 'acctRoleWhatOperator',
  publisher: 'acctRoleWhatPublisher',
  admin: 'acctRoleWhatAdmin',
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: 9,
  fontSize: 14,
  borderRadius: 8,
  border: `1px solid ${tokens.border}`,
  fontFamily: fontStack,
  marginTop: 4,
}

const button = (bg: string, disabled = false): React.CSSProperties => ({
  background: disabled ? tokens.muted : bg,
  color: '#fff',
  border: 'none',
  borderRadius: 8,
  padding: '10px 16px',
  minHeight: 40,
  fontSize: 13,
  fontWeight: 600,
  cursor: disabled ? 'default' : 'pointer',
  fontFamily: fontStack,
})

/* ------------------------------------------------------------------ */
/* Screen                                                             */
/* ------------------------------------------------------------------ */

type Load =
  | { state: 'loading' }
  | { state: 'ready'; data: AccountList }
  | { state: 'error'; text: string }

export default function AdminAccounts({
  locale,
  session,
}: {
  locale: Locale
  session: Session | null
}) {
  const tr = (k: StringKey) => t(k, locale)

  const [load, setLoad] = useState<Load>({ state: 'loading' })
  const [email, setEmail] = useState('')
  const [passphrase, setPassphrase] = useState('')
  const [role, setRole] = useState('operator')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [resetFor, setResetFor] = useState<string | null>(null)
  const [resetValue, setResetValue] = useState('')

  const reload = useCallback(async () => {
    setLoad({ state: 'loading' })
    try {
      const data = await listAccounts()
      setLoad({ state: 'ready', data })
      // Default to the least-privileged role the caller may grant, so nobody accidentally
      // creates a publisher when they meant a viewer.
      if (data.can_create.length > 0 && !data.can_create.includes(role)) {
        setRole(data.can_create[0])
      }
    } catch (err) {
      const text =
        err instanceof AccountApiError && (err.status === 401 || err.status === 403)
          ? tr('acctNeedRole')
          : tr('acctLoadFailed')
      setLoad({ state: 'error', text })
    }
    // `role` is intentionally not a dependency: including it would refetch on every keystroke of
    // the role selector.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale])

  useEffect(() => {
    void reload()
  }, [reload])

  const submitCreate = async () => {
    setBusy(true)
    setNotice(null)
    try {
      await createAccount(email.trim(), passphrase, role)
      setNotice({ kind: 'ok', text: tr('acctCreated') })
      setEmail('')
      setPassphrase('')
      await reload()
    } catch (err) {
      const map: Record<string, StringKey> = {
        role_escalation: 'acctCannotGrant',
        validation_failed: 'acctValidationFailed',
        last_admin: 'acctLastAdmin',
      }
      const key = err instanceof AccountApiError ? map[err.code] : undefined
      const text =
        key ? tr(key) : err instanceof AccountApiError ? err.message : tr('acctCreateFailed')
      setNotice({ kind: 'err', text })
    } finally {
      setBusy(false)
    }
  }

  const toggle = async (row: AccountRow) => {
    setBusy(true)
    setNotice(null)
    try {
      await setDisabled(row.id, !row.disabled)
      setNotice({ kind: 'ok', text: tr('acctUpdated') })
      await reload()
    } catch (err) {
      const text =
        err instanceof AccountApiError && err.code === 'last_admin'
          ? tr('acctLastAdmin')
          : err instanceof AccountApiError && err.code === 'role_escalation'
            ? tr('acctCannotManage')
            : tr('acctUpdateFailed')
      setNotice({ kind: 'err', text })
    } finally {
      setBusy(false)
    }
  }

  const submitReset = async (row: AccountRow) => {
    setBusy(true)
    setNotice(null)
    try {
      await resetPassphrase(row.id, resetValue)
      setNotice({ kind: 'ok', text: tr('acctPassphraseReset') })
      setResetFor(null)
      setResetValue('')
      await reload()
    } catch (err) {
      const map: Record<string, StringKey> = {
        last_admin: 'acctLastAdmin',
        role_escalation: 'acctCannotManage',
        validation_failed: 'acctValidationFailed',
      }
      const key = err instanceof AccountApiError ? map[err.code] : undefined
      setNotice({ kind: 'err', text: key ? tr(key) : tr('acctUpdateFailed') })
    } finally {
      setBusy(false)
    }
  }

  const canCreate = load.state === 'ready' ? load.data.can_create : []

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
        {tr('acctTitle')}
      </h2>
      <p style={{ margin: '0 0 12px', fontSize: 12, color: tokens.muted }}>
        {tr('acctExplain')}
      </p>

      {load.state === 'loading' && (
        <p style={{ fontSize: 13, color: tokens.muted }}>{tr('acctLoading')}</p>
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

      {notice && (
        <p
          role={notice.kind === 'err' ? 'alert' : 'status'}
          style={{
            background: notice.kind === 'ok' ? tokens.okBg : tokens.dangerBg,
            color: notice.kind === 'ok' ? tokens.okFg : tokens.dangerFg,
            padding: '9px 12px',
            borderRadius: 8,
            fontSize: 13,
            margin: '0 0 12px',
          }}
        >
          {notice.text}
        </p>
      )}

      {load.state === 'ready' && (
        <>
          {/* ---- counts, from real rows ---- */}
          <div
            style={{
              display: 'flex',
              gap: 8,
              flexWrap: 'wrap',
              marginBottom: 14,
              fontSize: 12,
              color: tokens.navy700,
            }}
          >
            {['admin', 'publisher', 'operator', 'viewer', 'public'].map((r) => (
              <span
                key={r}
                style={{
                  background: tokens.surfaceAlt,
                  border: `1px solid ${tokens.border}`,
                  borderRadius: 999,
                  padding: '3px 10px',
                }}
              >
                {tr(ROLE_KEY[r] ?? 'acctRolePublic')}: <strong>{load.data.stats[r] ?? 0}</strong>
              </span>
            ))}
            {load.data.stats.disabled > 0 && (
              <span
                style={{
                  background: tokens.warnBg,
                  color: tokens.warnFg,
                  border: `1px solid ${tokens.warnFg}`,
                  borderRadius: 999,
                  padding: '3px 10px',
                }}
              >
                {tr('acctDisabledCount')}: <strong>{load.data.stats.disabled}</strong>
              </span>
            )}
          </div>

          {/* ---- create form ---- */}
          {canCreate.length > 0 ? (
            <div
              style={{
                border: `1px solid ${tokens.border}`,
                borderRadius: 10,
                padding: 14,
                marginBottom: 16,
                background: tokens.surfaceAlt,
              }}
            >
              <h3 style={{ margin: '0 0 10px', fontSize: 14, color: tokens.navy900 }}>
                {tr('acctCreateTitle')}
              </h3>

              <label htmlFor="acct-email" style={{ fontSize: 12, fontWeight: 600, color: tokens.navy900 }}>
                {tr('acctEmailLabel')}
              </label>
              <input
                id="acct-email"
                type="email"
                autoComplete="off"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                style={inputStyle}
              />

              <label
                htmlFor="acct-passphrase"
                style={{ fontSize: 12, fontWeight: 600, color: tokens.navy900, display: 'block', marginTop: 10 }}
              >
                {tr('acctPassphraseLabel')}
              </label>
              <input
                id="acct-passphrase"
                type="password"
                autoComplete="new-password"
                value={passphrase}
                onChange={(e) => setPassphrase(e.target.value)}
                style={inputStyle}
              />
              <p style={{ margin: '4px 0 0', fontSize: 11, color: tokens.muted }}>
                {tr('acctPassphraseHint')}
              </p>

              <label
                htmlFor="acct-role"
                style={{ fontSize: 12, fontWeight: 600, color: tokens.navy900, display: 'block', marginTop: 10 }}
              >
                {tr('acctRoleLabel')}
              </label>
              <select
                id="acct-role"
                value={role}
                onChange={(e) => setRole(e.target.value)}
                style={{ ...inputStyle, maxWidth: 320 }}
              >
                {canCreate.map((r) => (
                  <option key={r} value={r}>
                    {tr(ROLE_KEY[r] ?? 'acctRolePublic')} — {tr(ROLE_WHAT[r] ?? 'acctRoleWhatViewer')}
                  </option>
                ))}
              </select>

              <div style={{ marginTop: 12 }}>
                <button
                  type="button"
                  disabled={busy || !email.trim() || passphrase.length < 12}
                  onClick={() => void submitCreate()}
                  style={button(tokens.teal700, busy || !email.trim() || passphrase.length < 12)}
                >
                  {busy ? tr('acctWorking') : tr('acctCreateButton')}
                </button>
              </div>

              <p style={{ margin: '10px 0 0', fontSize: 11, color: tokens.muted }}>
                {tr('acctBootstrapOnly')}
              </p>
            </div>
          ) : (
            <p
              style={{
                background: tokens.surfaceAlt,
                border: `1px solid ${tokens.border}`,
                borderRadius: 8,
                padding: '10px 12px',
                fontSize: 12,
                color: tokens.muted,
              }}
            >
              {tr('acctNoGrantable')}
            </p>
          )}

          {/* ---- account table ---- */}
          <h3 style={{ margin: '0 0 8px', fontSize: 14, color: tokens.navy900 }}>
            {tr('acctExistingTitle')}
          </h3>

          {load.data.accounts.length === 0 ? (
            <p style={{ fontSize: 13, color: tokens.muted }}>{tr('acctEmpty')}</p>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ textAlign: 'left', color: tokens.muted, fontSize: 11 }}>
                    <th style={{ padding: '6px 8px' }}>{tr('acctEmailLabel')}</th>
                    <th style={{ padding: '6px 8px' }}>{tr('acctRoleLabel')}</th>
                    <th style={{ padding: '6px 8px' }}>{tr('acctCreatedLabel')}</th>
                    <th style={{ padding: '6px 8px' }}>{tr('acctLastActiveLabel')}</th>
                    <th style={{ padding: '6px 8px' }}>{tr('acctStateLabel')}</th>
                    <th style={{ padding: '6px 8px' }}>{tr('acctActionsLabel')}</th>
                  </tr>
                </thead>
                <tbody>
                  {load.data.accounts.map((a) => (
                    <tr key={a.id} style={{ borderTop: `1px solid ${tokens.border}` }}>
                      <td style={{ padding: '8px' }}>
                        <div style={{ fontWeight: 600, color: tokens.navy900 }}>{a.email}</div>
                        {session?.id === a.id && (
                          <div style={{ fontSize: 11, color: tokens.teal700 }}>
                            {tr('acctThisIsYou')}
                          </div>
                        )}
                      </td>
                      <td style={{ padding: '8px' }}>{tr(ROLE_KEY[a.role] ?? 'acctRolePublic')}</td>
                      <td style={{ padding: '8px', color: tokens.muted, fontSize: 12 }}>
                        {formatTime(a.created_at, locale)}
                      </td>
                      <td style={{ padding: '8px', color: tokens.muted, fontSize: 12 }}>
                        {formatTime(a.last_active_at, locale)}
                      </td>
                      <td style={{ padding: '8px' }}>
                        <span
                          style={{
                            display: 'inline-block',
                            padding: '2px 8px',
                            borderRadius: 999,
                            fontSize: 11,
                            fontWeight: 700,
                            background: a.disabled ? tokens.warnBg : tokens.okBg,
                            color: a.disabled ? tokens.warnFg : tokens.okFg,
                            border: `1px solid ${a.disabled ? tokens.warnFg : tokens.okFg}`,
                          }}
                        >
                          {/* Word, never colour alone. */}
                          {a.disabled ? tr('acctDisabled') : tr('acctActive')}
                        </span>
                      </td>
                      <td style={{ padding: '8px' }}>
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => void toggle(a)}
                            style={button(a.disabled ? tokens.teal700 : tokens.navy700, busy)}
                          >
                            {a.disabled ? tr('acctEnable') : tr('acctDisable')}
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => {
                              setResetFor(resetFor === a.id ? null : a.id)
                              setResetValue('')
                            }}
                            style={button(tokens.muted, busy)}
                          >
                            {tr('acctResetPassphrase')}
                          </button>
                        </div>

                        {resetFor === a.id && (
                          <div style={{ marginTop: 8 }}>
                            <label
                              htmlFor={`reset-${a.id}`}
                              style={{ fontSize: 11, color: tokens.muted }}
                            >
                              {tr('acctNewPassphraseLabel')}
                            </label>
                            <input
                              id={`reset-${a.id}`}
                              type="password"
                              autoComplete="new-password"
                              value={resetValue}
                              onChange={(e) => setResetValue(e.target.value)}
                              style={{ ...inputStyle, maxWidth: 260 }}
                            />
                            <div style={{ marginTop: 6 }}>
                              <button
                                type="button"
                                disabled={busy || resetValue.length < 12}
                                onClick={() => void submitReset(a)}
                                style={button(tokens.teal700, busy || resetValue.length < 12)}
                              >
                                {tr('acctConfirmReset')}
                              </button>
                            </div>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ---- disclosures ---- */}
          <ul style={{ margin: '14px 0 0', paddingLeft: 18, fontSize: 11, color: tokens.muted }}>
            {load.data.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
