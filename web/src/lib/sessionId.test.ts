import { beforeEach, describe, expect, it, vi } from 'vitest'
import { loadSessionId, rotateSessionId } from './sessionId'

const STORAGE_KEY = 'coach.sessionId'

describe('per-browser session id (R-06)', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.restoreAllMocks()
  })

  it('mints an id on first visit and persists it', () => {
    const id = loadSessionId()

    expect(id).toBeTruthy()
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe(id)
  })

  it('returns the same id on reload, so reconnect still finds the Session', () => {
    // The whole reason the id is persisted: resume identifies a Session by id, so a reload that
    // minted a fresh one would orphan the interview it was meant to rejoin.
    const first = loadSessionId()
    const second = loadSessionId()

    expect(second).toBe(first)
  })

  it('never reuses the old constant, and two fresh browsers get different ids', () => {
    // The defect: every visitor shared 'local-web-session', so anyone could resume — and export the
    // transcript of — whoever was interviewing.
    const first = loadSessionId()
    window.localStorage.clear() // a second browser profile
    const second = loadSessionId()

    expect(first).not.toBe('local-web-session')
    expect(second).not.toBe('local-web-session')
    expect(second).not.toBe(first)
  })

  it('is long enough not to be guessable', () => {
    expect(loadSessionId().replace(/-/g, '').length).toBeGreaterThanOrEqual(32)
  })

  it('rotate mints a new id and persists it over the old one', () => {
    const original = loadSessionId()

    const rotated = rotateSessionId()

    expect(rotated).not.toBe(original)
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe(rotated)
    expect(loadSessionId()).toBe(rotated)
  })

  it('falls back to getRandomValues where randomUUID is unavailable', () => {
    // randomUUID only exists in a secure context; a plain-http LAN deploy (R-11) has none, and there
    // the call is simply absent. Falling back must not produce something guessable.
    const original = crypto.randomUUID
    Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true })

    try {
      const id = rotateSessionId()
      expect(id).toMatch(/^[0-9a-f]{32}$/)
    } finally {
      Object.defineProperty(crypto, 'randomUUID', { value: original, configurable: true })
    }
  })

  it('still yields a usable id when localStorage throws', () => {
    // Safari private mode and policy-disabled storage throw outright rather than returning null.
    // A memory-only id loses resume-after-reload; failing to start would be far worse.
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage disabled')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage disabled')
    })

    expect(loadSessionId()).toBeTruthy()
  })
})
