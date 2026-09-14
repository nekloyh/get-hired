# OSS landscape: AI mock-interview / interview-coach projects

Access date: 2026-09-02. Primary sources: the repositories themselves (README, tree, manifests, license, commits, stars) via the GitHub API. Tags: [SOURCED] = read directly from the repo/API; [INFERRED] = derived from what was read.

Our baseline (nekloyh/get-hired, "personal-interviewer"): adaptive mock technical interview; LangGraph + FastAPI + React; single LLM judge (gpt-5.4-mini, pinned) with a bilingual VN/EN calibration bench (35 cases, median-of-k, k=3); Bayesian (Beta-prior) skill state; YAML question packs; replay bench; study plan.

## 1. Search log

GitHub repository search, 2026-09-02, each query run sorted by stars and by last-updated (top 10 each). [SOURCED]

| Query | total_count | Top by stars (★) | Signal in "recently updated" slice |
|---|---|---|---|
| `"mock interview" AI` | 10,276 | liftoff 1,522 · adrianhajdin/ai_mock_interviews 567 · Lujie-Careerkit 325 · interview-skills 320 · Multi-Agent-Mock-Interview 132 · IliaLarchenko/Interviewer 126 | all ★0 pushed today: Flask+Gemini, Next.js+Vapi, "LiveKit/Tavus" one-offs |
| `"interview coach"` | 4,176 | noamseg/interview-coach-skill 2,075 (Claude skill, prompt-only) · interview-ai-prototype 218 · Azure-Samples/interview-coach-agent-framework 163 | ★0 student projects; several are Claude Code "skills" (markdown prompts, no app) |
| `"interview simulator"` | 2,177 | liftoff 1,522 · system-design-simulator 334 · iPG 188 · backend-interview-simulator 163 (skill) · nicobytes/interview-full-stack 95 | — |
| `"AI interviewer"` | 7,043 | TorchLeet 2,461 (problem set, not an interviewer) · go-interview-practice 2,459 · ai-interview-platform 904 · GPTInterviewer 264 · FindJobs-Agent 252 | ★0 voice/LangGraph one-offs |
| `"interview practice" LLM` | 78 | GPTInterviewer 264 · PrepDojo 30 · interview-bot 10 · AI-Interview-Agent 5 | — |
| `interview langgraph` | 571 | mostly study guides (AgentGuide 9,086, generative-ai 2,610); real apps: 1624899/ai_interview 64 · zzzlip/langgraph-AI-interview-agent 58 · next-role 49 · rolemule 37 · DeepInterview 33 | ~10 ★0 LangGraph interview repos pushed 2026-09-01 alone |
| `"mock interview" voice` | 1,105 | mock-interviews-with-ai 58 (2023) · DeepInterview 33 · Hire-Wise 27 · preptalk-ai 17 | Next.js+Vapi pattern dominates |
| `"interview copilot"` | 672 | natively-cluely 2,405 · MeetingCopilot 187 · Open-Cluely 149 · Interview-Copilot 146 | this is the *cheating-assistant* class (live STT -> answer overlay), not practice tools; excluded from the detailed list |
| `"phỏng vấn" AI` | 16 | all ★≤4: ARISP 2 (C#, recruiter-side), phongvan-ai 0 ("chấm điểm đa tiêu chí"), IntervAI 0, CareerMindAI 0, inMentor 0 | no Vietnamese-language interview-practice OSS with any adoption exists |
| `"phỏng vấn"` (updated) | 129 | cheat-sheets and question lists; nothing app-shaped above ★4 | — |

Excluded classes: (a) question banks / study guides (TorchLeet, ai-interview-codex, AgentGuide); (b) Claude Code / agent "skills" that are a markdown prompt with no runtime (noamseg/interview-coach-skill ★2,075, backend-interview-simulator, kirilxd/swe-interview-coach, fenlili0108/interview-coach); (c) live interview copilots (Cluely clones); (d) recruiter-side screening tools.

## 2. Interview repos (detailed)

Format: URL · ★ · forks · license · created → last commit (release) · issues. All [SOURCED] from API/README/tree unless tagged.

### 2.1 ngoanpv/DeepInterview — closest competitor
- https://github.com/ngoanpv/DeepInterview · ★33 · 11 forks · Apache-2.0 · 2026-06-08 → 2026-08-26 (v0.3.0, 2026-08-02) · 14 issues (11 open); CI, CHANGELOG, CITATION.cff, README.vi.md.
- Stack: pnpm/turbo monorepo. `apps/web` Next.js (Vercel button). `apps/agent` Python 3.11 + uv, FastAPI :8000, Pydantic models with TS parity tests; LangGraph for the prep and post pipelines; `services/lightrag` (:9621); Supabase repo with in-memory fallback; LiveKit worker for live voice (opt-in compose profile); STT/TTS/LLM pluggable per component (closed issues: faster-whisper, Kokoro/XTTS, Ollama/Qwen3); Tavily/Exa search adapter.
- Features: CV + JD upload, company research, `QuestionPlan`, adaptive difficulty (pure function in `live.state`), competency scoring + language coach + report/ScoreCard, "skill distiller" that writes reusable packs, study coach loop. `skills/*.md` packs carry YAML frontmatter (`company`, `role`, `level`, `competency`, `version`, `source_runs`, `confidence` 0–1 that decays, `status` draft/review/promoted/deprecated) — the closest analogue to our YAML question packs, with provenance fields ours lacks.
- Architecture: explicit prep / live / post split — "heavy reasoning happens before and after the call, never on the live turn path"; one fast model on the live loop reading an `InterviewContext` blackboard. Persistence: sessions in repo; live worker writes back at shutdown.
- Eval: 20+ offline pytest modules against `MockLLM` (test_score, test_adaptive, test_report_regression). No judge-quality measurement — scoring is only exercised with a deterministic mock. `test_report_regression.py` pins a production bug: when the live model never called the `save_answer` tool, every answer was silently dropped.
- Multilingual: UI strings EN + VI shipped, but issue #50 "Wire up the Vietnamese (vi) UI message pack" is still OPEN; README claims voice in 7 languages incl. Vietnamese.
- Real use: external bug report #67 (stuck while connecting/grading); CVE lockfile issue #70. README self-labels "early open build".
- Weaknesses: answer capture depends on LLM tool-calling; judge never measured; VI not finished; ★33 after three months.

### 2.2 IliaLarchenko/Interviewer — the only one with an LLM-graded simulation gate
- https://github.com/IliaLarchenko/Interviewer · ★126 · 42 forks · Apache-2.0 · 2024-04-22 → 2024-08-17 (no releases) · 2 issues, both open install breakage (`Client.__init__() got an unexpected keyword argument 'proxies'`).
- Stack: Gradio app (also a HF Space; the only workflow is `sync_to_huggingface.yml`), `api/llm.py` + `api/audio.py`; LLM OpenAI / Anthropic / Ollama-compatible; STT/TTS OpenAI or HF/local; Docker compose. No DB — one Gradio session, no resume.
- Features: types `ml_design, math, ml_theory, system_design, sql, coding`; speech-first; prompts in `resources/prompts.py`; feedback at the end.
- Eval: `tests/candidate.py` plays an LLM candidate, `tests/test_simulation.py` runs every type plus edge modes `empty/gibberish/repeat`, `tests/grader.py` grades the transcript with gpt-4o, thresholds `MIN_AVERAGE_SCORE=0.7`, `MIN_INTERVIEW_SCORE=0.2`; `tests/analysis.py` (pandas) for offline analysis. This grades the *interviewer's* behaviour, not the judge against human labels. [INFERRED: closest OSS analogue to our replay bench.]
- Dead since 2024-08.

### 2.3 zixi-liu/interview-ai-prototype — judge-reliability research artefact
- https://github.com/zixi-liu/interview-ai-prototype · ★218 · 3 forks · NO license · 2025-11-23 → 2026-04-15 · 0 issues.
- Stack: FastAPI + OpenAI (LiteLLM in the eval harness); gpt-4o(-mini/-audio), claude-3-5-sonnet, gemini-1.5-pro; Docker, Railway.
- Features: analyzes one self-introduction or behavioral answer (text/audio) with "FAANG-standard" hire/no-hire feedback; `feedbacks/` holds hundreds of dated `*_Hire.md` / `*_Leaning_No_Hire.md` outputs.
- Eval: `paper_2_eval/` rates a 50-answer TOML set with four judge models across Google/Meta/Amazon rubrics, JS-divergence early stop, `reliability_metrics.py`, arXiv draft. `policy/` is a learned STOP/CONTINUE probing policy: 88% accuracy vs heuristic 60% vs gpt-4o zero-shot 56% (30 sessions, 125 samples). The only repo measuring judge agreement, but as a study, not a merge gate; single-answer analyzer, not a session.
- Weaknesses: no license, no issues, 3 forks — stars without adoption.

### 2.4 XUZIAa/Multi-Agent-Mock-Interview — dual-loop voice director
- https://github.com/XUZIAa/Multi-Agent-Mock-Interview · ★132 · 2 forks · GPL-3.0 · 2026-08-05 → 2026-08-28 (v2.1.0, 2026-08-22) · 0 issues. Chinese only. Desktop app with downloadable release (PyInstaller spec); Java and Python backends both in tree.
- Stack: React 19 + Vite 7 + TS + Tailwind 4 + shadcn; Python 3.12 FastAPI sidecar; SQLAlchemy 2.0 async + aiosqlite (WAL) as "single source of truth, written every turn, crash-recoverable"; WebSocket OpenAI-Realtime-style protocol; full-duplex voice with interruptions both ways; `pdfplumber` resume ingest.
- Architecture: stated motivation — realtime voice models drift persona after 30 min because audio context is bounded — so "Fast Loop (mouth)" = realtime voice model that only listens and voices the director's intent; "Slow Loop" = `agents/director.py` plus `guard.py`, `live_agents.py`, `prepare_agents.py`, `resume_agent.py`, `coding_agent.py`, `reviewer.py`; `analysis/prosody.py` + `transcript.py`.
- Features: multi-dimensional end score, annotated transcript, "full-marks answer reconstruction", targeted improvement plan. No eval/bench, no tests dir at root.

### 2.5 1624899/ai_interview ("面面") — LangGraph state machine, hosted
- https://github.com/1624899/ai_interview · ★64 · 9 forks · NOASSERTION · 2025-11-21 → 2026-07-07 · 0 issues; public hosted demo.
- Stack: Python backend (`app/core/graph.py`, `interview_planner.py`, `interview_analysis.py`, `memory.py`, `mode_strategy.py`, `voice_interview.py`, three resume `*_graph.py`) = LangGraph; TS web; nginx + docker-compose; OpenAI / Azure / DeepSeek / Qwen; voice via Qwen3-Omni realtime + browser STT + VAD; recordings cached in IndexedDB.
- Features: plan from resume + JD; no in-interview feedback (hints on demand); self-intro/tech/behavioral/system-design; end report with score, strengths/weaknesses, hire recommendation; multi-round continuation with resume/JD inherited; 3–10 questions; 5-dimension ability scores with a cumulative trend across interviews; resume "roundtable" (matcher / optimizer / HR reviewer + Reflector QA node).
- Eval: one test file (`test_interview_completion.py`). Chinese only.

### 2.6 Azure-Samples/interview-coach-agent-framework — vendor teaching sample
- https://github.com/Azure-Samples/interview-coach-agent-framework · ★163 · 67 forks · MIT · 2026-01-21 → 2026-08-31 · 4 issues.
- Stack: C#/.NET, Blazor chat UI, Aspire orchestration, Microsoft Agent Framework, MCP servers (MarkItDown parsing, InterviewData session store), `gpt-5-mini` via Microsoft Foundry or GitHub Copilot; `azd up`. `Single` mode (1 agent) vs `HandOff` (5 specialists). Text only; `InterviewCoach.Agent.Tests` exist; no scoring bench, no voice.

### 2.7 Tameyer41/liftoff — most-starred, dead, single prompt
- https://github.com/Tameyer41/liftoff · ★1,522 · 256 forks · MIT · 2023-05-31 → 2023-06-07 · 5 issues.
- Stack: Next.js + Vercel template, Upstash Redis rate-limit, react-webcam, Whisper transcription, gpt-3.5-turbo streaming; three API routes (`generate.ts`, `transcribe.ts`, `blocked.ts`). System prompt: "You are a tech hiring manager. You are to only provide feedback on the interview candidate's transcript…". Fixed questions, no adaptivity, no rubric, no persistence. Stars come from Vercel-template virality. [INFERRED]

### 2.8 jiatastic/GPTInterviewer — 2023 Streamlit + LangChain
- https://github.com/jiatastic/GPTInterviewer · ★264 · 124 forks · MIT · 2023-06-25 → 2024-01-31 (v0.1.2, 2023-08-06) · 4 issues.
- Stack: Streamlit, LangChain, OpenAI, FAISS over resume/JD, Azure Cognitive Services TTS + `st_audiorec`; pages Behavioral / Professional / Resume. Per-role prompt templates ("I want you to act as an interviewer… Create a guideline with 3 topics"). Session lost on refresh (README: "initiate a new interview simply by refreshing"). Dead.

### 2.9 yuanzhongqiao/ai-interview-platform (聆悟 / haacoo) — recruiter-side, 10-day burst
- https://github.com/yuanzhongqiao/ai-interview-platform · ★904 · 87 forks · MIT · 2026-05-26 → 2026-06-05 · 1 issue. Primary use is employer screening (design interview → share link → AI conducts → report); README lists job-seeker self-practice as a secondary audience.
- Stack: Next.js 14 + tRPC + Supabase (Postgres, RLS, Storage); Node voice relay for Volcengine (豆包) ASR/TTS and an OpenAI voice relay; `@google/genai` + `openai`; Docker. Tests: `node:test` suite incl. `answer-quality.test.ts` (heuristic guardrails: coach-echo / meta-answer detection, prep-score caps), ASR interim, rate-limit, API-key auth.
- 904 stars in ten days of commits then silence for three months. [INFERRED: promotional star velocity.] Chinese-first.

### 2.10 zzzlip/langgraph-AI-interview-agent — Java platform + Python worker
- https://github.com/zzzlip/langgraph-AI-interview-agent · ★58 · 13 forks · no license · 2025-08-04 → 2026-07-10 · 0 issues. Chinese only.
- Stack: Spring Boot 3 modular monolith (auth, tasks, files, SSE, admin) + Python worker (`langgraph`, `langchain-openai`, `chromadb`, `sentence-transformers`, cv2) + static frontend; MySQL, Redis, RabbitMQ, MinIO; DeepSeek / DashScope; Codeforces for algorithm tasks. README states the historical LangGraph prototype is *not* part of the V1 release.
- Features: resume eval (5 dims + radar), resume rewrite, algorithm tasks, mock interview with follow-up decisions, stage state, in-task memory compression, final report, multimodal signals as auxiliary input. Infra far heavier than its adoption. [INFERRED]

### 2.11 Ranjit2111/AI-Interview-Agent — interviewer/coach split, dead
- https://github.com/Ranjit2111/AI-Interview-Agent · ★5 · 2 forks · no license · 2025-03-19 → 2025-06-30 · 0 issues.
- Stack: FastAPI, React + Vite + shadcn, Supabase Postgres, Gemini, Deepgram STT, TTS, Azure Container deploy. `backend/agents/`: `orchestrator.py`, `interviewer.py`, `agentic_coach.py` (`evaluate_answer` per turn, final summary + web-searched resources), `interview_state.py`; `backend/tests/` present.
- Features: adaptive questions from JD/resume, styles Formal/Casual/Technical/Aggressive, difficulty, timed sessions, silent per-turn coach feedback, final score + transcript replay, persisted sessions. Closest in *shape* to our Interviewer/Evaluator split, but no eval and abandoned after three months. [INFERRED]

### 2.12 yudongfang-thu/PrepDojo — local-first, sandbox judge + AI 八股 interviewer
- https://github.com/yudongfang-thu/PrepDojo · ★30 · 3 forks · MIT · 2025-08-21 → 2026-08-23 · 0 issues. Chinese.
- Stack: FastAPI + no-build static UI, SQLite, DeepSeek via OpenAI-compatible client with function calling (AI coach can call the code-judge sandbox); Docker judge image required for multi-user; modules `judge.py`, `quiz.py` (AI interviewer asks / scores / follows up on knowledge questions), `review.py`, `ingest.py` (PDF/MD → question cards), `auth.py`. 15 pytest files (judge five states, docker judge, web security, multi-user). No LLM eval; honest README on the "local-first vs API boundary".

### 2.13 Chozzc/Lujie-Careerkit — career workspace with mock-interview module
- https://github.com/Chozzc/Lujie-Careerkit · ★325 · 20 forks · Apache-2.0 · 2026-06-30 → 2026-08-24 (v0.3.0) · 9 issues; live preview.
- Stack: Next.js + Prisma/SQLite (local), `@ai-sdk/openai-compatible`, `next-intl` (en, zh-CN), vitest, Docker. Mock interview = generate questions from resume + JD, save answer drafts, AI review report; not a live adaptive session. Exports "Agent Skills" for the same workflows.

### 2.14 prashma03/interview-director — deterministic director owns state
- https://github.com/prashma03/interview-director · ★1 · created 2026-08-30 · no license. LiveKit Agents (Node) + Tavus avatar, Express token server, React/Vite, vitest.
- Architecture: `src/interviewMachine.ts` is the "sole owner of stages, questions, evidence, limits, and transitions"; "the LLM never mutates workflow state"; stage agents differ only in instructions; ≤2 follow-ups per primary; 150 s / 300 s stage fallbacks; event IDs + stage epochs reject stale answers; candidate-confirmed transcripts before evidence extraction. No scoring. Tiny, but the same plan-executor stance as our ADR 0001. [INFERRED]

### 2.15 viettungjr-byte/phongvan-ai — the only Vietnamese practice app found
- https://github.com/viettungjr-byte/phongvan-ai · ★0 · created 2026-07-23 → 2026-08-02 · no license. Node Express + Prisma/MySQL, React/Vite, browser Web Speech API; `AI_PROVIDER` = `mock` (default) | openai | gemini | claude; scores 5 criteria = 100 points, generates the next question, end report. One API smoke test.

### 2.16 Briefly noted
- vijaygupta18/system-design-simulator · ★334 · MIT · → 2026-06-14: Next.js 16 static + ReactFlow + Zustand/localStorage; deterministic "connectivity-aware" scoring engine (`src/scoring`), no LLM SDK in deps; 35 problems. Rubric-as-code without a judge.
- nicobytes/interview-full-stack · ★95 · → 2024-04-15: Angular + Hono on Cloudflare Workers, LangChainJS, `@cf/openai/whisper`, openai-tts; per-answer feedback. Dead.

## 3. The "Next.js + Gemini/Vapi clone" class

Pattern [SOURCED from adrianhajdin/ai_mock_interviews and modamaan/Ai-mock-Interview]: Next.js app; auth + storage in Firebase or Neon/Drizzle; questions generated by one Gemini prompt (with a "no special characters, the voice assistant will read this" instruction); the interview is a Vapi voice workflow or a text form; feedback is one `generateObject` call to `gemini-2.0-flash-001` returning `totalScore` plus five fixed `categoryScores` (0–100) from a `feedbackSchema` zod tuple. No per-answer judgement, no follow-up logic, no skill state, no evaluation of the judge.

Count in this pass: 7 repos whose description names Next.js/Vapi/Gemini or Flask+Gemini (adrianhajdin 567★, modamaan 120★, preptalk-ai 17★, Rahul2201020931 14★, DeveloperMK07 8★, MR360-TECH 0★, shubham-8863 0★); the JavaScript Mastery template alone has 306 forks and 33 issues, almost all Vapi room / Firebase auth errors (#37 "VAPI WORKFLOW", #36 "Exiting meeting because room was deleted", #33 "Issue in auth"). The `"mock interview" AI` query returns 10,276 repos; the recently-updated slice was 100% ★0 same-day pushes of this shape.

Examples: (1) adrianhajdin/ai_mock_interviews — Next.js 15 + Vapi + Gemini + Firebase, no license, last commit 2025-03-29. (2) modamaan/Ai-mock-Interview — Next.js + Gemini (also OpenAI/Llama modal switch in `utils/`) + Neon Postgres/Drizzle, no license, created 2024-06, last commit 2026-07-29, "overall grade" + "recent interviews".

## 4. Adjacent OSS (one line each; ★ / license / latest release as of 2026-09-02) [SOURCED]

| Project | What | License | ★ | Latest release | Relevant capability | Docs |
|---|---|---|---|---|---|---|
| promptfoo/promptfoo | prompt/agent eval + red-team CLI | MIT | 24,738 | tag 2026-08-28 (per-package tags) | model-graded assertions (`llm-rubric`, `factuality`) in a CI eval matrix | https://www.promptfoo.dev/docs/configuration/expected-outputs/model-graded/ |
| UKGovernmentBEIS/inspect_ai | LLM evaluation framework (UK AISI) | MIT | 2,683 | PyPI only, no GH releases | Task/Solver/Scorer with `model_graded_qa` scorer + log viewer | https://inspect.aisi.org.uk/scorers.html |
| confident-ai/deepeval | LLM evaluation framework | Apache-2.0 | 18,042 | python-v4.2.0 2026-08-24 | G-Eval / DAG judge metrics as pytest cases | https://deepeval.com/docs/metrics-llm-evals |
| livekit/agents | realtime voice-agent framework | Apache-2.0 | 13,951 | livekit-agents@1.7.1 2026-08-27 | `AgentSession` STT→LLM→TTS with turn detection + interruptions (used by DeepInterview, interview-director) | https://docs.livekit.io/agents |
| pipecat-ai/pipecat | voice/multimodal agent pipelines | BSD-2-Clause | 15,114 | v1.8.1 2026-08-27 | frame pipeline, transport-agnostic (Daily/WebRTC/WebSocket) | https://docs.pipecat.ai |
| vocodedev/vocode-core | voice LLM agents (telephony) | MIT | 3,787 | v0.1.113 2024-06-18; last push 2024-11-15 | effectively unmaintained | https://docs.vocode.dev |
| langchain-ai/langgraph | agent orchestration (our stack) | MIT | 40,882 | sdk==0.4.4 2026-08-27 | checkpointers for persistence/resume + `interrupt` | https://docs.langchain.com/oss/python/langgraph/ |
| pydantic/pydantic-ai | typed agent framework | MIT | 19,650 | v2.37.0 2026-09-01 | `pydantic_evals` datasets + `LLMJudge` evaluator | https://ai.pydantic.dev/evals/ |
| openai/openai-agents-python | multi-agent SDK | MIT | 29,128 | v0.22.0 2026-08-19 | handoffs, guardrails, tracing | https://openai.github.io/openai-agents-python/ |
| google/adk-python | agent toolkit with built-in eval | Apache-2.0 | 21,369 | v2.8.0 2026-08-26 | `adk eval` with evalsets (trajectory + response match) | https://google.github.io/adk-docs/evaluate/ |

## 5. Synthesis

### 5.1 Comparison table [SOURCED unless marked]

| Repo | ★ | Last commit | License | Orchestration | Scoring | Judge-quality eval | Voice | VN | Persist/resume | Question source |
|---|---|---|---|---|---|---|---|---|---|---|
| ngoanpv/DeepInterview | 33 | 2026-08-26 | Apache-2.0 | LangGraph prep/post + lean LiveKit live loop | competency scores + coach report | MockLLM tests only | yes (LiveKit; local STT/TTS) | UI strings, wiring open; voice claimed | Supabase / memory | CV+JD plan + md skill packs |
| IliaLarchenko/Interviewer | 126 | 2024-08-17 | Apache-2.0 | single LLM interviewer prompt | end feedback | LLM candidate sim + gpt-4o grader thresholds | yes | no | none (Gradio) | prompt-generated |
| zixi-liu/interview-ai-prototype | 218 | 2026-04-15 | none | single analyzer + learned stop policy | hire / no-hire verdict | 4-judge agreement study (research) | audio in | no | file dumps | fixed BQ set |
| XUZIAa/Multi-Agent-Mock-Interview | 132 | 2026-08-28 | GPL-3.0 | director (slow) + realtime voice (fast) | multi-dim end score | none | full-duplex | no (zh) | SQLite per turn, crash-recoverable | resume-driven |
| 1624899/ai_interview | 64 | 2026-07-07 | NOASSERTION | LangGraph state machine | 5-dim + hire rec + trend | 1 test file | Qwen3-Omni | no (zh) | DB + multi-round | resume+JD plan |
| Azure-Samples/interview-coach | 163 | 2026-08-31 | MIT | 1 agent or 5 handoff agents (MS Agent Framework) | narrative | unit tests | no | no | MCP session store | prompt |
| Tameyer41/liftoff | 1,522 | 2023-06-07 | MIT | single prompt | free-text | none | webcam + Whisper | no | none | fixed |
| jiatastic/GPTInterviewer | 264 | 2024-01-31 | MIT | LangChain single chain | end feedback | none | Azure TTS | no | none | resume/JD via FAISS |
| yuanzhongqiao/ai-interview-platform | 904 | 2026-06-05 | MIT | Next.js tRPC + voice relay | criteria per interview | heuristic guardrail tests | Volcengine relay | no (zh) | Supabase | NL-generated |
| zzzlip/langgraph-AI-interview-agent | 58 | 2026-07-10 | none | Java platform + LangGraph worker | 5-dim + report | none | no | no (zh) | MySQL/MinIO | resume+JD |
| Ranjit2111/AI-Interview-Agent | 5 | 2025-06-30 | none | orchestrator + interviewer + coach agents | per-turn + final score | none | Deepgram | no | Supabase | JD/resume |
| yudongfang-thu/PrepDojo | 30 | 2026-08-23 | MIT | single LLM w/ tool = code judge | code judge + AI quiz score | 15 pytest (no LLM eval) | no | no (zh) | SQLite | user PDFs → cards |
| Chozzc/Lujie-Careerkit | 325 | 2026-08-24 | Apache-2.0 | single prompts per feature | AI review report | vitest | no | no (en/zh) | SQLite | resume+JD |
| prashma03/interview-director | 1 | 2026-09-02 | none | deterministic state machine, LLM talks only | none | vitest | LiveKit + Tavus | no | evidence log | fixed 5 primaries |
| viettungjr-byte/phongvan-ai | 0 | 2026-08-02 | none | single prompt per turn | 5 criteria / 100 | none | Web Speech API | yes (VN only) | MySQL | generated |
| clone class (adrianhajdin et al.) | 567 / 306 forks | 2025-03-29 | none | Vapi workflow + 1 Gemini call | 5 fixed categories 0–100 | none | Vapi | no | Firebase | generated |
| **ours (get-hired)** | — | 2026-09 | — | LangGraph plan-executor; Interviewer / Evaluator / Supervisor | Evaluator BARS 1–5 per dimension → Beta skill state | 35-case VN/EN bench, median-of-k gate, replay bench | no | yes (bilingual judge) | Session export + resume | YAML packs |

### 5.2 Findings

1. **Dominant OSS architecture** [SOURCED]: one "interviewer" prompt for the conversation plus one "feedback" prompt over the whole transcript at the end (liftoff, GPTInterviewer, clone class, nicobytes, phongvan-ai, Lujie). Scores, when present, are a single structured-output call with fixed categories. No project keeps a per-skill state across answers; "progress" means a list of past sessions or (1624899) an averaged trend.
2. **The 2026 cohort converges on separating a lean live loop from heavy offline reasoning** [SOURCED]: DeepInterview (prep/live/post, one fast model on the turn path), XUZIAa (fast "mouth" loop vs slow director), interview-director (state machine owns everything, LLM only talks). Their stated reason is voice latency and persona drift, not judge quality. This matches our ADR 0001 plan-executor stance from a different motivation. [INFERRED]
3. **Judge-quality evaluation: none has a calibrated gate.** [SOURCED] Closest: IliaLarchenko (LLM-simulated candidate + gpt-4o grader with pass thresholds — measures the interviewer, not the judge, and has been dead two years); zixi-liu (four-judge agreement study + learned stop policy — a paper artefact, no license, not wired to CI); DeepInterview (scoring exercised only with `MockLLM`); ai-interview-platform (heuristic guardrails, no judge). Nobody measures score drift across languages or across judge-model changes. Our 35-case bilingual bench with a median-of-k merge gate has no OSS counterpart in this set.
4. **Voice** [SOURCED]: 11 of 16 detailed repos have it (LiveKit ×2, OpenAI-Realtime-style WS, Qwen3-Omni, Deepgram, Vapi, Volcengine, Whisper+TTS, Web Speech API, Azure TTS). Ours has none. The two maintained frameworks behind the serious ones are LiveKit Agents (1.7.1, 2026-08-27) and Pipecat (1.8.1, 2026-08-27); Vocode is unmaintained.
5. **Vietnamese** [SOURCED]: only DeepInterview (VN author; README.vi, EN+VI UI strings shipped but issue #50 to wire the vi pack is open; "voice in 7 languages incl. Vietnamese" claimed, unverified here) and phongvan-ai (★0, default provider `mock`). No repo tests whether its judge scores Vietnamese and English answers the same; ours is the only one that measured it (`correctness` 2 vs 4 split, ADR 0009 addendum d).
6. **What ours has that none of these have** [SOURCED vs each]: (a) a checked-in judge calibration bench with language-fairness cases and a stochastic-aware (median-of-k) gate; (b) Bayesian per-skill state with priors, decay, and role-criticality; (c) a replay bench of live sessions; (d) explicit budget-exhaustion suspend/resume and noise-vs-evidence separation (ADR 0005); (e) a pinned judge role whose failover cannot change model.
7. **What several have that ours lacks** [SOURCED]: voice (11/16); CV + JD-driven question planning (DeepInterview, GPTInterviewer, 1624899, zzzlip, Ranjit, Lujie); an end-of-session narrative report with a hire recommendation (1624899, XUZIAa, DeepInterview); a cross-session progress view (1624899 trend, modamaan "recent interviews", Ranjit replay); a local-model path (DeepInterview, IliaLarchenko, PrepDojo, XUZIAa); question-pack metadata with provenance and decaying confidence (DeepInterview `skills/SCHEMA.md`: `source_runs`, `confidence`, `status`); a learned rather than prompted stop policy for follow-ups (zixi-liu: 88% vs 56% gpt-4o zero-shot); one-command deploy (docker compose / Vercel button) on most.
8. **Maintenance reality** [SOURCED, cutoff = last commit before 2026-03-02]: 6 of 17 detailed repos are dead > 6 months — liftoff (2023-06), GPTInterviewer (2024-01), nicobytes (2024-04), IliaLarchenko (2024-08), adrianhajdin (2025-03), Ranjit2111 (2025-06). The three most-starred (liftoff 1,522; ai-interview-platform 904; adrianhajdin 567) are all inactive; ai-interview-platform gained 904 stars in ten days of commits then stopped. Committed within the last 30 days: DeepInterview, XUZIAa, Azure sample, Lujie, PrepDojo, interview-director. Every repo with a real bug tracker (>3 issues) is either a tutorial (adrianhajdin: auth/Vapi errors) or DeepInterview (1 external bug, 1 CVE sweep).
9. **Licensing** [SOURCED]: 7 of 17 have no license at all (zixi-liu, zzzlip, Ranjit, adrianhajdin, modamaan, phongvan-ai, interview-director, nicobytes); XUZIAa is GPL-3.0. Reusable code is limited to the Apache/MIT set: DeepInterview, IliaLarchenko, PrepDojo, Lujie, liftoff, GPTInterviewer, Azure sample.
