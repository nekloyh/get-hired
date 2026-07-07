# Diagnostic phase has no transport-error backstop

**Type:** AFK
**Kind:** bug

## What to build

Discovered live while validating issue 0015/0020: `_cmd_session` (`cli.py`) calls
`diagnose(profile, client)` directly, before the LangGraph Session even starts. Unlike
`question_node`, `study_plan_node`, and `decide_next_move` — all of which catch a
provider/transport error and degrade per ADR 0005 — this call site has no `try`/`except` at all.
A provider/transport failure here (timeout, rate limit, 4xx after fallback exhaustion) crashes with
a raw traceback and exit code 1 instead of degrading.

Confirmed live twice during 0015's validation:

- Once via a deliberately invalid `GROQ_MODEL` (primary 404 → expired-MiMo-fallback 401,
  uncaught).
- Once organically: a real Groq 429 (daily token limit reached) during unrelated live testing
  cascaded into the same uncaught crash, since the MiMo fallback is also expired.

`diagnostic.py` already has a deterministic offline fallback path (`diagnose(profile, None)` is
used throughout the test suite and by the CLI when no provider is configured) — the fix is to run
the live call through the same backstop pattern as the other three node call sites: catch the
provider/transport error and fall back to the deterministic Diagnostic instead of crashing, logging
the degrade distinctly (mirroring issue 0020's `reason_prefix` convention).

## Acceptance criteria

- [ ] A provider/transport exception during the CLI's Diagnostic phase degrades to the
      deterministic Topic Plan instead of crashing the process
- [ ] The degrade is logged distinctly (transport failure, not "no provider configured") and the
      Session proceeds normally from there
- [ ] Test: a fake client raising a transport error at the Diagnostic call site — the Session still
      starts and completes
- [ ] Consider whether the same gap exists in `web_api.py`'s equivalent Diagnostic call (the
      websocket `start_session` path) and fix it there too if so

## Blocked by

None — can start immediately.

## Status

**Open.**
