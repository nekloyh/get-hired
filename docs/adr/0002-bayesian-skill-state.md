# Beta-distributed skill state with prior-only correlations

Each Skill's mastery is modeled as a **Beta distribution** (`mastery = α/(α+β)`, `confidence` derived from the variance) rather than a moving average, because the Supervisor's deviate/terminate-early judgment must read *how sure we are*, not just a point estimate — "0.3 mastery after one shaky answer" and "0.3 after four consistent misses" are different decisions. Cross-skill correlations are applied **only to the initial prior**: a strong background in one Skill shifts the starting Beta of related Skills, but once direct evidence for a Skill arrives it dominates and we do **not** cross-credit on subsequent evaluations.

Priors are **weak by default** (low pseudo-counts near neutral), so a candidate's self-claim sets only the *starting question difficulty*, never our confidence — direct evidence overrides within an answer or two. **Role criticality** (derived from `target_role` + `target_companies` via a hand-built table) further flexes prior *strength* and the evidence bar for early-termination: a Skill the role treats as must-have gets an even weaker prior and a higher evidence bar (probe hard, never trust the claim), while a peripheral Skill gets a stronger prior and low bar (trust the claim, save the question budget). Role criticality never moves the prior *mean* — the job description tells us what the role wants, not how good the candidate is. The hard max-questions cap still bounds everything, so one critical Skill can't starve the rest.

## Considered Options

The V2 plan (`MVP_v2.md`) proposed ongoing correlated updates — bumping every related Skill's α/β on each evaluation. We rejected it because it double-counts overlapping competence: answering a Deep Learning question well, then an ML-Fundamentals question, inflates ML-Fundamentals confidence from ~1 direct + 1 borrowed observation. That inflated confidence could let the Supervisor skip a Skill it never actually tested — the worst possible failure for a tool whose job is finding gaps. Prior-only correlations keep the modeling lesson and the cold-start benefit without the masked-gap bug.

## Addendum: evidence semantics (2026-07-19). Status: Proposed — gated on experiment E2

**Not applied to code until this section's status is Accepted.** The Beta model and prior-only
correlations were independently re-derived and stand (with ≤5–8 observations per Session and no
population data, IRT-2PL is unidentifiable and Elo/Glicko has no opponent pool — Beta is
right-sized). What no one would re-derive is the current *evidence semantics*, three properties
that exist only as code accidents:

1. **Difficulty-blind updates.** `difficulty` exists (`seeds.py:61`) and drives question
   *selection*, but `apply_evaluation` never sees it: a 4.0 on a difficulty-5 question and a 4.0
   on a difficulty-1 question are identical evidence. Proposed: an IRT-lite difficulty term in
   the update (score adjusted or weighted by item difficulty) — pure arithmetic, offline-testable.
2. **Last-turn-wins.** The micro-loop keeps only the final turn's evaluation
   (`microloop.py:284`, the docstring admits "keeps the last, not the best"): a strong seed
   answer followed by one weak follow-up discards the strong evidence entirely. Proposed: fold
   every turn at weight `confidence_weight(conf)/len(turns)` so one question contributes
   ~EVIDENCE_WEIGHT total regardless of turn count (display semantics unchanged). This is R-24
   (GH #79).
3. **The confidence input is a dead signal.** `confidence_weight` scales evidence by the judge's
   self-report, which is saturated (≈0.95 always) — the weight range has collapsed to
   [1.93, 2.0] and the 0021 feature only bites through its deterministic caps. Proposed: the
   input becomes derived confidence (ADR 0011) when that ADR is accepted.

**Experiment E2** (offline, cheapest in the queue): the change behind a flag; re-run trajectory
tests + persona replays (existing artifact + 2 new personas). *Win criteria:* MAE(posterior
mastery, persona ground truth) improves ≥10%, mastery *ordering* across personas is preserved,
and the property test holds (equal scores on a harder question move mastery strictly more).
*Lose:* any ordering regression — the semantics stay as they are and this section is marked
Rejected with the numbers.

*Source: ADR red-team review 2026-07-19 — verdict REAFFIRM core + AMEND evidence semantics;
panel report Phần 1 trục agentic (difficulty-blind Beta), debt #10 (last-turn-wins).*
