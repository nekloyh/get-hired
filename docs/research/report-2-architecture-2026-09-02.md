# Report 2 — Tech stack và kiến trúc phù hợp cho form kế tiếp

**Ngày:** 2026-09-02 · **Anchor code:** `docs/audits/baseline-2026-09-02.md` (main @ `2dac711`)
**Nguồn:** `docs/research/2026-09-02-stack-references.md` (STK), `docs/research/2026-09-02-oss-landscape.md` (OSS),
`docs/research/2026-09-02-market-landscape.md` (MKT), Report 1 (tính năng mục tiêu). Tag như Report 1:
`[SOURCED §x]` · `[MEASURED]` · `[INFERRED]` · `[OPINION]`. Priority: (1) học agentic → (2) prep tool → (3) signal.

---

## 0. Kết luận ngắn

1. **Giữ lõi Python hiện tại, không rewrite.** LangGraph 1.2.11 (MIT), pinned judge + bench, Beta state, packs là phần đã đo và không OSS nào có `[SOURCED STK §1]` `[SOURCED OSS §5.2.6]`. Rewrite sang Next.js/Vapi (mẫu clone) sẽ đưa ta về đúng kiến trúc "một prompt + một feedback" mà OSS §5.2.1 cho thấy là mặt bằng chung.
2. **Voice là transport, text là sự thật.** STT ở mép → cùng micro-loop → judge chấm transcript; TTS đọc câu hỏi. Không dùng speech-to-speech cho judge: mất transcript (bench vô hiệu), audio $32/$64 per 1M token so với text mini $0.75/$4.50 `[SOURCED STK §3]`. Cohort OSS 2026 cũng tách "live loop mỏng" khỏi "reasoning nặng" `[SOURCED OSS §5.2.2]`.
3. **Một Postgres cho tất cả** (Supabase: Auth + Postgres + pgvector + Storage): thay SqliteSaver bằng `PostgresSaver` 3.1.2, ledger JSON → bảng, exports → storage, concept vectors → pgvector **tính sẵn lúc pack lint** (bỏ sentence-transformers khỏi runtime — đóng lỗ hổng Docker không có rag extras) `[SOURCED STK §1, §5]` `[MEASURED baseline §6.12]`.
4. **Judge: giữ đơn, pin, bench-gate; giảm chi phí bằng Batch API 50% cho bench và role table thật cho các role rẻ** (nano/Gemini Flash free tier cho interviewer/planner; judge không đổi nếu không qua bench) `[SOURCED STK §3]`.
5. **Không phụ thuộc LangGraph Platform** (self-host chỉ ở Enterprise) `[SOURCED STK §1]`; deploy Docker trên Fly `sin` (~$6/tháng) hoặc VPS; **không lưu audio** để tránh xếp loại dữ liệu nhạy cảm và hồ sơ chuyển dữ liệu xuyên biên giới (Nghị định 13 — văn bản gốc chưa verify) `[SOURCED STK §9]`.

---

## 1. Ràng buộc đầu vào

