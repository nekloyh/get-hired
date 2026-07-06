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

- [ ] Closing the tab / cancelling while a question is pending never produces an evaluation of an
      empty answer and never records the question as failed with zero evidence
- [ ] Cancellation surfaces as a distinct control-flow outcome; the in-flight question remains
      resumable (the audit confirmed resume itself works — the question must survive too)
- [ ] Cancelled flag + answers queue reset between runs on one socket: start → cancel → start
      again works without stale state
- [ ] A second connection on the same `session_id` has a defined, tested behavior
- [ ] Offline tests drive cancel-mid-question and double-connect through the web API

## Blocked by

- ADR 0005 (candidate intent aborts; infrastructure degrades) — read it first; this issue is its
  web-transport half, issue 0018 is the terminal half

## Status

**Open.**
