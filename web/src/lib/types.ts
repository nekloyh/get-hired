export const SKILLS = [
  'ml_fundamentals',
  'deep_learning',
  'mlops',
  'system_design',
  'vietnamese_nlp',
] as const

export type Skill = (typeof SKILLS)[number]
export type SessionMode = 'auto' | 'demo' | 'live'
export type ConnectionStatus = 'idle' | 'connecting' | 'active' | 'evaluating' | 'complete' | 'error'

export type SetupForm = {
  mode: SessionMode
  sessionId: string
  targetRole: string
  targetCompanies: string
  claimedSkills: Record<Skill, number>
  maxQuestions: number
}

export type Health = {
  status: string
  primary_provider: string
  primary_configured: boolean
  fallback_provider: string
  fallback_configured: boolean
  demo_available: boolean
}

export type SkillState = {
  skill: string
  alpha: number
  beta: number
}

export type Evaluation = {
  dimensions: Record<string, { score: number; evidence: string }>
  weighted_score: number
  confidence: number
  follow_up_recommended: boolean
  follow_up_rationale: string
  self_critique?: {
    triggers: string[]
    first_confidence: number
    second_confidence: number
    kept_pass: string
  } | null
}

export type TranscriptTurn = {
  question: string
  answer: string
  is_follow_up: boolean
  grounding_concept_id?: string | null
  grounding_concept_title?: string | null
  evaluation: Evaluation
  trace: Record<string, unknown>
}

export type TranscriptItem = {
  skill: string
  plan_index: number
  stop_reason: string
  resolved_weighted_score: number
  resolved_confidence: number
  skill_state: SkillState
  turns: TranscriptTurn[]
}

export type StudyResource = {
  id: string
  skill: string
  title: string
  url: string
  summary: string
  resource_type: string
  effort_minutes: number
}

export type StudyPlan = {
  session_id: string
  readiness_estimate: number
  readiness_rationale: string
  prioritized_topics: Array<{
    priority: number
    skill: string
    title: string
    rationale: string
    target_mastery: string
    mastery: number
    confidence: number
    role_criticality: string
    resources: StudyResource[]
  }>
  schedule: Array<{
    day: number
    focus: string
    outcome: string
    resources: StudyResource[]
  }>
  milestones: Array<{ week: number; description: string; evidence: string }>
}

export type SupervisorDecision = {
  action: string
  reasoning: string
  target_skill?: string | null
  target_plan_index?: number | null
  after_question: number
  from_plan_index: number
  to_plan_index: number
  deviation: boolean
  llm_reasoning: string
}

export type TopicPlanEntry = {
  skill: string
  target_difficulty: number
  rationale: string
}

export type SessionState = {
  session_id: string
  topic_plan: TopicPlanEntry[]
  skill_states: Record<string, SkillState>
  skill_metadata: Record<string, { role_criticality: string; evidence_bar: number }>
  current_plan_index: number
  next_skill?: string | null
  question_count: number
  max_questions: number
  status: string
  stop_reason?: string | null
  transcript: TranscriptItem[]
  supervisor_decisions: SupervisorDecision[]
  study_plan?: StudyPlan | null
  study_plan_error?: string | null
}

export type SessionEvent =
  | { type: 'session_started'; session_id: string; mode: string; resumed: boolean }
  | { type: 'question'; question: string }
  | { type: 'state_update'; state: SessionState }
  | { type: 'session_completed'; state: SessionState }
  | { type: 'session_error'; error: string }

export type ChatMessage = {
  id: string
  role: 'interviewer' | 'candidate' | 'system'
  content: string
}
