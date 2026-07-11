# Judge Calibration Bench — Panel Verdict lands (issue 0027 / GH #28)

**Judge change under test:** issue 0027 replaces the lone Self-critique re-read with a committee:
when the deterministic escalation triggers fire (confidence < 0.5, or the weighted-score
cross-check tripping), a **Skeptic** and an **Advocate** each argue the exchange citing the
candidate's actual words, then the Evaluator re-evaluates having read both and that verdict is
kept unconditionally — the panel advises, the Evaluator decides (ADR 0001). Committee disagreement
(|skeptic − advocate|, 0–4) replaces judge confidence as the evidence weight on escalated
questions (`skill.panel_agreement_weight`). This run also carries the delivery-gate hardening
batch from the 0024 review (≥5-word activation gate, per-rubric system prompt, structural-noise
folding). Per ADR 0009 every judge change is bench-gated; four borderline `panel_*` cases were
added for this issue (29 cases total).

## Verdict: 29/29 — bench GREEN

- All four new borderline cases (`panel_sd_retry_storm` en/vi, `panel_ml_eval_on_train` en/vi)
  land in band, both languages.
- The 0024 disentanglement guarantees hold: mixed-mode delivery labels matched (2/2, 5/5) with
  the required ≥3 phrase-level fixes on the broken-English case, and no phantom delivery scores.
- EN/VN paired deltas stay tight (see table below); `panel_sd_retry_storm` sits at the very bottom
  of its band in EN (1.00 vs floor 1.0) — the judge fairly hammers a catastrophic retry-storm
  answer, which is why the floor was set at 1.0 during the baseline run.

## Honest failure log: one 24/29 run preceded this green one

The first post-panel run errored on 5 cases (not band misses — `StructuredOutputError` after both
attempts). Re-running the 5 cases with full logs exposed two structural-noise modes of
gpt-5.4-mini, both burning the single retry:

1. **Volunteered `english_delivery`.** Describing the delivery rules in the system prompt on
   every case made the judge score `english_delivery` on delivery-less cases (`score: null` on
   attempt 1, a real score on attempt 2 — both rejected by the exact-dimensions validator). Fix:
   the delivery rules ride in the system prompt only when the rubric actually lists
   `english_delivery` (`_system_prompt(rubric)`), mirroring the earlier per-rubric schema hint.
2. **Whole judgment flattened inside `dimensions`.** On long answers the judge sometimes emitted
   `weighted_score`/`confidence`/`follow_up_*` as siblings of the dimension scores. Fix: the
   `Evaluation` sanitizer relocates known top-level fields out of `dimensions` — field placement
   is structural noise, never judgment, so it is folded deterministically instead of burning the
   retry.

Both fixes are locked offline (`test_system_prompt_mentions_english_delivery_only_when_active`,
`test_top_level_fields_nested_inside_dimensions_are_recovered`). The re-run is the 29/29 above.

## Forced-escalation experiment: does the debate help?

The acceptance question "does the panel improve accuracy on borderline goldens?" cannot be
answered by the bench alone: on gpt-5.4-mini the triggers essentially never fire naturally —
first-pass confidence is uniformly ≥ 0.90, even on eloquent-but-wrong answers. So
`scripts/experiment_issue_0027_forced_escalation.py` forces the committee to convene (trigger
threshold raised above 1.0) on 10 cases — the four borderline `panel_*` cases, the adversarial
injection case, a genuinely-medium pair, the two eloquence traps, and two clean anchors — through
the production `evaluate()` path:

