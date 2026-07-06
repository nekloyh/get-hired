# The calibration bench gates every judge change

Any change to the **Evaluator** — its prompt, self-critique thresholds, structured-output path, or
the provider/model behind it — must pass `coach bench` (the hand-labeled, bilingual golden-answer
set, issue 0022) with no range regression before it merges. **A provider swap is a judge change.**
Bench reports — per-dimension bias, EN/VN paired-answer deltas, and confidence calibration — are
versioned in `docs/audits/` so judge quality has a history, not a vibe.

## Why

The entire value chain flows through one LLM judgment: Evaluation → Beta skill state → Supervisor
deviation decisions → Study Plan. ADR 0001's single-judge design is only defensible if the judge
is *measured*; the 2026-07 audit found its trust resting on ~5 golden cases whose expected ranges
cannot even separate a weak answer from a strong one, and — after MiMo's expiry forced a provider
change — **zero** recorded validation of the replacement judge in either language. That is the
proof case: the model behind every score changed, and nothing in the repo would have caught a
drift.

Gating on the bench institutionalizes the project's eval-discipline lesson (goal #1 is learning
agentic patterns): judge meta-evaluation, confidence calibration ("does 0.9 mean right 90% of the
time?"), and drift detection across model swaps are the exact skills the harness exists to teach.

## Considered Options

Relying on the existing `eval-harness` CLI exit code alone was rejected: without hand labels,
per-band anchors, and paired-language cases it can go green while the judge drifts on precisely
the axes the product depends on (weak/strong separation, VN parity). Continuous live testing in CI
was rejected for cost and flakiness on free-tier providers — the bench is a deliberate,
pre-merge, human-triggered gate.
