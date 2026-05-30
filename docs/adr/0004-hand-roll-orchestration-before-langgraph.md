# Hand-roll orchestration first; adopt LangGraph at the persistence seam

Early slices (the micro-loop, reflection, tool-using Interviewer, Diagnostic) are orchestrated in **plain Python** — a simple loop calling typed agents. LangGraph is introduced only at the Supervisor/macro-loop slice, where multi-question state, checkpointing, and resume genuinely pay off; at that point the hand-rolled glue is migrated into a `StateGraph` + `SqliteSaver` (the agents themselves don't change — only the wiring).

## Why

The planning docs (`MVP_v1_2day.md`, `MVP_v2.md`) recommend LangGraph from day one — the *ship-fast* answer. The project's top priority is **learning agentic systems**, and the deeper lesson comes from feeling what statefulness, control flow, and resume cost by hand *before* adopting the framework, so the value LangGraph provides is understood rather than assumed. The cost is one rewrite of the orchestration glue, which is itself part of the lesson. This is a deliberate deviation, not an oversight: do not retrofit LangGraph into the early slices.
