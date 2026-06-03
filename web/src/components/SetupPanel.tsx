import { Play, RotateCcw } from 'lucide-react'
import { SKILLS, type Health, type SetupForm, type Skill } from '../lib/types'

type Props = {
  form: SetupForm
  health: Health | null
  errors: string[]
  onChange: (form: SetupForm) => void
  onStart: () => void
  onResume: () => void
}

export function SetupPanel({ form, health, errors, onChange, onStart, onResume }: Props) {
  const setClaim = (skill: Skill, value: number) => {
    onChange({ ...form, claimedSkills: { ...form.claimedSkills, [skill]: value } })
  }

  return (
    <section className="panel setup-panel" aria-label="Session setup">
      <div className="panel-heading">
        <h2>Setup</h2>
        <span className={health?.primary_configured ? 'status-pill live' : 'status-pill demo'}>
          {health?.primary_configured ? `${health.primary_provider} ready` : 'demo fallback'}
        </span>
      </div>
      <div className="field-grid">
        <label>
          Mode
          <select value={form.mode} onChange={(event) => onChange({ ...form, mode: event.target.value as SetupForm['mode'] })}>
            <option value="auto">Auto</option>
            <option value="demo">Demo</option>
            <option value="live">Live</option>
          </select>
        </label>
        <label>
          Session id
          <input value={form.sessionId} onChange={(event) => onChange({ ...form, sessionId: event.target.value })} />
        </label>
        <label>
          Target role
          <input value={form.targetRole} onChange={(event) => onChange({ ...form, targetRole: event.target.value })} />
        </label>
        <label>
          Target companies
          <input
            value={form.targetCompanies}
            onChange={(event) => onChange({ ...form, targetCompanies: event.target.value })}
            placeholder="Viettel, VinAI"
          />
        </label>
        <label>
          Max questions
          <input
            min={1}
            max={10}
            type="number"
            value={form.maxQuestions}
            onChange={(event) => onChange({ ...form, maxQuestions: Number(event.target.value) })}
          />
        </label>
      </div>
      <div className="claim-grid">
        {SKILLS.map((skill) => (
          <label className="slider-field" key={skill}>
            <span>
              {skill}
              <strong>{form.claimedSkills[skill]}</strong>
            </span>
            <input
              min={1}
              max={5}
              step={0.5}
              type="range"
              value={form.claimedSkills[skill]}
              onChange={(event) => setClaim(skill, Number(event.target.value))}
            />
          </label>
        ))}
      </div>
      {errors.length ? (
        <div className="error-box" role="alert">
          {errors.map((error) => (
            <p key={error}>{error}</p>
          ))}
        </div>
      ) : null}
      <div className="setup-actions">
        <button className="primary" onClick={onStart} type="button">
          <Play size={16} aria-hidden />
          Start
        </button>
        <button onClick={onResume} type="button">
          <RotateCcw size={16} aria-hidden />
          Resume
        </button>
      </div>
    </section>
  )
}
