# Hand-roll orchestration first; adopt LangGraph at the persistence seam

Early slices (the micro-loop, reflection, tool-using Interviewer, Diagnostic) are orchestrated in **plain Python** — a simple loop calling typed agents. LangGraph is introduced only at the Supervisor/macro-loop slice, where multi-question state, checkpointing, and resume genuinely pay off; at that point the hand-rolled glue is migrated into a `StateGraph` + `SqliteSaver` (the agents themselves don't change — only the wiring).

## Why

The planning docs (`MVP_v1_2day.md`, `MVP_v2.md`) recommend LangGraph from day one — the *ship-fast* answer. The project's top priority is **learning agentic systems**, and the deeper lesson comes from feeling what statefulness, control flow, and resume cost by hand *before* adopting the framework, so the value LangGraph provides is understood rather than assumed. The cost is one rewrite of the orchestration glue, which is itself part of the lesson. This is a deliberate deviation, not an oversight: do not retrofit LangGraph into the early slices.

## Status (2026-07-19): executed — historical

The sequencing decision this ADR exists for was **consumed** when slice 0010 performed the
migration; there is nothing left to comply with, and nothing here freezes today's orchestration.
Recorded so future readers stop treating it as a live constraint:

- The lesson (hand-rolled statefulness → felt cost → framework adoption) is captured in issue 0010
  and the git history; that record *is* this ADR's remaining value.
- The live dependency is the **checkpointer seam** (`SqliteSaver`, and whatever replaces it —
  see issue 0036's Postgres path), not `StateGraph` itself. Re-derived today from zero, one would
  start *with* a framework; keeping LangGraph is a cost/benefit statement (migration away buys
  nothing at this scale), not a principle.
- Future orchestration changes are governed by the replay bench (issue 0029) and new ADRs, not by
  this document.

*Source: ADR red-team review 2026-07-19 — verdict REAFFIRM-AS-EXECUTED (historical).*
