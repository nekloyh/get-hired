import { beforeEach, describe, expect, it, vi } from 'vitest'
import { authFrame } from './api'
import { loadAuthToken, saveAuthToken } from './authToken'

describe('runtime access token (R-07)', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    vi.unstubAllGlobals()
  })

  it('starts empty so an ungated backend needs no configuration', () => {
    expect(loadAuthToken()).toBe('')
    expect(authFrame()).toBeNull()
  })

  it('round-trips a token and sends it as the opening frame', () => {
    saveAuthToken('shared-secret')

    expect(loadAuthToken()).toBe('shared-secret')
    expect(authFrame()).toEqual({ type: 'auth', token: 'shared-secret' })
  })

  it('clears the token when it is emptied', () => {
    saveAuthToken('shared-secret')
    saveAuthToken('')

    expect(loadAuthToken()).toBe('')
    expect(window.sessionStorage.getItem('coach.authToken')).toBeNull()
  })

  it('lives in sessionStorage, never localStorage', () => {
    // The credential must not outlive the tab or land in the on-disk profile for the next visitor.
    saveAuthToken('shared-secret')

    expect(window.localStorage.getItem('coach.authToken')).toBeNull()
  })

  it('degrades to no token when storage throws instead of breaking the app', () => {
    vi.stubGlobal('sessionStorage', {
      getItem: () => {
        throw new Error('storage disabled by policy')
      },
      setItem: () => {
        throw new Error('storage disabled by policy')
      },
      removeItem: () => {},
    })

    expect(() => saveAuthToken('shared-secret')).not.toThrow()
    expect(loadAuthToken()).toBe('')
  })
})
