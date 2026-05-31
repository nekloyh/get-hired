# Diagnostic → Topic Plan + seeded priors

**Type:** AFK

## What to build

The planner-executor entry point. A **Diagnostic** agent reads the Candidate profile (claimed skills, self-assessment, target role/companies) and produces a **Topic Plan** — an ordered list of (Skill, target difficulty, rationale). It also seeds the Beta **Skill** priors per `ADR 0002`: priors are *weak* by default (a self-claim sets only the starting question difficulty, never our confidence), cross-skill correlations apply *only to the initial prior*, and **Role criticality** (from a hand-built `target_role` + `target_companies` table) flexes prior strength and the early-termination evidence bar — never the prior mean.

## Acceptance criteria

- [x] Diagnostic produces a Topic Plan of (Skill, difficulty, rationale) entries
- [x] Seeded priors are weak — within an answer or two of direct evidence, the prior is overridden
- [x] Correlations affect only the initial prior; no cross-crediting on later evaluations
- [x] A Skill the role marks must-have gets a weaker prior + higher evidence bar than a peripheral Skill
- [x] Role criticality never shifts the prior mean (verified: changing the target role changes strength/bar, not the starting mastery estimate)

## Blocked by

- 0002 (Beta skill-state model the priors seed)
