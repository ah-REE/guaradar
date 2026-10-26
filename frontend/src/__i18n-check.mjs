// Static guard over the i18n catalogue. Run in CI and by hand.
// Parses src/i18n.ts as text (no build step needed) and asserts two things:
//   1. every key has a non-empty en AND es value  (D22: both complete)
//   2. no value contains banned safety overclaims
import { readFileSync } from 'node:fs'

const src = readFileSync(new URL('./i18n.ts', import.meta.url), 'utf8')

// Extract "key: { en: '…', es: '…' }" entries, on ONE line or across THREE.
//
// The old pattern required `en:` and `es:` to sit on the same line as each other, so every
// multi-line entry was silently skipped. That was 31 of 76 keys — including `routeNotSafe`,
// `noFabricatedData` and `pathIsNotSafety`, i.e. exactly the safety-critical copy this guard
// exists to protect. It reported "passed" while validating 59 % of the catalogue. `\s*` now
// spans newlines so both layouts are covered.
const entryRe =
  /(\w+):\s*\{\s*en:\s*('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")\s*,\s*es:\s*('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")\s*,?\s*\}/g

const errors = []
const banned = ['flood-proof', 'risk-free', 'guaranteed safe', 'guaranteed', 'always passable']
const bannedRoute = ['is safe', 'are safe', 'safe route', 'ruta segura', 'es segura']

let count = 0
for (const m of src.matchAll(entryRe)) {
  count++
  const [, key, enRaw, esRaw] = m
  const unq = (raw) => {
    const q = raw[0]
    const inner = raw.slice(1, -1)
    return inner.replace(/\\'/g, "'").replace(/\\\\/g, '\\').replace(/\\"/g, '"')
  }
  const en = unq(enRaw)
  const es = unq(esRaw)
  if (!en.trim()) errors.push(`${key}: empty English value`)
  if (!es.trim()) errors.push(`${key}: empty Spanish value`)
  for (const term of banned) {
    if (en.toLowerCase().includes(term) || es.toLowerCase().includes(term)) {
      errors.push(`${key}: contains banned overclaim "${term}"`)
    }
  }
  // Route-safety claims, but NEGATION-AWARE.
  //
  // A naive substring test flags the very disclaimers this guard exists to enforce: "does not
  // mean a road is safe to travel" and "this does not establish that the route is safe" both
  // contain "is safe". Those are the honest sentences, not the overclaims, so the negation in
  // front of the phrase is what decides it.
  const NEGATIONS = [
    'not',
    'no',
    'never',
    'nothing',
    'cannot',
    "isn't",
    "doesn't",
    'ni',
    'nunca',
    'tampoco',
  ]
  const isNegated = (text, at) => {
    // Look back over the preceding clause for a negation. 60 chars covers
    // "does not mean a road" and "no significa que una vía" without reaching
    // into an unrelated earlier sentence.
    const before = text.slice(Math.max(0, at - 60), at)
    const clause = before.split(/[.;:!?]/).pop() ?? ''
    return NEGATIONS.some((n) => new RegExp(`\\b${n}\\b`, 'i').test(clause))
  }
  for (const term of bannedRoute) {
    for (const text of [en.toLowerCase(), es.toLowerCase()]) {
      let idx = text.indexOf(term)
      while (idx !== -1) {
        if (!isNegated(text, idx)) {
          errors.push(
            `${key}: makes a route-safety claim "${term}" (no negation in the preceding clause)`,
          )
          break
        }
        idx = text.indexOf(term, idx + 1)
      }
    }
  }
}

// Every declared key must be parsed. A parser that silently skips entries reports "passed"
// while validating nothing, which is worse than failing. This is the guard against that.
const declaredKeys = [...src.matchAll(/^  (\w+):\s*\{/gm)].map((m) => m[1])
const parsedKeys = new Set([...src.matchAll(entryRe)].map((m) => m[1]))
const unparsed = declaredKeys.filter((k) => !parsedKeys.has(k))
if (unparsed.length) {
  errors.push(
    `${unparsed.length} declared key(s) were never parsed, so they are unvalidated: ` +
      unparsed.join(', '),
  )
}
if (count < 20) {
  errors.push(`only ${count} entries parsed — the parser probably stopped matching`)
}

// Every key referenced by t() must exist: cheap check that no key is misspelled.
const usedKeys = [...src.matchAll(/t\('(\w+)'/g)].map((m) => m[1])
for (const k of usedKeys) {
  if (!new RegExp(`\\b${k}:\\s*\\{`).test(src)) errors.push(`t() references unknown key "${k}"`)
}

if (errors.length) {
  console.error('i18n check FAILED:')
  for (const e of errors) console.error('  -', e)
  process.exit(1)
}
console.log(`i18n check passed: ${count} keys, both languages present, no overclaims`)
