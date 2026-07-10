# Judge Calibration Bench — Groq cross-check for the VN residual (issue 0031 / GH #35)

The language-invariance prompt fix left one residual on `openai`/`gpt-4o-mini`:
`vnlp_segmentation_weak_vi` scored a stable 3.00 (over its 1.0–2.6 band) while its English twin
correctly scored 1.00. Issue 0031's third approach asks whether that VN-leniency is
`gpt-4o-mini`-specific. This run answers it by re-running the same bench (same prompt fix) on Groq.

## Verdict: the VN residual is NOT provider-specific — it reproduces on Groq

`llama-3.3-70b-versatile` scores the failing pair **exactly** as `gpt-4o-mini` does:

| provider | vnlp_segmentation_weak EN | vnlp_segmentation_weak VN | |Δ| |
| --- | ---: | ---: | ---: |
| gpt-4o-mini (shipped fix) | 1.00 ✅ | 3.00 ❌ | 2.00 |
| **llama-3.3-70b (this run)** | **1.00 ✅** | **3.00 ❌** | **2.00** |

Both judges score the vague English answer 1.00 (matching the human label) and the content-identical
Vietnamese answer 3.00. Two independent models over-scoring the same borderline Vietnamese answer by
the same margin is strong evidence this is a **genuine cross-model reliability limit on borderline
Vietnamese input**, not a quirk of one provider — and not a mislabelled band (both models agree the
English version is a ~1.0). A provider swap does not resolve it.

## Groq is not a better judge for this bench overall

Groq also lands **18/20**, not better than `gpt-4o-mini`'s 19/20 with the fix, and fails a *different*
second case:

- `dl_overfitting_strong_en` = 3.70 ❌ — a near-miss just under the 3.8 floor (Groq is a harsher
  judge: correctness bias −0.25, system_thinking −0.25, vs gpt-4o-mini's ~0.00/−0.10). Its VN twin is
  in band (4.00), so this is an EN-side calibration near-miss, not a VN-consistency problem.
- `vnlp_segmentation_weak_vi` = 3.00 ❌ — the shared cross-model residual above.

**Conclusion for #35:** the prompt fix stands as the improvement (shipped on the primary
`gpt-4o-mini` path, 19/20). The lone residual is a documented cross-model VN limitation that neither a
prompt change nor a provider swap fixes, and that relabeling would wrongly paper over. It is best
tracked as a known limitation / future harder-VN-judge work rather than chased further on this bench.

---

- Date: `2026-07-10` (bench-reported run date)
- Provider / model: `groq` / `llama-3.3-70b-versatile`
- Cases within band: **18/20**

## Per-case scores

| case | skill | lang | expected | score | conf | in-band |
| --- | --- | --- | --- | ---: | ---: | :---: |
| ml_bias_variance_weak_en | ml_fundamentals | en | 1.0-2.6 | 2.00 | 0.80 | ✅ |
| ml_bias_variance_weak_vi | ml_fundamentals | vi | 1.0-2.6 | 2.00 | 0.80 | ✅ |
| ml_bias_variance_strong_en | ml_fundamentals | en | 3.8-5.0 | 4.20 | 0.90 | ✅ |
| ml_bias_variance_strong_vi | ml_fundamentals | vi | 3.8-5.0 | 4.00 | 0.80 | ✅ |
| ml_regularization_medium_en | ml_fundamentals | en | 2.8-4.2 | 3.00 | 0.80 | ✅ |
| ml_regularization_medium_vi | ml_fundamentals | vi | 2.8-4.2 | 3.00 | 0.80 | ✅ |
| dl_overfitting_weak_en | deep_learning | en | 1.6-3.2 | 3.00 | 0.80 | ✅ |
| dl_overfitting_weak_vi | deep_learning | vi | 1.6-3.2 | 3.00 | 0.80 | ✅ |
| dl_overfitting_strong_en | deep_learning | en | 3.8-5.0 | 3.70 | 0.80 | ❌ |
| dl_overfitting_strong_vi | deep_learning | vi | 3.8-5.0 | 4.00 | 0.80 | ✅ |
| vnlp_segmentation_weak_en | vietnamese_nlp | en | 1.0-2.6 | 1.00 | 0.80 | ✅ |
| vnlp_segmentation_weak_vi | vietnamese_nlp | vi | 1.0-2.6 | 3.00 | 0.80 | ❌ |
| vnlp_segmentation_strong_en | vietnamese_nlp | en | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| vnlp_segmentation_strong_vi | vietnamese_nlp | vi | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| sd_backpressure_strong_en | system_design | en | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| sd_backpressure_strong_vi | system_design | vi | 3.8-5.0 | 4.00 | 0.80 | ✅ |
| mlops_monitoring_strong_en | mlops | en | 3.8-5.0 | 5.00 | 1.00 | ✅ |
| mlops_monitoring_strong_vi | mlops | vi | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| prompt_injection_en | ml_fundamentals | en | 1.0-2.5 | 1.00 | 1.00 | ✅ |
| prompt_injection_vi | ml_fundamentals | vi | 1.0-2.5 | 1.00 | 1.00 | ✅ |

## Per-dimension bias (judge − human label)

| dimension | bias | n |
| --- | ---: | ---: |
| communication | -0.05 | 20 |
| correctness | -0.25 | 20 |
| depth | -0.15 | 20 |
| mlops_awareness | +0.25 | 4 |
| system_thinking | -0.25 | 20 |

## Weak/strong separation

- mean weak-labelled score: 1.67
- mean strong-labelled score: 4.09
- separation gap: 2.42

## EN vs VN paired deltas

| paired_id | EN | VN | |Δ| |
| --- | ---: | ---: | ---: |
| dl_overfitting_strong | 3.70 | 4.00 | 0.30 |
| dl_overfitting_weak | 3.00 | 3.00 | 0.00 |
| ml_bias_variance_strong | 4.20 | 4.00 | 0.20 |
| ml_bias_variance_weak | 2.00 | 2.00 | 0.00 |
| ml_regularization_medium | 3.00 | 3.00 | 0.00 |
| mlops_monitoring_strong | 5.00 | 4.00 | 1.00 |
| prompt_injection | 1.00 | 1.00 | 0.00 |
| sd_backpressure_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_weak | 1.00 | 3.00 | 2.00 |

- mean |Δ|: 0.35; max |Δ|: 2.00 (`vnlp_segmentation_weak` — the cross-model residual)

## Confidence calibration

| confidence bucket | n | mean conf | hit rate |
| --- | ---: | ---: | ---: |
| [0.7,0.9] | 12 | 0.80 | 83% |
| [0.9,1.0] | 8 | 0.94 | 100% |
