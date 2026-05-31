# Issue 0007 Audit — RAG Concepts + Tool-Using Interviewer

Date: 2026-05-31

## Scope

Audited the slice-0007 path against ADR 0003:

- the Interviewer is the only component with a tool loop;
- the tool is `lookup_concept`;
- Follow-up generation uses provider-level `tool_calls` when the client supports tools;
- MiMo thinking is disabled on the tool loop;
- retrieved concept notes ground the final Follow-up.

## Result

Pass for the offline native-tool smoke path.

The earlier JSON tool-plan fallback was too permissive for full 0007 verification because a native
provider could decline/fail the forced tool call and still appear green. The current behavior is:

- MiMo and Groq both advertise native tool-call support.
- Native tool-call providers fail loudly if they do not emit `tool_calls`.
- JSON tool-plan fallback is retained only for non-native fake/dummy clients.
- The smoke verifies that `reasoning_content` is not replayed into the multi-turn tool history.

## Commands Run

```bash
uv run python scripts/smoke_issue_0007.py
uv run pytest tests/test_interviewer.py tests/test_microloop.py tests/test_llm.py
uv run pytest -m rag
```

Smoke output:

```text
issue 0007 smoke: PASS
- native provider tool calls: lookup_concept
- MiMo thinking disabled on both tool-loop requests
- reasoning_content not replayed
- grounded concept: ml_fundamentals_l2_regularization
- follow-up: What mechanism connects the L2 penalty to lower variance?
```

## Chroma/BGE Integration Check

The Chroma + `BAAI/bge-small-en-v1.5` integration test is present behind the `rag` marker and is
deselected from the default suite because it requires optional dependencies and model download.
It has been verified in this environment with the optional `rag` extra installed:

```bash
uv sync --extra rag
uv run pytest -m rag
```

Current environment result with optional extras: `1 passed, 80 deselected`.
