---
banner: |
  ⚠️ **Superseded by issue drafts** — This document is archived for reference.
  For current roadmap and implementation details, see `/docs/issues/` and `/CLAUDE.md`.
---

# Adaptive AI/ML Interview Coach Agent — 2-Day MVP Build Blueprint

**TL;DR**
- Build a **LangGraph-orchestrated multi-agent interview coach** powered by **MiMo-V2.5-Pro** (via OpenAI-compatible endpoint `https://api.xiaomimimo.com/v1`), with **ChromaDB** for RAG over a curated AI/ML interview question bank, **SQLite** for session state, **Streamlit** for the demo UI, and a thin **LLMClient abstraction** that fails over to **Groq Llama-3.3-70B** when your MiMo free tokens expire (2026-06-03).
- Recruiter signal lives in **agentic discipline, not features**: ship a supervisor → diagnostic → RAG-driven selector → ReAct interviewer → rubric evaluator with reflection → skill-state updater → study planner graph, with explicit Pydantic v2 state, structured-JSON evaluation, and an evaluator-optimizer self-critique loop.
- For Vietnamese AI companies (VinAI, FPT AI, Zalo/VNG, Viettel AI), tailor the demo to a **fresh-graduate Vietnamese candidate targeting MLE** with rubrics covering ML fundamentals, MLOps, system design, and Vietnamese-NLP specifics (PhoBERT, VnCoreNLP word segmentation, ranking) — the four screen-out skills these companies actually test.

---

## Key Findings

