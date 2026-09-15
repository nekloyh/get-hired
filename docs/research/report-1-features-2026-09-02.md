# Report 1 — Nên xây tính năng gì để vừa hợp thời, vừa bền, và kéo được người dùng từ nền tảng hiện có

**Ngày:** 2026-09-02 · **Anchor code:** `docs/audits/baseline-2026-09-02.md` (main @ `2dac711`)
**Nguồn số liệu:** `docs/research/2026-09-02-market-landscape.md` (MKT), `docs/research/2026-09-02-oss-landscape.md` (OSS),
`docs/research/2026-09-02-stack-references.md` (STK). Mọi claim gắn tag: `[SOURCED §x]` = cite mục trong file nguồn ·
`[MEASURED]` = audit/test trong repo · `[INFERRED]` = suy luận từ fact đã cite · `[OPINION]` = đánh giá của tôi.
**Chấm theo priority dự án:** (1) học agentic systems → (2) prep tool dùng được → (3) recruiter signal.

---

## 0. Kết luận ngắn

1. **Thị trường đã chuẩn hoá ở modality (voice/video), JD/CV import, free tier — và trống hoàn toàn ở chất lượng judge.** Không một trong ~20 vendor page đã fetch công bố rubric, dimension, calibration hay language-fairness `[SOURCED MKT §D2, §D4]`. Trong 16 repo OSS, không repo nào có gate calibrated cho judge; chỉ 2 repo đo bất kỳ thứ gì về judge và cả hai đều không nối vào CI `[SOURCED OSS §5.2.3]`.
2. **Đối thủ VN trực tiếp là X-Interview (Hà Nội): voice, bank 20,000+ câu "từ FPT/VNG/Shopee/Grab/Momo", VN+EN, freemium, generic mọi ngành, không công bố chất lượng chấm** `[SOURCED MKT §C4a]`. Job board VN (TopCV, ITviec, VietnamWorks, Vieclam24h) chưa có phỏng vấn AI trên homepage `[SOURCED MKT §C3a]`.
3. **Moat bền không thể là LLM hay bank câu hỏi** (ai cũng có; X-Interview có 20k câu). Thứ dự án đã có mà không ai có: judge bilingual được đo 35/35 median-of-k, Beta skill state longitudinal, replay bench, packs-as-data `[MEASURED baseline §2, §5]` `[SOURCED OSS §5.2.6]`. **Chiến lược đúng là biến "đo được" thành tính năng người dùng nhìn thấy** (Judge Card, skill timeline, "vì sao điểm này"), chứ không phải đuổi theo copilot.
4. **"Hợp thời" = 3 thứ:** voice VN/EN (11/16 OSS có, mọi sản phẩm thương mại có; ta chưa có) `[SOURCED OSS §5.2.4]`; CV/JD-tailored (table-stakes) `[SOURCED MKT §D2]`; và **mô phỏng vòng phỏng vấn AI của nhà tuyển dụng** — thứ ứng viên 2026 thực sự đối mặt (Alex "1,000,000 candidates interviewed", 30 ngôn ngữ; HireVue AI Interviewer) `[SOURCED MKT §B5, §B1]` — chưa sản phẩm prep nào định vị rõ.
5. **Không làm:** live copilot "undetectable" (cả 3 copilot lớn bán tính năng này, không có ethics FAQ) `[SOURCED MKT §A10]`; phân tích khuôn mặt/video; bank đa ngành; multi-judge average (đo vô dụng) `[MEASURED]`. Chi tiết mục 6.

---

## 1. Bức tranh thị trường 2026 (fact)

