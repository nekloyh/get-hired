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

- [ ] A provider/transport exception in the Supervisor's LLM call degrades to the deterministic
      plan-following decision instead of crashing the Session
- [ ] The degrade is recorded/logged distinctly from the existing schema-fallback path, and the
      export reflects it honestly (consistent with the degraded-stop labeling convention)
- [ ] Test: a fake client raising a transport error at the decision node; the Session still
      completes with deterministic decisions

## Blocked by

None — can start immediately.

## Status

**Open.**
