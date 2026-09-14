# Data model — every store, its shape, and what it is authoritative for

Verified against the working tree of branch `audit/stabilize-2026-09-14` (after slice 1; commit hash to be recorded at
merge). Line refs are `path:line`; when the code moves, the code wins. Terms: see `CONTEXT.md` (**Skill ledger** ≠
**usage ledger**, see Naming below).

## 1. Durable stores

| # | Store | Default path → env / `Settings` → container | Writers | Readers | Retention | Authoritative for |
|---|---|---|---|---|---|---|
| 1 | LangGraph checkpoints (SQLite) | `.session-checkpoints.sqlite` → `COACH_CHECKPOINT_DB` / `checkpoint_db` (`config.py:116`) → `/app/state/session-checkpoints.sqlite` (`Dockerfile:62`, `docker-compose.yml:14`). CLI `--checkpoint-db` default ignores the env var (`cli.py:907-911`). | Every graph step via `SqliteSaver`: CLI `cli.py:391` + stream loop `cli.py:273` (+ `update_state` on resume `cli.py:413`); web `web_api.py:831` + `web_api.py:993` | CLI resume `cli.py:405` → `supervisor.py:199-208`; web resume `web_api.py:930-945` (reads `language_mode`, `max_questions`: `:769-772, :961`) then `initial_state=None` `web_api.py:840` → `web_api.py:993`; TTL sweep `web_api.py:430-471` | TTL sweep at `create_app` only (`web_api.py:658`, `:665-675`): threads whose newest checkpoint is older than `checkpoint_ttl_seconds` (7 d default, `COACH_CHECKPOINT_TTL_SECONDS`, `0` disables — `config.py:130`). CLI never sweeps. | **The Session** — in-flight and completed state, resume, per-Session `skill_states`. |
| 2 | Skill ledger (JSON) | `.skill-ledger.json` → `COACH_LEDGER_DB` / `ledger_db` (`config.py:117`) → `/app/state/skill-ledger.json` (`Dockerfile:63`, `docker-compose.yml:15`). CLI `--ledger-db` defaults ignore the env var (`cli.py:918-922`, `:1049-1053`). | `save_posteriors` (`ledger.py:165-223`; lock `:56`, atomic rename `:216`) from web COMPLETE `web_api.py:884-889`, CLI `cli.py:522-524`, post-mortem `postmortem.py:186` | `load_priors` (`ledger.py:131-143`) from `web_api.py:854`, `cli.py:463`; `load_states` (`ledger.py:146-162`) from `postmortem.py:180` | None. One record per `candidate_id`, replaced on every save. | **Cross-session scoring memory** (decayed Beta priors, ADR 0006). Not any Session's result. |
| 3 | Usage ledger (JSONL) + `.unreconciled` sidecar | `<repo>/logs/usage-ledger.jsonl`, repo-anchored not CWD (`usage.py:63`) → `COACH_USAGE_LEDGER` read via `os.environ`, **not** a `Settings` field (`usage.py:77-78`) → `/app/state/usage-ledger.jsonl` (`Dockerfile:65`, `docker-compose.yml:22`). Sidecar `<ledger>.unreconciled` (`usage.py:84-90`). | `_append` (`usage.py:423-429`): token rows `llm.py:502-512`; `questions` `web_api.py:788`; `session_run` via `begin_session_run` (`usage.py:779-782`) from `web_api.py:848`, `cli.py:462`; `quota_exhausted` `llm.py:458`; `quota_retry` via `clear_run_rails_for_resume` (`usage.py:1036-1037`) from `web_api.py:794`, `cli.py:425`. Sidecar: `_flush_faults` `usage.py:371-392`, rewritten whole on reconcile `usage.py:603-625`. | `_all_rows` (`usage.py:635-655`); rails `usage.py:823, 846, 871, 896, 957`; per-call gate `llm.py:437` → `accounting_gate` `usage.py:532-551`; `coach usage` `cli.py:707-760`; bench preflight `cli.py:658-668`; forge `cli.py:772-776`; `--reconcile` `cli.py:710-715` → `usage.py:554` | None. Append-only, never rotated. | **Spend** (day / run / identity) and the `insufficient_quota` latch — the only record; the provider API exposes no daily quota (`usage.py:3-5`). |
| 4 | Exports (Markdown) | `data/exports/<safe-id>.md` → `COACH_EXPORTS_DIR` / `exports_dir` (`config.py:118`, `web_api.py:130`) → `/app/state/exports` (`Dockerfile:64`, `docker-compose.yml:16`). `<safe-id>` = the Session id if it matches `SAFE_SESSION_ID` (`web_api.py:134`), else its sha256 (`web_api.py:295-306`). CLI `--export-markdown <any path>` (`cli.py:1012`). | `_persist_export` on COMPLETE (`web_api.py:883`, `:964-974`) → `exporter.py:14-19`; CLI `cli.py:526-527` | Export endpoint, only after a RAM miss (`web_api.py:652-656`) | None. | Nothing — a rendering of #1. After a restart it is the only copy the export endpoint can serve (§5 item 1). |
| 5 | Chroma persist dir (concept notes) | `.chroma/` → `COACH_CONCEPT_PERSIST_DIR` / `concept_persist_dir` (`config.py:126`); kind `concept_store="auto"` (`config.py:125`). Per-embedder subdir `<dir>/<model, "/"→"__">` (`concepts.py:309-320`): `BAAI__bge-small-en-v1.5`, `intfloat__multilingual-e5-small` (`concepts.py:23, 28`). No container override; the image installs without `--extra rag` (`Dockerfile:42`), so `auto` resolves to `memory` there (`concepts.py:323-331`). | `ChromaConceptStore.ingest` (`concepts.py:219`) via `build_concept_store(seed=True)` at every Session start: web `web_api.py:808-813`, CLI `_cmd_session` `cli.py:350-361`; `coach ingest-concepts` (`cli.py:819-821`). Chroma writes are local-only — in the container every one of these calls lands in the memory store. | `lookup` (`concepts.py:233-261`) via `lookup_concept` (`concepts.py:374-383`) — the Interviewer's tool | None. Derived; rebuilt by re-ingest. | Nothing — an index over the YAML shelf. |
| 6 | Chroma resource store (Study Planner) | No `Settings` field; CLI-only: `--resource-store` (default `memory`) / `--resource-persist-dir` (default `.chroma`, `cli.py:996-1005`, `:1073-1081`) → `build_resource_store` (`resources.py:391-406`) → `ChromaResourceStore.create` → `chromadb.PersistentClient(path=persist_dir)` (`resources.py:140-171`), collection `RESOURCE_COLLECTION = "resources"` (`resources.py:22`). Web hardcodes `memory` (`web_api.py:814`). **Caveat for #5:** the default root is the same `.chroma` and this store is **not** namespaced per embedder, so `--resource-store=chroma` writes a second collection into the concept store's root directory. | `ingest` (`resources.py:190`) via `build_resource_store(seed=True)` `cli.py:364-368`, `:565-568`; `coach ingest-resources` (`cli.py:828-831`, `--persist-dir` default `.chroma` `:1174`) | `search_resources` (`resources.py:409`) from `study_planner.py:244` | None. Derived. | Nothing — an index over `SEED_RESOURCES`. |
| 7 | Server log file | None by default (stderr only) → `COACH_LOG_FILE`, env-only, **not** a `Settings` field: read once at import `web_api.py:700` → `configure_session_logging` (`web_api.py:390-427`; `RotatingFileHandler(maxBytes=10 MiB, backupCount=5)` `:420`). Compose sets `/app/state/logs/coach-api.log` (`docker-compose.yml:26`); the Dockerfile does not. CLI `coach api --log-file` writes the env var before the import (`cli.py:846-847`; flag `:1181-1188`). | Every `interview_coach` logger record, incl. the per-call `llm-call` trace (`_trace_call`, `llm.py:481-500`). | Humans (`docs/deploy.md:159`). No code reads it. | 5 × 10 MiB rotation (`web_api.py:420`). | Nothing — a support trace, never evidence. |

