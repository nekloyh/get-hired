import { describe, expect, it } from 'vitest'
import {
  addCandidateAnswer,
  initialSession,
  reduceConnectionClosed,
  reduceSessionEvent,
  validateSetup,
} from './sessionReducer'
import type { SetupForm } from './types'
import { stateFixture } from '../test/fixtures'

const form: SetupForm = {
  mode: 'demo',
  sessionId: 's1',
  candidateId: '',
  targetRole: 'machine learning engineer',
  targetCompanies: '',
  claimedSkills: {
    ml_fundamentals: 3,
    deep_learning: 3,
    mlops: 3,
    system_design: 3,
    vietnamese_nlp: 3,
  },
  maxQuestions: 2,
  languageMode: 'en',
}

describe('setup validation', () => {
  it('rejects missing identity and invalid question caps', () => {
    expect(validateSetup({ ...form, sessionId: '', maxQuestions: 0 })).toEqual([
      'Session id is required.',
      'Max questions must be at least 1.',
    ])
  })

  it('accepts a complete setup form', () => {
    expect(validateSetup(form)).toEqual([])
  })
})

describe('session event reducer', () => {
  it('binds the pending turn id and releases it once answered', () => {
    // NEW-01: the id the server minted with the question rides back with the answer, and stops being
    // sendable the moment the question stops being answerable — otherwise a stale id could re-arm a
    // turn the server has already closed.
    const asked = reduceSessionEvent(initialSession, {
      type: 'question',
      question: 'Explain drift monitoring.',
      turn_id: 7,
    })
    expect(asked.currentTurnId).toBe(7)
    expect(addCandidateAnswer(asked, 'Track input distributions.').currentTurnId).toBeNull()
    expect(reduceConnectionClosed(asked).currentTurnId).toBeNull()
  })

  it('adds interviewer and candidate chat messages around a question', () => {
    const started = reduceSessionEvent(initialSession, {
      type: 'session_started',
      session_id: 's1',
      mode: 'demo',
      resumed: false,
    })
    const asked = reduceSessionEvent(started, { type: 'question', question: 'Explain drift monitoring.', turn_id: 1 })
    const answered = addCandidateAnswer(asked, 'Track input distributions and delayed labels.')

    expect(answered.status).toBe('evaluating')
    expect(answered.messages.map((message) => message.role)).toEqual(['system', 'interviewer', 'candidate'])
  })

  it('keeps the Session open while the planner runs after the last state_update', () => {
    // NEW-15: the Supervisor stamps `complete` one graph node before the Study Plan exists, so the
    // server streams a state_update reading complete with `study_plan: null` and only then spends
    // 5-30s in the planner. Ending the Session on that frame rendered the report early — "N/A %
    // readiness", "Study Plan was not produced." Only `session_completed` is the end.
    const planning = { ...stateFixture, status: 'complete', study_plan: null, study_plan_error: null }

    const streaming = reduceSessionEvent(initialSession, { type: 'state_update', state: planning })
    expect(streaming.status).toBe('evaluating')

    const finished = reduceSessionEvent(streaming, { type: 'session_completed', state: stateFixture })
    expect(finished.status).toBe('complete')
    expect(finished.state?.study_plan?.readiness_estimate).toBe(0.62)
  })

  it('stores final state and error events', () => {
    const completed = reduceSessionEvent(initialSession, { type: 'session_completed', state: stateFixture })
    expect(completed.status).toBe('complete')
    expect(completed.state?.study_plan?.readiness_estimate).toBe(0.62)

    const errored = reduceSessionEvent(completed, { type: 'session_error', error: 'provider missing' })
    expect(errored.status).toBe('error')
    expect(errored.error).toBe('provider missing')
  })
})

describe('connection lifecycle', () => {
  it('marks a mid-session close as disconnected with a resume hint', () => {
    const started = reduceSessionEvent(initialSession, {
      type: 'session_started',
      session_id: 's1',
      mode: 'demo',
      resumed: false,
    })
    const asked = reduceSessionEvent(started, { type: 'question', question: 'Explain drift monitoring.', turn_id: 1 })

    const dropped = reduceConnectionClosed(asked)

    expect(dropped.status).toBe('disconnected')
    expect(dropped.currentQuestion).toBe('')
    expect(dropped.messages.at(-1)?.content).toMatch(/Connection to the interviewer was lost/)
  })

  it('treats a drop inside the planner window as a recoverable disconnect (NEW-15)', () => {
    // The report is not ready yet, so the close is a fault with a resume path — not a finished
    // Session. Resuming re-enters the graph at the study_plan node.
    const planning = { ...stateFixture, status: 'complete', study_plan: null, study_plan_error: null }
    const streaming = reduceSessionEvent(initialSession, { type: 'state_update', state: planning })

    expect(reduceConnectionClosed(streaming).status).toBe('disconnected')
  })

  it('ignores a close after completion (a clean shutdown is not a fault)', () => {
    const completed = reduceSessionEvent(initialSession, { type: 'session_completed', state: stateFixture })
    expect(reduceConnectionClosed(completed)).toBe(completed)
  })

  it('leaves an already-surfaced error untouched on close', () => {
    const errored = reduceSessionEvent(initialSession, { type: 'session_error', error: 'provider missing' })
    expect(reduceConnectionClosed(errored)).toBe(errored)
  })
})
