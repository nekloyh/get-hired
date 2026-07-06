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

- [ ] Resuming a Session after a long gap does not force-complete on the time rail; the chosen
      clock semantics are documented
- [ ] `max_elapsed_seconds` finally has a test (currently none)
- [ ] `--resume` with an unknown id exits with a clear one-line error that tells the user how to
      find valid session ids
- [ ] Resuming prints a compact recap (questions resolved so far, current Skill) instead of
      re-printing history as live updates
- [ ] Forgetting `--resume` while a default-thread Session is in flight no longer silently
      restarts over it — warn or refuse

## Blocked by

None — can start immediately.

## Status

**Open.**
