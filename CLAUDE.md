# Agent Design & Implementation — Source of Truth

This file tells any agent or contributor where the authoritative design lives, so implementation does not drift toward the older planning docs.

## Quick Links (authoritative — read in this order)

1. **`/CONTEXT.md`** — domain glossary. Use these exact terms (Candidate, Session, Interviewer, Evaluator, Supervisor, Micro-loop, Macro-loop, Skill, Topic Plan, Role criticality, Follow-up, Self-critique, Derived confidence, Budget exhaustion, Coaching memory).
2. **`/docs/adr/`** — the binding architectural decisions. Thirteen files, numbered 0001–0011, 0014 and 0015; **there is no 0012 or 0013** and never was, so a missing number is not a missing document. **These win over everything else.** Sections and files marked `Status: Proposed` are experiment-gated hypotheses — do NOT implement from them until their status is Accepted; everything else (including addenda dated 2026-07-19) is binding now.
3. **[GitHub milestones](https://github.com/nekloyh/get-hired/milestones)**: the only place work, its order and its status live. `v0.3.0 Stable`, then `v0.4.0 Foundation`; `Later` is frozen until both close. **[`/docs/issues/README.md`](docs/issues/README.md)** holds the tracking rules and the alias table (`R-NN = #(55+NN)`, work IDs `F1`/`Q1`/…, `M0a`–`M6`). **`/docs/issues/00NN-*.md`** are slice specs: design and acceptance criteria. Their `## Status` sections are historical.
4. **[`/docs/roadmap.md`](docs/roadmap.md)**: direction. It says what unblocks what and what the hardware can host. Subordinate to the ADRs and the milestones; it answers *why in this order*, not *what is in each milestone*.

## Three rules for anything you write here

- **Status lives in GitHub, `CHANGELOG.md` and ADR `Status:` lines, nowhere else.** Never write "currently", a gate's score or "done" into an evergreen doc, this file included. This file said the judge was green at 35/35 for two months after the gate went red.
- **New work is `#NN`.** Do not mint new `R-NN`, work IDs or milestone letters.
- **Cite `module.symbol`, not `file:line`.** Line numbers die at the next refactor; #124 broke every open issue that cited `web_api.py`. A dated record in `docs/audits/` may cite lines, because it names its commit.

## Deleted: the original MVP planning docs

`/docs/reference/MVP_v1_2day.md` and `MVP_v2.md` (1,261 lines) were removed — every agent was told to load them and then told not to implement from them, which is the worst of both. They are in git history if you need them; `git log --diff-filter=D -- docs/reference` finds the commit.

They were optimized for shipping fast / recruiter signal. That is **not** this project's priority order, which is: **(1) learn agentic systems, (2) a usable prep tool, (3) recruiter signal.** Everything they said that still holds is in an ADR, and where they conflicted with one, the ADR won.

## For Implementers

Start from the open issues of the earliest open milestone. Each links its slice spec in `/docs/issues/` when one exists. To learn the design, read the slice critical path **0001 → 0002 → 0005 → {0006, 0007, 0009} → 0010**. Before quoting an issue's evidence, check it against the code: an issue body is true as of the day it was filed. Reuse the existing GitHub trackers. Accounts are a public-launch gate, not a prerequisite for the trusted-pilot dashboard. Before every push, run `scripts/gate.sh`: one `PASS`/`FAIL` per check and a single verdict line.

### Where the ADRs override the MVP docs (common traps)

The MVP docs will mislead you on these — trust the ADR:

- **The Supervisor is NOT an LLM that routes every decision.** It is a plan-executor over the Topic Plan with a single LLM "deviate?" judgment. `deep_dive` and `self_critique` are not Supervisor actions. (Whether even that one LLM call earns its keep is on trial — experiment E1, `ADR 0001` amendment.) → `ADR 0001`
- **The Evaluator is the only judge.** The Interviewer never scores. Self-critique lives inside the Evaluator's micro-loop — but note its low-confidence trigger is measurably dormant on the current judge; the replacement signal is `ADR 0011` (Proposed). → `ADR 0001`, `ADR 0011`
- **Skill correlations are prior-only**, never ongoing per-evaluation cross-credits. Priors are weak; Role criticality flexes prior *strength* and the early-termination bar, never the prior *mean*. → `ADR 0002`
- **Tool-calling is confined to the Interviewer — but for the surviving reason, not the original one.** The MiMo quirk that motivated it is historical; the live principle is *tools per proven need, every grant carries an eval gate* (judge→bench, Supervisor→replay). Injecting context into single-shot prompts (e.g. a concept note into the Evaluator) is compliant and is not "adding tools". → `ADR 0003` addendum
- **Never swap the judge model silently — at merge time OR runtime.** Judge changes gate on `coach bench` (ADR 0009); the judge role is pinned and its failover never changes model (ADR 0009 addendum a). The bench is a stochastic measurement, so **the gate is median-of-k (k=3) at the production temperature** — one run is not a measurement, and a band is never widened to turn a red green (addenda b and d). → `ADR 0009`, `ADR 0010`
- **A missing middle BARS anchor is a language-fairness bug.** A dimension with a gap in its 1–5 scale lets the judge resolve the gap on *style*, and idiomatic Vietnamese reads as more authoritative than clumsy English — measured, not theorised: `correctness` had no `3` and split the same answer 2 (EN) vs 4 (VN). The dimensions that still have that hole are tracked in #96 and #103. → `ADR 0009` addendum d
- **Infrastructure noise must never corrupt skill evidence; human intent must never become fake evidence** — and budget exhaustion is its own third category: suspend-and-resume, never `failed`-and-advance. → `ADR 0005`
- **Cross-session memory: probing & judging surfaces never see prior transcripts; presentation & planning surfaces may.** Scoring memory stays decayed Beta priors. → `ADR 0006`

### Deferred / reshaped — sync with the 2026-07-19 red-team verdicts

The old blanket list ("multi-judge consensus, modern RAG, cross-session memory, observability dashboard — all future work") is superseded by per-item verdicts:

- **Multi-judge consensus** — *reshaped, not deferred.* Debate-as-score-corrector was measured worthless on this judge (verdict moved 0.00 in 10 forced escalations); cheap multi-vote as an **uncertainty** signal is `ADR 0011` (Proposed, gated E4/E5). Do not build score-averaging consensus.
- **Modern RAG (HyDE / hybrid / rerank)** — *deferral reaffirmed with data:* the toy store scores 47/50 vs embedders' 46–47/50 at current shelf size; the Skill filter does the work. Upgrade triggers are recorded in R-13 (GH #68); revisit when taxonomy-as-data (`ADR 0014`) changes the shelf.
- **Cross-session transcript memory** — *split:* scoring memory stays decayed priors (`ADR 0006`, unchanged); **coaching memory** on presentation/planning surfaces is allowed by the 0006 addendum and consumed by slice 0035 (GH #83).
- **Observability** — *split:* the minimal per-call LLM trace **landed** (R-26/GH #81) — every provider call logs `llm-call provider= model= ms= prompt= completion= outcome= session= question= turn= role=` (the last four since #144), and `TurnTrace.llm_calls_by_provider` puts the per-turn provider split in the export, which is what makes a silent judge failover visible after the fact. The Candidate progress dashboard is #83, which needs Skill history (#127) first. A separate operations dashboard remains deferred.

## Provider note

**MiMo is dead** (endpoint retired 2026-06-03 — issue 0015 audit); any MiMo-primary instruction you find is stale. The judge is **OpenAI `gpt-5.4-mini`**. Its measured bench state is deliberately **not** written here: [`judge.lock`](judge.lock) names the bench artifact that measured the judge the code builds, and `tests/test_judge_lock.py` goes red on *any* change to what the judge is sent (ADR 0009 addendum g). A red there is the gate, not a test to update. This line said "green at 35/35" for two months after the gate went red. A bench run only measures a judge change when the run is repeated: median-of-k at k=3, with several invocations per wording. `coach bench` scores fixed, hand-labelled answers, so every token it spends is a judge token. Groq is an *availability* fallback that does **not** pass the judge bench (18/20, VN Δ=2.00) — per ADR 0009's addendum the judge role must never fail over onto it. Per-role routing landed in #95, so the judge role is pinned in code; any judge-model switch is still a bench-gated change. All LLM calls go through the `LLMRouter` — no agent imports a provider client directly.
