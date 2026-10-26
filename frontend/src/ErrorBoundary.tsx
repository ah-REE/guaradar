/**
 * Error boundary — stops a single bad value from blanking the whole page.
 *
 * WHY THIS EXISTS: the Status tab went blank because a formatter threw `RangeError` during
 * render (`dateStyle` combined with `timeZoneName`). React unmounts the entire tree on an
 * uncaught render error, so the user saw an infinite spinner followed by nothing at all —
 * with no indication of what failed.
 *
 * The formatter bug is fixed, but a blank page is such a useless failure mode that it should
 * be structurally impossible to reach again. A boundary converts "the app vanished" into
 * "this section failed", which is both honest and diagnosable.
 *
 * It deliberately does NOT try to render partial content or fake data — the point is to be
 * truthful about the failure, not to hide it.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react'
import { tokens } from './tokens'

interface Props {
  children: ReactNode
  /** Short name shown in the message, e.g. "Status" or "Route". */
  section: string
  locale: 'en' | 'es'
}

interface State {
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Console is the only sink available; no data leaves the browser.
    console.error(`[guaradar] ${this.props.section} section crashed:`, error, info.componentStack)
  }

  private reset = (): void => {
    this.setState({ error: null })
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    const es = this.props.locale === 'es'
    return (
      <section
        role="alert"
        style={{
          background: tokens.warnBg,
          color: '#7C2D12',
          border: `1px solid ${tokens.warnFg}`,
          borderRadius: 12,
          padding: 16,
          marginBottom: 16,
        }}
      >
        <h2 style={{ margin: '0 0 6px', fontSize: 15 }}>
          {es ? 'Esta sección no se pudo mostrar' : 'This section could not be displayed'}
        </h2>
        <p style={{ margin: '0 0 8px', fontSize: 13 }}>
          {es
            ? `Los datos de "${this.props.section}" se recibieron, pero la página no pudo dibujarlos. No se muestran valores estimados en su lugar.`
            : `The "${this.props.section}" data was received, but the page could not draw it. No estimated values are shown in its place.`}
        </p>
        <p
          style={{
            margin: '0 0 10px',
            fontSize: 12,
            fontFamily: 'ui-monospace, monospace',
            opacity: 0.85,
            wordBreak: 'break-word',
          }}
        >
          {error.name}: {error.message}
        </p>
        <button
          type="button"
          onClick={this.reset}
          style={{
            padding: '10px 16px',
            minHeight: 44,
            borderRadius: 8,
            border: `1px solid ${tokens.warnFg}`,
            background: '#fff',
            color: tokens.warnFg,
            fontWeight: 600,
            fontSize: 13,
            cursor: 'pointer',
          }}
        >
          {es ? 'Reintentar' : 'Try again'}
        </button>
      </section>
    )
  }
}
