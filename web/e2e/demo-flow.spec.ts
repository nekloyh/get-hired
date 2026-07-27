import { expect, test } from '@playwright/test'

test('demo Session reaches final report', async ({ page, request }) => {
  const apiBase = process.env.VITE_API_URL ?? 'http://127.0.0.1:8000'
  const health = await request.get(`${apiBase}/api/health`)
  test.skip(!health.ok(), 'Backend API is not running; start `uv run coach api` for this E2E.')

  await page.goto('/')
  await page.getByLabel('Mode').selectOption('demo')
  // R-06: the id is generated per browser and read-only, so this spec no longer types one in — a
  // fresh Playwright context starts with empty localStorage and therefore its own unguessable id,
  // which is exactly the uniqueness the old `fill()` was faking.
  const sessionId = page.getByLabel('Session id')
  await expect(sessionId).toHaveAttribute('readonly', '')
  await expect(sessionId).not.toHaveValue('local-web-session')
  await expect(sessionId).not.toHaveValue('')
  await page.getByLabel('Max questions').fill('1')
  await page.getByRole('button', { name: 'Start' }).click()

  await expect(page.getByText(/Session started in demo mode/)).toBeVisible()
  await expect(page.getByPlaceholder('Answer as the Candidate...')).toBeEnabled()
  await page
    .getByPlaceholder('Answer as the Candidate...')
    .fill('I would monitor drift, delayed labels, validation quality, and rollback risk before retraining.')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.getByLabel('Final report')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('Final Report')).toBeVisible()
  await expect(page.getByText(/Q1/)).toBeVisible()
})
