# Concept retrieval review on the real Chroma store (issue 0008 follow-up)

The 2026-07-11 review pass (`concept-retrieval-review-2026-07-11.md`) ran on
`InMemoryConceptStore` because chromadb was not installed, and recorded its 47/50 as a *floor*
with a standing recommendation to re-run on the production path. This is that re-run:
`ChromaConceptStore` + `bge-small-en-v1.5` (chromadb 1.5.9), same 50-lookup method, same
hand-labelled ground truth. The review script is now a repeatable artifact:
`scripts/review_issue_0008_chroma_retrieval.py` (the earlier one was scratchpad-throwaway).

## Verdict: 46/50 (92%) — better than the toy floor on English, measurably worse on Vietnamese

| | InMemory (toy ranker) | Chroma + bge-small-en-v1.5 |
| --- | ---: | ---: |
| All 50 lookups | 47/50 | **46/50** |
| English-skill lookups (43) | 41/43 | **42/43** |
| vietnamese_nlp lookups (7) | 6/7 | **4/7** |
| vi-note self-retrieval probe (6) | 5/6 | **3/6** |

- **The real embedder resolves the predicted toy-ranker artifacts on English content.** Both
  system_design "load shedding" seeds were toy misses on morphology ("shed" vs "shedding"); BGE
  fixes one outright. The survivor — *"what do they shed first / avoid a retry storm"* →
  `serving_latency` (0.680) over `backpressure` — is genuine neighbor confusion between two
  on-topic notes, not tokenizer noise; the returned note still grounds a reasonable follow-up.
- **One label defect found and fixed** (same convention as the first pass: the store returned a
  *more* relevant note than the hand label). *"Which fix would you try first, given a wide
  generalization gap"* retrieved `ml_fundamentals_l2_regularization` — the canonical *fix* note —
  where the label only listed the *diagnosis* note. Added `ml_fundamentals_l2_regularization` to
  that question's `expected_concepts` (44/50 raw → 46/50 after this one-line fix + re-run).
- **The Vietnamese weakness the first audit predicted is now measured, and it is real.**
  `bge-small-en-v1.5` is an English model: fully-Vietnamese queries collapse toward
  `vietnamese_nlp_word_segmentation` (it wins 3 of the 4 vi misses across both probes at
  0.67–0.83 cosine — a hub-note effect), and vi-note self-retrieval drops to 3/6 (the toy's
  ASCII-tag surface actually did better at 5/6). Metadata routing bounds the damage exactly as
  designed — the `language: vi` + Skill filter always reaches the right shelf, the embedder just
  ranks poorly *within* it — but within-shelf ranking is now proven unreliable for Vietnamese.

## Recommendation (carried forward, now with numbers)

If Vietnamese-query relevance is wanted beyond metadata routing, swap to a multilingual embedder
(e.g. a multilingual BGE variant) and gate the change on this same 50-lookup sample: the bar to
beat is 46/50 overall and 4/7 // 3/6 on the Vietnamese probes. Until then, vn-Session follow-up
grounding correctly leans on the metadata filter, not the embedder.

## Gate results

`uv run pytest`: 297 passed · `uv run ruff check .`: clean.

---

# Concept retrieval review — real Chroma store (issue 0008 follow-up)

Store: ChromaConceptStore + bge-small-en-v1.5; notes: 40.

## Results: 46/50 hits (92%)

| Skill | hits | misses |
| --- | ---: | ---: |
| deep_learning | 10/10 | 0 |
| ml_fundamentals | 13/13 | 0 |
| mlops | 10/10 | 0 |
| system_design | 9/10 | 1 |
| vietnamese_nlp | 4/7 | 3 |

### Misses

- **system_design** seed *"Ask what they shed first and how they avoid a retry storm."* -> `system_design_serving_latency` (score 0.680); expected one of `system_design_backpressure`
- **vietnamese_nlp** seed *"Ask how they build parallel data for the restoration model."* -> `vietnamese_nlp_word_segmentation` (score 0.700); expected one of `vietnamese_nlp_diacritic_restoration`
- **vietnamese_nlp** seed *"Ask why the normalization must run in both the training and serving paths."* -> `vietnamese_nlp_word_segmentation` (score 0.671); expected one of `vietnamese_nlp_unicode_normalization`
- **vietnamese_nlp** seed *"Ask which they would fund first with a limited budget — normalization rules or in-domain labels — and why."* -> `vietnamese_nlp_word_segmentation` (score 0.674); expected one of `vietnamese_nlp_teencode, vietnamese_nlp_diacritic_restoration`

## Vietnamese-note reachability probe (6 vi notes)

- `vietnamese_nlp_word_segmentation` <- own title: HIT (score 0.706)
- `vietnamese_nlp_phobert` <- own title: HIT (score 0.782)
- `vietnamese_nlp_vncorenlp` <- own title: MISS (got `vietnamese_nlp_phobert`) (score 0.615)
- `vietnamese_nlp_diacritic_restoration` <- own title: MISS (got `vietnamese_nlp_word_segmentation`) (score 0.810)
- `vietnamese_nlp_unicode_normalization` <- own title: MISS (got `vietnamese_nlp_word_segmentation`) (score 0.832)
- `vietnamese_nlp_teencode` <- own title: HIT (score 0.841)

Self-retrieval: 3/6.
