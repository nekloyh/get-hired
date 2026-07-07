# Adaptive Interview Coach

A multi-agent system that runs an adaptive mock technical interview. Built primarily to **learn
agentic patterns** — see `AGENTS.md` for the authoritative design and `CONTEXT.md` for the domain
glossary.

## Status

**Slices 0010–0012 — persisted Sessions, Study Planner, React UI/API, and Evaluator harness.**
`coach session` still runs/resumes a multi-question interactive Session through LangGraph +
`SqliteSaver` in the terminal. The local web MVP is now a Vite React + TypeScript app backed by
`coach api`, a thin FastAPI/WebSocket layer over the same Python Session graph. The backend uses live
LLMs when configured and has an explicit demo-only deterministic client for UI review without
credentials. `--scripted` runs the built-in fixture Candidate for demos/tests. `--export-markdown`
writes the full Session transcript, evaluations, Supervisor decisions, and Study Plan as a portfolio
artifact; the web API also exposes completed Session Markdown at `/api/sessions/{session_id}/export.md`.
`coach eval-harness` runs held-out golden answers through the Evaluator and exits non-zero when score
ranges regress.

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
cd web && npm install   # install the React UI toolchain
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
uv run python -m interview_coach session --candidate alice --max-questions 3                                    # 0023: remember a returning Candidate across Sessions
uv run python -m interview_coach pack lint data/packs/fpt                                                       # 0025: validate a content pack (fail-loud)
uv run python -m interview_coach session --pack data/packs/fpt --scripted --max-questions 3                     # 0025: run a Session from a pack
uv run python -m interview_coach eval-harness        # issue 0012: golden-answer Evaluator harness
uv run python -m interview_coach ingest-concepts --persist-dir .chroma
uv run python -m interview_coach ingest-resources --persist-dir .chroma
uv run python scripts/smoke_issue_0007.py
uv run python scripts/smoke_issue_0009.py   # live: validate the Diagnostic agent against the real provider
```

Web MVP:

```bash
uv run coach api --port 8000
cd web && npm run dev
```

Then open `http://127.0.0.1:5173`. Choose `demo` mode to run without credentials; choose `live` once
`.env` has the selected provider configured.

## Content packs (issue 0025 / ADR 0008)

Interview content is external data, not code. A **pack** is a directory validated by a fail-loud
contract (`coach pack lint <dir>`); the built-in `src/interview_coach/data/` bank is the reference
pack, and `data/packs/fpt/` ships as a first FPT-style pack. A pack directory holds:

- `questions.yaml` — top-level mapping `Skill -> [questions]`. Each question:
  `question` (unique prompt), `difficulty` (1–5; the Topic Plan's `target_difficulty` selects the
  closest match — optional, defaults to 3), `rubric.weights` (over the 5 fixed dimensions),
  `answers` (scripted fixture replies; `answers[0]` answers the question, `answers[1:]` the
  follow-ups), `expected_concepts` (must resolve to a concept id), and `follow_up_seeds`.
- `concepts.yaml` — a list of concept notes (`id`, `skill`, `title`, `content`, optional `language`,
  `tags`). Every canonical Skill needs at least one note, and every question's `expected_concepts`
  must reference a note that exists.
- `pack.yaml` — metadata (`name` required; e.g. `role`, `company_style`, `description`).

`coach pack lint` dies with a named violation on anything malformed (unknown Skill, dangling concept
reference, bad difficulty, missing name) and exits non-zero, so a broken pack fails at lint time,
never mid-interview. `coach session --pack <dir>` then runs the whole Session from that pack.

## Judge calibration gate (issue 0022 / ADR 0009)

The Evaluator is the single judge everything downstream trusts, so **every judge change — its prompt,
self-critique thresholds, structured-output path, or the provider/model behind it (a provider swap is
a judge change) — must pass `coach bench` before it merges.**

```bash
uv run coach bench                                  # run the bilingual calibration bench live
uv run coach bench --out docs/audits/bench-x.md     # choose the report path
```

`coach bench` runs the hand-labelled EN/VN paired golden set (`data/bench/cases.yaml`) against the
configured provider and writes a Markdown report to `docs/audits/`: per-dimension bias vs the human
labels, weak/strong separation, EN-vs-VN paired deltas, and a confidence-calibration table ("when it
says 0.9, is it right ~90% of the time?"). It exits non-zero on any range regression, so it gates a
judge change the same way a failing test would. Reports are versioned in `docs/audits/` so judge
quality has a history, not a vibe.

The bench's companion is the **Simulated Candidate + Supervisor replay bench** (issue 0029,
`interview_coach.replay`): where `coach bench` calibrates the *judge*, the replay bench calibrates the
*loop*. A `Persona` with a ground-truth mastery profile drives a full unattended Session through the
existing Candidate seam (`run_persona_session`), and the run asserts trajectory properties — the final
posterior mastery ordering recovers the persona's ground truth, and the Supervisor does not burn budget
on a Skill the persona is strong at. The trajectory is dumped as a versioned replay artifact so
`replay_decision` can re-run the Supervisor's decision node over it with a different model — the seed of
decision-level regression testing. Together they are the two halves of the eval stack.

## Test

```bash
uv run pytest             # offline/unit tests only (no credentials needed)
uv run pytest -m live     # explicitly hit the real provider (needs .env configured)
uv sync --extra rag && uv run pytest -m rag  # optional Chroma/BGE integration
cd web && npm run lint
cd web && npm run test
cd web && npm run build
cd web && npm run test:e2e  # optional: requires the backend API running and Playwright browsers installed
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
- `src/interview_coach/web_api.py` — FastAPI health, WebSocket Session, and Markdown export endpoints
  for the React UI.
- `src/interview_coach/demo_llm.py` — demo-only deterministic `LLMClient` for local UI review without
  provider credentials; it is deliberately separate from production provider routing.
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
  terminal UI; `api` runs the web backend; `eval-harness` runs the Evaluator regression checks.
- `web/` — Vite React + TypeScript local UI with typed WebSocket events, setup controls, interview
  workspace, live Skill/Topic Plan sidebars, final report, unit tests, and a Playwright demo-flow spec.
