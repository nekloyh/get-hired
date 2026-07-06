# Language is first-class Session state; delivery is scored apart from knowledge

A Session carries an explicit `language_mode` — `en` | `vn` | `mixed` — chosen at setup and
threaded through the Session state; every prompt-bearing agent (Interviewer, Evaluator, Study
Planner) must respect it. English communication quality is scored in a dedicated
`english_delivery` rubric dimension that is active only when the answer is in English (weight-0
disable otherwise, the existing rubric mechanic). The five technical dimensions must remain
language-independent: paired EN/VN golden answers in the calibration bench (ADR 0009) are the
regression proof that the same technical content scores the same in either language.

## Why

Real Vietnamese technical interviews code-switch — a VN conversation with EN terms, or an EN round
inside a VN process. Leaving language implicit makes the judge conflate an English-communication
gap with a knowledge gap, which is the single most common misread of Vietnamese fresh-grad
candidates — and an entangled score poisons the Bayesian skill state: a genuinely strong
`deep_learning` answer delivered in halting English would lower `deep_learning` mastery, steering
the Supervisor and the Study Plan at the wrong target.

Separating the axes is also the product's most differentiated feedback: "your knowledge is 4/5,
your English delivery of it is 2/5, and here are the three phrases to fix" — something neither
global interview tools (EN-only) nor generic chatbots provide.

## Considered Options

Scoring language inside the existing `communication` dimension was rejected: it re-entangles the
axes the moment weights are tuned, and gives no way to run a pure-VN Session where English is
simply not assessed. A separate dimension with weight-0 disable needs no rubric surgery.
