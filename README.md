# Adaptive Interview Coach

A multi-agent system that runs an adaptive mock technical interview. Built primarily to **learn
agentic patterns** — see `CLAUDE.md` for the authoritative design and `CONTEXT.md` for the domain
glossary.

Development sequencing and acceptance gates live in **[the implementation plan](docs/issues/README.md)**.
It links the existing slices and separates personal/trusted-pilot milestones from public-launch requirements.
**[The roadmap](docs/roadmap.md)** says what to do next and why in that order.

## Quickstart (live) — clone to a real interview

You need [uv](https://docs.astral.sh/uv/), Node 18+, and **one OpenAI API key**. Nothing else: no
Chroma, no second provider, no Docker.

**How long this takes**, measured on a clean clone on 2026-09-15 (R-04 / #59). Two numbers, because
only one of them is ours to control:

| | wall time | what it covers |
|---|---:|---|
| **Repo-controlled** — toolchain caches already warm | **8 s** | clone → `uv sync` → `npm install` → backend answering → a completed interview |
| **Cold total** — nothing cached, everything downloaded | **38 s** | the above plus ~275 MB: a managed Python (103 MB, 4 s), the Python wheels (171 MB, 24 s) and `node_modules` (41 MB, 5 s) |

Add however long it takes you to paste an API key. The cold number is **network-bound**, so it is
the one that moves: it was measured on fast broadband, and on a slow link the three downloads
dominate everything else the project does. The repo-controlled 8 s is what changes when this
repository changes, and is the number to watch in review.

**1. Clone and install** (~30 s cold, ~3 s warm)

```bash
git clone https://github.com/nekloyh/get-hired.git && cd get-hired
uv sync                      # venv + Python deps (downloads Python 3.12 if needed)
cd web && npm install && cd ..
```

**2. Configure one key**

```bash
cp .env.example .env
```

Edit `.env` and set just these two lines — everything else can stay commented out:

```dotenv
PRIMARY_PROVIDER=openai
OPENAI_API_KEY=sk-...your key...
```

`OPENAI_MODEL` already defaults to `gpt-5.4-mini`, the judge this project validates against
(see [Judge calibration gate](#judge-calibration-gate-issue-0022--adr-0009)). MiMo is retired and
Groq does **not** pass the judge bench — leave both commented out.

**3. Start the backend**

```bash
uv run coach api --port 8000
```

Check it: `curl -s localhost:8000/api/health` should report `"primary_configured": true`.

**4. Start the UI** (in a second terminal)

```bash
cd web && npm run dev
```

**5. Run a one-question live interview**

Open `http://127.0.0.1:5173`, set **Mode** to `live` and **Max questions** to `1`, then press
**Start**. Answer in your own words and press **Send**.

Expect a **follow-up**: "max questions" caps interview *questions*, not turns, so a single question
can probe further before it resolves — that is the micro-loop doing its job, not a stuck UI. Answer
the follow-up too. You then land on a Final Report with a readiness estimate, per-skill bars, and a
Markdown export button.

> Prefer the terminal? `uv run coach session --max-questions 1` does the same thing without the UI.
> No API key at all? Set **Mode** to `demo` — the whole flow runs on a deterministic fake model.

### If something goes wrong

| Symptom | Cause |
| --- | --- |
| `"primary_configured": false` | `.env` is missing `OPENAI_API_KEY`, or `PRIMARY_PROVIDER` is not `openai`. |
| UI loads but `live` mode errors instantly | The backend cannot reach the provider — check the `coach api` terminal for the `llm-call ... outcome=error:` line, which names the real failure. |
| `insufficient_quota` | The day's OpenAI allowance is spent. `uv run coach usage` shows what this repo has recorded today. |
| Browser cannot reach the API | The UI expects `http://127.0.0.1:8000`; override with `VITE_API_URL` if you moved it. |

### Exposing it beyond localhost

For an actual deployment — Docker image, compose stack with TLS and `wss://`, and the single-VPS
runbook — see **[`docs/deploy.md`](docs/deploy.md)**. `docker compose up -d --build` is the whole
thing once `.env` is filled in. The rest of this section is the configuration that matters wherever
you run it.

The API ships **open** — no auth — because that is the right default for `localhost`, and the wrong
one anywhere else (`coach api` warns about this on startup). Before putting it on a network:

```dotenv
COACH_AUTH_TOKEN=<openssl rand -hex 32>           # ASCII only — the server refuses to start otherwise
COACH_ALLOWED_ORIGINS=https://your-ui-host        # comma-separated; set it, or your UI is rejected
```

With a token set, the transcript export requires `Authorization: Bearer <token>` and the Session
WebSocket must present the token in its first frame from an allowlisted `Origin`. The UI **prompts
for the token at runtime** and keeps it in `sessionStorage`; there is deliberately no build-time
`VITE_*` token, because Vite inlines those into `assets/index-*.js` — a secret shipped inside the
app it is meant to gate is readable by anyone who can fetch the app. This is a single shared secret
sized for a handful of trusted users; per-user accounts are tracked separately (R-29).

Without a token the API is open to whatever can reach the port, but browser sockets are still
restricted to `localhost`/`127.0.0.1` origins. That matters even for a purely local setup: the
same-origin policy does not apply to WebSockets, so any page you visit could otherwise open a socket
to your own backend and run interviews on your API key.

Your Session id is generated per browser and stored in `localStorage`, so a reload can resume an
interview in progress. It is read-only in the UI; use **New session** to start a fresh one.

## Status

**`v0.2.0` (2026-09-20).** M-0 and M-1 of the [implementation plan](docs/issues/README.md) are
complete: the Session is bounded, its spend is accounted for, and the stack deploys behind nginx/TLS.
The whole path has been driven through a real compose stack — HTTP→HTTPS, `wss://` through the proxy,
a restart mid-question, a teardown and restore — and what that run found is in
[`MILESTONE-REPORT.md`](MILESTONE-REPORT.md) §5.

`v0.2.0` adds no feature. It removes dead code, splits the two 1,400-line modules, and makes the
replay bench measure the pack it was actually recorded against; it also **removes public CLI
surface**, which is why the minor version moved. [`CHANGELOG.md`](CHANGELOG.md) has the list, including
what is still red.

**Before anyone but you uses it, work through [`docs/pilot-runbook.md`](docs/pilot-runbook.md).** It
is a pre-flight gate, and one of its lines is a Groq key rotation that only you can tick.

### What runs today

A Session is a Diagnostic (profile → Topic Plan + weak Beta priors), then a Supervisor macro-loop
executing that plan over LangGraph with SQLite checkpoints, then a micro-loop per question:
Interviewer asks → Candidate answers → Evaluator scores and flags a Follow-up → the Interviewer aims
one at the gap using the `lookup_concept` tool → repeat until the Evaluator stops or the cap trips.
The Evaluator is the only component that judges (ADR 0001). When its own deterministic triggers say a
score is shaky, the judgment escalates to a Skeptic/Advocate **Panel** and the Evaluator re-decides
having read both; committee disagreement, not judge confidence, becomes the evidence weight. Skill
state is a decayed Beta posterior per Skill (ADR 0002, ADR 0006), never a running average. A Session
ends with a two-week Study Plan and a Markdown export of the whole thing.

EN/VN/mixed is first-class (ADR 0007): the mode is Session state, a deterministic detector — never
the judge — decides when English delivery is scored, and that dimension stays out of `weighted_score`
so the skill posterior is technical-only.

Interfaces: `coach session` in the terminal, `coach api` + a Vite/React app in the browser, and a
Docker image with an nginx/TLS compose stack.

### What is not true yet

| | |
|---|---|
| The judge calibration gate is **red at 34/35** | a known EN/VN split on two dimensions with a gap in their 1–5 scale ([#96](https://github.com/nekloyh/get-hired/issues/96)). Scores are for practice, not for comparing people |
| One shared token, no accounts | anyone with it can read or overwrite anyone's Skill history by typing their Candidate id ([#84](https://github.com/nekloyh/get-hired/issues/84)) |
| Resume is per **question**, not per turn | a crash costs the question in flight, not the interview |
| The Skill ledger keeps one snapshot per Candidate | there is no history to chart yet ([#127](https://github.com/nekloyh/get-hired/issues/127)) |
| Self-critique is dormant | its low-confidence trigger never fires on the current judge; the Panel above is what replaced it. The leftover `SelfCritiqueTrace` type was deleted in `v0.2.0` ([#129](https://github.com/nekloyh/get-hired/issues/129)), so the dormancy is now the only part left — a replacement signal is ADR 0011, still Proposed |

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                 # create the venv + install deps (downloads Python 3.12 if needed)
uv sync --extra rag     # optional: install Chroma + sentence-transformers for persistent RAG
cp .env.example .env    # then set PRIMARY_PROVIDER=openai and OPENAI_API_KEY (see Quickstart)
cd web && npm install   # install the React UI toolchain
```

`.env` keys: set `PRIMARY_PROVIDER` to `openai`, `groq`, or `zenmux`, then fill that provider's
`*_API_KEY` and `*_MODEL` (plus `*_BASE_URL` for zenmux). Any other configured provider is used as
fallback. **The validated judge is `openai` / `gpt-5.4-mini`** — the configuration that passes
`coach bench` 20/20 (issue 0031) and runs inside OpenAI's free daily tier; `gpt-4o-mini` and Groq
`llama-3.3-70b` each leave one borderline Vietnamese case out of band (a small-model capability limit).

## Run

```bash
uv run python -m interview_coach                          # prints the subcommand help and exits 2
uv run python -m interview_coach diagnose --target-role "machine learning engineer" --claim mlops=4             # LLM agent when configured, else deterministic
uv run python -m interview_coach diagnose --offline --target-role "machine learning engineer" --claim mlops=4   # force the deterministic offline path
uv run python -m interview_coach session --max-questions 3 --export-markdown exports/session.md                 # interactive Candidate answers
uv run python -m interview_coach session --scripted --max-questions 3                                           # deterministic demo Candidate
uv run python -m interview_coach session --candidate alice --max-questions 3                                    # 0023: remember a returning Candidate across Sessions
uv run python -m interview_coach pack lint data/packs/fpt                                                       # 0025: validate a content pack (fail-loud)
uv run python -m interview_coach session --pack data/packs/fpt --scripted --max-questions 3                     # 0025: run a Session from a pack
uv run python -m interview_coach eval-harness        # issue 0012: golden-answer Evaluator harness
uv run python -m interview_coach ingest-concepts --persist-dir .chroma
uv run python scripts/smoke_issue_0009.py   # live: validate the Diagnostic agent against the real provider
```

Web MVP:

```bash
uv run coach api --port 8000
cd web && npm run dev
```

Then open `http://127.0.0.1:5173`. Choose `demo` mode to run without credentials; choose `live` once
`.env` has the selected provider configured. See [Quickstart](#quickstart-live--clone-to-a-real-interview)
for the first-run walkthrough and for the auth settings needed before exposing this beyond localhost.

## Content packs (issue 0025 / ADR 0008)

Interview content is external data, not code. A **pack** is a directory validated by a fail-loud
contract (`coach pack lint <dir>`); the built-in `src/interview_coach/data/` bank is the reference
pack, and `data/packs/fpt/` ships as a first FPT-style pack. A pack directory holds:

- `questions.yaml` — top-level mapping `Skill -> [questions]`. Each question:
  `question` (unique prompt), `difficulty` (1–5; the Topic Plan's `target_difficulty` selects the
  closest match — optional, defaults to 3), `rubric.weights` (over the 5 technical dimensions;
  `english_delivery` is Session-injected per answer, never authored in a pack),
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

Current status: the bench is **green (29/29)** after the gpt-5.4-mini re-anchor — latest report
`docs/audits/calibration-bench-2026-07-11-reanchor.md`. All six dimensions now carry scored guide
bands; residual biases are small (communication −0.10, depth −0.31). Known model behavior:
confidence is saturated (~0.95 uniform), so panel escalation never fires naturally — a deliberate,
documented non-change (the forced-escalation experiment showed the verdict never moves).

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
./scripts/gate.sh         # everything CI runs, one verdict per line, one GATE: OK at the end
./scripts/gate.sh --all   # ...plus the image build, compose validation and the browser specs
```

Or one at a time:

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

- `src/interview_coach/llm.py` — `LLMClient`, `OpenAIClient`, `GroqClient`, `ZenMuxClient`, and
  `LLMRouter`: structured output + one self-correcting retry, primary-provider selection, and typed
  failover with a per-provider circuit breaker.
- `src/interview_coach/evaluator.py` — the `Evaluation` schema + `evaluate()`, plus the slice-0003
  `weighted_score` cross-check and the deterministic triggers that escalate a shaky judgment to the
  Panel. The Evaluator is the *only* component that judges (ADR 0001).
- `src/interview_coach/interviewer.py` — the Interviewer: `generate_follow_up()` aims one Follow-up at
  the gap the Evaluator flagged using the `lookup_concept` tool. It never scores.
- `src/interview_coach/concepts.py` — seed concept notes, the `lookup_concept` tool interface,
  deterministic in-memory retrieval for tests, and the Chroma/BGE persistent store.
- `src/interview_coach/resources.py` — the seed learning-resource catalog and the deterministic
  in-memory retrieval the Study Planner uses. One store by design (#130): the catalog is two entries
  per Skill behind a hard `skill=` filter, which no embedder can rank better.
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
- `src/interview_coach/cli.py` — `session` is the live terminal UI; `api` runs the web backend;
  `eval-harness` runs the Evaluator regression checks.
- `web/` — Vite React + TypeScript local UI with typed WebSocket events, setup controls, interview
  workspace, live Skill/Topic Plan sidebars, final report, unit tests, and a Playwright demo-flow spec.
