# Adaptive Interview Coach

A multi-agent system that runs an adaptive mock technical interview. Built primarily to **learn
agentic patterns** — see `AGENTS.md` for the authoritative design and `CONTEXT.md` for the domain
glossary.

## Status

**Slices 0010–0012 — persisted Sessions, Study Planner, CLI UI, and Evaluator harness.** `coach
session` runs/resumes a multi-question interactive Session through LangGraph + `SqliteSaver`,
prompts the Candidate in the terminal, streams live Skill-state bars after each resolved question,
then produces a Study Plan from final Skill states and retrieved resource candidates. `--scripted`
runs the built-in fixture Candidate for demos/tests. `--export-markdown` writes the full Session
transcript, evaluations, Supervisor decisions, and Study Plan as a portfolio artifact. `coach
eval-harness` runs held-out golden answers through the Evaluator and exits non-zero when score ranges
regress.

Earlier slices: **0006–0009** added Self-critique, RAG Follow-ups, and Diagnostic priors.
Low-confidence Evaluator judgments get exactly one Self-critique pass. The Interviewer is the only
tool-using agent: Follow-up generation first calls `lookup_concept`, then asks a grounded question
using the retrieved note, with MiMo thinking disabled for that tool loop. The concept store can run
in-memory for tests/demos or against a Chroma `concepts` collection using `BAAI/bge-small-en-v1.5`.
The Diagnostic reads the Candidate profile and produces a Topic Plan plus weak Beta priors with
prior-only correlations and Role criticality metadata. The single-shot LLM agent is the primary
Topic Plan path whenever a provider is configured; a deterministic ordering is the offline fallback.
`DiagnosticResult.topic_plan_source` records which path ran (`llm` | `deterministic`).

Earlier slices: **0004–0005** added the provider router + within-question micro-loop. LLM calls go
through an
`LLMRouter`: `PRIMARY_PROVIDER=mimo|groq` selects the primary OpenAI-compatible provider and falls
back to the other configured provider on primary call failure. The judgment path is also a loop that
owns one question end-to-end (ADR 0001): the **Interviewer** asks → the fixture **Candidate** answers
→ the **Evaluator** scores the turn and flags `follow_up_recommended` → if a **Follow-up** is flagged
and the safety cap is not hit, the Interviewer generates one targeting the gap and we repeat →
otherwise stop and keep the last score, then update the **Skill** state (slice 0002). The Evaluator's
flag is the stop logic; the cap is only a guardrail, logged distinctly when it trips.

Earlier slices: **0001** evaluate one answer → typed `Evaluation`; **0002** Beta-distributed Skill
state updated from the score (pure Python, no LLM — ADR 0002); **0003** a deterministic
`weighted_score` cross-check that lowers `confidence` on divergence. The Supervisor macro-loop is the
next major orchestration slice.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                 # create the venv + install deps (downloads Python 3.12 if needed)
uv sync --extra rag     # optional: install Chroma + sentence-transformers for persistent RAG
cp .env.example .env    # then fill in your MiMo/Groq credentials
```

`.env` keys: set `PRIMARY_PROVIDER=mimo` or `PRIMARY_PROVIDER=groq`, then fill that provider's
`*_API_KEY`, `*_BASE_URL`, and `*_MODEL`. If both providers are configured, the non-primary provider
is used as fallback.

## Run

```bash
uv run python -m interview_coach                          # run the micro-loop over the seed questions
uv run python -m interview_coach interview --max-turns 6  # raise the per-question safety cap
uv run python -m interview_coach interview --concept-store chroma --concept-persist-dir .chroma
uv run python -m interview_coach evaluate --answer weak   # slices 0001–0002: evaluate one fixture answer
uv run python -m interview_coach diagnose --target-role "machine learning engineer" --claim mlops=4             # LLM agent when configured, else deterministic
uv run python -m interview_coach diagnose --offline --target-role "machine learning engineer" --claim mlops=4   # force the deterministic offline path
uv run python -m interview_coach session --max-questions 3 --export-markdown exports/session.md                 # interactive Candidate answers
uv run python -m interview_coach session --scripted --max-questions 3                                           # deterministic demo Candidate
uv run python -m interview_coach eval-harness        # issue 0012: golden-answer Evaluator harness
uv run python -m interview_coach ingest-concepts --persist-dir .chroma
uv run python -m interview_coach ingest-resources --persist-dir .chroma
uv run python scripts/smoke_issue_0007.py
uv run python scripts/smoke_issue_0009.py   # live: validate the Diagnostic agent against the real provider
```

## Test

```bash
uv run pytest             # offline/unit tests only (no credentials needed)
uv run pytest -m live     # explicitly hit the real provider (needs .env configured)
uv sync --extra rag && uv run pytest -m rag  # optional Chroma/BGE integration
```

## Layout

- `src/interview_coach/llm.py` — `LLMClient`, `MimoClient`, `GroqClient`, and `LLMRouter`: structured
  output + one self-correcting retry, primary-provider selection, fallback, and MiMo's
  `reasoning_content` handling quarantined inside `MimoClient` (ADR 0003).
- `src/interview_coach/evaluator.py` — the `Evaluation` schema + `evaluate()`, plus the slice-0003
  `weighted_score` cross-check and slice-0006 Self-critique. The Evaluator is the *only* component
  that judges (ADR 0001).
- `src/interview_coach/interviewer.py` — the Interviewer: `generate_follow_up()` aims one Follow-up at
  the gap the Evaluator flagged using the `lookup_concept` tool. It never scores.
- `src/interview_coach/concepts.py` — seed concept notes, the `lookup_concept` tool interface,
  deterministic in-memory retrieval for tests, and the Chroma/BGE persistent store.
- `src/interview_coach/resources.py` — seed learning resources, deterministic in-memory retrieval,
  and the Chroma/BGE `resources` collection used by the Study Planner.
- `src/interview_coach/study_planner.py` — end-of-Session Study Planner: ranks weak/role-critical
  Skills, retrieves resource candidates, and produces a typed two-week `StudyPlan`.
- `src/interview_coach/eval_harness.py` — golden-answer Evaluator harness with expected score ranges,
  including an adversarial prompt-injection case.
- `src/interview_coach/ui.py` — terminal Skill-state rendering helpers used by the Session CLI.
- `src/interview_coach/exporter.py` — Markdown export of the full Session transcript, evaluations,
  Supervisor decisions, and Study Plan.
- `src/interview_coach/diagnostic.py` — Candidate profile → Topic Plan + weak seeded Skill priors
  with Role criticality and prior-only correlations.
- `src/interview_coach/microloop.py` — `run_micro_loop()`: the within-question loop, the `Candidate`
  protocol, `InteractiveCandidate`, `ScriptedCandidate`, and the `RESOLVED`/`SAFETY_CAP` stop
  reasons. Plain Python.
- `src/interview_coach/seeds.py` — the seed questions and their scripted candidate transcripts.
- `src/interview_coach/rubric.py` — the fixed 5-dimension rubric; a weight of 0 disables a dimension.
- `src/interview_coach/fixtures.py` — the slice-0001 hard-coded question + strong/weak fixture answers.
- `src/interview_coach/skill.py` — the Beta-distributed `SkillState` (`mastery`/`confidence` from
  α/β) and its pure-Python updater `apply_evaluation()`. No LLM by design (ADR 0002).
- `src/interview_coach/cli.py` — `interview` runs the micro-loop over the seed questions; `evaluate`
  runs the slices 0001–0002 demo (judgment → before→after Skill state); `session` is the live
  terminal UI; `eval-harness` runs the Evaluator regression checks.
