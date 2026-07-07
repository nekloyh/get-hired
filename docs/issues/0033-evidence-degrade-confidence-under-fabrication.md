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

- [ ] A judgment whose evidence was entirely blanked no longer reads as full-confidence (via a
      confidence haircut or an explicit degrade flag)
- [ ] The change is re-checked against `coach bench` (confidence-calibration table) so it does not
      regress the calibrated hit-rate

## Blocked by

None. Not urgent — the current behavior is safe, just not maximally skeptical.

## Status

**Open.**
