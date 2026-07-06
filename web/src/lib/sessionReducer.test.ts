import { describe, expect, it } from 'vitest'
import {
  addCandidateAnswer,
  initialSession,
  reduceConnectionClosed,
  reduceSessionEvent,
  validateSetup,
} from './sessionReducer'
import type { SessionState, SetupForm } from './types'

const form: SetupForm = {
  mode: 'demo',
  sessionId: 's1',
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
  it('adds interviewer and candidate chat messages around a question', () => {
    const started = reduceSessionEvent(initialSession, {
      type: 'session_started',
      session_id: 's1',
      mode: 'demo',
      resumed: false,
    })
    const asked = reduceSessionEvent(started, { type: 'question', question: 'Explain drift monitoring.' })
    const answered = addCandidateAnswer(asked, 'Track input distributions and delayed labels.')

    expect(answered.status).toBe('evaluating')
    expect(answered.messages.map((message) => message.role)).toEqual(['system', 'interviewer', 'candidate'])
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
    const asked = reduceSessionEvent(started, { type: 'question', question: 'Explain drift monitoring.' })

    const dropped = reduceConnectionClosed(asked)

    expect(dropped.status).toBe('disconnected')
    expect(dropped.currentQuestion).toBe('')
    expect(dropped.messages.at(-1)?.content).toMatch(/Connection to the interviewer was lost/)
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

export const stateFixture: SessionState = {
  session_id: 's1',
  topic_plan: [{ skill: 'mlops', target_difficulty: 4, rationale: 'Role-critical production Skill.' }],
  skill_states: { mlops: { skill: 'mlops', alpha: 3, beta: 2 } },
  skill_metadata: { mlops: { role_criticality: 'must_have', evidence_bar: 4 } },
  current_plan_index: 0,
  next_skill: null,
  question_count: 1,
  max_questions: 1,
  status: 'complete',
  stop_reason: 'max_questions',
  transcript: [
    {
      skill: 'mlops',
      plan_index: 0,
      stop_reason: 'resolved',
      resolved_weighted_score: 3.5,
      resolved_confidence: 0.8,
      skill_state: { skill: 'mlops', alpha: 3, beta: 2 },
      turns: [
        {
          question: 'How do you monitor drift?',
          answer: 'Track drift, delayed labels, and rollback risk.',
          is_follow_up: false,
          evaluation: {
            dimensions: { correctness: { score: 4, evidence: 'Track drift' } },
            weighted_score: 3.5,
            confidence: 0.8,
            follow_up_recommended: false,
            follow_up_rationale: 'Enough evidence for demo.',
          },
          trace: {},
        },
      ],
    },
  ],
  supervisor_decisions: [
    {
      action: 'end_early',
      reasoning: 'max questions',
      after_question: 1,
      from_plan_index: 0,
      to_plan_index: 0,
      deviation: true,
      llm_reasoning: 'Hard cap reached.',
    },
  ],
  study_plan: {
    session_id: 's1',
    readiness_estimate: 0.62,
    readiness_rationale: 'Close, with MLOps gaps.',
    prioritized_topics: [
      {
        priority: 1,
        skill: 'mlops',
        title: 'Sharpen MLOps',
        rationale: 'Monitoring evidence was thin.',
        target_mastery: 'Explain drift and rollback.',
        mastery: 0.6,
        confidence: 0.4,
        role_criticality: 'must_have',
        resources: [
          {
            id: 'mlops_google_rules',
            skill: 'mlops',
            title: 'Google Rules of ML',
            url: 'https://example.test/ml',
            summary: 'Production ML guidance.',
            resource_type: 'guide',
            effort_minutes: 45,
          },
        ],
      },
    ],
    schedule: Array.from({ length: 14 }, (_, index) => ({
      day: index + 1,
      focus: `Day ${index + 1} focus`,
      outcome: 'Write a concise answer.',
      resources: [],
    })),
    milestones: [{ week: 1, description: 'Record an answer.', evidence: 'Rubric notes.' }],
  },
  study_plan_error: null,
}
