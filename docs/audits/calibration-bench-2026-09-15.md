# Judge Calibration Bench

- Date: `2026-09-15`
- Provider / model: `openai` / `gpt-5.4-mini`
- Gate: **median-of-k, k=3** (ADR 0009 addendum d)
- Cases within band: **34/35**

## Per-case scores

The score column is the MEDIAN over k runs; `runs` shows every draw, so a case whose distribution sits on a band edge is visible here rather than discovered when it flips.

| case | skill | lang | expected | score | runs | conf | escalation | in-band |
| --- | --- | --- | --- | ---: | --- | ---: | --- | :---: |
| ml_bias_variance_weak_en | ml_fundamentals | en | 1.0-2.6 | 2.00 | 2.00/2.00/2.00 | 0.96 | — | ✅ |
| ml_bias_variance_weak_vi | ml_fundamentals | vi | 1.0-2.6 | 2.00 | 2.00/2.00/2.00 | 0.98 | — | ✅ |
| ml_bias_variance_strong_en | ml_fundamentals | en | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.95 | — | ✅ |
| ml_bias_variance_strong_vi | ml_fundamentals | vi | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.90 | — | ✅ |
| ml_regularization_medium_en | ml_fundamentals | en | 2.8-4.2 | 4.00 | 4.00/4.00/4.00 | 0.95 | — | ✅ |
| ml_regularization_medium_vi | ml_fundamentals | vi | 2.8-4.2 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| dl_overfitting_weak_en | deep_learning | en | 1.6-3.2 | 3.00 | 3.00/3.00/3.00 | 0.95 | — | ✅ |
| dl_overfitting_weak_vi | deep_learning | vi | 1.6-3.2 | 3.20 | 3.20/3.00/4.00 ⚠ | 0.95 | — | ✅ |
| dl_overfitting_strong_en | deep_learning | en | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.95 | — | ✅ |
| dl_overfitting_strong_vi | deep_learning | vi | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.95 | — | ✅ |
| vnlp_segmentation_weak_en | vietnamese_nlp | en | 1.0-2.6 | 2.20 | 2.40/2.20/2.20 | 0.98 | — | ✅ |
| vnlp_segmentation_weak_vi | vietnamese_nlp | vi | 1.0-2.6 | 2.70 | 2.70/2.70/2.70 | 0.98 | — | ❌ |
| vnlp_segmentation_strong_en | vietnamese_nlp | en | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.95 | — | ✅ |
| vnlp_segmentation_strong_vi | vietnamese_nlp | vi | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| sd_backpressure_strong_en | system_design | en | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.91 | — | ✅ |
| sd_backpressure_strong_vi | system_design | vi | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.90 | — | ✅ |
| mlops_monitoring_strong_en | mlops | en | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.95 | — | ✅ |
| mlops_monitoring_strong_vi | mlops | vi | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| prompt_injection_en | ml_fundamentals | en | 1.0-2.5 | 1.00 | 1.00/1.00/1.00 | 0.99 | — | ✅ |
| prompt_injection_vi | ml_fundamentals | vi | 1.0-2.5 | 1.00 | 1.00/1.00/1.00 | 0.99 | — | ✅ |
| mixed_dl_dropout_strong_vnmix | deep_learning | mixed | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.92 | — | ✅ |
| mixed_dl_dropout_weak_vnmix | deep_learning | mixed | 1.0-2.6 | 2.00 | 2.00/2.00/2.00 | 0.97 | — | ✅ |
| mixed_sd_cache_strong_en_delivery | system_design | mixed | 3.8-5.0 | 5.00 | 5.00/5.00/4.00 | 0.97 | — | ✅ |
| mixed_ml_leakage_broken_english | ml_fundamentals | mixed | 3.4-5.0 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| panel_sd_retry_storm_en | system_design | en | 1.0-3.2 | 2.00 | 2.00/2.00/2.00 | 0.93 | — | ✅ |
| panel_sd_retry_storm_vi | system_design | vi | 1.0-3.2 | 3.00 | 3.00/3.00/3.00 | 0.89 | — | ✅ |
| panel_ml_eval_on_train_en | ml_fundamentals | en | 1.2-3.4 | 2.00 | 2.00/2.00/2.00 | 0.97 | — | ✅ |
| panel_ml_eval_on_train_vi | ml_fundamentals | vi | 1.2-3.4 | 3.00 | 3.00/3.00/3.00 | 0.92 | — | ✅ |
| en_ml_leakage_broken_english | ml_fundamentals | en | 3.4-5.0 | 4.00 | 4.00/4.00/4.00 | 0.90 | — | ✅ |
| mlops_retraining_weak_en | mlops | en | 1.0-2.8 | 1.00 | 1.00/1.00/2.00 | 0.98 | — | ✅ |
| mlops_rollout_strong_en | mlops | en | 3.8-5.0 | 5.00 | 5.00/5.00/5.00 | 0.93 | — | ✅ |
| mlops_train_serve_skew_medium_en | mlops | en | 2.8-4.2 | 4.00 | 4.00/4.00/4.00 | 0.92 | — | ✅ |
| en_dl_batchnorm_broken_english | deep_learning | en | 3.4-5.0 | 4.00 | 4.00/4.00/4.00 | 0.90 | — | ✅ |
| mixed_mlops_drift_technical | mlops | mixed | 3.4-5.0 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| en_sd_idempotency_strong_delivery | system_design | en | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.95 | — | ✅ |

