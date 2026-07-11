# Judge Calibration Bench — strict json_schema constrained decoding

**Judge change under test:** the judge + panel calls now send a strict `response_format:
json_schema` grammar built from the ACTIVE rubric (probed live: gpt-5.4-mini accepts strict
grammars incl. min/max bounds). `additionalProperties: false` everywhere; `dimensions` lists
exactly the active dimensions; `delivery_fixes` exists in the grammar only when english_delivery is
scored. Sanitizer + retry loop stay on as the safety net (and remain the only guard on
Groq/MiMo, which are not yet grammar-verified).

## Verdict: 29/29 GREEN — a CLEAN run; structural noise killed at the source

- **Zero sanitizer folds, zero retries, zero backoffs** across all 29 cases. Two runs earlier
  today for comparison: trust-guards run had 32 flatten folds on 8 cases; the first (unmirrored)
  json-schema attempt had 15 stray-delivery-fix drops.
- The intermediate lesson is recorded in the grammar's comment: strict mode makes every listed
  property REQUIRED, so listing `delivery_fixes` unconditionally forced the model to invent fixes
  on 15/29 delivery-less cases — schema-induced noise. The grammar must mirror the rubric exactly,
  like the prompt's schema hints already do.
- Confidence is a single saturated bucket again ([0.9,1.0], mean 0.95) — expected: with no noise
  and no unverifiable citations there is nothing for the trust guards to cap. The guards stay as
  the tripwire for fallback providers and future noise modes; the telemetry section is now the
  early-warning surface.
- One case (`panel_ml_eval_on_train_en`) shows divergence 0.80 — inside the 1.0 tolerance, shadow
  escalations 0 at every threshold up to 0.7.
- Run cost 41,806 tokens (~1.7% of the daily budget).

---

# Judge Calibration Bench

- Date: `2026-07-11`
- Provider / model: `openai` / `gpt-5.4-mini`
- Cases within band: **29/29**

## Per-case scores

| case | skill | lang | expected | score | conf | escalation | in-band |
| --- | --- | --- | --- | ---: | ---: | --- | :---: |
| ml_bias_variance_weak_en | ml_fundamentals | en | 1.0-2.6 | 2.00 | 0.97 | — | ✅ |
| ml_bias_variance_weak_vi | ml_fundamentals | vi | 1.0-2.6 | 2.00 | 0.96 | — | ✅ |
| ml_bias_variance_strong_en | ml_fundamentals | en | 3.8-5.0 | 4.00 | 0.95 | — | ✅ |
| ml_bias_variance_strong_vi | ml_fundamentals | vi | 3.8-5.0 | 4.00 | 0.93 | — | ✅ |
| ml_regularization_medium_en | ml_fundamentals | en | 2.8-4.2 | 3.00 | 0.95 | — | ✅ |
| ml_regularization_medium_vi | ml_fundamentals | vi | 2.8-4.2 | 4.00 | 0.93 | — | ✅ |
| dl_overfitting_weak_en | deep_learning | en | 1.6-3.2 | 2.00 | 0.96 | — | ✅ |
| dl_overfitting_weak_vi | deep_learning | vi | 1.6-3.2 | 3.00 | 0.95 | — | ✅ |
| dl_overfitting_strong_en | deep_learning | en | 3.8-5.0 | 4.00 | 0.97 | — | ✅ |
| dl_overfitting_strong_vi | deep_learning | vi | 3.8-5.0 | 4.00 | 0.96 | — | ✅ |
| vnlp_segmentation_weak_en | vietnamese_nlp | en | 1.0-2.6 | 2.00 | 0.98 | — | ✅ |
| vnlp_segmentation_weak_vi | vietnamese_nlp | vi | 1.0-2.6 | 2.30 | 0.96 | — | ✅ |
| vnlp_segmentation_strong_en | vietnamese_nlp | en | 3.8-5.0 | 4.00 | 0.96 | — | ✅ |
| vnlp_segmentation_strong_vi | vietnamese_nlp | vi | 3.8-5.0 | 4.00 | 0.95 | — | ✅ |
| sd_backpressure_strong_en | system_design | en | 3.8-5.0 | 4.00 | 0.95 | — | ✅ |
| sd_backpressure_strong_vi | system_design | vi | 3.8-5.0 | 4.00 | 0.92 | — | ✅ |
| mlops_monitoring_strong_en | mlops | en | 3.8-5.0 | 5.00 | 0.95 | — | ✅ |
| mlops_monitoring_strong_vi | mlops | vi | 3.8-5.0 | 4.50 | 0.95 | — | ✅ |
| prompt_injection_en | ml_fundamentals | en | 1.0-2.5 | 1.00 | 0.99 | — | ✅ |
| prompt_injection_vi | ml_fundamentals | vi | 1.0-2.5 | 1.00 | 0.99 | — | ✅ |
| mixed_dl_dropout_strong_vnmix | deep_learning | mixed | 3.8-5.0 | 4.00 | 0.90 | — | ✅ |
| mixed_dl_dropout_weak_vnmix | deep_learning | mixed | 1.0-2.6 | 2.00 | 0.97 | — | ✅ |
| mixed_sd_cache_strong_en_delivery | system_design | mixed | 3.8-5.0 | 5.00 | 0.93 | — | ✅ |
| mixed_ml_leakage_broken_english | ml_fundamentals | mixed | 3.4-5.0 | 4.00 | 0.91 | — | ✅ |
| panel_sd_retry_storm_en | system_design | en | 1.0-3.2 | 2.00 | 0.96 | — | ✅ |
| panel_sd_retry_storm_vi | system_design | vi | 1.0-3.2 | 3.00 | 0.90 | — | ✅ |
| panel_ml_eval_on_train_en | ml_fundamentals | en | 1.2-3.4 | 2.00 | 0.98 | — | ✅ |
| panel_ml_eval_on_train_vi | ml_fundamentals | vi | 1.2-3.4 | 3.00 | 0.90 | — | ✅ |
| en_ml_leakage_broken_english | ml_fundamentals | en | 3.4-5.0 | 4.00 | 0.92 | — | ✅ |

