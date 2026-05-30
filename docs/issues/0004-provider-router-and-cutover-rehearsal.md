# Provider router + cutover rehearsal

**Type:** AFK

## What to build

The provider abstraction that makes the planned MiMo→Groq cutover a one-env-var change. Introduce an `LLMClient` ABC with `chat` and `chat_json`, a MiMo client (quarantining the `reasoning_content` thinking-mode quirk — see `ADR 0003`), a Groq client, and an `LLMRouter` that selects the primary by env var and fails over to the fallback on error. Refactor slice 0001's direct call to go through the router; no agent may import a provider client directly.

This is pulled early on purpose: MiMo free tokens expire **2026-06-03**, so the swap must be rehearsed and tested well before the deadline, not discovered on it.

## Acceptance criteria

- [ ] All LLM calls go through `LLMRouter`; no direct provider imports in agent code
- [ ] `PRIMARY_PROVIDER` env var switches MiMo ↔ Groq with no other code change
- [ ] Router fails over to the fallback provider on a primary error
- [ ] A test runs the *same* prompt through both MiMo and Groq and validates both parse into the same schema
- [ ] The MiMo `reasoning_content`/thinking-mode handling lives only inside the MiMo client

## Blocked by

- 0001 (generalizes its concrete LLM call)
