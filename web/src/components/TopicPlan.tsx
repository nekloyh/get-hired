import { GitBranch, Route } from 'lucide-react'
import type { SessionState } from '../lib/types'

export function TopicPlan({ state }: { state: SessionState | null }) {
  const doneCount = state?.topic_plan.filter((_, index) =>
    state.transcript.some((turn) => turn.plan_index === index),
  ).length ?? 0
  const planProgress = state?.topic_plan.length ? Math.round((doneCount / state.topic_plan.length) * 100) : 0

  return (
    <section className="panel side-panel" aria-label="Topic Plan progress">
      <div className="panel-heading">
        <span className="heading-icon" aria-hidden>
          <GitBranch size={18} />
        </span>
        <div>
          <span className="eyebrow">Supervisor path</span>
          <h2>Topic Plan</h2>
        </div>
      </div>
      {!state ? (
        <div className="rail-empty">
          <Route size={28} aria-hidden />
          <p className="muted">No Topic Plan yet.</p>
        </div>
      ) : (
        <>
          <div className="plan-meter" aria-label={`Topic Plan progress ${planProgress}%`}>
            <span style={{ width: `${planProgress}%` }} />
          </div>
          <ol className="topic-list">
            {state.topic_plan.map((item, index) => {
              const done = state.transcript.some((turn) => turn.plan_index === index)
              const active = state.current_plan_index === index && state.status !== 'complete'
              return (
                <li className={active ? 'active' : done ? 'done' : ''} key={`${item.skill}-${index}`}>
                  <span>{index + 1}</span>
                  <div>
                    <strong>{item.skill}</strong>
                    <small>difficulty {item.target_difficulty}</small>
                  </div>
                </li>
              )
            })}
          </ol>
        </>
      )}
      {state?.supervisor_decisions.length ? (
        <div className="decision-stack">
          {state.supervisor_decisions.map((decision, index) => (
            <div className="decision" key={`${decision.after_question}-${index}`}>
              <span>{decision.action}</span>
              <p>{decision.llm_reasoning}</p>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  )
}