## Repeatability (k=3)

Cases whose score moved between runs. A ⚠ straddle means some runs landed in-band and others did not — the band edge cuts through the judge's distribution, so the case is one provider nudge from flipping the gate even while its median reads green.

| case | runs | median | spread | band | straddles edge |
| --- | --- | ---: | ---: | --- | :---: |
| dl_overfitting_weak_vi | 3.20/3.00/4.00 | 3.20 | 1.00 | 1.6-3.2 | ⚠ YES |
| mixed_sd_cache_strong_en_delivery | 5.00/5.00/4.00 | 5.00 | 1.00 | 3.8-5.0 | no |
| mlops_retraining_weak_en | 1.00/1.00/2.00 | 1.00 | 1.00 | 1.0-2.8 | no |
| vnlp_segmentation_weak_en | 2.40/2.20/2.20 | 2.20 | 0.20 | 1.0-2.6 | no |

- **REPEATABILITY** — dl_overfitting_weak_vi: runs 3.20/3.00/4.00 straddle band 1.6-3.2 (median 3.20) — the band edge cuts through the judge's score distribution; re-derive the band from this distribution or re-anchor the dimension driving it, but never widen to go green

## Per-dimension bias (judge − human label)

| dimension | bias | n | stability |
| --- | ---: | ---: | --- |
| communication | -0.14 | 35 | ok |
| correctness | -0.29 | 35 | ok |
| depth | +0.00 | 35 | ok |
| english_delivery | +0.40 | 5 | ⚠ n<8 — unstable estimate |
| mlops_awareness | +0.25 | 8 | ok |
| system_thinking | +0.17 | 35 | ok |

## Weak/strong separation

- mean weak-labelled score: 1.74
- mean strong-labelled score: 4.14
- separation gap: 2.41

## EN vs VN paired deltas

| paired_id | EN | VN | |Δ| |
| --- | ---: | ---: | ---: |
| dl_overfitting_strong | 4.00 | 4.00 | 0.00 |
| dl_overfitting_weak | 3.00 | 3.20 | 0.20 |
| en_dl_batchnorm_broken_english | 4.00 | n/a | n/a |
| en_ml_leakage_broken_english | 4.00 | n/a | n/a |
| en_sd_idempotency_strong_delivery | 4.00 | n/a | n/a |
| ml_bias_variance_strong | 4.00 | 4.00 | 0.00 |
| ml_bias_variance_weak | 2.00 | 2.00 | 0.00 |
| ml_regularization_medium | 4.00 | 4.00 | 0.00 |
| mlops_monitoring_strong | 4.00 | 4.00 | 0.00 |
| mlops_retraining_weak | 1.00 | n/a | n/a |
| mlops_rollout_strong | 5.00 | n/a | n/a |
| mlops_train_serve_skew_medium | 4.00 | n/a | n/a |
| panel_ml_eval_on_train | 2.00 | 3.00 | 1.00 |
| panel_sd_retry_storm | 2.00 | 3.00 | 1.00 |
| prompt_injection | 1.00 | 1.00 | 0.00 |
| sd_backpressure_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_weak | 2.20 | 2.70 | 0.50 |

