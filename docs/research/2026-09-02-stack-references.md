# Stack references — primary-source facts (accessed 2026-09-02)

Scope: reference facts for the next form of personal-interviewer (voice VN+EN, accounts, longitudinal progress, CV/JD import, employer-side AI-interview simulation). Facts only, no recommendations. Every row cites the URL it was read from; "not verified" = primary page not reachable during this pass, value from memory/secondary.

Row convention: **gives / cost / constraint**.

## 1. Orchestration

| Item | Latest release (2026-09-02) | License | Persistence / resume | Evals story | gives / cost / constraint | Source |
|---|---|---|---|---|---|---|
| LangGraph (`langgraph`) | 1.2.11, 2026-08-11, Python >=3.10 | MIT | Checkpointer optional at compile (`checkpointer`, `store`, or both); persistence "resume after an interruption, recover from a failure" — durability modes (`exit`/`async`/`sync`) and `interrupt()`/`Command(resume=)` API **not verified** on this pass (docs page rendered only the overview) | None built in; LangSmith (separate SaaS) | gives graph + checkpoint replay you already run / $0 library / durable execution requires a checkpointer and idempotent side effects | https://pypi.org/project/langgraph/ ; https://docs.langchain.com/oss/python/langgraph/durable-execution |
| LangGraph PostgresSaver (`langgraph-checkpoint-postgres`) | 3.1.2, 2026-08-07, Python >=3.10 | MIT | Psycopg 3 (`psycopg`, optionally `psycopg[binary]`); must call `.setup()` once to create tables; manual connections need `autocommit=True` and `row_factory=dict_row` | — | gives Postgres-backed checkpoints / $0 + a Postgres / psycopg3-only, one-time `setup()` | https://pypi.org/project/langgraph-checkpoint-postgres/ |
| LangSmith / LangGraph Platform (LangChain pricing) | — | proprietary SaaS | Deployments: Plus "1 free Serverless (Small) deployment", extra deployments billed by vCPU-hours + GiB-hours (rates on page, not captured) | LangSmith traces + "Tuned Evaluators $0.01 LCU per evaluation run" (Plus) | gives hosted graph runtime + tracing / Developer $0 (1 seat, 5k base traces/mo then PAYG), Plus $39/seat/mo (10k base traces/mo), LCU $1.50, LSU $1.00 / **self-hosted & hybrid only on Enterprise**; Developer and Plus are cloud-only; per-node LangGraph Platform pricing no longer listed | https://www.langchain.com/pricing |
| pydantic-ai | 2.37.0, 2026-09-01, Python >=3.10 | MIT | "First-party, co-maintained durable execution on Temporal, DBOS, or Prefect"; Restate/Kitaru/Airflow integrations | "Pydantic Evals tests agent behavior the way pytest tests code" | gives typed agents + evals lib / $0 / durability is delegated to an external engine (Temporal/DBOS/Prefect), not built-in | https://pypi.org/project/pydantic-ai/ |
| OpenAI Agents SDK (`openai-agents`) | 0.22.0, 2026-08-19, Python >=3.10 | MIT | "Sessions: Automatic conversation history management"; extras `redis`, `sqlalchemy`; "Human in the loop: Built-in mechanisms" | Tracing built in; no evals module in package description | gives agent loop + handoffs + guardrails + tracing / $0 lib / sessions = message history, not graph checkpoints | https://pypi.org/project/openai-agents/ |
| Google ADK (`google-adk`) | 2.8.0, 2026-08-26, Python >=3.10 | Apache-2.0 | Session services (Database/VertexAI) **not verified** on PyPI page; deploy to Cloud Run or Vertex AI Agent Engine | `adk eval <agent> <evalset.json>` CLI | gives agent runtime + eval CLI + Gemini-first tooling / $0 lib / deployment story is GCP-centric | https://pypi.org/project/google-adk/ |
| Microsoft Agent Framework (`agent-framework`) | 1.16.0, 2026-08-28, Python >=3.10 | MIT | "workflows and orchestrations" (Sequential, Concurrent, Group Chat, Handoff, Magentic); checkpointing **not verified** from PyPI description | none in description | gives multi-agent orchestration patterns / $0 lib / Azure-leaning; checkpoint API not confirmed | https://pypi.org/project/agent-framework/ |

## 2. Judge / eval

