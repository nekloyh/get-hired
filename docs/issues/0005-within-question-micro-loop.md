# Within-question micro-loop

**Type:** AFK

## What to build

The **Micro-loop** that owns a single question end-to-end (see `ADR 0001`). The **Interviewer** asks a question; the **Candidate** (fixture) answers; the **Evaluator** scores every turn (B1) and emits `follow_up_recommended`; if a **Follow-up** is flagged and the safety cap is not hit, the Interviewer generates one (a plain LLM call for now — the RAG tool arrives in slice 0007) and asks it; repeat; otherwise stop and keep the last score. The cap is a guardrail, not the stop logic. Ships with 3–5 seed questions for a single Skill so the loop has real content.

Orchestrated in plain Python (LangGraph is deferred to slice 0010 per `ADR 0004`).

## Acceptance criteria

- [x] A weak fixture answer triggers a Follow-up; a strong one does not
- [x] The score is recomputed each turn and the last score is what the question resolves to
- [x] The Follow-up cannot be answered by repeating the original answer (it targets the gap)
- [x] The safety cap halts a pathological loop, and this is logged as a guardrail trip distinct from a normal stop
- [x] On loop exit, the resolved Skill state is updated (via slice 0002)

## Blocked by

- 0001 (Evaluator)
- 0002 (skill-state update on resolution)

## Done

`run_micro_loop` in `src/interview_coach/microloop.py` orchestrates the loop in plain Python: it
evaluates every turn (slice 0001), and when `follow_up_recommended` is set and the cap is not hit it
calls the new **Interviewer** (`interviewer.generate_follow_up`, a single-shot `chat_json` call fed the
weakest dimensions + the Evaluator's rationale so the Follow-up targets the gap — RAG tools wait for
0007). The "must not be answerable by repeating the original answer" criterion is enforced, not just
prompted: a validator (`interviewer._make_validators`, the extension point for 0007's grounding checks)
rejects a Follow-up whose normalized question restates the original, and the `chat_json` retry
regenerates. The Evaluator's flag is the stop logic; `max_turns` (default 4 = 1 question + 3 follow-ups) is a
guardrail whose trip is a distinct `StopReason.SAFETY_CAP` logged at WARNING, separate from the INFO
`RESOLVED` path. The last turn's score is kept either way and folded into the Skill state via slice
0002's `apply_evaluation`. The fixture **Candidate** is `ScriptedCandidate` over the three seed
questions in `seeds.py`. `coach interview` runs it; covered by `tests/test_microloop.py` +
`tests/test_interviewer.py` (offline, with live sanity checks marked `live`).
