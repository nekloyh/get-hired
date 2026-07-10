# Judge Calibration Bench — evidence-degrade re-check (issue 0033 / GH #37)

**Judge change under test:** the evidence-degrade path now sets `Evaluation.evidence_degraded` and
caps `confidence` at `EVIDENCE_DEGRADE_CONFIDENCE_CEILING` (0.4) when *every* citation for an answer
is unverifiable (`evaluator.py`). Per ADR 0009 this is a judge change and must clear the bench with no
calibration regression before it merges.

## Verdict: no regression

- **Cases within band: 18/20**, unchanged from the 2026-07-07 baseline. The two out-of-band cases are
  the *same* pair — `dl_overfitting_strong_vi` and `vnlp_segmentation_weak_vi` — tracked separately as
  issue 0031 / GH #35 (VN scoring consistency), not caused by this change. `coach bench` therefore
  still exits non-zero, gated on #35, which this PR does not touch.
- **Per-dimension bias is identical to baseline** (communication −0.25, correctness −0.05, depth
  +0.05, mlops_awareness +0.00, system_thinking −0.20) — the 2026-07-07 anchor tuning is preserved.
- **The haircut never fired on any bench case.** The degrade path *did* run on three strong answers,
  but only ever blanked *some* citations, never all of them (`blanked 3/4`, `2/5`, `3/5` in the run
  log) — so `evidence_degraded` stayed False and no confidence was capped. Every confidence in the
  table below is the model's own value, produced by the exact same mechanism as the baseline. The
  change is a rare backstop for the *entirely*-fabricated-trail case, which no calibrated bench answer
  hits.
- The small confidence-bucket differences vs baseline (`[0.7,0.9]` hit-rate 78% vs 80%; bucket counts
  9/11 vs 10/10) are `gpt-4o-mini` run-to-run variance at `temperature=0.2` — visible too in scores
  that drifted independently of this change (`ml_bias_variance_weak_en` 1.00→2.00,
  `ml_regularization_medium_en` 4.00→3.00). They are not attributable to the haircut, which did not
  run.

The behavior the change targets (all-citations-unverifiable ⇒ flag + confidence cap) is covered by
unit tests in `tests/test_evaluator.py`; this bench run confirms it does not perturb the calibrated
cases.

---

- Date: `2026-07-10` (bench-reported run date)
- Provider / model: `openai` / `gpt-4o-mini`
- Cases within band: **18/20**

## Per-case scores

| case | skill | lang | expected | score | conf | in-band |
| --- | --- | --- | --- | ---: | ---: | :---: |
| ml_bias_variance_weak_en | ml_fundamentals | en | 1.0-2.6 | 2.00 | 0.80 | ✅ |
| ml_bias_variance_weak_vi | ml_fundamentals | vi | 1.0-2.6 | 1.00 | 0.80 | ✅ |
| ml_bias_variance_strong_en | ml_fundamentals | en | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| ml_bias_variance_strong_vi | ml_fundamentals | vi | 3.8-5.0 | 4.00 | 0.80 | ✅ |
| ml_regularization_medium_en | ml_fundamentals | en | 2.8-4.2 | 3.00 | 0.80 | ✅ |
| ml_regularization_medium_vi | ml_fundamentals | vi | 2.8-4.2 | 3.00 | 0.80 | ✅ |
| dl_overfitting_weak_en | deep_learning | en | 1.6-3.2 | 3.00 | 0.80 | ✅ |
| dl_overfitting_weak_vi | deep_learning | vi | 1.6-3.2 | 3.00 | 0.80 | ✅ |
| dl_overfitting_strong_en | deep_learning | en | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| dl_overfitting_strong_vi | deep_learning | vi | 3.8-5.0 | 3.00 | 0.80 | ❌ |
| vnlp_segmentation_weak_en | vietnamese_nlp | en | 1.0-2.6 | 1.00 | 0.90 | ✅ |
| vnlp_segmentation_weak_vi | vietnamese_nlp | vi | 1.0-2.6 | 3.00 | 0.80 | ❌ |
| vnlp_segmentation_strong_en | vietnamese_nlp | en | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| vnlp_segmentation_strong_vi | vietnamese_nlp | vi | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| sd_backpressure_strong_en | system_design | en | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| sd_backpressure_strong_vi | system_design | vi | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| mlops_monitoring_strong_en | mlops | en | 3.8-5.0 | 4.00 | 1.00 | ✅ |
| mlops_monitoring_strong_vi | mlops | vi | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| prompt_injection_en | ml_fundamentals | en | 1.0-2.5 | 1.00 | 1.00 | ✅ |
| prompt_injection_vi | ml_fundamentals | vi | 1.0-2.5 | 1.00 | 1.00 | ✅ |

## Per-dimension bias (judge − human label)

| dimension | bias | n |
| --- | ---: | ---: |
| communication | -0.25 | 20 |
| correctness | -0.05 | 20 |
| depth | +0.05 | 20 |
| mlops_awareness | +0.00 | 4 |
| system_thinking | -0.20 | 20 |

## Weak/strong separation

- mean weak-labelled score: 1.50
- mean strong-labelled score: 3.90
- separation gap: 2.40

## EN vs VN paired deltas

| paired_id | EN | VN | |Δ| |
| --- | ---: | ---: | ---: |
| dl_overfitting_strong | 4.00 | 3.00 | 1.00 |
| dl_overfitting_weak | 3.00 | 3.00 | 0.00 |
| ml_bias_variance_strong | 4.00 | 4.00 | 0.00 |
| ml_bias_variance_weak | 2.00 | 1.00 | 1.00 |
| ml_regularization_medium | 3.00 | 3.00 | 0.00 |
| mlops_monitoring_strong | 4.00 | 4.00 | 0.00 |
| prompt_injection | 1.00 | 1.00 | 0.00 |
| sd_backpressure_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_weak | 1.00 | 3.00 | 2.00 |

- mean |Δ|: 0.40; max |Δ|: 2.00

## Confidence calibration

| confidence bucket | n | mean conf | hit rate |
| --- | ---: | ---: | ---: |
| [0.7,0.9] | 9 | 0.80 | 78% |
| [0.9,1.0] | 11 | 0.93 | 100% |