| Item | Fact | gives / cost / constraint | Source |
|---|---|---|---|
| OpenAI Structured Outputs | Guarantee: "the model will always generate responses that adhere to your supplied JSON Schema". JSON mode = valid JSON only, no schema adherence. Requires `strict: true`, `additionalProperties: false`, every property listed in `required`; "some features are unavailable either for performance or technical reasons" (numeric limits on depth/properties/enum count not captured this pass). Safety refusals arrive in a separate `refusal` field. Supported from gpt-4o-2024-08-06 and later; page now recommends **gpt-5.6** for new projects | gives judge output that cannot miss keys or invent enum values / no surcharge / subset of JSON Schema only; refusal path must be handled | https://developers.openai.com/api/docs/guides/structured-outputs |
| promptfoo | MIT; "Test your prompts, agents, and RAGs"; model-graded / llm-rubric assertions, red-teaming, GitHub Action for PR checks; CLI + local web viewer. Version/date not captured (npm returned 403, GitHub release list did not render) | gives declarative eval matrix + CI gate / $0 OSS / Node toolchain, YAML-driven | https://github.com/promptfoo/promptfoo |
| inspect_ai | 0.3.261, 2026-08-30, MIT, Python >=3.10, maintained by UK AI Security Institute; "model graded evaluations", multi-turn dialog, 200+ pre-built evals, log viewer | gives a solver/scorer eval harness with a log viewer / $0 / opinionated Task/Solver/Scorer model | https://pypi.org/project/inspect-ai/ |
| deepeval | 4.2.0, 2026-08-24, Apache-2.0, Python >=3.9,<4.0; "similar to Pytest but specialized for unit testing LLM apps"; metrics incl. G-Eval, Faithfulness, Hallucination, JSON Correctness, Task Completion, Tool Correctness, Role Adherence, Conversation Completeness | gives pytest-style LLM metrics incl. G-Eval / $0 lib (cloud "Confident AI" optional) / metrics are themselves LLM-judged | https://pypi.org/project/deepeval/ |
| LangSmith (tracing/evals) | Developer $0: 1 seat, 5k base traces/mo then PAYG; Plus $39/seat/mo, 10k base traces/mo; Enterprise custom; "Tuned Evaluators $0.01 LCU per evaluation run"; self-hosted/hybrid = Enterprise only | gives tracing + datasets + evaluators tied to LangGraph / free at 5k traces / self-host gated to Enterprise | https://www.langchain.com/pricing |
| Langfuse | Cloud: Hobby $0 "50k units / month", 30-day data access; Core $29/mo 100k units (+$8/100k), 90 days; Pro $199/mo, 3 years; Enterprise $2,499/mo. Self-host: "open source and you can self-host it for free"; needs Postgres + ClickHouse + Redis/Valkey + S3/blob; EE-key features: Organization Creators, Instance Management API, UI Customization. OSS license name not stated on these pages (MIT per repo — **not verified**) | gives tracing/evals/prompt mgmt, self-hostable / $0 self-host or $0–29/mo cloud / self-host is a 4-service stack | https://langfuse.com/pricing ; https://langfuse.com/self-hosting |
| Arize Phoenix | **not verified** this pass (pricing page not fetched); OSS Phoenix is commonly cited as Elastic License 2.0 with a free self-host path | gives OTel-based tracing + evals / $0 OSS / license from memory | — |
| Zheng et al. 2023 (MT-Bench / LLM-as-a-judge) | arXiv 2306.05685, submitted 2023-06-09. Examines "position, verbosity, and self-enhancement biases, as well as limited reasoning ability"; strong judges (GPT-4) reach ">80% agreement, the same level of agreement between humans" | gives the canonical bias list to control for (swap order, length-normalise) / — / agreement figure is on English chat pairs | https://arxiv.org/abs/2306.05685 |
| G-Eval (Liu et al. 2023) | arXiv 2303.16634 — ID supplied by caller; abstract **not re-fetched** this pass. From memory: GPT-4 + chain-of-thought + form-filling, probability-weighted scores | gives the CoT-rubric scoring recipe deepeval implements / — / known to prefer LLM-written text | https://arxiv.org/abs/2303.16634 |
| Prometheus 2 (Kim et al. 2024) | arXiv 2405.01535 — ID supplied by caller; abstract **not re-fetched**. From memory: open evaluator LM supporting direct assessment + pairwise ranking, trained via weight-merging | gives an open-weights judge option / self-host GPU / English-centric training data | https://arxiv.org/abs/2405.01535 |
| Hada et al. 2023 (multilingual judge bias) | arXiv 2309.07462, submitted 2023-09-14: "a bias in GPT4-based evaluators towards higher scores, underscoring the necessity of calibration with native speaker judgments, especially in low-resource and non-Latin script languages"; 20k human judgments, 8 languages, 3 tasks | gives primary evidence that a judge inflates non-English scores without native calibration / — / directly relevant to the VN/EN bench split | https://arxiv.org/abs/2309.07462 |
| MM-Eval (multilingual meta-eval for judges) | arXiv 2410.17578 — **not verified** this pass (ID from memory): multilingual meta-evaluation benchmark for LLM-as-a-judge across ~18 languages | gives a second multilingual judge-bias reference / — / verify ID before citing | — |
| BARS origin | Smith, P. C. & Kendall, L. M. (1963). "Retranslation of expectations: An approach to the construction of unambiguous anchors for rating scales." *Journal of Applied Psychology*, 47(2), 149–155. doi:10.1037/h0047060 — citation from memory, page **not fetched** | gives the provenance for behaviourally-anchored scales used in `packs/` / — / paywalled | — |

