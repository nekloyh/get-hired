# Web: cancel/disconnect lifecycle correctness

**Type:** AFK
**Kind:** bug

## What to build

The web backend converts Candidate intent into corrupt data (confirmed by code trace). Both the
cancel branch and the disconnect handler set the cancelled flag and then put `""` into the answers
queue — but `QueueCandidate.answer` is almost always blocked inside `answers.get(...)`, which
returns that `""` sentinel **as a real answer** before ever re-checking the flag. Closing the tab
while a question is pending means the Evaluator scores an empty answer (burning post-disconnect
LLM tokens and dragging the Beta skill state down into a checkpoint), or the question gets
permanently recorded as `failed`. Two further lifecycle gaps: the cancelled flag and answers queue
are never reset between runs on one socket, and two tabs opening the same `session_id` run two
concurrent graphs against one checkpoint thread.

Fix the lifecycle per ADR 0005: cancellation is a **control signal**, never data. Use a distinct
sentinel object checked inside `QueueCandidate`; reset per-run state; give concurrent connections
to one Session a defined outcome (reject the second with a clear message, or take over cleanly —
pick one and test it).

## Acceptance criteria

- [x] Closing the tab / cancelling while a question is pending never produces an evaluation of an
      empty answer and never records the question as failed with zero evidence
- [x] Cancellation surfaces as a distinct control-flow outcome; the in-flight question remains
      resumable (the audit confirmed resume itself works — the question must survive too)
- [x] Cancelled flag + answers queue reset between runs on one socket: start → cancel → start
      again works without stale state
- [x] A second connection on the same `session_id` has a defined, tested behavior
- [x] Offline tests drive cancel-mid-question and double-connect through the web API

## Blocked by

- ADR 0005 (candidate intent aborts; infrastructure degrades) — read it first; this issue is its
  web-transport half, issue 0018 is the terminal half

## Done

- Replaced the `""` disconnect/cancel sentinel with a distinct `_CANCEL = object()` control signal
  (`web_api.py`). `QueueCandidate.answer()` checks the cancelled flag *and* the sentinel around the
  blocking `answers.get()`, so a genuine empty-string answer now flows through as data while a cancel
  raises `CandidateInputUnavailable` — the empty-answer-scored-as-evidence bug is gone.
- `_run_session_thread` now catches `CandidateIntent` in a branch distinct from the infrastructure
  `except Exception`: it reports "Session cancelled" without scoring, and — because the supervisor
  re-raises intent past the per-question failure-isolation net — the in-flight question is never
  recorded as a zero-evidence `failed` and the checkpoint stays resumable.
- `RuntimeSession.reset_run_state()` assigns a fresh queue + `Event` before each start/resume, so
  start → cancel → start on one socket no longer inherits a set cancelled flag or a stale sentinel.
- A second WebSocket to a `session_id` that already has a live connection is rejected with a clear
  `session_error` and closed; the `finally` cleanup only drops the map entry when it is still its own,
  so the reject can't evict the live connection.
- `EventEmitter` drops events when the socket's event loop is already gone (disconnect/teardown)
  instead of crashing the background graph thread with `RuntimeError: Event loop is closed`.

## Verified

- `uv run pytest tests/test_web_api.py -q` — 7 passed, including the four new lifecycle tests:
  cancel-mid-question scores nothing (export 404s), resume-after-cancel records the *real* answer,
  start → cancel → start clears stale state, and a second connection is rejected.
- `uv run pytest -q` — 169 passed, `ruff check` clean.

## Status

**Closed.** Acceptance criteria are implemented and covered.
