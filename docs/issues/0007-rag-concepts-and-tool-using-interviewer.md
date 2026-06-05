# RAG concepts + tool-using ReAct Interviewer

**Type:** AFK

## What to build

Give the **Interviewer** its one tool and turn it into a genuine ReAct agent (see `ADR 0003` — tool-calling is confined to the Interviewer). Stand up a Chroma `concepts` collection embedded with `bge-small-en-v1.5`, an ingest path, and a `lookup_concept` tool. When a **Follow-up** is needed, the Interviewer reasons, calls `lookup_concept` to fetch the most semantically relevant concept note, and crafts a targeted follow-up grounded in it — replacing the plain-LLM follow-up from slice 0005. MiMo thinking mode is disabled for this tool-using agent (the quirk quarantine).

Baseline dense retrieval only (HyDE/hybrid/rerank are deferred). Ships with a small seed concept-set; breadth is slice 0008.

## Acceptance criteria

### Implemented

- [x] `concepts` collection ingests and is queryable by semantic similarity
- [x] The Interviewer calls `lookup_concept` while generating a follow-up and the retrieved note demonstrably informs the question
- [x] Tool-calling exists only in the Interviewer; all other agents remain single-shot with injected state
- [x] With MiMo as primary, the tool-using loop runs without the `reasoning_content` 400 error
- [x] Vietnamese concept notes are reached via Skill/metadata, not relied on through semantic search under the English embedder
- [x] Follow-up trace records the `lookup_concept` query/filter and retrieved concept hit for Session debugging

### Verified live / integration

- [x] Chroma ingest/query integration passes (`uv run pytest -m rag -ra`, verified 2026-05-31)
- [x] MiMo native tool-call path passes (`uv run pytest -m live -ra`, verified 2026-05-31)
- [x] Offline native-tool smoke passes (`uv run python scripts/smoke_issue_0007.py`, verified 2026-05-31)

## Blocked by

- 0005 (the micro-loop the tool plugs into)

## Status

**Closed.** Acceptance criteria are implemented and covered.
