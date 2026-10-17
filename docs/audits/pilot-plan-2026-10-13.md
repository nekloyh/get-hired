# Pilot plan — 2026-10-13 (proposal)

**Đây là đề xuất, chưa được chấp nhận.** Nó chỉ thành kế hoạch khi maintainer tạo milestone và
issue tương ứng trên GitHub. Từ lúc đó, trạng thái nằm trên GitHub, không nằm ở đây. Code nền là
`2ceaf81` (tag `v0.3.0`). Bằng chứng về docs và ADR nằm trong
[`docs-review-2026-10-12.md`](docs-review-2026-10-12.md).

## 0. Quyết định của maintainer (2026-10-13)

- Ưu tiên lúc này: **một công cụ luyện phỏng vấn dùng được, hoàn chỉnh, để pilot**. Ưu tiên
  "học agentic" và "recruiter signal" lùi lại sau.
- Pilot đầu tiên là bạn bè của maintainer. Phải qua được vòng này trước khi mở rộng hay public.
- Thời gian không giới hạn, không có deadline. Allowance 2,5M token/ngày vẫn còn.
- Dùng kiến trúc/stack tốt nhất cho sản phẩm, không chọn việc theo mục tiêu học.
- **Mọi quyết định ADR tạm dừng** để maintainer tự review và định hướng lại sản phẩm. Vì vậy kế
  hoạch này không phụ thuộc ADR nào đổi `Status:`. Việc cần một quyết định ADR được ghi rõ.

## 1. Pilot gặp gì ở `v0.3.0` (fact)

Đo bằng đọc code và chạy repro offline ở demo mode (`demo_llm.DemoLLMClient`, 0 token). Các mục
đánh dấu **[tự kiểm]** đã được kiểm lại độc lập bằng grep.

| # | Vấn đề | Bằng chứng | Mức với pilot |
|---|---|---|---|
| 1 | Resume trên web không reset đồng hồ: Session tạm dừng vì hết budget, resume hôm sau thì hỏi 0 câu rồi kết thúc, kết quả rút gọn vẫn ghi vào Skill ledger, UI không nói lý do | chỉ `cli_session._cmd_session` gọi `graph.update_state(..., {"started_at": ...})`; `web_session_driver._run_session_thread` thì không; `supervisor.decide_next_move` áp `DEFAULT_MAX_ELAPSED_SECONDS = 30*60` **[tự kiểm]**; repro trên `TestClient` | chặn |
| 2 | Session demo ghi bằng chứng giả vào Skill ledger thật; UI cho bạn bè chọn Demo; `auto` lặng lẽ rơi về demo khi thiếu key hoặc `OPENAI_MODEL` | `_run_session_thread` gọi `ledger.save_measured_posteriors` khi COMPLETE mà không xét mode **[tự kiểm]**; `config.Settings.openai_model` mặc định `""` | chặn |
| 3 | Rail 30 phút tính cả thời gian gõ; UI không gửi `max_elapsed_seconds` và không cho thấy rail này | `supervisor.DEFAULT_MAX_ELAPSED_SECONDS` **[tự kiểm]**; `web/src/App.tsx` không gửi trường này | lớn |
| 4 | Buổi thứ hai báo lỗi: "Start New Session" giữ nguyên Session id → `_ALREADY_CHECKPOINTED` | repro | lớn |
| 5 | Candidate id không được nhớ, phân biệt hoa thường; có dấu cách hoặc dấu tiếng Việt thì trả lỗi pydantic thô; sai token chỉ hiện "Connection lost… reconnect" | `web_protocol._parse_payload`; `App.openSocket` bỏ qua close code 1008 | lớn |
| 6 | Role ngoài bảng ("AI Engineer", "Data Scientist", "Junior ML Engineer", "Kỹ sư AI") rơi về all-PERIPHERAL mà không báo; công ty chỉ khớp chính xác vinai/zalo/viettel | `diagnostic.role_criticality` **[tự kiểm]** | lớn |
| 7 | Câu hỏi lặp: ở target 3 chỉ 13/45 câu có thể ra đầu tiên; sau 3 buổi kỳ vọng 9,5/15 câu khác nhau; mlops và vietnamese_nlp chắc chắn lặp. Form web mặc định 3 câu nên system_design và vietnamese_nlp không bao giờ được hỏi | `seeds.select_seed_question` xếp theo `abs(difficulty - target)` trước, rotation chỉ phá hòa; không loại câu đã hỏi giữa các buổi; mô phỏng 20k Session id | lớn khi luyện nhiều lần |
| 8 | Báo cáo không cho biết lý do điểm: không có evidence quote, không có stop reason, không có delta so với lần trước, mấy thứ này chỉ có trong file `.md`; không có câu trả lời mẫu | `ReportView`; `exporter._append_evaluation` | lớn |
| 9 | Study plan có thể khuyên học Skill chưa từng được hỏi (xếp theo self-claim); catalog chỉ có 2 link mỗi Skill, đều tiếng Anh | `study_planner.rank_study_targets`; `resources.SEED_RESOURCES` | vừa |
| 10 | UI đầy thuật ngữ nội bộ ("Micro-loop workspace", "calibration cockpit", `advance_plan`, `safety_cap`); lỗi lộ tên biến môi trường; banner bảo người dùng chạy `uv sync --extra rag` | `App.tsx`, `TopicPlan.tsx`, `ReportView.tsx`, `usage.start_refusal_reason` | vừa |
| 11 | Điểm của câu trả lời yếu bằng tiếng Việt có thể cao hơn bản tiếng Anh tới 1 điểm (câu mạnh không bị); gate RED 34/35 | `judge.lock` → `calibration-bench-2026-09-15.md`; `rubric.DIMENSION_GUIDE`: `depth` và `system_thinking` thiếu band 3, `communication` thiếu 2, `mlops_awareness` chỉ có 1 và 5 **[tự kiểm]** | vừa (đã công bố trong runbook §2) |
| 12 | Mode `vn` và `mixed` chưa từng chạy live end-to-end; bench không có case nào ở `language_mode=vn` | `live-smoke-2026-10-12.md` ("Not covered") | rủi ro chưa đo |
| 13 | Chưa có đường hosting đơn giản (chỉ có VPS + certbot); HTTPS là bắt buộc (`crypto.randomUUID` không chạy ở http) | `docs/deploy.md`; `web/src/lib/sessionReducer.ts` | chặn |
| 14 | Không có kênh feedback trong app | `ReportView` | mục đích của pilot |

