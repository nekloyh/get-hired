# Agent Design & Implementation

## Quick Links

- **Issue Drafts** (current roadmap): `/docs/issues/` — 13 prioritized implementation tickets
- **ADRs** (architectural decisions): `/docs/adr/` — reasoning on control flow, tool use, state, orchestration
- **Context** (domain language): `/CONTEXT.md` — shared terminology and domain model

## Reference

- **MVP v1 Blueprint** (2-day scope, tech stack choices): `/docs/reference/MVP_v1_2day.md` ⚠️ archived
- **MVP v2 Roadmap** (V1 critique + 5-day improvement plan): `/docs/reference/MVP_v2.md` ⚠️ archived

---

## For Implementers

Start with the **issue drafts in `/docs/issues/`**, which decompose the roadmap into concrete tasks. Each issue includes acceptance criteria and links to relevant design docs.

When designing agents:
1. Check `/CONTEXT.md` for canonical skill taxonomy, company profiles, and interaction patterns
2. Reference `/docs/adr/` for precedent on state management, tool scope, and orchestration strategy
3. Use the rubric patterns from MVP v1 blueprint (§12.1 of archive) for evaluation scoring

When prioritizing:
- **High signal, low effort:** LLM-driven supervisor (replaces if/else routing), multi-judge evaluator (production evaluation pattern)
- **Long-term strength:** Bayesian skill state (correlations), hybrid RAG (2025 standard), long-term memory (cross-session adaptation)
- **MVP scope:** Stick to V1 2-day plan; V2 upgrades are future work