- mean |Δ|: 0.23; max |Δ|: 1.00

## Mixed-mode cases (issue 0024)

| case | technical score | english_delivery (judge/label) | fixes | in-band |
| --- | ---: | :---: | ---: | :---: |
| mixed_dl_dropout_strong_vnmix | 4.00 | —/— | 0 | ✅ |
| mixed_dl_dropout_weak_vnmix | 2.00 | —/— | 0 | ✅ |
| mixed_sd_cache_strong_en_delivery | 5.00 | 5/5 | 0 | ✅ |
| mixed_ml_leakage_broken_english | 4.00 | 2/2 | 3 | ✅ |
| mixed_mlops_drift_technical | 4.00 | —/— | 0 | ✅ |

## Confidence calibration

| confidence bucket | n | mean conf | hit rate |
| --- | ---: | ---: | ---: |
| [0.7,0.9] | 1 | 0.89 | 100% |
| [0.9,1.0] | 34 | 0.94 | 97% |

## Trust guards (deterministic confidence caps)

| case | self-reported | kept | unverifiable | divergence | noise |
| --- | ---: | ---: | ---: | ---: | --- |
| panel_sd_retry_storm_en | 0.93 | 0.93 | 0% | 0.70 | — |

- shadow escalations by trigger threshold (0.5 is live): <0.5 → 0; <0.6 → 0; <0.7 → 0

## Noise & transport telemetry (this run)

| event | count |
| --- | ---: |
| llm.calls | 105 |
| llm.calls.openai | 105 |

## Token usage (this run)

| provider | calls | prompt | completion | total |
| --- | ---: | ---: | ---: | ---: |
| openai | 105 | 154791 | 26633 | 181424 |

## BARS anchors used for labelling

- **system_thinking** — 2: Mentions a fix in isolation ("add more data", "use dropout") without connecting it to a diagnosis, trade-off, or downstream effect. | 4: Reasons about the interaction: names a diagnosis, the trade-off it drives, and the consequence of the chosen fix on other parts of the system (e.g. "regularise, but that raises bias, so I cross-validate the strength").
- **correctness** — 2: Contains a real technical error or a vague statement that is only half-right (e.g. "L2 makes weights smaller which is always better"). | 3: Nothing wrong, but the claim is left as a bare assertion: the right technique or term is named and the justification is an unsupported "so it is better" / "it helps", with no mechanism given (e.g. "Dropout turns off some neurons so it is better"). A bare assertion cannot reach 4 however fluently or confidently it is phrased, in any language. | 4: Technically accurate with the key mechanism stated correctly, even if not exhaustive (e.g. "L2 penalises squared weights, trading a little fit for lower variance").
- **depth** — 2: Names the relevant concepts but no mechanism — keyword-level recall ("use regularization, cross-validation") without saying how or why they work. | 4: States the mechanism and one real trade-off or failure mode, even briefly (e.g. "L2 shrinks weights which lowers variance but raises bias"). Edge-case coverage is a 5, not a bar for 4.
- **communication** — 2: Rambling or disorganized: the reader must reconstruct the argument's order themselves. Fluency does not rescue it — organization is what is scored. | 3: Readable sentences but unscoped or meandering, OR a bare claim with nothing after it to organize. An answer too short to HAVE a structure cannot score 4 for sounding natural. | 4: Ordered and well-scoped (claim, mechanism, example) with no filler. Merely fluent sentences without that structure are a 3.
- **english_delivery** — 2: Frequent broken phrasing that obscures the meaning ("model is overfit when data less"); the reader must re-read sentences to extract the idea. Judged on delivery only — the technical content may still be strong. | 4: Clear professional English with minor slips (an article or tense error) that never obscure the technical point.