Ngân sách token: một Session 5 câu có follow-up ước khoảng 50–65k token. Con số này suy ra từ mẫu
26.478 token cho 2 câu, một câu 4 lượt; chưa đo trực tiếp. 5 người × 3 buổi/tuần là khoảng
0,15M token/ngày, nằm xa dưới allowance 2,5M/ngày.

## 2. Scope của `v0.4.0 Foundation`: không đúng cho mục tiêu mới (opinion)

Milestone này được dựng quanh ADR 0015 (#143) và việc lưu trữ (#125, #126, #127), cộng phần anchor
của judge (#96, #103). Với ưu tiên mới, nó sai ở ba điểm:

1. **Bốn trên bảy issue đang mở là việc của store.** Ở quy mô pilot chúng không ảnh hưởng người dùng:
   rail tốn khoảng 16 ms mỗi câu ở 1,5k dòng (`adr-0015-gate-2026-10-12.md`). Lõi của chúng là #143,
   mà #143 cần một quyết định ADR đang bị dừng.
2. **14 vấn đề ở §1 không nằm trong milestone nào.** Trong đó có 3 lỗi chặn pilot chưa có issue
   (dòng 1, 2, 13).
3. **#96 đã bị đóng nhầm** (PR #165), nên milestone hiện trông như đã xong phần anchor.

Đề xuất: giữ #139; tạo milestone pilot mới đứng trước; chuyển việc store sang sau, chờ quyết định ADR.

## 3. Ba hướng cho 2–3 tháng tới

| | A. Pilot trước: sửa hành trình người dùng | B. Chất lượng chấm trước | C. Nền móng trước (`v0.4.0` hiện tại) |
|---|---|---|---|
| Làm gì | §1 dòng 1–10, 12–14; anchor để sau | #96, #103, `mlops_awareness`, bench pair `vn`, rồi mới pilot | ADR 0015 → store → history → dashboard, rồi mới pilot |
| Được gì | phản hồi thật trong ~3–5 tuần; biết người dùng cần gì trước khi xây tiếp | điểm công bằng EN/VN trước khi ai đó dùng | nền sạch cho repeat practice |
| Token | ~0,1M phát triển + pilot ~0,15M/ngày | 1,3–2M judge token (1–2 ngày allowance), nhiều wording thì hơn | ~0 |
| Giờ (opinion) | 40–60 h | 20–40 h, cộng thời gian gán nhãn | 40–80 h |
| Rủi ro | lệch điểm VN vẫn còn trong vòng 1 (đã công bố) | #96 từng mất nhiều tuần mà không land được; pilot trễ không biết bao lâu | bị chặn bởi việc dừng ADR; pilot trễ 4–6 tuần |
| Bỏ / dời | store, thí nghiệm E1–E6, redesign | toàn bộ fix UX | toàn bộ fix UX và chất lượng |

**Chọn A** (opinion). Ba lý do. Mục tiêu mới là pilot sớm nhất. Phần lớn lỗi chặn tốn 0 token và
là S–M. Và B, C chỉ tối ưu đúng khi đã biết người dùng thật vấp ở đâu. Việc chấm VN (B) là việc đầu
tiên của milestone thứ hai, chạy trước vòng pilot 2. Lý do: nó chỉ tốn token (vừa trong một ngày
allowance), và đổi judge giữa chừng một vòng pilot sẽ làm điểm hai nửa vòng không so được với nhau.

## 4. Milestone đề xuất

### M1 — `v0.4.0 Pilot-ready` (vòng pilot 1 với bạn bè)

Issue theo thứ tự (`N*` là issue mới cần tạo, xem §6):

1. **#139** xoay toàn bộ provider key và thu hồi key cũ (chỉ maintainer làm được).
2. **N1** Web resume reset `started_at`, có test web.
3. **N2** Session demo không bao giờ ghi Skill ledger. UI pilot ẩn chọn Mode. `auto` không im lặng rơi về demo.
4. **N3** Rail thời gian hợp với người: UI gửi `max_elapsed_seconds` theo số câu (hoặc nâng mặc định); báo cáo hiện lý do Session kết thúc.
5. **N4** "Start New Session" tạo Session id mới; buổi thứ hai bắt đầu sạch.
6. **N5** Setup khó làm sai: nhớ Candidate id, kiểm tra ở client với lỗi dễ hiểu, báo rõ "token sai" khi close 1008, mặc định 5 câu.
7. **N6** Bảng alias cho role và công ty, cộng thông báo "role chưa được nhận diện" hiện trên UI.
8. **N7** Đa dạng câu hỏi: nhận độ khó trong khoảng ±1 quanh target (vẫn ưu tiên gần nhất). Sửa luôn test `test_target_difficulty_still_drives_selection`.
9. **N8** Báo cáo dễ hiểu: evidence quote, điểm từng lượt ("điểm câu = lượt cuối"), lý do dừng, mục "Câu trả lời tốt sẽ nói tới…" lấy từ note `expected_concepts`. Đây là thay đổi hiển thị, không phải judge change (`judge.lock` không đổi).
10. **N9** Study plan chỉ xếp hạng Skill đã đo trong buổi; Skill khác ghi "chưa đánh giá".
11. **N10** Một lượt viết lại chữ trên UI bằng ngôn ngữ người dùng: bỏ thuật ngữ nội bộ, ẩn banner `uv sync --extra rag`, thay lỗi thô bằng câu dễ hiểu.
12. **N11** Đường hosting cho pilot (Cloudflare Tunnel hoặc Tailscale Funnel, hoặc VPS + certbot), backup hằng ngày ra ngoài máy, cron grep lỗi có báo về.
13. **N12** Kênh feedback: form gắn link trong màn báo cáo, hỏi Session id, "điểm sai vì…", mức hữu ích 1–5.
14. **N13** Smoke live một Session `vn` và một `mixed` trên đúng stack pilot (~60–70k token). Làm cuối cùng, trước khi mời người.

**Exit criteria, tất cả nhị phân:**

- **P1** `scripts/gate.sh --all` xanh và CI xanh trên commit được tag.
- **P2** Mọi key trong `.env` của pilot chưa từng bị lộ, key cũ đã thu hồi (#139 đóng).
- **P3** Mọi dòng pre-flight trong `docs/pilot-runbook.md` pass trên host pilot.
- **P4** Có test tự động resume một Session web có `started_at` cũ hơn 30 phút, và Session đó hỏi đủ số câu còn lại.
- **P5** Có test cho thấy một Session demo để Skill ledger y nguyên từng byte.
- **P6** Có test: hai buổi liên tiếp cùng Candidate trong cùng trình duyệt bắt đầu không lỗi; với cùng profile, buổi hai có câu đầu khác buổi một ở ít nhất 3/5 Skill (demo mode, nhiều Session id).
- **P7** Vitest khẳng định báo cáo hiện evidence quote, điểm từng lượt và lý do dừng.
- **P8** Một Session live `vn` và một `mixed` hoàn tất trên stack pilot, tổng ≤150k token, ghi lại trong `docs/audits/`.
- **P9** Có kênh feedback; runbook §2 liệt kê đủ điều phải nói với người dùng (chung token, không riêng tư, điểm chỉ để luyện, câu trả lời được gửi tới OpenAI).
- **P10** Tag `v0.4.0` bằng `scripts/release.sh`.

### M2 — `v0.5.0 Pilot round 2: chấm VN và luyện lặp lại`

Bắt đầu sau khi M1 được tag và có ít nhất một tuần feedback. Danh sách sẽ điều chỉnh theo feedback.

1. **#96** (mở lại) land lại anchor band 3 cho `depth`/`system_thinking`, xuất phát từ tag
   `archive/pr-104-anchor-depth-system-thinking`. Screen trước (~60k), rồi ≥3 lần confirm k=3
   (181–212k mỗi lần): ~0,6–0,7M token, vừa trong một ngày. Thêm ≥2 cặp bench `language_mode=vn`.
2. **#103** band 2 cho `communication`, làm sau #96 (~0,6M).
3. **N14** band giữa cho `mlops_awareness`. Cần gán nhãn case mới trước.
4. **Quyết định store** (maintainer review ADR 0015) → **#127** lịch sử Skill. Với 0015, #125/#126 đi kèm.
5. **N15** Không hỏi lại câu đã hỏi cùng Candidate. Cần #127.
6. **#83** (thu nhỏ) lịch sử Session và tiến bộ theo Skill. Cần #127.
7. **#85** UI tiếng Việt.
8. **N16** Nội dung: câu hỏi LLM/RAG trong các Skill hiện có; `vietnamese_nlp` ≥9 câu; qua Forge và người duyệt.
9. **N17** Feedback trong app, cộng token riêng cho từng người bạn → principal (cầu nối rẻ tới #84).

Exit criteria khung, chốt lại khi mở M2:

- `judge.lock` dời cùng một artifact confirm xanh qua ≥3 lần chạy.
- Bench có ≥2 cặp ở mode `vn`.
- Kết quả tally feedback vòng 1 được ghi lại.
- Mỗi người bạn có ≥3 buổi.
- Ba buổi liên tiếp không lặp câu đầu của bất kỳ Skill nào.

## 5. Triage `Later` (12 issue)

| Issue | Đề xuất | Lý do (một câu) |
|---|---|---|
| #60 R-05 redesign (PR #50) | **close** (not planned) | Code đã cũ hơn hai tháng và được giữ ở tag archive; phần UX cần cho pilot nằm ở N8/N10, làm trên giao diện hiện tại |
| #71 R-16 deterministic triggers | **keep** (frozen) | Là judge change, không cần cho pilot; khi mở lại phải sửa AC "29/29" đã cũ |
| #72 R-17 backup judge | **keep** (frozen) | Với 5 người, OpenAI sự cố thì Session tạm dừng và resume được; không đáng làm trước pilot |
| #79 R-24 fold every turn | **keep** (frozen) | Bị gate bởi section Proposed của ADR 0002 (E2 âm, n=1); triệu chứng phía người dùng do N8 xử lý bằng hiển thị |
| #83 R-28 history + dashboard | **promote → M2** (bản thu nhỏ) | Luyện lặp lại là giá trị cốt lõi, nhưng cần #127 trước |
| #84 R-29 accounts + Postgres | **keep** | Là cổng cho public; vòng bạn bè dùng token chung, M2 có bước trung gian rẻ (N17) |
| #85 R-30 i18n VN | **promote → M2**, bỏ phụ thuộc vào #60 | Phần bỏ thuật ngữ đi vào M1 (N10); bản dịch đầy đủ vào M2 |
| #86 R-31 CV/JD import | **keep** | Hay nhưng không cần cho vòng bạn bè; xem lại sau feedback |
| #87 R-32 voice spike | **keep** | Sau khi luồng text đã tốt |
| #88 R-33 company packs | **merge vào N16** | Web không chọn được pack (`web_session_driver` không truyền `question_bank`); cần mở rộng bank có sẵn trước |
| #128 duplication debt | **keep** (frozen) | Không ảnh hưởng người dùng |
| #146 local simulated candidate | **keep** (frozen) | Phục vụ E1 và replay bench, không phục vụ pilot |

## 6. Thay đổi tracker đề xuất (chỉ liệt kê, maintainer tự thực hiện)

1. **Mở lại #96.** Nó bị PR #165 đóng nhầm vì câu "the anchor fixes #96/#103". Cập nhật body:
   case đỏ hiện là `vnlp_segmentation_weak_vi`; `panel_sd_retry_storm` có |Δ|=1,00 trong lần chạy
   2026-09-15. Đừng viết "fixes #NN" trong body PR nào trừ khi PR đó thật sự sửa issue ấy.
2. **Tạo milestone `v0.4.0 Pilot-ready`** với mô tả P1–P10. Chuyển #139 sang đó.
3. **Đổi tên `v0.4.0 Foundation` → `v0.5.0 Pilot round 2`.** Giữ #96 (mở lại), #103, #127, #125,
   #126, #143. Viết lại mô tả và bỏ cụm "fixes #96" khỏi đó.
4. **Tạo issue mới** (thân issue cần qua bước phản biện trước khi file):
   - M1: N1–N13 như §4.
   - M2: N14 `mlops_awareness`, N15, N16, N17.
   - Lỗi và nợ nhỏ tìm thấy trong review:
     - `interviewer.generate_follow_up` và `seeds.render_seed_question` chỉ bắt `StructuredOutputError`; case "hết quota rồi fallback cũng lỗi" chưa có test.
     - `coach session` chạy trong container mặc định `--ledger-db .skill-ledger.json`, nằm ngoài volume state.
     - `cli._cmd_ingest_concepts` truyền `embedding_model=None` và bỏ qua `concepts.embedder_persist_dir`.
     - Comment trạng thái trong `src`: `config.BENCH_VALIDATED_JUDGES` ("Green today… 35/35"); help `--log-file` của `cli_parser`.
     - Comment healthcheck nginx trong `docker-compose.yml` nói image không có curl (sai).
     - `PANEL_MAX_ESCALATIONS_PER_QUESTION` chưa được ghi docs.
     - `deploy.md` §5 backup `tar` file WAL đang mở.
5. **Triage `Later`** như §5: đóng #60; gắn #83 và #85 vào `v0.5.0`; gộp #88 vào N16.
6. **Sau khi chấp nhận hướng A:** cập nhật câu ưu tiên trong `CLAUDE.md` và `docs/roadmap.md` cho
   khớp quyết định ở §0. Đó là việc định hướng, nên không nằm trong PR sửa fact.

## 7. Tính năng đề xuất thêm

Theo thứ tự giá trị cho người luyện; đều tốn 0 token trừ khi có ghi.

- **"Câu trả lời tốt sẽ nói tới…"** sau mỗi câu, lấy từ note `expected_concepts` đã có cho 45/45
  câu. Hiện nội dung này không bao giờ tới tay người dùng. (M1, trong N8.)
- **Chế độ coach:** bật lên thì hiện điểm và một dòng lý do ngay sau mỗi câu, thay vì chờ tới cuối.
  Dữ liệu đã có sẵn. (M2.)
- **Thử lại câu này:** trả lời lại một câu sau khi xem feedback. Lần thử lại không tính là bằng
  chứng; phải thiết kế để không vi phạm ADR 0005 ("never fake evidence"). (M2+.)
- **Preset độ dài:** Nhanh 3 câu (~15 phút), Chuẩn 5 câu, Đầy đủ 8 câu, kèm thời gian ước tính. (M1, trong N3/N5.)
- **Ôn lại chỗ yếu:** buổi sau ưu tiên Skill và concept lần trước yếu. Cần lịch sử. (M2.)
- **Báo cáo chia sẻ được** (link hoặc PDF). (Sau M2.)

## 8. Không làm trong 2 milestone này

Thí nghiệm E1–E6, multi-judge, accounts/Postgres (#84), voice (#87), CV import (#86),
redesign (#60), làm sạch nợ duplication (#128).
