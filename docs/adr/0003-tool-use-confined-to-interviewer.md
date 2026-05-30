# Tool-calling confined to the Interviewer; all other agents are single-shot with injected state

Only the **Interviewer** does multi-turn tool-calling (it calls RAG `lookup_concept` to craft targeted follow-ups). Every other LLM call — Evaluator, Supervisor deviation judgment, Diagnostic — runs **single-shot** with the needed context (skill states, the exchange, the topic plan) **injected directly into the prompt** rather than fetched via tools.

## Why

MiMo's `reasoning_content` 400 trap only fires on multi-turn tool calls, and the documented mitigation is to disable thinking mode for tool-using agents. But thinking mode is precisely why we chose MiMo as primary — it's what makes the Evaluator and Supervisor reason well. Confining tool-use to the one agent that genuinely needs it (the Interviewer, which doesn't need deep reasoning) lets us keep thinking mode **on** for the reasoning-heavy nodes, quarantines the MiMo quirk to a single file, and keeps "Tool Use" a clean, demonstrable pattern in one place.

A reader might be tempted to make every agent ReAct-style with its own tools ("more agentic"). That would spread the 400 trap, force thinking mode off on the reasoning nodes, and reduce reliability. This is a deliberate choice, not an oversight.