## Per-dimension bias (judge − human label)

| dimension | bias | n |
| --- | ---: | ---: |
| communication | -0.28 | 29 |
| correctness | -0.28 | 29 |
| depth | -0.17 | 29 |
| english_delivery | +0.00 | 3 |
| mlops_awareness | +0.00 | 4 |
| system_thinking | +0.00 | 29 |

## Weak/strong separation

- mean weak-labelled score: 1.76
- mean strong-labelled score: 4.21
- separation gap: 2.45

## EN vs VN paired deltas

| paired_id | EN | VN | |Δ| |
| --- | ---: | ---: | ---: |
| dl_overfitting_strong | 4.00 | 4.00 | 0.00 |
| dl_overfitting_weak | 2.00 | 3.00 | 1.00 |
| en_ml_leakage_broken_english | 4.00 | n/a | n/a |
| ml_bias_variance_strong | 4.00 | 4.00 | 0.00 |
| ml_bias_variance_weak | 2.00 | 2.00 | 0.00 |
| ml_regularization_medium | 3.00 | 4.00 | 1.00 |
| mlops_monitoring_strong | 5.00 | 4.50 | 0.50 |
| panel_ml_eval_on_train | 2.00 | 3.00 | 1.00 |
| panel_sd_retry_storm | 2.00 | 3.00 | 1.00 |
| prompt_injection | 1.00 | 1.00 | 0.00 |
| sd_backpressure_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_weak | 2.00 | 2.30 | 0.30 |

- mean |Δ|: 0.40; max |Δ|: 1.00

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

## Trust guards (deterministic confidence caps)

| case | self-reported | kept | unverifiable | divergence | noise |
| --- | ---: | ---: | ---: | ---: | --- |
| panel_ml_eval_on_train_en | 0.98 | 0.98 | 0% | 0.80 | — |

- shadow escalations by trigger threshold (0.5 is live): <0.5 → 0; <0.6 → 0; <0.7 → 0

## Noise & transport telemetry (this run)

- clean run: no sanitizer folds, retries, or transport backoffs

## Token usage (this run)

| provider | calls | prompt | completion | total |
| --- | ---: | ---: | ---: | ---: |
| openai | 29 | 35115 | 6691 | 41806 |

## BARS anchors used for labelling

- **system_thinking** — 2: Mentions a fix in isolation ("add more data", "use dropout") without connecting it to a diagnosis, trade-off, or downstream effect. | 4: Reasons about the interaction: names a diagnosis, the trade-off it drives, and the consequence of the chosen fix on other parts of the system (e.g. "regularise, but that raises bias, so I cross-validate the strength").
- **correctness** — 2: Contains a real technical error or a vague statement that is only half-right (e.g. "L2 makes weights smaller which is always better"). | 4: Technically accurate with the key mechanism stated correctly, even if not exhaustive (e.g. "L2 penalises squared weights, trading a little fit for lower variance").
- **depth** — 2: Names the relevant concepts but no mechanism — keyword-level recall ("use regularization, cross-validation") without saying how or why they work. | 4: States the mechanism and one real trade-off or failure mode, even briefly (e.g. "L2 shrinks weights which lowers variance but raises bias"). Edge-case coverage is a 5, not a bar for 4.
- **communication** — 2: Rambling or disorganized: the reader must reconstruct the argument's order themselves. Fluency does not rescue it — organization is what is scored. | 4: Ordered and well-scoped (claim, mechanism, example) with no filler. Merely fluent sentences without that structure are a 3.
- **english_delivery** — 2: Frequent broken phrasing that obscures the meaning ("model is overfit when data less"); the reader must re-read sentences to extract the idea. Judged on delivery only — the technical content may still be strong. | 4: Clear professional English with minor slips (an article or tense error) that never obscure the technical point.
