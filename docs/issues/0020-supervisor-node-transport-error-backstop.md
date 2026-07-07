# Supervisor decision node: transport-error backstop

**Type:** AFK
**Kind:** bug

## What to build

`decide_next_move` defends against schema-invalid model output (`StructuredOutputError` → one
feedback retry → deterministic fallback), but a transport-level provider failure — timeout, 4xx
after fallback exhaustion — at this node crashes the whole run. It is the only unprotected LLM
call site in the macro-loop: `question_node` records a failed question and advances, and
`study_plan_node` records `study_plan_error` and completes, but the Supervisor's own call has no
backstop. Given the provider situation (issue 0015), this is the next crash a live Session hits.

Mirror the established pattern: on a provider/transport error at the decision node, log it
distinctly (a transport degrade is not a schema fallback) and take the deterministic
plan-following decision. Per ADR 0005 this is squarely an infrastructure failure — degrade, never
abort.

## Acceptance criteria

- [x] A provider/transport exception in the Supervisor's LLM call degrades to the deterministic
      plan-following decision instead of crashing the Session
- [x] The degrade is recorded/logged distinctly from the existing schema-fallback path, and the
      export reflects it honestly (consistent with the degraded-stop labeling convention)
- [x] Test: a fake client raising a transport error at the decision node; the Session still
      completes with deterministic decisions

## Blocked by

None — can start immediately.

## Done

- `decide_next_move` now catches a provider/transport error (an `except Exception` after the existing
  `except StructuredOutputError`) and degrades to the deterministic plan-following decision instead of
  crashing the Session — mirroring `question_node` and `study_plan_node`.
- `_deterministic_supervisor_fallback` gained a `reason_prefix` so the transport degrade is logged and
  recorded distinctly from the schema fallback; the reasoning flows through `llm_reasoning` into the
  Markdown export, so the degrade is shown honestly.
- Prompt/validator construction moved outside the guarded call so a bug there surfaces loudly rather
  than being swallowed by the backstop.

## Verified

- `uv run pytest` -> 165 passed; ruff clean. New `test_supervisor_degrades_on_transport_error_at_decision_node`
  (a fake `ConnectionError` at the decision node -> the Session still completes with the transcript
  preserved and the transport-degrade reasoning recorded).

## Status

**Closed.** Acceptance criteria are implemented and covered.
