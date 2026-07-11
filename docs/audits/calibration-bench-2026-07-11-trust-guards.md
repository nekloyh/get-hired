# Judge Calibration Bench — trust guards + free-tier hardening validation

**Judge change under test:** graded trust guards (evidence-degrade haircut generalised to a
fraction-proportional cap; structural-noise cap 0.85 when the parse needed sanitizer folds or
retries), TrustTrace shadow data, JUDGE_MAX_RETRIES=2, transport backoff + client-side daily token
ledger. The escalation trigger itself is untouched (0.5 + cross-check, per #53's deliberate
non-change).

## Verdict: 29/29 GREEN — and the guards finally see what saturation was hiding

- **The flatten fold is ~28% of live traffic, not an edge case.** `judgment_flattened_in_dimensions`
  fired on 8/29 cases (32 field relocations — see telemetry section), every one previously invisible
  behind a 0.90+ self-report and a silent sanitizer repair. Those 8 judgments now carry kept
  confidence 0.85, so their evidence weight (skill.py) is differentiated for the first time.
- **Confidence has variance again**: the calibration table now has two buckets (8 cases at mean
  0.85, 21 at 0.95) instead of one saturated band — created by deterministic guards, not by
  trusting the model's self-report.
- **Shadow escalations: 0 at <0.5, <0.6, AND <0.7.** Data-backed confirmation of #53: raising the
  trigger buys nothing on this judge even after the guards; the panel stays escalation-gated at 0.5.
- **Run cost measured, not guessed**: 37,350 tokens / 29 calls (zero retries burned — structural
  folds repair without extra calls). A full bench run is ~1.5% of the 2.5M daily budget; the ledger
  (`coach usage`) now tracks it client-side since the API exposes only per-minute limits.
- Bias vs the re-anchor run: correctness −0.24 → −0.17, depth −0.31 → −0.34, communication −0.10 →
  −0.07 — run-to-run wobble, nothing actionable. `mlops_awareness` swung +0.00 → +0.50 on n=4,
  which is exactly the too-small-sample instability the upcoming bias n-threshold guard flags.

---

# Judge Calibration Bench

- Date: `2026-07-11`
- Provider / model: `openai` / `gpt-5.4-mini`
- Cases within band: **29/29**

## Per-case scores

