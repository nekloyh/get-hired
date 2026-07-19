# Agent Design & Implementation — Source of Truth

This file tells any agent or contributor where the authoritative design lives, so implementation does not drift toward the older planning docs.

## Quick Links (authoritative — read in this order)

1. **`/CONTEXT.md`** — domain glossary. Use these exact terms (Candidate, Session, Interviewer, Evaluator, Supervisor, Micro-loop, Macro-loop, Skill, Topic Plan, Role criticality, Follow-up, Self-critique, Derived confidence, Budget exhaustion, Coaching memory).
2. **`/docs/adr/`** — the binding architectural decisions (0001–0014). **These win over everything else.** Sections and files marked `Status: Proposed` are experiment-gated hypotheses — do NOT implement from them until their status is Accepted; everything else (including addenda dated 2026-07-19) is binding now.
3. **`/docs/issues/`** — the build plan as vertical slices (0001–0037). Slice status lives in the doc's `## Status` section; live work status lives in GitHub Issues (the remediation backlog R-01→R-33 maps to GH #56–#88, `R-NN = #(55+NN)`).

## Reference — background only, do NOT implement from these

- `/docs/reference/MVP_v1_2day.md` — original 2-day build blueprint. ⚠️ archived
- `/docs/reference/MVP_v2.md` — original V2 critique/roadmap. ⚠️ archived

These are optimized for shipping fast / recruiter signal. That is **not** this project's priority order, which is: **(1) learn agentic systems, (2) a usable prep tool, (3) recruiter signal.** Where these docs conflict with an ADR, the ADR wins.

## For Implementers

Start with the issue drafts in `/docs/issues/`. Each is a thin vertical slice with acceptance criteria. The critical path to a running multi-question session (**0001 → 0002 → 0005 → {0006, 0007, 0009} → 0010**) is complete; current work is the remediation backlog (GH #56–#88, waves Now/Next/Later).

### Where the ADRs override the MVP docs (common traps)

The MVP docs will mislead you on these — trust the ADR:

- **The Supervisor is NOT an LLM that routes every decision.** It is a plan-executor over the Topic Plan with a single LLM "deviate?" judgment. `deep_dive` and `self_critique` are not Supervisor actions. (Whether even that one LLM call earns its keep is on trial — experiment E1, `ADR 0001` amendment.) → `ADR 0001`
- **The Evaluator is the only judge.** The Interviewer never scores. Self-critique lives inside the Evaluator's micro-loop — but note its low-confidence trigger is measurably dormant on the current judge; the replacement signal is `ADR 0011` (Proposed). → `ADR 0001`, `ADR 0011`
- **Skill correlations are prior-only**, never ongoing per-evaluation cross-credits. Priors are weak; Role criticality flexes prior *strength* and the early-termination bar, never the prior *mean*. → `ADR 0002`
- **Tool-calling is confined to the Interviewer — but for the surviving reason, not the original one.** The MiMo quirk that motivated it is historical; the live principle is *tools per proven need, every grant carries an eval gate* (judge→bench, Supervisor→replay). Injecting context into single-shot prompts (e.g. a concept note into the Evaluator) is compliant and is not "adding tools". → `ADR 0003` addendum
- **Never swap the judge model silently — at merge time OR runtime.** Judge changes gate on `coach bench` (ADR 0009); the judge role is pinned and its failover never changes model (ADR 0009 addendum a). The bench itself is a stochastic measurement — see the k=3 repeatability rules (addendum b). → `ADR 0009`, `ADR 0010`
- **Infrastructure noise must never corrupt skill evidence; human intent must never become fake evidence** — and budget exhaustion is its own third category: suspend-and-resume, never `failed`-and-advance. → `ADR 0005`
- **Cross-session memory: probing & judging surfaces never see prior transcripts; presentation & planning surfaces may.** Scoring memory stays decayed Beta priors. → `ADR 0006`

### Deferred / reshaped — sync with the 2026-07-19 red-team verdicts

The old blanket list ("multi-judge consensus, modern RAG, cross-session memory, observability dashboard — all future work") is superseded by per-item verdicts:

- **Multi-judge consensus** — *reshaped, not deferred.* Debate-as-score-corrector was measured worthless on this judge (verdict moved 0.00 in 10 forced escalations); cheap multi-vote as an **uncertainty** signal is `ADR 0011` (Proposed, gated E4/E5). Do not build score-averaging consensus.
- **Modern RAG (HyDE / hybrid / rerank)** — *deferral reaffirmed with data:* the toy store scores 47/50 vs embedders' 46–47/50 at current shelf size; the Skill filter does the work. Upgrade triggers are recorded in R-13 (GH #68); revisit when taxonomy-as-data (`ADR 0014`) changes the shelf.
- **Cross-session transcript memory** — *split:* scoring memory stays decayed priors (`ADR 0006`, unchanged); **coaching memory** on presentation/planning surfaces is allowed by the 0006 addendum and consumed by slice 0035 (GH #83).
- **Observability** — *split:* a minimal per-call LLM trace is **current work**, not future (silent judge failover is undiagnosable without it — R-26/GH #81); the *dashboard* remains Later (R-28/GH #83).

## Provider note

**MiMo is dead** (endpoint retired 2026-06-03 — issue 0015 audit); any MiMo-primary instruction you find is stale. The validated judge is **OpenAI `gpt-5.4-mini`** (bench bands re-anchored to it, 29/29 — with the k=3 flake documented in `docs/audits/calibration-bench-2026-07-19.md` and GH #92). Groq is an *availability* fallback that does **not** pass the judge bench (18/20, VN Δ=2.00) — per ADR 0009's addendum the judge role must never fail over onto it; until per-role routing (ADR 0010) lands, treat any judge-model switch as a bench-gated change. All LLM calls go through the `LLMRouter` — no agent imports a provider client directly.
