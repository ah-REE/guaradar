/**
 * Client for the community road-report API (features A–E).
 *
 * DESIGN NOTES THAT MATTER
 *   * Every mutation sends `credentials: 'same-origin'` so the httpOnly session cookie goes
 *     with it. The client never sees or stores a token.
 *   * `state` and `is_stale` come from the SERVER. This client does not decide what a report
 *     means: if the backend says a report is stale, the UI renders stale. Recomputing a
 *     freshness judgement in the browser would create a second, drifting source of truth for
 *     a safety-relevant label.
 *   * Nothing here builds a claim that a road is safe. The vocabulary is fixed and narrow on
 *     purpose, matching the backend's.
 *   * Image upload uses FormData with the raw `File`, not base64. Base64 inflates a photo by
 *     about a third and the brief explicitly asks that large images not be embedded.
 */

import type { LatLon } from './routeApi'

export type ReportCategory =
  | 'flooded'
  | 'blocked'
  | 'debris'
  | 'damaged'
  | 'rising'
  | 'other'

export const REPORT_CATEGORIES: ReportCategory[] = [
  'flooded',
  'blocked',
  'debris',
  'damaged',
  'rising',
  'other',
]

/** Public states. `stale` is a presentation state derived on the server, never stored. */
export type ReportState =
  | 'unverified'
  | 'potential_hazard'
  | 'blocked_verified'
  | 'passable_verified'
  | 'inconclusive'
  | 'rejected'
  | 'stale'
  | 'unknown'

export type Decision =
  | 'unverified'
  | 'potential_hazard'
  | 'blocked_verified'
  | 'passable_verified'
  | 'inconclusive'
  | 'rejected'

export interface PublicReport {
  id: string
  category: ReportCategory
  description: string | null
  lat: number
  lon: number
  location_is_snapped: boolean
  road_segment_id: number | null
  state: ReportState
  decision: Decision
  is_stale: boolean
  submitted_at: string
  verified_at: string | null
  last_confirmed_at: string | null
  expires_at: string
  confirm_count: number
  challenge_count: number
  has_image: boolean
  image_url: string | null
  seeded: boolean
}

export interface AdminReport extends PublicReport {
  user_id: string
  gps_lat: number
  gps_lon: number
  gps_accuracy_m: number | null
  gps_source: 'device' | 'manual' | 'map'
  snap_distance_m: number | null
  decided_by: string | null
  decided_at: string | null
  decision_note: string | null
}

export interface ReportList {
  schema_version: string
  reports: PublicReport[]
  count: number
  limit: number
  notes: string[]
}

export interface CreateReportResult {
  report: PublicReport
  messages: string[]
}

export interface AuditEntry {
  action: string
  actor_id: string | null
  actor_role: string | null
  from_state: string | null
  to_state: string | null
  detail: string | null
  at: string
}

export interface ReportHistory {
  report_id: string
  entries: AuditEntry[]
  effective_status: string | null
}

export interface EffectiveStatus {
  segments_with_reports: number
  segments_closed: number
  segments_with_stale_closure: number
  conflicts: string[]
  stale_after_minutes: number
}

/**
 * A structured API failure.
 *
 * `code` is the machine-readable identifier the backend returns (for example
 * `image_too_large`, `rate_limited`). The UI maps codes to translated sentences, so a new
 * backend code degrades to a generic message instead of showing raw server text.
 */
