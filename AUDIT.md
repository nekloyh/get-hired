# Forensic audit — `personal-interviewer` (Adaptive Interview Coach)

Audited: working tree at `2dac711` (HEAD, committed 2026-08-04) **plus 21 uncommitted modified files and 4 untracked paths** (the "M0a usage ledger" work; `git diff --stat HEAD`: 21 files, +1,149/−77). Every `file:line` below refers to the working tree, not HEAD. Audit date 2026-09-14. Read-only: nothing in the repo was modified; this file is the only write.

**Read fully:** all 33 modules under `src/interview_coach/`, every build/deploy/CI/config file, `README.md`, `CONTEXT.md`, `docs/deploy.md`, `docs/issues/README.md`, the `## Status` line of every `docs/issues/00NN-*.md`, all of `web/src` and `web/e2e`, all 30 test files plus `tests/conftest.py` and `tests/golden/`, all 7 scripts.
**Skimmed only:** the YAML/JSON data files (structure and counts, not content accuracy); `web/src/styles.css` (15-selector sample).
**Not read:** bodies of `docs/issues/0001–0037`, `docs/adr/*` beyond status headers, `docs/audits/*`, `docs/research/*`, `docs/reference/*`. Their claims are treated as claims.
**Executed (read-only):** `ruff check --no-cache`, `mypy` (cache outside repo), `uv lock --check`, `pytest -p no:cacheprovider` with `PYTHONDONTWRITEBYTECODE=1`, `tsc --noEmit`, `eslint .`, `vitest run`, `gh issue/pr/run list`, `sqlite3` reads of the local checkpoint DB, `openssl x509` on the public cert. Nothing was built into an image, deployed, or sent to an LLM provider.

---

## PHASE 1 — INVENTORY

### 1.1 Tree (vendor/build collapsed)

```
.
├── CLAUDE.md  CONTEXT.md  README.md  pyproject.toml  uv.lock  .python-version
├── Dockerfile  docker-compose.yml  .dockerignore  .env.example  .gitignore
├── .github/workflows/ci.yml
├── deploy/nginx/{conf.d/coach.conf, certs/}          # certs/ untracked, self-signed CN=localhost
├── src/interview_coach/                              # 33 .py modules, 13,790 LOC (working tree)
│   └── data/{questions.yaml, concepts.yaml}          # built-in reference "pack": 45 questions, 40 notes
├── tests/                                            # 30 test files + conftest + golden/ (6), 13,821 LOC
├── web/                                              # Vite 7 + React 19 + TS 5.9
│   ├── src/{App.tsx, main.tsx, styles.css, components/ (5), lib/ (6 + 3 tests), test/}
│   ├── e2e/{demo-flow, reconnect-flow}.spec.ts
│   ├── .vite/deps/  test-results/                    # TRACKED build/test artifacts (§3.4)
│   ├── dist/  node_modules/                          # ignored
│   └── package.json  package-lock.json  vite/playwright/eslint/tsconfig*
├── scripts/                                          # 7 one-off scripts, 803 LOC
├── data/{bench/ (3 yaml), forge/ (2), packs/fpt/ (3), replay/ (1), exports/ (2, ignored)}
├── docs/{adr/ (12), issues/ (37 + README), audits/ (22), reference/ (2), research/ (5, untracked)}
├── logs/usage-ledger.jsonl                           # ignored runtime state, 1,431 rows
├── .session-checkpoints.sqlite                       # ignored runtime state, 2.7 MB, 1 thread
├── .chroma/                                          # ignored, 3 embedder namespaces
└── .env                                              # ignored, 10 keys set
```

### 1.2 Lines of code

| Language | Tracked files | Lines | Notes |
|---|---:|---:|---|
| Python | 69 | 28,382 | src 13,790 (working tree) / tests 13,821 / scripts 803 |
| TypeScript/TSX | 23 | 1,953 | web/src + e2e |
| CSS | 1 | 1,989 | `web/src/styles.css` alone ≈ the whole TS app |
| YAML | 9 | 3,719 | banks, packs, bench cases, retrieval labels, forge queue |
| Markdown | 76 | 7,169 | docs ≈ 0.5× src |
| JSON | 10 | 5,764 | 4,596 is `package-lock.json`; 665 is a replay golden |
| Lockfiles | 2 | 8,416 | `uv.lock` + `package-lock.json` |

Ratios that matter: **tests ≈ 1.0× src**; **docs ≈ 0.5× src**; **narrative comments inside src are heavy** (`usage.py:1-42` is a 42-line module docstring; `web_api.py:307-320`, `:323-351`, `:354-371` are three consecutive functions whose docstrings exceed their bodies).

Per directory (tracked): `src/interview_coach` 15,424 (incl. 2,120 YAML); `tests` 14,726; `web/src` 3,719; `data` 2,520; `docs/audits` 2,302; `docs/issues` 2,099; `docs/reference` 1,261; `scripts` 803; `docs/adr` 664.

### 1.3 Top 20 largest tracked files

| Lines | File | Kind |
|---:|---|---|
| 4,596 | web/package-lock.json | lockfile |
| 3,820 | uv.lock | lockfile |
| 1,989 | web/src/styles.css | CSS |
| 1,720 | tests/test_web_api.py | test |
| 1,414 | src/interview_coach/cli.py | **god file** |
| 1,154 | tests/test_cli.py | test |
| 1,150 | src/interview_coach/data/questions.yaml | data |
| 1,126 | tests/test_supervisor.py | test |
| 1,033 | src/interview_coach/usage.py | src (uncommitted +365) |
| 992 | src/interview_coach/web_api.py | **god file** |
| 985 | src/interview_coach/llm.py | src (hub, fan-in 14) |
| 973 | tests/test_evaluator.py | test |
| 966 | src/interview_coach/evaluator.py | src |
| 949 | tests/test_usage.py | test |
| 934 | tests/test_retrieval_eval.py | test |
| 893 | tests/test_llm.py | test |
| 767 | src/interview_coach/supervisor.py | src |
| 760 | docs/reference/MVP_v1_2day.md | archived doc |
| 696 | src/interview_coach/interviewer.py | src |
| 665 | tests/golden/replay-trajectory.json | golden |

### 1.4 Entry points — how it actually starts

| Entry | Evidence | What runs |
|---|---|---|
| `coach` console script | `pyproject.toml:25` → `interview_coach.cli:main` | argparse, 13 subcommands (`cli.py:999-1414`) |
| `python -m interview_coach` | `__main__.py:3-6` | same `main` |
| Bare `coach` | `cli.py:1367-1377` | defaults to the **`interview` demo**, which requires a live LLM (`:1376`) and uses different store defaults from the explicit subcommand (`concept_store="memory"` vs `"auto"` at `:1027`) |
| `coach api` | `cli.py:962-996` → `uvicorn.run("interview_coach.web_api:app")` `:990` | FastAPI app, single worker enforced (`web_api.py:354-385`) |
| **Import of `web_api`** | `web_api.py:697-699`: `guard_single_worker()`, `configure_session_logging(...)`, `app = create_app()` at module scope | on import: reads `.env` from CWD (`config.py:63`), opens the CWD-relative checkpoint SQLite and sweeps it (`web_api.py:656, 663-673`), mounts static files |
| Docker | `Dockerfile:75` `CMD ["coach","api","--host","0.0.0.0","--port","8000"]`; healthcheck `:68-69` | one uvicorn worker |
| Compose | `docker-compose.yml:7-47`: `app` + `nginx:1.27-alpine` (TLS, WSS proxy, `deploy/nginx/conf.d/coach.conf`) | — |
| Per-session worker | `web_api.py:278-280`: one `threading.Thread(daemon=True)` per WebSocket start/resume | LangGraph graph streamed on that thread (`:964-992`) |
| Cron / jobs / queues | none (no scheduler, celery, apscheduler anywhere) | — |
| Eval tooling with **no** entry point | `replay.py` (no `coach replay`), `retrieval_eval.py` (only `scripts/retrieval_eval.py`) | reachable from scripts/tests only |

Subcommands (`cli.py:1008-1365`): `evaluate`, `interview` (default), `diagnose`, `session`, `postmortem`, `pack lint`, `eval-harness`, `usage [--reconcile]`, `bench`, `forge`, `ingest-concepts`, `ingest-resources`, `api`. `evaluate`/`interview` are slice demos per the module docstring (`cli.py:1-18`); product surfaces are `session`, `api`, `postmortem`; eval/ops surfaces are `bench`, `eval-harness`, `forge`, `usage`, `pack lint`, `ingest-*`.

### 1.5 Dependencies

**Python runtime** (`pyproject.toml:7-16`): fastapi, langgraph, langgraph-checkpoint-sqlite, openai, pydantic, pydantic-settings, pyyaml, uvicorn[standard]. **Optional `rag`** (`:19-22`): chromadb, sentence-transformers — imported lazily only (`concepts.py:172-176`, `resources.py:159-160`, `forge.py:305-306`). **Dev** (`:28-34`): httpx, mypy, pytest, pytest-cov, ruff.

