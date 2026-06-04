import { expect, test } from '@playwright/test'

test('demo Session reaches final report', async ({ page, request }) => {
  const apiBase = process.env.VITE_API_URL ?? 'http://127.0.0.1:8000'
  const health = await request.get(`${apiBase}/api/health`)
  test.skip(!health.ok(), 'Backend API is not running; start `uv run coach api` for this E2E.')

  await page.goto('/')
  await page.getByLabel('Mode').selectOption('demo')
  await page.getByLabel('Session id').fill(`pw-demo-${Date.now()}`)
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
