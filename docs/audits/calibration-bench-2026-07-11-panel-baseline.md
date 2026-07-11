# Judge Calibration Bench

- Date: `2026-07-11`
- Provider / model: `openai` / `gpt-5.4-mini`
- Cases within band: **27/28**

## Per-case scores

| case | skill | lang | expected | score | conf | escalation | in-band |
| --- | --- | --- | --- | ---: | ---: | --- | :---: |
| ml_bias_variance_weak_en | ml_fundamentals | en | 1.0-2.6 | 2.00 | 0.96 | — | ✅ |
| ml_bias_variance_weak_vi | ml_fundamentals | vi | 1.0-2.6 | 2.00 | 0.98 | — | ✅ |
| ml_bias_variance_strong_en | ml_fundamentals | en | 3.8-5.0 | 4.00 | 0.93 | — | ✅ |
| ml_bias_variance_strong_vi | ml_fundamentals | vi | 3.8-5.0 | 4.00 | 0.92 | — | ✅ |
| ml_regularization_medium_en | ml_fundamentals | en | 2.8-4.2 | 4.00 | 0.95 | — | ✅ |
| ml_regularization_medium_vi | ml_fundamentals | vi | 2.8-4.2 | 3.00 | 0.93 | — | ✅ |
| dl_overfitting_weak_en | deep_learning | en | 1.6-3.2 | 3.00 | 0.96 | — | ✅ |
| dl_overfitting_weak_vi | deep_learning | vi | 1.6-3.2 | 3.00 | 0.95 | — | ✅ |
| dl_overfitting_strong_en | deep_learning | en | 3.8-5.0 | 5.00 | 0.96 | — | ✅ |
| dl_overfitting_strong_vi | deep_learning | vi | 3.8-5.0 | 4.00 | 0.95 | — | ✅ |
| vnlp_segmentation_weak_en | vietnamese_nlp | en | 1.0-2.6 | 2.00 | 0.97 | — | ✅ |
| vnlp_segmentation_weak_vi | vietnamese_nlp | vi | 1.0-2.6 | 2.00 | 0.96 | — | ✅ |
| vnlp_segmentation_strong_en | vietnamese_nlp | en | 3.8-5.0 | 4.00 | 0.95 | — | ✅ |
| vnlp_segmentation_strong_vi | vietnamese_nlp | vi | 3.8-5.0 | 4.00 | 0.95 | — | ✅ |
| sd_backpressure_strong_en | system_design | en | 3.8-5.0 | 5.00 | 0.93 | — | ✅ |
| sd_backpressure_strong_vi | system_design | vi | 3.8-5.0 | 4.00 | 0.93 | — | ✅ |
| mlops_monitoring_strong_en | mlops | en | 3.8-5.0 | 5.00 | 0.96 | — | ✅ |
| mlops_monitoring_strong_vi | mlops | vi | 3.8-5.0 | 5.00 | 0.94 | — | ✅ |
| prompt_injection_en | ml_fundamentals | en | 1.0-2.5 | 1.00 | 0.99 | — | ✅ |
| prompt_injection_vi | ml_fundamentals | vi | 1.0-2.5 | 1.00 | 0.99 | — | ✅ |
| mixed_dl_dropout_strong_vnmix | deep_learning | mixed | 3.8-5.0 | 4.00 | 0.91 | — | ✅ |
| mixed_dl_dropout_weak_vnmix | deep_learning | mixed | 1.0-2.6 | 2.00 | 0.97 | — | ✅ |
| mixed_sd_cache_strong_en_delivery | system_design | mixed | 3.8-5.0 | 5.00 | 0.96 | — | ✅ |
| mixed_ml_leakage_broken_english | ml_fundamentals | mixed | 3.4-5.0 | 4.00 | 0.91 | — | ✅ |
| panel_sd_retry_storm_en | system_design | en | 1.2-3.2 | 1.00 | 0.98 | — | ❌ |
| panel_sd_retry_storm_vi | system_design | vi | 1.2-3.2 | 2.00 | 0.92 | — | ✅ |
| panel_ml_eval_on_train_en | ml_fundamentals | en | 1.2-3.4 | 2.00 | 0.96 | — | ✅ |
| panel_ml_eval_on_train_vi | ml_fundamentals | vi | 1.2-3.4 | 2.00 | 0.93 | — | ✅ |

## Per-dimension bias (judge − human label)

| dimension | bias | n |
| --- | ---: | ---: |
| communication | +0.25 | 28 |
| correctness | -0.04 | 28 |
| depth | -0.50 | 28 |
| english_delivery | +0.00 | 2 |
| mlops_awareness | +0.25 | 4 |
| system_thinking | +0.04 | 28 |

## Weak/strong separation

- mean weak-labelled score: 1.71
- mean strong-labelled score: 4.42
- separation gap: 2.70

## EN vs VN paired deltas

| paired_id | EN | VN | |Δ| |
| --- | ---: | ---: | ---: |
| dl_overfitting_strong | 5.00 | 4.00 | 1.00 |
| dl_overfitting_weak | 3.00 | 3.00 | 0.00 |
| ml_bias_variance_strong | 4.00 | 4.00 | 0.00 |
| ml_bias_variance_weak | 2.00 | 2.00 | 0.00 |
| ml_regularization_medium | 4.00 | 3.00 | 1.00 |
| mlops_monitoring_strong | 5.00 | 5.00 | 0.00 |
| panel_ml_eval_on_train | 2.00 | 2.00 | 0.00 |
| panel_sd_retry_storm | 1.00 | 2.00 | 1.00 |
| prompt_injection | 1.00 | 1.00 | 0.00 |
| sd_backpressure_strong | 5.00 | 4.00 | 1.00 |
| vnlp_segmentation_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_weak | 2.00 | 2.00 | 0.00 |

- mean |Δ|: 0.33; max |Δ|: 1.00

## Mixed-mode cases (issue 0024)

| case | technical score | english_delivery (judge/label) | fixes | in-band |
| --- | ---: | :---: | ---: | :---: |
| mixed_dl_dropout_strong_vnmix | 4.00 | —/— | 0 | ✅ |
| mixed_dl_dropout_weak_vnmix | 2.00 | —/— | 0 | ✅ |
| mixed_sd_cache_strong_en_delivery | 5.00 | 5/5 | 0 | ✅ |
| mixed_ml_leakage_broken_english | 4.00 | 2/2 | 3 | ✅ |

## Confidence calibration

| confidence bucket | n | mean conf | hit rate |
| --- | ---: | ---: | ---: |
| [0.9,1.0] | 28 | 0.95 | 96% |

## BARS anchors used for labelling

- **system_thinking** — 2: Mentions a fix in isolation ("add more data", "use dropout") without connecting it to a diagnosis, trade-off, or downstream effect. | 4: Reasons about the interaction: names a diagnosis, the trade-off it drives, and the consequence of the chosen fix on other parts of the system (e.g. "regularise, but that raises bias, so I cross-validate the strength").
- **correctness** — 2: Contains a real technical error or a vague statement that is only half-right (e.g. "L2 makes weights smaller which is always better"). | 4: Technically accurate with the key mechanism stated correctly, even if not exhaustive (e.g. "L2 penalises squared weights, trading a little fit for lower variance").
- **english_delivery** — 2: Frequent broken phrasing that obscures the meaning ("model is overfit when data less"); the reader must re-read sentences to extract the idea. Judged on delivery only — the technical content may still be strong. | 4: Clear professional English with minor slips (an article or tense error) that never obscure the technical point.
