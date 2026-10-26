/**
 * Admin data derivation (Stage 2 §13, §9, §10) — READ-ONLY.
 *
 * THE HARD CONSTRAINT
 *   The backend exposes exactly three public GET routes (forecast, sensors, route) plus health.
 *   There is no `/api/admin/*`, no incidents table, no alerts API, no shelters API, and no
 *   mutation verb anywhere (`rg "@app\.(post|put|patch|delete)"` -> none).
 *
 *   So this module cannot "load incidents". Inventing a fetch that returns fixtures would be
 *   fabricating records, which the brief forbids outright. Instead it derives what is genuinely
 *   knowable from responses the backend really returns, and every panel states plainly where its
 *   numbers come from and what is missing.
 *
 * WHAT IS DERIVABLE, AND WHAT IS NOT
 *
 *   Road status  — REAL, but SAMPLED. A route response's legs each carry `status` and `verified`
 *                  for an actual graph edge. Requesting several routes therefore samples real
 *                  edges and lets us count open/affected/closed/unknown. It is a SAMPLE of the
 *                  edges those routes happen to use, not a census of the network: 24,943 edges
 *                  exist and a handful of routes touch a few thousand at most. The panel says so
 *                  and shows the sample size, because a count presented as a census is a lie.
 *
 *   Incidents    — NOT AVAILABLE. No endpoint, no table. Rendered as an honest empty state.
 *   Alerts       — NOT AVAILABLE. Same.
 *   Shelters     — NOT AVAILABLE. Same.
 *
 * WHY ROUTE REQUESTS ARE THE SOURCE
 *   `status_source: "seed_generator"` is what the API actually reports for these results, and the
 *   panel repeats that verbatim rather than upgrading it to "live". When persistence is enabled
 *   the same field would read differently, and the panel would follow it automatically.
 */

import type { RouteResponse } from './routeApi'

export type EdgeStatusValue = 'open' | 'affected' | 'closed' | 'unknown'

export interface StatusTally {
  open: number
  affected: number
  closed: number
  unknown: number
  total: number
}

export interface DerivedStatusSample {
  tally: StatusTally
  /** Edges whose status was confirmed, i.e. verified coverage within the sample. */
  verifiedEdges: number
  verifiedPct: number
  /** How many route responses were sampled, so the panel can state its own scope. */
  routesSampled: number
  /** Verbatim from the API, never upgraded by the UI. */
  statusSource: string | null
  statusRecordsMatched: number
  /** Which profile produced this sample. */
  profile: string
  dataMode: string | null
  fetchedAt: string | null
}

const EMPTY: StatusTally = { open: 0, affected: 0, closed: 0, unknown: 0, total: 0 }

/** Accumulate every leg's status across a set of route responses. */
export function deriveStatusSample(
  responses: RouteResponse[],
  profile: string,
): DerivedStatusSample {
  const tally: StatusTally = { ...EMPTY }
  let verified = 0
  let sampled = 0

  for (const res of responses) {
    if (!res || res.refused || !res.routes) continue
    sampled += 1
    for (const route of res.routes) {
      for (const leg of route.legs ?? []) {
        const key = (leg.status ?? 'unknown') as EdgeStatusValue
        if (key === 'open' || key === 'affected' || key === 'closed' || key === 'unknown') {
          tally[key] += 1
        } else {
          // An unrecognised status string from the API counts as unknown, never as open.
          tally.unknown += 1
        }
        if (leg.verified) verified += 1
        tally.total += 1
      }
    }
  }

  const first = responses.find((r) => r && !r.refused)
  return {
    tally,
    verifiedEdges: verified,
    verifiedPct: tally.total === 0 ? 0 : (verified / tally.total) * 100,
    routesSampled: sampled,
    statusSource: first?.status_source ?? null,
    statusRecordsMatched: first?.status_records_matched ?? 0,
    profile,
    dataMode: first?.provenance?.data_mode ?? null,
    fetchedAt: first?.provenance?.fetched_at ?? null,
  }
}

/**
 * The six demo points, used to build a spread of routes so the sample is not one corridor.
 *
 * Duplicated from RouteScreen deliberately: this is a data-gathering helper, and importing a
 * component module into it would couple the admin view to the route form's internals.
 */
export const SAMPLE_POINTS: { id: string; lat: number; lon: number }[] = [
  { id: 'SIM-01', lat: -2.142763, lon: -79.905598 },
  { id: 'SIM-02', lat: -2.149230, lon: -79.901801 },
  { id: 'SIM-03', lat: -2.196117, lon: -79.886222 },
  { id: 'SIM-04', lat: -2.220429, lon: -79.908965 },
  { id: 'SIM-05', lat: -2.227579, lon: -79.914710 },
  { id: 'SIM-06', lat: -2.157834, lon: -79.889898 },
]

/**
 * Pairs chosen to cross the extract rather than cluster in one sector, giving a less biased
 * sample than six near-neighbours would. (from index, to index)
 */
export const SAMPLE_PAIRS: [number, number][] = [
  [0, 3],
  [2, 5],
  [1, 4],
  [0, 5],
]

/**
 * A capability the admin panel must NOT pretend to have.
 *
 * Every write action in the approved Stage 2 spec is listed here with the reason it is disabled,
 * so the UI renders a disabled control WITH its explanation rather than a button that silently
 * does nothing (or worse, appears to succeed).
 */
export interface DisabledAction {
  id: string
  labelEn: string
  labelEs: string
  reasonEn: string
  reasonEs: string
}

export const DISABLED_ACTIONS: DisabledAction[] = [
  {
    id: 'publish_alert',
    labelEn: 'Publish alert',
    labelEs: 'Publicar alerta',
    reasonEn:
      'No alerts table or endpoint exists. The approved design (Stage 2 §8) requires a draft → review → publish flow with a bilingual hard block, none of which is built.',
    reasonEs:
      'No existe tabla ni endpoint de alertas. El diseño aprobado (Etapa 2 §8) exige un flujo borrador → revisión → publicación con bloqueo bilingüe obligatorio, nada de lo cual está construido.',
  },
  {
    id: 'verify_incident',
    labelEn: 'Verify incident',
    labelEs: 'Verificar incidente',
    reasonEn:
      'No incidents table or endpoint exists. Verification requires an append-only audit trail (Stage 2 §2), which is not implemented.',
    reasonEs:
      'No existe tabla ni endpoint de incidentes. La verificación requiere un registro de auditoría inmutable (Etapa 2 §2), que no está implementado.',
  },
  {
    id: 'set_road_status',
    labelEn: 'Set road status',
    labelEs: 'Cambiar estado de vía',
    reasonEn:
      'The API is read-only by design: there is no POST/PUT/PATCH/DELETE route. Status shown is seed/demo data.',
    reasonEs:
      'La API es de solo lectura por diseño: no hay rutas POST/PUT/PATCH/DELETE. El estado mostrado son datos de demostración.',
  },
  {
    id: 'manage_users',
    labelEn: 'Manage users and roles',
    labelEs: 'Gestionar usuarios y roles',
    reasonEn:
      'Authentication is not implemented. N-2 is open: `current_app_role()` trusts a session setting with no server-side identity verification, so granting roles would be a fiction.',
    reasonEs:
      'La autenticación no está implementada. N-2 sigue abierto: `current_app_role()` confía en un ajuste de sesión sin verificación de identidad en el servidor, por lo que asignar roles sería una ficción.',
  },
]