### 1.0 Operator artifacts (not stores)

| Artifact | Path | Writer |
|---|---|---|
| Bench report | `docs/audits/calibration-bench-<date>.md` (or `--out`, `cli.py:1121`) | `_cmd_bench` `cli.py:686-688` |
| Forge review queue + report | `<--queue-dir>/review-queue-<date>.yaml` + `review-queue-<date>-report.md`; `--queue-dir` default `data/forge` (`cli.py:1147`) | `write_forge_outputs` (`forge.py:620-629`) from `_cmd_forge` `cli.py:795-796` |
| Replay artifact | caller-supplied path; JSON `{version, persona, ground_truth, final_state}` | `dump_replay_artifact` (`replay.py:158-169`); callers `scripts/dump_serde_goldens.py:100`, `tests/test_replay.py:145` |

Written once per run and never read by the product; reviewed or committed by hand.

### 1.1 Checkpoint shape (#1)

Tables from `langgraph-checkpoint-sqlite` (`langgraph/checkpoint/sqlite/__init__.py:142-162`): `checkpoints(thread_id,
checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint BLOB, metadata BLOB)` and `writes(thread_id,
checkpoint_ns, checkpoint_id, task_id, idx, channel, type, value BLOB)`. `thread_id` = Session id (`supervisor.py:194-196`).
Blobs are `msgpack` via `JsonPlusSerializer` (`serde/jsonplus.py:267`); `channel_values` is one `SessionState`.

