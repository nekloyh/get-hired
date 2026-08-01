# Beta-distributed skill state with prior-only correlations

Each Skill's mastery is modeled as a **Beta distribution** (`mastery = α/(α+β)`, `confidence` derived from the variance) rather than a moving average, because the Supervisor's deviate/terminate-early judgment must read *how sure we are*, not just a point estimate — "0.3 mastery after one shaky answer" and "0.3 after four consistent misses" are different decisions. Cross-skill correlations are applied **only to the initial prior**: a strong background in one Skill shifts the starting Beta of related Skills, but once direct evidence for a Skill arrives it dominates and we do **not** cross-credit on subsequent evaluations.

Priors are **weak by default** (low pseudo-counts near neutral), so a candidate's self-claim sets only the *starting question difficulty*, never our confidence — direct evidence overrides within an answer or two. **Role criticality** (derived from `target_role` + `target_companies` via a hand-built table) further flexes prior *strength* and the evidence bar for early-termination: a Skill the role treats as must-have gets an even weaker prior and a higher evidence bar (probe hard, never trust the claim), while a peripheral Skill gets a stronger prior and low bar (trust the claim, save the question budget). Role criticality never moves the prior *mean* — the job description tells us what the role wants, not how good the candidate is. The hard max-questions cap still bounds everything, so one critical Skill can't starve the rest.

## Considered Options

The V2 plan (`MVP_v2.md`) proposed ongoing correlated updates — bumping every related Skill's α/β on each evaluation. We rejected it because it double-counts overlapping competence: answering a Deep Learning question well, then an ML-Fundamentals question, inflates ML-Fundamentals confidence from ~1 direct + 1 borrowed observation. That inflated confidence could let the Supervisor skip a Skill it never actually tested — the worst possible failure for a tool whose job is finding gaps. Prior-only correlations keep the modeling lesson and the cold-start benefit without the masked-gap bug.

## Addendum: evidence semantics (2026-07-19). Status: Proposed — items 1 and 3 only, gated on experiment E2

**Items 1 and 3 are not applied to code until this section's status is Accepted.** Item 2 was
carved out and accepted separately on 2026-08-01 — see *Addendum: evidence aggregation semantics*
below, which is the binding statement of what the code now does.

The Beta model and prior-only
correlations were independently re-derived and stand (with ≤5–8 observations per Session and no
population data, IRT-2PL is unidentifiable and Elo/Glicko has no opponent pool — Beta is
right-sized). What no one would re-derive is the current *evidence semantics*, three properties
that exist only as code accidents:

1. **Difficulty-blind updates.** `difficulty` exists (`seeds.py:61`) and drives question
   *selection*, but `apply_evaluation` never sees it: a 4.0 on a difficulty-5 question and a 4.0
   on a difficulty-1 question are identical evidence. Proposed: an IRT-lite difficulty term in
   the update (score adjusted or weighted by item difficulty) — pure arithmetic, offline-testable.
2. ~~**Last-turn-wins.**~~ **LANDED 2026-08-01 (R-24 / GH #79)** — no longer Proposed, no longer
   gated on E2. The micro-loop kept only the final turn's evaluation (then `microloop.py:316`, the
   docstring admitting "keeps the last, not the best"): a strong seed answer followed by one weak
   follow-up discarded the strong evidence entirely. Now every turn folds at weight
   `evidence_weight_for(turn)/len(turns)` so one question contributes ~EVIDENCE_WEIGHT total
   regardless of turn count, display semantics unchanged. Binding statement: *Addendum: evidence
   aggregation semantics (2026-08-01)* below.
3. **The confidence input is a dead signal.** `confidence_weight` scales evidence by the judge's
   self-report, which is saturated (≈0.95 always) — the weight range has collapsed to
   [1.93, 2.0] and the 0021 feature only bites through its deterministic caps. Proposed: the
   input becomes derived confidence (ADR 0011) when that ADR is accepted.

