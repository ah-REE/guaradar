/**
 * Design tokens from Stage 1 §14. Kept in one file so a colour change is one edit.
 *
 * Severity is NEVER communicated by colour alone: every badge here also carries a word,
 * and the sensor cards carry a literal SIMULATED label rather than only a tint.
 */

export const tokens = {
  navy900: '#0A2540',
  navy700: '#143B5C',
  teal700: '#0F766E',
  teal50: '#ECFDF8',
  surface: '#FFFFFF',
  surfaceAlt: '#F7F9FA',
  border: '#E3EAEF',
  muted: '#5B6B78',
  infoBg: '#E0F2FE',
  infoFg: '#0E7490',
  watchBg: '#FEF3C7',
  watchFg: '#B45309',
  warnBg: '#FFEDD5',
  warnFg: '#C2410C',
  dangerBg: '#FEE2E2',
  dangerFg: '#B91C1C',
  okBg: '#DCFCE7',
  okFg: '#15803D',
  simBg: '#FFF7ED',
  simFg: '#9A3412',
} as const

export const fontStack =
  'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
