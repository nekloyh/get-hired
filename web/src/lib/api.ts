import type { Health } from './types'

export const API_BASE = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'

// Shared secret for a gated deployment (R-07). Empty is the local-dev default and matches the
// backend's "COACH_AUTH_TOKEN unset = open" contract, so an ungated localhost setup needs no config.
export const AUTH_TOKEN: string = import.meta.env.VITE_COACH_AUTH_TOKEN ?? ''

function authHeaders(): Record<string, string> {
  return AUTH_TOKEN ? { Authorization: `Bearer ${AUTH_TOKEN}` } : {}
}

/** The opening WebSocket frame when gated, or null when the backend is open. */
export function authFrame(): { type: 'auth'; token: string } | null {
  return AUTH_TOKEN ? { type: 'auth', token: AUTH_TOKEN } : null
}

export async function fetchHealth(): Promise<Health> {
  const response = await fetch(`${API_BASE}/api/health`, { headers: authHeaders() })
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
  if (!response.ok) throw new Error(`Export failed: ${response.status}`)
  return response.text()
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