## 3. Models & pricing

Prices are USD per 1M tokens unless stated; "cached" = cached-input read price.

| Provider / model | Price (2026-09-02) | Free tier / daily allowance | Strict JSON schema | Native audio | gives / cost / constraint | Source |
|---|---|---|---|---|---|---|
| OpenAI gpt-5.4 | $2.50 in / $0.25 cached / $15.00 out | none stated on pricing page | yes (Structured Outputs, `strict: true`) | via separate Realtime/transcribe/TTS models | gives frontier text model / 6x the mini price / — | https://developers.openai.com/api/docs/pricing |
| OpenAI gpt-5.4-mini (current pinned judge) | $0.75 in / $0.075 cached / $4.50 out | none stated | yes | no | gives the bench-validated judge / ~$0.75+$4.50 per 1M / any switch is bench-gated (ADR 0009) | same |
| OpenAI gpt-5.4-nano | $0.20 in / $0.02 cached / $1.25 out | none stated | yes | no | gives cheapest OpenAI text tier / — / not bench-validated as judge | same |
| OpenAI gpt-5.5 | $5.00 in / $0.50 cached / $30.00 out (<272K context) | — | yes | — | newer, pricier tier exists; Structured Outputs doc "recommends gpt-5.6 for new projects" | same; https://developers.openai.com/api/docs/guides/structured-outputs |
| OpenAI gpt-realtime | text $4.00 in / $0.40 cached / $16.00 out; audio $32.00 in / $0.40 cached / $64.00 out | — | function calling; schema strictness not verified | yes (speech-to-speech) | gives lowest-latency S2S / audio ≈ $0.06/min in + $0.24/min out at ~1k tok/min (derived) / most expensive path | same |
| OpenAI gpt-realtime-mini | text $0.60 / $0.06 cached / $2.40; audio $10.00 in / $0.30 cached / $20.00 out | — | — | yes | gives cheaper S2S / ~1/3 of gpt-realtime / — | same |
| OpenAI transcription | gpt-4o-transcribe $0.006/min; gpt-4o-mini-transcribe $0.003/min; whisper-1 $0.006/min | — | n/a | STT | gives hosted STT incl. Vietnamese (language list not re-verified) / $0.18–0.36 per hour / no published VN WER | same |
| OpenAI TTS | gpt-4o-mini-tts $12.00 per 1M chars; tts-1 $15.00; tts-1-hd $30.00 per 1M chars | — | n/a | TTS | gives multilingual TTS / ~$0.012 per 1k chars / Vietnamese voice quality not verified | same |
| OpenAI Batch API | 50% off input, output and cache ops | — | yes | — | gives half-price offline judging (bench replays) / 50% / async, not for live turns | same |
| Anthropic Claude Fable 5.1 | $10 in / $12.50 5m-cache write / $20 1h-cache write / $0.25 cache hit (0.025x) / $50 out | "New users receive a small amount of free credits" | not stated on pricing page (**not verified**) | not stated (**not verified**) | gives top-tier reasoning / 13x gpt-5.4-mini on input / cache hit unusually cheap (2.5%) | https://platform.claude.com/docs/en/about-claude/pricing |
| Anthropic Claude Opus 5 | $5 in / $6.25 / $10 / $0.50 hit / $25 out; Fast mode $10 in / $50 out (Opus 5 & 4.8 only) | same | — | — | gives Opus tier at half old Opus 4.1 price / 1M context at standard price (4.6+) / 4.7+ tokenizer yields ~30% more tokens for same text | same |
| Anthropic Claude Sonnet 5 | $2 in / $2.50 / $4 / $0.20 hit / $10 out — "introductory pricing … is now the standard price"; the scheduled Sep 1 2026 rise to $3/$15 "will not occur" | same | — | — | gives mid tier / cheaper than gpt-5.4 / — | same |
| Anthropic Claude Haiku 4.5 | $1 in / $1.25 / $2 / $0.10 hit / $5 out | same | — | — | gives cheap Anthropic tier / ~1.3x gpt-5.4-mini in, ~1.1x out / — | same |
| Anthropic Batch | 50% off in+out (e.g. Sonnet 5 $1/$5, Haiku 4.5 $0.50/$2.50); `inference_geo: "us"` = 1.1x | — | — | — | — | same |
| Google Gemini 3.7 Flash / 3.6 Flash | paid $0.75 in / $3.75 out through 2026-12-31, then $1.50 / $7.50 from 2027-01-01 | free tier: input, output and context caching "Free of charge" | `responseSchema` structured output — **not verified** this pass | via Live API models | gives a free-tier text model / $0 on free tier / free tier data-use terms not captured | https://ai.google.dev/gemini-api/docs/pricing |
| Google Gemini 3.5 Flash / 3.5 Flash-Lite | $1.50 / $9.00 ; $0.30 / $2.50 | both free tier | — | — | — | same |
| Google Gemini 3.1 Pro Preview | $2.00 in (≤200k) / $4.00 (>200k); $12.00 / $18.00 out | not listed as free | — | — | — | same |
| Google Gemini 3.1 Flash Live Preview (Live API) | text $0.75 in / $4.50 out; audio $3.00 in (≈$0.005/min) / $12.00 out (≈$0.018/min) | free tier "Free of charge" | — | yes (native audio S2S) | gives cheapest native-audio S2S with a free tier / ~$0.023 per minute paid / preview model; daily free RPD not captured | same |
| Google Gemini 2.5 Flash Preview TTS | text $0.50 in / audio $10.00 out | free tier | n/a | TTS | gives free-tier TTS / — / Vietnamese voice list not verified | same |
| Groq (LLM per-token prices) | **not verified** (groq.com/pricing rendered no numbers) | Free plan (base Developer limits) e.g. openai/gpt-oss-120b & 20b: 30 RPM, 1K RPD, 8K TPM, 200K TPD; qwen/qwen3.6-27b & qwen3.8-27b same; groq/compound 30 RPM, 250 RPD, 70K TPM; whisper-large-v3 & -turbo: 20 RPM, 2K RPD, 7,200 audio-sec/hour, 28,800 audio-sec/day | JSON mode / tool use exist; strict schema **not verified** | STT only (Whisper) | gives free fast inference for cheap roles + 8 h/day free Whisper / $0 at these caps / 200K TPD ceiling; judge bench fails on Groq (repo finding) | https://console.groq.com/docs/rate-limits |
| DeepSeek V4 Flash | cache-hit $0.014 / cache-miss $0.44 / out $1.32 (peak); 50% off off-peak (peak = 01:00–04:00 & 06:00–10:00 UTC Mon–Fri) ; 1M context, 384K max output | no free tier stated | "JSON output: Supported" (strict schema not stated) | no | gives very cheap long-context text / ~$0.44+$1.32 / off-peak-only discount, PRC-hosted | https://api-docs.deepseek.com/quick_start/pricing |
| DeepSeek V4 Pro | cache-hit $0.044 / miss $1.32 / out $3.96 (peak); same off-peak rule | none | JSON output supported | no | — | same |
| Qwen (Alibaba Model Studio) | **not verified** this pass (pricing page not fetched) | — | — | Qwen-Omni family advertises audio | open-weights Qwen also served on Groq free tier (see Groq row) | — |

