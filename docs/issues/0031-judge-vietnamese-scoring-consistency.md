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

## Blocked by

None.

## Status

**Open.**
