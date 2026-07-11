# Question Forge run — mlops

- Date: 2026-07-11
- Judge provider: openai — model: gpt-5.4-mini
  (the configured primary; a mid-run provider failover silently swaps the judge — check WARNING logs before trusting borderline admissions)
- Requested drafts: 3
- Admission bands: strong 3.5-5.0 / weak 1.0-3.0

## Per-gate yield

- drafted: 3
- gate 1 (contract): 3 -> 3
- gate 2 (novelty): 3 -> 3
- gate 3 (admission): 3 -> 3
- admitted: 3/3

## Per-draft outcomes

| # | question | verdict | gate | detail |
|---|----------|---------|------|--------|
| 1 | You own a fraud model that is deployed in real time. Two weeks after … | ADMITTED | - | nearest: Your fraud model reports 99% accuracy, … (sim 0.18); strong 5.00; weak 2.00 |
| 2 | A team wants to add CI/CD to an ML pipeline that trains a churn model… | ADMITTED | - | nearest: A model scores well in a notebook but d… (sim 0.18); strong 5.00; weak 3.00 |
| 3 | You are choosing how to evaluate and serve a recommendation model for… | ADMITTED | - | nearest: A model scores well in a notebook but d… (sim 0.15); strong 5.00; weak 3.00 |

## Rejection attribution

- (none)