export class ReportApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ReportApiError'
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, { credentials: 'same-origin', ...init })
  } catch {
    // A network failure is distinct from a server rejection and must not be shown as one.
    throw new ReportApiError(0, 'network_error', 'Could not reach the server.')
  }
  if (!res.ok) {
    let code = `http_${res.status}`
    let message = res.statusText || 'Request failed.'
    try {
      const body = await res.json()
      const detail = body?.detail
      if (typeof detail === 'string') {
        message = detail
      } else if (detail && typeof detail === 'object') {
        code = String(detail.code ?? code)
        message = String(detail.message ?? message)
      }
    } catch {
      // Non-JSON error body: keep the status-derived code rather than guessing.
    }
    throw new ReportApiError(res.status, code, message)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/* ------------------------------------------------------------------ */
/* Reads                                                              */
/* ------------------------------------------------------------------ */

export async function fetchReports(opts?: {
  bbox?: { minLat: number; minLon: number; maxLat: number; maxLon: number }
  limit?: number
  sinceHours?: number
}): Promise<ReportList> {
  const params = new URLSearchParams()
  if (opts?.bbox) {
    const { minLat, minLon, maxLat, maxLon } = opts.bbox
    params.set('bbox', [minLat, minLon, maxLat, maxLon].join(','))
  }
  if (opts?.limit !== undefined) params.set('limit', String(opts.limit))
  if (opts?.sinceHours !== undefined) params.set('since_hours', String(opts.sinceHours))
  const qs = params.toString()
  return request<ReportList>(`/api/reports${qs ? `?${qs}` : ''}`)
}

export async function fetchReport(id: string): Promise<PublicReport> {
  return request<PublicReport>(`/api/reports/${encodeURIComponent(id)}`)
}

/* ------------------------------------------------------------------ */
/* Mutations                                                          */
/* ------------------------------------------------------------------ */

export interface CreateReportInput {
  category: ReportCategory
  at: LatLon
  accuracyM: number | null
  gpsSource: 'device' | 'manual' | 'map'
  description: string
  image: File
}

export async function createReport(input: CreateReportInput): Promise<CreateReportResult> {
  const form = new FormData()
  form.set('category', input.category)
  form.set('lat', String(input.at.lat))
  form.set('lon', String(input.at.lon))
  form.set('gps_source', input.gpsSource)
  if (input.accuracyM !== null) form.set('accuracy_m', String(input.accuracyM))
  if (input.description.trim()) form.set('description', input.description.trim())
  // The filename is sent but never stored or echoed by the server; the stored identifier is
  // generated server-side.
  form.set('image', input.image, input.image.name || 'photo.jpg')

  return request<CreateReportResult>('/api/reports', { method: 'POST', body: form })
}

export async function confirmReport(
  id: string,
  kind: 'confirm' | 'challenge',
): Promise<{ report_id: string; outcome: string; confirm_count: number; challenge_count: number; note: string }> {
  return request(`/api/reports/${encodeURIComponent(id)}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind }),
  })
}

/* ------------------------------------------------------------------ */
/* Admin                                                              */
/* ------------------------------------------------------------------ */

export async function fetchAdminReports(opts?: {
  pendingOnly?: boolean
  limit?: number
}): Promise<AdminReport[]> {
  const params = new URLSearchParams()
  if (opts?.pendingOnly) params.set('pending_only', 'true')
  if (opts?.limit !== undefined) params.set('limit', String(opts.limit))
  const qs = params.toString()
  return request<AdminReport[]>(`/api/admin/reports${qs ? `?${qs}` : ''}`)
}

export async function decideReport(
  id: string,
  decision: Exclude<Decision, 'unverified'>,
  note?: string,
): Promise<AdminReport> {
  return request<AdminReport>(`/api/admin/reports/${encodeURIComponent(id)}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, note: note?.trim() || null }),
  })
}

export async function fetchReportHistory(id: string): Promise<ReportHistory> {
  return request<ReportHistory>(`/api/admin/reports/${encodeURIComponent(id)}/history`)
}

export async function fetchEffectiveStatus(): Promise<EffectiveStatus> {
  return request<EffectiveStatus>('/api/admin/reports/effective-status')
}

/* ------------------------------------------------------------------ */
/* Presentation helpers                                               */
/* ------------------------------------------------------------------ */

/**
 * Which i18n key describes a state.
 *
 * A total mapping rather than a chain of conditionals, so adding a backend state without
 * adding a label becomes a type error instead of a silently blank chip.
 */
export const STATE_LABEL_KEY = {
  unverified: 'reportStatusUnverified',
  potential_hazard: 'reportStatusPotential',
  blocked_verified: 'reportStatusBlocked',
  passable_verified: 'reportStatusPassable',
  inconclusive: 'reportStatusInconclusive',
  rejected: 'reportStatusRejected',
  stale: 'reportStatusStale',
  unknown: 'reportStatusUnknown',
} as const

/**
 * Visual tone per state. Colour is never the only channel — the chip always carries a word and
 * a shape, because a colour-blind user on a cracked phone screen in the rain is the actual user.
 */
export const STATE_TONE: Record<ReportState, 'danger' | 'warn' | 'ok' | 'muted' | 'info'> = {
  unverified: 'warn',
  potential_hazard: 'warn',
  blocked_verified: 'danger',
  passable_verified: 'ok',
  inconclusive: 'info',
  rejected: 'muted',
  stale: 'muted',
  unknown: 'muted',
}
