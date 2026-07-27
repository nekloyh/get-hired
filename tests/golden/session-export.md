# Interview Session: alice-traj

## Summary

- Status: `complete`
- Stop reason: `max_questions`
- Questions: `3`
- Language mode: `en`

## Final Skill States

| Skill | Mastery | Confidence | Beta | Role criticality |
| --- | ---: | ---: | --- | --- |
| `deep_learning` | 0.398 | 0.453 | alpha=1.70, beta=2.56 | core |
| `ml_fundamentals` | 0.384 | 0.400 | alpha=1.43, beta=2.30 | must_have |
| `mlops` | 0.384 | 0.400 | alpha=1.43, beta=2.30 | must_have |
| `system_design` | 0.500 | 0.150 | alpha=1.26, beta=1.26 | core |
| `vietnamese_nlp` | 0.500 | 0.300 | alpha=1.64, beta=1.64 | peripheral |

## Topic Plan

| # | Skill | Difficulty | Rationale |
| ---: | --- | ---: | --- |
| 1 | `ml_fundamentals` | 3 | must_have for the target role; start near difficulty 3 from the Candidate's weak prior (mastery 0.50, evidence bar 4.0) |
| 2 | `mlops` | 3 | must_have for the target role; start near difficulty 3 from the Candidate's weak prior (mastery 0.50, evidence bar 4.0) |
| 3 | `deep_learning` | 3 | core for the target role; start near difficulty 3 from the Candidate's weak prior (mastery 0.50, evidence bar 3.0) |
| 4 | `system_design` | 3 | core for the target role; start near difficulty 3 from the Candidate's weak prior (mastery 0.50, evidence bar 3.0) |
| 5 | `vietnamese_nlp` | 3 | peripheral for the target role; start near difficulty 3 from the Candidate's weak prior (mastery 0.50, evidence bar 2.0) |

## Transcript

### Question 1: `ml_fundamentals`

Resolved score: **2.00/5**; confidence: **0.82**; evidence weight: **1.73**; stop: `resolved`.

#### Turn 1: Question

**Interviewer:** You have a 1-to-100 imbalanced dataset. Walk me through training and evaluating a classifier on it without fooling yourself.

**Candidate:** A strong answer.

| Dimension | Score | Evidence |
| --- | ---: | --- |
| correctness | 2 | A strong answer. |
| depth | 2 | A strong answer. |
| communication | 2 | A strong answer. |
| system_thinking | 2 | A strong answer. |

Weighted score: **2.00/5**; confidence: **0.82**; follow-up recommended: `False`.
Rationale: Demo Evaluator keeps the loop short so the web workflow can be reviewed.

### Question 2: `mlops`

Resolved score: **2.00/5**; confidence: **0.82**; evidence weight: **1.73**; stop: `resolved`.

#### Turn 1: Question

**Interviewer:** How would you monitor a production model for data drift and decide when retraining is actually justified?

**Candidate:** A weak answer.

| Dimension | Score | Evidence |
| --- | ---: | --- |
| correctness | 2 | A weak answer. |
| depth | 2 | A weak answer. |
| communication | 2 | A weak answer. |
| system_thinking | 2 | A weak answer. |
| mlops_awareness | 2 | A weak answer. |

Weighted score: **2.00/5**; confidence: **0.82**; follow-up recommended: `False`.
Rationale: Demo Evaluator keeps the loop short so the web workflow can be reviewed.

### Question 3: `deep_learning`

Resolved score: **2.00/5**; confidence: **0.82**; evidence weight: **1.73**; stop: `resolved`.

#### Turn 1: Question

**Interviewer:** When would you choose SGD with momentum over Adam, and what does AdamW change?

**Candidate:** A strong answer.

| Dimension | Score | Evidence |
| --- | ---: | --- |
| correctness | 2 | A strong answer. |
| depth | 2 | A strong answer. |
| communication | 2 | A strong answer. |
| system_thinking | 2 | A strong answer. |

Weighted score: **2.00/5**; confidence: **0.82**; follow-up recommended: `False`.
Rationale: Demo Evaluator keeps the loop short so the web workflow can be reviewed.

## Supervisor Decisions

- After Q1: `advance_plan` (deviation=`False`) - Demo Supervisor follows the Topic Plan unless a hard cap completes the Session.
- After Q2: `advance_plan` (deviation=`False`) - Demo Supervisor follows the Topic Plan unless a hard cap completes the Session.
- After Q3: `end_early` (deviation=`True`) - Hard cap reached: max_questions bound the Session before any LLM deviation choice.

