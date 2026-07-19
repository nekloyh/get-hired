import { expect, it } from 'vitest'

it('CI tripwire - deliberately red', () => {
  expect(1).toBe(2)
})