## 4. Voice (Vietnamese + English)

### 4a. STT

| Vendor / model | Vietnamese availability | Price | Published VN WER | gives / cost / constraint | Source |
|---|---|---|---|---|---|
| OpenAI gpt-4o-transcribe / gpt-4o-mini-transcribe / whisper-1 | Vietnamese in Whisper language list (**not re-verified** this pass) | $0.006 / $0.003 / $0.006 per minute | none published by OpenAI | gives hosted STT on the provider already in the router / $0.18–0.36 per hour / no VN accuracy figure | https://developers.openai.com/api/docs/pricing |
| Deepgram Nova-3 / Nova-2 | `language=vi` listed for `nova-2`/`nova-2-general` and `nova-3`/`nova-3-general`; Nova-3 multilingual (`language=multi`) covers only "English, Spanish, French, German, Hindi, Russian, Portuguese, Japanese, Italian, and Dutch" — Vietnamese excluded | **not verified** (pricing page not fetched) | none | gives streaming STT with `vi` / — / **no VN+EN code-switching in one stream** (must pick `vi` or `en`) | https://developers.deepgram.com/docs/models-languages-overview |
| Google Cloud STT v2 | vi-VN: `chirp_3`, `long`, `short` in region `eu`; `chirp`, `chirp_2` in `asia-southeast1` and `europe-west4`; features: automatic punctuation, model adaptation, word-level confidence (varies by model), profanity filter; "No telephony or speaker diarization models are available for Vietnamese" | **not verified** (pricing page not fetched) | none | gives Chirp 3 for vi-VN with an ASEAN region option (chirp_2 only in asia-southeast1) / — / chirp_3 for vi-VN only in `eu` | https://docs.cloud.google.com/speech-to-text/v2/docs/speech-to-text-supported-languages |
| AssemblyAI | Vietnamese (`vi`) supported by Universal-2 (99 languages); not among Universal-3.5 Pro's 21 languages; streaming for vi not stated | **not verified** (pricing page not fetched) | tier label only: "Good accuracy" = ">10% to ≤25% WER" | gives batch STT with a published accuracy band / — / VN sits in the second tier, newest model excludes it | https://www.assemblyai.com/docs/speech-to-text/pre-recorded-audio/supported-languages |
| Whisper large-v3 (open weights) | **not verified** this pass (repo/model card not fetched); MIT and vi support from memory | self-host GPU | Whisper paper appendix figures **not verified** | gives offline STT baseline / GPU cost / — | — |
| PhoWhisper (VinAI) | Vietnamese-only fine-tune of Whisper; tiny 39M, base 74M, small 244M, medium 769M, large 1.55B; trained on "844-hour dataset that encompasses diverse Vietnamese accents" | BSD-3-Clause, self-host | large: CMV-Vi 8.14, VIVOS 4.67, VLSP2020-T1 13.75, VLSP2020-T2 26.68; small: 11.08 / 6.33 / 15.93 / 32.96 (ICLR 2024 Tiny Papers) | gives the only published VN WER table found / GPU or CPU (small) / Vietnamese-only, no built-in streaming, no EN code-switch | https://github.com/VinAIResearch/PhoWhisper |
| FPT.AI Speech, Viettel AI, Zalo AI (Kiki) | **not verified** this pass (vendor pages not fetched) | — | — | Vietnamese-vendor STT/TTS; pricing and WER unknown | — |

