# Supervisor + LangGraph migration

**Type:** AFK

## What to build

The **Macro-loop** and the move to LangGraph (see `ADR 0001` and `ADR 0004`). Build the **Supervisor** as a plan-executor over the **Topic Plan**: by default it walks the plan, and it makes a single LLM-judged decision per resolved question — whether emerging Skill evidence justifies *deviating* (extra question, skip ahead, switch Skill, end early). Hard caps (max questions, max time) are deterministic rails. Then migrate the hand-rolled Python orchestration from earlier slices into a LangGraph `StateGraph` over a single session state, with `SqliteSaver` checkpointing (resume by session id) and a `draw_mermaid_png()` architecture diagram. Agents don't change — only the wiring.

## Acceptance criteria

- [ ] After a resolved question the Supervisor either advances the plan or deviates, and logs the LLM reasoning for deviations
- [ ] A consistently strong Candidate triggers early termination; a struggling one triggers more probing or a Skill switch
- [ ] Hard caps bound the session regardless of the LLM's choices
- [ ] A multi-question session runs through the StateGraph and can be resumed mid-session from the SqliteSaver checkpoint by session id
- [ ] The architecture diagram exports to an image file

## Blocked by

- 0006 (reflection in the micro-loop)
- 0007 (tool-using Interviewer)
- 0009 (Topic Plan to execute)
