# Tool-calling confined to the Interviewer; all other agents are single-shot with injected state

Only the **Interviewer** does multi-turn tool-calling (it calls RAG `lookup_concept` to craft targeted follow-ups). Every other LLM call — Evaluator, Supervisor deviation judgment, Diagnostic — runs **single-shot** with the needed context (skill states, the exchange, the topic plan) **injected directly into the prompt** rather than fetched via tools.

## Why

MiMo's `reasoning_content` 400 trap only fires on multi-turn tool calls, and the documented mitigation is to disable thinking mode for tool-using agents. But thinking mode is precisely why we chose MiMo as primary — it's what makes the Evaluator and Supervisor reason well. Confining tool-use to the one agent that genuinely needs it (the Interviewer, which doesn't need deep reasoning) lets us keep thinking mode **on** for the reasoning-heavy nodes, quarantines the MiMo quirk to a single file, and keeps "Tool Use" a clean, demonstrable pattern in one place.

A reader might be tempted to make every agent ReAct-style with its own tools ("more agentic"). That would spread the 400 trap, force thinking mode off on the reasoning nodes, and reduce reliability. This is a deliberate choice, not an oversight.

## Addendum (slice 0007): native tool-calling, not JSON emulation

The Interviewer now uses **provider-level function-calling**: the model emits real OpenAI-compatible `tool_calls`, Python executes `lookup_concept`, and the result is fed back as a `tool` turn before the model writes the (still schema-validated) Follow-up. This replaces the earlier two-turn JSON emulation. Native tool-calling is enabled on **both** providers (`_supports_tools = True` on MiMo and Groq); thinking mode stays disabled for this loop and `reasoning_content` is never replayed into the multi-turn tool history, which is the mitigation this ADR requires.

A JSON tool-plan path still exists but is **only** for non-native clients (offline fakes/dummies). A native provider that declines or fails the forced tool call **fails loudly** rather than silently degrading — `LLMRouter.chat_with_tools` propagates `ToolCallingUnsupported` instead of failing over, so a tool-call integration problem is surfaced, not hidden behind the other provider. Only transport-level errors trigger failover.

## Addendum (resilience): a third category — transient malformed tool calls

The "fail loudly" rule above is about two categories: a genuine capability/integration failure (`ToolCallingUnsupported`, stays loud) and a transport error (fails over). Experience surfaced a **third** category the original wording lumped into "crash": MiMo occasionally emits a **garbled/misspelled tool name** in an otherwise well-formed `tool_calls` turn. That is not an integration failure (the provider *can* do tool-calling) and not a transport error — it is a transient malformed output. Previously it raised a plain `ValueError` from the Interviewer's tool executor, which propagated uncaught through the micro-loop and the LangGraph macro-loop and **killed the whole Session**.

Decision: distinguish it explicitly and **recover** without weakening the loud-failure guarantee.

- The executor raises a typed `UnknownToolCall` for an unexpected tool name.
- `_generate_follow_up_native` **retries the tool round-trip once** (the glitch is transient; a re-run usually succeeds).
- If it persists past the retry, the Interviewer raises `FollowUpUnavailable` — deliberately **not** a subclass of `ToolCallingUnsupported`. A Follow-up is an optional "go deeper" step and the turn already has a valid Evaluator score, so `run_micro_loop` catches it and resolves the question with the last score under a distinct `StopReason.FOLLOW_UP_UNAVAILABLE` (a degrade, logged as a warning, never a normal resolution).

`ToolCallingUnsupported` (the model returning *no* tool call for a forced request) is untouched and still fails loudly: a real "this provider can't do native tool-calling" problem must not be hidden behind a degrade. This addendum only rescues the transient-glitch case the loud-failure rule never meant to cover.

The same resilience principle applies to the end-of-Session Study Planner (`study_plan` node): it is optional end-matter produced *after* a fully-resolved interview, so a planner failure degrades to "no plan" (`study_plan=None` plus a `study_plan_error` marker) and the Session still completes, rather than discarding a finished interview at the final node.
