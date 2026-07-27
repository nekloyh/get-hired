import { loadAuthToken } from './authToken'
import type { Health } from './types'

export const API_BASE = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'

// Read per call, never captured at module load: the token is entered at runtime (see authToken.ts),
// so a value cached here would be the empty string from before the operator typed it in.
function authHeaders(): Record<string, string> {
  const token = loadAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** The opening WebSocket frame when a token is held, or null when the backend is open. */
export function authFrame(): { type: 'auth'; token: string } | null {
  const token = loadAuthToken()
  return token ? { type: 'auth', token } : null
}

export async function fetchHealth(): Promise<Health> {
  // Health is ungated by design — it is what tells the UI whether to ask for a token at all.
  const response = await fetch(`${API_BASE}/api/health`)
  if (!response.ok) throw new Error(`Health check failed: ${response.status}`)
  return response.json()
}

/** Fetch the transcript export as text, carrying the bearer token when one is configured.
 *
 * A plain `<a href>` cannot send an Authorization header, so a gated backend answered every export
 * click with a 401. Fetching it and handing the browser a blob keeps one code path for both modes.
 */
export async function fetchExportMarkdown(sessionId: string): Promise<string> {
  const response = await fetch(exportMarkdownUrl(sessionId), { headers: authHeaders() })
  if (!response.ok) throw new Error(exportFailureMessage(response.status))
  return response.text()
}

/** Turn an export failure into something the Candidate can act on rather than a bare status code. */
export function exportFailureMessage(status: number): string {
  if (status === 401) return 'Export refused: the access token is missing or wrong. Re-enter it in Setup.'
  if (status === 404) return 'Export is no longer on the server — it only keeps completed Sessions in memory.'
  return `Export failed (HTTP ${status}).`
}

export function sessionWebSocketUrl(sessionId: string): string {
  const url = new URL(API_BASE)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.pathname = `/api/sessions/${encodeURIComponent(sessionId)}`
  url.search = ''
  return url.toString()
}

export function exportMarkdownUrl(sessionId: string): string {
  return `${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}/export.md`
}