### 4b. TTS with Vietnamese voices

| Vendor | Vietnamese voice | Price | Source |
|---|---|---|---|
| OpenAI gpt-4o-mini-tts / tts-1 / tts-1-hd | multilingual; VN voice quality **not verified** | $12 / $15 / $30 per 1M characters | https://developers.openai.com/api/docs/pricing |
| Gemini 2.5 Flash Preview TTS | VN voice list **not verified** | text $0.50 in / audio $10.00 out per 1M tokens; free tier "Free of charge" | https://ai.google.dev/gemini-api/docs/pricing |
| Google Cloud TTS, Azure Speech, ElevenLabs, FPT.AI, VBee | **not verified** this pass (from memory: Azure `vi-VN-HoaiMyNeural`/`vi-VN-NamMinhNeural`; Google `vi-VN` Standard/Wavenet/Neural2; ElevenLabs multilingual v2 lists Vietnamese; FPT.AI and VBee are VN-native vendors) | — | — |

### 4c. Realtime frameworks

| Framework | License / self-host | What it wires | Latency claim | Source |
|---|---|---|---|---|
| LiveKit Agents | Apache-2.0; "run the entire stack on your own servers, including LiveKit server" | plugins named on page: Deepgram (STT), Cartesia (TTS), OpenAI + Google (LLM), LiveKit Inference API | no framework-level number on page | https://github.com/livekit/agents |
| Pipecat (Daily) | BSD-2-Clause; transports: Daily, LiveKit, Vonage, SmallWebRTCTransport, FastAPI WebSocket, WebSocket Server, WhatsApp, Local | STT: AssemblyAI, AWS, Azure, Deepgram, Google, Groq, OpenAI, Whisper, Speechmatics…; TTS: Azure, Google, ElevenLabs, OpenAI, Piper, Kokoro, XTTS…; LLM: Anthropic, Gemini, Groq, OpenAI, DeepSeek, Qwen, Ollama… | no quantified claim on page | https://github.com/pipecat-ai/pipecat |
| OpenAI Realtime API | hosted only | gpt-realtime / gpt-realtime-mini S2S (prices in §3) | no number on pricing page | https://developers.openai.com/api/docs/pricing |
| Gemini Live API | hosted only | Gemini 3.1 Flash Live Preview native audio (prices in §3, free tier) | no number on pricing page | https://ai.google.dev/gemini-api/docs/pricing |