### 1.1 Candidate-side toàn cầu
| Nhóm | Đại diện | Điều quan trọng với ta | Tag |
| --- | --- | --- | --- |
| Copilot live (đang thống trị marketing) | Final Round ("10M+", $25+/mo), Sensei ($24/mo), LockedIn ("1M+ users") | Headline = trả lời hộ trong phỏng vấn thật, "Undetectable on Zoom, Teams, and Meet"; mock interview chỉ là feature phụ; không có ethics FAQ; không công bố chất lượng | `[SOURCED MKT §A1, §A10]` |
| Communication coach voice/video | Yoodli ($8–20/mo, 5 lifetime session free, SOC2), Big Interview ($39/mo, B2B2C career centre), Huru ($24.99/mo, JD import qua Chrome extension, **liệt kê Vietnamese**) | Delivery analytics (pace, clarity, confidence); rubric là do khách hàng enterprise tự định nghĩa | `[SOURCED MKT §A2, §A3, §A6]` |
| Human/peer premium | interviewing.io (AI Interviewer free cho coding/system design; "$50B in job offers"), Aced/Exponent (600k users, peer mock, kênh đại học) | Giá cao, EN-only, bán "người thật từ FAANG" | `[SOURCED MKT §A4, §A5]` |
| Coding bank | HackerRank prep kit (free, không có AI interviewer phía candidate); LeetCode (403, chưa xác minh) | Không phải sân của ta | `[SOURCED MKT §A7, §A8]` |
| Google Interview Warmup | URL nay chỉ còn hướng dẫn chung, gợi ý dùng Gemini Live | Sản phẩm dạng "free AI mock" của Big Tech không còn là mối đe doạ trực tiếp | `[SOURCED MKT §A9]` |

### 1.2 Employer-side — thứ ứng viên sẽ gặp
- Alex (ex-Apriora): AI phỏng vấn vòng 1 qua phone/video/text, "personalized interviews with each candidate", 30 ngôn ngữ, "1,000,000 Candidates interviewed", 33 ATS integration `[SOURCED MKT §B5]`.
- HireVue: async video + "AI Interviewer" + coding assessments `[SOURCED MKT §B1]`. Paradox: chat/SMS screening khối lượng lớn `[SOURCED MKT §B2]`. HackerRank: live coding có AI assistant "the way they would on the job" `[SOURCED MKT §B6]`.
- `[INFERRED]` Ứng viên fresh grad 2026 có xác suất cao gặp một AI interviewer trước khi gặp người. Chưa sản phẩm prep nào ở MKT định vị "luyện với đúng dạng AI interviewer bạn sẽ gặp".

