# Judge scores Vietnamese answers less consistently than their English twins

**Type:** AFK
**Kind:** bug
**Tracked on GitHub:** [#35](https://github.com/nekloyh/get-hired/issues/35)

## What to build

Surfaced by the calibration bench (issue 0022) once the evidence-verbatim degrade (issue 0030
follow-up) stopped the strong cases from crashing, and after the `correctness`/`system_thinking`
anchor tuning brought the per-dimension bias in line. On `gpt-4o-mini` the two remaining
out-of-band cases are **both Vietnamese** and miss in **opposite** directions, while their English
twins (same question, same answer *content*) are in-band:

| paired_id | EN score | VN score | expected band |
| --- | ---: | ---: | --- |
| `dl_overfitting_strong` | 4.00 ✅ | 3.00 ❌ | 3.8–5.0 (VN under-scored) |
| `vnlp_segmentation_weak` | 1.00 ✅ | 3.00 ❌ | 1.0–2.6 (VN over-scored) |

Because the misses go both ways, this is not a directional bias the rubric anchors can fix — it is
**scoring variance / lower reliability on Vietnamese input**. The bench's `mean |Δ|` between EN/VN
twins is 0.40 with a max of 2.00 (`vnlp_segmentation_weak`), i.e. the judge sometimes gives a
Vietnamese answer a very different score from its English twin despite identical content.

## Acceptance criteria

- [ ] EN/VN paired `|Δ|` shrinks (target: `mean |Δ| ≤ 0.3`, no single pair `> 1.0`) without
      regressing the per-dimension bias won in the 2026-07-07 tuning (correctness −0.05,
      system_thinking −0.20)
- [ ] `dl_overfitting_strong_vi` and `vnlp_segmentation_weak_vi` land in band, or the bands/labels
      are corrected if HITL review finds the *draft* labels were wrong (cases.yaml is an AI-authored
      draft pending human review)
- [ ] The bench remains the gate — verify on a live run, no rigid per-case unit test

## Approaches to weigh

- Prompt: add a short instruction that the answer's language must not affect the score; score the
  *content*, translating mentally if needed.
- Cases: HITL-review the VN labels/bands for the two failing pairs — they may simply be mislabelled
  in the draft.
- Provider: re-run the bench on Groq (`llama-3.3-70b-versatile`) to see whether the VN inconsistency
  is `gpt-4o-mini`-specific before investing in a prompt change.

## Resolution progress

A language-invariance instruction was added to the Evaluator `SYSTEM_PROMPT` (*"LANGUAGE MUST NOT
AFFECT THE SCORE … score a Vietnamese answer exactly as you would its faithful English translation …
a weak answer scores just as low in Vietnamese as in English"*). Gated by `coach bench` on
`openai`/`gpt-4o-mini` — full report: `docs/audits/calibration-bench-2026-07-11-vn-consistency.md`.

- [x] `dl_overfitting_strong_vi` now lands **in band** (4.00, was 3.00); every strong/medium pair is
      consistent (Δ = 0.00). Per-dimension bias preserved (correctness +0.00, system_thinking −0.10);
      the judge did **not** get more lenient (weak-mean 1.60).
- [ ] `vnlp_segmentation_weak_vi` is **not** resolved — and it turns out this is not fixable here. The
      clean prompt scores the English twin 1.00 (matching the label, in band) but the Vietnamese twin
      a rock-solid 3.00 across all four prompt variants tried. Because the content is identical, the
      VN 3.00 is a genuine `gpt-4o-mini` leniency error on a borderline Vietnamese answer, **not** a
      mislabelled band — relabeling would bless a score the judge contradicts in English, and no
      prompt wording moves the stable VN 3.00. A "fully consistent" lenient wording was rejected: it
      reached EN≈VN only by inflating the English score over band (a worse judge).

**Groq cross-check done (issue's third approach):**
`docs/audits/calibration-bench-2026-07-11-vn-consistency-groq.md`. The residual is **not**
`gpt-4o-mini`-specific — `llama-3.3-70b-versatile` scores `vnlp_segmentation_weak` **identically**
(EN 1.00 ✅ / VN 3.00 ❌, Δ = 2.00). Two independent models over-scoring the same borderline
Vietnamese answer by the same margin confirms a genuine **cross-model reliability limit on borderline
Vietnamese input**, not a provider quirk and not a mislabelled band. Groq is also only 18/20 overall
(harsher judge; a different near-miss on `dl_overfitting_strong_en` = 3.70), so a *same-tier* provider
swap is not a win. Prompt tuning and relabeling were both ruled out.

**Resolved by a stronger judge model — `gpt-5.4-mini`.**
`docs/audits/calibration-bench-2026-07-11-gpt-5.4-mini.md`. Upgrading the judge from `gpt-4o-mini` to
`gpt-5.4-mini` (still on the language-invariance prompt) takes the bench to **20/20, exit 0 (green)**:
`vnlp_segmentation_weak_vi` now scores **2.00, in band**, matching its English twin (Δ = 0.00), and
weak/strong separation improves to 2.83. This confirms the residual was a **small-model capability
limit**, exactly the resolution this issue pointed to. `gpt-5.4-mini` sits in OpenAI's free
2.5M-tokens/day tier, so the upgrade is $0 at dev volume. Follow-up (not blocking): the bench bands
were labelled against `gpt-4o-mini`, and `gpt-5.4-mini` shows a `communication` bias of +0.65 and
scores strong answers high — worth a future anchor re-review for the new judge.

## Blocked by

None.

## Status

**Closed — resolved by upgrading the judge to `gpt-5.4-mini`.** The language-invariance prompt fix
(PR #41) fixed the VN consistency on all but one borderline case; that last case was a small-model
capability limit (reproduced on `gpt-4o-mini` and Groq `llama-3.3-70b`), and the stronger
`gpt-5.4-mini` judge scores it correctly — bench is now 20/20 green.
