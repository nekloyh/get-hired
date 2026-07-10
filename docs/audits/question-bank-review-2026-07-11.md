# Question-bank breadth + accuracy/difficulty review (issue 0013 / GH #13)

**Scope:** the built-in bank grew from 15 questions (3 per Skill) to **42 questions**
(9/9/9/9/6 across the five canonical Skills), backed by 26 new concept notes (14 → 40) so every
`expected_concepts` reference resolves. This report is the review pass the issue's last acceptance
box asks for, covering all 42 questions — the 15 pre-existing ones had never been reviewed either.

**Review provenance (honest caveat):** the new content was AI-drafted against standard ML
interview material and self-reviewed by the same agent; the pre-existing 15 were reviewed
independently of their authoring. Human sign-off happens at PR review — items a human should
double-check are flagged below.

## Coverage after this change

| Skill | questions | difficulty levels covered | notes |
| --- | ---: | --- | ---: |
| ml_fundamentals | 9 | 1, 2, 3, 4, 5 | 9 |
| deep_learning | 9 | 1, 2, 3, 4, 5 | 8 |
| mlops | 9 | 1, 2, 3, 4, 5 | 8 |
| system_design | 9 | 1, 2, 3, 4, 5 | 9 |
| vietnamese_nlp | 6 | 1, 2, 3, 4, 5 | 6 (all `language: vi`) |
| **total** | **42** | every Skill spans the full 1–5 scale | **40** |

Vietnamese-context items: **6** (target ~6), all tagged `vietnamese_nlp`, spanning word
segmentation, diacritic restoration, PhoBERT, Unicode/tone normalization, teencode + code-switching,
and a Zalo-style end-to-end chatbot design.

## Accuracy review

Every question's claims, scripted answers, and follow-up seeds were checked against the standard
references for the topic. Verdicts:

- **Pre-existing 15 — accurate.** One wording nit (not fixed, cosmetic): the bias–variance answer
  says "lowering one often raises the other," which correctly hedges the tradeoff as tendency, not
  law.
- **New 27 — accurate, with the following claims deliberately double-checked:**
  - Cross-entropy gradient `(p − y)` w.r.t. logits and the vanishing `σ′(z)` factor under MSE —
    standard result, stated correctly.
  - AdamW: L2-in-loss under Adam is rescaled by the adaptive denominator and is not equivalent to
    decoupled weight decay — matches Loshchilov & Hutter.
  - Distance concentration (nearest/farthest ratio → 1) — standard curse-of-dimensionality result.
  - Random-label memorization + double descent — Zhang et al. / Belkin et al., summarized without
    overclaiming ("test error *can* fall again").
  - Exactly-once as consumer idempotency, transactional outbox, token bucket, CAP/PACELC,
    HNSW/IVF recall-latency trade — standard systems material, stated correctly.
  - Vietnamese NFC/NFD + two tone-placement conventions ("hoà"/"hòa") and teencode examples
    ("ko", "dc", "j") — correct; a native-speaker skim is still the highest-value human check here.
- **Flagged for human spot-check:** none blocking. The Zalo-style chatbot question (difficulty 5)
  bundles several sub-decisions; if live sessions show it is too broad for one turn, split it.

## Difficulty calibration

Anchors used: 1 = definition/recall with one mechanism, 3 = mechanism + tradeoff, 5 = multi-part
reasoning or reconciling a paradox. Every Skill now spans 1–5, so `target_difficulty` extremes land
on genuinely different prompts (pinned by `test_target_difficulty_still_drives_selection`, which now
asserts exact 1 and 5 hits for ml_fundamentals).

Two calibration judgment calls worth knowing:

- `kNN collapses on 1,000 features` is rated 5 (not 4) because the geometric explanation — distance
  concentration — is rarely produced by fresh grads even when they know the term.
- `batch inference vs real-time` is rated 1: it is a definitions question whose depth lives in the
  follow-ups, which is exactly what a warm-up prompt should be.

## Rubric weights

New questions follow the existing weight archetypes: pure-concept questions zero out
`mlops_awareness` (0.4/0.3/0.2/0.1/0.0), applied-systems questions keep a small mlops weight, and
ops-flavored questions use the flatter 0.3/0.25/0.15/0.15/0.15 profile from the existing mlops
tranche. All weight vectors sum to 1.0; at least one dimension is disabled somewhere in every Skill
(pinned by `test_some_questions_disable_a_dimension_with_weight_zero`).

## Fixture answers

`answers[0]` answers the prompt; `answers[1:]` answer successive follow-ups. One deliberately weak
opener was added (`cross-entropy` — "that is the standard pairing") mirroring the existing weak-L2
opener, so the micro-loop's converge-on-follow-up path keeps fixture coverage on more than one
Skill.

## Gate results

- `uv run pytest`: **239 passed** (3 data-coupled tests updated: exact seed count, gate-harness
  `max_questions` lifted above the new per-Skill seed counts, difficulty-extreme assertions).
- `uv run ruff check .`: clean.
- `uv run coach pack lint data/packs/fpt`: pack still valid (packs are independent of the built-in
  bank; run as a regression check).
- New pins: ≥40 total, ≥6 per Skill, ≥3 difficulty levels per Skill, ≥6 VN questions, ≥6 `vi`
  notes, ≥4 concept notes per Skill.

No judge change is involved (no evaluator/prompt/provider/model edit), so the calibration bench is
not triggered by this PR (ADR 0009).
