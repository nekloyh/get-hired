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

- [ ] A transient failure in one question (raised tool/Evaluator/Interviewer error) does not abort
      the Session; resolved questions so far are preserved and the run can continue or end cleanly.
- [ ] The failure mode is recorded in the transcript (e.g. a `failed` stop reason) so it is visible,
      not silently swallowed — the fail-loudly intent (`ADR 0003`) is preserved at the right layer.
- [ ] A malformed/unexpected tool name from the provider is retried a bounded number of times before
      it is treated as a failed question.
- [ ] `lookup_concept` with no matching note degrades to a defined behaviour (defined fallback or a
      recorded failed question) rather than crashing the Session.
- [ ] Tests cover both failure modes through the Session graph (a fake client that raises once).

## Blocked by

- 0010 (the Session graph this hardens)
