import { Component, type ReactNode } from 'react'

/** Global error boundary: a render error shows a recoverable message instead of a blank page. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  componentDidCatch(error: Error) {
    console.error('UI error boundary caught:', error)
  }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div role="alert" data-testid="error-boundary" className="m-6 rounded-lg border border-red-400 bg-red-950 p-6 text-red-100">
        <h1 className="text-xl font-semibold">This screen hit an unexpected error</h1>
        <p className="mt-2 break-words text-sm">{this.state.error.message}</p>
        <p className="mt-2 text-sm">Nothing was changed by this error. Reload the screen; if it repeats, record the message above.</p>
        <button onClick={() => this.setState({ error: null })} className="mt-4 rounded bg-accent px-4 py-2 font-semibold text-navy-900 hover:bg-accent-hover">
          Try again
        </button>
      </div>
    )
  }
}
