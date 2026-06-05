# Session per-question failure isolation

**Type:** AFK

## What to build

Make the LangGraph **Session** (slice 0010) survive a failure inside a single question instead of
aborting the whole multi-question run. Today any exception raised inside `question_node` —
`run_micro_loop` → Evaluator / Interviewer — propagates out of `graph.invoke` and kills the Session,
losing every resolved question so far. This is too brittle for a multi-question interview that
depends on a flaky external provider (MiMo) and tool calls.

Two concrete failure modes seen live during the 0010 audit:

- **Transient malformed tool name.** MiMo returned `'lookup_conparameter'` instead of
  `'lookup_concept'`; the Interviewer's native-tool path (`interviewer.py` `execute`) hard-raises
  `ValueError("interviewer received an unexpected tool call: ...")`, which aborts the Session. A
  re-run succeeded, confirming it is transient model noise — not an integration bug.
- **Missing concept note.** `lookup_concept` raises `LookupError` when no note matches the Skill
  filter. Patched for `deep_learning` in 0010 by adding the note + a coverage test, but the
  underlying hard-raise still kills the Session for any future uncovered Skill/filter.

The fix must respect the existing deliberate **fail-loudly** design for the tool path (`ADR 0003`):
the goal is Session-level resilience, not silently swallowing every error. Decide the boundary —
e.g. retry the question once, then record a `failed`/`skipped` question in the transcript and let the
Supervisor advance, versus a bounded internal retry inside the Interviewer for malformed tool names.

## Acceptance criteria

- [x] A transient failure in one question (raised tool/Evaluator/Interviewer error) does not abort
      the Session; resolved questions so far are preserved and the run can continue or end cleanly.
- [x] The failure mode is recorded in the transcript (a `failed` stop reason) so it is visible,
      not silently swallowed — the fail-loudly intent (`ADR 0003`) is preserved at the right layer.
- [x] A malformed/unexpected tool name from the provider is retried a bounded number of times before
      it degrades (retry-once-then-`FollowUpUnavailable`); the Session-level catch backstops anything else.
- [x] `lookup_concept` with no matching note degrades to a defined behaviour (resolves the question
      without a follow-up, `FOLLOW_UP_UNAVAILABLE`) rather than crashing the Session.
- [x] Tests cover both failure modes through the Session graph (a fake client/micro-loop that raises once).

## Done

- `question_node` now wraps `run_micro_loop` in `try/except`: an error records a `failed` question
  (`_dump_failed_question`, new `StopReason.FAILED`) with the Skill's unchanged prior belief and a
  visible `error`, bumps `question_count`, and lets the Supervisor advance — mirroring the existing
  `study_plan_node` crash-resilience pattern.
- `lookup_concept` `LookupError` is caught inside the Interviewer (both native and JSON follow-up
  paths) and converted to the existing `FollowUpUnavailable` degrade. On the native path the miss is
  caught *inside* the tool executor so it never surfaces to the provider router as a transport fault
  (which would trip a spurious failover).
- The Markdown export renders a failed question honestly (shows the error, skips the misleading score).
- The CLI display now labels `failed` and `follow_up_unavailable` distinctly instead of presenting
  every non-resolved stop as a safety-cap halt.

## Verified

- `uv run pytest` -> 154 passed, 7 deselected. New: graph-level failure isolation
  (`test_question_failure_is_isolated_and_session_continues`) and concept-miss degrade on both the
  native and JSON paths (`tests/test_interviewer.py`), plus CLI degrade-label coverage.
- `uv run ruff check .` -> all checks passed.
- Offline smoke: forced `run_micro_loop` failure records a `failed` transcript entry, preserves the
  Session, and Markdown renders "Question failed and was skipped".
- Offline smoke: missing concept store resolves the micro-loop as `follow_up_unavailable`, keeps the
  last score, and does not crash.
- Live smoke: `uv run coach session --scripted --max-questions 1 --export-markdown ...` completed
  through MiMo, produced a Study Plan, and exported Markdown.

## Blocked by

- 0010 (the Session graph this hardens)
