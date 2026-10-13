# Data model — every store, its shape, and what it is authoritative for

References are `module.symbol`; where the code and this page disagree, the code wins. Terms: see `CONTEXT.md`
(**Skill ledger** ≠ **usage ledger**, see Naming below).

## 1. Durable stores

| # | Store | Default path → env / `Settings` → container | Writers | Readers | Retention | Authoritative for |
|---|---|---|---|---|---|---|
| 1 | LangGraph checkpoints (SQLite) | `.session-checkpoints.sqlite` → `COACH_CHECKPOINT_DB` / `checkpoint_db` (`config.Settings`) → `/app/state/session-checkpoints.sqlite` (`Dockerfile`, `docker-compose.yml`). CLI `--checkpoint-db` default ignores the env var (`cli_parser.build_parser`). | Every graph step via `SqliteSaver`: CLI `cli_session._cmd_session` → `cli_session._run_session_graph` (+ `update_state` of `started_at` on resume); web `web_session_driver._run_session_thread` → `web_session_driver._stream_graph` | CLI resume and overwrite check `supervisor.resumable_session_state` (from `cli_session._cmd_session`); web `web_session_driver._checkpoint_values` (a resume's `max_questions` and `language_mode`, the fresh-start refusal, `_release_unused_questions`, the export endpoint's fallback), then `initial_state = None` → `_stream_graph` on resume; TTL sweep `web_ops.prune_checkpoints` | TTL sweep once per `web_api.create_app` (`web_ops._sweep_checkpoints_at_startup`), i.e. on first `web_api.app` access (§2 import note): threads whose newest checkpoint is older than `checkpoint_ttl_seconds` (7 d default, `COACH_CHECKPOINT_TTL_SECONDS`, `0` disables — `config.Settings`). CLI never sweeps. | **The Session** — in-flight and completed state, resume, per-Session `skill_states`. |
| 2 | Skill ledger (JSON) | `.skill-ledger.json` → `COACH_LEDGER_DB` / `ledger_db` (`config.Settings`) → `/app/state/skill-ledger.json` (`Dockerfile`, `docker-compose.yml`). CLI `--ledger-db` defaults (`session`, `postmortem`) ignore the env var (`cli_parser.build_parser`). | `ledger.update_posteriors`: load, update and save in one critical section under `ledger._SAVE_LOCK` + `filelock.locked`, published by atomic rename (`filelock.atomic_write_text`). Called on COMPLETE by `ledger.save_measured_posteriors` from `web_session_driver._run_session_thread` and `cli_session._cmd_session`, which merges only the Skills `session_serde.measured_skill_states` returns over the carried decayed record; called directly by `postmortem.run_postmortem`. | `ledger.load_priors` from `web_session_driver._run_session_thread`, `cli_session._cmd_session` (no lock: publication is an atomic rename); `ledger.load_states` inside `ledger.update_posteriors` | None. One record per `candidate_id`, rewritten on every save (the carried decayed states plus the new evidence) with a fresh `completed_at`. | **Cross-session scoring memory** (decayed Beta priors, ADR 0006). Not any Session's result. |
| 3 | Usage ledger (JSONL) + `.unreconciled` sidecar | `<repo>/logs/usage-ledger.jsonl`, repo-anchored not CWD (`usage.DEFAULT_LEDGER_PATH`) → `COACH_USAGE_LEDGER` read via `os.environ`, **not** a `Settings` field (`usage.ledger_path`) → `/app/state/usage-ledger.jsonl` (`Dockerfile`, `docker-compose.yml`). Sidecar `<ledger>.unreconciled` (`usage.ledger_fault_path`). | `usage._append`: token rows `usage.record_usage` from `llm._OpenAICompatibleClient._record_usage`; `questions` via `usage.reserve_questions` (cap check + `usage.record_questions` in one step under `usage._LEDGER_WRITE_LOCK` + `filelock.locked`) from `web_session_driver._run_session_thread`; `questions_released` from `web_session_driver._release_unused_questions`; `session_run` via `usage.begin_session_run` from both drivers' fresh start and from `usage.extend_budget_for_resume`; `quota_exhausted` from `llm._OpenAICompatibleClient._create`; `quota_retry` via `usage.clear_run_rails_for_resume` from both drivers' resume; replayed rows from `usage.reconcile_accounting`. Sidecar: `usage._flush_faults`, rewritten whole on reconcile (`usage._rewrite_fault_sidecar`). | `usage._all_rows`; rails `usage.start_refusal_reason`, `usage.metered_command_refusal_reason`, `usage.question_cap_reason`, `usage.budget_stop_reason` (via `usage.session_budget_guard`); per-call gate `usage.accounting_gate` from `llm._OpenAICompatibleClient._create`; `coach usage` `cli._cmd_usage`; bench and forge preflight `cli._cmd_bench`, `cli._cmd_forge`; `--reconcile` → `usage.reconcile_accounting` | None. Append-only, never rotated. | **Spend** (day / run / identity) and the `insufficient_quota` latch — the only record; the `usage` module docstring records why the provider's daily allowance cannot be read from the API. |
| 4 | Exports (Markdown) | `data/exports/<safe-id>.md` → `COACH_EXPORTS_DIR` / `exports_dir` (`config.Settings`) → `/app/state/exports` (`Dockerfile`, `docker-compose.yml`). `<safe-id>` = the Session id if it matches `web_runtime.SAFE_SESSION_ID`, else its sha256 (`web_runtime.export_path`). CLI `--export-markdown <any path>` (`cli_session._cmd_session`). | `web_session_driver._persist_export` on COMPLETE → `exporter.export_session_markdown` (atomic rename); CLI `cli_session._cmd_session` | Export endpoint (`export_markdown` in `web_api.create_app`), only after a RAM miss; `scripts/retrieval_eval.py --harvest` (`retrieval_eval.harvest_lookup_calls`), an operator tool that also reads replay artifacts | None. | Nothing — a rendering of store 1. The export endpoint falls back to rendering the checkpoint when the file is missing, unreadable or empty; once `web_ops.prune_checkpoints` drops the thread, the file is the only copy it can serve (§5 item 1). |
| 5 | Chroma persist dir (concept notes) | `.chroma/` → `COACH_CONCEPT_PERSIST_DIR` / `concept_persist_dir`; kind `COACH_CONCEPT_STORE` / `concept_store="auto"` (`config.Settings`). The CLI's `--concept-store`/`--concept-persist-dir` and `ingest-concepts --persist-dir` defaults ignore both env vars (`cli_parser.build_parser`). Per-embedder subdir `<dir>/<model, "/"→"__">` (`concepts.embedder_persist_dir`): `BAAI__bge-small-en-v1.5`, `intfloat__multilingual-e5-small` (`concepts.BGE_SMALL_EN`, `concepts.E5_SMALL_MULTILINGUAL`), for web Sessions and `coach session` without `--pack`; `coach ingest-concepts` (`cli._cmd_ingest_concepts`) and `coach session --pack` write the persist dir root, which those Sessions do not read. No container override; the image installs without `--extra rag` (`Dockerfile`), so `auto` resolves to `memory` there (`concepts.resolve_concept_store_kind`). | `concepts.ChromaConceptStore.ingest` at Session start via `concepts.build_concept_store`: `web_session_driver._run_session_thread` always seeds (demo mode forces `memory`); `cli_session._cmd_session` seeds unless `--no-seed-concepts`, and with `--pack` builds the store with `seed=False` and ingests the pack's notes instead; `coach ingest-concepts` (`cli._cmd_ingest_concepts`). In the image (no `rag` extra) `auto` resolves to the memory store, and `coach ingest-concepts` or an explicit `chroma` kind raises `RuntimeError` from `concepts.ChromaConceptStore.create`. | `concepts.ChromaConceptStore.lookup` via `concepts.lookup_concept` — the Interviewer's tool | None. Derived; rebuilt by re-ingest. | Nothing — an index over the YAML shelf. |
| 6 | Server log file | None by default (stderr only) → `COACH_LOG_FILE`, env-only, **not** a `Settings` field: read once in the `web_api` module body → `web_ops.configure_session_logging` (`RotatingFileHandler(maxBytes=10 MiB, backupCount=5)`). Compose sets `/app/state/logs/coach-api.log` (`docker-compose.yml`); the Dockerfile does not. CLI `coach api --log-file` writes the env var before the import (`cli._cmd_api`). | Every `interview_coach` logger record, incl. the per-call `llm-call` trace (`llm._OpenAICompatibleClient._trace_call`). | Humans (`docs/deploy.md` §7). No code reads it. | 5 × 10 MiB rotation (`web_ops.configure_session_logging`). | Nothing — a support trace, never evidence. |

