import type { Evaluation, SessionState } from '../lib/types'

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

/** stateFixture with its single turn's evaluation patched — one place to grow the wire shape. */
export function withEvaluation(patch: Partial<Evaluation>): SessionState {
  const [item] = stateFixture.transcript
  const [turn] = item.turns
  return {
    ...stateFixture,
    transcript: [{ ...item, turns: [{ ...turn, evaluation: { ...turn.evaluation, ...patch } }] }],
  }
}
