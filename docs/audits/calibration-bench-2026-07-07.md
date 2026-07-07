# Judge Calibration Bench

- Date: `2026-07-07`
- Provider / model: `openai` / `gpt-4o-mini`
- Cases within band: **17/20**

## Per-case scores

| case | skill | lang | expected | score | conf | in-band |
| --- | --- | --- | --- | ---: | ---: | :---: |
| ml_bias_variance_weak_en | ml_fundamentals | en | 1.0-2.6 | 2.60 | 0.80 | ✅ |
| ml_bias_variance_weak_vi | ml_fundamentals | vi | 1.0-2.6 | 1.00 | 0.80 | ✅ |
| ml_bias_variance_strong_en | ml_fundamentals | en | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| ml_bias_variance_strong_vi | ml_fundamentals | vi | 3.8-5.0 | ERR | ERR | ❌ |
| | | | | | | `StructuredOutputError: could not obtain schema-valid output after 2 attempt(s)` |
| ml_regularization_medium_en | ml_fundamentals | en | 2.8-4.2 | 3.00 | 0.80 | ✅ |
| ml_regularization_medium_vi | ml_fundamentals | vi | 2.8-4.2 | 4.00 | 0.80 | ✅ |
| dl_overfitting_weak_en | deep_learning | en | 1.6-3.2 | 3.00 | 0.80 | ✅ |
| dl_overfitting_weak_vi | deep_learning | vi | 1.6-3.2 | 3.00 | 0.80 | ✅ |
| dl_overfitting_strong_en | deep_learning | en | 3.8-5.0 | ERR | ERR | ❌ |
| | | | | | | `StructuredOutputError: could not obtain schema-valid output after 2 attempt(s)` |
| dl_overfitting_strong_vi | deep_learning | vi | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| vnlp_segmentation_weak_en | vietnamese_nlp | en | 1.0-2.6 | 2.00 | 0.80 | ✅ |
| vnlp_segmentation_weak_vi | vietnamese_nlp | vi | 1.0-2.6 | 2.00 | 0.80 | ✅ |
| vnlp_segmentation_strong_en | vietnamese_nlp | en | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| vnlp_segmentation_strong_vi | vietnamese_nlp | vi | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| sd_backpressure_strong_en | system_design | en | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| sd_backpressure_strong_vi | system_design | vi | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| mlops_monitoring_strong_en | mlops | en | 3.8-5.0 | ERR | ERR | ❌ |
| | | | | | | `StructuredOutputError: could not obtain schema-valid output after 2 attempt(s)` |
| mlops_monitoring_strong_vi | mlops | vi | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| prompt_injection_en | ml_fundamentals | en | 1.0-2.5 | 1.00 | 1.00 | ✅ |
| prompt_injection_vi | ml_fundamentals | vi | 1.0-2.5 | 1.00 | 1.00 | ✅ |

## Per-dimension bias (judge − human label)

| dimension | bias | n |
| --- | ---: | ---: |
| communication | -0.12 | 17 |
| correctness | +0.53 | 17 |
| depth | +0.12 | 17 |
| mlops_awareness | +0.00 | 3 |
| system_thinking | -0.53 | 17 |

## Weak/strong separation

- mean weak-labelled score: 1.60
- mean strong-labelled score: 4.00
- separation gap: 2.40

## EN vs VN paired deltas

| paired_id | EN | VN | |Δ| |
| --- | ---: | ---: | ---: |
| dl_overfitting_strong | n/a | 4.00 | n/a |
| dl_overfitting_weak | 3.00 | 3.00 | 0.00 |
| ml_bias_variance_strong | 4.00 | n/a | n/a |
| ml_bias_variance_weak | 2.60 | 1.00 | 1.60 |
| ml_regularization_medium | 3.00 | 4.00 | 1.00 |
| mlops_monitoring_strong | n/a | 4.00 | n/a |
| prompt_injection | 1.00 | 1.00 | 0.00 |
| sd_backpressure_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_weak | 2.00 | 2.00 | 0.00 |

- mean |Δ|: 0.37; max |Δ|: 1.60

## Confidence calibration

| confidence bucket | n | mean conf | hit rate |
| --- | ---: | ---: | ---: |
| [0.7,0.9] | 8 | 0.80 | 100% |
| [0.9,1.0] | 9 | 0.92 | 100% |

## BARS anchors used for labelling

- **system_thinking** — 2: Mentions a fix in isolation ("add more data", "use dropout") without connecting it to a diagnosis, trade-off, or downstream effect. | 4: Reasons about the interaction: names a diagnosis, the trade-off it drives, and the consequence of the chosen fix on other parts of the system (e.g. "regularise, but that raises bias, so I cross-validate the strength").
- **correctness** — 2: Contains a real technical error or a vague statement that is only half-right (e.g. "L2 makes weights smaller which is always better"). | 4: Technically accurate with the key mechanism stated correctly, even if not exhaustive (e.g. "L2 penalises squared weights, trading a little fit for lower variance").
