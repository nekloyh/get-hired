import { spawn, type ChildProcess } from 'node:child_process'
import path from 'node:path'
import { expect, test } from '@playwright/test'

// Issue 0016: kill `coach api` mid-question, restart it, reconnect from the browser, and confirm the
// Session continues to completion. Runs its own backend on a dedicated port (not the shared dev-server
// backend other e2e specs assume) since this spec needs to kill/respawn it mid-test.
const API_PORT = 8010
const API_BASE = `http://127.0.0.1:${API_PORT}`
const REPO_ROOT = path.resolve(process.cwd(), '..')

let apiProcess: ChildProcess | null = null

function spawnApi(): ChildProcess {
  // `uv run coach api` is a wrapper around a child `coach`/uvicorn process (confirmed via `pstree`):
  // killing only the wrapper PID leaves the real server listening, since SIGKILL cannot be forwarded
  // the way SIGTERM sometimes is. Spawn detached so the wrapper and its child share a process group,
  // and always kill the whole group (see killApi) so the actual server dies too.
  return spawn('uv', ['run', 'coach', 'api', '--port', String(API_PORT)], {
    cwd: REPO_ROOT,
    stdio: 'ignore',
    detached: true,
  })
}

function killApi(proc: ChildProcess): void {
  if (proc.pid) {
    try {
      process.kill(-proc.pid, 'SIGKILL')
    } catch {
      proc.kill('SIGKILL')
    }
  } else {
    proc.kill('SIGKILL')
  }
}

async function waitForHealth(timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${API_BASE}/api/health`)
      if (res.ok) return true
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
  return false
}

async function waitForDown(timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      await fetch(`${API_BASE}/api/health`)
    } catch {
      return true
    }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  return false
}

test.describe('web kill/restart/reconnect (issue 0016)', () => {
  test.afterEach(() => {
    if (apiProcess) killApi(apiProcess)
    apiProcess = null
  })

  test('kill coach api mid-question, restart, reconnect, continue to completion', async ({ page }, testInfo) => {
    test.setTimeout(180_000)
    // This spec manages its own backend process and needs the dev server started with
    // VITE_API_URL=http://127.0.0.1:8010 (npm run test:e2e:reconnect). Running it under the default
    // `npm run test:e2e` (no such env, two browser projects) would point the page at the wrong
    // backend and double-spawn/kill the same port from two projects at once.
    test.skip(
      testInfo.project.name !== 'chromium' || process.env.VITE_API_URL !== API_BASE,
      'Run via `npm run test:e2e:reconnect`, not the default test:e2e suite.',
    )
    apiProcess = spawnApi()
    const up = await waitForHealth(20_000)
    test.skip(!up, 'coach api did not come up on the dedicated e2e port for this test.')

    // The dev server must be started with VITE_API_URL=http://127.0.0.1:8010 (see package.json's
    // test:e2e:reconnect script) so the page's fixed API_BASE points at this test's own backend.
    await page.goto('/')
    await page.getByLabel('Mode').selectOption('live')
    await page.getByLabel('Session id').fill(`pw-reconnect-${Date.now()}`)
    await page.getByLabel('Max questions').fill('2')
    await page.getByRole('button', { name: 'Start' }).click()

    const answerBox = page.getByPlaceholder('Answer as the Candidate...')
    const finalReport = page.getByLabel('Final report')

    // Kill the backend the moment the Candidate is mid-question (question shown, answer not sent
    // yet) instead of racing the answer round trip: with a fast test model the Evaluator/Supervisor
    // round trip can complete faster than this Node-side process kill, so waiting for that click to
    // resolve first would let the follow-up arrive before the connection actually drops.
    await expect(answerBox).toBeEnabled({ timeout: 30_000 })
    killApi(apiProcess)
    apiProcess = null
    const down = await waitForDown(10_000)
    expect(down).toBe(true)

    await expect(page.getByRole('alert')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByText(/Connection lost/)).toBeVisible()

    apiProcess = spawnApi()
    const backUp = await waitForHealth(20_000)
    expect(backUp).toBe(true)

    await page.getByRole('button', { name: /Reconnect/ }).click()

    // The in-flight answer may or may not have been durably checkpointed before the kill, so resume
    // may re-ask the same question or move straight to the next one. Answer whatever comes up until
    // the Session completes.
    for (let round = 0; round < 10; round += 1) {
      if (await finalReport.isVisible().catch(() => false)) break
      await expect(answerBox.or(finalReport)).toBeVisible({ timeout: 30_000 })
      if (await finalReport.isVisible().catch(() => false)) break
      await expect(answerBox).toBeEnabled({ timeout: 30_000 })
      await answerBox.fill(
        'Residual connections let gradients flow through identity shortcuts, easing optimization in very deep networks; they do not by themselves fix internal covariate shift or poor weight initialization.',
      )
      await page.getByRole('button', { name: 'Send' }).click()
    }

    await expect(finalReport).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText('Final Report')).toBeVisible()
  })
})
