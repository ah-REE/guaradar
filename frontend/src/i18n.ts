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
  // CORRECTED 2026-10-26. The banner used to read "PROTOTYPE — NOT AUTHORISED" and claim that
  // authentication was not implemented and that no write action existed. Both statements became
  // FALSE when server-side auth shipped (M13) and road-report decisions shipped (M15). Leaving
  // them would teach operators to distrust the panel that now genuinely works.
  adminPrototype: {
    en: 'PROTOTYPE — AUTHORISED SESSION',
    es: 'PROTOTIPO — SESIÓN AUTORIZADA',
  },
  adminPrototypeBody: {
    en: 'You are signed in with a real role, checked by the server on every action. Some actions DO change data: verifying a road report changes the road status used for routing, and account changes take effect immediately. Everything you do is recorded in an audit log. This remains a prototype on prototype data — do not treat it as the city operating system.',
    es: 'Has iniciado sesión con un rol real, verificado por el servidor en cada acción. Algunas acciones SÍ cambian datos: verificar un reporte de vía cambia el estado usado para el enrutamiento, y los cambios de cuenta se aplican de inmediato. Todo lo que hagas queda registrado en una auditoría. Sigue siendo un prototipo con datos de prototipo: no lo trates como el sistema operativo de la ciudad.',
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
  // CORRECTED 2026-10-26. The previous adminIncidentsEmpty copy said there was no citizen-report
  // channel, no endpoint and no table. Road reports now exist, so that sentence became false —
  // the same class of stale disclosure this project has had to fix twice before (the "50 km"
  // figure and the "routing not exposed" line). The remaining absence is narrow and exact.
  adminIncidentsEmpty: {
    en: 'Citizen road reports are reviewed in the panel below. What still does not exist: clustering of nearby reports into one incident, water-depth band estimation, and submission without an account. Those are not shown rather than simulated.',
    es: 'Los reportes ciudadanos de vías se revisan en el panel inferior. Lo que todavía no existe: agrupar reportes cercanos en un solo incidente, estimar la franja de profundidad del agua y el envío sin cuenta. No se muestran en lugar de simularse.',
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
  adminRolesTitle: { en: 'Roles and what they allow', es: 'Roles y lo que permiten' },
  adminRolesBody: {
    en: 'Viewer, Operator, Publisher and Admin are enforced server-side on every request. A hidden button is not the control: the API rejects an action the role is not permitted, so disabling a tab in the browser changes nothing. Roles cannot be changed after an account is created.',
    es: 'Lector, Operador, Publicador y Administrador se aplican en el servidor en cada solicitud. Un botón oculto no es el control: la API rechaza una acción que el rol no permite, así que deshabilitar una pestaña en el navegador no cambia nada. Los roles no se pueden cambiar después de crear la cuenta.',
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

  // --- M13: access, SMS consent, admin ---------------------------------
  tabAccount: { en: 'Account', es: 'Cuenta' },
  authTitle: { en: 'Sign in', es: 'Iniciar sesión' },
  authSignIn: { en: 'Sign in', es: 'Iniciar sesión' },
  authRegister: { en: 'Create account', es: 'Crear cuenta' },
  authEmail: { en: 'Email', es: 'Correo electrónico' },
  authPasswordField: { en: 'Password', es: 'Contraseña' },
  authPasswordHint: {
    en: 'At least 12 characters. Length matters more than symbols.',
    es: 'Al menos 12 caracteres. La longitud importa más que los símbolos.',
  },
  authSignOut: { en: 'Sign out', es: 'Cerrar sesión' },
  authSignedInAs: { en: 'Signed in as', es: 'Sesión iniciada como' },
  authRole: { en: 'Role', es: 'Rol' },
  authAnonymous: {
    en: 'Browsing as a guest. Public map, forecast, sensors and routing need no account.',
    es: 'Navegando como invitado. El mapa público, el pronóstico, los sensores y las rutas no requieren cuenta.',
  },
  authCreateAccountReason: {
    en: 'An account is only needed to opt in to SMS alerts or to use the admin console.',
    es: 'Solo se necesita una cuenta para activar las alertas por SMS o para usar la consola de administración.',
  },
  authNoRoleChoice: {
    en: 'You cannot choose your own role. New accounts are always public users; administrator accounts are created by the operator on the server.',
    es: 'No puede elegir su propio rol. Las cuentas nuevas son siempre de usuario público; las cuentas de administrador las crea el operador en el servidor.',
  },
  authSessionNote: {
    en: 'Your session is held in a secure, script-inaccessible cookie and expires after 12 hours.',
    es: 'Su sesión se guarda en una cookie segura inaccesible desde scripts y caduca a las 12 horas.',
  },
  smsConsentTitle: { en: 'SMS alerts', es: 'Alertas por SMS' },
  smsConsentExplain: {
    en: 'Register a phone number to receive flood alerts by text. This is optional and off by default. You can withdraw at any time and the number is deleted when you do.',
    es: 'Registre un número de teléfono para recibir alertas de inundación por mensaje. Es opcional y está desactivado por defecto. Puede retirarlo en cualquier momento y el número se elimina al hacerlo.',
  },
  smsPhone: { en: 'Phone number', es: 'Número de teléfono' },
  smsPhoneHint: {
    en: 'International format, e.g. +593 99 999 9999. A number without a country code is rejected rather than guessed.',
    es: 'Formato internacional, p. ej. +593 99 999 9999. Un número sin código de país se rechaza en lugar de adivinarse.',
  },
  smsOptIn: { en: 'Opt in to SMS alerts', es: 'Activar alertas por SMS' },
  smsOptOut: { en: 'Withdraw consent', es: 'Retirar consentimiento' },
  smsOptedIn: { en: 'Opted in', es: 'Activado' },
  smsOptedOut: { en: 'Not opted in', es: 'No activado' },
  smsHistory: { en: 'Consent history', es: 'Historial de consentimiento' },
  smsHistoryEmpty: { en: 'No consent changes recorded.', es: 'No hay cambios de consentimiento registrados.' },
  smsWithdrawNote: {
    en: 'Withdrawing removes your number from the system, not just the flag, so it cannot be used by mistake.',
    es: 'Retirar el consentimiento elimina su número del sistema, no solo la marca, para que no se use por error.',
  },
  smsDryRunBanner: {
    en: 'SMS is in DRY-RUN mode on this deployment: no gateway credentials are configured, so nothing leaves this machine and no delivery is claimed.',
    es: 'El SMS está en modo SIMULACIÓN en esta instalación: no hay credenciales de pasarela configuradas, por lo que nada sale de esta máquina y no se declara ninguna entrega.',
  },
  smsLiveBanner: {
    en: 'Gateway credentials are configured. A message can only be delivered if a paired Android device is online.',
    es: 'Hay credenciales de pasarela configuradas. Un mensaje solo puede entregarse si un dispositivo Android vinculado está en línea.',
  },
  adminLoginRequired: {
    en: 'The admin console requires an administrator sign-in.',
    es: 'La consola de administración requiere iniciar sesión como administrador.',
  },
  adminNotAuthorised: {
    en: 'Your account does not have an administrator role. This is enforced by the server, not just hidden here.',
    es: 'Su cuenta no tiene un rol de administrador. Esto lo aplica el servidor, no solo se oculta aquí.',
  },
  adminAlertsSection: { en: 'Alerts', es: 'Alertas' },
  adminAlertsEmpty: {
    en: 'No alerts have been drafted yet.',
    es: 'Todavía no se ha redactado ninguna alerta.',
  },
  adminNewAlert: { en: 'Draft an alert', es: 'Redactar una alerta' },
  adminAlertTitleEn: { en: 'Title (English)', es: 'Título (inglés)' },
  adminAlertTitleEs: { en: 'Title (Spanish)', es: 'Título (español)' },
  adminAlertBodyEn: { en: 'Message (English)', es: 'Mensaje (inglés)' },
  adminAlertBodyEs: { en: 'Message (Spanish)', es: 'Mensaje (español)' },
  adminAlertSeverity: { en: 'Severity', es: 'Gravedad' },
  adminAlertArea: { en: 'Area', es: 'Zona' },
  adminAlertSaveDraft: { en: 'Save draft', es: 'Guardar borrador' },
  adminAlertBilingualRequired: {
    en: 'Both languages are required. An alert cannot be published in only one language.',
    es: 'Se requieren ambos idiomas. Una alerta no puede publicarse en un solo idioma.',
  },
  adminApprove: { en: 'Approve', es: 'Aprobar' },
  adminSend: { en: 'Send', es: 'Enviar' },
  adminSendConfirm: {
    en: 'Send to every opted-in recipient? This cannot be undone.',
    es: '¿Enviar a todos los destinatarios que aceptaron? Esto no se puede deshacer.',
  },
  adminSendConfirmYes: { en: 'Yes, send now', es: 'Sí, enviar ahora' },
  adminCancel: { en: 'Cancel', es: 'Cancelar' },
  adminAlertStatusDraft: { en: 'Draft', es: 'Borrador' },
  adminAlertStatusApproved: { en: 'Approved', es: 'Aprobada' },
  adminAlertStatusSent: { en: 'Sent', es: 'Enviada' },
  adminAlertStatusFailed: { en: 'Failed', es: 'Fallida' },
  adminAlertDemo: {
    en: 'DEMO ALERT — created from simulated data, not verified emergency information.',
    es: 'ALERTA DE DEMOSTRACIÓN — creada a partir de datos simulados, no es información de emergencia verificada.',
  },
  adminSodNote: {
    en: 'The person who drafts an alert cannot approve it. That requires a second administrator with the publisher role.',
    es: 'Quien redacta una alerta no puede aprobarla. Eso requiere un segundo administrador con el rol de publicador.',
  },
  adminDeliverySection: { en: 'SMS delivery', es: 'Entrega de SMS' },
  adminDeliveryEmpty: {
    en: 'No messages have been attempted yet.',
    es: 'Todavía no se ha intentado ningún mensaje.',
  },
  adminRecipientsOptedIn: { en: 'Recipients opted in', es: 'Destinatarios que aceptaron' },
  adminGatewayMode: { en: 'Gateway mode', es: 'Modo de pasarela' },
  adminConfigRequired: { en: 'Configuration required', es: 'Configuración necesaria' },
  adminConfigBody: {
    en: 'Set these on the server and restart to enable real sending. They are never exposed to the browser.',
    es: 'Configure estas variables en el servidor y reinicie para habilitar el envío real. Nunca se exponen al navegador.',
  },
  adminTestSms: { en: 'Send a test message', es: 'Enviar un mensaje de prueba' },
  adminTestSmsTo: { en: 'Recipient number', es: 'Número de destino' },
  adminTestSmsConfirm: {
    en: 'I confirm I want to send a test message to this number.',
    es: 'Confirmo que quiero enviar un mensaje de prueba a este número.',
  },
  adminTestSmsSend: { en: 'Send test', es: 'Enviar prueba' },
  stateDryRun: { en: 'Dry run — not sent', es: 'Simulación — no enviado' },
  statePending: { en: 'Queued at provider', es: 'En cola en el proveedor' },
  stateProcessed: { en: 'Processed by device', es: 'Procesado por el dispositivo' },
  stateSent: { en: 'Sent — not confirmed delivered', es: 'Enviado — entrega no confirmada' },
  stateDelivered: { en: 'Delivered', es: 'Entregado' },
  stateFailed: { en: 'Failed', es: 'Fallido' },
  stateCancelled: { en: 'Cancelled', es: 'Cancelado' },
  stateCancelling: { en: 'Cancelling', es: 'Cancelando' },
  stateUnknown: { en: 'Unknown', es: 'Desconocido' },
  adminDeliveryStateNote: {
    en: 'Delivery states come from the SMS Gateway itself. "Sent" means the device handed the message to the network, which is not proof it reached the recipient — the provider documents that a message can stay in "Sent" even after delivery.',
    es: 'Los estados de entrega provienen de la propia pasarela SMS. "Enviado" significa que el dispositivo entregó el mensaje a la red, lo que no prueba que llegara al destinatario: el proveedor documenta que un mensaje puede quedarse en "Enviado" incluso después de entregarse.',
  },
  adminClosuresTitle: { en: 'Road closures', es: 'Cierres de vías' },
  adminIncidentsSection: { en: 'Incident reports', es: 'Reportes de incidentes' },
  adminIncidentsNone: {
    en: 'There is no citizen-report channel or incidents table in this build, so nothing can be listed or verified here.',
    es: 'No hay canal de reportes ciudadanos ni tabla de incidentes en esta versión, por lo que aquí no se puede listar ni verificar nada.',
  },
  adminPrototypeShort: {
    en: 'Prototype console. Every action below is authorised by the server, not by this page.',
    es: 'Consola de prototipo. Cada acción a continuación la autoriza el servidor, no esta página.',
  },
  adminStorageNote: {
    en: 'Accounts, consent, alerts and delivery logs are stored in a local SQLite file for this prototype. This is not a production database and has no row-level security.',
    es: 'Las cuentas, el consentimiento, las alertas y los registros de entrega se guardan en un archivo SQLite local para este prototipo. No es una base de datos de producción y no tiene seguridad a nivel de fila.',
  },

  // --- M14: seven-day forecast, INAMHI bulletin, comparison ------------
  weekTitle: { en: 'Seven-day rainfall forecast', es: 'Pronóstico de lluvia a siete días' },
  weekChartHeading: { en: 'Daily rainfall, next seven days', es: 'Lluvia diaria, próximos siete días' },
  weekCardsHeading: { en: 'Daily detail', es: 'Detalle diario' },
  weekUnavailable: {
    en: 'The provider returned no daily series, so the seven-day view is not shown.',
    es: 'El proveedor no devolvió una serie diaria, por lo que no se muestra la vista de siete días.',
  },
  next24Title: { en: 'Hourly rainfall, next 24 hours', es: 'Lluvia horaria, próximas 24 horas' },
  dayRain: { en: 'Rain', es: 'Lluvia' },
  dayProbability: { en: 'Max probability', es: 'Probabilidad máxima' },
  dayTemp: { en: 'Temperature', es: 'Temperatura' },
  dayWeather: { en: 'Sky', es: 'Cielo' },
  dayUnavailable: { en: 'unavailable', es: 'no disponible' },
  chartNoData: {
    en: 'No values to plot. The provider omitted them; nothing was filled in.',
    es: 'No hay valores que graficar. El proveedor los omitió; no se rellenó nada.',
  },
  chartLabel: {
    en: 'Bar chart of daily rainfall in millimetres',
    es: 'Gráfico de barras de lluvia diaria en milímetros',
  },
  hourlyChartLabel: {
    en: 'Bar chart of hourly rainfall in millimetres for the next 24 hours',
    es: 'Gráfico de barras de lluvia horaria en milímetros para las próximas 24 horas',
  },
  bulletinTitle: { en: 'INAMHI official bulletin', es: 'Boletín oficial del INAMHI' },
  bulletinLoading: { en: 'Reading the official bulletin…', es: 'Leyendo el boletín oficial…' },
  bulletinUnavailable: {
    en: 'The official INAMHI bulletin could not be read. Open the official source to see it directly — no values are shown in its place.',
    es: 'No se pudo leer el boletín oficial del INAMHI. Abra la fuente oficial para verlo directamente: no se muestran valores en su lugar.',
  },
  bulletinOpenOfficial: { en: 'Open the official document', es: 'Abrir el documento oficial' },
  bulletinNumber: { en: 'Bulletin', es: 'Boletín' },
  bulletinStatus: { en: 'Status', es: 'Estatus' },
  bulletinIssued: { en: 'Issued', es: 'Emitido' },
  bulletinValid: { en: 'Valid', es: 'Vigencia' },
  bulletinThreat: { en: 'Threat level', es: 'Nivel de amenaza' },
  bulletinPhenomenon: { en: 'Phenomenon', es: 'Fenómeno' },
  bulletinRegions: { en: 'Regions named', es: 'Regiones mencionadas' },
  bulletinBands: {
    en: 'Published 24-hour rainfall bands (mm/24h)',
    es: 'Rangos de lluvia publicados en 24 horas (mm/24h)',
  },
  bulletinBandsNote: {
    en: 'These are regional bands published by INAMHI, not a forecast for any single point.',
    es: 'Son rangos regionales publicados por el INAMHI, no un pronóstico para un punto concreto.',
  },
  bulletinQualitative: {
    en: 'This bulletin publishes no numeric rainfall table, so it is shown as an official statement rather than as numbers.',
    es: 'Este boletín no publica una tabla numérica de lluvia, por lo que se muestra como una declaración oficial en lugar de como cifras.',
  },
  bulletinCached: { en: 'from cache', es: 'desde caché' },
  bulletinRecommendations: { en: 'What may happen', es: 'Qué puede pasar' },
  comparisonTitle: { en: 'Forecast vs INAMHI bulletin', es: 'Pronóstico frente al boletín del INAMHI' },
  comparisonRefused: {
    en: 'No comparison is shown.',
    es: 'No se muestra ninguna comparación.',
  },
  comparisonInside: { en: 'inside band', es: 'dentro del rango' },
  comparisonOutside: { en: 'outside every published band', es: 'fuera de todos los rangos publicados' },
  comparisonCaveats: { en: 'Read before interpreting', es: 'Leer antes de interpretar' },
  comparisonModelRow: { en: 'Model (point)', es: 'Modelo (punto)' },
  comparisonBulletinRow: { en: 'INAMHI (region)', es: 'INAMHI (región)' },
  forecastNotFloodWarning: {
    en: 'Rainfall is not a flood prediction. These numbers describe expected precipitation at a location; they say nothing about water depth on any particular road.',
    es: 'La lluvia no es una predicción de inundación. Estas cifras describen la precipitación prevista en un lugar; no dicen nada sobre la profundidad del agua en una vía concreta.',
  },
  forecastNoRiskScore: {
    en: 'No flood-risk score is calculated from rainfall alone.',
    es: 'No se calcula ninguna puntuación de riesgo de inundación solo a partir de la lluvia.',
  },
  officialLinksTitle: { en: 'Official INAMHI sources', es: 'Fuentes oficiales del INAMHI' },

  // --- M15: community road reports (features A–E) -----------------------
  // Authored in English first per the project language rule, then translated. Every string
  // that touches safety is phrased as evidence, never as a verdict.
  tabReport: { en: 'Report', es: 'Reportar' },
  reportTitle: { en: 'Report a road condition', es: 'Reportar el estado de una vía' },
  reportIntro: {
    en: 'Tell other people what you can see. A report is evidence, not a road-status decision: an operator decides whether a road is closed.',
    es: 'Cuéntale a otras personas lo que puedes ver. Un reporte es evidencia, no una decisión sobre el estado de la vía: un operador decide si una vía está cerrada.',
  },
  reportSignInRequired: {
    en: 'Sign in to submit a report. Your email is never shown publicly — only the road and the photo.',
    es: 'Inicia sesión para enviar un reporte. Tu correo nunca se muestra públicamente: solo la vía y la foto.',
  },
  reportPhotoTitle: { en: '1. Photo', es: '1. Foto' },
  reportTakePhoto: { en: 'Take a photo', es: 'Tomar una foto' },
  reportChoosePhoto: { en: 'Choose an existing photo', es: 'Elegir una foto existente' },
  reportPhotoHint: {
    en: 'JPEG, PNG or WebP, up to 5 MB. The image is resized and its embedded location data is removed before it is published.',
    es: 'JPEG, PNG o WebP, hasta 5 MB. La imagen se redimensiona y se eliminan sus datos de ubicación antes de publicarla.',
  },
  reportPhotoCameraUnavailable: {
    en: 'Camera capture is not available in this browser. Choose a photo instead.',
    es: 'La captura con cámara no está disponible en este navegador. Elige una foto en su lugar.',
  },
  reportPhotoRequired: { en: 'A photo is required for a report.', es: 'Se requiere una foto para el reporte.' },
  reportPhotoTooLarge: {
    en: 'That photo is larger than the 5 MB limit. Choose a smaller one.',
    es: 'Esa foto supera el límite de 5 MB. Elige una más pequeña.',
  },
  reportPhotoRejected: {
    en: 'That file could not be used as a photo. Try a JPEG, PNG or WebP image.',
    es: 'Ese archivo no se pudo usar como foto. Prueba con una imagen JPEG, PNG o WebP.',
  },
  reportLocationTitle: { en: '2. Location', es: '2. Ubicación' },
  reportUseMyLocation: { en: 'Use my current location', es: 'Usar mi ubicación actual' },
  reportLocationHint: {
    en: 'Location is requested only when you press the button. It is not tracked in the background.',
    es: 'La ubicación se solicita solo cuando presionas el botón. No se rastrea en segundo plano.',
  },
  reportLocationDenied: {
    en: 'Location permission was denied. You can place the pin on the map yourself.',
    es: 'Se denegó el permiso de ubicación. Puedes colocar el marcador en el mapa tú mismo.',
  },
  reportLocationUnavailable: {
    en: 'Your position could not be determined. Place the pin on the map instead.',
    es: 'No se pudo determinar tu posición. Coloca el marcador en el mapa en su lugar.',
  },
  reportLocationGetting: { en: 'Getting your location…', es: 'Obteniendo tu ubicación…' },
  reportAccuracy: { en: 'Accuracy', es: 'Precisión' },
  reportAccuracyPoor: {
    en: 'Your GPS accuracy is poor, so the road could not be matched automatically. Adjust the pin or try again outdoors.',
    es: 'La precisión de tu GPS es baja, por lo que no se pudo asociar la vía automáticamente. Ajusta el marcador o inténtalo de nuevo al aire libre.',
  },
  reportPinInstruction: {
    en: 'Tap the map to move the pin so it sits on the road you are reporting.',
    es: 'Toca el mapa para mover el marcador y situarlo sobre la vía que estás reportando.',
  },
  reportMatchedRoad: { en: 'Matched road segment', es: 'Tramo de vía asociado' },
  reportNotMatched: {
    en: 'Not matched to a road. The report will be shown as a nearby hazard but cannot change any road status.',
    es: 'No se asoció a una vía. El reporte se mostrará como un peligro cercano, pero no puede cambiar el estado de ninguna vía.',
  },
  reportCategoryTitle: { en: '3. What do you see?', es: '3. ¿Qué ves?' },
  reportCategoryFlooded: { en: 'Flooded road', es: 'Vía inundada' },
  reportCategoryBlocked: { en: 'Road completely blocked', es: 'Vía completamente bloqueada' },
  reportCategoryDebris: { en: 'Debris or fallen objects', es: 'Escombros u objetos caídos' },
  reportCategoryDamaged: { en: 'Damaged road', es: 'Vía dañada' },
  reportCategoryRising: { en: 'Water level rising', es: 'Nivel del agua subiendo' },
  reportCategoryOther: { en: 'Other road hazard', es: 'Otro peligro en la vía' },
  reportDescription: { en: 'Description (optional)', es: 'Descripción (opcional)' },
  reportDescriptionHint: {
    en: 'Up to 280 characters. Do not include names, phone numbers or addresses.',
    es: 'Hasta 280 caracteres. No incluyas nombres, teléfonos ni direcciones.',
  },
  reportSubmit: { en: 'Submit report', es: 'Enviar reporte' },
  reportSubmitting: { en: 'Submitting…', es: 'Enviando…' },
  reportSubmitted: {
    en: 'Report submitted as UNVERIFIED. Other people can now see it and confirm what they see.',
    es: 'Reporte enviado como NO VERIFICADO. Otras personas ya pueden verlo y confirmar lo que observan.',
  },
  reportSubmitFailed: {
    en: 'The report was not saved. Nothing was recorded; please try again.',
    es: 'El reporte no se guardó. No se registró nada; inténtalo de nuevo.',
  },
  reportRateLimited: {
    en: 'You have submitted several reports recently. Please wait before sending another.',
    es: 'Has enviado varios reportes recientemente. Espera antes de enviar otro.',
  },
  reportPrivacyTitle: { en: 'What is published', es: 'Qué se publica' },
  reportPrivacyBody: {
    en: 'Published: the photo, the road or nearby area, the category and your description. Not published: your email, your account identity, or your exact standing position. When the pin matches a road, the road position is shown instead of yours.',
    es: 'Se publica: la foto, la vía o la zona cercana, la categoría y tu descripción. No se publica: tu correo, la identidad de tu cuenta ni tu posición exacta. Cuando el marcador coincide con una vía, se muestra la posición de la vía en lugar de la tuya.',
  },
  reportMapTitle: { en: 'Recent reports', es: 'Reportes recientes' },
  reportMapEmpty: {
    en: 'No reports yet. An empty list does not mean the roads are clear — nobody has reported anything.',
    es: 'Todavía no hay reportes. Una lista vacía no significa que las vías estén despejadas: nadie ha reportado nada.',
  },
  reportMapFailed: {
    en: 'Reports could not be loaded. This is a data problem, not an all-clear.',
    es: 'No se pudieron cargar los reportes. Es un problema de datos, no una señal de que todo esté despejado.',
  },
  reportStatusUnverified: { en: 'Unverified report', es: 'Reporte no verificado' },
  reportStatusPotential: { en: 'Potential hazard', es: 'Peligro potencial' },
  reportStatusBlocked: { en: 'Blocked — verified', es: 'Bloqueada — verificada' },
  reportStatusPassable: { en: 'Passable — verified', es: 'Transitable — verificada' },
  reportStatusInconclusive: { en: 'Inconclusive', es: 'No concluyente' },
  reportStatusRejected: { en: 'Rejected', es: 'Rechazado' },
  reportStatusStale: { en: 'Stale — needs re-check', es: 'Desactualizado — requiere revisión' },
  reportStatusUnknown: { en: 'Unknown', es: 'Desconocido' },
  reportStatusLegend: {
    en: 'Unverified means nobody has checked. Verified means an operator recorded a decision. Stale means the evidence is older than the freshness window — it is NOT a statement that the road is passable.',
    es: 'No verificado significa que nadie lo ha comprobado. Verificado significa que un operador registró una decisión. Desactualizado significa que la evidencia es más antigua que la ventana de vigencia: NO es una afirmación de que la vía sea transitable.',
  },
  reportReportedAt: { en: 'Reported', es: 'Reportado' },
  reportVerifiedAt: { en: 'Last verified', es: 'Última verificación' },
  reportExpiresAt: { en: 'Fresh until', es: 'Vigente hasta' },
  reportStaleNote: {
    en: 'This evidence has expired. Conditions may have changed and it is not proof that the road is passable.',
    es: 'Esta evidencia ha caducado. Las condiciones pueden haber cambiado y no es prueba de que la vía sea transitable.',
  },
  reportConfirmStillThere: { en: 'Still there', es: 'Sigue allí' },
  reportConfirmImproved: { en: 'Looks improved', es: 'Parece mejor' },
  reportConfirmations: { en: 'Community confirmations', es: 'Confirmaciones de la comunidad' },
  reportChallenges: { en: 'Improved reports', es: 'Reportes de mejora' },
  reportConfirmRecorded: {
    en: 'Recorded. This adds evidence and does not change the road status by itself.',
    es: 'Registrado. Esto añade evidencia y no cambia el estado de la vía por sí solo.',
  },
  reportAlreadyConfirmed: {
    en: 'You have already responded to this report.',
    es: 'Ya has respondido a este reporte.',
  },
  reportConfirmFailed: {
    en: 'Your response was not recorded. Please try again.',
    es: 'Tu respuesta no se registró. Inténtalo de nuevo.',
  },
  reportPhotoAlt: { en: 'Photo submitted with this road report', es: 'Foto enviada con este reporte de vía' },
  reportNoPhoto: { en: 'No photo', es: 'Sin foto' },
  reportSeededBadge: {
    en: 'Demo fixture — not a real submission',
    es: 'Datos de demostración — no es un envío real',
  },
  reportNearbyTitle: { en: 'Reports near you', es: 'Reportes cerca de ti' },

  // --- admin: report review ---------------------------------------------
  adminReportsTitle: { en: 'Road report review', es: 'Revisión de reportes de vías' },
  adminReportsExplain: {
    en: 'Reports arrive unverified. A decision here changes the road status used by routing, so it is recorded with your role and timestamp in an append-only history.',
    es: 'Los reportes llegan sin verificar. Una decisión aquí cambia el estado de la vía que usa el enrutamiento, por lo que se registra con tu rol y hora en un historial de solo adición.',
  },
  adminReportsEmpty: {
    en: 'No reports are waiting for review.',
    es: 'No hay reportes esperando revisión.',
  },
  adminReportsFailed: {
    en: 'The report queue could not be loaded. No decisions are available while it is unavailable.',
    es: 'No se pudo cargar la cola de reportes. No hay decisiones disponibles mientras no esté disponible.',
  },
  adminReportsNeedRole: {
    en: 'Reviewing reports requires an operator account. This panel is read-only without one.',
    es: 'Revisar reportes requiere una cuenta de operador. Sin ella, este panel es de solo lectura.',
  },
  adminReportAccuracy: { en: 'GPS accuracy', es: 'Precisión del GPS' },
  adminReportSource: { en: 'Position source', es: 'Origen de la posición' },
  adminReportSnapDistance: { en: 'Distance to road', es: 'Distancia a la vía' },
  adminReportSegment: { en: 'Road segment', es: 'Tramo de vía' },
  adminReportHistory: { en: 'Status history', es: 'Historial de estado' },
  adminReportNoHistory: { en: 'No recorded changes yet.', es: 'Aún no hay cambios registrados.' },
  adminDecisionVerifyBlocked: { en: 'Verify as blocked', es: 'Verificar como bloqueada' },
  adminDecisionVerifyPassable: { en: 'Verify as passable', es: 'Verificar como transitable' },
  adminDecisionPotential: { en: 'Mark potential hazard', es: 'Marcar peligro potencial' },
  adminDecisionInconclusive: { en: 'Mark inconclusive', es: 'Marcar no concluyente' },
  adminDecisionReject: { en: 'Reject report', es: 'Rechazar reporte' },
  adminDecisionNote: { en: 'Decision note (optional)', es: 'Nota de la decisión (opcional)' },
  adminDecisionSaved: {
    en: 'Decision recorded. The road status used by routing has been updated.',
    es: 'Decisión registrada. Se actualizó el estado de la vía que usa el enrutamiento.',
  },
  adminDecisionFailed: {
    en: 'The decision was not saved. Nothing was changed; please try again.',
    es: 'La decisión no se guardó. No se cambió nada; inténtalo de nuevo.',
  },
  adminDecisionNeedsOperator: {
    en: 'Only an operator can record a decision. Your current role can view reports but not decide them.',
    es: 'Solo un operador puede registrar una decisión. Tu rol actual puede ver reportes pero no decidirlos.',
  },
  adminReportSeeded: {
    en: 'This is a demo fixture, not a citizen submission.',
    es: 'Estos son datos de demostración, no un envío ciudadano.',
  },
  adminUnverifiedIsNotClosure: {
    en: 'An unverified report is evidence only. It cannot close a road until an operator verifies it.',
    es: 'Un reporte no verificado es solo evidencia. No puede cerrar una vía hasta que un operador lo verifique.',
  },
  adminConflictsTitle: { en: 'Conflicting reports', es: 'Reportes contradictorios' },
  adminConflictsBody: {
    en: 'Where verified reports disagree, the higher-risk reading is used for routing and both are kept. Nothing is averaged away.',
    es: 'Cuando los reportes verificados se contradicen, se usa la lectura de mayor riesgo para el enrutamiento y se conservan ambos. Nada se promedia.',
  },

  // --- routing: current location ----------------------------------------
  routeOriginTitle: { en: 'Starting point', es: 'Punto de partida' },
  routeUseMyLocation: { en: 'Use my current location', es: 'Usar mi ubicación actual' },
  routeLocationGetting: { en: 'Getting your location…', es: 'Obteniendo tu ubicación…' },
  routeLocationDenied: {
    en: 'Location permission was denied. Choose a starting point from the list instead.',
    es: 'Se denegó el permiso de ubicación. Elige un punto de partida de la lista en su lugar.',
  },
  routeLocationUnavailable: {
    en: 'Your position could not be determined. Choose a starting point from the list instead.',
    es: 'No se pudo determinar tu posición. Elige un punto de partida de la lista en su lugar.',
  },
  routeOriginFromGps: {
    en: 'Origin: your current position, snapped to the nearest road.',
    es: 'Origen: tu posición actual, ajustada a la vía más cercana.',
  },
  routeOriginOffNetwork: {
    en: 'Your position is too far from this road network to start a route. Choose a starting point from the list.',
    es: 'Tu posición está demasiado lejos de esta red de vías para iniciar una ruta. Elige un punto de partida de la lista.',
  },
  routeReportsInfluence: {
    en: 'Community reports affected the road status used for this search.',
    es: 'Los reportes de la comunidad afectaron el estado de las vías usado en esta búsqueda.',
  },
  routeReportsNone: {
    en: 'No community report affected this search. That is not evidence the roads are clear.',
    es: 'Ningún reporte de la comunidad afectó esta búsqueda. Eso no es evidencia de que las vías estén despejadas.',
  },

  // --- M16: staff account administration --------------------------------
  // Authoring rule: these describe PERMISSIONS, so each says what a role can do rather than
  // ranking it ("higher"/"lower"). A reader deciding what to grant needs the capability, not a
  // hierarchy diagram.
  acctTitle: { en: 'Staff accounts', es: 'Cuentas del personal' },
  acctExplain: {
    en: 'Create and manage the accounts used by city staff. Roles are fixed when an account is created and cannot be changed afterwards, so there is no way for an account to gain more access than it was granted.',
    es: 'Crea y gestiona las cuentas del personal municipal. Los roles se fijan al crear la cuenta y no se pueden cambiar después, por lo que ninguna cuenta puede obtener más acceso del que se le concedió.',
  },
  acctLoading: { en: 'Loading accounts…', es: 'Cargando cuentas…' },
  acctLoadFailed: {
    en: 'The account list could not be loaded. No accounts are shown rather than showing a stale list.',
    es: 'No se pudo cargar la lista de cuentas. No se muestran cuentas en lugar de mostrar una lista desactualizada.',
  },
  acctNeedRole: {
    en: 'Managing accounts requires an operator account or above.',
    es: 'Gestionar cuentas requiere una cuenta de operador o superior.',
  },
  acctCreateTitle: { en: 'Create an account', es: 'Crear una cuenta' },
  acctEmailLabel: { en: 'Email', es: 'Correo electrónico' },
  acctPassphraseLabel: { en: 'Initial passphrase', es: 'Frase de acceso inicial' },
  acctPassphraseHint: {
    en: 'At least 12 characters. Length matters more than symbols. It is stored only as a hash and is never shown again — record it before you leave this screen.',
    es: 'Al menos 12 caracteres. La longitud importa más que los símbolos. Se guarda solo como hash y nunca se vuelve a mostrar: anótala antes de salir de esta pantalla.',
  },
  acctRoleLabel: { en: 'Role', es: 'Rol' },
  acctCreateButton: { en: 'Create account', es: 'Crear cuenta' },
  acctWorking: { en: 'Working…', es: 'Procesando…' },
  acctCreated: {
    en: 'Account created. Give the passphrase to that person directly; it cannot be displayed again.',
    es: 'Cuenta creada. Entrega la frase de acceso a esa persona directamente; no se puede volver a mostrar.',
  },
  acctCreateFailed: {
    en: 'The account was not created. Nothing was saved; please try again.',
    es: 'La cuenta no se creó. No se guardó nada; inténtalo de nuevo.',
  },
  acctUpdated: { en: 'Account updated.', es: 'Cuenta actualizada.' },
  acctUpdateFailed: {
    en: 'That change was not saved. Nothing was modified; please try again.',
    es: 'Ese cambio no se guardó. No se modificó nada; inténtalo de nuevo.',
  },
  acctValidationFailed: {
    en: 'Check the details: the email must be valid and the passphrase at least 12 characters. If the email is already registered, choose another.',
    es: 'Revisa los datos: el correo debe ser válido y la frase de acceso de al menos 12 caracteres. Si el correo ya está registrado, elige otro.',
  },
  acctCannotGrant: {
    en: 'You cannot grant that role. You may only grant roles below your own; creating an administrator is possible only from the server command line.',
    es: 'No puedes conceder ese rol. Solo puedes conceder roles inferiores al tuyo; crear un administrador solo es posible desde la línea de comandos del servidor.',
  },
  acctCannotManage: {
    en: 'You cannot manage that account: its role is above your own.',
    es: 'No puedes gestionar esa cuenta: su rol es superior al tuyo.',
  },
  acctLastAdmin: {
    en: 'This is the last enabled administrator. Disabling it would leave nobody able to manage accounts, so it is refused. Create another administrator from the command line first.',
    es: 'Este es el último administrador habilitado. Deshabilitarlo dejaría a nadie capaz de gestionar cuentas, por lo que se rechaza. Crea primero otro administrador desde la línea de comandos.',
  },
  acctBootstrapOnly: {
    en: 'Administrator accounts cannot be created here. Only the server command line can create one, which keeps the highest role out of reach of a web session entirely.',
    es: 'Las cuentas de administrador no se pueden crear aquí. Solo la línea de comandos del servidor puede crear una, lo que mantiene el rol más alto fuera del alcance de una sesión web.',
  },
  acctNoGrantable: {
    en: 'Your role cannot grant any role. This panel is read-only for you.',
    es: 'Tu rol no puede conceder ningún rol. Este panel es de solo lectura para ti.',
  },
  acctExistingTitle: { en: 'Existing accounts', es: 'Cuentas existentes' },
  acctEmpty: { en: 'No accounts yet.', es: 'Aún no hay cuentas.' },
  acctCreatedLabel: { en: 'Created', es: 'Creada' },
  acctLastActiveLabel: { en: 'Last sign-in', es: 'Último acceso' },
  acctStateLabel: { en: 'State', es: 'Estado' },
  acctActionsLabel: { en: 'Actions', es: 'Acciones' },
  acctActive: { en: 'Active', es: 'Activa' },
  acctDisabled: { en: 'Disabled', es: 'Deshabilitada' },
  acctDisabledCount: { en: 'Disabled', es: 'Deshabilitadas' },
  acctEnable: { en: 'Enable', es: 'Habilitar' },
  acctDisable: { en: 'Disable', es: 'Deshabilitar' },
  acctThisIsYou: { en: 'This is you', es: 'Esta eres tú' },
  acctResetPassphrase: { en: 'Reset passphrase', es: 'Restablecer frase' },
  acctNewPassphraseLabel: { en: 'New passphrase', es: 'Nueva frase de acceso' },
  acctConfirmReset: { en: 'Set passphrase', es: 'Establecer frase' },
  acctPassphraseReset: {
    en: 'Passphrase replaced and every existing session for that account was signed out.',
    es: 'Frase de acceso reemplazada y todas las sesiones existentes de esa cuenta fueron cerradas.',
  },
  acctRoleViewer: { en: 'Viewer', es: 'Lector' },
  acctRoleOperator: { en: 'Operator', es: 'Operador' },
  acctRolePublisher: { en: 'Publisher', es: 'Publicador' },
  acctRoleAdmin: { en: 'Administrator', es: 'Administrador' },
  acctRolePublic: { en: 'Citizen', es: 'Ciudadano' },
  acctRoleWhatViewer: { en: 'can read panels, cannot change anything', es: 'puede leer paneles, no puede cambiar nada' },
  acctRoleWhatOperator: { en: 'can verify and reject road reports', es: 'puede verificar y rechazar reportes de vías' },
  acctRoleWhatPublisher: { en: 'can approve and send public alerts', es: 'puede aprobar y enviar alertas públicas' },
  acctRoleWhatAdmin: { en: 'full access, including accounts', es: 'acceso total, incluidas las cuentas' },
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
