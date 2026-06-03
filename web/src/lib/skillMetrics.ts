import type { SkillState } from './types'

const NEUTRAL_VARIANCE = betaVariance(1, 1)

export function mastery(state: SkillState): number {
  return state.alpha / (state.alpha + state.beta)
}

export function confidence(state: SkillState): number {
  return clamp01(1 - betaVariance(state.alpha, state.beta) / NEUTRAL_VARIANCE)
}

export function pct(value: number): string {
  return `${Math.round(clamp01(value) * 100)}%`
}

function betaVariance(alpha: number, beta: number): number {
  const n = alpha + beta
  return (alpha * beta) / (n * n * (n + 1))
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value))
}