1. **MiMo-V2.5-Pro is the right primary** — 1M-context Mixture-of-Experts (1.02T total, 42B active), OpenAI-compatible at `https://api.xiaomimimo.com/v1`, full function-calling support, `response_format` json_object mode, and `tools=[{type:"function",...}]` accepted natively. Pricing: $1/M input (cache miss) / $0.20/M input (cache hit) / $3/M output at ≤256K prompts; rate limit 100 RPM / 10M TPM. One **hard gotcha**: in thinking mode + multi-turn tool calls, you must persist `reasoning_content` on every assistant message or you get a 400. Mitigation: disable thinking mode in tool-using agents via `extra_body={"thinking":{"type":"disabled"}}`.
2. **LangGraph beats hand-rolled in 2 days, period** — you get `StateGraph`, `SqliteSaver` checkpoint persistence, `Command(goto=..., update=...)` supervisor routing, and `draw_mermaid_png()` diagram export for the README. Plus "LangGraph" is the keyword recruiters search for. Don't lean on `create_supervisor` — write the supervisor explicitly so the diagram shows your custom routing logic.
3. **ChromaDB wins the vector-DB decision** for this MVP. Chroma's v1.0 (Rust-core) release post states *"local Chroma is 4× faster for common write and query workflows, thanks to a new core written in Rust"* (benchmarked on 1M OpenAI-1536-dim embeddings on a 12-core M2 MacBook), with individual breakdowns of "3-5× faster writes" and "3-5× faster queries." Embedded persistent client, no server process, default LangChain integration. Qdrant is faster at scale but adds Docker; FAISS lacks metadata filtering; LanceDB is less battle-tested with LangChain; sqlite-vec is too new for recruiter signal.
4. **Groq Llama-3.3-70B is the right primary fallback** — per Groq's official rate-limits documentation, the free tier offers 30 RPM / 6,000 TPM / 1,000 RPD on `llama-3.3-70b-versatile`, and Groq's LPU benchmark docs cite sub-200ms time-to-first-token (3–10× faster than standard GPU inference). Same OpenAI schema, no `reasoning_content` quirk, no credit card. Gemini 2.5 Flash (per Google's official pricing page: 1,500 RPD / 1M TPM / 15 RPM, no card, no expiration) has more daily volume, but its 15 RPM cap is hostile to a multi-call-per-turn agent — keep Gemini as tertiary for the Study Planner only (one call per session).
5. **Embeddings: BAAI/bge-small-en-v1.5.** Per the model card: 33.4M parameters, 384-dim, ranked 1st on the MTEB and C-MTEB benchmarks at v1 release (August 2023). Runs on CPU in tens of milliseconds per document. BGE-M3 (1024-dim, 100+ languages) is the right *future-work* upgrade for fuller Vietnamese coverage; ship small-en-v1.5 first.
6. **Vietnamese hiring context matters.** VinAI (Vingroup subsidiary, 200+ AI researchers, CES 2024 Innovation Award for MirrorSense, deployed in 80,000+ vehicles) values research depth and computer-vision/NLP papers. FPT Software/FPT AI ($2.47B 2024 revenue, $200M NVIDIA-chip AI Factory, targeting 6,000 AI engineers by 2028) values enterprise MLOps, OCR, and reliability. VNG/Zalo (77.6M monthly active users on Zalo, 300+ AI engineers, ~2B messages/day, AI Avatar +140% over growth target in 2024) values Vietnamese NLP and ranking/recommendation. Viettel AI values telecom-scale voice/CV. Encode this directly into the diagnostic agent's bias and the study planner's "company-specific notes" section.
7. **Six agentic patterns must be named explicitly** in code and README: supervisor/router, ReAct, planner-executor, evaluator-optimizer (reflection), structured output, tool use. These are the literal keywords recruiters grep CVs for.

---

## Details

### 1. MVP Scope — Cut Hard, Keep the Agentic Skeleton

**Keep (this is what recruiters look at):**
1. Profile intake → automatic skill diagnosis from claimed experience.
2. Adaptive question selection driven by RAG over a YAML question bank (≥40 questions across 7 topics).
3. Multi-turn ReAct interviewer that asks clarifying / follow-up questions when answers are weak.
4. Rubric-based evaluator returning **structured JSON** scores per dimension (correctness, depth, communication, system-thinking, MLOps awareness).
5. Persistent `SkillState` (mastery 0-1, confidence, evidence count), updated after every evaluation.
6. Final readiness report + personalized study plan (prioritized topics, resources, weekly schedule, milestones).
7. SQLite-backed session replay (resume any session by ID).
8. LangGraph state-machine diagram exported as PNG for the README.
9. LLM router with primary (MiMo) + Groq fallback + structured-output retry logic.
10. ≥3 unit tests + 1 evaluator-quality smoke test (golden answers).

**Cut without mercy:** authentication, audio/TTS, video/webcam, frontend polish, cloud deployment, fine-tuning, DB migrations, multi-language UI.

**Why this scope wins:** every cut item is a checkbox; everything kept demonstrates a *distinct agentic engineering concept*.

---

### 2. Agentic Workflow Design — Patterns to Demonstrate

Architect the system to deliberately showcase **six named agentic patterns**, and call them out in the README:

| Pattern | Where it lives |
|---|---|
| **Supervisor / Router** | `graph/supervisor.py` — explicit `Command(goto=..., update=...)` based on `current_state` and evaluator confidence |
| **ReAct (Reason+Act)** | `agents/interviewer.py` uses `lookup_concept` (RAG) and `get_skill_state` tools to decide follow-up vs. move on |
| **Planner-Executor** | Diagnostic produces a `target_topic_plan`; Selector executes one step per turn |
| **Evaluator-Optimizer (Reflection)** | Evaluator emits `confidence`; if `<0.6`, supervisor routes through `SelfCritique` node that re-prompts MiMo with the answer + critique |
| **Structured Output** | Every machine-consumable LLM call uses Pydantic schemas + `response_format={"type":"json_object"}` + `parse_with_retry` |
| **Tool Use** | `rag_search`, `get_skill_state`, `update_skill_state`, each with typed Pydantic I/O |

---

### 3. LangGraph vs. Hand-Rolled — **Use LangGraph**

Reasoning: (a) LangChain's own 2025 guidance recommends LangGraph for all new agent builds, and "LangGraph" appears in Vietnamese AI job descriptions — give recruiters the keyword. (b) You get `StateGraph`, `MessagesState`, `SqliteSaver`, conditional edges, and `Command(goto=..., update=...)` for free; hand-rolling means writing a buggy mini-framework instead of an agent. (c) `graph.get_graph().draw_mermaid_png()` produces the README architecture diagram in one line. (d) MiMo plugs in cleanly via `ChatOpenAI(model="mimo-v2.5-pro", base_url=...)` — but for tool-using nodes, bypass `ChatOpenAI` and call MiMo directly so you can manage `reasoning_content` (see §13).

The one trap: don't over-use prebuilts. Build the supervisor as an explicit `StateGraph` node, not `create_supervisor`.

---

### 4. Backend Architecture — Final Stack

| Concern | Choice | One-line justification |
|---|---|---|
| Runtime | **Python 3.11+** | Pydantic v2 perf, exception groups, structural matching |
| Primary LLM | **MiMo-V2.5-Pro** via `https://api.xiaomimimo.com/v1` | Free tokens until 2026-06-03; 1M-context MoE; OpenAI-compat |
| Fallback LLM | **Groq `llama-3.3-70b-versatile`** | Free 30 RPM/1000 RPD, sub-200ms TTFT, same OpenAI schema |
| LLM SDK | `openai>=1.40` | Single client class, swap `base_url` |
| Agent framework | **LangGraph 0.2+** with `SqliteSaver` | Stateful, persisted, resumable |
| Schemas | **Pydantic v2** | `model_validate_json`, native JSON-schema export |
| Question bank | **YAML** under `data/questions/*.yaml` | Hand-editable, diff-friendly |
| Session state | **SQLite** via LangGraph `SqliteSaver` | Single file, durable, replayable |
| UI | **Streamlit** (+ Typer CLI for tests/demo) | Working interactive demo in ~120 LOC |
| Vector DB | **ChromaDB** (embedded persistent) | See §8 |
| Embeddings | **`BAAI/bge-small-en-v1.5`** | 33.4M params, 384-dim, MTEB-#1 at v1 release |
| Config | `pydantic-settings` + `.env` | One place for keys/base URLs |
| Logging | `structlog` JSON to `logs/agent.jsonl` | Per-node trace for the demo |
| Testing | `pytest` + `pytest-asyncio` | Three smoke tests + one golden-answer evaluator test |

**Canonical MiMo client snippet:**

```python
# llm/mimo_client.py
import os
from openai import OpenAI

def make_mimo_client() -> OpenAI:
    return OpenAI(
        api_key=os.environ["MIMO_API_KEY"],
        base_url="https://api.xiaomimimo.com/v1",
        timeout=60.0,
        max_retries=2,
    )
```

---

### 5. Agent / Module Design

The orchestrator is a LangGraph `StateGraph` whose shared state is `InterviewSession`. Each node mutates state via `Command(update=..., goto=...)`.

- **Profile Agent.** Inputs: raw user-entered profile + form. Calls MiMo with a normalization prompt that returns a cleaned `CandidateProfile` JSON (skills mapped to canonical taxonomy: `ml_fundamentals`, `deep_learning`, `nlp`, `cv`, `mlops`, `system_design`, `vietnamese_nlp`). Output: validated `CandidateProfile`. Runs once at session start.
- **Diagnostic Agent.** Reads `CandidateProfile` + initial `SkillState`. Calls MiMo to produce a planner-style `target_topic_plan: List[(skill, target_difficulty, rationale)]` of length 6–8, biased toward weak claimed skills and the target role's must-haves (MLE → MLOps + system design weighted heavier). This is **planner-executor**.
- **Question Selector (RAG).** Builds a hybrid query (`topic + skill_level + Vietnamese-context flag`), queries Chroma over indexed question bank + concept docs, returns top-3 candidates, then calls MiMo to *choose* one based on `SkillState` (avoiding repeats, calibrating difficulty).
- **Interviewer Agent (ReAct).** Built with `create_react_agent(model=mimo, tools=[rag_lookup, get_skill_state])`. Asks the question, accepts the answer, decides via tool calls whether to probe deeper, hint, or move on. Limited to 2 follow-ups per question to prevent runaway loops.
- **Evaluator Agent.** Sends question + rubric + transcript chunk + expected concepts to MiMo with a strict JSON-schema prompt. Returns `EvaluationResult` with per-rubric scores (1–5), verbatim evidence quotes, strengths, weaknesses, and `confidence`. If `confidence<0.6`, supervisor routes to `SelfCritique` (evaluator-optimizer).
- **Skill State Updater.** Pure Python, no LLM. Bayesian-flavored update: `new_mastery = (old_mastery × evidence_count + normalized_score) / (evidence_count + 1)`; confidence grows with `evidence_count`. Detects `weak_areas` when any sub-rubric scores <2/5 twice in a row. This deliberate no-LLM node demonstrates judgment about when *not* to call the model — recruiters notice.
- **Study Planner Agent.** At session end (≥6 questions or user terminates), reads final `SkillState`, retrieves curated learning resources from the RAG index, calls MiMo for a `StudyPlan` (prioritized topics, mapped resources, 2-week schedule, milestones). Exports to Markdown.
- **Supervisor / Orchestrator.** `StateGraph` entrypoint reads `current_state` and routes:

```
START → PROFILE → DIAGNOSTIC → SELECT_QUESTION → INTERVIEW → EVALUATE
                                       ↑                          │
                                       │              (conf≥0.6)  ▼
                                       └── UPDATE_STATE ◀──────── EVALUATE
                                                │   ▲ (conf<0.6) SELF_CRITIQUE↺
                                                ▼
                                    (n≥6 or terminate?) → STUDY_PLAN → END
```

State flows through a single `InterviewSession` Pydantic object; LangGraph persists checkpoints to SQLite after every node, so the demo can resume mid-interview.

---

### 6. Pydantic v2 Schemas (drop-in)

```python
# schemas.py
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
from uuid import uuid4

class Skill(str, Enum):
    ML_FUNDAMENTALS = "ml_fundamentals"
    DEEP_LEARNING   = "deep_learning"
    NLP             = "nlp"
    CV              = "cv"
    MLOPS           = "mlops"
    SYSTEM_DESIGN   = "system_design"
    VIETNAMESE_NLP  = "vietnamese_nlp"

class Difficulty(str, Enum):
    EASY = "easy"; MEDIUM = "medium"; HARD = "hard"

class QuestionType(str, Enum):
    CONCEPT = "concept"; CODING = "coding"
    SYSTEM_DESIGN = "system_design"; SCENARIO = "scenario"

class SessionState(str, Enum):
    INIT = "init"; DIAGNOSED = "diagnosed"; INTERVIEWING = "interviewing"
    EVALUATING = "evaluating"; PLANNING = "planning"; DONE = "done"

class CandidateProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(default_factory=lambda: f"cand_{uuid4().hex[:8]}")
    name: str
    background: str
    target_role: Literal["MLE","AI_Engineer","Research_Engineer","Data_Scientist"]
    target_companies: list[str] = Field(default_factory=list)
    years_experience: float = 0.0
    claimed_skills: list[Skill] = Field(default_factory=list)
    self_assessment: dict[Skill, int] = Field(default_factory=dict)
    notes: str | None = None

class RubricDimension(BaseModel):
    name: Literal["correctness","depth","communication","system_thinking","mlops_awareness"]
    weight: float = Field(ge=0.0, le=1.0)
    description: str

class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    topic: Skill
    difficulty: Difficulty
    type: QuestionType
    prompt: str
    expected_concepts: list[str]
    rubric: list[RubricDimension]
    follow_ups: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    embedding_metadata: dict = Field(default_factory=dict)
    vietnamese_context: bool = False

class RubricScore(BaseModel):
    dimension: str
    score: int = Field(ge=1, le=5)
    rationale: str
    evidence: str   # verbatim quote from candidate's answer

class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str
    rubric_scores: list[RubricScore]
    weighted_score: float = Field(ge=0.0, le=1.0)
    strengths: list[str]
    weaknesses: list[str]
    missing_concepts: list[str]
    follow_up_recommended: bool
    confidence: float = Field(ge=0.0, le=1.0)
    evaluator_model: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class SkillState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill: Skill
    mastery: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_count: int = 0
    weak_areas: list[str] = Field(default_factory=list)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

class TranscriptTurn(BaseModel):
    role: Literal["interviewer","candidate","system"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)

class InterviewSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(default_factory=lambda: f"sess_{uuid4().hex[:8]}")
    candidate_id: str
    candidate_profile: CandidateProfile
    current_state: SessionState = SessionState.INIT
    target_topic_plan: list[tuple[Skill, Difficulty, str]] = Field(default_factory=list)
    questions_asked: list[Question] = Field(default_factory=list)
    evaluations: list[EvaluationResult] = Field(default_factory=list)
    skill_states: dict[Skill, SkillState] = Field(default_factory=dict)
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

class StudyResource(BaseModel):
    title: str
    url: str | None = None
    type: Literal["book_chapter","blog","paper","course","video","github_repo"]
    skill: Skill
    estimated_hours: float

class StudyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    prioritized_topics: list[tuple[Skill, str]]
    resources: list[StudyResource]
    weekly_schedule: dict[int, list[str]]
    milestones: list[str]
    readiness_estimate: float = Field(ge=0.0, le=1.0)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
```

---

### 7. MiMo Prompt Templates

All system prompts start with the recommended MiMo persona stub and demand JSON where applicable. Pair every JSON request with `response_format={"type":"json_object"}` and embed the Pydantic schema in the prompt body.

**7.1 Skill Diagnosis**
```text
[SYSTEM]
You are MiMo, an AI assistant developed by Xiaomi, acting as a senior AI/ML hiring
manager at a top Vietnamese AI company (VinAI / FPT AI / Zalo AI / VNG / Viettel AI).
Produce a calibrated diagnostic plan. Be skeptical — candidates over-claim skills.
Return ONLY a single JSON object matching the schema. No prose, no markdown, no fences.

[USER]
Candidate profile: {candidate_profile_json}
Canonical skills: ml_fundamentals, deep_learning, nlp, cv, mlops, system_design, vietnamese_nlp
Target role: {target_role}
Target companies: {target_companies}

Company emphases:
- VinAI publishes papers (research depth); FPT AI = enterprise OCR/chatbots (MLOps);
- Zalo/VNG = Vietnamese NLP + recommendation; Viettel AI = telecom voice + CV at scale.

Produce 6-8 entries biased toward (a) claimed skills the candidate seems weak in given
their background, (b) skills the target role must have, (c) Vietnamese-context skills.

Return JSON:
{
  "target_topic_plan": [{"skill":"...","target_difficulty":"easy|medium|hard","rationale":"..."}],
  "initial_skill_estimates": {"ml_fundamentals": 0.5, ...},
  "diagnostic_notes": "..."
}
```

**7.2 Rubric-Based Answer Evaluation**
```text
[SYSTEM]
You are a strict but fair senior AI/ML interviewer scoring conservatively.
- 1: wrong/empty  - 2: partial recall  - 3: correct fundamentals, no depth
- 4: correct + nuanced, minor gaps  - 5: textbook + production awareness
Always cite VERBATIM evidence from the candidate's answer (or "[no evidence]").
If overall confidence is below 0.6, say so — orchestrator triggers self-critique.
Return ONLY a single JSON object.

[USER]
Question: {question.prompt}
Type: {question.type}
Expected concepts: {question.expected_concepts}
Rubric: {rubric_json}
Candidate answer: """{candidate_answer}"""
Follow-up exchanges: {follow_ups_json}

Return JSON:
{
  "rubric_scores":[{"dimension":"...","score":1-5,"rationale":"...","evidence":"quote"}],
  "weighted_score":0.0-1.0,
  "strengths":["..."], "weaknesses":["..."], "missing_concepts":["..."],
  "follow_up_recommended":true|false, "confidence":0.0-1.0
}
```

**7.3 Adaptive Follow-Up**
```text
[SYSTEM] You are MiMo as an interviewer who probes weak answers with ONE targeted
follow-up. No preamble. English unless candidate clearly prefers Vietnamese.

[USER]
Original question: {original_question}
Candidate's answer: {candidate_answer}
SkillState: mastery={mastery}, confidence={confidence}, weak_areas={weak_areas}
Detected weakness: {weakness}

Generate one follow-up that (a) targets that weakness, (b) cannot be answered by
repeating the original answer, (c) is at difficulty {target_difficulty}, (d) is
concrete (asks for an example, tradeoff, or failure mode — not "tell me more").
Output: just the question.
```

**7.4 Final Readiness Report**
```text
[SYSTEM] You are MiMo, producing a structured readiness report for a fresh AI graduate
in Vietnam preparing to interview at {target_companies}. Be specific, evidence-based,
actionable. Cite the candidate's own answers. Return Markdown.

[USER]
Session summary:
- Questions answered: {n_questions}
- Final skill states: {skill_states_json}
- All evaluations: {evaluations_json}

Required H2 sections:
## Overall Readiness (0-100 score + one-sentence verdict)
## Strengths (3-5 bullets, each citing a specific answer)
## Critical Gaps (3-5 bullets, each citing the failing rubric dimension)
## Company-Specific Notes (one paragraph per target company)
## Recommended Next Steps (3 prioritized bullets)
```

**7.5 Personalized Study Plan**
```text
[SYSTEM] You are MiMo generating a 2-week study plan. Output strict JSON matching the
StudyPlan schema. Be ruthless: at most 3 topics per week. Map topics to specific
resources from the provided catalog — do NOT invent URLs.

[USER]
Final skill states: {skill_states_json}
Critical gaps: {gaps_json}
Target companies + emphases: {target_company_profiles}
Resource catalog (from RAG): {resource_catalog_json}

Return JSON:
{
  "prioritized_topics":[["skill","why this matters for target_companies"]],
  "resources":[{"title":"...","url":"...","type":"...","skill":"...","estimated_hours":N}],
  "weekly_schedule":{"1":["Mon-Tue:...","Wed-Thu:...","Fri-Sun:..."],
                     "2":["Mon-Tue:...","Wed-Thu:...","Fri-Sun:..."]},
  "milestones":["End of week 1: ...","End of week 2: ..."],
  "readiness_estimate":0.0-1.0
}
```

---

### 8. RAG Design

**Final choice: ChromaDB embedded persistent client.** Per Chroma's v1.0 release post: *"local Chroma is 4× faster for common write and query workflows, thanks to a new core written in Rust"* (benchmark: 1M OpenAI-1536-dim embeddings, default settings, 12-core M2 MacBook; "3-5× faster writes" and "3-5× faster queries"). Zero glue code with LangChain. For ≤10k docs on a laptop, Qdrant is overkill and adds a Docker dependency; FAISS lacks metadata filtering; LanceDB is less battle-tested with LangChain integrations; sqlite-vec is too new for recruiter signal.

**Three collections to index:**
1. **`questions`** — every YAML question. Document = `prompt + expected_concepts + topic + difficulty`. Metadata: `id, topic, difficulty, type, vietnamese_context`. ~80–120 docs.
2. **`concepts`** — 200–400-token concept explanations seeded from Chip Huyen's *Introduction to Machine Learning Interviews Book* (huyenchip.com/ml-interviews-book) chapter outlines, *Designing Machine Learning Systems* summaries, and Vietnamese-NLP resources (PhoBERT README, VnCoreNLP). ~150 docs.
3. **`resources`** — learning resources (books, blog posts, GitHub repos, papers, courses). Metadata: `skill, type, url, estimated_hours`. ~60 entries.

**Chunking:** documents are short and self-contained — **chunk = whole document**, no sliding-window splitting. Eliminates retrieval errors and is fast.

**Retrieval:**
- **Default**: dense, top-k=5, cosine, metadata filter on `topic` and (optionally) `difficulty`.
- **Question Selector**: top-k=10 → re-rank by `abs(difficulty_score − target_difficulty)` + `1.0 if not in questions_asked else -inf`.
- **Study Planner**: top-k=8 per gap skill, type rotation (one book + one blog + one repo per topic).
- **Hybrid (stretch)**: BM25 via `rank_bm25` + dense via reciprocal rank fusion. Add only if Day 2 is ahead of schedule; otherwise list as future work.

**Embeddings:** `BAAI/bge-small-en-v1.5` via `sentence-transformers`. Per the model card: 33.4M parameters, 384-dim, ranked **1st on MTEB and C-MTEB** at v1 release (BAAI's August 2023 announcement). Defer multilingual BGE-M3 (1024-dim) as a future-work upgrade — call it out by name in the README.

**Seeding sources (collect on Day 1, hour 1):**
- Chip Huyen, *Introduction to Machine Learning Interviews Book* (huyenchip.com/ml-interviews-book) — concept questions across all topics.
- Chip Huyen, *Designing Machine Learning Systems* (O'Reilly, June 2022) — MLOps + system design chapter summaries from `chiphuyen/dmls-book`.
- Chip Huyen, MLOps guide (huyenchip.com/mlops/) — curated resources, courses, paper links.
- Chip Huyen, *Machine Learning Systems Design* booklet on GitHub (`chiphuyen/machine-learning-systems-design`) — 27 open-ended ML systems design questions.
- PhoBERT primary source: Nguyen et al. (2020), *PhoBERT: Pre-trained language models for Vietnamese*, EMNLP 2020 Findings (arXiv:2003.00744): *"we use a 20GB pre-training dataset of uncompressed texts… Vietnamese Wikipedia corpus (~1GB) and ~19GB Vietnamese news corpus, resulting in ~145M word-segmented sentences (~3B word tokens)"*; RDRSegmenter via VnCoreNLP for word segmentation.
- Zalo AI Challenge problem statements (challenge.zalo.ai) — Vietnamese-context tasks.
- A hand-written set of 30 questions tailored to MLE interviews at VinAI / FPT / Zalo / VNG / Viettel, derived from their public job descriptions.

---

### 9. Repo Structure

```
adaptive-interview-coach/
├── README.md
├── pyproject.toml
├── .env.example                 # MIMO_API_KEY=, GROQ_API_KEY=
├── Makefile                     # make ingest, make demo, make test
├── src/coach/
│   ├── config.py                # pydantic-settings
│   ├── schemas.py               # all Pydantic v2 schemas (§6)
│   ├── llm/
│   │   ├── base.py              # LLMClient ABC
│   │   ├── mimo.py              # MiMoClient (OpenAI-compat)
│   │   ├── groq.py              # GroqClient (fallback)
│   │   ├── router.py            # LLMRouter w/ failover + JSON retry
│   │   └── prompts.py           # Jinja2 templates (§7)
│   ├── rag/
│   │   ├── chroma_store.py
│   │   ├── embed.py             # BGE-small wrapper
│   │   ├── ingest.py            # CLI: build indexes
│   │   └── retrievers.py        # question/concept/resource retrievers
│   ├── agents/
│   │   ├── profile.py
│   │   ├── diagnostic.py
│   │   ├── selector.py          # RAG + MiMo pick
│   │   ├── interviewer.py       # create_react_agent
│   │   ├── evaluator.py
│   │   ├── skill_updater.py     # pure Python, no LLM
│   │   ├── planner.py
│   │   └── self_critique.py     # evaluator-optimizer
│   ├── graph/
│   │   ├── state.py             # LangGraph reducers
│   │   ├── nodes.py
│   │   ├── supervisor.py        # explicit routing
│   │   └── build_graph.py       # StateGraph + SqliteSaver
│   ├── storage/
│   │   ├── sqlite.py
│   │   └── exporters.py         # session → markdown / json
│   └── ui/
│       ├── streamlit_app.py
│       └── cli.py               # typer
├── data/
│   ├── questions/               # 7 YAML files, one per skill
│   ├── concepts/                # short .md per concept
│   ├── resources.yaml
│   └── golden_answers/          # for evaluator smoke test
├── chroma_db/   logs/   sessions.db   (gitignored)
├── tests/
│   ├── test_schemas.py
│   ├── test_llm_router.py
│   ├── test_rag.py
│   ├── test_skill_updater.py
│   └── test_evaluator_golden.py
└── assets/
    ├── architecture.png         # LangGraph Mermaid export
    └── demo.gif
```

---

### 10. Hour-by-Hour 2-Day Plan

**Day 1 (10 hours) — Skeleton + Core Loop**

| Hour | Deliverable |
|---|---|
| D1-H1 | `uv init`; `pyproject.toml` deps (langgraph, langchain-openai, openai, pydantic>=2, pydantic-settings, chromadb, sentence-transformers, structlog, typer, streamlit, pyyaml, rank-bm25, pytest); `.env.example`; commit. Pull seed data (Chip Huyen READMEs, PhoBERT README, your hand-written VN questions). |
| D1-H2 | Implement `schemas.py` (§6) end-to-end. `test_schemas.py` with 4+ round-trip tests. |
| D1-H3 | `llm/base.py`, `llm/mimo.py`, `llm/groq.py`, `llm/router.py` with `chat_json(messages, schema)` retry. Smoke-test against MiMo. |
| D1-H4 | All 7 question-bank YAMLs — 5–7 per topic, ≥40 total. Each has rubric, expected_concepts, follow_ups, sources. 6 Vietnamese-context items. |
| D1-H5 | `rag/embed.py` (load BGE-small once, cache), `rag/chroma_store.py`, `rag/ingest.py`. Run ingest; verify 3 retrieval queries. |
| D1-H6 | `agents/profile.py` + `agents/diagnostic.py` with §7.1 prompt. Run on a sample profile; verify Pydantic parsing. |
| D1-H7 | `agents/selector.py` (RAG + pick), `agents/interviewer.py` via `create_react_agent` with `rag_lookup` + `get_skill_state` tools. Manual single-turn test. |
| D1-H8 | `agents/evaluator.py` with strict JSON + retry. `tests/test_evaluator_golden.py`: ≥3 golden Q+A with expected score ranges (empty → ≤2, perfect → ≥4). |
| D1-H9 | `agents/skill_updater.py` (pure Python). 3 unit tests. `agents/self_critique.py`. |
| D1-H10 | `scripts/dry_run.py` integrates Profile → Diagnostic → Selector → Interviewer → Evaluator → Updater for one profile + answer. Fix breakages. **Commit "Day 1: core agents working."** |

**Day 2 (10 hours) — Orchestration, UI, Polish, Demo**

| Hour | Deliverable |
|---|---|
| D2-H1 | `graph/state.py` (reducers), `graph/nodes.py` wrapping each agent. |
| D2-H2 | `graph/supervisor.py` with explicit `Command` routing. `graph/build_graph.py` with `SqliteSaver`. Export diagram: `graph.get_graph().draw_mermaid_png()` → `assets/architecture.png`. |
| D2-H3 | `agents/planner.py` + §7.5 prompt. Test on synthetic session. |
| D2-H4 | Streamlit UI (`ui/streamlit_app.py`): 3 tabs — *Setup*, *Interview* (Q/A + live SkillState bars + supervisor route highlight), *Report*. Wire via `app.invoke({...}, config={"configurable":{"thread_id": session_id}})`. |
| D2-H5 | CLI mirror in `ui/cli.py` (typer): `coach new-session`, `coach answer`, `coach report`. README's "How to run" uses this — more impressive than Streamlit-only. |
| D2-H6 | `storage/exporters.py` writes each session as Markdown (transcript + evals + plan). Portfolio artifact per run. |
| D2-H7 | Tiny eval harness `scripts/eval_evaluator.py`: runs evaluator on 5 golden answers; prints distribution vs. expected. README → "evaluation framework." |
| D2-H8 | README (§12). Mermaid diagram, agentic-patterns table, prompt-engineering decisions, RAG details, "Why LangGraph", "Why ChromaDB", "How fallback works." Explain decisions. |
| D2-H9 | Record the 3-min demo (§11) via OBS. Convert to GIF for README header; keep mp4 for LinkedIn. |
| D2-H10 | Polish: docstrings on every public function, type hints everywhere, `make test` green, `make lint` (ruff) clean. Push to GitHub. Write LinkedIn post using CV bullets. **Commit "v1.0 — MVP complete."** |

If you fall behind: cut Streamlit (CLI-only is more impressive); keep everything else.

---

### 11. 3-Minute Demo Script

**Setup:** seed `data/questions/` and ingest. Terminal showing `tail -f logs/agent.jsonl`. `assets/architecture.png` open in a viewer.

**Profile:** "Linh Nguyen," fresh CS graduate from HUST (Hanoi University of Science and Technology); final-year thesis on Vietnamese sentiment classification with PhoBERT; internship at a local startup building invoice OCR; target = MLE at VinAI + FPT AI; claimed skills `[ml_fundamentals, deep_learning, nlp, vietnamese_nlp]`; self-assessment: ml_fundamentals=4, deep_learning=3, nlp=4, vietnamese_nlp=3, mlops=1, system_design=1.

**0:00–0:15 — Hook.** "This is an Adaptive AI/ML Interview Coach Agent — a LangGraph multi-agent system that diagnoses skill gaps, runs an adaptive interview using RAG over a curated question bank, scores answers with a rubric, and produces a personalized study plan. Powered by Xiaomi MiMo-V2.5-Pro with a Groq fallback." [Screen: README with architecture diagram.]

**0:15–0:35 — Profile + Diagnosis.** "Fresh AI graduate targeting MLE at VinAI and FPT AI — strong in NLP and Vietnamese NLP, weak in MLOps and system design." [Screen: Streamlit Setup tab → submit. Switch to terminal trace: Profile → Diagnostic. Topic plan shows MLOps and system design first.]

**0:35–1:15 — Strong NLP answer.** "First question: 'Explain how PhoBERT differs from multilingual BERT for Vietnamese tasks.' I answer well." Paste a pre-prepared strong answer mentioning RDRSegmenter word segmentation via VnCoreNLP, 20GB monolingual corpus, RoBERTa optimization, outperforming XLM-R. [Screen: Evaluator returns correctness=5, depth=4, communication=4. NLP SkillState bar jumps to ~0.78.]

**1:15–2:10 — Weak MLOps + adaptive follow-up.** Question: "Your fraud-detection model's precision drops 15% in production after two weeks. Walk me through detecting and fixing this." Weak answer: *"I would retrain the model with more data. Maybe also check if there are bugs in the code. We could try a better model architecture like XGBoost."* [Screen: Evaluator: correctness=2, mlops_awareness=1, weakness="no mention of data drift, monitoring, shadow deployment, or rollback." `follow_up_recommended: true`. Interviewer generates: *"What specific drift-detection metric would you compute, and on which data slice?"* — highlight as **ReAct + evaluator-optimizer** in trace.]

**2:10–2:35 — Self-Critique trigger.** "On the follow-up, evaluator confidence drops to 0.55 — below threshold — supervisor auto-routes through SelfCritique." [Screen: trace shows `SELF_CRITIQUE → EVALUATE`, confidence rises to 0.82, MLOps SkillState moves to 0.18.]

**2:35–3:00 — Report + Study Plan.** "After six questions, the planner generates a personalized study plan. Top gaps: MLOps and system design. The plan maps gaps to specific resources from Chip Huyen's *Designing ML Systems* and *Introduction to ML Interviews Book*, with a 2-week schedule and milestones tailored to VinAI's research emphasis and FPT AI's enterprise focus." [End on GitHub URL + your name.]

---

### 12. README + CV Bullets

**12.1 README outline**
```markdown
# Adaptive AI/ML Interview Coach Agent
> LangGraph multi-agent system: diagnoses skill gaps, runs adaptive mock
> interviews with RAG, scores with a structured rubric, generates personalized
> study plans. Built in 2 days for AI engineering interview prep targeted at
> Vietnamese AI companies.

![Demo](assets/demo.gif)

## Why this exists
(2-3 sentences: most interview-prep tools are static; Vietnamese AI companies
test for production thinking, not LeetCode.)

## Architecture
![Architecture](assets/architecture.png)
(Auto-generated via LangGraph `get_graph().draw_mermaid_png()`)

## Agentic patterns used
| Pattern | Where |
|---|---|
| Supervisor / Router | graph/supervisor.py |
| ReAct | agents/interviewer.py |
| Planner-Executor | agents/diagnostic.py + selector |
| Evaluator-Optimizer (Reflection) | agents/evaluator.py → self_critique.py |
| Structured Output | llm/router.py::chat_json + Pydantic |
| Tool Use | rag_lookup, get_skill_state, update_skill_state |

## Tech stack
Python 3.11 · LangGraph 0.2 · Pydantic v2 · ChromaDB · BGE-small-en-v1.5 ·
sentence-transformers · SQLite (LangGraph SqliteSaver) · Streamlit · Typer ·
structlog · pytest

## LLM provider
- Primary: Xiaomi MiMo-V2.5-Pro (OpenAI-compatible)
- Fallback: Groq llama-3.3-70b-versatile (free, sub-200ms TTFT)
- Single LLMClient abstraction; provider swap = one env var.

## RAG details
Three Chroma collections (questions / concepts / resources), seeded from
Chip Huyen's ML Interviews Book + Designing ML Systems + Vietnamese-AI
resources (PhoBERT, VnCoreNLP, Zalo AI Challenge). Dense retrieval with
BGE-small-en-v1.5 (33.4M params, 384-dim, MTEB-1st at v1 release), metadata
filtering on topic/difficulty.

## How to run
git clone ... && cd adaptive-interview-coach
uv sync
cp .env.example .env   # add MIMO_API_KEY and (optionally) GROQ_API_KEY
make ingest            # build Chroma indexes (~30s)
make demo              # launch Streamlit
# OR: coach new-session    # CLI mode

## Evaluation framework
scripts/eval_evaluator.py runs the evaluator agent on 5 golden answers and
reports score distribution vs. expected ranges. Run via `make eval`.

## Future work
Hybrid retrieval (BM25 + dense + RRF) · BGE-M3 multilingual embeddings for
full Vietnamese-NLP coverage · MiMo-V2.5-TTS voice-driven interviews ·
LangSmith tracing in CI · Agent observability dashboard

## License
MIT
```

**12.2 CV bullets (English, recruiter-keyword-dense)**

1. **Built an Adaptive AI/ML Interview Coach Agent** in Python 3.11 — a **LangGraph-orchestrated multi-agent system** (supervisor, ReAct interviewer, rubric evaluator, planner) with **persisted state in SQLite via SqliteSaver**, **structured JSON output via Pydantic v2 + response_format**, and an **evaluator-optimizer reflection loop** that re-evaluates low-confidence scores.
2. **Designed and shipped a RAG pipeline over a curated AI/ML interview corpus** (~250 docs across questions, concepts, and resources from Chip Huyen's *Introduction to ML Interviews Book*, *Designing ML Systems*, and Vietnamese-NLP sources including the PhoBERT EMNLP 2020 paper) using **ChromaDB** with **BAAI/bge-small-en-v1.5 embeddings** (384-dim, MTEB-1st at v1 release), top-k dense retrieval, and metadata filtering — integrated into a Question Selector and Study Planner agent.
3. **Engineered a provider-agnostic LLM router** abstracting Xiaomi **MiMo-V2.5-Pro** (OpenAI-compatible, 1M-context, 1.02T-param / 42B-active MoE) with automatic failover to **Groq Llama-3.3-70B-versatile** (sub-200ms TTFT per Groq's LPU benchmark docs), including structured-output retry with Pydantic schema validation and an explicit `reasoning_content` propagation policy for MiMo's thinking-mode multi-turn tool-call constraint.
4. **Implemented six agentic patterns end-to-end** — supervisor routing, ReAct with typed tool use (rag_lookup, get_skill_state), planner-executor topic plans, evaluator-optimizer self-critique, structured output, and Bayesian skill-state updates — explicitly mapped to source files and visualized via auto-generated LangGraph Mermaid diagrams.
5. **Built a rubric-based evaluation framework** with weighted dimensions (correctness, depth, communication, system-thinking, MLOps awareness), verbatim evidence citation, and a **golden-answer regression harness** asserting score ranges on held-out Q-A pairs — the pattern used to QA production LLM systems.
6. **Tailored the system for Vietnamese AI hiring** (VinAI, FPT AI, Zalo AI, VNG, Viettel AI): hand-curated Vietnamese-NLP questions covering PhoBERT, VnCoreNLP/RDRSegmenter word segmentation, and Zalo AI Challenge tasks; per-company emphasis modeling in the readiness report and study plan.

---

### 13. MiMo API Specifics

- **Base URL:** `https://api.xiaomimimo.com/v1` (OpenAI-compatible); Anthropic-compatible variant at `https://api.xiaomimimo.com/anthropic`. Console at `https://platform.xiaomimimo.com`.
- **Authentication:** Both `Authorization: Bearer $MIMO_API_KEY` and `api-key: $MIMO_API_KEY` headers are officially supported per the platform's OpenAI-API reference page. The OpenAI Python SDK uses Bearer by default.
- **OpenAI-compatible:** Yes — drop in `openai>=1.x` by setting `base_url`. `client.chat.completions.create(...)` works; streaming, `tools` (function calling), `tool_choice`, and `response_format` are all supported on `mimo-v2.5-pro`.
- **Default model:** `mimo-v2.5-pro` for reasoning-heavy nodes (Diagnostic, Selector pick, Evaluator, Planner). Use `mimo-v2.5` (omni-modal sibling, ~half the cost) for the Interviewer ReAct loop if budget tightens. Skip the TTS variants in this MVP.
- **Pricing (pay-as-you-go, mimo-v2.5-pro ≤256K prompts):** $1.00/M input cache-miss, $0.20/M input cache-hit, $3.00/M output. Doubles in the 256K–1M range. Cache writes are limited-time free. Web-search tool: $5 per 1000 calls.
- **Rate limits:** 100 RPM, 10M TPM, 1M-token context, 128K max output. Implement exponential backoff on 429.
- **Your timeline:** Free tokens valid until **2026-06-03**. No documented automatic free tier afterward; the "Orbit 100T Token Grant for Builders" exists but is application-reviewed. Plan the Groq cutover for June 3.
- **Token Plan keys (`tp-xxxxx`)** are scoped to approved coding tools — **not** for programmatic backend use. Use a pay-as-you-go key for this project.
- **Structured JSON output:** `response_format={"type":"json_object"}` is supported (visible in the OpenAI-API reference's "structured output" tab and in the capability matrix). `response_format={"type":"json_schema",...}` is asserted but not richly documented in English prose. **Belt-and-suspenders implementation:** pass `response_format={"type":"json_object"}`, embed the JSON schema in the system prompt, and retry once on parse failure with the parser error appended.
- **Function / tool calling:** Full OpenAI-style `tools=[{type:"function", function:{name,description,parameters}}]` + `tool_choice:"auto"`. Responses carry `choices[0].message.tool_calls`. LangGraph's `create_react_agent` works as-is.
- **Critical gotcha — the `reasoning_content` quirk:** Per the platform's authoritative Chinese-version multi-turn-tool-call notice: *"When MiMo thinking mode is enabled in a multi-turn conversation, and tool calls exist in the conversation history, then in all subsequent user interaction turns, if the returned assistant message contains tool calls, the `reasoning_content` field must be passed back in full — otherwise the API will return a 400 error."* **Mitigation in this project:** (a) disable thinking mode in tool-using agents via `extra_body={"thinking":{"type":"disabled"}}` (recommended for the Interviewer ReAct loop — simplest), or (b) preserve `reasoning_content` on every assistant message in the history. LangChain's `ChatOpenAI` strips non-standard fields like `reasoning_content`, so handle this in your raw MiMoClient, not via `ChatOpenAI`.
- **Other limitations:** MiMo-V2.5-Pro is verbose (higher-end output volume vs. comparable open-weight reasoning models per public benchmarks) — set `max_completion_tokens` aggressively (1024 for evaluator JSON; 2048 for study plan). TTFT is at the higher end of comparable open-weight models on public provider medians — show a "MiMo is thinking…" placeholder in Streamlit.

---

### 14. Fallback Strategy

**Primary fallback: Groq `llama-3.3-70b-versatile`.** Per Groq's official rate-limits documentation, free tier = **30 RPM / 6,000 TPM / 1,000 RPD**; Groq's LPU benchmark docs cite **sub-200ms TTFT (3–10× faster than standard GPU inference)**. OpenAI-compatible at `https://api.groq.com/openai/v1`. No card. Same schema. No `reasoning_content` quirk.

**Tertiary fallback: Gemini 2.5 Flash for Study Planner only.** Per Google AI's official pricing page (April 2026): **1,500 RPD / 1M TPM / 15 RPM, no credit card, no expiration**. The 15 RPM cap is hostile to a multi-call-per-turn agent, but fine for one Study Planner call per session.

**Single abstraction, single config switch:**

```python
# llm/base.py
from abc import ABC, abstractmethod
from pydantic import BaseModel

class LLMClient(ABC):
    name: str
    @abstractmethod
    def chat(self, messages, **kwargs) -> str: ...
    @abstractmethod
    def chat_json(self, messages, schema: type[BaseModel], **kwargs) -> BaseModel: ...

# llm/router.py
import structlog
from openai import RateLimitError, APIError
log = structlog.get_logger()

class LLMRouter(LLMClient):
    name = "router"
    def __init__(self, primary, fallbacks): self.primary, self.fallbacks = primary, fallbacks
    def _try(self, method, *a, **kw):
        last = None
        for c in [self.primary, *self.fallbacks]:
            try:
                log.info("llm.call", provider=c.name, method=method)
                return getattr(c, method)(*a, **kw)
            except (RateLimitError, APIError, Exception) as e:
                log.warning("llm.failover", provider=c.name, err=str(e)); last = e
        raise RuntimeError(f"all providers failed: {last}")
    def chat(self, m, **k):       return self._try("chat", m, **k)
    def chat_json(self, m, s, **k): return self._try("chat_json", m, schema=s, **k)

# llm/mimo.py
import json
from openai import OpenAI
from pydantic import BaseModel, ValidationError

class MiMoClient(LLMClient):
    name = "mimo-v2.5-pro"
    def __init__(self, api_key, model="mimo-v2.5-pro"):
        self.client = OpenAI(api_key=api_key,
                             base_url="https://api.xiaomimimo.com/v1",
                             timeout=60)
        self.model = model
    def chat(self, messages, **kwargs):
        # Disable thinking by default for tool-using agents to avoid the
        # reasoning_content multi-turn 400 trap.
        extra_body = kwargs.pop("extra_body", {"thinking": {"type": "disabled"}})
        r = self.client.chat.completions.create(
            model=self.model, messages=messages, extra_body=extra_body, **kwargs)
        return r.choices[0].message.content
    def chat_json(self, messages, schema, **kwargs):
        sys_add = f"\n\nReturn ONE JSON object matching this schema:\n{schema.model_json_schema()}"
        msgs = list(messages)
        if msgs and msgs[0]["role"] == "system":
            msgs[0] = {**msgs[0], "content": msgs[0]["content"] + sys_add}
        else:
            msgs.insert(0, {"role": "system", "content": sys_add})
        for _ in range(2):
            content = self.chat(msgs, response_format={"type":"json_object"}, **kwargs)
            try:    return schema.model_validate_json(content)
            except (ValidationError, json.JSONDecodeError) as e:
                msgs += [{"role":"assistant","content":content},
                         {"role":"user","content":f"Previous response failed validation: {e}. Return ONLY valid JSON."}]
        raise ValueError("schema validation failed after retries")
```

`GroqClient` is the same shape with `base_url="https://api.groq.com/openai/v1"` and `model="llama-3.3-70b-versatile"`; no thinking-mode shenanigans needed. Switching is one env var (`PRIMARY_PROVIDER=mimo|groq|gemini`); on 2026-06-04 you change the env var, nothing else.

---

### 15. Anti-Patterns to Avoid

A recruiter scans your repo in 90 seconds. The following kill agentic-engineer signal — avoid each, and (where possible) call out in the README how you addressed it.

1. **Single mega-prompt pretending to be an agent.** *Fix:* split into named agents with typed inputs/outputs; ship the graph diagram.
2. **No persisted state.** In-memory `messages=[]` that dies on refresh. *Fix:* LangGraph `SqliteSaver` keyed by `session_id`; user can resume.
3. **No rubric, no numeric scoring.** "Great answer!" vibes feedback. *Fix:* weighted `RubricDimension`s, per-dimension score, verbatim evidence citation.
4. **No structured output.** Free-text parsed with regex. *Fix:* Pydantic schema → `response_format={"type":"json_object"}` → `model_validate_json` → retry-with-error.
5. **No adaptation.** Same question pool regardless of skill. *Fix:* SkillState mutates after every eval; Selector reads SkillState before picking next.
6. **No RAG.** Hardcoded prompts only. *Fix:* ChromaDB-backed Selector and Planner — even 80 indexed docs show the retrieval path.
7. **No evaluation framework.** "Seems to work" testing. *Fix:* `scripts/eval_evaluator.py` with golden answers + score-range assertions.
8. **Hard-coupled to one provider.** `from openai import OpenAI; client = OpenAI(...)` scattered everywhere. *Fix:* `LLMClient` ABC + Router.
9. **Black-box LangGraph prebuilts only.** Just `create_supervisor` + `create_react_agent`. *Fix:* hand-code at least one supervisor node, one reflection node, and one pure-Python no-LLM node.
10. **No tests.** *Fix:* schema round-trip, skill-update math, golden-answer evaluator tests.
11. **No diagram.** *Fix:* export the LangGraph Mermaid diagram into the README and `assets/`.
12. **"Chatbot Mandate" framing.** Selling it as "a chatbot that helps you prep." *Fix:* lead the README with "stateful multi-agent system with rubric evaluation and adaptive question selection" — recruiter keywords.

---

## Recommendations

**Staged execution plan.**

1. **Tonight (before Day 1, 30 min):** create the MiMo API key on `platform.xiaomimimo.com`, verify a curl call against `mimo-v2.5-pro`, sign up for Groq Cloud free tier and verify `llama-3.3-70b-versatile`. If MiMo's free credits balance shows <5M tokens, stop and re-apply for the Orbit grant before starting.
2. **Day 1 (10 hrs):** schemas → LLM router → question bank YAMLs → RAG ingest → all agents wired in dry-run script. End-of-day milestone: `python scripts/dry_run.py` completes one full Profile → Diagnostic → Question → Eval → Update cycle with valid Pydantic outputs throughout.
3. **Day 2 (10 hrs):** LangGraph orchestration → Streamlit + CLI → exporters → eval harness → README → 3-min recorded demo. End-of-day milestone: GitHub repo public, README with embedded GIF + Mermaid diagram, LinkedIn post drafted from the CV bullets.
4. **Day 3 (after the deadline, optional 3 hrs):** apply tailoring patches per target company — e.g., add 5 more computer-vision questions before applying to VinAI; add 5 more Vietnamese-NLP + ranking questions before applying to Zalo/VNG; add MLOps + enterprise-OCR questions before FPT AI.
5. **2026-06-03 (cutover day):** set `PRIMARY_PROVIDER=groq` in `.env`, run `make test`, push a commit titled "switch primary to Groq Llama-3.3-70B post-MiMo-credits expiry." This commit itself is recruiter signal: it proves you actually designed for provider portability.

**Benchmarks that would change the plan:**

- *If MiMo grants you ≥100M tokens via Orbit:* keep MiMo primary indefinitely, upgrade Interviewer to use `mimo-v2.5` for vision tasks (omni-modal — supports image input on the same OpenAI-compat endpoint), and add an image-based system-design question as a third demo flourish.
- *If your golden-answer eval shows evaluator scores diverging >1 point from expected on 2/5 cases:* invest D2-H7 in a few-shot prompt with 2 in-context score examples and run the golden test again.
- *If MiMo's `response_format` json_schema mode misbehaves with thinking enabled:* you already have the fallback in `chat_json` (json_object + schema-in-prompt + retry). No code change needed.
- *If you finish all of Day 2 by hour 8:* add hybrid retrieval (BM25 + dense + RRF) and a LangSmith trace export — both are big-name recruiter keywords.
- *If a recruiter asks "is this just a chatbot?":* answer with the one-line elevator: *"It's a LangGraph-based multi-agent interview coach with a supervisor routing across diagnostic, RAG-driven selector, ReAct interviewer, rubric evaluator with reflection, and study planner agents — Pydantic-typed state persisted in SQLite, structured JSON output enforced via response_format + schema-retry, ChromaDB RAG over a curated ML-interview corpus, and a provider-agnostic LLM router so I can swap MiMo for Groq with one env var."* That sentence is the whole project. Build to it.

---

## Caveats

- **MiMo's `response_format={"type":"json_schema",...}` is asserted but under-documented in English prose.** The capability matrix and OpenAI-API reference tab show it; no worked example was found. Treat json_object mode + schema-in-prompt + retry as the safe default; only adopt strict json_schema mode if you confirm it works against your evaluator prompt empirically.
- **The `reasoning_content` multi-turn-tool-call requirement is real and breaks LangChain's `ChatOpenAI`** (which strips non-standard fields). For tool-using nodes, either disable thinking mode or use the raw MiMoClient. This blueprint recommends the former because it's simpler and the Interviewer doesn't need extended reasoning.
- **Free-tier provider limits change.** Gemini cut free limits in 2025; Groq could too. Your CV is safe — you've built provider portability in. But monitor `console.groq.com/docs/rate-limits` monthly.
- **ChromaDB's "4× faster" claim is benchmarked on 1M OpenAI-1536-dim embeddings on a 12-core M2 MacBook** per Chroma's own release post. Your numbers will differ; the point is that ChromaDB is no longer a "dev-only" toy — it's production-grade for small/medium corpora.
- **PhoBERT figures (20GB corpus, ~145M sentences, ~3B word tokens) come from Nguyen et al. (2020), EMNLP Findings (arXiv:2003.00744).** Quote this paper, not a derivative blog, in your README's RAG section — it shows you read primary sources, which VinAI specifically values.
- **VinAI valuation figures and FPT/VNG metrics in this blueprint are drawn from third-party industry reports (Second Talent, Designveloper, Nucamp).** Treat them as directional, not audited financials; mention them in your *demo narration*, not in formal claims.
- **MiMo-V2.5-Pro is a reasoning model and is verbose.** Expect higher output token consumption than non-reasoning baselines; budget accordingly and aggressively cap `max_completion_tokens`.
- **MTEB-#1 ranking for BGE-small-en-v1.5 was at v1 release (August 2023).** The MTEB leaderboard has since moved on (Voyage AI voyage-3-large, NV-Embed-v2, Cohere embed-v4 lead various metrics in 2026). For a 2-day MVP this doesn't matter; for future work, evaluate switching to BGE-M3 (multilingual, 1024-dim) for genuine Vietnamese-NLP coverage.
- **None of the prompts in §7 have been A/B-tested.** Treat them as a strong starting point but expect to iterate on the evaluator prompt specifically — that's where score quality lives. Use the golden-answer harness to detect regressions.