The Study Planner's resource index is not a store: `resources.build_resource_store` builds an in-memory
`resources.InMemoryResourceStore` (seeded from `resources.SEED_RESOURCES`) on every run.

### 1.0 Operator artifacts (not stores)

| Artifact | Path | Writer |
|---|---|---|
| Bench report | `docs/audits/calibration-bench-<date>.md`, or `logs/bench-screen-<date>.md` for an `--only` screen; `--out` overrides either | `cli._cmd_bench` |
| Forge review queue + report | `<--queue-dir>/review-queue-<date>.yaml` + `review-queue-<date>-report.md`; `--queue-dir` default `data/forge` (`cli_parser.build_parser`) | `forge.write_forge_outputs` from `cli._cmd_forge` |
| Replay artifact | caller-supplied path; JSON `{version, persona, ground_truth, pack, final_state}` (`replay.REPLAY_ARTIFACT_VERSION`); `pack` is the pack directory the Session ran from, or null for the built-in bank | `replay.dump_replay_artifact`; callers `scripts/dump_serde_goldens.py`, `tests/test_replay.py` |

Written once per run and never read by the product; reviewed or committed by hand.

### 1.1 Checkpoint shape (store 1)

Tables created by `SqliteSaver.setup` in `langgraph-checkpoint-sqlite` (version pinned in `uv.lock`): `checkpoints(thread_id,
checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint BLOB, metadata BLOB)` and `writes(thread_id,
checkpoint_ns, checkpoint_id, task_id, idx, channel, type, value BLOB)`. `thread_id` = Session id (`supervisor.session_config`).
Blobs are `msgpack` via `JsonPlusSerializer` (`langgraph.checkpoint.serde.jsonplus`); `channel_values` is one `SessionState`.

