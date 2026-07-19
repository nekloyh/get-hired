# Concept retrieval — embedder A/B on the real Chroma store (issue 0008 follow-up)

**Question under test:** the Chroma re-run (`concept-retrieval-review-chroma-2026-07-11.md`)
measured the predicted Vietnamese weakness — the English embedder collapses fully-Vietnamese
queries toward the `word_segmentation` hub note (vi self-retrieval 3/6, vietnamese_nlp 4/7) — and
set the bar for a multilingual replacement at **46/50 overall**. This A/B prices
`intfloat/multilingual-e5-small` against that bar with the exact same 50-lookup method, ground
truth, and store (`scripts/review_issue_0008_chroma_retrieval.py --embedding-model ...`). The e5
family's asymmetric `query:`/`passage:` prefixes are applied by the store itself
(`ChromaConceptStore` encodes both sides and hands Chroma raw vectors) — without them e5 ranks
silently worse, so the prefixes live next to the model id in `concepts.py`.

## Verdict: e5-small clears the bar and fixes exactly what it was hired to fix

| | bge-small-en-v1.5 | multilingual-e5-small |
| --- | ---: | ---: |
| Overall (bar: 46/50) | 46/50 (92%) | **47/50 (94%)** |
| vietnamese_nlp seeds | 4/7 | **6/7** |
| vi-note self-retrieval | 3/6 | **4/6** |
| deep_learning / ml_fundamentals / mlops | 33/33 | 33/33 |
| system_design | 9/10 | 8/10 |

- **The word_segmentation hub collapse is broken.** All 3 of BGE's vietnamese_nlp misses landed on
  the hub note; e5's single miss (`unicode_normalization` seed → `teencode`) is an adjacent-topic
  confusion, not a hub collapse, and its self-retrieval misses scatter instead of funneling.
- **English retrieval holds.** The dl/ml/mlops block stays perfect. The one system_design
  regression (queueing-vs-shedding seed → `serving_latency` instead of `backpressure`) is the same
  note-pair confusion BGE already exhibited on the retry-storm seed — a *content* problem (the two
  notes are semantically adjacent) flagged as system_design weakness in the original audit, not an
  embedder artifact. Sharpening those two notes' contrast is bank work, tracked separately.
- **Cost:** ~470MB model vs ~130MB, CPU-friendly either way; zero API cost.

## Decision

- `--concept-embedder` is exposed on `interview` / `session` / `ingest-concepts`;
  `multilingual-e5-small` is the **recommended embedder for vn-mode practice**.
- The default stays `bge-small-en-v1.5` deliberately: embeddings are not portable across models,
  so silently flipping the default would corrupt lookups against any existing persisted
  `--persist-dir` collection. Switch = re-ingest, and the CLI help says so.

## Companion fix in the same change: language preference decoupled from the shelf

The retrieval language filter was hard-bound to the `vietnamese_nlp` shelf
(`interviewer.py`), so a vn-mode Session asking about any other Skill could never
prefer a Vietnamese note — and vi notes on other shelves were unreachable forever. Now:

- preference order: the model's own `language` request > Session `language_mode` (vn/mixed → vi) >
  vi-native shelf default;
- the preference is **soft**: when a shelf has no note in the preferred language the lookup widens
  to any language instead of failing the follow-up (most shelves carry only English notes today,
  and an English grounding note is strictly better than no follow-up);
- the recorded `concept_lookup_language` reflects the filter that actually ran (None after
  widening), so traces never claim a filter that was dropped.

## Raw runs

Arm A and B outputs are reproducible with:

```
uv run python scripts/review_issue_0008_chroma_retrieval.py
uv run python scripts/review_issue_0008_chroma_retrieval.py --embedding-model intfloat/multilingual-e5-small
```

### Arm A misses (bge-small-en-v1.5)

- system_design: retry-storm seed → `system_design_serving_latency` (expected `system_design_backpressure`)
- vietnamese_nlp: parallel-data seed → `word_segmentation` hub (expected `diacritic_restoration`)
- vietnamese_nlp: train/serve-normalization seed → `word_segmentation` hub (expected `unicode_normalization`)
- vietnamese_nlp: budget seed → `word_segmentation` hub (expected `teencode` or `diacritic_restoration`)

### Arm B misses (multilingual-e5-small)

- system_design: retry-storm seed → `serving_latency` (same confusion as Arm A)
- system_design: queueing-vs-shedding seed → `serving_latency` (expected `backpressure`)
- vietnamese_nlp: train/serve-normalization seed → `teencode` (expected `unicode_normalization`)
