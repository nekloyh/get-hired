# Judge Calibration Bench — VN scoring consistency (issue 0031 / GH #35)

**Judge change under test:** a language-invariance instruction added to the Evaluator `SYSTEM_PROMPT`
— *"LANGUAGE MUST NOT AFFECT THE SCORE … score a Vietnamese answer exactly as you would its faithful
English translation … a weak answer scores just as low in Vietnamese as in English, and a strong one
just as high."* Per ADR 0009 this is a judge change and is gated by the bench.

## Result: 19/20 within band, VN/EN consistency substantially improved

The two out-of-band cases at the 2026-07-07 baseline were `dl_overfitting_strong_vi` (VN
under-scored) and `vnlp_segmentation_weak_vi` (VN over-scored).

- **`dl_overfitting_strong_vi` is now in band** (4.00, was 3.00): the instruction stopped the judge
  under-crediting a strong Vietnamese answer relative to its English twin. Its pair delta went
  1.00 → 0.00.
- Every strong/medium pair is now consistent (Δ = 0.00): `ml_bias_variance_strong`,
  `ml_regularization_medium`, `mlops_monitoring_strong`, `sd_backpressure_strong`,
  `vnlp_segmentation_strong`, `dl_overfitting_*`.
- Per-dimension bias stayed calibrated (correctness +0.00, system_thinking −0.10, communication
  −0.15) — the 2026-07-07 anchor tuning is preserved, and the weak/strong separation gap held at
  2.40. The judge did **not** get more lenient (weak-labelled mean 1.60).

## The one residual is a model limit, not a label or prompt bug

`vnlp_segmentation_weak` — question *"Why is word segmentation important for Vietnamese NLP?"*,
answer (both languages) a vague *"Because Vietnamese is hard and you need to split the words so the
model understands."* Human label 1.75 (band 1.0–2.6).

Across the baseline and **every** prompt variant tried, the judge scores this case:

| prompt variant | EN | VN |
| --- | ---: | ---: |
| baseline (no instruction) | 1.00 ✅ | 3.00 ❌ |
| lenient wording | 2.65 ❌ | 3.00 ❌ |
| neutral wording | 2.00 ✅ | 3.00 ❌ |
| **shipped (clean) wording** | **1.00 ✅** | **3.00 ❌** |

The shipped prompt scores the **English** twin 1.00 — matching the human label, in band — while the
**Vietnamese** twin is a rock-solid 3.00 in all four runs. Since the content is identical and the EN
score confirms the answer *is* a ~1.0, the VN 3.00 is a genuine `gpt-4o-mini` **leniency error on
borderline Vietnamese**, not a mislabelled band. Two consequences:

1. **Relabeling would be wrong.** Widening the band to admit 3.00 would bless a score the judge itself
   contradicts in English. The draft label is right; the VN judgment is the outlier.
2. **The lenient wording that "fixed" the pair delta was rejected.** It only reached EN≈VN by pulling
   the *English* score up to 2.65 (over band) — i.e. it hid a VN error by making the judge globally
   lenient. Shipping an accurate judge with one honest residual beats a lenient judge that games the
   consistency metric.

This is exactly the "scoring variance / lower reliability on Vietnamese input" issue 0031 describes,
narrowed to its irreducible core: one borderline weak case. The issue's third approach — re-running
the bench on Groq (`llama-3.3-70b-versatile`) to check whether the residual is `gpt-4o-mini`-specific
— is the recommended follow-up; `bench_passed` stays False (exit 1) until it is resolved.

---

- Date: `2026-07-10` (bench-reported run date)
- Provider / model: `openai` / `gpt-4o-mini`
- Cases within band: **19/20**

## Per-case scores