`SessionState` (`supervisor.SessionState`, all keys optional at the type level; written by
`supervisor.initial_session_state`):

| Key | Type | Notes |
|---|---|---|
| `schema_version` | `int` | `= supervisor.SESSION_SCHEMA_VERSION`, written by `initial_session_state` and stamped by every node (§4). Absent on `a576501` checkpoints (§4). |
| `session_id` | `str` | = `thread_id`. |
| `topic_plan` | `list[{skill, target_difficulty, rationale}]` | `diagnostic.TopicPlanEntry`. |
| `skill_states` | `dict[skill, {skill, alpha, beta}]` | `skill.SkillState.to_dict`. |
| `skill_metadata` | `dict[skill, {role_criticality, evidence_bar}]` | `supervisor.initial_session_state`. |
| `current_plan_index`, `next_skill`, `question_count`, `max_questions` | `int`, `str\|None`, `int`, `int` | |
| `max_elapsed_seconds`, `started_at` | `float`, `float` | Client type: `SessionState` in `web/src/lib/types.ts`. |
| `status`, `stop_reason` | `"active"\|"complete"`, `str\|None` | `supervisor.SessionStatus`. |
| `transcript` | `list[TranscriptItem]` | Below. |
| `supervisor_decisions` | `list[DecisionRecord]` | Below. |
| `study_plan`, `study_plan_error` | `StudyPlan.model_dump()\|None`, `str\|None` | `study_planner.StudyPlan`. |
| `candidate_id` | `str` | `""` = cold start. |
| `ledger_prior_mastery` | `dict[skill, float]` | Only present for a returning Candidate (`supervisor.initial_session_state`). |
| `language_mode` | `"en"\|"vn"\|"mixed"` | Absent pre-0024 → `.get(…, "en")`. |

Nested shapes (`session_serde` is the typed read view; writers are the truth):

