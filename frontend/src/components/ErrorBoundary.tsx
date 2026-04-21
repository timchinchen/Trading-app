import { Component, type ErrorInfo, type ReactNode } from 'react'

/**
 * Top-level error boundary. Without this, any runtime error inside a
 * route component (e.g. SymbolPage, Dashboard) crashes React's tree and
 * leaves the viewport blank with no visible hint. We catch the error,
 * log it to the console, and render a recoverable fallback so the user
 * can at least navigate away or retry.
 */
interface Props {
  children: ReactNode
  label?: string
}

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Surface to devtools - invaluable when debugging in a browser with
    // the React devtools overlay disabled.
    console.error(
      `[ErrorBoundary${this.props.label ? ` · ${this.props.label}` : ''}]`,
      error,
      info,
    )
  }

  reset = () => this.setState({ error: null })

  render() {
    if (!this.state.error) return this.props.children
    const err = this.state.error
    return (
      <div className="p-6 max-w-2xl mx-auto">
        <div className="panel p-6 space-y-3">
          <h2 className="text-lg font-semibold text-destructive">
            Something went wrong
          </h2>
          <p className="text-sm text-muted-foreground">
            {this.props.label ? `Error in ${this.props.label}.` : 'A render error occurred.'}{' '}
            The underlying message is shown below for debugging.
          </p>
          <pre className="text-xs text-destructive bg-destructive/10 border border-destructive/30 rounded-lg p-3 overflow-auto max-h-64">
            {err.name}: {err.message}
            {err.stack ? `\n\n${err.stack}` : ''}
          </pre>
          <div className="flex gap-2">
            <button
              onClick={this.reset}
              className="text-xs px-3 py-1.5 rounded-md bg-muted/60 border border-border hover:bg-muted"
            >
              Retry
            </button>
            <button
              onClick={() => (window.location.href = '/')}
              className="text-xs px-3 py-1.5 rounded-md bg-muted/60 border border-border hover:bg-muted"
            >
              Back to Dashboard
            </button>
          </div>
        </div>
      </div>
    )
  }
}
