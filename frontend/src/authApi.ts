/**
 * Auth and SMS API client.
 *
 * SECURITY NOTES THAT DRIVE THIS FILE
 *   * The session lives in an httpOnly cookie set by the server, so this code never sees or
 *     stores the token. Nothing here writes to localStorage: a token in localStorage is readable
 *     by any XSS, and the cookie is not.
 *   * `credentials: 'same-origin'` is required so the cookie is sent. The browser talks to the
 *     Vite dev server, which proxies /api to FastAPI, so this is same-origin and no CORS
 *     credential negotiation is involved.
 *   * The client NEVER decides authorisation. `is_admin` from the server is used only to decide
 *     whether to *render* admin UI; the server re-checks every call. A user who forges a
 *     response in devtools sees a broken panel, not data.
 */

import type { ApiError } from './api'

export type Role = 'public' | 'viewer' | 'operator' | 'publisher' | 'admin'

export interface Session {
  id: string
  email: string
  role: Role
  is_admin: boolean
  phone: string | null
  sms_opt_in: boolean
}

export interface ConsentHistoryEntry {
  action: 'opt_in' | 'opt_out'
  phone: string | null
  source: string
  at: string
}

export interface GatewayInfo {
  configured: boolean
  base_url_set: boolean
  username_set: boolean
  password_set: boolean
  device_id_set: boolean
  mode: 'live' | 'dry_run'
  required_env: string[]
  optional_env: string[]
  scopes_requested: string[]
}

export interface ConsentState {
  sms_opt_in: boolean
  phone: string | null
  history: ConsentHistoryEntry[]
  gateway?: GatewayInfo
}

export interface DeliveryMessage {
  id: string
  alert_id: string | null
  phone: string
  state: string
  provider_state: string | null
  error_code: string | null
  dry_run: boolean
  created_at: string
  updated_at: string
}

export interface AlertRow {
  id: string
  title_en: string
  severity: string
  area: string
  status: string
  is_demo: number
  created_at: string
  sent_at: string | null
}

export interface SendResult {
  alert_id: string
  dry_run: boolean
  attempted: number
  accepted: number
  failed: number
  skipped_rate_limited: number
  states: Record<string, number>
  recipients: {
    message_id: string
    phone: string
    state: string
    dry_run: boolean
    error_code: string | null
  }[]
}

export class HttpError extends Error {
  status: number
  detail: unknown
  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail))
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })
  if (res.status === 204) return undefined as T
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    body = null
  }
  if (!res.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in (body as Record<string, unknown>)
        ? (body as Record<string, unknown>).detail
        : `HTTP ${res.status}`
    throw new HttpError(res.status, detail)
  }
  return body as T
}

/** Human-readable message for an error, preferring the server's structured detail. */
export function errorMessage(err: unknown, locale: 'en' | 'es'): string {
  if (err instanceof HttpError) {
    const d = err.detail
    if (d && typeof d === 'object' && 'message' in (d as Record<string, unknown>)) {
      return String((d as Record<string, unknown>).message)
    }
    if (typeof d === 'string') return d
    if (err.status === 401) return locale === 'es' ? 'Inicie sesión para continuar.' : 'Sign in to continue.'
    if (err.status === 403) return locale === 'es' ? 'No tiene permiso para esta acción.' : 'You do not have permission for this action.'
    if (err.status === 429) return locale === 'es' ? 'Demasiados intentos. Espere un momento.' : 'Too many attempts. Wait a moment.'
    return `HTTP ${err.status}`
  }
  const e = err as ApiError
  return e?.message ?? (locale === 'es' ? 'Error de red.' : 'Network error.')
}

/* ------------------------------------------------------------------ */
/* Auth                                                               */
/* ------------------------------------------------------------------ */

export const register = (email: string, password: string) =>
  request<Session>('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })

export const login = (email: string, password: string) =>
  request<Session>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })

export const logout = () => request<void>('/api/auth/logout', { method: 'POST' })

export const me = () => request<Session>('/api/auth/me')

/* ------------------------------------------------------------------ */
/* Consent                                                            */
/* ------------------------------------------------------------------ */

export const getConsent = () => request<ConsentState>('/api/sms/consent')

export const setConsent = (optIn: boolean, phone?: string) =>
  request<ConsentState>('/api/sms/consent', {
    method: 'POST',
    body: JSON.stringify(optIn ? { opt_in: true, phone } : { opt_in: false }),
  })

/* ------------------------------------------------------------------ */
/* Admin                                                              */
/* ------------------------------------------------------------------ */

export const adminStatus = () =>
  request<{
    actor: Session
    gateway: GatewayInfo
    delivery: Record<string, number>
    recipients_opted_in: number
  }>('/api/admin/status')

export const adminAlerts = () => request<{ alerts: AlertRow[] }>('/api/admin/alerts')

export const adminDelivery = () =>
  request<{ summary: Record<string, number>; messages: DeliveryMessage[]; gateway_mode: string }>(
    '/api/admin/delivery',
  )

export const adminAudit = () =>
  request<{ entries: { actor_role: string | null; action: string; subject: string | null; detail: string | null; at: string }[] }>(
    '/api/admin/audit',
  )

export const createAlert = (payload: {
  title_en: string
  title_es: string
  body_en: string
  body_es: string
  severity: string
  area: string
  idempotency_key?: string
}) =>
  request<AlertRow>('/api/admin/alerts', { method: 'POST', body: JSON.stringify(payload) })

export const approveAlert = (id: string) =>
  request<AlertRow>(`/api/admin/alerts/${id}/approve`, { method: 'POST' })

export const sendAlert = (id: string, language: 'en' | 'es') =>
  request<SendResult>(`/api/admin/alerts/${id}/send?confirm=true&language=${language}`, {
    method: 'POST',
  })

export const testSms = (to: string, confirm: boolean) =>
  request<{
    dry_run: boolean
    state: string
    provider_id: string | null
    provider_state: string | null
    error_code: string | null
    error_message: string | null
    to: string
  }>('/api/admin/test-sms', {
    method: 'POST',
    body: JSON.stringify({ to, confirm }),
  })
