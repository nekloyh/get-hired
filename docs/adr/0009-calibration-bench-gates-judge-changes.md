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

## Addendum (2026-07-19): gate-as-code, measurement ceiling, and the two-bench contract

Three extensions, each closing a hole the original text left open.

### (a) The gate must also hold at runtime: the judge role is pinned

This ADR gates *merges*, but the router un-gates the judge *at runtime*: a single transient
primary-provider error trips the blanket `except Exception` failover (`llm.py:392`) and the
hardcoded preference order (`config.py:69`) hands the judge role to Groq `llama-3.3-70b` — a model
that **fails this bench** (18/20, known VN over-scoring Δ=2.00) — silently, mid-Session, logged
only as a warning. A merge gate with a runtime hole is not a gate.

Decision: **the judge role is pinned to a model with a green bench artifact in `docs/audits/`.**
Judge-role failover is retry-same-model, degrade, or suspend (ADR 0005's budget-exhaustion
addendum) — **never a model swap**. Other roles may fail over freely. Implemented by the per-role
router (ADR 0010, R-18/GH #73) and the typed-failover work (R-09/GH #64); until those land, every
audit must state which model actually judged.

### (b) The measurement has a ceiling: labels and repeatability

The gate is currently a **single run of a stochastic judge** (global `LLM_TEMPERATURE=0.2`) over
n=29 cases labeled by one rater. That ceiling is now measured, not hypothetical: k=3 identical
runs on 2026-07-19 returned 28/29, 28/29, 29/29 — `dl_overfitting_weak_vi` scored 3.30/3.30/3.20
against a band top of 3.2, after passing 3/3 on 2026-07-11 on an unchanged judge path
(`docs/audits/calibration-bench-2026-07-19.md`, GH #92). The band edge sits inside the judge's
score distribution; single-run green/red on that case is a coin flip, and provider-side drift is
real (the communication bias flipped +0.65 → −0.28 between the two dates).

Decision: the judge role runs the bench at `temperature=0` **or** the gate becomes median-of-k
(k=3) per case — one of the two, recorded when implemented (GH #92). Bands are set from a score
*distribution* (k runs), never from a single observation, and never widened just to go green (the
one-way-ratchet failure). New labels enter from two provenances beyond the original rater: the
Forge review queue (`data/bench/pending-cases-*.yaml`) and replayed live-session answers — both
human-reviewed before admission.

### (c) The two-bench contract

`coach bench` measures **the judge** (scores vs hand labels). The replay bench (issue 0029)
measures **the loop** (does the Session's trajectory recover a persona's ground truth). Every
architecture experiment must name its gate up front: judge-touching changes gate on `coach bench`
(this ADR); Supervisor/evidence-semantics changes gate on the replay bench (experiments E1/E2);
changes touching both gate on both. "It passed a bench" without naming which one is not evidence.

*Source: ADR red-team review 2026-07-19 — verdict REAFFIRM + 3 AMENDs; Wave-0 execution k=3 data
(GH #92); remediation decisions B1 (judge pinning) and the R-15/R-17 label/backup-judge program.*