| Shape | Keys | Writer |
|---|---|---|
| Transcript item (resolved) | `skill, plan_index, stop_reason, resolved_weighted_score, resolved_confidence, evidence_weight, skill_state, turns` | `session_serde.TranscriptItem.from_micro_loop` |
| Transcript item (failed) | same keys with zero sentinels, `turns: []`, plus `error` | `session_serde.TranscriptItem.failed` |
| Turn | `question, answer, is_follow_up, grounding_concept_id, grounding_concept_title, evaluation, trace` | `session_serde._dump_turn` |
| `evaluation` | `Evaluation.model_dump(mode="json")`: `dimensions, weighted_score, confidence, follow_up_recommended, follow_up_rationale, evidence_degraded, delivery_fixes, panel, trust` | `evaluator.Evaluation` |
| `trace` | `TurnTrace` fields (`microloop.TurnTrace`); `stop_reason` stored as its string value; `judge_unvalidated` present only when true | `session_serde._dump_turn` |
| Decision record | `SupervisorDecision` fields `action, reasoning, target_skill, target_plan_index, will_probe_skill` (`supervisor.SupervisorDecision`) + `after_question, from_plan_index, to_plan_index, deviation, llm_reasoning` | `supervisor._apply_supervisor_decision` |

### 1.2 Skill ledger shape (store 2)

`ledger` module docstring, `ledger._save_locked`; serialized `json.dumps(indent=2, sort_keys=True)`:

```json
{"_meta": {"schema_version": 1},
 "<candidate_id>": {"completed_at": 1757800000.0, "skills": {"<skill>": {"alpha": 2.5, "beta": 1.5}}}}
```

`_meta` is written on every save (`ledger._save_locked`, `ledger.LEDGER_SCHEMA_VERSION`); files last saved before that
write lack it (§4). Readers subscript `data[candidate_id]` (`ledger._load_candidate`), so `_meta` is never read as a
Candidate; anything that iterates the top level must skip keys starting with `_`.

### 1.3 Usage ledger rows (store 3)

Every row carries `ts` (UTC ISO, seconds — `usage._now_ts`). Readers identify a kind by `kind` or by `prompt_tokens`,
never by "which keys are present" (`usage` module docstring); unknown rows and unparseable lines are skipped
(`usage._all_rows`).

| Kind | Row | Writer |
|---|---|---|
| token row (no `kind`) | `{ts, provider, model, prompt_tokens, completion_tokens, session?}` — `session` only inside `usage.session_scope` | `usage.record_usage` |
| `session_run` | `{ts, kind, session, baseline}` | `usage.begin_session_run` |
| `questions` | `{ts, kind, identity, questions}` — identity = `sha256(token)[:16]` or `"anonymous"` (`usage.token_identity`) | `usage.record_questions`, only via `usage.reserve_questions` |
| `questions_released` | `{ts, kind, identity, questions, session?}` — a compensating row; `usage.questions_today` subtracts it from the day's reservations, floored at 0 | `usage.record_questions_released`, from `web_session_driver._release_unused_questions` |
| `quota_exhausted` | `{ts, kind, provider}` — `provider` ∈ `ProviderName = groq\|openai\|zenmux` (`config.ProviderName`; `primary_provider` default `openai`, `config.Settings`) | `usage.record_quota_exhausted`, from `llm._OpenAICompatibleClient._create` |
| `quota_retry` | `{ts, kind, provider, session?}` — with `session` the grant clears the latch only for that Session (`usage.quota_exhausted_today`); without it, for everyone | `usage.clear_quota_exhausted`, via `usage.clear_run_rails_for_resume` |
| sidecar `accounting_fault` | `{ts, id, kind, row, billed, ledger, error, entry}` — `entry` is the unwritten row. A billed call with no usable token count parks `row: "tokens_unmeasured"` with `provider, model, session?` and no `entry` | `usage._latch_fault`, `usage.record_unmeasured_call` |

A row replayed by `usage.reconcile_accounting` (via `usage._reconcile_held_rows`) carries the parked fault's `id` as an
extra `fault` key; `usage._replayed_fault_ids` reads it so a second reconcile cannot replay the same row.

### 1.4 Sidecar and lock files

Never read as data. `<skill-ledger>.lock` and `<usage-ledger>.lock` are the flock targets of `filelock.locked`;
created once, never unlinked. One `<checkpoint-db>.<sha256(session id)[:16]>.lock` per `coach session` id
(`cli_session._checkpoint_lock_target`, `filelock.claimed`) keeps a second CLI process off a thread; never unlinked,
and not touched by `web_ops.prune_checkpoints`. `<checkpoint-db>-wal`/`-shm` are SQLite's own (`SqliteSaver.setup`
sets `journal_mode=WAL`). `filelock.atomic_write_text` stages `.<name>.*.tmp` beside its target
and renames it over the target, or unlinks it on a write error.

## 2. Volatile stores