## 5. Data / persistence

| Item | Fact | gives / cost / constraint | Source |
|---|---|---|---|
| Supabase Free | "500 MB database size (Shared CPU • 500 MB RAM)", "50,000 monthly active users", "1 GB file storage", "5 GB egress" + "5 GB cached egress", 2 active projects, "Free projects are paused after 1 week of inactivity"; Auth included (anonymous sign-ins, social OAuth); pgvector not named on pricing page (available as a Postgres extension — **not verified** here) | gives auth + Postgres + storage on one free project / $0 / 500 MB and auto-pause after 7 idle days | https://supabase.com/pricing |
| Supabase Pro | "$25/month": "8 GB disk size per project (then $0.125 per GB)", "100,000 monthly active users (then $0.00325 per MAU)", "100 GB file storage", "250 GB egress (then $0.09 per GB)" | — | same |
| Neon Free | "100" projects, "0.5 GB/project" storage, "100 CU-hours/project", "10" branches, autosuspend "After 5 min" | gives branchable serverless Postgres / $0 / cold start after 5 min idle | https://neon.com/pricing |
| Neon Launch | "Pay for what you use": "$0.35/GB-month", "$0.106/CU-hour", "10 included, then $1.50/branch-month", autosuspend "can be disabled" | — | same |
| Turso | **not verified** this pass | libSQL/SQLite-compatible hosted DB | — |
| pgvector | PostgreSQL License (from memory, **not verified**) | vectors inside the same Postgres as auth/state / $0 / — | — |
| Chroma | Apache-2.0 (from memory, **not verified**; current repo dependency) | — | — |
| Qdrant | Apache-2.0 (from memory, **not verified**) | — | — |
| LangGraph PostgresSaver requirements | see §1: `langgraph-checkpoint-postgres` 3.1.2, Psycopg 3, one-time `.setup()`, `autocommit=True` + `row_factory=dict_row` on manual connections | gives durable checkpoints on any of the Postgres offers above / — / needs a Postgres, not SQLite | https://pypi.org/project/langgraph-checkpoint-postgres/ |

## 6. Frontend / distribution

| Item | Fact | gives / cost / constraint | Source |
|---|---|---|---|
| Zalo Mini App | SDK: `npm install zmp-sdk`; "Mini apps operate exclusively within Zalo's native environment using the ZMP framework". Identity APIs: `getUserInfo`, `getPhoneNumber`, `getAccessToken`, `authorize`. Media: `openMediaPicker` ("Mở cửa sổ chọn media (camera, ảnh, file, video)"), `chooseImage`, `createCameraContext`, `takePhoto` — **no microphone/audio-recording API listed in the index**. Storage: `setItem`/`getItem`, `saveFile`, `getSavedFileList`, `downloadFile`. Navigation: `openWebview`, `openMiniApp`, `closeApp`. Payment APIs not in this index (a separate "Payment" section exists on the docs home). Review/approval and content restrictions **not captured** | gives Zalo-native identity + phone number for VN users / $0 SDK / runs only inside Zalo; no recordAudio API found, so a voice interview would need a webview or `getUserMedia` inside the webview (**not verified**) | https://docs.zaloplatforms.com/docs/MA/api/intro ; https://miniapp.zaloplatforms.com/documents/ |
| Next.js vs Vite SPA | **not verified** this pass (no doc page fetched). From memory: Next.js = React with server rendering/route handlers/middleware (auth cookies server-side); Vite = client SPA build tool, SSR only via separate frameworks; both can register a PWA service worker | — | — |
| Expo (React Native) | **not verified** this pass | native iOS/Android + web from one codebase; mic access via `expo-av`/`expo-audio` (from memory) | — |
| PWA on Android | **not verified** this pass | installable web app; `getUserMedia` mic works in Chrome PWAs (from memory); no store listing needed | — |

