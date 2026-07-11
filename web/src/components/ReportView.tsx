import { CalendarDays, Download, ExternalLink, FileText, Trophy } from 'lucide-react'
import { exportMarkdownUrl } from '../lib/api'
import { pct } from '../lib/skillMetrics'
import type { SessionState } from '../lib/types'

export function ReportView({ state }: { state: SessionState | null }) {
  if (!state || state.status !== 'complete') return null
  const plan = state.study_plan

  return (
    <section className="report" aria-label="Final report">
      <div className="report-heading">
        <div className="readiness-gauge" aria-label="Readiness estimate">
          <strong>{plan ? Math.round(plan.readiness_estimate * 100) : 'N/A'}</strong>
          <span>% readiness</span>
        </div>
        <div className="report-copy">
          <span className="eyebrow">Final Report</span>
          <h2>{plan ? pct(plan.readiness_estimate) : 'No readiness estimate'}</h2>
          <p>{plan?.readiness_rationale ?? state.study_plan_error ?? 'Study Plan was not produced.'}</p>
        </div>
        <div className="report-actions">
          <a className="icon-button" href={exportMarkdownUrl(state.session_id)} title="Download Markdown export">
            <Download size={18} aria-hidden />
          </a>
        </div>
      </div>

      {plan ? (
        <>
          <div className="report-grid">
            {plan.prioritized_topics.map((topic) => (
              <article className="report-card" key={topic.skill}>
                <header>
                  <div className="card-kicker">Priority {topic.priority}</div>
                  <span>{pct(topic.mastery)}</span>
                </header>
                <h3>{topic.title}</h3>
                <p>{topic.rationale}</p>
                <div className="resource-list">
                  {topic.resources.map((resource) => (
                    <a href={resource.url} key={resource.id} rel="noreferrer" target="_blank">
                      <FileText size={14} aria-hidden />
                      <span>{resource.title}</span>
                      <ExternalLink size={13} aria-hidden />
                    </a>
                  ))}
                </div>
              </article>
            ))}
          </div>
          <div className="milestone-strip" aria-label="Milestones">
            {plan.milestones.map((milestone) => (
              <article key={milestone.week}>
                <Trophy size={16} aria-hidden />
                <strong>Week {milestone.week}</strong>
                <span>{milestone.description}</span>
                <small>{milestone.evidence}</small>
              </article>
            ))}
          </div>
          <div className="schedule-heading">
            <CalendarDays size={18} aria-hidden />
            <h3>Study Schedule</h3>
          </div>
          <div className="schedule-grid">
            {plan.schedule.map((item) => (
              <div className="schedule-day" key={item.day}>
                <strong>Day {item.day}</strong>
                <span>{item.focus}</span>
                <small>{item.outcome}</small>
              </div>
            ))}
          </div>
        </>
      ) : null}

      <div className="accordion-stack">
        {state.transcript.map((item, index) => (
          <details key={`${item.skill}-${index}`}>
            <summary>
              Q{index + 1} {item.skill} · {item.resolved_weighted_score.toFixed(2)}/5 · {item.stop_reason}
            </summary>
            {item.turns.map((turn, turnIndex) => (
              <div className="turn-detail" key={`${turn.question}-${turnIndex}`}>
                <strong>{turn.is_follow_up ? 'Follow-up' : 'Question'}</strong>
                <p>{turn.question}</p>
                <strong>Candidate</strong>
                <p>{turn.answer}</p>
                <div className="dimension-grid">
                  {Object.entries(turn.evaluation.dimensions).map(([dimension, score]) => (
                    <span key={dimension}>
                      {dimension}: <b>{score.score}</b>
                    </span>
                  ))}
                </div>
                {turn.evaluation.delivery_fixes?.length ? (
                  <div className="delivery-fixes">
                    <strong>English delivery fixes</strong>
                    <ul>
                      {turn.evaluation.delivery_fixes.map((fix) => (
                        <li key={fix}>{fix}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <small>{turn.evaluation.follow_up_rationale}</small>
              </div>
            ))}
          </details>
        ))}
      </div>
    </section>
  )
}