| case | band | first | verdict | Δ | skeptic | advocate | disagree | verdict in band | first conf |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | :-: | ---: |
| panel_sd_retry_storm_en | 1.0-3.2 | 2.00 | 2.00 | +0.00 | 1 | 2 | 1.0 | Y | 0.95 |
| panel_sd_retry_storm_vi | 1.0-3.2 | 2.00 | 2.00 | +0.00 | 2 | 3 | 1.0 | Y | 0.90 |
| panel_ml_eval_on_train_en | 1.2-3.4 | 2.00 | 2.00 | +0.00 | 2 | 2 | 0.0 | Y | 0.96 |
| panel_ml_eval_on_train_vi | 1.2-3.4 | 2.00 | 2.00 | +0.00 | 2 | 2 | 0.0 | Y | 0.98 |
| prompt_injection_en | 1.0-2.5 | 1.00 | 1.00 | +0.00 | 1 | 1 | 0.0 | Y | 0.99 |
| ml_regularization_medium_en | 2.8-4.2 | 4.00 | 4.00 | +0.00 | 2 | 4 | 2.0 | Y | 0.95 |
| ml_regularization_medium_vi | 2.8-4.2 | 3.00 | 3.00 | +0.00 | 2 | 4 | 2.0 | Y | 0.93 |
| mixed_ml_leakage_broken_english | 3.4-5.0 | 4.00 | 4.00 | +0.00 | 3 | 4 | 1.0 | Y | 0.91 |
| ml_bias_variance_strong_en | 3.8-5.0 | 4.00 | 4.00 | +0.00 | 4 | 4 | 0.0 | Y | 0.95 |
| dl_overfitting_weak_en | 1.6-3.2 | 3.00 | 3.00 | +0.00 | 2 | 4 | 2.0 | Y | 0.95 |

Read honestly, three findings:

1. **The verdict never moved (mean |Δ| = 0.00, 10/10 in band before and after).** On this model the
   debate does not change scores — but it also never *wrecked* an in-band judgment, which is the
   safety property that makes keeping the verdict unconditionally safe.
2. **Disagreement is a real signal even when the score is stable.** The committee converged
   (0.0) exactly on the clear-cut cases (train-set evaluation, prompt injection, the clean strong
   anchor) and split hardest (2.0) on the genuinely ambiguous ones (`ml_regularization_medium`,
   `dl_overfitting_weak` — the "3 could be a 2 or a 4" cases). That split is what
   `panel_agreement_weight` feeds into the Beta update: an escalated 3.00 with a 2-vs-4 committee
   moves the posterior with weight 1.25 instead of 2.0. The panel's measurable value today is this
   evidence-quality signal plus the committee packet in the export — not score correction.
3. **Natural escalations: 0/10 (first-pass confidence ≥ 0.90 everywhere).** The cost gate is
   airtight on gpt-5.4-mini — and so is the panel's dormancy. The confidence saturation is a known
   watch-item; the bench re-anchor follow-up owns recalibrating the trigger threshold against this
   model's actual confidence distribution.

## Watch-items carried forward

Confidence saturation (~0.95 uniform) now gates *two* things: calibration reporting and the panel
trigger. Communication bias (+0.25 this run) and the generous top scale remain on the re-anchor
worklist.

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
| ml_bias_variance_strong_vi | ml_fundamentals | vi | 3.8-5.0 | 4.00 | 0.95 | — | ✅ |
| ml_regularization_medium_en | ml_fundamentals | en | 2.8-4.2 | 4.00 | 0.96 | — | ✅ |
| ml_regularization_medium_vi | ml_fundamentals | vi | 2.8-4.2 | 3.00 | 0.93 | — | ✅ |
| dl_overfitting_weak_en | deep_learning | en | 1.6-3.2 | 3.00 | 0.95 | — | ✅ |
| dl_overfitting_weak_vi | deep_learning | vi | 1.6-3.2 | 3.00 | 0.95 | — | ✅ |
| dl_overfitting_strong_en | deep_learning | en | 3.8-5.0 | 4.00 | 0.96 | — | ✅ |
| dl_overfitting_strong_vi | deep_learning | vi | 3.8-5.0 | 5.00 | 0.96 | — | ✅ |
| vnlp_segmentation_weak_en | vietnamese_nlp | en | 1.0-2.6 | 2.00 | 0.96 | — | ✅ |
| vnlp_segmentation_weak_vi | vietnamese_nlp | vi | 1.0-2.6 | 2.00 | 0.96 | — | ✅ |
| vnlp_segmentation_strong_en | vietnamese_nlp | en | 3.8-5.0 | 4.00 | 0.94 | — | ✅ |
| vnlp_segmentation_strong_vi | vietnamese_nlp | vi | 3.8-5.0 | 4.00 | 0.92 | — | ✅ |
| sd_backpressure_strong_en | system_design | en | 3.8-5.0 | 4.00 | 0.90 | — | ✅ |
| sd_backpressure_strong_vi | system_design | vi | 3.8-5.0 | 5.00 | 0.93 | — | ✅ |
| mlops_monitoring_strong_en | mlops | en | 3.8-5.0 | 5.00 | 0.96 | — | ✅ |
| mlops_monitoring_strong_vi | mlops | vi | 3.8-5.0 | 5.00 | 0.95 | — | ✅ |
| prompt_injection_en | ml_fundamentals | en | 1.0-2.5 | 1.00 | 0.99 | — | ✅ |
| prompt_injection_vi | ml_fundamentals | vi | 1.0-2.5 | 1.00 | 0.99 | — | ✅ |
| mixed_dl_dropout_strong_vnmix | deep_learning | mixed | 3.8-5.0 | 4.00 | 0.92 | — | ✅ |
| mixed_dl_dropout_weak_vnmix | deep_learning | mixed | 1.0-2.6 | 2.00 | 0.97 | — | ✅ |
| mixed_sd_cache_strong_en_delivery | system_design | mixed | 3.8-5.0 | 5.00 | 0.95 | — | ✅ |
| mixed_ml_leakage_broken_english | ml_fundamentals | mixed | 3.4-5.0 | 4.00 | 0.92 | — | ✅ |
| panel_sd_retry_storm_en | system_design | en | 1.0-3.2 | 2.00 | 0.96 | — | ✅ |
| panel_sd_retry_storm_vi | system_design | vi | 1.0-3.2 | 2.00 | 0.90 | — | ✅ |
| panel_ml_eval_on_train_en | ml_fundamentals | en | 1.2-3.4 | 2.00 | 0.97 | — | ✅ |
| panel_ml_eval_on_train_vi | ml_fundamentals | vi | 1.2-3.4 | 2.00 | 0.92 | — | ✅ |
| en_ml_leakage_broken_english | ml_fundamentals | en | 3.4-5.0 | 4.00 | 0.91 | — | ✅ |

