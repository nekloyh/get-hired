import type { ChatMessage, ConnectionStatus, SessionEvent, SessionState, SetupForm } from './types'

export type AppSession = {
  status: ConnectionStatus
  sessionId: string
  mode: string
  currentQuestion: string
  messages: ChatMessage[]
  state: SessionState | null
  error: string | null
}

export const initialSession: AppSession = {
  status: 'idle',
  sessionId: '',
  mode: 'auto',
  currentQuestion: '',
  messages: [],
  state: null,
  error: null,
}

export function reduceSessionEvent(session: AppSession, event: SessionEvent): AppSession {
  if (event.type === 'session_started') {
    return {
      ...session,
      status: 'active',
      sessionId: event.session_id,
      mode: event.mode,
      error: null,
      messages: event.resumed
        ? [...session.messages, systemMessage('Session resumed from checkpoint.')]
        : [systemMessage(`Session started in ${event.mode} mode.`)],
    }
  }
  if (event.type === 'question') {
    return {
      ...session,
      status: 'active',
      currentQuestion: event.question,
      messages: [...session.messages, interviewerMessage(event.question)],
    }
  }
  if (event.type === 'state_update') {
    return {
      ...session,
      status: event.state.status === 'complete' ? 'complete' : 'evaluating',
      state: event.state,
    }
  }
  if (event.type === 'session_completed') {
    return {
      ...session,
      status: 'complete',
      currentQuestion: '',
      state: event.state,
      messages: [...session.messages, systemMessage('Session completed.')],
    }
  }
  return {
    ...session,
    status: 'error',
    error: event.error,
    messages: [...session.messages, systemMessage(event.error)],
  }
}

export function addCandidateAnswer(session: AppSession, answer: string): AppSession {
  return {
    ...session,
    status: 'evaluating',
    currentQuestion: '',
    messages: [...session.messages, candidateMessage(answer)],
  }
}

export function validateSetup(form: SetupForm): string[] {
  const errors = []
  if (!form.sessionId.trim()) errors.push('Session id is required.')
  if (!form.targetRole.trim()) errors.push('Target role is required.')
  if (!Number.isInteger(form.maxQuestions) || form.maxQuestions < 1) {
    errors.push('Max questions must be at least 1.')
  }
  for (const [skill, value] of Object.entries(form.claimedSkills)) {
    if (value < 1 || value > 5) errors.push(`${skill} claim must be between 1 and 5.`)
  }
  return errors
}

function systemMessage(content: string): ChatMessage {
  return { id: crypto.randomUUID(), role: 'system', content }
}

function interviewerMessage(content: string): ChatMessage {
  return { id: crypto.randomUUID(), role: 'interviewer', content }
}

function candidateMessage(content: string): ChatMessage {
  return { id: crypto.randomUUID(), role: 'candidate', content }
}