| Store | Where | Written | Read | Bound |
|---|---|---|---|---|
| `WebApiState.completed_sessions: dict[str, dict]` | `web_runtime` | `web_runtime._remember_completed` from `web_session_driver._run_session_thread`, on any final state | export endpoint (`export_markdown` in `web_api.create_app`) | `web_runtime.MAX_COMPLETED_SESSIONS_IN_MEMORY = 64`; oldest-first eviction under `lock`. On COMPLETE the Markdown (store 4) is written first (`web_session_driver._persist_export`), so an evicted id is still exportable. |
| `WebApiState.runtimes: dict[str, RuntimeSession]` | `web_runtime` | registered by `web_runtime._claim_session_id`; popped by whichever of socket-close (`session_socket`'s `finally` in `web_api.create_app`) / thread-exit (`web_session_driver._run_session_thread`'s `finally`) happens last | duplicate-socket refusal in `web_runtime._claim_session_id` | One entry per Session id. A closed socket whose thread is still inside a provider call keeps the entry until that thread exits. |
| `WebApiState.waiting: set[str]` | `web_runtime` | `add`/`discard` in `web_runtime._claim_session_id` | `web_runtime._claim_session_id` — a second waiter is refused (`_STILL_FINISHING`) | One waiter per Session id and at most `web_runtime.MAX_CONCURRENT_STALE_JOINS = 8` in total (past it the reconnect is refused with `_TOO_MANY_JOINS`); each join is capped at `web_runtime.STALE_RUNTIME_JOIN_SECONDS = 120` and runs on `join_pool`. |
| `WebApiState.join_pool: ThreadPoolExecutor` | `web_runtime` | threads spawned on demand by the stale-run join in `web_runtime._claim_session_id` | — | `max_workers = MAX_CONCURRENT_STALE_JOINS`; shut down without waiting by `web_api.create_app`'s lifespan. |
| `WebApiState.lock: threading.Lock` | `web_runtime` | — | guards every read/write of `runtimes`, `waiting` and the `completed_sessions` eviction | Process-wide. |
| `RuntimeSession` per socket: `answers`, `cancelled`, `thread`, `socket_closed`, `run_finished`, `turn_seq`, `awaiting_turn_id` | `web_runtime` | `answers.put_nowait` and `awaiting_turn_id = None` in `session_socket` (`web_api.create_app`); `socket_closed = True` in its `finally`; `run_finished = True` in `_run_session_thread`'s `finally`; `turn_seq`/`awaiting_turn_id` by `RuntimeSession.begin_turn`; queue/event/flag reset per run by `RuntimeSession.reset_run_state` | `web_runtime.QueueCandidate`; `RuntimeSession.run_in_flight`; the answer check in `session_socket` | `answers` is `queue.Queue(maxsize=ANSWER_QUEUE_MAXSIZE)` (= 8); overflow drops the answer with a recoverable `session_error`. An answer is queued only when its `turn_id` equals `awaiting_turn_id`; any other is refused the same way. `turn_seq` is never reset per run. |
| `telemetry._counters` | `telemetry` | `telemetry.incr` outside any `usage.session_scope` (bench, forge) | `telemetry.snapshot` / `telemetry.delta` from `cli._cmd_bench` and per judge call in `evaluator.evaluate` | Process lifetime; not persisted (`telemetry` module docstring). |
| `telemetry._session_counters`, `telemetry._trace` (`ContextVar`s) | `telemetry` | a fresh `Counter` per `usage.session_scope` (`telemetry.session_counters`); `_trace` by `telemetry.trace_scope` / `telemetry.traced_role` | `telemetry.incr` / `snapshot` inside a Session; `_trace` by `telemetry.trace_fields` for the `llm-call` line | Per **context**, like `usage._SESSION_ID`. |
| `usage._SESSION_ID` (`ContextVar[str]`) | `usage` | set/reset by `usage.session_scope` | `usage.record_usage`, `usage.record_unmeasured_call`, `usage.current_session_id` (the `llm-call` line) | Per **context**, not per process: langgraph copies it into every sync node. |
| `usage._FAULTS`, `usage._PROVEN_WRITABLE` | `usage` | `_FAULTS` (under `usage._FAULT_LOCK`): `usage._latch_fault`, `usage.record_unmeasured_call`, `usage._flush_faults`, `usage._rewrite_fault_sidecar`, `usage.reset_accounting_state`. `_PROVEN_WRITABLE`: `.add` in `usage.accounting_gate`, `.discard` in `usage._reconcile_held_rows`, `.clear` in `usage.reset_accounting_state` | `usage._parked_faults`, `usage.accounting_gate` | Faults also parked to the sidecar; probe successes are process-local. |
| `usage._LEDGER_WRITE_LOCK` + the flock on `<usage-ledger>.lock` (`filelock.locked`) | `usage` | — | `usage.reserve_questions` (cap check + `questions` row) and `usage.reconcile_accounting` | Serialises both read-modify-writes across threads and processes; the reservation itself is a ledger row (store 3). |
| `llm._BREAKERS` (guarded by `llm._BREAKER_LOCK`) | `llm` | `LLMRouter._record_success`, `LLMRouter._record_failure` | `LLMRouter.breaker_is_open` | Process lifetime; shared by every Session in the process. |

