# Adaptive Interview Coach

A multi-agent system that runs an adaptive mock technical interview. Built primarily to **learn
agentic patterns** — see `AGENTS.md` for the authoritative design and `CONTEXT.md` for the domain
glossary.

## Status

**Slices 0004–0005 — provider router + within-question micro-loop.** LLM calls now go through an
`LLMRouter`: `PRIMARY_PROVIDER=mimo|groq` selects the primary OpenAI-compatible provider and falls
back to the other configured provider on primary call failure. The judgment path is also a loop that
owns one question end-to-end (ADR 0001): the **Interviewer** asks → the fixture **Candidate** answers
→ the **Evaluator** scores the turn and flags `follow_up_recommended` → if a **Follow-up** is flagged
and the safety cap is not hit, the Interviewer generates one targeting the gap and we repeat →
otherwise stop and keep the last score, then update the **Skill** state (slice 0002). The Evaluator's
flag is the stop logic; the cap is only a guardrail, logged distinctly when it trips.

Earlier slices: **0001** evaluate one answer → typed `Evaluation`; **0002** Beta-distributed Skill
state updated from the score (pure Python, no LLM — ADR 0002); **0003** a deterministic
`weighted_score` cross-check that lowers `confidence` on divergence. Correlations, informative priors,
RAG, and the Supervisor macro-loop are later slices.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                 # create the venv + install deps (downloads Python 3.12 if needed)
cp .env.example .env    # then fill in your MiMo/Groq credentials
```

`.env` keys: set `PRIMARY_PROVIDER=mimo` or `PRIMARY_PROVIDER=groq`, then fill that provider's
`*_API_KEY`, `*_BASE_URL`, and `*_MODEL`. If both providers are configured, the non-primary provider
is used as fallback.

## Run

```bash
uv run python -m interview_coach                          # run the micro-loop over the seed questions
uv run python -m interview_coach interview --max-turns 6  # raise the per-question safety cap
uv run python -m interview_coach evaluate --answer weak   # slices 0001–0002: evaluate one fixture answer
```

## Test

```bash
uv run pytest             # offline/unit tests only (no credentials needed)
uv run pytest -m live     # explicitly hit the real provider (needs .env configured)
```

## Layout

- `src/interview_coach/llm.py` — `LLMClient`, `MimoClient`, `GroqClient`, and `LLMRouter`: structured
  output + one self-correcting retry, primary-provider selection, fallback, and MiMo's
  `reasoning_content` handling quarantined inside `MimoClient` (ADR 0003).
- `src/interview_coach/evaluator.py` — the `Evaluation` schema + `evaluate()`, plus the slice-0003
  `weighted_score` cross-check. The Evaluator is the *only* component that judges (ADR 0001).
- `src/interview_coach/interviewer.py` — the Interviewer: `generate_follow_up()` aims one Follow-up at
  the gap the Evaluator flagged. It never scores. Single-shot for now; RAG tools land in slice 0007.
- `src/interview_coach/microloop.py` — `run_micro_loop()`: the within-question loop, the `Candidate`
  protocol + `ScriptedCandidate` fixture, and the `RESOLVED`/`SAFETY_CAP` stop reasons. Plain Python.
- `src/interview_coach/seeds.py` — the seed questions and their scripted candidate transcripts.
- `src/interview_coach/rubric.py` — the fixed 5-dimension rubric; a weight of 0 disables a dimension.
- `src/interview_coach/fixtures.py` — the slice-0001 hard-coded question + strong/weak fixture answers.
- `src/interview_coach/skill.py` — the Beta-distributed `SkillState` (`mastery`/`confidence` from
  α/β) and its pure-Python updater `apply_evaluation()`. No LLM by design (ADR 0002).
- `src/interview_coach/cli.py` — `interview` runs the micro-loop over the seed questions; `evaluate`
  runs the slices 0001–0002 demo (judgment → before→after Skill state).
