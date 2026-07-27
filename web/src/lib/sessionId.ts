// Per-browser Session identity (R-06).
//
// The default used to be the constant `'local-web-session'`, which meant every visitor shared one
// Session id: anyone who opened the app could resume — and export the full transcript of — whoever
// was interviewing at the time. The id is the only thing the backend keys a Session on, so it has to
// be unguessable, not merely editable.
//
// Persisted in localStorage because reconnect/resume identifies the Session by id: a page reload
// that minted a fresh id would orphan the in-flight interview it was meant to rejoin.

const STORAGE_KEY = 'coach.sessionId'

function randomId(): string {
  // randomUUID is only exposed in a secure context; a plain-http LAN deployment (R-11) is not one,
  // and there the call is simply absent. getRandomValues has no such restriction, so fall back to it
  // rather than to something guessable like Date.now().
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function readStored(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY)
  } catch {
    // Storage can throw outright, not just return null (Safari private mode, storage disabled by
    // policy). An in-memory id still runs a full interview; only resume-after-reload is lost, which
    // is a better outcome than the app failing to start.
    return null
  }
}

function writeStored(id: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, id)
  } catch {
    // See readStored: unusable storage degrades to a memory-only id.
  }
}

/** This browser's Session id, minting and persisting one on first visit. */
export function loadSessionId(): string {
  return readStored() ?? rotateSessionId()
}

/** Mint and persist a fresh Session id — the "new session" action, and a way to drop a stuck one. */
export function rotateSessionId(): string {
  const id = randomId()
  writeStored(id)
  return id
}
