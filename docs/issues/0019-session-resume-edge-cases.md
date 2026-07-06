# Session resume edge cases: clock, unknown id, replayed history

**Type:** AFK
**Kind:** bug

## What to build

Resume works at question granularity (tested through a real SqliteSaver), but three confirmed
papercuts make multi-day usage broken in practice:

- **The clock keeps running while you're gone.** `max_elapsed_seconds` measures wall-clock since
  Session creation, so resuming tomorrow force-completes after one question. This also silently
  blocks every future multi-day feature (drip practice, issue 0026's flows). The audit found this
  rail has zero test coverage.
- **Unknown `--resume` id crashes raw.** Resuming a session id with no checkpoint surfaces
  langgraph's `EmptyInputError` ("Received no input for `__start__`") as a bare traceback.
- **History replays as live.** Resuming in live mode re-prints every historical question as a
  "LIVE UPDATE" because the seen-questions counter starts at zero instead of from the checkpoint.

Make resume a first-class flow: the time cap counts active interviewing time (or resets on resume
— decide and document in the close-out), unknown ids fail with a friendly one-liner, and resuming
prints a compact recap instead of replaying history.

## Acceptance criteria

- [x] Resuming a Session after a long gap does not force-complete on the time rail; the chosen
      clock semantics are documented
- [x] `max_elapsed_seconds` finally has a test (currently none)
- [x] `--resume` with an unknown id exits with a clear one-line error that tells the user how to
      find valid session ids
- [x] Resuming prints a compact recap (questions resolved so far, current Skill) instead of
      re-printing history as live updates
- [x] Forgetting `--resume` while a default-thread Session is in flight no longer silently
      restarts over it — warn or refuse

## Blocked by

None — can start immediately.

## Done

- **Clock semantics:** `--resume` resets `started_at` (`graph.update_state`), so `max_elapsed_seconds`
  bounds a single sitting and a Session picked up after a gap is not force-completed. Documented in the
  `--resume` / `--max-elapsed-seconds` help.
- **Unknown id:** new `resumable_session_state` helper; an unknown `--resume` id exits with a friendly
  one-liner that lists known Session ids (`_known_session_ids` via the checkpointer connection) instead
  of surfacing langgraph's `EmptyInputError`.
- **No replayed history:** `_run_session_graph` gained `already_seen` so resumed questions are not
  reprinted as live updates; `_print_resume_recap` prints a compact recap (resolved count + current Skill).
- **In-flight guard:** starting without `--resume` over a non-complete checkpoint on the same id is
  refused with a clear message rather than silently restarting over it.

## Verified

- `uv run pytest` -> 165 passed. New graph-level tests: `test_max_elapsed_seconds_hard_rail_ends_session`
  (the rail's first test), `test_resumable_session_state_returns_none_for_unknown_id`,
  `test_resume_resets_elapsed_clock_so_a_long_gap_does_not_force_complete`. New CLI-level tests:
  `test_run_session_graph_does_not_replay_resumed_history_as_live`,
  `test_session_refuses_to_restart_over_inflight_checkpoint` (+ a complete-checkpoint companion),
  `test_cmd_session_resume_resets_clock_via_cli`, `test_unknown_resume_message_hints_when_no_checkpoints`.
- The three CLI-path tests were mutation-checked: each fails when its fix is reverted. Real CLI smoke
  covered the unknown-id message, the resume recap, and the in-flight guard.

## Status

**Closed.** Acceptance criteria are implemented and covered.