**Single-process assumption.** All of these are process-local (the `ContextVar`s narrower still). The server refuses
`--workers`/`WEB_CONCURRENCY` > 1 at import (`web_ops.guard_single_worker`, called in the `web_api` module body;
`docs/deploy.md` §6). A second process would miss reconnects, contend for the checkpoint SQLite file, and run its own
breakers, thread locks and unparked faults. What stays shared is on disk: the ledgers' read-modify-writes take
`filelock.locked`, and every process reads the parked faults and the `quota_exhausted` latch from store 3.

**Import-time effects.** Importing `interview_coach.web_api` runs only `web_ops.guard_single_worker()` and
`web_ops.configure_session_logging(COACH_LOG_FILE)`. `web_api.app` is built lazily by the module `__getattr__` on first
attribute access, so the import itself does not read `.env` (`config.load_settings`), open or sweep the checkpoint DB
(`web_ops._sweep_checkpoints_at_startup`), or mount static files (`web_api._mount_static_ui`); those run in
`web_api.create_app` when uvicorn or a test first touches `app`.

## 3. Browser keys

| Key | Storage | Code | Purpose |
|---|---|---|---|
| `coach.sessionId` | `localStorage` | `web/src/lib/sessionId.ts`: `STORAGE_KEY`, read `readStored`, write `writeStored`, rotate `rotateSessionId`; `loadSessionId` used in `App.tsx`, `rotateSessionId` in `components/SetupPanel.tsx` | The Session id sent as the WebSocket path segment; persisted so reload → resume. |
| `coach.authToken` | `sessionStorage` | `web/src/lib/authToken.ts`: `STORAGE_KEY`, read `loadAuthToken`, write `saveAuthToken`; used in `App.tsx` and `lib/api.ts` | Shared secret for the `auth` frame and the export Bearer header; tab-scoped by design. |

## 4. Versioning

