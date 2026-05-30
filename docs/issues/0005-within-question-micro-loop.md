# Within-question micro-loop

**Type:** AFK

## What to build

The **Micro-loop** that owns a single question end-to-end (see `ADR 0001`). The **Interviewer** asks a question; the **Candidate** (fixture) answers; the **Evaluator** scores every turn (B1) and emits `follow_up_recommended`; if a **Follow-up** is flagged and the safety cap is not hit, the Interviewer generates one (a plain LLM call for now — the RAG tool arrives in slice 0007) and asks it; repeat; otherwise stop and keep the last score. The cap is a guardrail, not the stop logic. Ships with 3–5 seed questions for a single Skill so the loop has real content.

Orchestrated in plain Python (LangGraph is deferred to slice 0010 per `ADR 0004`).

## Acceptance criteria

- [ ] A weak fixture answer triggers a Follow-up; a strong one does not
- [ ] The score is recomputed each turn and the last score is what the question resolves to
- [ ] The Follow-up cannot be answered by repeating the original answer (it targets the gap)
- [ ] The safety cap halts a pathological loop, and this is logged as a guardrail trip distinct from a normal stop
- [ ] On loop exit, the resolved Skill state is updated (via slice 0002)

## Blocked by

- 0001 (Evaluator)
- 0002 (skill-state update on resolution)