**Experiment E2** (offline, cheapest in the queue) — now scoped to items **1 and 3 only**: the
change behind a flag; re-run trajectory tests + persona replays (existing artifact + 2 new
personas). *Win criteria:* MAE(posterior mastery, persona ground truth) improves ≥10%, mastery
*ordering* across personas is preserved, and the property test holds (equal scores on a harder
question move mastery strictly more). *Lose:* any ordering regression — the semantics stay as they
are and this section is marked Rejected with the numbers.

*Source: ADR red-team review 2026-07-19 — verdict REAFFIRM core + AMEND evidence semantics;
panel report Phần 1 trục agentic (difficulty-blind Beta), debt #10 (last-turn-wins).*

## Addendum: evidence aggregation semantics (2026-08-01). Status: Accepted

Binding now. This section replaces item 2 of the 2026-07-19 addendum and is the specification of
what `skill.py`/`microloop.py` do today.

**(a) The question, not the turn, is the unit of evidence.** `apply_evaluations(state, turns)`
folds *every* turn the Micro-loop scored, each at `evidence_weight_for(turn) / len(turns)`. The
total a question contributes is therefore the *mean* per-turn weight — ~`EVIDENCE_WEIGHT` at full
confidence, `EVIDENCE_WEIGHT * CONFIDENCE_WEIGHT_FLOOR` at zero — and **turn count is never a
weight multiplier**. That divisor is the whole design: the number of turns is the Evaluator's
chattiness, not the Candidate's competence, so a 4-turn question must not outvote a 1-turn one 4:1
for a reason no candidate can influence. α+β is exactly what the Supervisor reads as "how sure are
we", and inflating it on a chatty exchange would let the Supervisor terminate a Skill early on
manufactured certainty — the masked-gap failure this ADR exists to avoid, arriving by a second
door. Each turn keeps its **own** dispatch through `evidence_weight_for`, so a panel-escalated
follow-up inside an otherwise unescalated question is still priced by committee agreement.

**(b) Display and belief are deliberately split, and are allowed to disagree.**
`MicroLoopResult.resolved_evaluation` and the persisted `resolved_weighted_score` /
`resolved_confidence` keep **last-turn** semantics: an exchange has to read as a conversation that
arrived somewhere, and "best turn wins" would reward flailing. A strong seed pulled down by one
weak follow-up therefore shows the weak score in the transcript and a posterior strictly above the
weak-only one. Both halves are pinned by test, in both directions.

**(c) The exported `evidence_weight` is now the total folded, not the last turn's.** `n=1` is
unchanged, so this is not a wire change and old checkpoints keep loading; on a multi-turn question
the number now answers "what actually moved the Beta". `aggregate_evidence_weight` is the single
source of truth the export and the updater share.

**(d) Nothing else in the weighting stack moved.** `evidence_weight_for`, `confidence_weight`,
`panel_agreement_weight` (0027) and `POSTMORTEM_WEIGHT_RATIO` (0026) have unchanged signatures and
unchanged behaviour. The post-mortem ratio fuses through `observe()` directly and never reaches
this path.

**(e) Why this is Accepted while E2 is not.** E2 bundles three items behind one MAE gate, and that
gate is **not measurable on current fixtures**: no offline fixture in the repo emits a multi-turn
question (`demo_llm.py` and `tests/test_replay.py`'s sim judge both hardcode
`follow_up_recommended: False`), so every persona replay has `len(turns) == 1` and the ordering /
MAE checks are satisfied *vacuously* by both the old and the new code. Claiming E2's win criterion
was met would be a fabrication. R-24 is instead accepted on a **correctness** argument: discarding
evidence the Evaluator already produced is a defect, not a tuning knob — the old posterior was
provably bit-identical to `apply_evaluation(prior, last_turn)` no matter how many turns were
scored. The preserved-ordering half of the gate is verified (replay + trajectory suites green,
all six serde goldens byte-identical without regeneration), with the caveat that it is preserved
vacuously. The MAE gate stays attached to items 1 and 3, which are genuine modelling changes with a
tunable knob and no correctness argument behind them. Building a multi-turn persona fixture is the
prerequisite for running E2 at all, and is not blocked by this change.
