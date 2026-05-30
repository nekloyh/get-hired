# Study Planner + session export

**Type:** AFK

## What to build

The end-of-session output. When the Supervisor ends the **Session**, a Study Planner agent reads the final Skill states, retrieves matching learning materials from a Chroma `resources` collection, and produces a `StudyPlan` (prioritized topics, mapped resources, a 2-week schedule, milestones, a readiness estimate). Also add a session exporter that writes the whole run — transcript, evaluations, and the plan — to Markdown as a portfolio artifact. Resource matching is genuine semantic retrieval (a fuzzy gap → relevant materials); the planner must map to real catalog entries, not invent URLs.

## Acceptance criteria

- [ ] At session end a schema-valid StudyPlan is produced from the final Skill states
- [ ] Prioritized topics reflect the weakest, most role-critical Skills
- [ ] Resources come from the `resources` collection (no invented URLs)
- [ ] The full session exports to a readable Markdown file

## Blocked by

- 0010 (a complete session to plan from)
