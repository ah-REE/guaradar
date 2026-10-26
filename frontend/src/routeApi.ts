/**
 * Route types and client for GET /api/public/route.
 *
 * Field names mirror backend/app/api/route_models.py. `schema_version` is checked so an
 * unfamiliar shape is refused rather than misread.
 */

export interface LatLon {
  lat: number
  lon: number
}

export type HazardClass = 'clear' | 'hazard_crossing'
export type Band = 'high' | 'moderate' | 'low' | 'none'
export type Classification = 'eligible' | 'marginal' | 'hazard_crossing'
export type LegStatus = 'open' | 'affected' | 'closed' | 'unknown'

export interface RouteLeg {
  from: LatLon
  to: LatLon
  length_m: number
  status: LegStatus
  verified: boolean
  synthetic: boolean
}

export interface Route {
  id: string
  rank: number
  geometry: LatLon[]
  distance_m: number
  duration_s: number
  hazard_class: HazardClass
  classification: Classification
  coverage_pct: number
  band: Band
  recommended: boolean
  warnings: string[]
  label: string
  legs: RouteLeg[]
  phase: 1 | 2
  mean_elevation_m: number | null
  elevation_used_as_tiebreak: boolean
  synthetic: boolean
  notes: string[]
}

export interface RouteResponse {
  schema_version: string
  routes: Route[]
  refused: boolean
  refusal_reason: string | null
  all_routes_hazard_crossing: boolean
  best_available_is_uncertain: boolean
  snap_from_m: number | null
  snap_to_m: number | null
  synthetic: boolean
  provenance: {
    chip: string
    fetched_at: string | null
    simulated: boolean
    data_mode: string
    notes: string[]
  }
  notes: string[]
  // Which status profile produced this result, and whether it is a demo fixture.
  status_profile?: StatusProfile
  profile_is_demo_fixture?: boolean
  status_source?: string
  status_records_matched?: number
  // Community-report overlay. Optional because an older server omits them; absent must render
  // as "unknown", never as "no reports" — the two mean different things.
  report_overlay_applied?: boolean
  report_segments_affected?: number
  report_closures?: number
  report_stale_closures?: number
}

export class RouteError extends Error {
  constructor(
    message: string,
    readonly kind: 'network' | 'http' | 'malformed' | 'timeout',
  ) {
    super(message)
    this.name = 'RouteError'
  }
}

const SUPPORTED_SCHEMA = '1'

export function routeUrlBase(): string {
  // Same-origin by default, matching api.ts. Dev requests are proxied by Vite to FastAPI.
  const env = (import.meta as unknown as { env?: Record<string, string> }).env
  const fromEnv = env?.VITE_API_BASE_URL
  return fromEnv && fromEnv.length > 0 ? fromEnv : ''
}

async function getJson(path: string, timeoutMs = 10000): Promise<unknown> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(`${routeUrlBase()}${path}`, {
      method: 'GET',
      credentials: 'omit',
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })
    if (!res.ok) throw new RouteError(`API returned ${res.status}`, 'http')
    return await res.json()
  } catch (err) {
    if (err instanceof RouteError) throw err
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new RouteError('Request timed out', 'timeout')
    }
    throw new RouteError('Network request failed', 'network')
  } finally {
    clearTimeout(timer)
  }
}

export type StatusProfile = 'baseline' | 'demo_clear'

export async function fetchRoute(
  from: LatLon,
  to: LatLon,
  alternatives = 3,
  profile: StatusProfile = 'baseline',
): Promise<RouteResponse> {
  const q = new URLSearchParams({
    from_lat: from.lat.toFixed(6),
    from_lon: from.lon.toFixed(6),
    to_lat: to.lat.toFixed(6),
    to_lon: to.lon.toFixed(6),
    alternatives: String(alternatives),
    // Always sent explicitly so the request states which scenario it asked for. The backend
    // still defaults to 'baseline' and still rejects an unknown value with HTTP 422.
    profile,
  })
  const data = (await getJson(`/api/public/route?${q.toString()}`)) as Partial<RouteResponse>

  if (typeof data !== 'object' || data === null) {
    throw new RouteError('Response was not an object', 'malformed')
  }
  if (data.schema_version !== SUPPORTED_SCHEMA) {
    // Refuse to guess at an unfamiliar contract.
    throw new RouteError(
      `Unsupported route schema version ${String(data.schema_version)}`,
      'malformed',
    )
  }
  if (!Array.isArray(data.routes)) {
    throw new RouteError('Malformed route list', 'malformed')
  }
  return data as RouteResponse
}