| case | skill | lang | expected | score | conf | escalation | in-band |
| --- | --- | --- | --- | ---: | ---: | --- | :---: |
| ml_bias_variance_weak_en | ml_fundamentals | en | 1.0-2.6 | 2.00 | 0.98 | — | ✅ |
| ml_bias_variance_weak_vi | ml_fundamentals | vi | 1.0-2.6 | 2.00 | 0.96 | — | ✅ |
| ml_bias_variance_strong_en | ml_fundamentals | en | 3.8-5.0 | 4.00 | 0.95 | — | ✅ |
| ml_bias_variance_strong_vi | ml_fundamentals | vi | 3.8-5.0 | 4.00 | 0.95 | — | ✅ |
| ml_regularization_medium_en | ml_fundamentals | en | 2.8-4.2 | 3.00 | 0.95 | — | ✅ |
| ml_regularization_medium_vi | ml_fundamentals | vi | 2.8-4.2 | 3.00 | 0.93 | — | ✅ |
| dl_overfitting_weak_en | deep_learning | en | 1.6-3.2 | 2.00 | 0.95 | — | ✅ |
| dl_overfitting_weak_vi | deep_learning | vi | 1.6-3.2 | 3.00 | 0.95 | — | ✅ |
| dl_overfitting_strong_en | deep_learning | en | 3.8-5.0 | 5.00 | 0.97 | — | ✅ |
| dl_overfitting_strong_vi | deep_learning | vi | 3.8-5.0 | 4.00 | 0.95 | — | ✅ |
| vnlp_segmentation_weak_en | vietnamese_nlp | en | 1.0-2.6 | 2.00 | 0.95 | — | ✅ |
| vnlp_segmentation_weak_vi | vietnamese_nlp | vi | 1.0-2.6 | 2.00 | 0.95 | — | ✅ |
| vnlp_segmentation_strong_en | vietnamese_nlp | en | 3.8-5.0 | 4.00 | 0.96 | — | ✅ |
| vnlp_segmentation_strong_vi | vietnamese_nlp | vi | 3.8-5.0 | 4.00 | 0.95 | — | ✅ |
| sd_backpressure_strong_en | system_design | en | 3.8-5.0 | 5.00 | 0.85 | — | ✅ |
| sd_backpressure_strong_vi | system_design | vi | 3.8-5.0 | 5.00 | 0.85 | — | ✅ |
| mlops_monitoring_strong_en | mlops | en | 3.8-5.0 | 5.00 | 0.96 | — | ✅ |
| mlops_monitoring_strong_vi | mlops | vi | 3.8-5.0 | 5.00 | 0.85 | — | ✅ |
| prompt_injection_en | ml_fundamentals | en | 1.0-2.5 | 1.00 | 0.99 | — | ✅ |
| prompt_injection_vi | ml_fundamentals | vi | 1.0-2.5 | 1.00 | 0.99 | — | ✅ |
| mixed_dl_dropout_strong_vnmix | deep_learning | mixed | 3.8-5.0 | 4.00 | 0.92 | — | ✅ |
| mixed_dl_dropout_weak_vnmix | deep_learning | mixed | 1.0-2.6 | 2.00 | 0.96 | — | ✅ |
| mixed_sd_cache_strong_en_delivery | system_design | mixed | 3.8-5.0 | 5.00 | 0.85 | — | ✅ |
| mixed_ml_leakage_broken_english | ml_fundamentals | mixed | 3.4-5.0 | 4.00 | 0.93 | — | ✅ |
| panel_sd_retry_storm_en | system_design | en | 1.0-3.2 | 1.00 | 0.85 | — | ✅ |
| panel_sd_retry_storm_vi | system_design | vi | 1.0-3.2 | 2.00 | 0.85 | — | ✅ |
| panel_ml_eval_on_train_en | ml_fundamentals | en | 1.2-3.4 | 2.00 | 0.85 | — | ✅ |
| panel_ml_eval_on_train_vi | ml_fundamentals | vi | 1.2-3.4 | 2.00 | 0.85 | — | ✅ |
| en_ml_leakage_broken_english | ml_fundamentals | en | 3.4-5.0 | 4.00 | 0.93 | — | ✅ |

## Per-dimension bias (judge − human label)

| dimension | bias | n |
| --- | ---: | ---: |
| communication | -0.07 | 29 |
| correctness | -0.17 | 29 |
| depth | -0.34 | 29 |
| english_delivery | +0.00 | 3 |
| mlops_awareness | +0.50 | 4 |
| system_thinking | +0.03 | 29 |

## Weak/strong separation

- mean weak-labelled score: 1.71
- mean strong-labelled score: 4.50
- separation gap: 2.79

## EN vs VN paired deltas

| paired_id | EN | VN | |Δ| |
| --- | ---: | ---: | ---: |
| dl_overfitting_strong | 5.00 | 4.00 | 1.00 |
| dl_overfitting_weak | 2.00 | 3.00 | 1.00 |
| en_ml_leakage_broken_english | 4.00 | n/a | n/a |
| ml_bias_variance_strong | 4.00 | 4.00 | 0.00 |
| ml_bias_variance_weak | 2.00 | 2.00 | 0.00 |
| ml_regularization_medium | 3.00 | 3.00 | 0.00 |
| mlops_monitoring_strong | 5.00 | 5.00 | 0.00 |
| panel_ml_eval_on_train | 2.00 | 2.00 | 0.00 |
| panel_sd_retry_storm | 1.00 | 2.00 | 1.00 |
| prompt_injection | 1.00 | 1.00 | 0.00 |
| sd_backpressure_strong | 5.00 | 5.00 | 0.00 |
| vnlp_segmentation_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_weak | 2.00 | 2.00 | 0.00 |

