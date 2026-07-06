# Bilingual Judge calibration bench

**Type:** HITL
**Kind:** enhancement

## What to build

The Evaluator is the single judge everything downstream trusts (ADR 0001), and that trust is
currently vibes: the harness holds ~5 golden cases whose expected ranges give no weak/strong
separation, and after the forced provider change nothing has measured the judge at all — in
either language. Grow `eval-harness` into a calibration bench:

- **~20 hand-labeled golden cases** across at least two Skills, each with **EN and VN paired
  answer variants**, labeled on the 5-dimension rubric by a human.
- **BARS-style per-band anchors** for at least two dimensions: concrete exemplars of what a 2
  vs a 4 on `system_thinking` sounds like, so labels (and future labelers) stay consistent.
- **`coach bench`**: runs the set live against the configured provider and writes a Markdown
  calibration report into `docs/audits/` — per-dimension bias vs hand labels, weak/strong
  separation, EN-vs-VN deltas on paired answers, and a confidence-calibration table (when the
  Evaluator says 0.9, is it right ~90% of the time?). Non-zero exit on range regression, same
  convention as today's harness.

HITL because hand-labeling and anchor authoring are human judgment; the harness/report plumbing
is AFK-able. Per ADR 0009, once this lands the bench gates every judge change — prompt, threshold,
or provider.

## Acceptance criteria

- [ ] ≥20 golden cases with EN + VN paired answers, human labels on the 5-dim rubric, and
      per-band anchors for ≥2 dimensions
- [ ] `coach bench` runs live, writes the calibration report to `docs/audits/`, and exits
      non-zero on regression vs recorded ranges
- [ ] Report covers per-dimension bias, weak/strong separation, EN/VN paired deltas, and
      confidence calibration
- [ ] The prompt-injection adversarial case is retained and gets a VN twin
- [ ] README documents the bench as the pre-merge gate for judge changes (ADR 0009)

## Blocked by

- 0015 (a working live provider is the whole point)
- ADR 0009 (the gate policy this implements)

## Status

**Open.**
