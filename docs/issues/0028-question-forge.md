# Question Forge — generator-critic flywheel with the Evaluator as admission gate

**Type:** AFK
**Kind:** enhancement

## What to build

Attack the thin-bank problem from the supply side: the system starts producing its own content
instead of only consuming hand-authored YAML. `coach forge --skill X --n 5`:

1. A **Writer** agent drafts candidate questions grounded in the Skill's concept notes.
2. Drafts pass through **ordered gates, cheap → expensive**:
   - **Gate 1 — contract:** pack-lint schema + cross-referential validation (issue 0025's lint).
   - **Gate 2 — novelty:** embedding-duplicate detection against the existing bank/packs.
   - **Gate 3 — admission test:** generate a strong and a weak answer for the draft and require
     the live Evaluator to *separate* them into the right bands — reusing the golden-answer
     machinery. A question the judge can't discriminate on is a bad question.
3. Survivors land in a **review-queue YAML** the owner merges by hand — the human promotion gate.
   Nothing enters the bank automatically.

The run report attributes every rejection to its gate, so gate ordering and yield are measurable
from day one. Batch sizes stay within free-tier limits.

## Acceptance criteria

- [ ] `coach forge` produces a review-queue YAML; nothing reaches the bank without a human merge
- [ ] All three gates run in cheap→expensive order; the run report names which gate killed each
      reject and the per-gate yield
- [ ] Admission gate enforced: strong answer scores in the high band, weak in the low band, else
      reject
- [ ] Offline tests cover gates 1–2 with fixtures; a live smoke covers gate 3 within budget

## Blocked by

- 0022 (the separation machinery gate 3 reuses)
- 0025 (the pack/bank contract that defines "valid" and the merge target)

## Status

**Open.**