- mean |Δ|: 0.25; max |Δ|: 1.00

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
| [0.7,0.9] | 8 | 0.85 | 100% |
| [0.9,1.0] | 21 | 0.95 | 100% |

## Trust guards (deterministic confidence caps)

| case | self-reported | kept | unverifiable | divergence | noise |
| --- | ---: | ---: | ---: | ---: | --- |
| sd_backpressure_strong_en | 0.92 | 0.85 | 0% | 0.45 | sanitizer.judgment_flattened_in_dimensions |
| sd_backpressure_strong_vi | 0.93 | 0.85 | 0% | 0.45 | sanitizer.judgment_flattened_in_dimensions |
| mlops_monitoring_strong_vi | 0.96 | 0.85 | 0% | 0.60 | sanitizer.judgment_flattened_in_dimensions |
| mixed_sd_cache_strong_en_delivery | 0.95 | 0.85 | 0% | 0.20 | sanitizer.delivery_fixes_misplaced, sanitizer.judgment_flattened_in_dimensions |
| panel_sd_retry_storm_en | 0.97 | 0.85 | 0% | 0.90 | sanitizer.judgment_flattened_in_dimensions |
| panel_sd_retry_storm_vi | 0.90 | 0.85 | 0% | 0.70 | sanitizer.judgment_flattened_in_dimensions |
| panel_ml_eval_on_train_en | 0.98 | 0.85 | 0% | 0.10 | sanitizer.judgment_flattened_in_dimensions |
| panel_ml_eval_on_train_vi | 0.93 | 0.85 | 0% | 0.50 | sanitizer.judgment_flattened_in_dimensions |

- shadow escalations by trigger threshold (0.5 is live): <0.5 → 0; <0.6 → 0; <0.7 → 0

## Noise & transport telemetry (this run)

| event | count |
| --- | ---: |
| sanitizer.delivery_fixes_misplaced | 1 |
| sanitizer.judgment_flattened_in_dimensions | 32 |

## Token usage (this run)

| provider | calls | prompt | completion | total |
| --- | ---: | ---: | ---: | ---: |
| openai | 29 | 30370 | 6980 | 37350 |

## BARS anchors used for labelling

- **system_thinking** — 2: Mentions a fix in isolation ("add more data", "use dropout") without connecting it to a diagnosis, trade-off, or downstream effect. | 4: Reasons about the interaction: names a diagnosis, the trade-off it drives, and the consequence of the chosen fix on other parts of the system (e.g. "regularise, but that raises bias, so I cross-validate the strength").
- **correctness** — 2: Contains a real technical error or a vague statement that is only half-right (e.g. "L2 makes weights smaller which is always better"). | 4: Technically accurate with the key mechanism stated correctly, even if not exhaustive (e.g. "L2 penalises squared weights, trading a little fit for lower variance").
- **depth** — 2: Names the relevant concepts but no mechanism — keyword-level recall ("use regularization, cross-validation") without saying how or why they work. | 4: States the mechanism and one real trade-off or failure mode, even briefly (e.g. "L2 shrinks weights which lowers variance but raises bias"). Edge-case coverage is a 5, not a bar for 4.
- **communication** — 2: Rambling or disorganized: the reader must reconstruct the argument's order themselves. Fluency does not rescue it — organization is what is scored. | 4: Ordered and well-scoped (claim, mechanism, example) with no filler. Merely fluent sentences without that structure are a 3.
- **english_delivery** — 2: Frequent broken phrasing that obscures the meaning ("model is overfit when data less"); the reader must re-read sentences to extract the idea. Judged on delivery only — the technical content may still be strong. | 4: Clear professional English with minor slips (an article or tense error) that never obscure the technical point.
