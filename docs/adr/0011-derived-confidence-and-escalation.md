# Derived confidence replaces self-reported confidence as the control signal

**Status: Proposed — gated on experiments E4 (calibration) and E5 (shadow cutover). Not applied
to code until Accepted.**

The Evaluator's control signal for reflection and evidence weighting becomes **derived
confidence** — uncertainty computed from *measured* disagreement between independent judge passes
— instead of the judge's self-reported `confidence` field. Escalation triggers (self-critique,
Panel Verdict) move to the deterministic set already drafted in R-16 (GH #71), with derived
confidence as the graded input where a graded signal is needed.

## Why

Self-reported confidence was never decided as an architecture — it accreted — and it is now the
single control signal behind three mechanisms, **all measurably dead on the current judge**
(gpt-5.4-mini, audits 2026-07-11):

- **Self-critique trigger** (`< 0.5`, `evaluator.py:340`): confidence sits ≥0.90 on 20/20 bench
  cases (mean 0.95) — the trigger is dormant.
- **Confidence-weighted evidence** (issue 0021, `skill.py`): the weight range collapsed to
  [1.93, 2.0] out of [0.5, 2.0] — functionally inert except through its deterministic caps.
- **Panel Verdict escalation** (issue 0027): 0/10 natural escalations.

Meanwhile the forced-escalation experiment produced a signal that *does* discriminate: committee
disagreement (Skeptic vs Advocate spread) converged to 0.0 on clear-cut cases and split to 2.0 on
the genuinely ambiguous ones — and the same experiment showed debate-as-score-corrector is
worthless on this judge (verdict moved 0.00 across 10 forced escalations). The reshape this ADR
proposes is therefore **not** multi-judge consensus for accuracy (measured: no effect) but cheap
multi-vote for *uncertainty*: with 2026-07-19 verified pricing, 3 votes on Groq `gpt-oss-20b`
(~$0.001/answer) cost a quarter of one gpt-5.4-mini pass (~$0.004) — the economics of the original
"multi-judge consensus" deferral have inverted for this narrow use.

## Design under trial

- K=3 cheap single-shot votes per answer (strict `json_schema` decoding; no tools — ADR 0003);
  `derived_confidence = f(vote spread)`, calibrated on the bench.
- The decider stays a single judge (ADR 0001 unchanged): votes inform *uncertainty*, never the
  score.
- Escalation triggers become deterministic (R-16 list: cross-check divergence, evidence-degrade /
  unverifiable fraction, score-without-evidence, residual low-confidence guard), with derived
  confidence replacing the dead self-report in the residual guard and in `confidence_weight`.

## Gates

- **E4 (calibration, on `coach bench`):** run the K-vote packet over the 29 cases; compare the
  existing `confidence_calibration` table for derived vs self-reported. *Win:* derived-confidence
  buckets are monotone with hit-rate (self-report currently occupies a single saturated bucket)
  AND median-of-3-cheap-votes stays ≥27/29 in-band. *Lose:* spread is as flat as self-report —
  this ADR is marked Rejected and the deterministic triggers proceed alone under R-16.
- **E5 (shadow cutover):** 100 shadow sessions with consumers switched; fire-rate lands in the
  R-16 bands (self-critique 5–15%, panel 2–5%) with verdict-changed-rate > 0; `coach bench` stays
  green under ADR 0009 (trigger thresholds are part of the judge).

## Considered Options

- **Recalibrating the 0.5 threshold against the model's real confidence distribution:** rejected
  — the distribution is a point mass (≈0.95); any threshold is either always-on or never-on.
- **Full multi-judge consensus (average N judges' scores):** re-examined and re-rejected *with
  data this time* — forced escalation moved no verdict; paying N× for the score buys nothing on
  this judge. The deferral shape changed: votes are for uncertainty only.
- **Prompting the judge to self-report better ("be conservative"):** rejected — retunes a vibe;
  the audit history shows prompt-side confidence surgery does not survive model swaps.

*Source: ADR red-team review 2026-07-19 — PHẦN 2 (reopened deferral: multi-judge consensus, new
shape) and implicit decision #1 (self-reported confidence as master signal, never decided); panel
report chí-mạng #4 (dormant quality machinery); forced-escalation audit 2026-07-11.*
