import { Activity } from 'lucide-react'
import { confidence, mastery, pct } from '../lib/skillMetrics'
import type { SessionState } from '../lib/types'

export function SkillBars({ state }: { state: SessionState | null }) {
  const skills = Object.values(state?.skill_states ?? {})

  return (
    <section className="panel side-panel" aria-label="Skill states">
      <div className="panel-heading">
        <Activity size={18} aria-hidden />
        <h2>Skill State</h2>
      </div>
      {skills.length === 0 ? (
        <p className="muted">Waiting for Session evidence.</p>
      ) : (
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
      )}
    </section>
  )
}
