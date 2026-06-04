import { Activity, Gauge } from 'lucide-react'
import { confidence, mastery, pct } from '../lib/skillMetrics'
import type { SessionState } from '../lib/types'

export function SkillBars({ state }: { state: SessionState | null }) {
  const skills = Object.values(state?.skill_states ?? {})
  const averageMastery =
    skills.length > 0 ? skills.reduce((total, skill) => total + mastery(skill), 0) / skills.length : 0
  const averageConfidence =
    skills.length > 0 ? skills.reduce((total, skill) => total + confidence(skill), 0) / skills.length : 0

  return (
    <section className="panel side-panel" aria-label="Skill states">
      <div className="panel-heading">
        <span className="heading-icon" aria-hidden>
          <Activity size={18} />
        </span>
        <div>
          <span className="eyebrow">Evaluator evidence</span>
          <h2>Skill State</h2>
        </div>
      </div>
      {skills.length === 0 ? (
        <div className="rail-empty">
          <Gauge size={28} aria-hidden />
          <p className="muted">Waiting for Session evidence.</p>
        </div>
      ) : (
        <>
          <div className="rail-summary">
            <span>
              <strong>Avg {pct(averageMastery)}</strong>
              <small>mastery</small>
            </span>
            <span>
              <strong>Avg {pct(averageConfidence)}</strong>
              <small>certainty</small>
            </span>
          </div>
          <div className="skill-list">
            {skills.map((skill) => {
              const meta = state?.skill_metadata[skill.skill]
              const m = mastery(skill)
              const c = confidence(skill)
              return (
                <div className="skill-row" key={skill.skill}>
                  <div className="skill-row-top">
                    <span>{skill.skill}</span>
                    <strong>{pct(m)}</strong>
                  </div>
                  <div className="meter" aria-label={`${skill.skill} mastery ${pct(m)}`}>
                    <span style={{ width: pct(m) }} />
                  </div>
                  <div className="skill-row-meta">
                    <span>confidence {pct(c)}</span>
                    <span>{meta?.role_criticality ?? 'unknown'}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}
    </section>
  )
}
