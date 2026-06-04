import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ReportView } from './ReportView'
import { SkillBars } from './SkillBars'
import { TopicPlan } from './TopicPlan'
import { stateFixture } from '../lib/sessionReducer.test'

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
  })
})