## 7. Vietnamese NLP assets

| Asset | License | Gives | Source |
|---|---|---|---|
| PhoBERT (VinAI) | page lists "MIT License and GNU Affero GPL v3" (dual listing — check `LICENSE` before commercial use) | `vinai/phobert-base` 135M, `-large` 370M, `-base-v2` 135M; pre-trained on "20GB of Wikipedia and News texts" (+120 GB OSCAR-2301 for v2); evaluated on POS, dependency parsing, NER, NLI; Findings of EMNLP 2020 | https://github.com/VinAIResearch/PhoBERT |
| VnCoreNLP | "See LICENSE.md" — terms **not captured** (research vs commercial not verified) | word segmentation, POS tagging, NER, dependency parsing; Java 1.8+; Python wrapper `py_vncorenlp`; NAACL 2018 demo | https://github.com/vncorenlp/VnCoreNLP |
| ViSoBERT | **not verified** (from memory: social-media Vietnamese BERT, EMNLP 2023) | — | — |
| underthesea | **not verified** (GPL-3.0 from memory) | pure-Python VN word segmentation / POS / NER | — |
| multilingual-e5 | **not verified** this pass (MIT from memory; repo's VN A/B winner per project memory) | multilingual embeddings incl. vi | — |
| bge-m3 | **not verified** this pass (MIT from memory; 100+ languages incl. vi) | dense + sparse + multi-vector retrieval | — |
| Diacritic (tone-mark) restoration | **not verified**; no primary page fetched | toneless→toned Vietnamese; relevant to the #78/#120 detector line | — |

## 8. Deployment cost

| Provider | Price (2026-09-02) | Region near VN | gives / cost / constraint | Source |
|---|---|---|---|---|
| Fly.io | shared-cpu-1x 256 MB "$2.02"/mo; shared-cpu-1x 1 GB "$5.92"/mo; volumes "$0.15/GB per month of provisioned capacity"; egress Asia-Pacific "$0.04 per GB"; first 10 single-hostname certs free; volume snapshots "First 10GB free each month"; no general free compute allowance stated | Singapore (`sin`) listed | gives per-machine Docker hosting with a VN-adjacent region / ~$6/mo for 1 GB / no free tier | https://fly.io/docs/about/pricing/ |
| Railway | Free Trial "$5 one-time credit (30 days)"; Free "$1/month" credit; Hobby "$5/month" (incl. $5 usage); Pro "$20/month per workspace" (incl. $20); CPU "$0.00000772 per vCPU/s" (≈$20/vCPU-mo); RAM "$0.00000386 per GB/s" (≈$10/GB-mo); egress "$0.05 per GB (services)"; volumes ≈"$0.15 per GB" mo | Asia regions not stated on pricing page | gives git-push Docker + Postgres / ~$5/mo minimum / usage-billed CPU/RAM | https://railway.com/pricing |
| Render | **not verified** this pass (pricing page not fetched) | Singapore region exists (from memory) | — | — |
| Hetzner Cloud | plan table did not render (placeholder "starting from max/mo."); page states Hetzner "provides cloud instances in Singapore" | Singapore | gives cheapest raw VPS in the set / EUR pricing **not captured** / no managed services | https://www.hetzner.com/cloud/ |
| Viettel IDC, VNG Cloud, FPT Cloud | **not verified** this pass (VN vendor pricing pages not fetched) | in-country (HN/HCM) | in-country hosting is the data-residency lever for §9 / pricing unknown / — | — |

## 9. Compliance facts

| Item | Fact | Constraint it imposes | Source |
|---|---|---|---|
| Vietnam Decree 13/2023/NĐ-CP (personal data protection) | Primary text **not reachable** this pass (thuvienphapluat 403; chinhphu.vn PDF path 404). From memory, **not verified**: effective 2023-07-01; consent must be explicit, voluntary, verifiable, silence is not consent (Art. 11); sensitive data list includes biometric data and health data (Art. 2); controllers must file a personal-data processing impact assessment dossier with A05/MPS within 60 days of starting processing (Art. 24); separate dossier for cross-border transfer of Vietnamese citizens' data (Art. 25); data subjects may request deletion (Art. 9, Art. 16) | voice recordings + CV/JD are personal data; audio/biometrics may be sensitive; storing them on non-VN hosts triggers the transfer dossier | — |
| Vietnam Law on Personal Data Protection (Luật Bảo vệ dữ liệu cá nhân, 91/2025/QH15) | From memory, **not verified**: passed 2025-06-26, effective 2026-01-01, layered on top of / superseding parts of Decree 13; adds administrative fines up to a % of revenue for violations | in force on the access date — any storage design must be checked against the Law, not only the Decree | — |
| HackerRank / Google / Amazon policies on AI interview copilots | **not verified** this pass (no vendor statement page fetched; WebSearch budget exhausted). From memory: Amazon told candidates (early 2025) that unauthorised AI tools during interviews are disqualifying; Google leadership said it is increasing in-person interview rounds; HackerRank publishes an AI-use position for its assessments | an employer-side "AI interview" simulation must not double as a live-interview copilot | — |

## 10. Addendum — direct verifications after the main pass (2026-09-02, WebFetch only)

| Item | Fact | Source |
|---|---|---|
| Whisper (OpenAI) | MIT; sizes tiny 39M → large 1550M, `turbo` 809M = "optimized version of large-v3 … minimal degradation in accuracy"; README has a per-language WER chart (Common Voice 15 / Fleurs) but the Vietnamese figure was not readable in the fetch | https://github.com/openai/whisper |
| Deepgram pricing | Free "$200 Credit"; Nova-3 streaming monolingual "$0.0048/min" (regular $0.0077), multilingual "$0.0058/min"; pre-recorded mono "$0.0043/min"; TTS Aura-2 "$0.030/1k characters" | https://deepgram.com/pricing |
| AssemblyAI pricing | Pre-recorded Universal-2 "$0.15/hr", Universal-3.5 Pro "$0.21/hr"; streaming Universal-Streaming (EN / Multilingual) "$0.15/hr", U-3.5 Pro realtime "$0.45/hr"; billed on **WebSocket session duration, idle time counts**; "$50 in free credits" | https://www.assemblyai.com/pricing |
| Azure Speech vi-VN | TTS neural voices `vi-VN-HoaiMyNeural` (F), `vi-VN-NamMinhNeural` (M) — standard voices, no styles; STT vi-VN: fast transcription ✅, post-stream refinement ✗; pronunciation assessment: vi-VN not listed | https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts |
| LangGraph `interrupt()` | Needs "A checkpointer to persist the graph state" + "A thread ID"; on resume "The node restarts from the beginning of the node where the interrupt was called"; "side effects called before interrupt should (ideally) be idempotent"; resume value = return of `interrupt()` via `Command(resume=...)` | https://docs.langchain.com/oss/python/langgraph/interrupts |
| LangGraph durability modes | Page fetched rendered only the persistence overview; mode names (`exit`/`async`/`sync`) **still not verified** | https://docs.langchain.com/oss/python/langgraph/durable-execution |
| pgvector | v0.8.6; HNSW + IVFFlat; up to 16,000 dims (vector/halfvec), 64,000 binary; license file present, name not rendered (PostgreSQL License from memory) | https://github.com/pgvector/pgvector |
| Chroma | Apache-2.0; in-memory, persistent local, and client-server (`chroma run --path`) modes | https://github.com/chroma-core/chroma |
| underthesea | **Apache-2.0**; Python 3.10–3.14; word segmentation, POS, NER, sentiment, classification, language detection, **text normalization + diacritics restoration**, dependency parsing; v9.3.0+; now framed as an "Agentic AI Toolkit with built-in Vietnamese NLP" | https://github.com/undertheseanlp/underthesea |
| multilingual-e5-small | Model card not rendered (HF page truncated) — license/dims **still not verified** here; repo already pins it as the vn/mixed embedder | https://huggingface.co/intfloat/multilingual-e5-small |
| Google STT pricing, Render pricing | pages did not render numbers — **not verified** | — |
