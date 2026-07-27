import { Activity, MessagesSquare, Send, Sparkles, Square } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ReportView } from './components/ReportView'
import { BrandSeal } from './components/Seal'
import { SessionAlert } from './components/SessionAlert'
import { SetupPanel } from './components/SetupPanel'
import { SkillBars } from './components/SkillBars'
import { TopicPlan } from './components/TopicPlan'
import { fetchHealth, sessionWebSocketUrl } from './lib/api'
import {
  addCandidateAnswer,
  initialSession,
  reduceConnectionClosed,
  reduceSessionEvent,
  validateSetup,
} from './lib/sessionReducer'
import { SKILLS, type Health, type SessionEvent, type SetupForm } from './lib/types'

const defaultForm: SetupForm = {
  mode: 'auto',
  sessionId: 'local-web-session',
  candidateId: '',
  targetRole: 'machine learning engineer',
  targetCompanies: 'Viettel',
  claimedSkills: {
    ml_fundamentals: 3.5,
    deep_learning: 3,
    mlops: 2.5,
    system_design: 3,
    vietnamese_nlp: 2,
  },
  maxQuestions: 3,
  languageMode: 'en',
}

export function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [form, setForm] = useState(defaultForm)
  const [session, setSession] = useState(initialSession)
  const [draft, setDraft] = useState('')
  const [setupErrors, setSetupErrors] = useState<string[]>([])
  const socketRef = useRef<WebSocket | null>(null)
  // Set right before a close we initiate (cancel, back-to-setup, unmount) so `onclose` does not
  // mistake a deliberate close for a dropped connection.
  const closingRef = useRef(false)
  const errors = useMemo(() => setupErrors, [setupErrors])

  const phase = useMemo(() => {
    // Only a truly idle app returns to setup. Errors and dropped connections stay in the session view
    // so their banner is visible and offers a resume path, instead of silently resetting to setup.
    if (session.status === 'idle') return 1
    if (session.status === 'complete') return 3
    return 2
  }, [session.status])

  // The Candidate may only answer when a question is pending on a healthy connection. Gating the
  // composer on this (not just a non-empty draft) stops a leftover draft from being "sent" into a
  // closed socket after a drop — which silently lost the answer and hid the recovery banner (0016).
  const canAnswer = session.status === 'active' && Boolean(session.currentQuestion)
  const activePlanItem = session.state?.topic_plan[session.state.current_plan_index]
  const answeredCount = session.state?.question_count ?? 0
  const questionCap = session.state?.max_questions ?? form.maxQuestions
  const progressPct = questionCap ? Math.min(100, Math.round((answeredCount / questionCap) * 100)) : 0
  const providerLabel = health?.primary_configured ? `${health.primary_provider} live` : 'demo fallback'
  const phaseItems = ['Setup', 'Session', 'Report']

  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => setSetupErrors(['Backend API is not reachable.']))
    return () => {
      closingRef.current = true
      socketRef.current?.close()
    }
  }, [])

  const openSocket = (sessionId: string, firstMessage: object) => {
    closingRef.current = false
    const previous = socketRef.current
    if (previous) {
      previous.onclose = null // a socket we are replacing must not fire the disconnected banner
      previous.close()
    }
    const socket = new WebSocket(sessionWebSocketUrl(sessionId))
    socketRef.current = socket
    socket.onopen = () => socket.send(JSON.stringify(firstMessage))
    socket.onmessage = (message) => {
      const event = JSON.parse(message.data) as SessionEvent
      setSession((current) => reduceSessionEvent(current, event))
    }
    socket.onerror = () => {
      setSession((current) =>
        reduceSessionEvent(current, { type: 'session_error', error: 'WebSocket connection failed.' }),
      )
    }
    socket.onclose = () => {
      // Ignore closes from a socket we already replaced or one we closed deliberately; anything else
      // is a genuine drop (restarted backend, network sleep) that only fires onclose (issue 0016).
      if (socketRef.current !== socket || closingRef.current) return
      setSession((current) => reduceConnectionClosed(current))
    }
  }

  const startMessage = (resume: boolean) =>
    resume
      ? { type: 'resume_session', mode: form.mode }
      : {
          type: 'start_session',
          mode: form.mode,
          candidate_id: form.candidateId.trim(),
          target_role: form.targetRole,
          target_companies: form.targetCompanies
            .split(',')
            .map((company) => company.trim())
            .filter(Boolean),
          claimed_skills: Object.fromEntries(SKILLS.map((skill) => [skill, form.claimedSkills[skill]])),
          max_questions: form.maxQuestions,
          language_mode: form.languageMode,
        }

  const connect = (resume: boolean) => {
    const nextErrors = validateSetup(form)
    setSetupErrors(nextErrors)
    if (nextErrors.length) return

    setSession({ ...initialSession, status: 'connecting', sessionId: form.sessionId })
    openSocket(form.sessionId, startMessage(resume))
  }

  const reconnect = () => {
    // Resume the in-flight Session on the same id after an error or a dropped connection. The backend
    // re-streams state and re-emits the pending question on resume, so the Candidate can continue.
    const sessionId = session.sessionId || form.sessionId
    setSession((current) => ({ ...current, status: 'connecting', error: null }))
    openSocket(sessionId, { type: 'resume_session', mode: form.mode })
  }

  const backToSetup = () => {
    closingRef.current = true
    socketRef.current?.close()
    setSession(initialSession)
    setSetupErrors([])
  }

  const sendAnswer = () => {
    const answer = draft.trim()
    const socket = socketRef.current
    // Never send into a stale/closed socket: a CLOSED socket silently discards the payload (the
    // answer is lost) yet the optimistic state flip would hide the disconnected/error banner (0016).
    if (!answer || !canAnswer || !socket || socket.readyState !== WebSocket.OPEN) return
    socket.send(JSON.stringify({ type: 'candidate_answer', answer }))
    setSession((current) => addCandidateAnswer(current, answer))
    setDraft('')
  }

  const cancel = () => {
    closingRef.current = true
    socketRef.current?.send(JSON.stringify({ type: 'cancel_session' }))
    socketRef.current?.close()
    setSession(initialSession)
  }

  return (
    <div className={`page phase-${phase}`}>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            <BrandSeal />
          </span>
          <span className="brand-text">
            <strong>Interview Coach</strong>
            <small>Luyện phỏng vấn · AI/ML</small>
          </span>
        </div>
        <nav className="phase-nav" aria-label="Session phase">
          {phaseItems.map((label, index) => {
            const step = index + 1
            const stateClass = phase === step ? 'active' : phase > step ? 'done' : ''
            return (
              <span className={stateClass} key={label}>
                <span className="phase-index" aria-hidden>
                  {String(step).padStart(2, '0')}
                </span>
                {label}
              </span>
            )
          })}
        </nav>
        <span className={health?.primary_configured ? 'topbar-meta live' : 'topbar-meta demo'}>
          {providerLabel}
        </span>
      </header>
      <main className="app-shell">
      {phase === 1 && (
        <section className="setup-stage">
          <section className="setup-brief" aria-label="Session brief">
            <div>
              <span className="eyebrow">Adaptive Interview Coach</span>
              <h1>
                The interview grades you <em>in red ink</em>
              </h1>
              <p>
                A mock technical interview that adapts as you answer: every reply is scored against a
                rubric with quoted evidence, your skill estimate updates question by question, and you
                leave with a graded scoresheet and a two-week study plan.
              </p>
            </div>
            <div className="brief-metrics" aria-label="Setup summary">
              <span>
                <strong>{form.targetRole}</strong>
                <small>target role</small>
              </span>
              <span>
                <strong>{form.maxQuestions}</strong>
                <small>question cap</small>
              </span>
              <span>
                <strong>{form.mode}</strong>
                <small>mode</small>
              </span>
            </div>
            <BrandSeal className="brief-seal" />
          </section>
          <SetupPanel
            errors={errors}
            form={form}
            health={health}
            onChange={setForm}
            onResume={() => connect(true)}
            onStart={() => connect(false)}
          />
        </section>
      )}
      
      {phase === 2 && (
        <section className="workspace">
          <SessionAlert
            error={session.error}
            onBackToSetup={backToSetup}
            onReconnect={reconnect}
            status={session.status}
          />
          <aside className="left-rail">
            <SkillBars state={session.state} />
          </aside>
          <section className="interview-panel" aria-label="Interview workspace">
            <div className="interview-header">
              <div>
                <span className="eyebrow">Micro-loop workspace</span>
                <h1>{session.sessionId || form.sessionId}</h1>
                <p>
                  {activePlanItem ? `${activePlanItem.skill} · difficulty ${activePlanItem.target_difficulty}` : 'Preparing first question'}
                </p>
              </div>
              <div className="run-cluster" aria-label="Session progress">
                <div className="progress-dial" style={{ '--progress': `${progressPct}%` } as React.CSSProperties}>
                  <span>{progressPct}%</span>
                </div>
                <div>
                  <div className={`run-status ${session.status}`}>{session.status}</div>
                  <small>{answeredCount}/{questionCap} questions</small>
                </div>
              </div>
            </div>
            <div className="chat-log" aria-live="polite">
              {session.messages.map((message) => (
                <article className={`message ${message.role}`} key={message.id}>
                  <span>{message.role}</span>
                  <p>{message.content}</p>
                </article>
              ))}
              {session.messages.length === 0 ? (
                <div className="empty-state">
                  <MessagesSquare size={34} aria-hidden />
                  <span>Interviewer standing by.</span>
                </div>
              ) : null}
            </div>
            <div className="composer">
              <textarea
                disabled={!canAnswer}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') sendAnswer()
                }}
                placeholder={canAnswer ? 'Answer as the Candidate...' : 'Waiting for the Interviewer'}
                value={draft}
              />
              <div className="composer-actions">
                <button className="icon-button" onClick={cancel} title="Cancel Session" type="button">
                  <Square size={17} aria-hidden />
                </button>
                <button className="primary" disabled={!canAnswer || !draft.trim()} onClick={sendAnswer} type="button">
                  <Send size={16} aria-hidden />
                  Send
                </button>
              </div>
            </div>
          </section>
          <aside className="right-rail">
            <TopicPlan state={session.state} />
          </aside>
        </section>
      )}

      {phase === 3 && (
        <section className="report-phase">
          <div className="interview-panel report-panel">
            <div className="interview-header">
              <div>
                <span className="eyebrow">Interview Completed</span>
                <h1>{session.sessionId || form.sessionId}</h1>
                <p>Evaluator evidence resolved into a Study Plan.</p>
              </div>
              <div className="run-cluster">
                <Activity size={18} aria-hidden />
                <div className={`run-status ${session.status}`}>{session.status}</div>
              </div>
            </div>
            <ReportView state={session.state} />
            <div className="restart-row">
              <button className="primary" onClick={() => setSession(initialSession)}>
                <Sparkles size={16} aria-hidden />
                Start New Session
              </button>
            </div>
          </div>
        </section>
      )}
      </main>
    </div>
  )
}