### 1.3 Việt Nam
| Sản phẩm | Fact | Tag |
| --- | --- | --- |
| X-Interview (x-interview.com, Hà Nội) | "Trợ lý phỏng vấn AI"; voice; 20,000+ câu; VN+EN; chấm "content relevance, communication clarity, structure, confidence"; freemium; "10,000+ practice sessions", "4.9-star" (tự công bố); không rubric/calibration | `[SOURCED MKT §C4a]` |
| TopCV / ITviec / VietnamWorks / Vieclam24h | Không có tính năng phỏng vấn AI trên homepage (chỉ CV builder, test MBTI, job matching). JobsGO: 403, chưa xác minh | `[SOURCED MKT §C3a]` |
| ELSA / Prep | App học tiếng Anh; adaptive *language* roleplay; không có mode phỏng vấn xin việc; ELSA Pro 1 năm 1,095,000₫ (promo), Premium 1 năm 1,716,000₫ | `[SOURCED MKT §C1, §C2]` |
| OSS VN | phongvan-ai (★0, provider mặc định `mock`); DeepInterview (tác giả VN, ★33, Apache-2.0, LangGraph + LiveKit, UI vi chưa wire xong — issue #50) | `[SOURCED OSS §2.15, §2.1]` |

Trần chi trả VN: ELSA anchor ≈ 1.1–1.7 triệu ₫/năm (≈ $40–65/năm ở tỷ giá ~26k) `[SOURCED MKT §C1]` `[INFERRED quy đổi]`; panel review 2026-07-19 ghi WTP toàn cầu $8–20/tháng (memory, không re-verify lần này).

### 1.4 GitHub / OSS
- Mẫu kiến trúc thống trị: **một prompt interviewer + một prompt feedback cuối** trả 5 category cố định; không skill state, không đo judge `[SOURCED OSS §5.2.1, §3]`. Lớp clone "Next.js + Vapi + Gemini" chiếm gần hết kết quả mới (306 fork của một template) `[SOURCED OSS §3]`.
- Cohort 2026 hội tụ về **live loop mỏng + reasoning nặng offline + director deterministic giữ state** (DeepInterview, XUZIAa, interview-director) — trùng lập trường ADR 0001 của ta nhưng vì lý do latency/persona drift `[SOURCED OSS §5.2.2]`.
- 6/17 repo chết >6 tháng, gồm cả 3 repo nhiều sao nhất; 7/17 không có license `[SOURCED OSS §5.2.8, §5.2.9]`.
- `[INFERRED]` Trên GitHub, "nhiều sao" ≠ "được dùng"; tài sản hiếm là bench + dữ liệu đo, không phải app.

### 1.5 Table-stakes vs differentiator (tổng hợp)
- **Table-stakes 2026** (≥4 sản phẩm có): free tier/trial; JD/CV import; AI feedback sau mỗi câu; voice hoặc video; đa ngôn ngữ; một integration (extension/meeting tool) `[SOURCED MKT §D2]`.
- **Differentiator quan sát được:** người thật từ công ty tên tuổi; mạng peer + kênh đại học; licensing tổ chức; enterprise rubric + SOC2; "undetectable" `[SOURCED MKT §D2]`.
- **Không ai công bố:** judge model, rubric anchor, agreement/calibration, repeatability, language fairness `[SOURCED MKT §D4]` `[SOURCED OSS §5.2.3]`. Hada et al. 2023 (arXiv 2309.07462) là bằng chứng học thuật rằng GPT-4-class judge **thổi điểm** ngôn ngữ non-Latin/low-resource nếu không calibrate với native speaker `[SOURCED STK §2]` — đúng hiện tượng ta đã đo (`correctness` EN 2 vs VN 4 trên cùng câu trả lời) `[MEASURED baseline §5]`.

---

## 2. Ta đang đứng ở đâu (đối chiếu baseline)

| Trục | Ta có (đã đo) | Thị trường/OSS có mà ta thiếu | Tag |
| --- | --- | --- | --- |
| Judge | 35/35 median-of-k k=3, bilingual, bias per-dimension, straddle tripwire, judge pinned | — (không ai có) | `[MEASURED baseline §5]` |
| Skill model | Beta per-Skill, priors từ ledger decay 30 ngày, role criticality | Cross-session **view** (1624899 trend, modamaan "recent interviews") — ta có ledger nhưng **không có UI** | `[MEASURED baseline §2]` `[SOURCED OSS §5.2.7]` |
| Adaptivity | Follow-up do Evaluator quyết, Supervisor plan-executor | Learned stop policy (zixi-liu 88% vs 56% zero-shot) | `[SOURCED OSS §2.3]` |
| Modality | Text-only | Voice: 11/16 OSS, mọi sản phẩm thương mại, X-Interview | `[SOURCED OSS §5.2.4]` |
| Input cá nhân hoá | Profile claims + target_role/companies (3 role string) | CV + JD import (DeepInterview, Huru, Final Round, 1624899…) | `[MEASURED baseline §2]` `[SOURCED MKT §D2]` |
| Content | 45 câu + 40 note trong package; 1 pack FPT; Forge | DeepInterview pack có `source_runs`, `confidence` decay, `status` (provenance) | `[SOURCED OSS §2.1]` |
| Report | Markdown export đầy đủ (dimension, evidence, panel packet) | Narrative report + hire recommendation; shareable | `[SOURCED OSS §5.2.7]` |
| Onboarding | Cold 15m01s (uv sync 864s), warm 37s; UI chrome tiếng Anh, jargon nội bộ | One-command deploy / hosted demo trên hầu hết OSS | `[MEASURED baseline §5]` `[SOURCED OSS §5.2.7]` |
| Accounts | Không (session id do browser mint, shared token) | Supabase auth phổ biến | `[MEASURED baseline §2]` |

`[OPINION]` Vị thế: **engine judge tốt nhất trong tập khảo sát, bọc trong sản phẩm không ai dùng nổi 10 phút.** Rủi ro lớn nhất không phải thiếu feature, mà là feature độc nhất (judge đo được, skill longitudinal) **vô hình** với người dùng.

---

## 3. Luận điểm: "hợp thời" và "bền" là hai bài toán khác nhau

- **Hợp thời (6–12 tháng):** người dùng so sánh bạn với X-Interview và Final Round bằng mắt: có voice không, có nhập CV không, có luyện đúng dạng phỏng vấn AI không, mở lên chạy được ngay không. Thiếu một trong bốn thứ này thì không được thử. `[INFERRED từ MKT §D2, OSS §5.2.7]`
- **Bền (2–3 năm):** LLM rẻ dần và giống nhau (STK §3: gpt-5.4-nano $0.20/$1.25, Gemini Flash free tier, DeepSeek V4 Flash $0.44/$1.32) → bất kỳ ai cũng dựng "interviewer + feedback" trong một ngày (OSS §3 chứng minh: 10,276 repo cho một query). Thứ không copy được trong một ngày: **(a) dữ liệu đo chất lượng judge tích luỹ theo thời gian và theo ngôn ngữ, (b) skill state của từng người dùng tích luỹ qua nhiều Session, (c) content có provenance do cộng đồng/công ty đóng góp qua contract, (d) niềm tin — "vì sao tôi được 3 điểm" có bằng chứng.** `[INFERRED]` `[OPINION]`
- Hệ quả: **ưu tiên (2) và (1) trùng nhau ở judge và skill state; ưu tiên (3) trùng ở việc công bố bench.** Voice và CV import là "vé vào cửa", cần làm nhưng phải làm theo cách **không phá đo lường** (Report 2: voice là transport, text là sự thật).

---

## 4. Tính năng nên xây — 4 tầng

Mỗi dòng: tính năng · vì sao (evidence) · phục vụ priority nào · tiêu chí chấp nhận đo được · phụ thuộc/rủi ro.

### Tầng A — Nền để "dùng được" (làm trước, nhỏ, không mới về agentic)
| # | Tính năng | Vì sao | Priority | Acceptance đo được | Phụ thuộc / rủi ro |
| --- | --- | --- | --- | --- | --- |
| A1 | **Hosted demo + onboarding < 3 phút** (link web chạy sẵn ở demo mode; quickstart không cần `uv sync` 14 phút) | Cold onboarding 15m01s `[MEASURED #59]`; OSS đối thủ có Vercel button / compose 1 lệnh `[SOURCED OSS §5.2.7]` | (2), (3) | Clean device → hoàn thành 1 câu hỏi live ≤ 3 phút (không tính tải dependency); demo mode không cần key | Docker image hiện thiếu rag extras `[MEASURED baseline §6.12]` |
| A2 | **Accounts thật** (Supabase Auth: email/Google; VN: Zalo login sau) | Không thể có progress nếu không có identity; session id đang do browser mint `[MEASURED baseline §2]`; Supabase free 50k MAU `[SOURCED STK §5]` | (2) | Đăng nhập → 2 Session cùng candidate → ledger nối đúng; RLS test | Slice 0036 (#84) |
| A3 | **Progress dashboard / skill timeline** (ledger đã có, chỉ thiếu UI) | Differentiator "longitudinal skill state" đang vô hình `[MEASURED baseline §2 coaching memory]`; đối thủ chỉ có list session hoặc trend trung bình `[SOURCED OSS §5.2.1]` | (2), (1: consumer đầu tiên của ADR 0006 addendum) | Sau 2 Session: hiển thị mastery ± confidence per Skill theo thời gian, delta "since last session"; e2e test | Slice 0035 (#83); phụ thuộc A2 |
| A4 | **Chrome VN-first + bỏ jargon nội bộ** ("Micro-loop workspace" → ngôn ngữ người dùng) | Audience VN, UI đang EN `[MEASURED baseline §2 Frontend]`; X-Interview UI Việt `[SOURCED MKT §C4a]` | (2) | 2 locale, không enum thô hiển thị; snapshot test | #85; đừng dịch skin cũ hai lần nếu #50 chưa quyết |
| A5 | **CV/JD import → Diagnostic priors** (single-shot extraction, ADR 0003-compliant) | Table-stakes `[SOURCED MKT §D2]`; Diagnostic đã nhận claims + role — đây là input adapter `[MEASURED baseline §2 Diagnostic]` | (2), (1: kiểm chứng "CV claim là claim, không phải evidence" — ADR 0002 prior weakness) | Upload CV fixture → form prefilled → Session chạy; property test: prior sau CV vẫn "weak" (α+β không vượt ngưỡng) | Slice 0037 (#86); unknown role → all-PERIPHERAL im lặng phải thành cảnh báo (ADR 0014) |
| A6 | **Báo cáo cuối có narrative + "vì sao điểm này"** (mỗi dimension kèm anchor BARS trúng + evidence quote đã có) | Export đã có dữ liệu; thị trường chỉ có "AI insights" mơ hồ `[SOURCED MKT §D4]`; OSS có narrative + hire rec `[SOURCED OSS §5.2.7]` | (2), (3) | Report hiển thị anchor text của band được chấm + quote; người dùng share được link/PDF | Không thêm LLM call (render từ Evaluation) |

### Tầng B — Hợp thời (làm sau A, có gate đo)
| # | Tính năng | Vì sao | Priority | Acceptance đo được | Phụ thuộc / rủi ro |
| --- | --- | --- | --- | --- | --- |
| B1 | **Voice mode VN/EN** — STT ở mép, **judge vẫn chấm transcript**, TTS đọc câu hỏi | Text-only không còn credible `[SOURCED OSS §5.2.4]` `[SOURCED MKT §D3]`; giữ bench hợp lệ | (2), (1: học pipeline realtime + phân tách delivery/knowledge) | Spike #87 trước: WER trên 5 mẫu VN code-switch, có/không dấu; latency end-to-end p50 < 2.5s cho câu trả lời 30s; bench judge **không đổi** (byte-identical prompt trên transcript) | STT VN: Deepgram `vi` nhưng multi-mode **không** hỗ trợ code-switch; AssemblyAI vi ở band WER 10–25%; PhoWhisper self-host có WER công bố `[SOURCED STK §4a]`. Xem Report 2 §4.5 |
| B2 | **Delivery analytics deterministic** (pace, pause, filler, độ dài) tách khỏi điểm kỹ thuật | Yoodli/Huru/Big Interview bán cái này `[SOURCED MKT §A2, §A3, §A6]`; ADR 0007 đã tách `english_delivery` khỏi weighted_score `[MEASURED]` | (2) | Tính từ timestamp STT, không LLM; hiển thị riêng, không vào Beta state | Chỉ có ý nghĩa sau B1 |
| B3 | **Mode "Phỏng vấn với AI interviewer của nhà tuyển dụng"** — persona pack: phone-screen kiểu Alex (hội thoại, 30 phút, hỏi theo CV), async 1-shot có giới hạn thời gian kiểu HireVue, chat screening kiểu Paradox | Nhu cầu mới thật `[SOURCED MKT §B]`; chưa sản phẩm prep nào định vị `[INFERRED]`; là **data** (persona + format) chứ không phải code — ADR 0008 | (2), (3), (1: persona như pack, Interviewer style tách khỏi judge) | 3 persona pack; cùng câu trả lời → judge cho cùng điểm dù persona khác (test invariance); người dùng chọn "luyện với dạng phỏng vấn X" | Rủi ro: bị hiểu nhầm là copilot → copy phải nói rõ "luyện, không dùng trong phỏng vấn thật" |
| B4 | **Pack theo công ty/style VN** (FPT đã có; thêm VNG, Zalo, Momo, Viettel... qua Forge + review) | X-Interview quảng cáo câu hỏi "từ FPT/VNG/Shopee/Grab/Momo" `[SOURCED MKT §C4a]`; #88 đang mở | (2) | Mỗi pack lint pass + ≥ 4 câu/Skill + concept note; bench không đổi (pack không chạm judge) | ADR 0014 (E6) nếu pack cần Skill mới |
| B5 | **Mobile-usable (PWA)** | Fresh grad VN dùng điện thoại; voice cần mic (getUserMedia) | (2) | Lighthouse PWA installable; e2e mobile-chrome đã có project | Zalo Mini App **không** có API ghi âm `[SOURCED STK §6]` → chỉ dùng cho identity/distribution |

### Tầng C — Bền / moat (biến "đo được" thành sản phẩm)
| # | Tính năng | Vì sao | Priority | Acceptance đo được | Phụ thuộc / rủi ro |
| --- | --- | --- | --- | --- | --- |
| C1 | **Judge Card công khai** — trang "Chúng tôi chấm thế nào": rubric + anchor, bench k=3 mới nhất, bias per-dimension, EN/VN |Δ|, straddle, model + ngày | Không ai công bố `[SOURCED MKT §D4]`; ta đã có audit `[MEASURED]`; là recruiter signal mạnh nhất có thể (priority 3) mà không tốn feature | (3), (2: niềm tin), (1) | Trang render tự động từ audit mới nhất; mỗi judge change kèm Judge Card mới; CI fail nếu README số liệu lệch audit (fix drift D1) | Cần audit machine-readable (JSON bên cạnh .md) |
| C2 | **Coaching memory trên planning surface** — Study Plan nhắc "lần trước bạn yếu X, hôm nay delta"; không bao giờ vào prompt probing/judging | ADR 0006 addendum cho phép, chưa có consumer `[MEASURED baseline §3]`; Không OSS nào có per-skill memory `[SOURCED OSS §5.2.1]` | (1), (2) | Prompt-construction test: transcript cũ không xuất hiện trong message của Evaluator/Interviewer/Supervisor (đóng drift D12); planner nhận ledger delta | Phụ thuộc A2, A3 |
| C3 | **Pack provenance + cộng đồng**: `source_runs`, `confidence`, `status`, `reviewed_by` trong pack schema; Forge → review queue → admitted; nhãn bench từ live answer đã review (ADR 0009b) | DeepInterview đã có schema provenance `[SOURCED OSS §2.1]`; ta có Forge + admission gate `[MEASURED]`; nhãn bench là tài sản tích luỹ | (1), (3) | `coach pack lint` bắt buộc provenance; bench label tăng từ 35 → mục tiêu 60 với nguồn ≥ 2 provenance; mỗi label mới có reviewer | Cần người review (owner) — bottleneck thật |
| C4 | **Bench + eval mở như artifact độc lập trên GitHub** (dataset bilingual + harness `coach bench`, license rõ) | 7/17 repo OSS không license; không ai có bench `[SOURCED OSS §5.2.3, §5.2.9]`; đây là thứ người khác **muốn tái sử dụng** — kéo contributor và recruiter signal | (3), (1) | Repo/package tách được (`interview-judge-bench`), README có Judge Card, ≥ 1 PR ngoài trong 3 tháng | Không tách code judge ra khỏi engine; chỉ dataset + harness |
| C5 | **Derived confidence (ADR 0011) khi E4 xanh** — uncertainty từ vote spread thay self-report chết | Self-report bão hoà, 0 escalation `[MEASURED]`; multi-vote rẻ (Groq/nano) `[SOURCED STK §3]` | (1) | E4: bucket monotone với hit-rate; median-of-3 votes ≥ 27/29 in-band (theo ADR) | Đây là experiment, không phải feature cam kết |

### Tầng D — Không xây (non-goals, viết rõ để không trôi)
| # | Không làm | Lý do |
| --- | --- | --- |
| D1 | **Live copilot / "undetectable" overlay** | Toàn bộ segment bán detectability, không ethics FAQ `[SOURCED MKT §A10]`; xung đột mục tiêu học (priority 1) và niềm tin (C1); rủi ro policy nhà tuyển dụng (chưa verify được văn bản, STK §9) `[OPINION]` |
| D2 | **Phân tích khuôn mặt / video** | Không có bằng chứng giá trị trong MKT; dữ liệu sinh trắc là nhạy cảm theo Nghị định 13 (chưa verify văn bản gốc) `[SOURCED STK §9]`; tốn kém, không phục vụ priority nào |
| D3 | **Bank đa ngành (marketing, sales, HR...)** | X-Interview đã "20,000+ câu mọi ngành" `[SOURCED MKT §C4a]`; ta thắng bằng **độ sâu AI/ML + judge đo được**, không bằng độ rộng |
| D4 | **Multi-judge lấy trung bình điểm** | Forced-escalation: verdict Δ 0.00 trên 10/10 case `[MEASURED]`; ADR 0011 chỉ giữ multi-vote cho uncertainty |
| D5 | **Speech-to-speech end-to-end cho judge** (Realtime API chấm trực tiếp audio) | Mất transcript = mất bench; audio $32/$64 per 1M token ≈ đắt hơn text mini ~40× `[SOURCED STK §3]`; xem Report 2 |
| D6 | **Marketplace người phỏng vấn thật** | interviewing.io/Aced sở hữu, vốn và network effect; không phải bài toán agentic |
| D7 | **Code judge LeetCode-style** | HackerRank/LeetCode; nếu cần thì là một *pack type* sau, không phải core |

---

## 5. Kéo người dùng từ nền tảng hiện có — theo từng nguồn

| Người dùng đang ở | Họ ở đó vì | Điểm đau (evidence) | Cái kéo họ sang | Tính năng tương ứng |
| --- | --- | --- | --- | --- |
| **X-Interview** (VN, voice, generic) | Tiếng Việt, voice, câu hỏi "từ công ty" | Điểm số không giải thích, không rubric, không tiến bộ theo Skill `[SOURCED MKT §C4a]` (không thấy progress/timeline trên homepage) | "Điểm có bằng chứng" + skill timeline + pack công ty VN sâu về AI/ML | A3, A6, B1, B4, C1 |
| **Final Round / copilot** | Sợ phỏng vấn thật, muốn "trợ giúp" | Không học được gì; rủi ro bị phát hiện; mock chỉ là phụ `[SOURCED MKT §A10]` | Mô phỏng đúng AI interviewer họ sẽ gặp + luyện thật để không cần copilot | B3, B1 |
| **LeetCode / HackerRank** | Coding | Không có ML theory/system design/MLOps được chấm | Interview ML-specific có follow-up và rubric | (đã có core), B4 |
| **interviewing.io / Aced** | Người thật, chất lượng | Đắt, EN-only, không VN `[SOURCED MKT §A4, §A5]` | Judge được calibrate + bilingual với giá VN | C1, A4 |
| **ELSA / Prep** | Luyện tiếng Anh nói | Không có nội dung phỏng vấn kỹ thuật `[SOURCED MKT §C1, §C2]` | `english_delivery` tách khỏi kiến thức + phrase fixes (đã có, ADR 0007) + voice | B1, B2 |
| **GitHub OSS (DeepInterview, clone class)** | Tự host, học | Không có bench, không đo VN/EN `[SOURCED OSS §5.2.3]` | Bench + Judge Card mở; packs contract | C1, C4, C3 |
| **Sinh viên qua trường/bootcamp** | Kênh tổ chức | Big Interview/Aced bán qua career centre `[SOURCED MKT §D6]` | Pack theo chương trình + dashboard lớp (sau) | A2, A3, B4 |

**Levers thị trường đã quan sát và cách áp dụng** `[SOURCED MKT §D6]` `[OPINION]`:
- Free tier **giữ core** (khác Final Round giữ lại copilot): N Session/tuần miễn phí với judge đầy đủ; trả phí = voice + pack công ty + lịch sử dài. Budget rail đã có (480 câu/ngày) `[MEASURED baseline §2 Usage]`.
- Định giá VN dưới trần ELSA: ≈ 49–99k₫/tháng hoặc gói 6 tháng `[INFERRED từ MKT §C1]` — mục tiêu là *thử*, không phải doanh thu (priority 3 < 2).
- Shareable scorecard (A6) = social proof kiểu "Product Hunt 4.9" của Final Round nhưng có nội dung thật.
- Chrome extension nhập JD từ TopCV/ITviec (mẫu Huru) — chỉ làm sau A5.
- Zalo: login/identity và chia sẻ; **không** chạy phỏng vấn voice trong Mini App (không có API ghi âm) `[SOURCED STK §6]`.

---

## 6. Lộ trình gợi ý (3 bước, mỗi bước có gate đo)

1. **"Dùng được trong 3 phút, thấy được tiến bộ"** — A1, A2, A3, A4, A6 (+ đóng #119, #96/#103 vì Judge Card cần bench sạch). Gate: onboarding ≤ 3 phút; 2 Session → timeline; bench 35/35 k=3 ×2 invocation; prompt-construction test ADR 0006.
2. **"Hợp thời"** — spike #87 → B1, B2, A5, B4 (2 pack), B3 (1 persona). Gate: WER/latency memo; bench byte-identical; persona invariance test; 2 pack lint xanh.
3. **"Bền"** — C1, C2, C3, C4; E4 (C5) nếu ngân sách. Gate: Judge Card auto-render; nhãn bench ≥ 60 với 2 provenance; PR ngoài đầu tiên.

`[OPINION]` Thứ tự này tôn trọng priority: bước 1 và 3 là nơi (1) học agentic và (3) signal trùng nhau (evaluation, memory boundary, data contract); bước 2 là plumbing cần thiết cho (2) và phải được làm *như adapter* để không phá (1).

---

## 7. Giả định chưa kiểm chứng / rủi ro

- **Chưa xác minh:** giá X-Interview (`/pricing`, `/bang-gia` 404); JobsGO (403); LeetCode (403); Google Interview Warmup còn sống không; chính sách chính thức của Amazon/Google/HackerRank về copilot; văn bản Nghị định 13/2023 và Luật BVDLCN 2025 (host chặn fetch) `[SOURCED MKT §C0, STK §9]`.
- **WebSearch của session đã hết quota** → discovery tiếng Việt chỉ bằng fetch trực tiếp domain đã biết; có thể sót sản phẩm VN nhỏ (`[SOURCED MKT §C0]`).
- **Giả định lớn nhất:** người dùng VN trả tiền cho "điểm có bằng chứng" thay vì "voice + nhiều câu". Chưa có dữ liệu; cách rẻ nhất để kiểm: A6 + C1 lên trước B1 và đo retention 2-Session.
- **Bottleneck thật là người review nhãn** (C3), không phải code.