| Finding | Evidence | Sev |
|---|---|---|
| All 8 runtime deps are imported; no duplicated-purpose libraries (one HTTP client — the `openai` SDK — serves all 4 providers `llm.py:897-902`) | import survey | — |
| **Undeclared direct imports**: `typing_extensions` (`supervisor.py:22`), `starlette` (`web_api.py:30`) — transitive via pydantic/fastapi | `pyproject.toml:7-16` | LOW |
| `MimoClient` and all `mimo_*` settings remain live for a provider retired 2026-06-03; `primary_provider` **defaults to `"mimo"`** | `llm.py:601-623, 898`; `config.py:21, 69, 71-73, 91` | §3.4 |
| `langgraph` is used for one 3-node `StateGraph` + `SqliteSaver` | `supervisor.py:335-347` | design choice (ADR 0004) |
| Version floors only (`>=`); `uv.lock` fresh (`uv lock --check` ok) | `pyproject.toml:8-15` | LOW |

**Web** (`web/package.json:15-38`): `react`, `react-dom`, `lucide-react` (imported in all 6 TSX files); 17 devDeps. `tsc -p tsconfig.app.json --noEmit` and `eslint .` both exit 0 with no output.

### 1.6 Build / deploy — exists vs. works

| Artifact | Exists | Verified here | Status |
|---|---|---|---|
| CI `.github/workflows/ci.yml` | ruff + mypy + pytest; npm lint/test/build | Last 5 `main` runs all `success` (2026-08-01…08-04). Locally: `ruff` clean; `mypy` "no issues in 33 source files"; **pytest 833 passed, 9 deselected, 2 xfailed, 8.6 s**; vitest 32 passed | **Works.** But the last CI run is 41 days old and 1,149 uncommitted lines have never been through it. |
| Dockerfile (2-stage node→uv, non-root uid 10001) | yes | **Not built here.** `docs/deploy.md:170-223` records container verification on 2026-07-27, 08-01, 09-13 | UNKNOWN today: needs `docker build .` |
| docker-compose (app + nginx) | yes | not run | UNKNOWN |
| nginx TLS | yes; `server_name _` | local certs self-signed, CN=localhost, valid to 2027-07-27; untracked (`.gitignore:45`) | smoke-test grade |
| `.env.example` | 122 lines | `.env` on disk sets 10 keys incl. `MIMO_*` and `GROQ_*` (values not read) | keys for a dead provider still present |
| Migrations | **none**. SQLite schema is LangGraph-owned (`checkpoints`, `writes`); skill ledger and usage ledger are schemaless JSON/JSONL with **no version field** | `ledger.py:210-216`; `usage.py:287-331` | any shape change silently breaks old files |
| Secrets in git | `.env`, `privkey.pem`, `.session-checkpoints.sqlite`, `logs/`, `data/exports/` all untracked and ignored | `git ls-files` | **clean** |

---

## PHASE 2 — WHAT IT ACTUALLY DOES

### 2.1 User-facing surfaces

**HTTP / WebSocket** (`web_api.py`):

| Surface | Entry | Auth | Touches |
|---|---|---|---|
| `GET /api/health` | `:526-542` | none | `config.py` flags, `concepts.py:323` retrieval kind |
| `WS /api/sessions/{session_id}` | `:544-629` | Origin check before accept (`:549`), then optional `auth` first frame (`:554`) | `_run_session_thread` `:751-914` → the whole graph stack (§2.3 A) |
| `GET /api/sessions/{session_id}/export.md` | `:631-654` | Bearer when a token is set (`:634-641`) | `exporter.py:32` from RAM, else `exports/<id>.md` from disk |
| `GET /` static UI | `:676-694` | none | `web/dist` when `COACH_STATIC_DIR` set |

Client→server payloads `start_session`/`resume_session`/`candidate_answer`/`cancel_session`/`auth` (`web_api.py:74-111`) match the client exactly (`web/src/App.tsx:96-98, 117-132, 164, 171`; `lib/api.ts:19-22`), except the client **never sends `max_elapsed_seconds`** (server default applies, `web_api.py:82`). Server→client events `question` (`:234`), `session_started` (`:867-874`), `state_update` (`:984`), `session_completed` (`:891`), `session_error` (`:562, 580, 584, 597, 782, 897, 904, 911, 914`) all exist on the client union (`lib/types.ts:161-166`).

**Browser UI** (`web/src`, 3-phase single page, no router): setup (`App.tsx:218-266`, `SetupPanel.tsx`: mode / session id / token / candidate / role / companies / max-q / language / 5 claim sliders `:49-157`); live workspace with question, answer box, Skill bars and Topic Plan (`App.tsx:268-337`, `SkillBars.tsx`, `TopicPlan.tsx`); report with readiness gauge, study plan, 14-day schedule, transcript, Markdown export via Blob download (`ReportView.tsx:12-30, 33-149`). Reconnect/Resume banner (`SessionAlert.tsx`), token field shown only when `health.auth_required` (`SetupPanel.tsx:74-88`). No pack selector. Session id persisted in `localStorage["coach.sessionId"]` (never cleared, `lib/sessionId.ts:11, 45-54`), token in `sessionStorage["coach.authToken"]` (`lib/authToken.ts:11, 25-26`). `API_BASE = VITE_API_URL ?? (DEV ? 'http://127.0.0.1:8000' : window.location.origin)` (`lib/api.ts:8-9`).

**CLI**: `coach session` is the terminal twin of the web flow (`cli.py:456-639`) with extras the web lacks — `--pack`, `--candidate`, `--export-markdown`, `--scripted`, `--diagram`, and **unbounded** `--max-questions` (`:1129`) vs the web's `le=10` (`web_api.py:81`).

### 2.2 Data model — every store, and whether it is actually written

| # | Store | Location (default → container) | Shape | Written by | Read by | Verdict |
|---|---|---|---|---|---|---|
| 1 | **LangGraph checkpoints** (SQLite) | `.session-checkpoints.sqlite` → `/app/state/…` (`config.py:116`, `Dockerfile:62`) | tables `checkpoints(thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint BLOB, metadata BLOB)` and `writes(…)` (DDL read from disk); `thread_id` = session id (`supervisor.py:191-193`); payload = `SessionState` TypedDict `supervisor.py:74-93` with nested transcript items `session_serde.py:130-164`, turns `:211-223`, decisions `supervisor.py:458-464` | every graph step (`cli.py:398`, `web_api.py:980`) | resume (`supervisor.py:196-205`, `web_api.py:917-932`), TTL sweep (`web_api.py:428-469`) | **LIVE.** Local: 1 thread, 5 checkpoints. |
| 2 | **Skill ledger** (JSON) | `.skill-ledger.json` → `/app/state/…` (`config.py:117`) | `{candidate_id: {completed_at, skills: {skill: {alpha, beta}}}}` (`ledger.py:14, 210-216`) — **latest snapshot only** | `save_posteriors` on COMPLETE when `candidate_id != ""` (`cli.py:632-634`, `web_api.py:880-887`, `ledger.py:198-199`) | `load_priors` at start; `load_states` by postmortem | **LIVE but never written locally** (file absent). The web sends `candidate_id` only if the user fills the field (`App.tsx:120-132`). |
| 3 | **Usage ledger** (JSONL, append-only, never rotated) | `logs/usage-ledger.jsonl` → `/app/state/…` (`usage.py:63, 78`; `Dockerfile:65`) + sidecar `.unreconciled` (`usage.py:84-90`) | 4 row kinds: token rows, `session_run`, `questions`, `quota_exhausted`/`quota_retry` (`usage.py:18-24, 287-331`); fault rows (`:392-400`) | `_record_usage` per provider call (`llm.py:497-507`); rails (`web_api.py:786, 846`; `cli.py:587`) | every budget rail, `coach usage`, bench/forge preflight | **LIVE for token rows only.** Real file: 1,431 token rows (2026-07-11→08-01), **0 with a `session` attribution, 0 `session_run`/`questions`/`quota_*` rows** — the R-25 rail row kinds have never been exercised against the real ledger. **51 rows are fabricated test output** (`provider: mimo, model: test-model`, 2026-07-27), admitted at `tests/conftest.py:54-56`. |
| 4 | **Exports** (Markdown) | `data/exports/<safe-id>.md` → `/app/state/exports/` (`config.py:118`, `web_api.py:293-304`) | rendered text, not data | `_persist_export` on COMPLETE (`web_api.py:951-961`); CLI `--export-markdown` | export endpoint fallback (`:650-654`) | **LIVE**; 2 real transcripts locally. |
| 5 | **Chroma** | `.chroma/<embedder>/` (`config.py:126`, `concepts.py:309-320`); collections `concepts`, `resources` | HNSW cosine; metadata `{id, skill, title, language, tags, embedder}` (`concepts.py:63-70, 186-189`) | `ingest` at store build / `coach ingest-*` | Interviewer `lookup_concept` (`concepts.py:233-261`) | **LIVE only with rag extras installed** (`concepts.py:355-362`); else in-memory Jaccard. **The `resources` collection is never used at runtime**: `web_api.py:812` hardcodes `"memory"` and the CLI default is `"memory"` (`cli.py:1174, 1251`), despite `resources.py:3` calling Chroma "the production path". |
| 6 | **In-process** | `WebApiState.completed_sessions`, `.runtimes` (`web_api.py:289-290`) | dicts | `:877`, `:570` | export (`:642`), duplicate-socket check (`:560`) | **LIVE, unbounded**: `completed_sessions` is never evicted. |
| 7 | Process globals | `telemetry._counters` (`telemetry.py:18`); `usage._FAULTS`/`_PROVEN_WRITABLE` (`usage.py:350-353`); `LLMRouter._breakers` (`llm.py:694`) | counters / latch | — | — | LIVE; single-process assumption baked in |
| 8 | **Browser** | `localStorage["coach.sessionId"]`, `sessionStorage["coach.authToken"]` | UUID / token | UI | UI | LIVE |
| 9 | Static content | `src/interview_coach/data/*.yaml` (45 questions, 40 notes), `data/packs/fpt/*` (20 questions, 10 notes), `data/bench/cases.yaml`, `data/bench/retrieval-labels.yaml` (62 rows), `data/replay/*.json` | validated at import (`bank.py:87-135`; `seeds.py:73`) | git | loaders | LIVE (bank, pack, bench, labels). **Never loaded by any code:** `data/bench/pending-cases-2026-07-11.yaml`, `data/forge/review-queue-2026-07-11.yaml` (+ report) — write-only outputs committed to git. |

