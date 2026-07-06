import { PlugZap, RotateCcw, TriangleAlert } from 'lucide-react'
import type { ConnectionStatus } from '../lib/types'

type Props = {
  status: ConnectionStatus
  error: string | null
  onReconnect: () => void
  onBackToSetup: () => void
}

// Renders a visible, actionable banner whenever a Session hits an error or loses its connection.
// Before this, `session_error` events were stored but never rendered and a dropped socket left the
// UI stuck on "Waiting for the Interviewer" (issue 0016). Self-hides for every other status.
export function SessionAlert({ status, error, onReconnect, onBackToSetup }: Props) {
  if (status !== 'error' && status !== 'disconnected') return null

  const disconnected = status === 'disconnected'
  const Icon = disconnected ? PlugZap : TriangleAlert
  const heading = disconnected ? 'Connection lost' : 'Session error'
  const message =
    error ??
    'The interviewer connection dropped. Your progress is checkpointed — reconnect to resume where you left off.'

  return (
    <div className={`session-alert ${status}`} role="alert">
      <div className="session-alert-body">
        <span className="session-alert-icon" aria-hidden>
          <Icon size={18} />
        </span>
        <div>
          <strong>{heading}</strong>
          <p>{message}</p>
        </div>
      </div>
      <div className="session-alert-actions">
        <button className="primary" onClick={onReconnect} type="button">
          <PlugZap size={15} aria-hidden />
          Reconnect &amp; Resume
        </button>
        <button onClick={onBackToSetup} type="button">
          <RotateCcw size={15} aria-hidden />
          Back to Setup
        </button>
      </div>
    </div>
  )
}
