# Study Planner + session export

**Type:** AFK

## What to build

The end-of-session output. When the Supervisor ends the **Session**, a Study Planner agent reads the final Skill states, retrieves matching learning materials from a Chroma `resources` collection, and produces a `StudyPlan` (prioritized topics, mapped resources, a 2-week schedule, milestones, a readiness estimate). Also add a session exporter that writes the whole run — transcript, evaluations, and the plan — to Markdown as a portfolio artifact. Resource matching is genuine semantic retrieval (a fuzzy gap → relevant materials); the planner must map to real catalog entries, not invent URLs.

## Acceptance criteria

- [x] At session end a schema-valid StudyPlan is produced from the final Skill states
- [x] Prioritized topics reflect the weakest, most role-critical Skills
- [x] Resources come from the `resources` collection (no invented URLs)
- [x] The full session exports to a readable Markdown file

## Done

- Added `interview_coach.resources` with seed learning materials, an in-memory test store, and a
  Chroma-backed `resources` collection using the same BGE small embedding path as concepts.
- Added `interview_coach.study_planner`: a single-shot Study Planner that ranks final Skill states
  by weakness + Role criticality, retrieves resource candidates in Python, and asks the LLM for a
  schema-valid two-week plan using only retrieved catalog IDs.
- Wired a final `study_plan` LangGraph node after Supervisor completion so completed Sessions return
  `state["study_plan"]`.
- Added `interview_coach.exporter` and `coach session --export-markdown` for a full Markdown
  artifact containing transcript, evaluations, Supervisor decisions, and the Study Plan.
- Added `coach ingest-resources` and `coach session --resource-store chroma` support for persistent
  resource retrieval.

## Verified

- `uv run pytest` -> 104 passed, 7 deselected (includes 4 new regression tests from audit).
- `uv run ruff check .` -> all checks passed.
- Real-MiMo audit: 21/21 checks passed across in-memory and Chroma/BGE retrieval paths, valid
  first-try with 0 retries; no invented URLs in any run.
- `pytest -m live` -> interviewer native tool-call + full LangGraph session pass on real MiMo.

## Hardened during audit

Two "one LLM glitch sinks the whole run" patterns were found and fixed in the same commit:

- **Planner node crash** (`study_plan_node`): a malformed plan surviving two attempts now degrades to
  `study_plan=None` + `study_plan_error` marker; the completed Session still reaches END.
- **Garbled tool name** (MiMo transient, issue 0010 residual): the native tool round-trip retries
  once on `UnknownToolCall`; if it persists, `FollowUpUnavailable` signals the micro-loop to keep
  the last score and resolve under `StopReason.FOLLOW_UP_UNAVAILABLE`. `ToolCallingUnsupported`
  (genuine integration failure) still fails loudly. ADR 0003 addendum documents the third category.

## Status

**Closed — no MVP blocker.** All four acceptance criteria verified against real MiMo. The two
resilience gaps found during the audit (planner crash + garbled tool name) were fixed in the same
commit (`4a78c42` on `dev`).

## Blocked by

- 0010 (a complete session to plan from)
