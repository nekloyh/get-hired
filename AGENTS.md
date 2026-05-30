# Agent Design & Implementation — Source of Truth

This file tells any agent or contributor where the authoritative design lives, so implementation does not drift toward the older planning docs.

## Quick Links (authoritative — read in this order)

1. **`/CONTEXT.md`** — domain glossary. Use these exact terms (Candidate, Session, Interviewer, Evaluator, Supervisor, Micro-loop, Macro-loop, Skill, Topic Plan, Role criticality, Follow-up, Self-critique).
2. **`/docs/adr/`** — the binding architectural decisions (0001–0004). **These win over everything else.**
3. **`/docs/issues/`** — the build plan as vertical slices (0001–0013), in dependency order. Start at 0001.

## Reference — background only, do NOT implement from these

- `/docs/reference/MVP_v1_2day.md` — original 2-day build blueprint. ⚠️ archived
- `/docs/reference/MVP_v2.md` — original V2 critique/roadmap. ⚠️ archived

These are optimized for shipping fast / recruiter signal. That is **not** this project's priority order, which is: **(1) learn agentic systems, (2) a usable prep tool, (3) recruiter signal.** Where these docs conflict with an ADR, the ADR wins.

## For Implementers

Start with the issue drafts in `/docs/issues/`. Each is a thin vertical slice with acceptance criteria. The critical path to a running multi-question session is **0001 → 0002 → 0005 → {0006, 0007, 0009} → 0010**.

### Where the ADRs override the MVP docs (common traps)

The MVP docs will mislead you on these — trust the ADR:

- **The Supervisor is NOT an LLM that routes every decision.** It is a plan-executor over the Topic Plan with a single LLM "deviate?" judgment. `deep_dive` and `self_critique` are not Supervisor actions. → `ADR 0001`
- **The Evaluator is the only judge.** The Interviewer never scores — it asks questions and generates follow-ups. Self-critique lives inside the Evaluator's micro-loop. → `ADR 0001`
- **Skill correlations are prior-only**, never ongoing per-evaluation cross-credits. Priors are weak; Role criticality flexes prior *strength* and the early-termination bar, never the prior *mean*. → `ADR 0002`
- **Tool-calling is confined to the Interviewer.** Every other agent is single-shot with state injected directly — this keeps MiMo thinking mode usable and quarantines the `reasoning_content` quirk. Do not give every agent its own tools. → `ADR 0003`
- **Orchestration is hand-rolled Python first; LangGraph enters at slice 0010**, not day one. → `ADR 0004`

### Deferred — explicitly NOT in scope now

Multi-judge evaluator consensus, modern RAG (HyDE / hybrid / rerank), long-term cross-session memory, and an observability dashboard are **future work**, each its own learning project. Do not pull them into the MVP because an MVP doc frames them as "high signal."

## Provider note

MiMo is the primary LLM provider; a planned cutover to Groq is due **2026-06-03** (see issue 0004). All LLM calls go through the `LLMRouter` — no agent imports a provider client directly; swapping providers is one env var.
