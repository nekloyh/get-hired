export const SKILLS = [
  'ml_fundamentals',
  'deep_learning',
  'mlops',
  'system_design',
  'vietnamese_nlp',
] as const

// Mirrors web_api.MAX_ANSWER_CHARS. The composer enforces it too (QA-15): the server's refusal only
// arrives after the draft has been cleared and the answer already shown as sent, so a bound that
// lives only on the server is a bound that destroys the text it rejects. `maxLength` counts UTF-16
// code units and pydantic counts code points, and a string never has more code points than code
// units — so the browser bound is the stricter of the two and cannot let an over-long frame through.
export const MAX_ANSWER_CHARS = 20_000

export type Skill = (typeof SKILLS)[number]
export type SessionMode = 'auto' | 'demo' | 'live'
// Session language_mode (issue 0024, ADR 0007): en = English interview; vn = Vietnamese;
// mixed = Vietnamese with natural English code-switching, like a VNG/FPT round.
export type LanguageMode = 'en' | 'vn' | 'mixed'
export type ConnectionStatus =
  | 'idle'
  | 'connecting'
  | 'active'
  | 'evaluating'
  | 'complete'
  | 'error'
  | 'disconnected'

export type SetupForm = {
  mode: SessionMode
  sessionId: string
  candidateId: string
  targetRole: string
  targetCompanies: string
  claimedSkills: Record<Skill, number>
  maxQuestions: number
  languageMode: LanguageMode
}

export type Health = {
  status: string
  primary_provider: string
  primary_configured: boolean
  fallback_provider: string
  fallback_configured: boolean
  demo_available: boolean
  // R-07: whether the backend is gated. Drives whether the UI asks for an access token — which it
  // must do at runtime, because a build-time token would ship inside the bundle.
  auth_required?: boolean
  // R-13: which retrieval path the backend is actually on. Every published retrieval number
  // describes Chroma, so running on the keyword ranker is worth saying out loud.
  concept_store?: string
  retrieval_degraded?: boolean
}

export type SkillState = {
  skill: string
  alpha: number
  beta: number
}

export type PanelOpinion = {
  recommended_score: number
  argument: string
  key_evidence: string
}

export type PanelTrace = {
  triggers: string[]
  skeptic: PanelOpinion
  advocate: PanelOpinion
  initial_score: number
  initial_confidence: number
  disagreement: number
}

export type TrustTrace = {
  pre_guard_confidence: number
  unverifiable_fraction: number
  divergence: number
  noise_events: string[]
  panel_suppressed: boolean
}

export type Evaluation = {
  dimensions: Record<string, { score: number; evidence: string }>
  weighted_score: number
  confidence: number
  follow_up_recommended: boolean
  follow_up_rationale: string
  evidence_degraded?: boolean
  delivery_fixes?: string[]
  panel?: PanelTrace | null
  trust?: TrustTrace | null
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
  stop_reason: string | null
  resolved_weighted_score: number
  resolved_confidence: number
  evidence_weight?: number
  skill_state: SkillState | null
  turns: TranscriptTurn[]
  error?: string
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
  will_probe_skill?: string | null
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
  schema_version?: number
  session_id: string
  topic_plan: TopicPlanEntry[]
  skill_states: Record<string, SkillState>
  skill_metadata: Record<string, { role_criticality: string; evidence_bar: number }>
  current_plan_index: number
  next_skill?: string | null
  question_count: number
  max_questions: number
  max_elapsed_seconds?: number
  started_at?: number
  status: string
  stop_reason?: string | null
  transcript: TranscriptItem[]
  supervisor_decisions: SupervisorDecision[]
  study_plan?: StudyPlan | null
  study_plan_error?: string | null
  candidate_id?: string
  ledger_prior_mastery?: Record<string, number>
  language_mode?: LanguageMode
}

export type SessionEvent =
  | { type: 'session_started'; session_id: string; mode: string; resumed: boolean }
  | { type: 'question'; question: string; turn_id: number }
  | { type: 'state_update'; state: SessionState }
  | { type: 'session_completed'; state: SessionState }
  // QA-15: `recoverable` marks a frame the server's socket loop rejected while the Session kept
  // running — nothing else moved, so the client may put back what it applied optimistically. Optional
  // so an older server (which sends none) reads as "every error is terminal", i.e. today's behaviour.
  | { type: 'session_error'; error: string; recoverable?: boolean }

export type ChatMessage = {
  id: string
  role: 'interviewer' | 'candidate' | 'system'
  content: string
}