**Từ baseline (đã đo, không tranh cãi lại):**
- Judge `gpt-5.4-mini` 35/35 median-of-k k=3, 4 invocation liên tiếp; 192k token/invocation `[MEASURED]`. Mọi thay đổi judge (prompt, anchor, model, cả STT nếu đổi nội dung transcript) phải qua gate này.
- LangGraph `StateGraph` + `SqliteSaver`, resume theo `thread_id` hoạt động; budget rail nằm ở driver ngoài graph `[MEASURED baseline §2]`.
- Debt kiến trúc đang sống: `insufficient_quota` bị nuốt trong `question_node` (#119); replay artifact không mang pack (#113); rubric thiếu anchor (#96/#103 + `mlops_awareness` chỉ 1/5); MiMo default trong config; Docker không có rag extras; không có test ADR 0006; voice/accounts/dashboard chưa có `[MEASURED baseline §6]`.

**Từ Report 1 (tính năng mục tiêu):** accounts, dashboard, CV/JD import, voice VN/EN, delivery analytics, persona "AI interviewer nhà tuyển dụng", Judge Card, coaching memory, pack provenance.

**Từ priority:** (1) mỗi thành phần mới phải dạy một bài agentic có thể đo (eval, memory boundary, control), (2) plumbing dùng dịch vụ có sẵn thay vì tự viết, (3) thứ công khai được phải tái sử dụng được.

---

## 2. Nguyên tắc kiến trúc (5 điều)

| # | Nguyên tắc | Vì sao (evidence) |
| --- | --- | --- |
| P1 | **Text là nguồn sự thật; mọi modality là adapter** vào cùng micro-loop | Bench chấm text `[MEASURED]`; S2S không cho transcript đáng tin và đắt `[SOURCED STK §3]`; Hada 2023: judge cần calibrate theo ngôn ngữ — chỉ làm được trên text `[SOURCED STK §2]` |
| P2 | **Director deterministic giữ state, LLM chỉ "nói" và "chấm"** (ADR 0001) | 3 repo OSS 2026 độc lập đi đến cùng kết luận vì persona drift/latency `[SOURCED OSS §5.2.2]`; LangGraph `interrupt()` re-run node từ đầu → side effect phải idempotent `[SOURCED STK §10]` |
| P3 | **Judge đơn, pin, bench-gated; mọi tín hiệu phụ (vote, delivery) chỉ đo uncertainty hoặc trục khác, không sửa điểm** | Forced-escalation Δ 0.00 `[MEASURED]`; ADR 0011 |
| P4 | **Nội dung và persona là data có provenance** (pack) | ADR 0008/0014; DeepInterview schema `source_runs/confidence/status` `[SOURCED OSS §2.1]` |
| P5 | **Plumbing mua, không xây**: auth/DB/storage/STT/TTS là dịch vụ; tự viết chỉ ở judge, skill state, control loop, bench | Priority (1) vs (2); 6/17 OSS chết vì gánh hạ tầng (zzzlip: Spring + MySQL + Redis + RabbitMQ + MinIO cho ★58) `[SOURCED OSS §2.10, §5.2.8]` |

---

## 3. Ba phương án và lựa chọn

| | A. Giữ lõi Python + thêm adapter (đề xuất) | B. Rewrite TypeScript (Next.js + Vercel AI SDK + Vapi/LiveKit) | C. Realtime S2S agent (LiveKit/Pipecat + OpenAI Realtime / Gemini Live) |
| --- | --- | --- | --- |
| (1) Học agentic | Giữ toàn bộ bài học đã có (eval gate, memory boundary, control); thêm bài "voice pipeline như transport" | Mất bench/replay/skill state; học lại từ mẫu clone `[SOURCED OSS §3]` | Học realtime nhưng **mất khả năng đo judge** — trái ADR 0009 |
| (2) Tool dùng được | Cần thêm accounts/dashboard/voice — đều là adapter | Nhanh ở UI, chậm ở chất lượng chấm | Trải nghiệm tự nhiên nhất, latency thấp nhất |
| (3) Signal | Bench công khai là thứ hiếm `[SOURCED OSS §5.2.3]` | Giống 10,276 repo khác | Ấn tượng demo, không có số liệu |
| Chi phí/Session (20 phút) | Text ≈ $0.04; + STT ≈ $0.05–0.10; + TTS ≈ $0.02 `[INFERRED §6]` | tương tự A nếu giữ judge riêng | Realtime ≈ $3/Session; Gemini Live ≈ $0.46 `[INFERRED §6]` |
| Rủi ro | Voice VN code-switch (STT) | Regress priority (1) | Persona drift sau 30 phút (XUZIAa ghi nhận), không transcript chuẩn `[SOURCED OSS §2.4]` |
| **Chọn** | **A** | — | Chỉ như *persona* B3 tuỳ chọn về sau, judge vẫn chấm transcript |

`[OPINION]` A thắng vì cả ba priority; ADR 0004 addendum đã ghi "migration away buys nothing at this scale".

---

## 4. Kiến trúc đề xuất (final form)

```
                ┌──────────── Presentation (Vite SPA → PWA, VN-first) ────────────┐
                │ Setup/CV import · Interview room (text | voice) · Dashboard · Judge Card │
                └────────────┬───────────────────────────────┬──────────────────────┘
                   WS/HTTP (FastAPI)                 Audio WS (adapter)
                ┌────────────▼───────────┐   ┌────────────────▼────────────────┐
                │ Session driver (budget  │   │ Voice adapter: STT (stream) →  │
                │ rails, suspend/resume)  │◄──┤ transcript + timings; TTS ←    │
                └────────────┬───────────┘   │ question text. No audio stored │
                             │                └─────────────────────────────────┘
        ┌────────────────────▼───────────────────────────────────────┐
        │ LangGraph StateGraph (Supervisor plan-executor, rails)     │
        │  question_node → run_micro_loop(Interviewer ⇄ Evaluator)   │
        │  study_plan_node (Planner; coaching memory: ledger delta)  │
        └───────┬───────────────┬──────────────────┬─────────────────┘
        Interviewer role     Judge role (pinned)   Delivery analytics (deterministic)
        (cheap model, tools) (bench-gated)         (từ timestamps, không LLM)
                │               │
        ┌───────▼───────────────▼─────────────────────────────────────┐
        │ Content: packs (questions, concepts, personas, criticality) │
        │ + precomputed embeddings (pack lint) → pgvector             │
        └───────────────────────┬─────────────────────────────────────┘
        ┌───────────────────────▼─────────────────────────────────────┐
        │ Postgres (Supabase): auth · checkpoints (PostgresSaver) ·   │
        │ ledger (Beta per skill) · exports · usage · bench artifacts │
        └─────────────────────────────────────────────────────────────┘
        Eval stack (offline): coach bench (k=3, Batch API) · replay bench (CLI) ·
        retrieval eval (62→150) · serde goldens · voice WER/latency memo
```

### 4.1 Orchestration — giữ LangGraph, đổi checkpointer
- `langgraph` 1.2.11 MIT; `langgraph-checkpoint-postgres` 3.1.2 cần Psycopg 3 + `.setup()` một lần `[SOURCED STK §1]`. Đổi `SqliteSaver` → `PostgresSaver` khi A2 (accounts) lên; giữ SQLite cho CLI/dev.
- `interrupt()`: node **chạy lại từ đầu** khi resume, side effect trước interrupt phải idempotent `[SOURCED STK §10]`. Áp dụng cho: budget suspend (đưa rail **vào** graph như một `interrupt` thay vì driver-side — đóng debt #9 baseline và làm #119 sửa tự nhiên: quota error → interrupt, không phải `failed`), và cho web "chờ candidate trả lời".
- Không dùng LangGraph Platform/LangSmith trả phí (self-host Enterprise-only; Developer 5k trace/tháng free có thể dùng cho tracing) `[SOURCED STK §1, §2]`.
- Không đổi sang pydantic-ai/OpenAI Agents/ADK: không framework nào có checkpoint graph + evals cùng lúc theo cách ta cần; pydantic-ai delegates durability sang Temporal/DBOS `[SOURCED STK §1]`. Nếu muốn học thêm framework: dùng `pydantic_evals` hoặc `inspect_ai` **cho replay bench harness**, không cho control loop `[OPINION]`.

### 4.2 Judge & roles
- Judge: `gpt-5.4-mini` pin, Structured Outputs strict `[SOURCED STK §2]`. Structured Outputs doc nay khuyến nghị gpt-5.6; gpt-5.5 $5/$30 `[SOURCED STK §3]` → nâng judge chỉ qua R-17 (backup judge program) với k=3 ≥ 3 invocation.
- **Role table mặc định thật** (ADR 0010 hiện chỉ là comment `.env.example`) `[MEASURED baseline drift D20]`: interviewer/planner/diagnostic → `gpt-5.4-nano` ($0.20/$1.25) hoặc Gemini Flash free tier (availability tier, không bao giờ judge) `[SOURCED STK §3]`; supervisor → mini (cần reasoning) — đo bằng replay bench.
- **Bench chạy qua Batch API** (−50%, offline) `[SOURCED STK §3]`: 192k token/invocation ×3 → chi phí giảm nửa; cho phép "3 invocation liên tiếp" thành thói quen thay vì ngoại lệ.
- Derived confidence (ADR 0011): 3 vote trên Groq free (200K TPD) hoặc nano `[SOURCED STK §3]` — chỉ khi E4 xanh.
- Giữ rubric BARS đầy đủ anchor: đóng #96, #103, và **`mlops_awareness` (chỉ 1/5)** `[MEASURED baseline §6.3]`; Hada 2023 là lý do học thuật để publish Judge Card kèm EN/VN |Δ| `[SOURCED STK §2]`.

### 4.3 Skill state, memory, coaching
- Beta state + ledger giữ nguyên toán; chuyển lưu trữ sang bảng Postgres `skill_posteriors(candidate, skill, alpha, beta, updated_at)`; decay tính lúc đọc như hiện tại.
- Coaching memory: planner nhận `ledger_delta` (đã có trong export) + tóm tắt **do code tạo** (không LLM) về Skill yếu lần trước; **thêm prompt-construction tests** cho 3 probing agent (đóng drift D12).
- Learned stop policy (zixi-liu 88% vs 56%) `[SOURCED OSS §2.3]`: **không** thay `follow_up_recommended` bằng model học; ghi là experiment E7 khi có ≥ 200 Session thật.

### 4.4 Content & retrieval
- Packs mở rộng theo ADR 0014 (skills/criticality/correlations) + provenance (`source_runs`, `confidence`, `status`, `reviewed_by`) + **persona** (Interviewer style + format cho B3).
- **Embeddings tính lúc `coach pack lint`** bằng multilingual-e5-small (đã A/B thắng VN 6/7) `[MEASURED]`, lưu vector vào pack artifact và pgvector (HNSW, ≤16k dim) `[SOURCED STK §10]`. Runtime chỉ cần embed **query** — giữ một encoder nhỏ trong image *hoặc* dùng OpenAI embeddings cho query (đo lại 62-case set trước). Loại bỏ Chroma + runtime sentence-transformers khỏi image; giữ `InMemoryConceptStore` cho test.
- Retrieval eval: nâng frozen set 62 → 150 (`TARGET_SET_SIZE`) `[MEASURED]`, chạy trong CI trên in-memory, chạy pgvector theo tay.

### 4.5 Voice adapter (VN + EN)
| Lớp | Lựa chọn | Fact | Tag |
| --- | --- | --- | --- |
| Transport | FastAPI WebSocket audio frames (tự viết, mỏng) **hoặc** Pipecat (BSD-2, có `FastAPI WebSocket` transport, plugin STT/TTS đa vendor) | Pipecat 1.8.1 2026-08-27; LiveKit Agents 1.7.1 Apache-2.0 self-host nhưng kéo theo LiveKit server | `[SOURCED STK §4c]` `[SOURCED OSS §4]` |
| STT (cloud) | **Azure Speech** vi-VN fast transcription; **Deepgram Nova-3** `vi` $0.0048/phút streaming; **AssemblyAI** Universal-2 vi $0.15/giờ (band WER 10–25%, billed theo thời gian socket) | Deepgram multi-mode **không** có vi → không code-switch trong một stream; AssemblyAI U-3.5 Pro bỏ vi | `[SOURCED STK §4a, §10]` |
| STT (self-host) | **PhoWhisper** (BSD-3) — WER công bố VIVOS 4.67 / CMV-Vi 8.14 (large), 6.33 / 11.08 (small); Whisper large-v3/turbo MIT đa ngôn ngữ; Groq free Whisper 28,800 giây/ngày | PhoWhisper VN-only, không streaming → dùng chunked | `[SOURCED STK §4a, §3, §10]` |
| Code-switch | Ẩn số lớn nhất: VN + thuật ngữ EN trong một câu. Ứng viên: Whisper-class multilingual (Groq/self-host) cho mixed; Azure/Deepgram `vi` cho vn; `en` cho en — chọn theo `language_mode` của Session (đã là state, ADR 0007) | Chưa có vendor nào công bố WER code-switch VN/EN | `[INFERRED]` |
| TTS | Azure `vi-VN-HoaiMyNeural`/`vi-VN-NamMinhNeural`; OpenAI gpt-4o-mini-tts $12/1M ký tự; Gemini TTS free tier | Chất lượng giọng VN của OpenAI/Gemini chưa verify | `[SOURCED STK §10, §3]` |
| Không lưu audio | STT → transcript + timestamps → xoá audio; delivery analytics tính từ timestamps | Tránh dữ liệu sinh trắc/nhạy cảm và hồ sơ chuyển xuyên biên giới (Nghị định 13, chưa verify văn bản) | `[SOURCED STK §9]` `[OPINION]` |

**Gate trước khi viết product code (spike #87):** 5 mẫu VN code-switch (có/không dấu) × 3 STT → WER-ish, latency, $/phút; quyết định đường đi. Sau đó **bench judge phải byte-identical** (voice không chạm prompt judge). Diacritic restoration của **underthesea (Apache-2.0)** `[SOURCED STK §10]` là ứng viên thay curated word list #78 (đang ở ceiling) `[MEASURED baseline §6.4]`.

### 4.6 Persona "AI interviewer nhà tuyển dụng" (B3)
- Là **pack data**: `persona.yaml` (giọng điệu, độ dài, format: conversational phone-screen / async 1-shot có timer / chat screening), map vào Interviewer prompt block và micro-loop parameters (`max_turns`, time limit). Judge không đọc persona → test invariance: cùng transcript, mọi persona → cùng Evaluation `[INFERRED từ ADR 0001/0007]`.

### 4.7 Data & auth
- **Supabase**: Free 500 MB, 50k MAU, pause sau 7 ngày idle (chấp nhận cho dev; Pro $25/tháng khi có user thật) `[SOURCED STK §5]`. Neon (autosuspend 5 phút) là backup nếu chỉ cần Postgres `[SOURCED STK §5]`.
- Bảng: `candidates`, `sessions` (checkpoint qua PostgresSaver), `skill_posteriors`, `exports` (Storage), `usage_ledger` (thay JSONL), `bench_runs` (audit machine-readable cho Judge Card).
- RLS theo `candidate_id`; token chia sẻ hiện tại chỉ giữ cho CLI/dev.

### 4.8 Frontend & phân phối
- Giữ Vite SPA (React 19) → PWA installable (mic qua `getUserMedia`), i18n 2 locale, dashboard, Judge Card page. Next.js không cần: không SSR/SEO cho app đăng nhập `[OPINION]`.
- Zalo Mini App: có `getUserInfo`/`getPhoneNumber`, **không có API ghi âm** → chỉ dùng cho login/chia sẻ, phỏng vấn mở webview `[SOURCED STK §6]`.

### 4.9 Deploy, chi phí, tuân thủ
- Docker hiện tại + Fly.io `sin` shared-cpu-1x 1 GB $5.92/tháng hoặc Railway Hobby $5 `[SOURCED STK §8]`; Hetzner SG nếu cần rẻ hơn (giá chưa capture).
- Nếu về sau **có** lưu audio/CV lâu dài: cân nhắc host trong nước (Viettel IDC/VNG/FPT — giá chưa verify) vì hồ sơ chuyển dữ liệu xuyên biên giới `[SOURCED STK §9]`. Mặc định: transcript-only, retention exports có TTL (đóng debt #11).
- Observability: giữ `llm-call` trace; thêm bảng `session_metrics` (token, latency p50/p95, calls per provider) — baseline không có số token/Session thực `[MEASURED baseline §5]`. Langfuse self-host (4 service) hoặc LangSmith Developer free — tuỳ chọn, không bắt buộc.

---

## 5. Bảng stack: hiện tại → đề xuất

| Lớp | Hiện tại (baseline) | Đề xuất | Lý do / evidence | Đổi lớn? |
| --- | --- | --- | --- | --- |
| Ngôn ngữ/runtime | Python 3.12, uv | giữ | — | KEEP |
| Orchestration | LangGraph + SqliteSaver | LangGraph + PostgresSaver (web), SqliteSaver (CLI) | STK §1; budget rail → `interrupt` | REFACTOR |
| Judge | gpt-5.4-mini pinned, strict schema, bench k=3 | giữ; Batch API cho bench; anchors đầy đủ | STK §2, §3; baseline §6.3 | KEEP + FIX |
| Roles rẻ | primary provider + temp toàn cục (mimo default!) | role table mặc định: nano/Gemini Flash/Groq (availability), temp per-role; xoá MiMo | baseline D20, §6.8 | FIX |
| Skill state | Beta + JSON ledger file | Beta + bảng Postgres | — | REFACTOR |
| Content | YAML packs, bank trong package, Chroma runtime | packs + provenance + persona; embeddings precomputed → pgvector | ADR 0014; STK §10 | NEW + REFACTOR |
| Retrieval | Chroma + e5/bge runtime; toy in-memory trong Docker | pgvector + query encoder nhỏ; in-memory cho test | baseline §6.12 | REFACTOR |
| Voice | không | adapter WS: STT (Azure/Deepgram/PhoWhisper) → text; TTS; không lưu audio | STK §4 | NEW |
| Delivery analytics | `english_delivery` (LLM) | + deterministic pace/pause/filler từ timestamps | ADR 0007 | NEW |
| Web API | FastAPI WS + shared token | FastAPI WS + Supabase JWT + RLS; `session_suspended` message type riêng | baseline §6.9 | REFACTOR |
| Frontend | Vite React SPA, EN chrome | PWA, i18n VN-first, dashboard, Judge Card | Report 1 A3/A4/C1 | NEW |
| Auth/DB | không / SQLite / JSONL | Supabase (Auth, Postgres, Storage) | STK §5 | NEW |
| Eval | bench (không CI), replay (không CLI), retrieval 62, goldens | bench Batch + JSON artifact; `coach replay` CLI + pack trong artifact (#113); retrieval → 150; voice memo | ADR 0009c; baseline §6.14 | FIX |
| Deploy | Docker + nginx compose, VPS runbook | + Fly/Railway config; exports TTL | STK §8 | KEEP + FIX |
| Observability | `llm-call` trace, counters | + `session_metrics` bảng | baseline §5 | NEW (nhỏ) |

---

## 6. Chi phí ước tính mỗi Session (5 câu, ~20 phút) `[INFERRED từ STK §3, §4; sizing usage.py]`

| Cấu hình | Thành phần | Ước tính |
| --- | --- | --- |
| Text hiện tại | ~27k token/Session (1k setup + 5.2k/câu) trên gpt-5.4-mini, giả định 80% input | ≈ $0.04 |
| + roles rẻ | interviewer/planner sang nano | ≈ $0.03 |
| + Voice (cloud STT) | 20 phút Deepgram vi $0.0048/phút ≈ $0.10; AssemblyAI $0.15/giờ ≈ $0.05; TTS ~2k ký tự ≈ $0.02 | ≈ $0.10–0.15 |
| + Voice (self-host PhoWhisper small, CPU) | $0 API; latency phụ thuộc máy | ≈ $0.05 |
| S2S Realtime (không đề xuất) | gpt-realtime audio $32/$64 per 1M token, ~$0.06/phút vào + $0.24/phút ra | ≈ $3.00 |
| Gemini 3.1 Flash Live (persona tuỳ chọn) | ≈ $0.023/phút, có free tier | ≈ $0.46 |
| Bench k=3 | 192k token; Batch −50% | ≈ $0.25 → $0.12 / invocation |

Ý nghĩa: voice cloud làm chi phí Session tăng ~3×, vẫn < $0.20; free tier VN (X-Interview freemium) là khả thi về chi phí.

---

## 7. Quality bar cho final form (phải xanh để gọi là "done")

| Phép đo | Ngưỡng | Cách chạy |
| --- | --- | --- |
| Judge bench | 35/35 (→ ≥ 60 case) median-of-k k=3, **≥ 3 invocation liên tiếp** cho mọi judge change; 0 straddle; |bias| < 0.5 ở n ≥ 8; EN/VN max |Δ| ≤ 1.0 | `coach bench --k 3` (Batch) |
| Replay bench | ordering persona giữ nguyên; artifact mang pack; ≥ 3 persona × 2 pack | `coach replay` (CLI mới) trong CI với DemoLLM |
| Serde goldens | byte-identical | `tests/test_serde_golden.py` trong CI |
| Retrieval | ≥ 95% hit@1 trên set frozen (59/62 hiện tại) khi đổi store/encoder | `scripts/retrieval_eval.py` |
| Voice | WER-ish trên 10 mẫu VN code-switch ≤ ngưỡng do spike đặt; p50 end-to-end ≤ 2.5s; judge prompt byte-identical với text mode | memo `docs/audits/voice-spike-<date>.md` + test |
| ADR 0006 | prompt-construction tests xanh cho 3 probing agent | pytest |
| Budget | quota error mid-question → 0 `failed`, Session `active`, resumable | pytest (#119) |
| Onboarding | ≤ 3 phút (trừ tải dependency) | walkthrough ghi vào PR |

---

## 8. Thứ tự di chuyển (dependency)

1. **Ổn định base (không đổi hành vi):** #119 (quota → không `failed`), anchors #96/#103/`mlops_awareness` (bench-gated), xoá MiMo default, role table thật, `coach replay` CLI + pack trong artifact (#113), prompt-construction tests ADR 0006, exports TTL. Verify: goldens + bench + replay.
2. **Postgres + auth:** PostgresSaver, ledger/usage/exports vào Supabase, JWT + RLS; giữ SQLite cho CLI. Verify: goldens byte-identical (serde không đổi), e2e 2-Session.
3. **Dashboard + Judge Card + coaching memory:** UI đọc bảng; audit JSON. Verify: e2e, prompt tests.
4. **Content pipeline:** pack provenance + persona + embeddings precomputed → pgvector; bỏ Chroma runtime. Verify: retrieval eval, pack lint.
5. **Voice spike → adapter → delivery analytics.** Verify: WER memo, bench byte-identical, latency.
6. **CV/JD import, persona B3, packs công ty.** Verify: prior-weakness property test, persona invariance test.

Bước 1–2 là nền; 3 biến đo lường thành sản phẩm; 4–6 là "hợp thời". Không bước nào yêu cầu đổi judge.

---

## 9. Rủi ro và điều chưa verify

- STT code-switch VN/EN: không vendor nào công bố; spike phải trả lời trước khi hứa voice `[SOURCED STK §4a]`.
- LangGraph durability modes (`exit/async/sync`) chưa verify từ docs; `interrupt()` re-run semantics đã verify `[SOURCED STK §1, §10]`.
- Supabase free pause 7 ngày idle → demo công khai cần Pro hoặc Neon/Fly Postgres `[SOURCED STK §5]`.
- Nghị định 13/2023 và Luật BVDLCN 2025: chưa đọc được văn bản gốc (host chặn) — mọi claim về hồ sơ/consent là từ trí nhớ `[SOURCED STK §9]`.
- Giá Google STT, Render, Hetzner, FPT.AI/Viettel/Zalo speech: chưa capture.
- gpt-5.4-mini không còn là tier mới nhất (5.5/5.6 tồn tại) — không đổi judge nếu không có ≥ 3 invocation k=3 xanh trên bench mở rộng.
