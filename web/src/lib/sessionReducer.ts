import type { ChatMessage, ConnectionStatus, SessionEvent, SessionState, SetupForm } from './types'

export type AppSession = {
  status: ConnectionStatus
  sessionId: string
  mode: string
  currentQuestion: string
  // NEW-01: the turn the pending question belongs to. Sent back with the answer so the server can
  // refuse one that answers a different turn; null whenever nothing is answerable.
  currentTurnId: number | null
  messages: ChatMessage[]
  state: SessionState | null
  error: string | null
  // QA-15: what the composer applied optimistically for the answer now in flight, kept only until the
  // server proves it took it. A `recoverable` refusal puts every field of it back.
  pendingAnswer: { messageId: string; answer: string; question: string; turnId: number } | null
}

export const initialSession: AppSession = {
  status: 'idle',
  sessionId: '',
  mode: 'auto',
  currentQuestion: '',
      currentTurnId: null,
  messages: [],
  state: null,
  error: null,
  pendingAnswer: null,
}

export function reduceSessionEvent(session: AppSession, event: SessionEvent): AppSession {
  if (event.type === 'session_started') {
    return {
      ...session,
      status: 'active',
      sessionId: event.session_id,
      mode: event.mode,
      error: null,
      pendingAnswer: null,
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
      currentTurnId: event.turn_id,
      // The graph asked the next question, so the answer in flight was provably consumed.
      pendingAnswer: null,
      messages: [...session.messages, interviewerMessage(event.question)],
    }
  }
  if (event.type === 'state_update') {
    // NEW-15: a state_update never ends the Session, even when the state it carries already reads
    // `complete`. The Supervisor stamps that status one graph node BEFORE the planner runs, so
    // ending here rendered the report during the 5-30s planner call — "N/A % readiness", "Study Plan
    // was not produced." Only `session_completed` carries a finished Session. The state is still
    // stored on every frame, so the live rails keep updating during the planner window.
    return {
      ...session,
      status: 'evaluating',
      state: event.state,
      pendingAnswer: null,
    }
  }
  if (event.type === 'session_completed') {
    return {
      ...session,
      status: 'complete',
      currentQuestion: '',
      currentTurnId: null,
      pendingAnswer: null,
      state: event.state,
      messages: [...session.messages, systemMessage('Session completed.')],
    }
  }
  // QA-15: `recoverable` (see types.ts) means the server rejected the FRAME and kept the Session, its
  // pending turn and the graph thread exactly as they were. So roll the optimistic send back rather
  // than ending the Session: re-arm the question, drop the bubble for an answer that was never really
  // delivered, and hand the text back to the composer. Everything else stays terminal — a refused
  // start, a refused resume, a refused budget, a suspended budget, a dead quota and a crash all leave
  // nothing on this socket to retry.
  if (event.recoverable && session.pendingAnswer) {
    const { messageId, question, turnId } = session.pendingAnswer
    return {
      ...session,
      status: 'active',
      currentQuestion: question,
      currentTurnId: turnId,
      pendingAnswer: null,
      error: null,
      messages: [...session.messages.filter((message) => message.id !== messageId), systemMessage(event.error)],
    }
  }
  return {
    ...session,
    status: 'error',
    // Clear the pending question so the composer disables — sending into a failed socket would throw.
    currentQuestion: '',
    currentTurnId: null,
    pendingAnswer: null,
    error: event.error,
    messages: [...session.messages, systemMessage(event.error)],
  }
}

export function reduceConnectionClosed(session: AppSession): AppSession {
  // A WebSocket close mid-Session (restarted backend, uvicorn shutdown, network sleep) fires only
  // `onclose`, so no event reaches the reducer and the UI would hang forever on "Waiting for the
  // Interviewer". Surface a distinct disconnected state with a resume path. A clean close after
  // completion, an idle socket, or an already-surfaced error is not a fault, so leave those be.
  if (session.status === 'complete' || session.status === 'idle' || session.status === 'error') {
    return session
  }
  return {
    ...session,
    status: 'disconnected',
    currentQuestion: '',
      currentTurnId: null,
    messages: [
      ...session.messages,
      systemMessage('Connection to the interviewer was lost. Reconnect to resume where you left off.'),
    ],
  }
}

export function addCandidateAnswer(session: AppSession, answer: string): AppSession {
  const message = candidateMessage(answer)
  return {
    ...session,
    status: 'evaluating',
    currentQuestion: '',
    currentTurnId: null,
    // QA-15: everything needed to put the Session back if the server refuses this frame. Optimism is
    // what makes the UI feel live; without the rollback record it is what destroys the answer.
    pendingAnswer: { messageId: message.id, answer, question: session.currentQuestion, turnId: session.currentTurnId! },
    messages: [...session.messages, message],
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
