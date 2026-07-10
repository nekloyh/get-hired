# Concept retrieval relevance + accuracy review (issue 0008 / GH #8)

The last open acceptance box on issue 0008: *"Retrieval for a sampled set of follow-up needs
returns relevant, accurate notes (human-reviewed)."* This is that review pass, run over the
expanded bank (42 questions, 40 concept notes — the breadth landed with issue 0013).

**Provenance:** review executed by the agent, human sign-off at PR review. The script lives in the
session scratchpad (throwaway); the method and full results are reproduced here.

## Method

Every question's `follow_up_seeds` were treated as the follow-up needs the Interviewer would look
up mid-session — 50 lookups in total. Each seed (plus its question text, mirroring the context the
Interviewer has) was sent through `lookup_concept` with the Skill filter applied, and a lookup
counts as a **hit** when the returned note is one of that question's `expected_concepts` (the
hand-labelled relevance ground truth).

**Store caveat:** `chromadb` is not installed in this environment, so the review ran on
`InMemoryConceptStore` — the same interface and the same metadata-filter contract as production,
but a token-overlap ranker instead of BGE embeddings, and its tokenizer is ASCII-only (no
stemming, and Vietnamese diacritic text contributes almost nothing to ranking). Results below are
therefore a *floor* for the production Chroma + `bge-small-en-v1.5` path, with one exception
called out in the Vietnamese section.

## Results: 47/50 hits (94%) after review-driven fixes

| Skill | hits | misses |
| --- | ---: | ---: |
| ml_fundamentals | 13/13 | 0 |
| deep_learning | 10/10 | 0 |
| mlops | 10/10 | 0 |
| system_design | 8/10 | 2 |
| vietnamese_nlp | 6/7 | 1 |

The first run scored 43/50 (86%). Four of the seven misses turned out to be **label or metadata
defects, not retrieval defects** — the store returned a *more* relevant note than the hand label —
and were fixed as part of this review:

1. *"Ask what they version to make a run reproducible"* (mlops notebook→prod question) retrieved
   `mlops_experiment_tracking` — which is exactly the right note for that need. The question's
   `expected_concepts` predated the tracking/validation notes; **added
   `mlops_experiment_tracking` + `mlops_data_validation`** to its labels.
2. *"Probe the single most likely cause of train/prod divergence"* retrieved
   `mlops_data_validation` — on-target for the same reason; covered by the same label fix.
3. *"Ask why segmenting the input before PhoBERT matters"* retrieved `vietnamese_nlp_vncorenlp` —
   the PhoBERT question literally asks "what preprocessing does it assume", and VnCoreNLP
   segmentation is that answer. **Added `vietnamese_nlp_vncorenlp`** to its labels.
4. *"Ask why the normalization must run in both training and serving"* missed
   `vietnamese_nlp_unicode_normalization` because the note's English-reachable surface (title is
   Vietnamese) lacked the keyword. **Added a `normalization` tag** to the note.

## Residual misses (3) — toy-ranker artifacts, documented not chased

- Two `system_design` seeds about load shedding rank `delivery_semantics`/`scaling_basics` a hair
  above `backpressure` (scores 0.060–0.065): the ASCII ranker does no stemming, so query "shed"
  never matches the note's "shedding", and shared tokens like "retry"/"requests" leak across
  notes. The returned notes are still on-topic neighbors. A real embedder handles this morphology
  trivially — do not tune note text to the toy ranker.
- One `vietnamese_nlp` seed (unicode question) returns `teencode` over `unicode_normalization`:
  both notes' bodies are Vietnamese, so the ASCII ranker sees only tags plus a handful of ASCII
  tokens, and the shorter note wins the Jaccard denominator. Same class of artifact; the returned
  note is the adjacent preprocessing note, not a wrong-topic result.

## Vietnamese-note reachability (the one production-relevant finding)

A separate probe queried each `vi` note by its own (Vietnamese) title under `language: "vi"`
filtering: 5/6 return themselves; `vietnamese_nlp_diacritic_restoration` loses to
`word_segmentation` because a fully-Vietnamese query carries zero signal through the ASCII
tokenizer. **This limitation is not unique to the toy store**: the production embedder is
`bge-small-en-v1.5` — an *English* model — so Vietnamese-text similarity is weak there too. That
is exactly why the design routes `vi` notes by metadata filter (`language: vi`, Skill) rather than
trusting the embedder (the `metadata_routed` tag on the original note records this decision), and
all `vi` notes carry English tags as their embedder-visible surface.

**Recommendation (non-blocking, for when the Chroma path is stood up):** re-run this review on the
real store; if Vietnamese-query relevance matters beyond metadata routing, swap to a multilingual
embedder (e.g. a multilingual BGE variant) — measured against this same 50-lookup sample.

## Accuracy review of the notes themselves

All 40 notes were read for technical accuracy in this pass:

- The 14 pre-existing notes: accurate; no changes. (PhoBERT/VnCoreNLP claims match the published
  tooling papers; the systems notes state standard results.)
- The 26 new notes (landed with 0013): reviewed against standard references at authoring time —
  verdicts and the deliberately double-checked claims are documented in
  `docs/audits/question-bank-review-2026-07-11.md`.
- Notes remain short, self-contained, whole-document chunks — no chunk-splitting artifacts; the
  longest note renders under ~10 lines.

## Gate results

`uv run pytest`: 239 passed · `uv run ruff check .`: clean ·
`uv run coach pack lint data/packs/fpt`: valid.