`SessionState` (`supervisor.py:75-94`, all keys optional at the type level; written by `initial_session_state`
`supervisor.py:138-191`):

| Key | Type | Notes |
|---|---|---|
| `schema_version` | `int` | `= SESSION_SCHEMA_VERSION` (`supervisor.py:59`), written at `:163`. Absent on `a576501` checkpoints (§4). |
| `session_id` | `str` | = `thread_id`. |
| `topic_plan` | `list[{skill, target_difficulty, rationale}]` | `diagnostic.py:74-79`. |
| `skill_states` | `dict[skill, {skill, alpha, beta}]` | `skill.py:123-125`. |
| `skill_metadata` | `dict[skill, {role_criticality, evidence_bar}]` | `supervisor.py:167-173`. |
| `current_plan_index`, `next_skill`, `question_count`, `max_questions` | `int`, `str\|None`, `int`, `int` | |
| `max_elapsed_seconds`, `started_at` | `float`, `float` | Client type: `web/src/lib/types.ts:183-184`. |
| `status`, `stop_reason` | `"active"\|"complete"`, `str\|None` | `supervisor.py:62-64`. |
| `transcript` | `list[TranscriptItem]` | Below. |
| `supervisor_decisions` | `list[DecisionRecord]` | Below. |
| `study_plan`, `study_plan_error` | `StudyPlan.model_dump()\|None`, `str\|None` | `study_planner.py:103`. |
| `candidate_id` | `str` | `""` = cold start. |
| `ledger_prior_mastery` | `dict[skill, float]` | Only present for a returning Candidate (`supervisor.py:189-190`). |
| `language_mode` | `"en"\|"vn"\|"mixed"` | Absent pre-0024 → `.get(…, "en")`. |

Nested shapes (`session_serde.py` is the typed read view; writers are the truth):

| Shape | Keys | Writer |
|---|---|---|
| Transcript item (resolved) | `skill, plan_index, stop_reason, resolved_weighted_score, resolved_confidence, evidence_weight, skill_state, turns` | `session_serde.py:130-143` |
| Transcript item (failed) | same keys with zero sentinels, `turns: []`, plus `error` | `session_serde.py:146-164` |
| Turn | `question, answer, is_follow_up, grounding_concept_id, grounding_concept_title, evaluation, trace` | `session_serde.py:211-223` |
| `evaluation` | `Evaluation.model_dump(mode="json")`: `dimensions, weighted_score, confidence, follow_up_recommended, follow_up_rationale, evidence_degraded, delivery_fixes, self_critique, panel, trust` | `evaluator.py:169-198` |
| `trace` | `TurnTrace` fields (`microloop.py:155-177`); `stop_reason` stored as its string value | `session_serde.py:211-214` |
| Decision record | `SupervisorDecision` fields `action, reasoning, target_skill, target_plan_index, will_probe_skill` (`supervisor.py:98-109`) + `after_question, from_plan_index, to_plan_index, deviation, llm_reasoning` | `supervisor.py:466-472` |

### 1.2 Skill ledger shape (#2)

`ledger.py:14-15`, `:193-197`; serialized `json.dumps(indent=2, sort_keys=True)` (`:211`):

```json
{"_meta": {"schema_version": 1},
 "<candidate_id>": {"completed_at": 1757800000.0, "skills": {"<skill>": {"alpha": 2.5, "beta": 1.5}}}}
```

