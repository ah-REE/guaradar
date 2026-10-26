/**
 * Typed API client.
 *
 * The types mirror backend/app/api/models.py. They are hand-written rather than generated
 * because the surface is three endpoints and a generator would add a build step for little
 * benefit at this size.
 *
 * Deliberate design points:
 *  - `fetchWithTimeout` so a hung API shows the error state instead of an infinite spinner.
 *  - No fallback fixtures. A failed request yields an error, never demo values dressed up
 *    as live ones.
 *  - No credentials, no cookies: `credentials: 'omit'` makes that explicit.
 */

export type Chip = 'verified' | 'reported' | 'estimated' | 'stale' | 'no_data'
export type DataMode = 'LIVE' | 'SIMULATED' | 'MIXED'

export interface SourceRef {
  name: string
  model_run_at: string | null
}

export interface Provenance {
  chip: Chip
  fetched_at: string | null
  stale_after_s: number | null
  simulated: boolean
  data_mode: DataMode
  sources: SourceRef[]
  notes: string[]
}

export interface HourlyRain {
  at: string
  precipitation_mm: number | null
  probability_pct: number | null
  kind: 'forecast' | 'observation'
}

export interface ForecastResponse {
  ok: boolean
  hours: HourlyRain[]
  total_mm: number
  max_hourly_mm: number | null
  units: string
  provider_units_original: string | null
  latitude: number | null
  longitude: number | null
  error: string | null
  summary: string
  provenance: Provenance
}

export interface SensorReading {
  sensor_id: string
  depth_m: number
  observed_at: string
  threshold_m: number
  fraction_of_threshold: number
  above_threshold: boolean
  simulated: true
  label: 'SIMULATED'
}

export interface Sensor {
  sensor_id: string
  sector_id: string
  profile: string
  lat: number
  lon: number
  threshold_m: number
  health: 'ok' | 'degraded' | 'offline'
  last_reading_age_s: number | null
  latest: SensorReading | null
  simulated: true
  label: 'SIMULATED'
  notes: string[]
}

export interface SensorsResponse {
  sensors: Sensor[]
  available: boolean
  any_offline: boolean
  simulated: true
  provenance: Provenance
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly kind: 'network' | 'http' | 'malformed' | 'timeout',
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

const DEFAULT_TIMEOUT_MS = 8000

export function apiBaseUrl(): string {
  // Default: SAME ORIGIN (empty base), so requests go to `/api/...` on whatever origin served
  // the page. In dev, Vite proxies that to the FastAPI server (see vite.config.ts), which
  // avoids a cross-origin request entirely. In production the API is expected to be served
  // behind the same origin.
  //
  // Override with VITE_API_BASE_URL only when the API genuinely lives elsewhere, e.g.
  // http://127.0.0.1:8000. An absolute override re-introduces CORS, so it is not the default.
  const env = (import.meta as unknown as { env?: Record<string, string> }).env
  const fromEnv = env?.VITE_API_BASE_URL
  return fromEnv && fromEnv.length > 0 ? fromEnv : ''
}

async function fetchWithTimeout(url: string, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, {
      method: 'GET',
      credentials: 'omit',
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError('Request timed out', 'timeout')
    }
    throw new ApiError('Network request failed', 'network')
  } finally {
    clearTimeout(timer)
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetchWithTimeout(`${apiBaseUrl()}${path}`)
  if (!res.ok) {
    throw new ApiError(`API returned ${res.status}`, 'http')
  }
  try {
    return (await res.json()) as T
  } catch {
    throw new ApiError('Response was not valid JSON', 'malformed')
  }
}

/**
 * Validates just enough shape to avoid rendering nonsense. Deliberately shallow: the
 * backend is typed, and a heavy runtime schema would duplicate it.
 */
function assertProvenance(value: unknown, where: string): asserts value is Provenance {
  if (typeof value !== 'object' || value === null) {
    throw new ApiError(`Missing provenance in ${where}`, 'malformed')
  }
  const p = value as Partial<Provenance>
  if (typeof p.chip !== 'string' || typeof p.data_mode !== 'string') {
    throw new ApiError(`Malformed provenance in ${where}`, 'malformed')
  }
}

export async function fetchForecast(hours = 24): Promise<ForecastResponse> {
  const data = await getJson<ForecastResponse>(`/api/public/forecast?hours=${hours}`)
  assertProvenance(data.provenance, 'forecast')
  if (!Array.isArray(data.hours)) {
    throw new ApiError('Malformed forecast hours', 'malformed')
  }
  return data
}

export async function fetchSensors(count = 6): Promise<SensorsResponse> {
  const data = await getJson<SensorsResponse>(`/api/public/sensors?count=${count}`)
  assertProvenance(data.provenance, 'sensors')
  if (!Array.isArray(data.sensors)) {
    throw new ApiError('Malformed sensor list', 'malformed')
  }
  return data
}
