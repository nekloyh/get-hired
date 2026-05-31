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

- `uv run pytest` -> 100 passed, 7 deselected.
- `uv run ruff check .` -> all checks passed.

## Blocked by

- 0010 (a complete session to plan from)