> **Enforcement.** Both markers are written *and read*. The checkpoint is stamped by every graph node, and
> `supervisor.require_supported_session_version` gates every entry into the graph (the `_versioned` wrapper in
> `supervisor.build_session_graph`): a checkpoint carrying a version this build does not know raises
> `UnsupportedSessionVersion` before any node runs, so the refusal can never be recorded as a `failed` question.
> Readers outside the graph do not call it: `web_session_driver._checkpoint_values` (the export endpoint's fallback,
> `_release_unused_questions`, a resume's `max_questions` and `language_mode`) and `supervisor.resumable_session_state`
> (`cli_session._cmd_session`'s resume and overwrite checks) read a newer checkpoint ungated. The Skill ledger is
> guarded by `ledger._ledger_version_is_supported`, which returns a bool rather than raising — both loaders and the
> save path (`ledger._save_locked`) are contractually forbidden to raise — so a newer ledger degrades to a cold start
> with an ERROR log and, critically, is **not rewritten**: an old build must never downgrade `_meta` and clobber a
> shape it cannot read.

| Store | Marker | Rule |
|---|---|---|
| Checkpoint (store 1) | `SessionState["schema_version"] = SESSION_SCHEMA_VERSION` (`= 1`, `supervisor.SESSION_SCHEMA_VERSION`), set in `supervisor.initial_session_state` | Absent on `a576501` and older checkpoints, so the reader uses `.get("schema_version", 0)` and never subscripts — the field is declared under `total=False` and carries that warning. A pre-stamp checkpoint is upgraded in place on its first resume, because every node stamps it. |
| Skill ledger (store 2) | top-level `"_meta": {"schema_version": LEDGER_SCHEMA_VERSION}` (`= 1`, `ledger.LEDGER_SCHEMA_VERSION`; written by `ledger._save_locked`) | Absent on files last saved before the write → version 0. `_meta` is not a Candidate record. |
| Usage ledger (store 3) | none | Append-only rows already identified by `kind`/keys, and every reader tolerates unknown rows (`usage._all_rows`). A version would belong in a header row; `usage._append` writes none. |
| Exports (store 4), Chroma (store 5), log (store 6) | none | Renderings / derived indexes / trace; regenerate, do not migrate. |

A reader that meets a version **higher** than it knows must refuse loudly (raise, log the path and both versions) and
must not guess, default, or partially load. A reader that meets a **lower** version applies the documented `.get`
defaults for that version. Bumping a version is a wire change: update this file, the client types
(`web/src/lib/types.ts`), and the goldens in `tests/golden/` (regenerate with `scripts/dump_serde_goldens.py`;
`tests/test_serde_golden.py` checks them) in the same change.

## 5. Duplicated sources of truth

| # | Duplication | Which copy wins |
|---|---|---|
| 1 | A completed Session exists in the checkpoint (store 1), RAM (bounded by `web_runtime.MAX_COMPLETED_SESSIONS_IN_MEMORY`) and Markdown (`web_session_driver._persist_export`); the export endpoint (`export_markdown` in `web_api.create_app`) reads RAM, then the file, then renders a COMPLETE checkpoint through `web_session_driver._checkpoint_values` when the file is missing, unreadable or empty. | The checkpoint. RAM and the file are caches; once `web_ops.prune_checkpoints` drops the thread, the file is the only copy. |
| 2 | Skill posteriors live in each checkpoint's `skill_states` (every canonical Skill, unprobed self-claim seeds included) and in the Skill ledger, which holds one record per Candidate: the carried decayed states merged per Skill with what the latest Session measured (`ledger.save_measured_posteriors` → `ledger.update_posteriors`), with no per-Session history (#127). | Per Session, the checkpoint. The Skill ledger wins only for the *carried prior* (decayed memory, ADR 0006); history for a dashboard must come from checkpoints or explicit snapshots, never from the ledger. |
| 3 | Provider retry constants restated in `usage` (`usage.STRUCTURED_ATTEMPTS`, `JUDGE_ATTEMPTS`, `NATIVE_TOOL_ATTEMPTS`, `PANEL_ESCALATIONS_PER_QUESTION`) to avoid an import cycle; pinned by `tests/test_usage.py::test_the_call_model_matches_the_constants_it_restates`. | The owning modules (`evaluator`, `interviewer`, `llm`). `usage` is a derived worst-case model and keeps the pin test. |
| 4 | `llm_reasoning` duplicates `reasoning` in every decision record (`supervisor._apply_supervisor_decision`; admitted in `session_serde.DecisionRecord`). | `reasoning`. `llm_reasoning` is a compatibility alias to drop with the next `schema_version` bump. |
| 5 | Client/server Session shape: `web/src/lib/types.ts` re-declares the serialized shape that `supervisor` and `session_serde` write. | The server's serialized shape (§1.1). The client type is a declared subset of it, updated in the same change as any wire change (§4). |

Related, not a duplication but a split: two paths bypass `Settings` — the usage ledger (`usage.ledger_path`) and the
server log (`COACH_LOG_FILE`, read in the `web_api` module body) — and the CLI's argparse defaults
(`cli_parser.build_parser`) for `--checkpoint-db`, `--ledger-db`, `--concept-store`, `--concept-persist-dir` and
`ingest-concepts --persist-dir` ignore the env vars, so `Settings` places those stores on the web path only. Three
mechanisms (`Settings`, bare `os.environ`, argparse defaults) can disagree about where a store lives.

## 6. Naming

"Ledger" names two unrelated files. Use **Skill ledger** for `ledger.py` / `--ledger-db` / `COACH_LEDGER_DB` /
`.skill-ledger.json` (Candidate priors) and **usage ledger** for `usage.py` / `COACH_USAGE_LEDGER` /
`logs/usage-ledger.jsonl` (token spend). Never say "the ledger" unqualified; `COACH_LEDGER_DB` is the Skill ledger.
