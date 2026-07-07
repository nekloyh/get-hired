# Judge Calibration Bench

- Date: `2026-07-07`
- Provider / model: `openai` / `gpt-4o-mini`
- Cases within band: **18/20**

## Calibration history

This run reflects two judge fixes gated by this bench (ADR 0009 loop):

1. **Evidence-verbatim degrade** — the first run crashed 3 strong cases with
   `StructuredOutputError` (gpt-4o-mini paraphrased its citation past the retry). The judge now
   NFC-normalizes evidence and, when a quote survives unverifiable, sanitizes it and keeps the
   score. All 20 cases now evaluate; no crashes.
2. **Rubric anchor tuning** (`rubric.py` `DIMENSION_GUIDE`) — aligned the `correctness` and
   `system_thinking` anchors to the BARS exemplars below.

Per-dimension bias, before → after:

| dimension | before (baseline) | after (this run) |
| --- | ---: | ---: |
| correctness | +0.53 | **−0.05** |
| system_thinking | −0.53 | **−0.20** |
| separation gap | 2.40 | **2.57** |

Residual: two Vietnamese cases miss the band in **opposite** directions
(`dl_overfitting_strong_vi` under, `vnlp_segmentation_weak_vi` over) while their English twins are
in-band — a VN scoring-consistency gap (not a directional bias), filed as issue 0031.

## Per-case scores

| case | skill | lang | expected | score | conf | in-band |
| --- | --- | --- | --- | ---: | ---: | :---: |
| ml_bias_variance_weak_en | ml_fundamentals | en | 1.0-2.6 | 1.00 | 0.80 | ✅ |
| ml_bias_variance_weak_vi | ml_fundamentals | vi | 1.0-2.6 | 1.00 | 0.80 | ✅ |
| ml_bias_variance_strong_en | ml_fundamentals | en | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| ml_bias_variance_strong_vi | ml_fundamentals | vi | 3.8-5.0 | 4.00 | 0.80 | ✅ |
| ml_regularization_medium_en | ml_fundamentals | en | 2.8-4.2 | 4.00 | 0.80 | ✅ |
| ml_regularization_medium_vi | ml_fundamentals | vi | 2.8-4.2 | 3.00 | 0.80 | ✅ |
| dl_overfitting_weak_en | deep_learning | en | 1.6-3.2 | 3.00 | 0.80 | ✅ |
| dl_overfitting_weak_vi | deep_learning | vi | 1.6-3.2 | 3.00 | 0.80 | ✅ |
| dl_overfitting_strong_en | deep_learning | en | 3.8-5.0 | 4.00 | 1.00 | ✅ |
| dl_overfitting_strong_vi | deep_learning | vi | 3.8-5.0 | 3.00 | 0.80 | ❌ |
| vnlp_segmentation_weak_en | vietnamese_nlp | en | 1.0-2.6 | 1.00 | 0.80 | ✅ |
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

- mean weak-labelled score: 1.33
- mean strong-labelled score: 3.90
- separation gap: 2.57

## EN vs VN paired deltas

| paired_id | EN | VN | |Δ| |
| --- | ---: | ---: | ---: |
| dl_overfitting_strong | 4.00 | 3.00 | 1.00 |
| dl_overfitting_weak | 3.00 | 3.00 | 0.00 |
| ml_bias_variance_strong | 4.00 | 4.00 | 0.00 |
| ml_bias_variance_weak | 1.00 | 1.00 | 0.00 |
| ml_regularization_medium | 4.00 | 3.00 | 1.00 |
| mlops_monitoring_strong | 4.00 | 4.00 | 0.00 |
| prompt_injection | 1.00 | 1.00 | 0.00 |
| sd_backpressure_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_weak | 1.00 | 3.00 | 2.00 |

- mean |Δ|: 0.40; max |Δ|: 2.00

## Confidence calibration

| confidence bucket | n | mean conf | hit rate |
| --- | ---: | ---: | ---: |
| [0.7,0.9] | 10 | 0.80 | 80% |
| [0.9,1.0] | 10 | 0.94 | 100% |

## BARS anchors used for labelling

- **system_thinking** — 2: Mentions a fix in isolation ("add more data", "use dropout") without connecting it to a diagnosis, trade-off, or downstream effect. | 4: Reasons about the interaction: names a diagnosis, the trade-off it drives, and the consequence of the chosen fix on other parts of the system (e.g. "regularise, but that raises bias, so I cross-validate the strength").
- **correctness** — 2: Contains a real technical error or a vague statement that is only half-right (e.g. "L2 makes weights smaller which is always better"). | 4: Technically accurate with the key mechanism stated correctly, even if not exhaustive (e.g. "L2 penalises squared weights, trading a little fit for lower variance").