## Study Plan

Readiness estimate: **58%**. Demo estimate: usable baseline with several targeted gaps to practice.

### Prioritized Topics

1. **Sharpen ml fundamentals** (`ml_fundamentals`) - Demo Study Planner prioritizes the weakest or most role-critical Skill state.
   Target: Give a concise answer with mechanism, trade-off, and deployment implication.; current mastery 38%; criticality `must_have`.
   - [scikit-learn: Cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html)
   - [scikit-learn: Ridge regression and L2 regularization](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html)
2. **Sharpen mlops** (`mlops`) - Demo Study Planner prioritizes the weakest or most role-critical Skill state.
   Target: Give a concise answer with mechanism, trade-off, and deployment implication.; current mastery 38%; criticality `must_have`.
   - [Google: Rules of Machine Learning](https://developers.google.com/machine-learning/guides/rules-of-ml)
   - [Google Cloud: ML applications and operations architecture guides](https://docs.cloud.google.com/architecture/ai-ml/ml-application-operations-architecture-guides)
3. **Sharpen deep learning** (`deep_learning`) - Demo Study Planner prioritizes the weakest or most role-critical Skill state.
   Target: Give a concise answer with mechanism, trade-off, and deployment implication.; current mastery 40%; criticality `core`.
   - [Dive into Deep Learning: Residual Networks](https://d2l.ai/chapter_convolutional-modern/resnet.html)
   - [PyTorch Tutorial: Transfer Learning for Computer Vision](https://docs.pytorch.org/tutorials/beginner/transfer_learning_tutorial.html)

### Two-Week Schedule

| Day | Focus | Resources | Outcome |
| ---: | --- | --- | --- |
| 1 | Practice ml fundamentals | [scikit-learn: Cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) | Write one answer with a concrete trade-off and failure mode. |
| 2 | Practice mlops | [scikit-learn: Ridge regression and L2 regularization](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html) | Write one answer with a concrete trade-off and failure mode. |
| 3 | Practice deep learning | [Google: Rules of Machine Learning](https://developers.google.com/machine-learning/guides/rules-of-ml) | Write one answer with a concrete trade-off and failure mode. |
| 4 | Practice ml fundamentals | [Google Cloud: ML applications and operations architecture guides](https://docs.cloud.google.com/architecture/ai-ml/ml-application-operations-architecture-guides) | Write one answer with a concrete trade-off and failure mode. |
| 5 | Practice mlops | [Dive into Deep Learning: Residual Networks](https://d2l.ai/chapter_convolutional-modern/resnet.html) | Write one answer with a concrete trade-off and failure mode. |
| 6 | Practice deep learning | [PyTorch Tutorial: Transfer Learning for Computer Vision](https://docs.pytorch.org/tutorials/beginner/transfer_learning_tutorial.html) | Write one answer with a concrete trade-off and failure mode. |
| 7 | Review and mock interview synthesis |  | Record one timed answer and compare it against the rubric. |
| 8 | Practice mlops | [scikit-learn: Ridge regression and L2 regularization](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html) | Write one answer with a concrete trade-off and failure mode. |
| 9 | Practice deep learning | [Google: Rules of Machine Learning](https://developers.google.com/machine-learning/guides/rules-of-ml) | Write one answer with a concrete trade-off and failure mode. |
| 10 | Practice ml fundamentals | [Google Cloud: ML applications and operations architecture guides](https://docs.cloud.google.com/architecture/ai-ml/ml-application-operations-architecture-guides) | Write one answer with a concrete trade-off and failure mode. |
| 11 | Practice mlops | [Dive into Deep Learning: Residual Networks](https://d2l.ai/chapter_convolutional-modern/resnet.html) | Write one answer with a concrete trade-off and failure mode. |
| 12 | Practice deep learning | [PyTorch Tutorial: Transfer Learning for Computer Vision](https://docs.pytorch.org/tutorials/beginner/transfer_learning_tutorial.html) | Write one answer with a concrete trade-off and failure mode. |
| 13 | Practice ml fundamentals | [scikit-learn: Cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) | Write one answer with a concrete trade-off and failure mode. |
| 14 | Review and mock interview synthesis |  | Record one timed answer and compare it against the rubric. |

### Milestones

- Week 1: Answer the top-priority Skill without notes. (evidence: A recorded three-minute answer covers mechanism and trade-offs.)
- Week 2: Run a mixed mock interview under time pressure. (evidence: Every planned Skill has one complete answer and one Follow-up response.)
