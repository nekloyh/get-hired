# Provider router + cutover rehearsal

**Type:** AFK

## What to build

The provider abstraction that makes the planned MiMo→Groq cutover a one-env-var change. Introduce an `LLMClient` ABC with `chat` and `chat_json`, a MiMo client (quarantining the `reasoning_content` thinking-mode quirk — see `ADR 0003`), a Groq client, and an `LLMRouter` that selects the primary by env var and fails over to the fallback on error. Refactor slice 0001's direct call to go through the router; no agent may import a provider client directly.

This is pulled early on purpose: MiMo free tokens expire **2026-06-03**, so the swap must be rehearsed and tested well before the deadline, not discovered on it.

## Acceptance criteria

- [x] All LLM calls go through `LLMRouter`; no direct provider imports in agent code
- [x] `PRIMARY_PROVIDER` env var switches MiMo ↔ Groq with no other code change
- [x] Router fails over to the fallback provider on a primary error
- [x] A test runs the *same* prompt through both MiMo and Groq and validates both parse into the same schema
- [x] The MiMo `reasoning_content`/thinking-mode handling lives only inside the MiMo client

## Blocked by

- 0001 (generalizes its concrete LLM call)

## Done

`LLMClient` is now an ABC with raw `chat` plus shared structured-output `chat_json` parsing/retry.
`MimoClient` and `GroqClient` are OpenAI-compatible provider clients; MiMo's
`reasoning_content` handling remains quarantined in `MimoClient`. `LLMRouter` selects
`PRIMARY_PROVIDER` (`mimo` or `groq`) and falls back to the other configured provider when the
primary chat call errors. `build_client(load_settings())` is the CLI construction path; test
fixtures also route agent calls through `LLMRouter`, so agent modules keep depending on `LLMClient`
rather than provider clients. Covered by `tests/test_llm.py`; `.env.example` documents
provider-specific credentials.

## Status

**Closed.** Acceptance criteria are implemented and covered.
