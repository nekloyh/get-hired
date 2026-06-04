import { Activity, BrainCircuit, ClipboardCheck, MessagesSquare, Radar, Send, Sparkles, Square } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ReportView } from './components/ReportView'
import { SetupPanel } from './components/SetupPanel'
import { SkillBars } from './components/SkillBars'
import { TopicPlan } from './components/TopicPlan'
import { fetchHealth, sessionWebSocketUrl } from './lib/api'
import { addCandidateAnswer, initialSession, reduceSessionEvent, validateSetup } from './lib/sessionReducer'
import { SKILLS, type Health, type SessionEvent, type SetupForm } from './lib/types'

const defaultForm: SetupForm = {
  mode: 'auto',
  sessionId: 'local-web-session',
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
}

export function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [form, setForm] = useState(defaultForm)
  const [session, setSession] = useState(initialSession)
  const [draft, setDraft] = useState('')
  const [setupErrors, setSetupErrors] = useState<string[]>([])
  const socketRef = useRef<WebSocket | null>(null)
  const errors = useMemo(() => setupErrors, [setupErrors])

  const phase = useMemo(() => {
    if (session.status === 'idle' || session.status === 'error') return 1
    if (session.status === 'complete') return 3
    return 2;
  }, [session.status])

  const activePlanItem = session.state?.topic_plan[session.state.current_plan_index]
  const answeredCount = session.state?.question_count ?? 0
  const questionCap = session.state?.max_questions ?? form.maxQuestions
  const progressPct = questionCap ? Math.min(100, Math.round((answeredCount / questionCap) * 100)) : 0
  const providerLabel = health?.primary_configured ? `${health.primary_provider} live` : 'demo fallback'
  const phaseItems = [
    { icon: ClipboardCheck, label: 'Setup' },
    { icon: BrainCircuit, label: 'Session' },
    { icon: Radar, label: 'Report' },
  ]

  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => setSetupErrors(['Backend API is not reachable.']))
    return () => socketRef.current?.close()
  }, [])

  const connect = (resume: boolean) => {
    const nextErrors = validateSetup(form)
    setSetupErrors(nextErrors)
    if (nextErrors.length) return

    socketRef.current?.close()
    setSession({ ...initialSession, status: 'connecting', sessionId: form.sessionId })
    const socket = new WebSocket(sessionWebSocketUrl(form.sessionId))
    socketRef.current = socket
    socket.onopen = () => {
      if (resume) {
        socket.send(JSON.stringify({ type: 'resume_session', mode: form.mode }))
      } else {
        socket.send(
          JSON.stringify({
            type: 'start_session',
            mode: form.mode,
            target_role: form.targetRole,
            target_companies: form.targetCompanies
              .split(',')
              .map((company) => company.trim())
              .filter(Boolean),
            claimed_skills: Object.fromEntries(
              SKILLS.map((skill) => [skill, form.claimedSkills[skill]]),
            ),
            max_questions: form.maxQuestions,
          }),
        )
      }
    }
    socket.onmessage = (message) => {
      const event = JSON.parse(message.data) as SessionEvent
      setSession((current) => reduceSessionEvent(current, event))
    }
    socket.onerror = () => {
      setSession((current) =>
        reduceSessionEvent(current, { type: 'session_error', error: 'WebSocket connection failed.' }),
      )
    }
  }

  const sendAnswer = () => {
    const answer = draft.trim()
    if (!answer || !socketRef.current) return
    socketRef.current.send(JSON.stringify({ type: 'candidate_answer', answer }))
    setSession((current) => addCandidateAnswer(current, answer))
    setDraft('')
  }

  const cancel = () => {
    socketRef.current?.send(JSON.stringify({ type: 'cancel_session' }))
    socketRef.current?.close()
  }

  return (
    <div className={`page phase-${phase}`}>
      <div className="ambient-field" aria-hidden>
        <span className="ambient-capsule capsule-a" />
        <span className="ambient-capsule capsule-b" />
        <span className="ambient-capsule capsule-c" />
      </div>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            <Sparkles size={17} />
          </span>
          <span className="brand-text">
            <strong>Interview Coach</strong>
            <small>Candidate calibration cockpit</small>
          </span>
        </div>
        <nav className="phase-nav" aria-label="Session phase">
          {phaseItems.map((item, index) => {
            const StepIcon = item.icon
            const step = index + 1
            const stateClass = phase === step ? 'active' : phase > step ? 'done' : ''
            return (
              <span className={stateClass} key={item.label}>
                <StepIcon size={15} aria-hidden />
                {item.label}
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
              <h1>Evidence-first interview sessions for ML roles</h1>
              <p>
                The Session keeps Candidate claims, Topic Plan pressure, Evaluator confidence, and Supervisor movement in one cockpit.
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
            <div className="inflated-diagram" aria-hidden>
              <span className="diagram-node node-candidate" />
              <span className="diagram-node node-interviewer" />
              <span className="diagram-node node-evaluator" />
              <span className="diagram-node node-supervisor" />
              <span className="diagram-link link-a" />
              <span className="diagram-link link-b" />
              <span className="diagram-link link-c" />
            </div>
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
                disabled={!session.currentQuestion || session.status === 'complete'}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') sendAnswer()
                }}
                placeholder={session.currentQuestion ? 'Answer as the Candidate...' : 'Waiting for the Interviewer'}
                value={draft}
              />
              <div className="composer-actions">
                <button className="icon-button" onClick={cancel} title="Cancel Session" type="button">
                  <Square size={17} aria-hidden />
                </button>
                <button className="primary" disabled={!draft.trim()} onClick={sendAnswer} type="button">
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
