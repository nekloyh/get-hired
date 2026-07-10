# Judge Calibration Bench — gpt-5.4-mini resolves the VN residual (issue 0031 / GH #35)

**Judge change under test:** the judge model was upgraded from `gpt-4o-mini` to `gpt-5.4-mini`
(`PRIMARY_PROVIDER=openai`, `OPENAI_MODEL=gpt-5.4-mini`), keeping the same language-invariance prompt.
Per ADR 0009 a provider/model swap is a judge change and is gated by the bench.

## Verdict: 20/20 — bench GREEN, the cross-model VN residual is resolved

The one case that resisted every prompt variant and reproduced identically on `gpt-4o-mini` *and* Groq
`llama-3.3-70b-versatile` — `vnlp_segmentation_weak_vi`, stuck at 3.00 over its 1.0–2.6 band — now
scores **2.00, in band**, matching its English twin (2.00, Δ = 0.00).

| judge | within band | `vnlp_segmentation_weak` EN/VN | bench exit |
| --- | ---: | --- | ---: |
| gpt-4o-mini (+ prompt fix) | 19/20 | 1.00 ✅ / 3.00 ❌ | 1 |
| Groq llama-3.3-70b (+ prompt fix) | 18/20 | 1.00 ✅ / 3.00 ❌ | 1 |
| **gpt-5.4-mini (+ prompt fix)** | **20/20** | **2.00 ✅ / 2.00 ✅** | **0** |

This **confirms the residual was a small-model capability limit**, not a mislabelled band: a stronger
judge with better low-resource-language discrimination scores the borderline Vietnamese answer
correctly. It is the resolution issue 0031 pointed to (a stronger judge model, not a same-tier
provider swap — Groq did not help). Weak/strong separation also improved to **2.83** (best recorded).

## Calibration watch-items (green, but the bands were labelled against gpt-4o-mini)

Everything is in band, but switching judge models shifts the calibration surface, and these are worth
a future anchor re-review for the new model:

- **`communication` bias +0.65** — gpt-5.4-mini over-rates communication vs the human labels (the
  other dimensions are close: correctness −0.20, depth −0.25, system_thinking +0.00).
- **Generous on strong answers** — it hands out 5.00 freely (strong-labelled mean 4.50), where
  gpt-4o-mini sat at 4.00. Still all in band, but the top of the scale is looser.
- **Confidence is uniformly high** — all 20 cases land in the [0.9, 1.0] bucket (mean 0.95, hit-rate
  100%). It is accurate here, but the judge barely expresses uncertainty, so `confidence` carries less
  discriminating signal than it did on gpt-4o-mini (relevant to the self-critique trigger and the
  evidence-weighting).
- **Residual EN/VN variance** — mean |Δ| 0.30, and three pairs still differ by 1.00
  (`dl_overfitting_weak`, `ml_regularization_medium`, `sd_backpressure_strong`), all within band.

None of these block the gate; they are the eval-discipline follow-up (re-label / re-anchor the bench
for gpt-5.4-mini so the bands track the model actually in use).

## Cost

`gpt-5.4-mini` is in OpenAI's **free 2.5M-tokens/day tier** (data-shared traffic), so at dev volume
(a handful of bench runs + sessions/day) the judge runs at **$0**.

---

- Date: `2026-07-10` (bench-reported run date)
- Provider / model: `openai` / `gpt-5.4-mini`
- Cases within band: **20/20**

## Per-case scores

