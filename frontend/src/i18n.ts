/**
 * Bilingual safety strings.
 *
 * Deliberately a plain object rather than a localisation framework: the brief asked for
 * simple, and adding i18n machinery for two languages would be more surface area than
 * value in this block.
 *
 * Rules encoded here:
 *  - Every string exists in BOTH English and Spanish. The `T` type makes a missing Spanish
 *    entry a compile error, which is the cheapest possible enforcement of D22/D26 at this
 *    size.
 *  - No string claims a route is "safe", "flood-proof", "risk-free" or "guaranteed".
 *    `assertNoOverclaim` below is exercised by a test.
 */

export type Locale = 'en' | 'es'

type Pair = { en: string; es: string }

export const STRINGS = {
  appName: { en: 'Guaradar', es: 'Guaradar' },
  tagline: {
    en: 'Detect early. Navigate safely.',
    es: 'Detectar a tiempo. Circular con seguridad.',
  },
  prototypeBanner: {
    en: 'Prototype — not an official municipal service.',
    es: 'Prototipo — no es un servicio municipal oficial.',
  },

  // --- data status -------------------------------------------------------
  dataStatusTitle: { en: 'Current data status', es: 'Estado actual de los datos' },
  forecastAvailable: { en: 'Forecast available', es: 'Pronóstico disponible' },
  forecastUnavailable: { en: 'Forecast unavailable', es: 'Pronóstico no disponible' },
  forecastStale: { en: 'Forecast may be out of date', es: 'El pronóstico puede estar desactualizado' },
  source: { en: 'Source', es: 'Fuente' },
  fetchTime: { en: 'Retrieved', es: 'Obtenido' },
  modelRunTime: { en: 'Model run time', es: 'Hora de ejecución del modelo' },
  modelRunUnavailable: {
    en: 'Model run time unavailable.',
    es: 'Hora de ejecución del modelo no disponible.',
  },
  modelRunNeverInferred: {
    en: 'The provider did not supply a model run time, so none is shown. Retrieval time is not model run time.',
    es: 'El proveedor no indicó una hora de ejecución del modelo, por lo que no se muestra ninguna. La hora de obtención no es la hora de ejecución del modelo.',
  },
  totalRainfall: { en: 'Total rainfall', es: 'Lluvia total' },
  peakHourly: { en: 'Peak in one hour', es: 'Máximo en una hora' },
  forecastNotObservation: {
    en: 'These are forecast values, not measured rainfall.',
    es: 'Estos son valores de pronóstico, no lluvia medida.',
  },
  hoursShown: { en: 'hours shown', es: 'horas mostradas' },

  // --- sensors -----------------------------------------------------------
  sensorsTitle: { en: 'Water-level sensors', es: 'Sensores de nivel de agua' },
  simulatedBadge: { en: 'SIMULATED', es: 'SIMULADO' },
  simulatedExplanation: {
    en: 'All sensor readings on this page are simulated for demonstration. No real sensor telemetry exists in this project.',
    es: 'Todas las lecturas de sensores en esta página son simuladas para la demostración. En este proyecto no existe telemetría real de sensores.',
  },
  sensorFeedEmpty: {
    en: 'No sensor readings available.',
    es: 'No hay lecturas de sensores disponibles.',
  },
  healthOk: { en: 'Reading current', es: 'Lectura actual' },
  healthDegraded: { en: 'Readings late', es: 'Lecturas retrasadas' },
  healthOffline: { en: 'No recent reading', es: 'Sin lectura reciente' },
  threshold: { en: 'Prototype threshold', es: 'Umbral prototipo' },
  thresholdNote: {
    en: 'Thresholds are prototype values, not municipal flood thresholds.',
    es: 'Los umbrales son valores de prototipo, no umbrales municipales de inundación.',
  },
  depth: { en: 'Depth', es: 'Profundidad' },
  lastReading: { en: 'Last reading', es: 'Última lectura' },

  // --- limitations -------------------------------------------------------
  limitationsTitle: { en: 'Limitations and provenance', es: 'Limitaciones y procedencia' },
  syntheticGraph: {
    en: 'Road geometry comes from a bounded real OpenStreetMap extract of Guayaquil \u2014 {streets} of mapped street inside roughly {span}. That is street LENGTH inside the extract, not a share of the city; outlying districts are not included, so any coverage percentage describes this extract only. The road STATUS shown is demo seed data, not a live municipal feed.',
    es: 'La geometría vial proviene de una extracción real y acotada de OpenStreetMap de Guayaquil \u2014 {streets} de calle mapeada dentro de aproximadamente {span}. Es LONGITUD de calle dentro de la extracción, no una proporción de la ciudad; los barrios periféricos no están incluidos, por lo que cualquier porcentaje de cobertura describe únicamente esta extracción. El ESTADO de las vías son datos de demostración, no una fuente municipal en vivo.',
  },
  noRouteApi: {
    en: 'Routing IS available on the Route tab, and it runs over this extract only. A route existing in the data does not mean the road is open, passable or safe in reality.',
    es: 'El cálculo de rutas SÍ está disponible en la pestaña Ruta, y se ejecuta únicamente sobre esta extracción. Que exista una ruta en los datos no significa que la vía esté abierta, transitable o sea segura en la realidad.',
  },
  pathIsNotSafety: {
    en: 'A path existing in the data does not mean a road is safe to travel.',
    es: 'Que exista una ruta en los datos no significa que una vía sea segura para circular.',
  },
  riskNotApproved: {
    en: 'A combined risk level is not shown. The risk model is an unvalidated heuristic and its specification still has an unresolved conflict, so it is not presented as an approved safety rule.',
    es: 'No se muestra un nivel de riesgo combinado. El modelo de riesgo es una heurística no validada y su especificación aún tiene un conflicto sin resolver, por lo que no se presenta como una regla de seguridad aprobada.',
  },
  noFabricatedData: {
    en: 'No live flood map, road closures, shelter availability or official alerts are shown. None of these exist in this project yet.',
    es: 'No se muestran mapas de inundación en vivo, cierres de vías, disponibilidad de albergues ni alertas oficiales. Nada de esto existe todavía en este proyecto.',
  },

  // --- states ------------------------------------------------------------
  loading: { en: 'Loading…', es: 'Cargando…' },
  errorTitle: { en: 'Could not load data', es: 'No se pudieron cargar los datos' },
  errorBody: {
    en: 'The data service did not respond. Nothing is shown rather than showing an estimate that could be mistaken for a measurement.',
    es: 'El servicio de datos no respondió. No se muestra nada en lugar de mostrar una estimación que pudiera confundirse con una medición.',
  },
  retry: { en: 'Try again', es: 'Reintentar' },
  malformed: {
    en: 'The response could not be read.', 
    es: 'No se pudo leer la respuesta.',
  },
  unavailable: { en: 'Unavailable', es: 'No disponible' },
  languageLabel: { en: 'Español', es: 'English' },
  staleWarning: {
    en: 'This data is older than its freshness budget. Treat it as possibly out of date.',
    es: 'Estos datos superan su límite de vigencia. Considérelos posiblemente desactualizados.',
  },
  footerAttribution: {
    en: 'Forecast: Open-Meteo (CC BY 4.0). Sensors: simulated. Map data: synthetic demo.',
    es: 'Pronóstico: Open-Meteo (CC BY 4.0). Sensores: simulados. Datos de mapa: demostración sintética.',
  },

  // --- map / route (M7) -----------------------------------------------
  mapTitle: { en: 'Route check', es: 'Verificación de ruta' },
  mapNotRealStreets: {
    en: 'The lines drawn here follow real OpenStreetMap geometry for a bounded extract of Guayaquil ({streets} of mapped street). The streets are real, but the extract is not city-wide, and the road STATUS shown is demo seed data, not a live municipal feed.',
    es: 'Las líneas dibujadas siguen la geometría real de OpenStreetMap para una extracción acotada de Guayaquil ({streets} de calle mapeada). Las calles son reales, pero la extracción no cubre toda la ciudad y el ESTADO de las vías son datos de demostración, no una fuente municipal en vivo.',
  },
  mapPickPoints: {
    en: 'Choose a start and destination from the demo points below.',
    es: 'Elija un origen y un destino entre los puntos de demostración de abajo.',
  },
  mapStart: { en: 'Start', es: 'Origen' },
  mapDestination: { en: 'Destination', es: 'Destino' },
  mapFindRoute: { en: 'Check route', es: 'Verificar ruta' },
  mapLoading: { en: 'Checking route…', es: 'Verificando ruta…' },
  mapNoRoute: { en: 'No route could be calculated', es: 'No se pudo calcular ninguna ruta' },
  mapDemoPoints: { en: 'Demo points (sensor locations)', es: 'Puntos de demostración (ubicaciones de sensores)' },
  routeCoverage: { en: 'Verified coverage', es: 'Cobertura verificada' },
  routeDistance: { en: 'Distance', es: 'Distancia' },
  routeDuration: { en: 'Estimated time', es: 'Tiempo estimado' },
  routePhase: { en: 'Search phase', es: 'Fase de búsqueda' },
  routePhase1: {
    en: 'Phase 1 — searched without closed roads',
    es: 'Fase 1 — búsqueda sin vías cerradas',
  },
  routePhase2: {
    en: 'Phase 2 — no route avoids every closure, so closures were restored',
    es: 'Fase 2 — ninguna ruta evita todos los cierres, por lo que se restauraron los cierres',
  },
  routeRecommended: { en: 'Recommended', es: 'Recomendada' },
  routeNotRecommended: { en: 'Not recommended', es: 'No recomendada' },
  routeHazardCrossing: { en: 'Crosses a closed road', es: 'Cruza una vía cerrada' },
  routeLowCoverage: { en: 'Low verified coverage', es: 'Cobertura verificada baja' },
  routeWarningsTitle: { en: 'Warnings', es: 'Advertencias' },
  routeNotSafe: {
    en: 'A path existing in the data does not mean a road is safe to travel. These results describe only what the demo dataset records.',
    es: 'Que exista una ruta en los datos no significa que una vía sea segura para circular. Estos resultados describen únicamente lo que registra el conjunto de datos de demostración.',
  },
  routeEstimatedShort: {
    en: 'estimate, not live travel time',
    es: 'estimación, no tiempo real',
  },
  routeEstimatedTime: {
    en: 'Estimated assuming unimpeded travel. Not a live travel time.',
    es: 'Estimado suponiendo circulación sin obstáculos. No es un tiempo de viaje real.',
  },
  routeElevationTiebreak: {
    en: 'Position affected by an approximate terrain tie-break (SRTM 30 m, ±4 m). This does not establish that the route is safe.',
    es: 'La posición se vio afectada por un desempate de terreno aproximado (SRTM 30 m, ±4 m). Esto no establece que la ruta sea segura.',
  },
  routeUncertainBest: {
    en: 'Every available route has low or no verified coverage. None is recommended.',
    es: 'Todas las rutas disponibles tienen cobertura verificada baja o nula. No se recomienda ninguna.',
  },
  routeAllHazard: {
    en: 'No route avoids all closures. The options below each cross a closed road.',
    es: 'Ninguna ruta evita todos los cierres. Cada opción de abajo cruza una vía cerrada.',
  },
  viewList: { en: 'List view', es: 'Vista de lista' },
  viewMap: { en: 'Map view', es: 'Vista de mapa' },
  mapUnavailable: {
    en: 'The map could not be loaded. The route details are still shown below.',
    es: 'No se pudo cargar el mapa. Los detalles de la ruta se muestran igualmente abajo.',
  },

  // --- M12: demo scenario selector ------------------------------------
  scenarioLabel: { en: 'Road-status scenario', es: 'Escenario de estado de vías' },
  scenarioBaseline: {
    en: 'Baseline (default) — dense demo closures',
    es: 'Base (predeterminado) — cierres de demostración densos',
  },
  scenarioDemoClear: {
    en: 'Demo: few closures (eligible route visible)',
    es: 'Demostración: pocos cierres (ruta elegible visible)',
  },
  scenarioHelp: {
    en: 'The baseline marks about one road in twenty-nine as closed, so most cross-sector trips must cross a closure and end up in the fallback phase. The demo scenario uses only six closures so an eligible route can be shown.',
    es: 'La base marca aproximadamente una vía de cada veintinueve como cerrada, por lo que la mayoría de los trayectos entre sectores deben cruzar un cierre y terminan en la fase alternativa. El escenario de demostración usa solo seis cierres para poder mostrar una ruta elegible.',
  },
  scenarioDemoWarning: {
    en: 'DEMO SCENARIO — the closures in this scenario are simulated demonstration data, not verified real-world reports. Switch back to the baseline to see normal behaviour.',
    es: 'ESCENARIO DE DEMOSTRACIÓN — los cierres de este escenario son datos simulados de demostración, no reportes reales verificados. Vuelva a la base para ver el comportamiento normal.',
  },
  scenarioActive: { en: 'Scenario', es: 'Escenario' },

  // --- Admin panel (read-only prototype) -------------------------------
  tabStatus: { en: 'Status', es: 'Estado' },
  tabRoute: { en: 'Route', es: 'Ruta' },
  tabAdmin: { en: 'Admin', es: 'Administración' },
  adminTitle: { en: 'Admin control centre', es: 'Centro de control de administración' },
  adminPrototype: {
    en: 'PROTOTYPE — NOT AUTHORISED',
    es: 'PROTOTIPO — SIN AUTORIZACIÓN',
  },
  adminPrototypeBody: {
    en: 'This panel is a read-only prototype. Authentication is not implemented and no write action is available, so nothing here can change public data. Every control that would write is disabled and says why. Do not treat this screen as an operational console.',
    es: 'Este panel es un prototipo de solo lectura. La autenticación no está implementada y ninguna acción de escritura está disponible, por lo que nada aquí puede cambiar datos públicos. Cada control que escribiría está deshabilitado y explica por qué. No trate esta pantalla como una consola operativa.',
  },
  adminOverviewTitle: { en: 'Overview', es: 'Resumen' },
  adminRoadStatusTitle: { en: 'Road status sample', es: 'Muestra de estado de vías' },
  adminRoadStatusExplain: {
    en: 'Counts are taken from the legs of real route responses, so they describe only the edges those routes used — a sample, not the whole network. The network contains 24,943 edges; four routes cannot cover it.',
    es: 'Los recuentos provienen de los tramos de respuestas de ruta reales, por lo que describen únicamente las vías que esas rutas usaron: una muestra, no toda la red. La red contiene 24.943 tramos; cuatro rutas no pueden cubrirla.',
  },
  adminSampleSize: { en: 'Edges sampled', es: 'Tramos muestreados' },
  adminRoutesSampled: { en: 'Route responses sampled', es: 'Respuestas de ruta muestreadas' },
  adminStatusSource: { en: 'Status source reported by API', es: 'Fuente de estado según la API' },
  adminVerifiedShare: { en: 'Sample verified share', es: 'Proporción verificada de la muestra' },
  adminStatusOpen: { en: 'Open', es: 'Abierta' },
  adminStatusAffected: { en: 'Affected', es: 'Afectada' },
  adminStatusClosed: { en: 'Closed', es: 'Cerrada' },
  adminStatusUnknown: { en: 'Unknown', es: 'Desconocida' },
  adminUnknownNote: {
    en: 'Unknown means no status record exists for that edge. It is never counted as open, and it lowers the verified share rather than raising it.',
    es: 'Desconocida significa que no existe registro de estado para esa vía. Nunca se cuenta como abierta y reduce la proporción verificada en lugar de aumentarla.',
  },
  adminIncidentsTitle: { en: 'Incident review', es: 'Revisión de incidentes' },
  adminAlertsTitle: { en: 'Alert management', es: 'Gestión de alertas' },
  adminSheltersTitle: { en: 'Shelter availability', es: 'Disponibilidad de refugios' },
  adminNotAvailable: { en: 'No data source exists', es: 'No existe fuente de datos' },
  adminIncidentsEmpty: {
    en: 'There is no incidents table, endpoint or citizen-report channel in this build. Nothing can be listed, verified or rejected. A real queue would show clustered reports with capture time, depth band and location — none of which exists yet.',
    es: 'No hay tabla de incidentes, endpoint ni canal de reportes ciudadanos en esta versión. No se puede listar, verificar ni rechazar nada. Una cola real mostraría reportes agrupados con hora de captura, profundidad y ubicación, nada de lo cual existe todavía.',
  },
  adminAlertsEmpty: {
    en: 'There is no alerts table or publication endpoint. The approved flow requires bilingual content, an approval step and an append-only audit trail before an alert can reach the public — so no alert can be drafted, approved or published here.',
    es: 'No hay tabla de alertas ni endpoint de publicación. El flujo aprobado exige contenido bilingüe, un paso de aprobación y un registro de auditoría inmutable antes de que una alerta llegue al público, por lo que aquí no se puede redactar, aprobar ni publicar ninguna.',
  },
  adminSheltersEmpty: {
    en: 'There is no shelter register. Shelter availability is real-world information that cannot be simulated without misleading someone about where to go in a flood, so this stays empty rather than showing invented places.',
    es: 'No hay registro de refugios. La disponibilidad de refugios es información del mundo real que no se puede simular sin engañar a alguien sobre adónde ir durante una inundación, por lo que esto queda vacío en lugar de mostrar lugares inventados.',
  },
  adminWritesTitle: { en: 'Actions unavailable in this build', es: 'Acciones no disponibles en esta versión' },
  adminWritesExplain: {
    en: 'Each action is shown disabled with its reason, rather than hidden or faked. A control that appears to work and silently does nothing is worse than an honestly disabled one.',
    es: 'Cada acción se muestra deshabilitada con su motivo, en lugar de ocultarse o simularse. Un control que parece funcionar y no hace nada es peor que uno honestamente deshabilitado.',
  },
  adminDisabled: { en: 'Disabled', es: 'Deshabilitado' },
  adminRolesTitle: { en: 'Roles defined but not enforced', es: 'Roles definidos pero no aplicados' },
  adminRolesBody: {
    en: 'Viewer, Operator, Publisher and Admin were approved. None is enforced, because there is no server-side identity check (N-2). Showing a role selector would imply access control that does not exist.',
    es: 'Se aprobaron Lector, Operador, Publicador y Administrador. Ninguno se aplica, porque no hay verificación de identidad en el servidor (N-2). Mostrar un selector de rol implicaría un control de acceso que no existe.',
  },
  adminDataMode: { en: 'Data mode', es: 'Modo de datos' },
  adminMixedExplain: {
    en: 'MIXED is the normal state for this demo: the forecast may come from a real upstream while every sensor reading is simulated and road status is seed data.',
    es: 'MIXTO es el estado normal de esta demostración: el pronóstico puede venir de una fuente real mientras que todas las lecturas de sensores son simuladas y el estado de las vías son datos de ejemplo.',
  },
  adminRefresh: { en: 'Refresh sample', es: 'Actualizar muestra' },
  adminLoading: { en: 'Sampling routes…', es: 'Muestreando rutas…' },
  adminSampleFailed: {
    en: 'Could not sample road status. The route API did not answer, so no counts are shown rather than showing zeroes.',
    es: 'No se pudo muestrear el estado de las vías. La API de rutas no respondió, por lo que no se muestran recuentos en lugar de mostrar ceros.',
  },
} satisfies Record<string, Pair>