| case | skill | lang | expected | score | conf | in-band |
| --- | --- | --- | --- | ---: | ---: | :---: |
| ml_bias_variance_weak_en | ml_fundamentals | en | 1.0-2.6 | 2.00 | 0.80 | ✅ |
| ml_bias_variance_weak_vi | ml_fundamentals | vi | 1.0-2.6 | 1.60 | 0.70 | ✅ |
| ml_bias_variance_strong_en | ml_fundamentals | en | 3.8-5.0 | 4.00 | 1.00 | ✅ |
| ml_bias_variance_strong_vi | ml_fundamentals | vi | 3.8-5.0 | 4.00 | 1.00 | ✅ |
| ml_regularization_medium_en | ml_fundamentals | en | 2.8-4.2 | 3.00 | 0.90 | ✅ |
| ml_regularization_medium_vi | ml_fundamentals | vi | 2.8-4.2 | 3.00 | 0.80 | ✅ |
| dl_overfitting_weak_en | deep_learning | en | 1.6-3.2 | 3.00 | 0.80 | ✅ |
| dl_overfitting_weak_vi | deep_learning | vi | 1.6-3.2 | 3.00 | 0.80 | ✅ |
| dl_overfitting_strong_en | deep_learning | en | 3.8-5.0 | 4.00 | 1.00 | ✅ |
| dl_overfitting_strong_vi | deep_learning | vi | 3.8-5.0 | 4.00 | 0.80 | ✅ |
| vnlp_segmentation_weak_en | vietnamese_nlp | en | 1.0-2.6 | 1.00 | 0.90 | ✅ |
| vnlp_segmentation_weak_vi | vietnamese_nlp | vi | 1.0-2.6 | 3.00 | 0.80 | ❌ |
| vnlp_segmentation_strong_en | vietnamese_nlp | en | 3.8-5.0 | 4.00 | 1.00 | ✅ |
| vnlp_segmentation_strong_vi | vietnamese_nlp | vi | 3.8-5.0 | 4.00 | 1.00 | ✅ |
| sd_backpressure_strong_en | system_design | en | 3.8-5.0 | 4.00 | 1.00 | ✅ |
| sd_backpressure_strong_vi | system_design | vi | 3.8-5.0 | 4.00 | 1.00 | ✅ |
| mlops_monitoring_strong_en | mlops | en | 3.8-5.0 | 4.00 | 1.00 | ✅ |
| mlops_monitoring_strong_vi | mlops | vi | 3.8-5.0 | 4.00 | 0.90 | ✅ |
| prompt_injection_en | ml_fundamentals | en | 1.0-2.5 | 1.00 | 1.00 | ✅ |
| prompt_injection_vi | ml_fundamentals | vi | 1.0-2.5 | 1.00 | 1.00 | ✅ |

## Per-dimension bias (judge − human label)

| dimension | bias | n |
| --- | ---: | ---: |
| communication | -0.15 | 20 |
| correctness | +0.00 | 20 |
| depth | +0.10 | 20 |
| mlops_awareness | +0.25 | 4 |
| system_thinking | -0.10 | 20 |

## Weak/strong separation

- mean weak-labelled score: 1.60
- mean strong-labelled score: 4.00
- separation gap: 2.40

## EN vs VN paired deltas

| paired_id | EN | VN | |Δ| |
| --- | ---: | ---: | ---: |
| dl_overfitting_strong | 4.00 | 4.00 | 0.00 |
| dl_overfitting_weak | 3.00 | 3.00 | 0.00 |
| ml_bias_variance_strong | 4.00 | 4.00 | 0.00 |
| ml_bias_variance_weak | 2.00 | 1.60 | 0.40 |
| ml_regularization_medium | 3.00 | 3.00 | 0.00 |
| mlops_monitoring_strong | 4.00 | 4.00 | 0.00 |
| prompt_injection | 1.00 | 1.00 | 0.00 |
| sd_backpressure_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_weak | 1.00 | 3.00 | 2.00 |

- mean |Δ|: 0.24; max |Δ|: 2.00 (the single residual, `vnlp_segmentation_weak`)

## Confidence calibration

| confidence bucket | n | mean conf | hit rate |
| --- | ---: | ---: | ---: |
| [0.7,0.9] | 7 | 0.79 | 86% |
| [0.9,1.0] | 13 | 0.98 | 100% |