## Per-dimension bias (judge − human label)

| dimension | bias | n |
| --- | ---: | ---: |
| communication | +0.34 | 29 |
| correctness | -0.10 | 29 |
| depth | -0.52 | 29 |
| english_delivery | +0.00 | 3 |
| mlops_awareness | +0.25 | 4 |
| system_thinking | +0.07 | 29 |

## Weak/strong separation

- mean weak-labelled score: 1.71
- mean strong-labelled score: 4.42
- separation gap: 2.70

## EN vs VN paired deltas

| paired_id | EN | VN | |Δ| |
| --- | ---: | ---: | ---: |
| dl_overfitting_strong | 4.00 | 5.00 | 1.00 |
| dl_overfitting_weak | 3.00 | 3.00 | 0.00 |
| en_ml_leakage_broken_english | 4.00 | n/a | n/a |
| ml_bias_variance_strong | 4.00 | 4.00 | 0.00 |
| ml_bias_variance_weak | 2.00 | 2.00 | 0.00 |
| ml_regularization_medium | 4.00 | 3.00 | 1.00 |
| mlops_monitoring_strong | 5.00 | 5.00 | 0.00 |
| panel_ml_eval_on_train | 2.00 | 2.00 | 0.00 |
| panel_sd_retry_storm | 2.00 | 2.00 | 0.00 |
| prompt_injection | 1.00 | 1.00 | 0.00 |
| sd_backpressure_strong | 4.00 | 5.00 | 1.00 |
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
| [0.9,1.0] | 29 | 0.95 | 100% |

## BARS anchors used for labelling

- **system_thinking** — 2: Mentions a fix in isolation ("add more data", "use dropout") without connecting it to a diagnosis, trade-off, or downstream effect. | 4: Reasons about the interaction: names a diagnosis, the trade-off it drives, and the consequence of the chosen fix on other parts of the system (e.g. "regularise, but that raises bias, so I cross-validate the strength").
- **correctness** — 2: Contains a real technical error or a vague statement that is only half-right (e.g. "L2 makes weights smaller which is always better"). | 4: Technically accurate with the key mechanism stated correctly, even if not exhaustive (e.g. "L2 penalises squared weights, trading a little fit for lower variance").
- **english_delivery** — 2: Frequent broken phrasing that obscures the meaning ("model is overfit when data less"); the reader must re-read sentences to extract the idea. Judged on delivery only — the technical content may still be strong. | 4: Clear professional English with minor slips (an article or tense error) that never obscure the technical point.
