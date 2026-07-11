# Judge Calibration Bench — gpt-5.4-mini re-anchor (bias worklist from the July 11 audits)

**Judge change under test:** the two rubric dimensions that had never been calibrated —
`communication` (judge inflated, +0.34: fluent-but-disorganized answers earned 4s) and `depth`
(judge deflated, −0.52: it demanded edge cases before granting a 4) — get scored DIMENSION_GUIDE
bands, the same treatment `correctness`/`system_thinking` received in earlier passes. Matching
"2"/"4" BARS anchors are added to `cases.yaml` so the human labelling standard is recorded.
`.env.example` gains the OPENAI block. Per ADR 0009 the change is bench-gated.

## Verdict: 29/29 GREEN — both target biases moved the right way

| dimension | before | after |
| --- | ---: | ---: |
| communication | +0.34 | **−0.10** |
| depth | −0.52 | **−0.31** |
| correctness | −0.10 | −0.24 |
| system_thinking | +0.07 | +0.07 |

Weak/strong separation holds (1.71 / 4.33, gap 2.62). Correctness drifted slightly stricter —
small, in-band everywhere, watch next run.

## Deliberate non-change: the panel trigger stays at 0.5

Confidence remains saturated (all 29 in [0.9, 1.0], mean 0.95, hit-rate 100%), so the panel
triggers still never fire naturally on this model. Raising the threshold into the 0.90–0.92 tail
was considered and REJECTED: the forced-escalation experiment
(`calibration-bench-2026-07-11-panel-verdict.md`) showed the verdict never moves on this model, so
paying 3 extra calls per low-tail judgment buys no accuracy. The saturation is model behavior, not
labelling error; the trigger becomes worth recalibrating only on a judge whose confidence actually
varies.

---

# Judge Calibration Bench

- Date: `2026-07-11`
- Provider / model: `openai` / `gpt-5.4-mini`
- Cases within band: **29/29**

## Per-case scores

| case | skill | lang | expected | score | conf | escalation | in-band |
| --- | --- | --- | --- | ---: | ---: | --- | :---: |
| ml_bias_variance_weak_en | ml_fundamentals | en | 1.0-2.6 | 2.00 | 0.97 | — | ✅ |
| ml_bias_variance_weak_vi | ml_fundamentals | vi | 1.0-2.6 | 2.00 | 0.97 | — | ✅ |
| ml_bias_variance_strong_en | ml_fundamentals | en | 3.8-5.0 | 4.00 | 0.95 | — | ✅ |
| ml_bias_variance_strong_vi | ml_fundamentals | vi | 3.8-5.0 | 4.00 | 0.93 | — | ✅ |
| ml_regularization_medium_en | ml_fundamentals | en | 2.8-4.2 | 3.00 | 0.95 | — | ✅ |
| ml_regularization_medium_vi | ml_fundamentals | vi | 2.8-4.2 | 4.00 | 0.93 | — | ✅ |
| dl_overfitting_weak_en | deep_learning | en | 1.6-3.2 | 2.00 | 0.95 | — | ✅ |
| dl_overfitting_weak_vi | deep_learning | vi | 1.6-3.2 | 3.00 | 0.95 | — | ✅ |
| dl_overfitting_strong_en | deep_learning | en | 3.8-5.0 | 4.00 | 0.98 | — | ✅ |
| dl_overfitting_strong_vi | deep_learning | vi | 3.8-5.0 | 4.00 | 0.97 | — | ✅ |
| vnlp_segmentation_weak_en | vietnamese_nlp | en | 1.0-2.6 | 2.00 | 0.98 | — | ✅ |
| vnlp_segmentation_weak_vi | vietnamese_nlp | vi | 1.0-2.6 | 2.00 | 0.96 | — | ✅ |
| vnlp_segmentation_strong_en | vietnamese_nlp | en | 3.8-5.0 | 4.00 | 0.95 | — | ✅ |
| vnlp_segmentation_strong_vi | vietnamese_nlp | vi | 3.8-5.0 | 4.00 | 0.95 | — | ✅ |
| sd_backpressure_strong_en | system_design | en | 3.8-5.0 | 5.00 | 0.93 | — | ✅ |
| sd_backpressure_strong_vi | system_design | vi | 3.8-5.0 | 4.00 | 0.93 | — | ✅ |
| mlops_monitoring_strong_en | mlops | en | 3.8-5.0 | 5.00 | 0.95 | — | ✅ |
| mlops_monitoring_strong_vi | mlops | vi | 3.8-5.0 | 5.00 | 0.96 | — | ✅ |
| prompt_injection_en | ml_fundamentals | en | 1.0-2.5 | 1.00 | 0.99 | — | ✅ |
| prompt_injection_vi | ml_fundamentals | vi | 1.0-2.5 | 1.00 | 0.99 | — | ✅ |
| mixed_dl_dropout_strong_vnmix | deep_learning | mixed | 3.8-5.0 | 4.00 | 0.93 | — | ✅ |
| mixed_dl_dropout_weak_vnmix | deep_learning | mixed | 1.0-2.6 | 2.00 | 0.99 | — | ✅ |
| mixed_sd_cache_strong_en_delivery | system_design | mixed | 3.8-5.0 | 5.00 | 0.95 | — | ✅ |
| mixed_ml_leakage_broken_english | ml_fundamentals | mixed | 3.4-5.0 | 4.00 | 0.93 | — | ✅ |
| panel_sd_retry_storm_en | system_design | en | 1.0-3.2 | 1.00 | 0.98 | — | ✅ |
| panel_sd_retry_storm_vi | system_design | vi | 1.0-3.2 | 2.00 | 0.93 | — | ✅ |
| panel_ml_eval_on_train_en | ml_fundamentals | en | 1.2-3.4 | 2.00 | 0.98 | — | ✅ |
| panel_ml_eval_on_train_vi | ml_fundamentals | vi | 1.2-3.4 | 2.00 | 0.93 | — | ✅ |
| en_ml_leakage_broken_english | ml_fundamentals | en | 3.4-5.0 | 4.00 | 0.90 | — | ✅ |

