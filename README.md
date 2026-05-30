# Adaptive Interview Coach

A multi-agent system that runs an adaptive mock technical interview. Built primarily to **learn
agentic patterns** — see `AGENTS.md` for the authoritative design and `CONTEXT.md` for the domain
glossary.

## Status

**Slice 0002 — skill-state update.** The judgment path now feeds a belief: a hard-coded question
plus a fixture answer → the **Evaluator** (a single structured LLM call) → a typed `Evaluation` → a
Beta-distributed **Skill** state updated from the score (pure Python, no LLM — ADR 0002). Each answer
shifts mastery toward its score and shrinks the variance, so confidence rises. No micro-loop,
correlations, informative priors, or RAG yet — those are later slices.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                 # create the venv + install deps (downloads Python 3.12 if needed)
cp .env.example .env    # then fill in your MiMo (OpenAI-compatible) credentials
```

`.env` keys: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`. MiMo is primary; a Groq cutover is planned
for 2026-06-03 (see `docs/issues/0004`).

## Run

```bash
uv run python -m interview_coach                 # evaluate both fixture answers
uv run python -m interview_coach --answer weak   # just the weak one
```

## Test

```bash
uv run pytest             # offline/unit tests only (no credentials needed)
uv run pytest -m live     # explicitly hit the real provider (needs .env configured)
```

## Layout

- `src/interview_coach/llm.py` — `MimoClient.chat_json`: structured output + one self-correcting
  retry; quarantines MiMo's `reasoning_content` thinking-mode quirk (ADR 0003). Issue 0004
  generalizes this into the multi-provider `LLMRouter`.
- `src/interview_coach/evaluator.py` — the `Evaluation` schema + `evaluate()`. The Evaluator is the
  *only* component that judges (ADR 0001).
- `src/interview_coach/rubric.py` — the fixed 5-dimension rubric; a weight of 0 disables a dimension.
- `src/interview_coach/fixtures.py` — the hard-coded question + strong/weak fixture answers.
- `src/interview_coach/skill.py` — the Beta-distributed `SkillState` (`mastery`/`confidence` from
  α/β) and its pure-Python updater `apply_evaluation()`. No LLM by design (ADR 0002).
- `src/interview_coach/cli.py` — runs the slice: prints the judgment, then the before→after Skill
  state showing how mastery and confidence moved.