| case | skill | lang | expected | score | conf | in-band |
| --- | --- | --- | --- | ---: | ---: | :---: |
| ml_bias_variance_weak_en | ml_fundamentals | en | 1.0-2.6 | 2.00 | 0.97 | ✅ |
| ml_bias_variance_weak_vi | ml_fundamentals | vi | 1.0-2.6 | 2.00 | 0.96 | ✅ |
| ml_bias_variance_strong_en | ml_fundamentals | en | 3.8-5.0 | 4.00 | 0.95 | ✅ |
| ml_bias_variance_strong_vi | ml_fundamentals | vi | 3.8-5.0 | 4.00 | 0.93 | ✅ |
| ml_regularization_medium_en | ml_fundamentals | en | 2.8-4.2 | 4.00 | 0.95 | ✅ |
| ml_regularization_medium_vi | ml_fundamentals | vi | 2.8-4.2 | 3.00 | 0.91 | ✅ |
| dl_overfitting_weak_en | deep_learning | en | 1.6-3.2 | 2.00 | 0.95 | ✅ |
| dl_overfitting_weak_vi | deep_learning | vi | 1.6-3.2 | 3.00 | 0.95 | ✅ |
| dl_overfitting_strong_en | deep_learning | en | 3.8-5.0 | 5.00 | 0.96 | ✅ |
| dl_overfitting_strong_vi | deep_learning | vi | 3.8-5.0 | 5.00 | 0.95 | ✅ |
| vnlp_segmentation_weak_en | vietnamese_nlp | en | 1.0-2.6 | 2.00 | 0.97 | ✅ |
| vnlp_segmentation_weak_vi | vietnamese_nlp | vi | 1.0-2.6 | 2.00 | 0.96 | ✅ |
| vnlp_segmentation_strong_en | vietnamese_nlp | en | 3.8-5.0 | 4.00 | 0.96 | ✅ |
| vnlp_segmentation_strong_vi | vietnamese_nlp | vi | 3.8-5.0 | 4.00 | 0.95 | ✅ |
| sd_backpressure_strong_en | system_design | en | 3.8-5.0 | 5.00 | 0.94 | ✅ |
| sd_backpressure_strong_vi | system_design | vi | 3.8-5.0 | 4.00 | 0.92 | ✅ |
| mlops_monitoring_strong_en | mlops | en | 3.8-5.0 | 5.00 | 0.93 | ✅ |
| mlops_monitoring_strong_vi | mlops | vi | 3.8-5.0 | 5.00 | 0.95 | ✅ |
| prompt_injection_en | ml_fundamentals | en | 1.0-2.5 | 1.00 | 0.99 | ✅ |
| prompt_injection_vi | ml_fundamentals | vi | 1.0-2.5 | 1.00 | 0.99 | ✅ |

## Per-dimension bias (judge − human label)

| dimension | bias | n |
| --- | ---: | ---: |
| communication | +0.65 | 20 |
| correctness | -0.20 | 20 |
| depth | -0.25 | 20 |
| mlops_awareness | +0.25 | 4 |
| system_thinking | +0.00 | 20 |

## Weak/strong separation

- mean weak-labelled score: 1.67
- mean strong-labelled score: 4.50
- separation gap: 2.83

## EN vs VN paired deltas

| paired_id | EN | VN | |Δ| |
| --- | ---: | ---: | ---: |
| dl_overfitting_strong | 5.00 | 5.00 | 0.00 |
| dl_overfitting_weak | 2.00 | 3.00 | 1.00 |
| ml_bias_variance_strong | 4.00 | 4.00 | 0.00 |
| ml_bias_variance_weak | 2.00 | 2.00 | 0.00 |
| ml_regularization_medium | 4.00 | 3.00 | 1.00 |
| mlops_monitoring_strong | 5.00 | 5.00 | 0.00 |
| prompt_injection | 1.00 | 1.00 | 0.00 |
| sd_backpressure_strong | 5.00 | 4.00 | 1.00 |
| vnlp_segmentation_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_weak | 2.00 | 2.00 | 0.00 |

- mean |Δ|: 0.30; max |Δ|: 1.00 (all in band)

## Confidence calibration

| confidence bucket | n | mean conf | hit rate |
| --- | ---: | ---: | ---: |
| [0.9,1.0] | 20 | 0.95 | 100% |