## Per-dimension bias (judge − human label)

| dimension | bias | n |
| --- | ---: | ---: |
| communication | -0.10 | 29 |
| correctness | -0.24 | 29 |
| depth | -0.31 | 29 |
| english_delivery | +0.00 | 3 |
| mlops_awareness | +0.00 | 4 |
| system_thinking | +0.07 | 29 |

## Weak/strong separation

- mean weak-labelled score: 1.71
- mean strong-labelled score: 4.33
- separation gap: 2.62

## EN vs VN paired deltas

| paired_id | EN | VN | |Δ| |
| --- | ---: | ---: | ---: |
| dl_overfitting_strong | 4.00 | 4.00 | 0.00 |
| dl_overfitting_weak | 2.00 | 3.00 | 1.00 |
| en_ml_leakage_broken_english | 4.00 | n/a | n/a |
| ml_bias_variance_strong | 4.00 | 4.00 | 0.00 |
| ml_bias_variance_weak | 2.00 | 2.00 | 0.00 |
| ml_regularization_medium | 3.00 | 4.00 | 1.00 |
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
| [0.9,1.0] | 29 | 0.95 | 100% |

## BARS anchors used for labelling

- **system_thinking** — 2: Mentions a fix in isolation ("add more data", "use dropout") without connecting it to a diagnosis, trade-off, or downstream effect. | 4: Reasons about the interaction: names a diagnosis, the trade-off it drives, and the consequence of the chosen fix on other parts of the system (e.g. "regularise, but that raises bias, so I cross-validate the strength").
- **correctness** — 2: Contains a real technical error or a vague statement that is only half-right (e.g. "L2 makes weights smaller which is always better"). | 4: Technically accurate with the key mechanism stated correctly, even if not exhaustive (e.g. "L2 penalises squared weights, trading a little fit for lower variance").
- **depth** — 2: Names the relevant concepts but no mechanism — keyword-level recall ("use regularization, cross-validation") without saying how or why they work. | 4: States the mechanism and one real trade-off or failure mode, even briefly (e.g. "L2 shrinks weights which lowers variance but raises bias"). Edge-case coverage is a 5, not a bar for 4.
- **communication** — 2: Rambling or disorganized: the reader must reconstruct the argument's order themselves. Fluency does not rescue it — organization is what is scored. | 4: Ordered and well-scoped (claim, mechanism, example) with no filler. Merely fluent sentences without that structure are a 3.
- **english_delivery** — 2: Frequent broken phrasing that obscures the meaning ("model is overfit when data less"); the reader must re-read sentences to extract the idea. Judged on delivery only — the technical content may still be strong. | 4: Clear professional English with minor slips (an article or tense error) that never obscure the technical point.