`_meta` is written on every save (`ledger.py:193`, `LEDGER_SCHEMA_VERSION` `:38`); files last saved before that write
lack it (§4). Readers subscript `data[candidate_id]` (`ledger.py:108`), so `_meta` is never read as a Candidate;
anything that iterates the top level must skip keys starting with `_`.

### 1.3 Usage ledger rows (#3)

Every row carries `ts` (UTC ISO, seconds — `usage.py:277-278`). Readers identify a kind by `kind` or by `prompt_tokens`,
never by "which keys are present" (`usage.py:18-24`); unknown rows and unparseable lines are skipped (`usage.py:635-655`).

| Kind | Row | Writer |
|---|---|---|
| token row (no `kind`) | `{ts, provider, model, prompt_tokens, completion_tokens, session?}` — `session` only inside `session_scope` (`usage.py:302-305`) | `usage.py:281-306` |
| `session_run` | `{ts, kind, session, baseline}` | `usage.py:779-782` |
| `questions` | `{ts, kind, identity, questions}` — identity = `sha256(token)[:16]` or `"anonymous"` (`usage.py:668-680`) | `usage.py:309-318` |
| `quota_exhausted` / `quota_retry` | `{ts, kind, provider}` | `usage.py:321-339` |
| sidecar `accounting_fault` | `{ts, kind, row, billed, ledger, error, entry}` — `entry` is the unwritten row | `_latch_fault` `usage.py:395-410` |

## 2. Volatile stores

| Store | Where | Written | Read | Bound |
|---|---|---|---|---|
| `WebApiState.completed_sessions: dict[str, dict]` | `web_api.py:291` | `web_api.py:879` on any final state | export endpoint `web_api.py:644` | Never evicted. |
| `WebApiState.runtimes: dict[str, RuntimeSession]` | `web_api.py:292` | `web_api.py:572`; popped `:630-631` | duplicate-socket check `web_api.py:562` | One entry per live socket. |
| `telemetry._counters` | `telemetry.py:18` | `incr` | bench snapshot/delta | Process lifetime; not persisted (`telemetry.py:10`). |
| `usage._SESSION_ID` (`ContextVar[str]`) | `usage.py:264` | set/reset by `session_scope` (`usage.py:268-274`) | `record_usage` (`usage.py:302`) | Per **context**, not per process: langgraph copies it into every sync node. |
| `usage._FAULTS`, `usage._PROVEN_WRITABLE` | `usage.py:358`, `:361` | `_FAULTS`: `_latch_fault` `:410`, `_flush_faults` `:392`, `_rewrite_fault_sidecar` `:607, :625`, `reset_accounting_state` `:631`. `_PROVEN_WRITABLE`: `accounting_gate` `.add` `:550`, `reconcile_accounting` `.discard` `:594`, `reset_accounting_state` `.clear` `:632` | `_parked_faults` `:447-448`, `accounting_gate` `:542-546` | Faults also parked to the sidecar; probe successes are process-local. |
| `LLMRouter._breakers` | `llm.py:699` | `_record_success` `:716-724`, `_record_failure` `:726-734` | `breaker_is_open` `:711-714` | Process lifetime. |

**Single-process assumption.** All six are process-local (the `ContextVar` narrower still). The server refuses
`--workers`/`WEB_CONCURRENCY` > 1 (`web_api.py:374-387`; `docs/deploy.md:101`). A second process would miss reconnects,
double-write the SQLite file, and run its own breakers and fault latch.

## 3. Browser keys

| Key | Storage | Code | Purpose |
|---|---|---|---|
| `coach.sessionId` | `localStorage` | `web/src/lib/sessionId.ts:11`, read `:25-34`, write `:36-42`, rotate `:50-54`; used `App.tsx:24` | The Session id sent as the WebSocket path segment; persisted so reload → resume. |
| `coach.authToken` | `sessionStorage` | `web/src/lib/authToken.ts:11`, read `:13-21`, write `:23-30`; used `App.tsx:43, 259` | Shared secret for the `auth` frame and the export Bearer header; tab-scoped by design. |

## 4. Versioning