**Duplicated sources of truth:**
1. A completed Session exists in **three** places — checkpoint (#1), RAM (#6), Markdown (#4). The export endpoint reads RAM, then the file, **never the checkpoint** (`web_api.py:642-654`); after a restart the Markdown rendering is the only readable copy.
2. Skill posteriors live in the checkpoint's `skill_states` **and** the skill ledger, which keeps only the last snapshot (`ledger.py:210-216`) — the progress dashboard (GH #83) has no history to draw from (`docs/issues/README.md:55` agrees).
3. Provider retry constants are **restated** in `usage.py:157-172` to dodge an import cycle (`:145-150`); a test pins the copy.
4. `llm_reasoning` duplicates `reasoning` in every Supervisor record (`supervisor.py:463`; admitted `session_serde.py:189-192`; declared on the client `types.ts:134`).
5. Stop-reason display names: `cli.py:145-152` and `exporter.py:13-21`.
6. Client/server state shape drift: server-only `max_elapsed_seconds`, `started_at`, `candidate_id`, `ledger_prior_mastery` (`supervisor.py:83-92`); `Evaluation.evidence_degraded/panel/trust` (`evaluator.py:179, 197-198`); `TranscriptItem.evidence_weight/error` (`session_serde.py:106, 109`); `SupervisorDecision.will_probe_skill` (`supervisor.py:107`) — none declared in `web/src/lib/types.ts:56-159`. The UI therefore cannot show evidence-degraded or panel verdicts, which the export does (`exporter.py:179-207`).

### 2.3 Critical flows, file by file

**A. Web live interview, start → completion**

1. Browser opens `ws(s)://…/api/sessions/{uuid}` (`lib/api.ts:49-55`, `App.tsx:91`); sends `auth` then `start_session` (`App.tsx:96-98, 120-132`).
2. `session_socket` (`web_api.py:545`): `origin_allowed` (`:549` → `:149-169`) → `accept` → `authenticate_socket` (`:554` → `:201-211`; constant-time compare `:172-183`) → duplicate-id check (`:560`) → `RuntimeSession` registered (`:568-570`) → `_parse_payload` (`:578` → `:708-726`) → `_select_mode` (`:587` → `:733-738`) → **daemon thread** `_run_session_thread` (`:588-594`).
3. Thread (`:751`): `_client_for_mode` (`:758` → `build_client` `llm.py:905-916`) → `build_role_clients` (`:761` → `llm.py:966-985`; judge pinned to one provider, non-bench-validated judge refused `config.py:212-244`) → rails `token_identity`/`question_cap_reason`/`start_refusal_reason`/`record_questions` (`:772-786` → `usage.py:660-672, 863-885, 838-860, 301-310`) → concept store (`:806-811` → `concepts.py:334-371`) → `SqliteSaver` + `session_scope` (`:829` → `usage.py:259-266`) → `build_session_graph` (`:830` → `supervisor.py:208-347`) → `begin_session_run` (`:846`) → `load_priors` (`:852` → `ledger.py:88-132`) → `diagnose_or_degrade` (`:853` → `diagnostic.py:214-248`, **LLM call** `:256`) → `initial_session_state` (`:858` → `supervisor.py:136-188`) → emit `session_started` (`:867`) → `_stream_graph` (`:875` → `:964-992`).
4. Graph (`supervisor.py:335-347`): `START → run_question → supervisor → (run_question | study_plan) → END`.
   - `question_node` (`:234-316`): `select_seed_question` (`:248` → `seeds.py:92-124`) → `QueueCandidate` (`web_api.py:835`) → `run_micro_loop` (`:261` → `microloop.py:195-322`).
   - Micro-loop: `render_seed_question` (`microloop.py:224` → `interviewer.py:647-696`, LLM call only for vn/mixed) → `candidate.answer` (`:234` → `web_api.py:233-244`: emits `question`, **polls a queue every 100 ms**) → `evaluate` (`:236` → `evaluator.py:875-966` → `_evaluate_once` `:805-835` → `chat_json` `llm.py:237-313` → `_create` `:402-474` → **`accounting_gate`** `usage.py:524-543` → OpenAI SDK `:435` → `_record_usage` `:471`) → cross-check (`evaluator.py:908`) → optional panel (2 voices `:928-929` + verdict `:931`) → follow-up if flagged (`microloop.py:274` → `interviewer.py:577-625` → `chat_with_tools` `llm.py:526-573`: forced `lookup_concept` → `concepts.py:374-383` → structured final) → loop until `RESOLVED`/`SAFETY_CAP`/`FOLLOW_UP_UNAVAILABLE` → `apply_evaluation` (`microloop.py:321` → `skill.py:173-183`).
   - `TranscriptItem.from_micro_loop` (`supervisor.py:310`); any other exception → `TranscriptItem.failed` (`:285-305`).
   - `supervisor_node` (`:318`) → `decide_next_move` (`:350-408`): hard caps, then **LLM call** `:384` with validators `:531-579`, deterministic fallback `:474-500` → `_apply_supervisor_decision` (`:420-471`).
   - `study_plan_node` (`:322-333`) → `plan_study` (**LLM call**, `study_planner.py:188`) → END.
   - Each `stream_mode="values"` event: emit `state_update` (`web_api.py:984`), cancel check (`:981`), `budget_stop` (`:988` → `usage.py:949-981` → `:888-946`).
5. Completion (`web_api.py:876-891`): `completed_sessions[id] = state` → `_persist_export` (`:881` → `exporter.py:24-29`) → `save_posteriors` (`:882` → `ledger.py:182-242`) → emit `session_completed`.
6. Browser downloads `/export.md` with Bearer (`ReportView.tsx:12-30`, `api.ts:36-40`).

Worst-case call model per question: `usage.py:175-190`; measured ≈5,200 tokens per question (`usage.py:136`).

**B. Auth / authz**

- WebSocket: missing `Origin` **passes** (`web_api.py:165-166`); no token → loopback origins only (`:167-168`); token → allowlist (`:169`). Then a `{"type":"auth","token":…}` frame within 10 s (`:123, :201-211`).
- HTTP export: `Authorization: Bearer`, constant-time (`:634-641`).
- **No identity.** One shared secret (`config.py:104-107`); the session id is a client-chosen URL segment; **any token holder can resume, cancel, or export any session id** (`web_api.py:560-565, 595-607, 642-654`). The product-cap identity is `sha256(token)[:16]`, so the whole deployment is one bucket (`usage.py:660-672`). Documented as the pilot trust boundary (`docs/issues/README.md:33-36`).

**C. Resume after disconnect**

- Web: reconnect with the same `localStorage` id, send `resume_session` (`App.tsx:134-149`). Server: new `RuntimeSession` (`web_api.py:568-570`), `_checkpoint_values` reads `language_mode`/`max_questions` (`:766, 917-932`), `clear_run_rails_for_resume` grants one more per-run budget and un-latches quota (`:792-798` → `usage.py:1009-1033`), `graph.stream(None, config)` resumes (`:838, 980`); the pending question re-emits because `question_node` re-enters and `QueueCandidate.answer` emits again (`:233-234`).
- CLI: `cli.py:529-570` (unknown id → friendly error `:531-535`; elapsed budget restarts `:538`; recap `:562`).
- **Granularity is the question, not the turn**: the whole micro-loop is one node (`supervisor.py:261-270`), so answered follow-ups inside an unfinished question are lost on crash. `docs/issues/README.md:50, 174-217` already schedules this as M1.

### 2.4 Where state lives — summary

Durable: #1 SQLite, #2 JSON, #3 JSONL, #4 Markdown, #5 Chroma. Volatile: two dicts (#6), four module globals (#7). Client: two browser keys (#8). Configuration: pydantic `Settings` from `.env` **plus six raw `os.environ` reads that bypass it** (`usage.py:78, 102-103, 208, 212`; `evaluator.py:448`; `web_api.py:698`; `cli.py:974`) — two config systems.

---

## PHASE 3 — DAMAGE REPORT

Severity: CRITICAL = data/money loss or compromise likely in normal use; HIGH = same under plausible misuse or concurrency; MEDIUM = bounded correctness/maintainability defect; LOW = hygiene.

### 3.1 Security

| Sev | Finding | Evidence | Blast radius |
|---|---|---|---|
| HIGH | **Unset `COACH_AUTH_TOKEN` = fully open API to any non-browser client.** Only a log warning. Missing `Origin` always passes, so curl/scripts bypass the loopback rule. | `web_api.py:165-168, 502-507`; `config.py:104-107`; `.env.example:44-51` | Anyone reaching the port runs paid interviews on the operator's key and reads transcripts. |
| HIGH | **No per-record ownership.** With the shared token, any pilot user can resume, cancel, or export any other user's Session by id. | `web_api.py:544-565, 595-607, 631-654`; ids are client UUIDs (`sessionId.ts:13-23`) | Cross-user transcript disclosure and cancellation. Acknowledged trust boundary (`docs/issues/README.md:33-36`). |
| MEDIUM | **Unbounded inputs**: `answer: str` no length cap; `max_elapsed_seconds` no ceiling; `answers` queue unbounded; a socket may send `candidate_answer` frames without limit. | `web_api.py:91-93, 82, 267, 613-614` | Memory and prompt-token cost on a single process; one abusive holder degrades everyone. Scheduled as M0b F2 (`docs/issues/README.md:89`). |
| MEDIUM | `/api/health` unauthenticated; discloses provider names, configured flags, `auth_required`. | `web_api.py:526-542` | reconnaissance |
| LOW | CORS `allow_credentials=True` with wildcard methods/headers; origins enumerated. | `web_api.py:518-524` | none while origins stay explicit |
| LOW | `.env` on disk still carries MiMo (dead) and Groq (not judge-validated) keys. | key names only | credential sprawl |
| INFO (good) | Export filename traversal neutralised by digest; constant-time token compare; token in a WS frame not a query string; non-ASCII token refused at startup; `.env`/certs/state ignored. | `web_api.py:293-304, 172-183, 100-105, 307-320`; `.gitignore:21-35, 45` | — |

### 3.2 Correctness

| Sev | Finding | Evidence | Blast radius |
|---|---|---|---|
| HIGH | **Disconnect → reconnect → resume race.** On `WebSocketDisconnect` the handler sets `cancelled`, but the daemon thread may be inside a provider call for tens of seconds. The `finally` pops the runtime at once, so a reconnect on the same id is accepted and `resume_session` starts a **second graph thread on the same checkpoint thread_id**; `_is_running` inspects only the *new* runtime. The old thread's later emits are dropped silently. The test suite itself shows a session thread outliving its socket (a `ValueError: I/O operation on closed file` from `web_api.py:910` during `tests/test_web_api.py:1697-1720`). | `web_api.py:621-629` (pop), `:595-607` (resume), `:729-730`, `:252-259` (drop), `:981` (old thread notices cancel only at its next stream event) | Two writers on one SQLite checkpoint thread; interleaved or duplicated transcript items; a resumed Session re-asks a question the old thread is still scoring. This is the exact path the UI advertises as "Reconnect & Resume" (`SessionAlert.tsx`). The plan admits it is unbuilt (`docs/issues/README.md:181`). |
| HIGH (known, GH #119) | `insufficient_quota` inside a question is caught by `question_node`'s broad `except Exception` → zero-evidence `failed` item, `question_count + 1`. Only `CandidateIntent` and `AccountingUnavailable` are re-raised. The ledger latch (`llm.py:455`) stops the *next* question, not this one. | `supervisor.py:271-305`; `llm.py:442-456`; `usage.py:888-946` | Violates ADR 0005's own rule once per quota event. |
| MEDIUM | **Question-cap reservation race**: `questions_today` check and `record_questions` append are separate, unlocked, across threads. | `web_api.py:772-786`; `usage.py:863-885, 301-310` | Two simultaneous starts both pass. M0 acceptance not met (`docs/issues/README.md:152`). |
| MEDIUM | **Import-time side effects**: importing `web_api` runs the worker guard, logging config, and `create_app()` — which reads `.env` from CWD, opens and sweeps the CWD-relative checkpoint SQLite, mounts static files. Tests import it (`tests/test_web_api.py:17`) and conftest pops env vars at collection to survive it. | `web_api.py:697-699`; `config.py:63`; `web_api.py:656, 663-673`; `tests/conftest.py:18-38` | Any importer mutates operator state. |
| MEDIUM | **Tests wrote into production state** (historical; mitigated only in the *uncommitted* conftest): 51 `mimo/test-model` token rows in the real usage ledger. | `logs/usage-ledger.jsonl` (counted); `tests/conftest.py:48-66`; `tests/test_llm.py:266-270` | Corrupted the 2026-07-27 `mimo` spend; shows the ledger has no provenance guard. |
| MEDIUM | **Ledger read amplification**: every graph event's `budget_stop` re-parses the whole all-time JSONL ≥4 times; every provider call re-reads the fault sidecar; the ledger is never rotated. | `usage.py:914-946 → 783-799, 735-780, 815-818`; `:524-543 → 424-441`; `:627-647` | O(rows) per call. Trivial at 1,431 rows; a cliff for a long-lived deployment. |
| MEDIUM | **`completed_sessions` never evicted** (checkpoints have a 7-day TTL; RAM has none). | `web_api.py:289, 877`; `config.py:130` | one full Session state leaked per completion until restart |
| MEDIUM | Silent `except Exception` with **no log** in eval tooling: `forge.py:418` (records rejection), `bench.py:187` (error string; module has no logger), `eval_harness.py:116`. | as cited | a provider or schema failure inside a bench/forge run is invisible in stderr; only the report row shows it |
| MEDIUM | `harness_passed` has no non-empty guard (`all([])` is `True`), unlike `bench_passed`. | `eval_harness.py:123-124` vs `bench.py:242`; noted at `forge.py:443-444` | an empty harness reports green |
| LOW | A crash between `completed_sessions[...] =` and `save_posteriors` silently loses the ledger write (`save_posteriors` never raises). | `web_api.py:877-887`; `ledger.py:195-197` | one Session's priors lost |
| LOW | Bare `coach` runs the LLM-requiring demo with defaults that differ from the explicit subcommand. | `cli.py:1367-1377` vs `:1024-1055` | footgun |
| LOW | CLI `--max-questions`/`--max-turns` unbounded vs web `le=10`. | `cli.py:1129-1135` vs `web_api.py:81` | budget arithmetic assumes small values |
| LOW | Dead-provider defaults: `primary_provider="mimo"`; `LLMRouter` fallback default references mimo/groq (unreachable via `build_client`). | `config.py:69`; `llm.py:690, 912-916` | a fresh checkout without `.env` says "primary 'mimo' not configured" |
| LOW | Unreachable `SKIP_AHEAD` default (`current_index + 2`) — the validator rejects the decision and the fallback never emits it. | `supervisor.py:444` vs `:547-548, 474-500` | dead branch |
| LOW | `QueueCandidate.answer` busy-polls at 100 ms although a cancel sentinel already exists. | `web_api.py:233-244, 217` | negligible CPU |
| LOW | `scripts/review_issue_0008_chroma_retrieval.py:73` divides `hits / total` unguarded (marked SUPERSEDED at `:3`). | as cited | script only |

### 3.3 Duplication (same logic, 2+ copies, which is live)

| Logic | Copies | Live |
|---|---|---|
| Stop-reason display names | `cli.py:145-152`; `exporter.py:13-21` | both |
| Study-plan console print block | `cli.py:346-357`; `cli.py:668-679` | both |
| Skill-ledger loader (read + validate + decay) | `ledger.py:88-132` `load_priors`; `ledger.py:135-179` `load_states` (~40 lines differing only in return shape) | both |
| Follow-up generation | native tool path `interviewer.py:460-511`; JSON two-turn emulation `:514-574` ("used only by non-native fake/dummy clients", `:524-527`) | native in prod; JSON only for fakes — test-only code shipped in a production module |
| Provider attempt constants | `evaluator.py:39`, `interviewer.py:333`, `llm.py:243`, `evaluator.py:450`; restated `usage.py:157-172` | both (import cycle) |
| Supervisor `reasoning` | `supervisor.py:98`; `llm_reasoning` `:463`, `session_serde.py:203`, `types.ts:134` | both, on the wire |
| ASCII tokenizer `[A-Za-z0-9_]+` + `_tokens` | `concepts.py:99-102`; `resources.py:85-89`; `forge.py:281-285`; `demo_llm.py:233` | all four |
| Token-overlap / Jaccard ranker | `concepts.py:140-142`; `resources.py:123-127`; `forge.py:288-293` | all |
| Chroma store creation (ImportError→RuntimeError, revision pin, embedder stamp) + `_metadata_filter` | `concepts.py:177-199, 264-270`; `resources.py:158-188, 241-247`; import pattern `forge.py:304-314` | all |
| Repo-root data path idiom | `bench.py:153`; `retrieval_eval.py:53-57`; `usage.py:63` | all |
| Strong/weak band thresholds 3.5/3.0 | `bench.py:55, 59`; `forge.py:59-60` | both |
| Case dataclass with `expected_min/max/expected_range` | `bench.py:31-59` `BenchCase`; `eval_harness.py:33-45` `GoldenAnswerCase` | both |
| Before/after counter delta | `telemetry.py:35`; `cli.py:760-770` `_usage_delta`; `llm.py:196` `call_counts` | all |
| Post-mortem evidence-weight formula | `postmortem.py:279`, `:417`; `cli.py:648` | all three |
| Weak-dimension extraction | `study_planner.py:428-444` and `:459-466` | both |
| Markdown pipe escaping / unescaping | `exporter.py:269-271`; `retrieval_eval.py:452-455` (inverse); `forge.py:548` | all |
| Report header provider/model/date | `bench.py:475-481`; `forge.py:562-571`, `:637-646` | all |
| `posterior_masteries` re-does `skill_states_from_mapping` | `replay.py:126-131` vs `session_serde.py:236` | both |
| `_synthesized_session_state` hand-mirrors `initial_session_state` | `postmortem.py:365-389` vs `supervisor.py:136` (admitted `:373`) | both |
| Test fakes | `_ProviderDemoClient` in `tests/test_cli.py:489` **and** `tests/test_web_api.py:1321`; `_MeteredDemoClient` in `test_cli.py:869` **and** `test_web_api.py:1331` (identical bodies); same-named helpers with differing bodies: `_evaluation` ×6, `_settings` ×3, `_eval` ×3, `_decision` ×2, `_diagnostic` ×2 (locations in §3.8) | — |

### 3.4 Dead code — deletion list

| Item | Evidence | ≈Lines |
|---|---|---|
| `web/.vite/deps/_metadata.json`, `web/.vite/deps/package.json`, `web/test-results/.last-run.json` — tracked build/test caches | `git ls-files`; added `5181192`/`d2a1365`; not ignored | 3 files |
| `MimoClient`, `_thinking_extra_body`, `mimo_*` settings, `"mimo"` in `ProviderName`/defaults/registry — provider retired 2026-06-03 | `llm.py:594-595, 601-623, 690, 898`; `config.py:21, 69, 71-73, 91, 164-167, 172, 179`; `tests/conftest.py:16, 171-179` and `scripts/smoke_issue_0007.py:122-131` are bound to it | ≈60 src + fixtures |
| `disable_thinking` threaded through every `chat*` signature (only MiMo consumes it) | `llm.py:223, 244, 334, 409, 423`; 4 external call sites | ≈15 |
| `_generate_follow_up_json` fake-only path (and the `supports_tool_calls` branch) | `interviewer.py:514-574, 598-616` | ≈60 |
| `forge.build_embedding_similarity` — **no caller anywhere** | `forge.py:296-323` | 28 |
| `TranscriptItem.to_dict` + `_raw` read-view guard — **no caller in `src/` or `tests/`** | `session_serde.py:110-111, 166-182` | ≈20 |
| `scripts/dump_serde_goldens.py::_skill_state` — defined, never called | `:86-89` | 4 |
| `fixtures.FixtureQuestion` referenced only inside its file | `fixtures.py:16-37` | — |
| `telemetry.reset` — test-only | `telemetry.py:31`; callers only in `tests/` | 2 (keep, but it is a test hook) |
| Unreachable `SKIP_AHEAD` default; `LLMRouter` fallback default; `cli._utc_date` | `supervisor.py:444`; `llm.py:690`; `cli.py:748-751` | 6 |
| `SelfCritiqueTrace` + `_escalation_triggers` shim for pre-2026-07-11 checkpoints; `bench.py:503-504` renders it though no `self_critique=` is ever assigned | `evaluator.py:103-113, 196`; `microloop.py:115-124`; `types.ts` still declares `self_critique` | ≈25 — **candidate only**: CLI checkpoint DBs are never swept |
| `coach evaluate` / `coach interview` slice demos + `ANSWERS` table (keep `fixtures.py`: `eval_harness.py:9` uses it) | `cli.py:120, 184-262, 1008-1055, 1367-1377` | ≈130 |
| `data/bench/pending-cases-2026-07-11.yaml`, `data/forge/review-queue-2026-07-11.{yaml,md}` — committed outputs with **no loader** | grep across src/scripts/tests | 3 files |
| `scripts/review_issue_0008_chroma_retrieval.py` (self-declared SUPERSEDED), `scripts/smoke_issue_0007.py` (MiMo-bound), `scripts/create_issues.sh` (says 13 issues, glob matches 37, aborts if any exists → inert) | `:3`; `:122-131`; `:2, 17-22` | 3 files |
| `docs/reference/MVP_v1_2day.md`, `MVP_v2.md` — archived per `CLAUDE.md` | 1,261 lines | 2 files |
| Duplicate `.claude/` in `.gitignore` | `.gitignore:38, 44` | 1 |
| Unused TS exports: `API_BASE`, `exportFailureMessage`, `exportMarkdownUrl` (`api.ts:8, 43, 57`); 9 types in `types.ts:10-137` referenced only inside `types.ts`; `AppSession` (`sessionReducer.ts:3`) | grep across `web/src` | — |
| CSS classes used in TSX with **no rule**: `delivery-fixes`, `field-row`, `ghost-button`, `hint` | `ReportView.tsx:134`; `SetupPanel.tsx:62, 66, 59` | 4 dangling names |

Commented-out code: none in `src/` (4 grep hits, all prose). The volume problem is the opposite — live prose.

**Stale comments that contradict the code** (cite when editing): `forge.py:43-45` "LLM stack has NO rate-limit/backoff logic" — contradicted by `llm.py:33-40, 141-166`; `forge.py:567-568` "a mid-run provider failover silently swaps the judge" — the judge is pinned and bypasses the router (`llm.py:9-10`, `cli.py:1412-1413`); `forge.py:49` "42 bank prompts" — 45 today; `resources.py:3` "production path is Chroma" — every runtime caller builds `"memory"`; `replay.py:69-70` "uses its own client" — default shares the judge client (`:117`); `README.md:157` `PRIMARY_PROVIDER=mimo|groq`; `README.md:146` "exactly one Self-critique pass" (superseded by the panel, `evaluator.py:565-572`); `README.md:258` "green (29/29)" vs `CLAUDE.md` 35/35; `README.md:287-289` lists `MimoClient, GroqClient` and omits `OpenAIClient`/`ZenMuxClient`.

### 3.5 Inconsistency — competing patterns for the same job

| Job | Pattern 1 | Pattern 2 | Pattern 3 |
|---|---|---|---|
| Error handling | typed control-flow exceptions re-raised past nets (`microloop.py:39-57`; `usage.py:229-249`) — pass-through list hand-maintained per net (`supervisor.py:271-284`) | broad `except Exception` + log + degrade (`supervisor.py:285, 330, 393`; `diagnostic.py:240`; `web_api.py:912`) | return `None`/`{}`/error-string on failure (`ledger.py:96-132`; `web_api.py:925-932`; `bench.py:187`; `eval_harness.py:116`) |
| Configuration | pydantic `Settings` (`config.py:61-148`) | raw `os.environ.get` for 6 knobs (`usage.py:78, 102, 208, 212`; `evaluator.py:448`; `web_api.py:698`; `cli.py:974`) | argparse defaults that ignore both (`cli.py:1082-1086` `--checkpoint-db` ignores `COACH_CHECKPOINT_DB`) |
| State shape | `TypedDict` (`supervisor.py:74-93`) | frozen read-views that refuse to serialise (`session_serde.py:39-182`) | raw `.get` on top-level keys by policy (`session_serde.py:8-12`); pydantic for LLM outputs; dataclasses for domain |
| Client construction | `build_client` → router (`llm.py:905`) | `build_role_clients` → bundle (`:966`) | `ensure_role_clients` + `ClientArg` union at 9 CLI sites (`cli.py:124, 185, 240, 282, 457, 683, 740, 777, 891`) |
| Logging setup | `basicConfig(force=True)` in CLI (`cli.py:1379-1384`) | `configure_session_logging` at web import (`web_api.py:388-425`) | uvicorn's own |
| "ledger" | Skill ledger (`ledger.py`, `--ledger-db`, `COACH_LEDGER_DB`) | Usage ledger (`usage.py`, `COACH_USAGE_LEDGER`) | `CONTEXT.md` defines neither |
| Bounds | web `Field(ge=1, le=10)` (`web_api.py:81`) | CLI unbounded (`cli.py:1129-1135`) | — |
| Markdown escaping | `exporter._md` (`:269-271`) | `forge._excerpt` (`:548`) | `retrieval_eval._unescape_md` (`:452-455`) |
| Eval report writers | `bench.render_bench_report` → `docs/audits/` (`cli.py:813-815`) | `forge.write_forge_outputs` → `data/forge/` (`cli.py:1323, 922`) | `retrieval_eval` → stdout only (`:459-463`) — three conventions, two of which write **into the git tree by default** |
| Demo client coupling | `demo_llm.py:128-261` regex-parses the Evaluator/Interviewer/Planner **prompt text** to choose canned answers | — | a prompt wording change silently breaks demo mode |

### 3.6 God objects and tangles

| Module | Lines | Concerns bundled | Churn |
|---|---:|---|---|
| `cli.py` | 1,414 | 13 commands, fan-out 23 (highest), session driver, resume UX, bench/forge preflight, printing | 31 commits — most-changed file |
| `web_api.py` | 992 | origin policy, auth, worker guard, logging, checkpoint sweeper, static mount, WS protocol, thread driver, budget rails, export persistence, resume | 14 |
| `usage.py` | 1,033 | JSONL IO, fault latch (module globals), measured constants, worst-case call model, per-run baseline, cap reservation, every rail *sentence* | uncommitted +365 |
| `llm.py` | 985 | transport retry, quota detection, per-call trace, usage recording, structured output + repair, tool loop, 4 provider classes, breaker, router, role pinning | fan-in **14** — every agent module |
| `supervisor.py` | 767 | graph wiring, node bodies, prompt builder, validators, fallback, state init | 17 |
| `evaluator.py` | 966 | schema + sanitiser, evidence check, 3 confidence haircuts, panel, prompts, JSON-schema builder | 12 |

**Import cycles** (graph walk): `bank ↔ seeds`, `bank ↔ concepts`, broken only by deferred in-function imports (`bank.py:10-13, 25-27, 92-94, 154-155, 213`). Near-cycle avoided by restating constants: `llm → usage` while `evaluator/interviewer/supervisor → llm` (`usage.py:145-150`).

### 3.7 Coupling map — what must change together

| Change | Files that move together |
|---|---|
| Any key in the Session wire format | writer `supervisor.py:160-188, 298-316, 458-471` → `session_serde.py` → `exporter.py`, `ui.py`, `cli.py:298-357`, `study_planner.py`, `replay.py`, `postmortem.py:365-389`, `web/src/lib/types.ts`, and the byte-goldens `tests/golden/*` via `tests/test_serde_golden.py` |
| `LLMClient` signature | `llm.py` + 14 importers + `demo_llm.py` + `FakeOpenAI` (`tests/conftest.py:83-169`) + 6 `LLMClient` subclasses in tests (`test_llm.py:46, 63, 73, 511`; `test_replay.py:25, 40`; `test_roles.py:47`; `test_interviewer.py:347`) |
| A retry/attempt count | `evaluator.py:39` / `interviewer.py:333` / `llm.py:243` **and** `usage.py:157-172` **and** `tests/test_usage.py` |
| Budget rail order or wording | `cli.py:494-513, 549-561, 582-587` **and** `web_api.py:772-798, 816-825, 841-846` — two hand-kept mirrors (`usage.py:949-963`) |
| Rubric anchors or judge prompt | `rubric.py:40-86` + `evaluator.py` prompts + `data/bench/cases.yaml` anchors + a `coach bench --k 3` run (ADR 0009) + `demo_llm.py` regexes |
| A fourth control-flow exception | every net: `supervisor.py:271-284`, `diagnostic.py:235-239`, `web_api.py:892-914`, `cli.py:604-631`, `postmortem.py:199-201` |
| Skill taxonomy | `diagnostic.py:23-29` → `bank.py:111, 222` → `diagnostic.py:119-161` tables → both YAML banks → `forge --skill` choices (`cli.py:1307`) → 5 sliders (`SetupPanel.tsx:135-157`) |
| Export line format | `exporter.py:143` ↔ regexes in `retrieval_eval.py:358-363` (string-format coupling for the retrieval harvest) |

### 3.8 Test coverage — real or theatre?

**Real.** Run: `833 passed, 9 deselected, 2 xfailed, 1 warning in 8.64s` (835 collected; 9 deselected = 7 `@live` + 2 `@rag`, `pyproject.toml:47-51`). Web: `32 passed` in 4 vitest files. No test writes into the repo tree (git status unchanged after the run); all file IO goes to `tmp_path`.

| Property | Finding |
|---|---|
| Assert-less tests | 5, all "does not raise" over a production validator/guard: `tests/test_supervisor.py:951, 982`; `tests/test_web_api.py:914, 942, 967`. No `assert True`. |
| WEAK files | none. `test_bank.py` is MIXED (content-inventory thresholds `:69-72` alongside behavioural checks `:44`). |
| Fake stack | one OpenAI-shaped fake (`tests/conftest.py:83-169`) injected into real `MimoClient`/`GroqClient` (`:187-207`); production `DemoLLMClient` for CLI/web; 6 local `LLMClient` subclasses. `fake.call_count == N` at 24 sites always sits beside a behavioural assert (e.g. `test_microloop.py:166` + `:172`) — call-budget contracts, not the sole check. |
| Monkeypatch density | `test_cli.py` 64 (`cli.load_settings` ×28, `cli.build_client` ×26); `test_supervisor.py` replaces `run_micro_loop` ×10 (Supervisor-in-isolation); `test_llm.py` injects `_sleep`/`_now` (no real time). |
| Flake candidates | `test_ledger.py:212-213` `sleep(0.05)` + `Barrier` (deliberate race widening); `test_postmortem.py:349, 379` two `time.time()` reads; `test_usage.py:108, 409` day-stamped rows read via `utc_date()` — a UTC-midnight crossing is the window. |
| Duplicated helpers | `_ProviderDemoClient`/`_MeteredDemoClient` copied verbatim between `test_cli.py:489, 869` and `test_web_api.py:1321, 1331`; same-named-different-body: `_evaluation` (`test_diagnostic.py:52`, `test_postmortem.py:47`, `test_skill.py:18`, `test_ledger.py:29`, `test_evaluator.py:61`, `test_roles.py:165`), `_settings` (`test_cli.py:43`, `test_postmortem.py:92`, `test_roles.py:35`), `_eval` (`test_trajectories.py:26`, `test_microloop.py:35`, `test_supervisor.py:52`). |
| Goldens | `tests/test_serde_golden.py` byte-compares 6 surfaces regenerated by `scripts/dump_serde_goldens.py` under a frozen clock (`:73-83`) from a demo persona run + the drifted checkpoint `data/replay/deep-learning-strong.json`. **This, not `coach bench`, is the refactor-safety harness.** |
| No dedicated test file | `config.py` (covered by `test_roles.py`), `demo_llm.py` (2 tests in `test_ui.py`), `exporter.py` (via goldens + 3 files), `rubric.py`, `telemetry.py`, `fixtures.py`, `__main__.py` (never imported). |
| Web | `rendering.test.tsx` imports `stateFixture` from `sessionReducer.test.ts:95` and thereby **re-registers that file's 7 tests** (13 reported, 6 own). Nothing renders `App`/`SetupPanel`; the WebSocket and export paths have no unit test; Playwright specs need a live backend (`demo-flow.spec.ts:4-6`; `reconnect-flow.spec.ts:13-14, 93-96`) and were not run. |
| Coverage % | `.coverage` is dated 2026-07-27, older than HEAD — stale, not used. |
| Live tests | 7 `@live` self-skip without credentials; 2 `@rag` `importorskip`. The judge itself is therefore exercised in CI **only through fakes**; the real-model gate is the manual `coach bench --k 3` (ADR 0009). |

---

## PHASE 4 — SALVAGE ASSESSMENT

| Module | Bucket | Reason |
|---|---|---|
| `skill.py` | **KEEP** | 183 lines of pure, tested Beta arithmetic; single rehydration point; no LLM. |
| `microloop.py` | **KEEP** | The clearest module in the repo: the loop the product is about, ~130 lines of logic. |
| `session_serde.py` | **KEEP** | Correct typed read-views, byte-golden-tested; drop the unused `to_dict`. |
| `evaluator.py` | **KEEP** | Dense but every guard is deterministic, bench-gated, cited; the one module you must not touch without `coach bench --k 3`. |
| `rubric.py`, `seeds.py`, `bank.py`, `language.py`, `config.py`, `telemetry.py`, `ui.py`, `exporter.py`, `diagnostic.py`, `concepts.py`, `study_planner.py`, `demo_llm.py` | **KEEP** | Small, single-purpose, validated, tested. `config.py` after MiMo removal; `study_planner` has one in-file duplicate; `demo_llm` is regex-coupled to prompt text but is demo-only. |
| `ledger.py` | **KEEP** | Correct atomic-rename + lock; fold `load_states` into `load_priors`. Its *design* (latest snapshot only) is the limit, not the code. |
| `resources.py` | **KEEP** (trim) | Correct; its Chroma half is unreachable from every runtime caller — either wire it or delete it. |
| `interviewer.py` | **FIX** | Sound; remove the JSON fake-only path and `disable_thinking` plumbing → one generation path. |
| `supervisor.py` | **FIX** | Sound plan-executor; fix #119 pass-through, delete the dead branch, replace the hand-listed pass-through exceptions with a base class or predicate. |
| `llm.py` | **FIX** | Correct and well-tested, but 10 concerns in one hub; delete MiMo, declare `typing_extensions`, split router/breaker from provider clients. |
| `usage.py` | **FIX** | Right ideas (client-side budget, latch, suspend/resume); wrong shape (re-parses an unrotated JSONL per call; 6 env knobs and 2 globals hidden inside). **Uncommitted — review before it lands.** |
| `web_api.py` | **FIX** | Fix the reconnect race, bound inputs/queues, evict `completed_sessions`, move `create_app()` out of import time; split into auth / session-runtime / app. |
| `cli.py` | **FIX** | Split per command group; delete the two demos; source defaults from `Settings`. |
| `postmortem.py` | **FIX** | Sound; remove the 3× weight formula and the hand-mirrored state builder. |
| `bench.py`, `eval_harness.py`, `forge.py` | **FIX** | Load-bearing for the project's stated first priority (measured judge quality). Add logging to the silent catches, share the case dataclass/bands, stop writing reports into the git tree by default. |
| `replay.py`, `retrieval_eval.py` | **FIX or DELETE** — decide | 681 lines with **no CLI entry**; reachable only from scripts/tests. `CLAUDE.md` calls replay the Supervisor's eval gate — if so, wire `coach replay`; if not, they are dead weight with 66 tests attached. |
| `fixtures.py` | **KEEP** | 55 lines; `eval_harness` depends on it. |
| `web/src` | **FIX** | Small, typed, lint/tsc clean, tests real; sync `types.ts` with the server, add the 4 missing CSS rules, stop re-registering tests, cover `App`/WS. |
| `MimoClient` + config, tracked web caches, demo commands, unloaded data outputs, superseded scripts, `docs/reference/*`, dup helpers | **DELETE** | dead provider, committed caches, slice-0001 demos, write-only artifacts, archived docs. |
| **REWRITE** | none | Nothing is rotten enough that from-scratch beats repair behind the same interface. The two god files need *splitting*, not rewriting. |

**Load-bearing share (computed from module line counts, 13,790 src lines):**
- Product runtime path (`cli`, `web_api`, `llm`, `usage`, `supervisor`, `microloop`, `evaluator`, `interviewer`, `skill`, `ledger`, `session_serde`, `exporter`, `diagnostic`, `language`, `concepts`, `resources`, `study_planner`, `bank`, `seeds`, `rubric`, `config`, `telemetry`, `ui`, `demo_llm`, `postmortem`): **11,593 lines ≈ 84%**.
- Eval tooling wired to the CLI (`bench`, `forge`, `eval_harness`, `fixtures`): **1,516 ≈ 11%** — load-bearing for priority (1), not for a Candidate.
- Eval code reachable only from scripts/tests (`replay`, `retrieval_eval`): **681 ≈ 5%**.
- Within the runtime share, dead/duplicate/demo removable now: ≈400–500 lines (≈3%).

**Roughly four-fifths of the source is genuinely load-bearing, the tests are real, and CI is green.** This is a *control* problem — two 1,000-line files, prose-heavy comments, hidden module state, five stores with a Session in three of them, a ledger re-read per call — far more than a *rot* problem.

---

## PHASE 5 — OPTIONS

### A) INCREMENTAL — stabilise in place

**First 5 steps**
1. Land or revert the 1,149 uncommitted lines (M0a) on a branch and let CI see them; the working tree has been un-CI'd for 41 days.
2. Apply the deletion list (§3.4) in one commit; prove behaviour-preservation with `tests/test_serde_golden.py` + the full suite.
3. Fix the reconnect race: keep the old `RuntimeSession` registered until its thread exits, or join it with a deadline before accepting a resume (`web_api.py:621-629, 595-607`).
4. Fix #119: raise a typed quota exception and re-raise it past `question_node` like `AccountingUnavailable` (`supervisor.py:278-284`; `llm.py:455-456`).
5. Bound inputs (`answer` max length, `max_elapsed_seconds` ceiling, `queue.Queue(maxsize=…)`), evict `completed_sessions` on export or TTL.

**Effort:** 6–10 focused days. **Breaks:** nothing user-visible; MiMo-bound fixtures in `conftest.py:16, 171-179` and `scripts/smoke_issue_0007.py`. **Gain:** both HIGH correctness bugs closed, ≈500 lines gone, CI green on what is actually on disk. **Right for:** the actual situation — one maintainer, a working product, and a first priority ("learn agentic systems") the current architecture serves.

### B) STRANGLER — keep running, rebuild module by module behind stable interfaces

**First 5 steps**
1. Freeze two seams: `LLMClient` (`llm.py:214-345`) and the Session wire format (`session_serde.py` + `tests/golden`). Add a `schema_version` key to the checkpoint state and both ledgers.
2. Extract `web_api.py` into `web/auth.py`, `web/session_runtime.py` (thread + queue + per-session lock + reconnect coordination), `web/app.py`; keep `web_api.app` as a lazy re-export so uvicorn/Docker/tests are untouched.
3. Replace the usage ledger's *read* path with a small SQLite table behind the same `record_usage`/`usage_for_day` API so rails become `SELECT SUM(...)`; keep the JSONL as an audit log; migrate by replay.
4. Split `cli.py` into `cli/session.py`, `cli/eval.py`, `cli/ops.py` with the argparse surface unchanged (`tests/test_cli.py` is the contract).
5. Collapse the two budget-rail mirrors into one `SessionDriver` that both `coach session` and the WS handler call.

**Effort:** 15–25 days, each step ships independently. **Breaks:** test import paths per split; nothing external (no known downstream importer). **Gain:** god files gone, one config system, the reconnect/eviction/race class becomes structurally impossible, and the storage seam is ready for accounts (M4). **Right for:** if you intend to run a real pilot for other people within a quarter.

### C) REBUILD — greenfield, port only KEEP parts

**First 5 steps**
1. New package; port `skill`, `rubric`, `language`, `bank`, `seeds`, `session_serde`, `microloop`, `evaluator` verbatim (none depends on the god files).
2. One `SessionStore` (SQLite, own schema: sessions, turns, submissions, skill_history, usage) replacing checkpoints + skill ledger + usage JSONL + export files.
3. One `SessionRunner` shared by `coach session` and the WS handler — no CLI/web mirror.
4. WS layer with per-session locking and bounded queues from day one.
5. `coach bench --k 3` against the ported Evaluator **before** anything else is trusted (ADR 0009).

**Effort:** 25–40 days to parity. **Dark period:** 3–5 weeks with no deployable build; existing checkpoints and the skill ledger do not carry over without a migration for a store you are abandoning. **You lose:** LangGraph's free checkpoint/resume; most of 13,800 test lines (they pin the code you would delete); the R-25 rail wording tuned against real failures; the 90-commit record of *why*. **You gain:** one storage model, one driver, no import-time side effects, and a codebase you wrote rather than inherited. **Right for:** only if the goal shifts to shipping a multi-user product and the learning value of the current architecture is spent.

### Recommendation

**A, then B's steps 2 and 5.** The evidence does not support a rewrite: ~84% of src is load-bearing, the algorithms are small and correct, the tests are real, CI is green, and each HIGH bug is a ~20-line fix. The damage is control damage, and splitting `web_api`/unifying the driver addresses it with no dark period.

**Strongest argument against this recommendation:** A and B both keep the *storage model* — five stores, a completed Session in three places, a skill ledger that cannot hold history, a JSONL every rail re-parses — and every remaining roadmap item (progress dashboard, accounts, durable per-turn ACKs, GH #83/#84 and M1/M3/M4 in `docs/issues/README.md`) is a storage change. If you know you will do M3/M4, every month on A is a month of code written against a schema you will replace, and C's `SessionStore` (step 2) is where the leverage actually is.

---

## PHASE 6 — WEEK ONE (regardless of option)

1. **Decide the uncommitted work.** Branch + commit (or stash) the M0a diff so CI runs it. Until then "CI green" describes code you are not running.
2. **Write the data model down.** Turn §2.2 into `docs/data-model.md`: five stores, exact shapes, which is authoritative for what. Add `schema_version` to the checkpoint state (`supervisor.py:160-188`) and both ledgers.
3. **Characterisation test: reconnect race.** Disconnect mid-question while a fake client sleeps, reconnect, resume; assert exactly one transcript item and one live thread. Fails today (`web_api.py:621-629`).
4. **Characterisation test: #119.** Fake `insufficient_quota` inside `run_micro_loop`; assert no `failed` item and unchanged `question_count`. Fails today (`supervisor.py:285-305`).
5. **Delete the dead list** (§3.4) in one commit; run `tests/test_serde_golden.py` and the suite; `git rm` the tracked web caches; add `web/.vite/` and `web/test-results/` to `.gitignore`.
6. **Freeze the wire format.** Add a golden covering a complete Session with panel, evidence-degraded, and failed items, so any key change is a visible diff — and sync `web/src/lib/types.ts` to it.
7. **Move `create_app()` out of import time** (lazy factory or `if __name__` guard) and delete the conftest workaround (`tests/conftest.py:18-38`).
8. **Bound the inputs and evict RAM.** `answer` length, `max_elapsed_seconds` ceiling, `Queue(maxsize=…)`, drop `completed_sessions[id]` after export or on TTL — ~30 lines, closes the MEDIUM class.
9. **Set the token now**, even on localhost (`COACH_AUTH_TOKEN`, `COACH_ALLOWED_ORIGINS`); remove the MiMo/Groq keys from `.env`; confirm `/api/health` reports `auth_required: true`.
10. **Purge the 51 fabricated rows** from `logs/usage-ledger.jsonl` (or archive it and start clean), and add a `source`/provenance field to token rows so tests can never again pass as spend.

---

## Appendix — open trackers (`gh`, 2026-09-14)

Open issues: #119 (quota → failed item, HIGH), #113 (replay carries no pack), #103/#96 (rubric anchors), #88/#87/#86/#85/#84/#83 (packs, voice spike, CV import, i18n, accounts, dashboard), #79/#72/#71 (eval), #60 (frontend redesign decision), #59 (blocker: onboarding ≤10 min truth-check). Open PRs: #104 (draft, anchors — "DO NOT MERGE"), #50 (frontend redesign, open since 2026-07-11). Last CI on `main`: 2026-08-04, green. ADR status: 0010 Accepted; 0011, 0014, and the 2026-07-19 addenda to 0001/0002 are **Proposed** (experiment-gated, not in code) — `docs/adr/0001-control-hierarchy.md:9`, `0002-bayesian-skill-state.md:11`, `0011:3`, `0014:3`.

---

## Execution log — branch `audit/stabilize-2026-09-14` (2026-09-14)

The recommendation (Option A plus Option B's step 5 in part) was executed on a branch off `main`; nothing was pushed. Every gate was run locally after each commit.

| Commit | What | Gates |
|---|---|---|
| `3ea1275` | Landed the 21 uncommitted M0a files and 4 untracked doc paths verbatim (Phase 6 item 1). | pytest 833 |
| `a576501` | This report. | — |
| `cf4e40e` | Web: `types.ts` synced with the wire format; panel verdict and evidence-degraded badge rendered; test fixture moved out of a `*.test` file (32 → 27 real tests); 4 missing CSS rules; tracked Vite/Playwright caches untracked and ignored. | eslint, tsc, vitest 27, vite build |
| `4f8cdf3` | **GH #119**: `ProviderQuotaExhausted` raised by the provider client, re-raised past every failure-isolation net, turned into a suspend with a resume path by both drivers (and an honest "start again" when it died on the Diagnostic). `schema_version` on checkpoints and `_meta` on the Skill ledger. Demo commands deleted; stop-reason and study-plan helpers deduped; ledger loaders folded; silent eval-tooling catches now log; `harness_passed([])` is red. | pytest 840, ruff, mypy; the session-summary and session-export goldens byte-identical — `tests/golden/replay-trajectory.json` gained the one new `schema_version` key, as the commit message says |
| `bd41425` | `docs/data-model.md` (every store, shape, writer, reader, retention, authority, versioning rule, duplications) and two glossary entries. | cites verified |
| `9bc067d` | **Reconnect race** closed (registration lives until the thread exits; reconnect joins the stale thread, one waiter per id, never overwrites an in-flight run); answer ≤ 20k chars, `max_elapsed_seconds` ≤ 4 h, answers queue bounded to 8 with a visible drop; `completed_sessions` bounded to 64 (export persisted first); `usage.reserve_questions` makes the cap check+record atomic and runs after the read-only budget rail; `web_api.app` built lazily so importing the module no longer reads `.env` or sweeps the checkpoint DB. | pytest 853, ruff, mypy, web/usage subset stable ×2 |
| `3f19c99` | MiMo provider and `disable_thinking` removed; `primary_provider` defaults to `openai`; test fake provider is Groq; two superseded scripts deleted; README/.env.example cleaned. | pytest 848 (853 − 5 MiMo-only tests), goldens byte-identical, vitest 27 |

Outside git: the 51 fabricated `mimo/test-model` rows were removed from `logs/usage-ledger.jsonl` (backup at `logs/usage-ledger.jsonl.bak-2026-09-14`); the Docker image was built from `9bc067d` via `git archive` (402 MB, lazy `app` resolves inside the container with the UI mounted) and then deleted — §1.6's UNKNOWN is closed.

### Corrections to this report found while executing it

1. §3.4 listed `_generate_follow_up_json` as fake-only. **Wrong**: demo mode (`DemoLLMClient` has no `chat_with_tools`) uses it. Kept.
2. §3.4 listed `TranscriptItem.to_dict` as having no caller. It has test callers (`tests/test_session_serde.py:35, 40`) and no production caller. Kept.
3. **§2.3**, not §2.2 row 1, cited `web_api.py:838` for the resume stream; the call is `_stream_graph`. (§2.2 row 1 cites `web_api.py:917-932` and is right.) §2.2 row 3 needed no correction either: `usage.py:287-331` is its row-*shape* cite and is accurate, and its `Written by` column already names `llm.py:497-507`. §2.2 row 5 already said "LIVE only with rag extras installed"; what is new is the container measurement — the image installs without `--extra rag`, so `auto` resolves to `memory` there. `docs/data-model.md` has the corrected cites.
4. **Phase 6 item 4**, not §3.2 row 2, set the #119 characterization target ("unchanged `question_count`"). That target was wrong: the test observed `3`, because the Session ran on to its cap after the fabricated `failed` item. §3.2 row 2 claimed only `question_count + 1` per quota event and was right.
5. **§3.2 row 5**, not §3.8, is where the ledger pollution is reported, and it already said "mitigated only in the *uncommitted* conftest" — nothing there was wrong. The update: that conftest is now committed and the 51 rows are purged. §3.8's "No test writes into the repo tree" was measured on the run and stands.

### Left for the user — not done, and why

- **`.env`** still holds `MIMO_*`/`GROQ_*` keys and no `COACH_AUTH_TOKEN` (Phase 6 item 9). Editing a secrets file was not assumed to be in scope.
- **GitHub**: nothing pushed; #119 not closed; PR #104 (draft) and #50 untouched. Push the branch, open a PR, let CI run on it, then close #119 from the PR.
- **Historical docs** (`docs/issues/*`, `docs/audits/*`, `docs/adr/*`, `docs/reference/*`, `CLAUDE.md`) keep their MiMo, `coach interview`/`coach evaluate`, and deleted-script mentions on purpose; a docs sweep is a separate decision.
- **Untested by design**: an exception escaping the socket loop after the parser guard is cancelled by the `finally` (code-reviewed) but not unit-tested, because the test client delivers pending frames lazily and the crash cannot be observed deterministically. `STALE_RUNTIME_JOIN_SECONDS` (120 s) is shorter than a full 4-attempt retry storm (~4 min); in that window a reconnect is told to retry.
- **Follow-ups worth a ticket**: `pytest-timeout` (a regression in the bounded-queue path would hang a receive loop instead of failing); Option B step 2 (split `web_api.py`) and step 3 (SQLite read path for the usage ledger, which every rail still re-parses per call) were not started; `ruff format` (not run by CI, which runs only `ruff check`) would reflow **18** pre-existing files at `60787d4` — 13 under `tests/`, 3 under `src/`, 2 under `scripts/` — and **24** after the M-0/M-1 fixes (15 tests, 7 src, 2 scripts); measured with `ruff 0.15.15`, the version pinned in `uv.lock`.