export type StringKey = keyof typeof STRINGS

/** Banned vocabulary. A test asserts no rendered string contains these. */
export const BANNED_TERMS = [
  'flood-proof',
  'risk-free',
  'guaranteed safe',
  'guaranteed',
  'always passable',
  // "safe" alone is checked contextually (the tagline uses "safely", which is a brand line,
  // not a route claim) — see assertNoRouteSafetyClaim.
]

/** Words that must never appear in a sentence about a route or a road condition. */
export const BANNED_ROUTE_TERMS = ['is safe', 'are safe', 'safe route', 'ruta segura', 'es segura']

export function t(key: StringKey, locale: Locale): string {
  return STRINGS[key][locale]
}

/**
 * Interpolate `{name}` placeholders.
 *
 * Used by the two disclosure strings that quote a measured figure. Hardcoding that figure is what
 * made it wrong before: the copy said "50 km" long after the graph had grown to 1,085 km. Pulling
 * it from the API means the text cannot drift from the data again.
 *
 * Missing values render as an explicit unknown rather than silently leaving `{streets}` on
 * screen, because a template placeholder leaking into the UI is worse than saying "unknown".
 */
export function tf(
  key: StringKey,
  locale: Locale,
  vars: Record<string, string | number | null | undefined>,
): string {
  let out = STRINGS[key][locale]
  for (const [name, value] of Object.entries(vars)) {
    const safe =
      value === null || value === undefined || value === ''
        ? locale === 'es'
          ? 'desconocido'
          : 'unknown'
        : String(value)
    out = out.split(`{${name}}`).join(safe)
  }
  return out
}
