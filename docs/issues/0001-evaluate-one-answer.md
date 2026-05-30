# Evaluate one answer

**Type:** AFK

## What to build

The thinnest end-to-end judgment path: take one hard-coded question and a fixture Candidate answer, call the **Evaluator** (a single LLM call via structured-output `chat_json`), and print a typed evaluation. The rubric uses the fixed 5-dimension vocabulary (correctness, depth, communication, system_thinking, mlops_awareness) with per-question weights, where weight 0 disables a dimension. The Evaluator emits per-dimension scores (1–5) with verbatim evidence, an LLM-emitted `weighted_score`, a `confidence`, and `follow_up_recommended`. No skill-state, no loop, no RAG yet — just answer in, structured judgment out.

The `follow_up_recommended` flag is the Evaluator's own judgment framed around *marginal information gain* ("would a follow-up likely reveal something not already known?"), not a score threshold.

## Acceptance criteria

- [ ] Running the slice on a fixture Q+answer prints a valid, schema-validated evaluation object
- [ ] Per-dimension scores carry verbatim evidence quotes from the answer (or an explicit "no evidence")
- [ ] Dimensions with weight 0 are not scored
- [ ] A clearly weak answer yields low scores; a strong fixture answer yields high scores
- [ ] Structured-output parsing retries once on validation failure before erroring

## Blocked by

None - can start immediately.
