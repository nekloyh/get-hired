# Evidence degrade keeps full confidence even when every citation is unverifiable

**Type:** AFK
**Kind:** enhancement
**Tracked on GitHub:** [#37](https://github.com/nekloyh/get-hired/issues/37)

## What to build

Raised during the PR #34 review of the new evidence degrade path (`evaluator.py`, added alongside
the judge crash-proofing fix).

When the Evaluator's evidence quote survives the enforced retry unverifiable, `_evaluate_once`
degrades: it re-runs without the hard evidence check and `_sanitize_unverifiable_evidence` blanks
the bad quote(s) to `UNVERIFIABLE_EVIDENCE` while **keeping the score at full confidence**. This is
deliberate — "a valid score must never be lost to an unverifiable quote."

The edge case worth hardening: if the model fabricates the evidence for **every** dimension, that is
a strong hallucination signal, yet we currently accept the judgment with a full audit-trail wipe and
unchanged confidence. Nothing signals downstream that the citation trail was entirely unverifiable.

## Possible directions

- Apply a `confidence` haircut proportional to the fraction of dimensions whose evidence was blanked
  (e.g. all-blanked ⇒ cap confidence low, mirroring the weighted-score cross-check ceiling).
- Or record an `evidence_degraded` flag on the `Evaluation` so the export/UI can surface "scored,
  but citations unverifiable."

## Acceptance criteria

- [x] A judgment whose evidence was entirely blanked no longer reads as full-confidence (via a
      confidence haircut or an explicit degrade flag)
- [x] The change is re-checked against `coach bench` (confidence-calibration table) so it does not
      regress the calibrated hit-rate

## Resolution

Both directions, together. `_sanitize_unverifiable_evidence` now sets a new `evidence_degraded` flag
on the `Evaluation` when *every* dimension's citation was blanked (an entirely fabricated audit
trail), and `apply_evidence_degrade_haircut` caps `confidence` at `EVIDENCE_DEGRADE_CONFIDENCE_CEILING`
(0.4, mirroring the weighted-score cross-check ceiling) for that judgment — never raising confidence,
idempotent, and applied to the pass actually kept so a self-critique that restored verifiable evidence
is not penalised. A *partial* blank keeps today's behavior (score + confidence intact): only a wholly
unverifiable trail is treated as the hallucination signal. The exporter surfaces a "scored, but
citations unverifiable" warning so the audit gap is visible downstream.

Verified against `coach bench` (ADR 0009) on `openai`/`gpt-4o-mini`:
`docs/audits/calibration-bench-2026-07-11-evidence-degrade.md` — **18/20 within band**, unchanged from
the 2026-07-07 baseline, per-dimension bias identical, and the haircut never fired on a calibrated
case (bench answers only partially degrade, never wholly), so calibration is provably unaffected. The
two remaining reds are the separate VN-consistency bug (issue 0031 / #35). Unit coverage in
`tests/test_evaluator.py` (entirely-blanked ⇒ flag + cap; partial ⇒ neither; happy path ⇒ neither;
min() never raises) and `tests/test_study_planner.py` (export surfacing).

## Blocked by

None. Not urgent — the current behavior is safe, just not maximally skeptical.

## Status

**Closed.**
