// Runtime holder for the shared access token (R-07).
//
// Deliberately NOT a `VITE_*` build constant. Vite substitutes those textually into the emitted
// bundle, so `curl https://ui-host/assets/index-*.js | grep` hands the shared secret to anyone who
// can fetch the app — and with it the transcript export and the ability to start live interviews on
// the operator's API key. A gate whose key ships inside the thing it gates is not a gate.
//
// sessionStorage, not localStorage: the credential lives as long as the tab and no longer, and it is
// never written to the profile on disk for a later visitor to find.

const STORAGE_KEY = 'coach.authToken'

export function loadAuthToken(): string {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY) ?? ''
  } catch {
    // Storage can throw outright (Safari private mode, policy). An in-memory-only session still
    // works for the current interview; the operator just re-enters the token in a new tab.
    return ''
  }
}

export function saveAuthToken(token: string): void {
  try {
    if (token) window.sessionStorage.setItem(STORAGE_KEY, token)
    else window.sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // See loadAuthToken.
  }
}
