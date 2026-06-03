import { Send, Square } from 'lucide-react'
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

  useEffect(() => {
    fetchHealth().then(setHealth).catch((error) => setSetupErrors([String(error)]))
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
    <main className="app-shell">
      <SetupPanel
        errors={errors}
        form={form}
        health={health}
        onChange={setForm}
        onResume={() => connect(true)}
        onStart={() => connect(false)}
      />
      <section className="workspace">
        <aside className="left-rail">
          <SkillBars state={session.state} />
        </aside>
        <section className="interview-panel" aria-label="Interview workspace">
          <div className="interview-header">
            <div>
              <span className="eyebrow">Adaptive Interview Coach</span>
              <h1>{session.sessionId || form.sessionId}</h1>
            </div>
            <div className={`run-status ${session.status}`}>{session.status}</div>
          </div>
          <div className="chat-log" aria-live="polite">
            {session.messages.map((message) => (
              <article className={`message ${message.role}`} key={message.id}>
                <span>{message.role}</span>
                <p>{message.content}</p>
              </article>
            ))}
            {session.messages.length === 0 ? (
              <div className="empty-state">Start or resume a Session to receive the first question.</div>
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
          <ReportView state={session.state} />
        </section>
        <aside className="right-rail">
          <TopicPlan state={session.state} />
        </aside>
      </section>
    </main>
  )
}
