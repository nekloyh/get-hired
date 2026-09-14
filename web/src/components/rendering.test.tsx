import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ReportView } from './ReportView'
import { SessionAlert } from './SessionAlert'
import { SkillBars } from './SkillBars'
import { TopicPlan } from './TopicPlan'
import { stateFixture, withEvaluation } from '../test/fixtures'

describe('Skill and progress rendering', () => {
  it('renders mastery, confidence context, and role criticality', () => {
    render(<SkillBars state={stateFixture} />)

    expect(screen.getByText('mlops')).toBeInTheDocument()
    expect(screen.getByText('60%')).toBeInTheDocument()
    expect(screen.getByText(/confidence/)).toBeInTheDocument()
    expect(screen.getByText('must_have')).toBeInTheDocument()
  })

  it('renders Topic Plan and Supervisor markers', () => {
    render(<TopicPlan state={stateFixture} />)

    expect(screen.getByText('mlops')).toBeInTheDocument()
    expect(screen.getByText('end_early')).toBeInTheDocument()
    expect(screen.getByText('Hard cap reached.')).toBeInTheDocument()
  })
})

describe('session alert', () => {
  it('renders a session error with the message and recovery actions', () => {
    render(
      <SessionAlert
        error="LLM primary provider 'openai' is not configured."
        onBackToSetup={() => {}}
        onReconnect={() => {}}
        status="error"
      />,
    )

    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText(/not configured/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Reconnect/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Back to Setup/ })).toBeInTheDocument()
  })

  it('renders a disconnected banner with a default resume message', () => {
    render(<SessionAlert error={null} onBackToSetup={() => {}} onReconnect={() => {}} status="disconnected" />)

    expect(screen.getByText('Connection lost')).toBeInTheDocument()
    expect(screen.getByText(/reconnect to resume/i)).toBeInTheDocument()
  })

  it('renders nothing while the Session is healthy', () => {
    const { container } = render(
      <SessionAlert error={null} onBackToSetup={() => {}} onReconnect={() => {}} status="active" />,
    )

    expect(container).toBeEmptyDOMElement()
  })
})

describe('report rendering', () => {
  it('renders readiness, resources, schedule, transcript, and evaluation detail', () => {
    render(<ReportView state={stateFixture} />)

    expect(screen.getByLabelText('Final report')).toBeInTheDocument()
    expect(screen.getByText('62%')).toBeInTheDocument()
    expect(screen.getByText('Google Rules of ML')).toBeInTheDocument()
    expect(screen.getByText('Day 1 focus')).toBeInTheDocument()
    expect(screen.getByText(/Q1 mlops/)).toBeInTheDocument()
    expect(screen.getByText('correctness:')).toBeInTheDocument()
    expect(screen.getByText('Enough evidence for demo.')).toBeInTheDocument()
    expect(screen.queryByText(/citations unverifiable/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Committee verdict')).not.toBeInTheDocument()
  })

  it('badges an evidence-degraded evaluation (issue 0033)', () => {
    render(<ReportView state={withEvaluation({ evidence_degraded: true })} />)

    expect(screen.getByText('citations unverifiable — confidence capped')).toBeInTheDocument()
    expect(screen.queryByLabelText('Committee verdict')).not.toBeInTheDocument()
  })

  it('renders the Committee verdict when the evaluation carries a panel trace (issue 0027)', () => {
    const panel = {
      triggers: ['low_confidence', 'divergence'],
      skeptic: { recommended_score: 2, argument: 'Thin on rollback.', key_evidence: 'rollback risk' },
      advocate: { recommended_score: 4, argument: 'Names delayed labels.', key_evidence: 'delayed labels' },
      initial_score: 2.5,
      initial_confidence: 0.4,
      disagreement: 2,
    }
    render(<ReportView state={withEvaluation({ panel, weighted_score: 3.5 })} />)

    const block = screen.getByLabelText('Committee verdict')
    expect(block).toHaveTextContent('Escalated on low_confidence, divergence')
    expect(block).toHaveTextContent('First pass 2.50/5 → verdict 3.50/5 · disagreement 2.00 points')
    expect(block).toHaveTextContent('Skeptic 2/5 · Advocate 4/5')
    expect(screen.queryByText(/citations unverifiable/)).not.toBeInTheDocument()
  })
})