| Store | Marker | Rule |
|---|---|---|
| Checkpoint (#1) | `SessionState["schema_version"] = SESSION_SCHEMA_VERSION` (`= 1`, `supervisor.py:59`), set in `initial_session_state` (`supervisor.py:163`) | Absent on `a576501` and older checkpoints → readers use `.get("schema_version", 0)`; never subscript (`supervisor.py:76`). |
| Skill ledger (#2) | top-level `"_meta": {"schema_version": LEDGER_SCHEMA_VERSION}` (`= 1`, `ledger.py:38`; written `:193`) | Absent on files last saved before the write → version 0. `_meta` is not a Candidate record. |
| Usage ledger (#3) | none | Append-only rows already identified by `kind`/keys, and every reader tolerates unknown rows (`usage.py:635-655`). A version belongs in a header row; deferred. |
| Exports (#4), Chroma (#5, #6), log (#7) | none | Renderings / derived indexes / trace; regenerate, do not migrate. |

A reader that meets a version **higher** than it knows must refuse loudly (raise, log the path and both versions) and
must not guess, default, or partially load. A reader that meets a **lower** version applies the documented `.get`
defaults for that version. Bumping a version is a wire change: update this file, the client types
(`web/src/lib/types.ts`), and the goldens in `tests/test_serde_golden.py` in the same change.

## 5. Duplicated sources of truth

| # | Duplication | Which copy wins |
|---|---|---|
| 1 | A completed Session exists in the checkpoint (#1), RAM (`web_api.py:879`) and Markdown (`web_api.py:883`); the export endpoint reads RAM then the file, never the checkpoint (`web_api.py:644-656`). | The checkpoint. RAM and the file are caches; the endpoint should render from #1 and fall back to the file only when the thread was pruned. |
| 2 | Skill posteriors live in each checkpoint's `skill_states` and in the Skill ledger, which keeps only the last snapshot (`ledger.py:193-197`; `docs/issues/README.md:55`). | Per Session, the checkpoint. The Skill ledger wins only for the *carried prior* (decayed memory, ADR 0006); history for a dashboard must come from checkpoints or explicit snapshots, never from the ledger. |
| 3 | Provider retry constants restated in `usage.py:157-172` to avoid an import cycle (`usage.py:147-150`); pinned by `tests/test_usage.py:165`. | The owning modules (`evaluator`, `interviewer`, `llm`). `usage.py` is a derived worst-case model and keeps the pin test. |
| 4 | `llm_reasoning` duplicates `reasoning` in every decision record (`supervisor.py:471`; admitted `session_serde.py:189-192`). | `reasoning`. `llm_reasoning` is a compatibility alias to drop with the next `schema_version` bump. |
| 5 | **Resolved.** Stop-reason display names have one source: `microloop.display_stop_reason` (`microloop.py:141-151`), imported by `exporter.py:9` (used `:101, :109`) and `cli.py:65-70` (used `:193, :209, :239, :327`). | `microloop.py`. Kept here as the record that `cli.py` and `exporter.py` each had a copy at `a576501`. |
| 6 | **Resolved.** Client/server state drift: at `a576501` the client type declared none of `max_elapsed_seconds`, `started_at`, `candidate_id`, `ledger_prior_mastery` (`supervisor.py:85-86, 93-94`), `Evaluation.evidence_degraded/panel/trust` (`evaluator.py:179, 197-198`), `TranscriptItem.evidence_weight/error` (`session_serde.py:106, 109`), `SupervisorDecision.will_probe_skill` (`supervisor.py:109`). `web/src/lib/types.ts` now declares them (`:85, 94-95`, `:114, 117`, `:159`, `:174`, `:183-184`, `:191-192`). | The server's serialized shape (§1.1). The client type is a declared subset of it. |

Related, not a duplication but a split: two paths bypass `Settings` — the usage ledger (`usage.py:78`) and the server log
(`web_api.py:700`, `COACH_LOG_FILE`) — while the other store paths go through it, and the CLI's argparse defaults for
`--checkpoint-db`/`--ledger-db` ignore the env vars. Three mechanisms (`Settings`, bare `os.environ`, argparse defaults)
can disagree about where a store lives.

## 6. Naming

"Ledger" names two unrelated files. Use **Skill ledger** for `ledger.py` / `--ledger-db` / `COACH_LEDGER_DB` /
`.skill-ledger.json` (Candidate priors) and **usage ledger** for `usage.py` / `COACH_USAGE_LEDGER` /
`logs/usage-ledger.jsonl` (token spend). Never say "the ledger" unqualified; `COACH_LEDGER_DB` is the Skill ledger.
