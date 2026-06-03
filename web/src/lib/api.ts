import type { Health } from './types'

export const API_BASE = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'

export async function fetchHealth(): Promise<Health> {
  const response = await fetch(`${API_BASE}/api/health`)
  if (!response.ok) throw new Error(`Health check failed: ${response.status}`)
  return response.json()
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
