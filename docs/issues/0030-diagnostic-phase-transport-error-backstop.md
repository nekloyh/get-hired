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

- [x] A provider/transport exception during the CLI's Diagnostic phase degrades to the
      deterministic Topic Plan instead of crashing the process
- [x] The degrade is logged distinctly (transport failure, not "no provider configured") and the
      Session proceeds normally from there
- [x] Test: a fake client raising a transport error at the Diagnostic call site — the Session still
      starts and completes
- [x] Consider whether the same gap exists in `web_api.py`'s equivalent Diagnostic call (the
      websocket `start_session` path) and fix it there too if so

## Blocked by

None — can start immediately.

## Done

- Added `diagnose_or_degrade()` in `diagnostic.py`: the ADR 0005 runtime backstop for the
  pre-graph Diagnostic call. It runs `diagnose(profile, client)` and, on any provider/transport
  failure (or a schema-invalid plan after retry), logs the degrade distinctly and falls back to the
  deterministic Topic Plan (`diagnose(profile, None)`). `diagnose()` itself stays strict — benches
  and tests that want the raw error keep calling it directly (see
  `test_diagnose_propagates_llm_failure_without_deterministic_fallback`). A genuine bug in the pure
  prep helpers still surfaces: it re-raises on the deterministic retry, which is not caught.
- Wired all three runtime entry points through the backstop: the two CLI commands (`_cmd_session`,
  `_cmd_diagnose`) and the web `_run_session_thread` (`web_api.py`). The web path already had an
  outer `except Exception` that converted failures to a `session_error` event, so it never crashed
  the *process* — but a Diagnostic transport error still aborted the whole session with an error
  instead of degrading. Routing it through `diagnose_or_degrade` makes the web Diagnostic degrade
  and continue, consistent with how the graph nodes already degrade on the web path (ADR 0005).

## Verified

- `tests/test_diagnostic.py`: provider-error degrade, healthy-provider passthrough, and offline
  equivalence to plain `diagnose`.
- `tests/test_cli.py`: the `spy_diagnose` wiring tests confirm the CLI commands route through the
  backstop with the correct client selection.
- `uv run pytest -q` — 214 passed; `uv run ruff check` clean.

## Status

**Closed.** Acceptance criteria are implemented and covered.
