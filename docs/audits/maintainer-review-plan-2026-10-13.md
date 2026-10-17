# Kế hoạch review toàn bộ cho maintainer — 2026-10-13

Record có ngày, viết tại `2ceaf81` (`v0.3.0`) sau khi maintainer duyệt sáu thay đổi tracker của
[`pilot-plan-2026-10-13.md`](pilot-plan-2026-10-13.md) §6. Đây là **thứ tự đọc và danh sách quyết
định** để maintainer tự review lại toàn bộ hạng mục, docs và ADR rồi chốt định hướng. Nó không phải
status: milestone và issue nằm trên GitHub, ADR nằm ở dòng `Status:` của từng ADR.

Mỗi khối dưới đây = *đọc gì* → *trả lời câu hỏi nào* → *quyết định ghi ở đâu*. Quyết định được đánh
số `D-x`; ghi tất cả vào một record mới `docs/audits/direction-decisions-<ngày>.md` theo mẫu ở §7.
Chỉ sau record đó mới sửa dòng `Status:` của ADR, mô tả milestone, hay `CHANGELOG.md`. Ước lượng giờ
là opinion.

## 0. Đã làm hôm nay (fact, kiểm lại được trên GitHub)

| Việc | Trạng thái |
|---|---|
| PR #166: record review + sửa 40 docs + plan + record này | mở, chờ maintainer merge; gate xanh trên branch |
| #96 | mở lại; title và body ghi state tại `v0.3.0` và baseline 2026-09-15 |
| Milestone `v0.4.0 Pilot-ready` (#6) | tạo, mô tả = P1–P10; chứa #139 và 15 issue mới |
| Milestone `v0.4.0 Foundation` → `v0.5.0 Pilot round 2` (#5) | đổi tên, bỏ "fixes #96"; giữ #96, #103, #125, #126, #127, #143; nhận #83, #85 |
| `Later` (#3) | mô tả cập nhật; #60 đóng (not planned); #88 đóng, gộp vào #184; còn 8 issue |
| Issue mới | 27 issue #167–#193 (2026-10-14), bảng §8: 15 trong `v0.4.0 Pilot-ready`, 12 trong `v0.5.0 Pilot round 2` |
| `CLAUDE.md`, `docs/roadmap.md` | câu ưu tiên và thứ tự milestone sửa theo §0 của plan (trong PR #166) |
| ADR | **không đổi** gì, kể cả 0015 trên PR #161 |

## 1. Cách dùng kế hoạch này

- Đọc **record trước, evergreen sau, code sau cùng**. Record nào cũng ghi commit nó đo; evergreen
  doc chỉ nói *how/why*; khi hai bên lệch nhau thì code tại `2ceaf81` là sự thật.
- Mỗi quyết định có ba đáp án chuẩn để khỏi mở rộng phạm vi: **giữ / sửa / bỏ** (ADR: keep /
  amend / supersede-reject; issue: keep / amend / close).
- Một ngày allowance là 2,5M token. Mọi thí nghiệm hay bench phải có budget ghi trước khi chạy
  (`docs/issues/README.md`, mục gates). Khối C liệt kê chi phí từng thí nghiệm để quyết định
  *có chạy hay không* trước khi quyết định *chạy khi nào*.
- Thứ tự khối: **E (vận hành, 1 h) → A (sản phẩm, 2 h) → B (issue, 2 h) → C (ADR, 4–6 h) → D (docs,
  1,5 h)**. E trước vì #139 chặn pilot và chỉ maintainer làm được. C sau A vì quyết định ADR chỉ cần
  đến khi M2 mở, và A có thể đổi câu hỏi của C.

## 2. Khối E — vận hành và chi phí (≈1 h)

| Đọc | Câu hỏi | Quyết định |
|---|---|---|
| #139; `docs/pilot-runbook.md` §1 | Key nào đã từng nằm trong checkout, chat, transcript? | **D-E1** xoay và thu hồi toàn bộ key (OpenAI, Groq, ZenMux nếu có). Việc này không chờ review nào khác |
| `docs/deploy.md`; issue hosting (#179) | Pilot chạy ở đâu: Cloudflare Tunnel, Tailscale Funnel, hay VPS + certbot? | **D-E2** chọn một đường; runbook §3 và #179 viết lại theo đó |
| `docs/audits/live-smoke-2026-10-12.md`; plan §3 dòng Token | Ngân sách token mỗi ngày cho pilot là bao nhiêu, và dành bao nhiêu ngày cho anchor (#96 ≈0,6–0,7M mỗi wording)? | **D-E3** số: budget/ngày pilot, số ngày dành cho judge work trong M2 |
| `docs/deploy.md` §5 | Backup ra đâu, tần suất, ai kiểm tra restore? | **D-E4** đích backup và lịch |

## 3. Khối A — sản phẩm và hướng đi (≈2 h)

Đọc [`pilot-plan-2026-10-13.md`](pilot-plan-2026-10-13.md) §0–§4, §7, §8, rồi
[`docs-review-2026-10-12.md`](docs-review-2026-10-12.md) §4 (lỗi code) và §6 (kickoff facts).

| Quyết định | Câu hỏi | Ảnh hưởng |
|---|---|---|
| **D-A1** | Giữ hướng A (hành trình người dùng trước, anchor sau) hay đổi? | thứ tự milestone; nếu đổi, mọi việc ở §0 đảo lại được bằng tay |
| **D-A2** | Nhóm pilot: bao nhiêu người, role nào (ML/AI engineer, data scientist, NLP…), mode ngôn ngữ nào (`en`/`vn`/`mixed`)? | bảng alias role (#173), nội dung (#184), smoke live (#181), budget (D-E3) |
| **D-A3** | Độ dài buổi mặc định (3/5/8 câu) và rail thời gian theo số câu | #169, #172, P6 |
| **D-A4** | Trong §7, tính năng nào vào M1, M2, hay không làm: "câu trả lời tốt sẽ nói tới…", coach mode, thử lại câu, preset độ dài, ôn chỗ yếu, báo cáo chia sẻ | #175, issue mới nếu cần |
| **D-A5** | Kênh feedback vòng 1: form ngoài (#180) đủ chưa, hay cần trong app ngay (#185)? Người dùng được nói gì (token chung, không riêng tư, câu trả lời gửi OpenAI)? | runbook §2, P9 |
| **D-A6** | Exit P1–P10 giữ nguyên hay sửa (ví dụ P6 "3/5 Skill khác nhau" có đúng kỳ vọng?) | mô tả milestone #6 |
| **D-A7** | Điểm VN lệch tới 1 điểm ở câu yếu (plan §1 dòng 11) chấp nhận công bố cho vòng 1, hay chặn pilot đến khi #96 land? | nếu chặn: #96 chuyển lên M1 và M1 cần ≈0,6–0,7M token |

## 4. Khối B — issue và milestone (≈2 h)

Đọc theo thứ tự: milestone #6 (từng issue theo thứ tự plan §4), rồi #5, rồi `Later`. Mỗi issue mới
đã qua một vòng phản biện (agent soạn → agent khác bác bỏ → sửa) nhưng chưa qua mắt maintainer.

| Quyết định | Câu hỏi |
|---|---|
| **D-B1** | Từng issue M1: keep / amend / close, và thứ tự. Đặc biệt kiểm: AC có đo được bằng test 0 token không, effort có hợp lý không |
| **D-B2** | Từng issue M2: giữ ở M2 hay dời; #127 (lịch sử Skill) có cần chờ quyết định 0015 không, hay làm bản tối thiểu trên JSON hiện có |
| **D-B3** | `Later` còn 8: #71, #72, #79, #84, #86, #87, #128, #146. Giữ đóng băng cả 8? #86 body vẫn mô tả AC "CV upload" cũ: viết lại hay đóng |
| **D-B4** | Những điểm review thấy nhưng **chưa file** (chủ ý, vì chạm ADR đang dừng): bench không có pair tolerance EN/VN dù ADR 0007 nói có (`bench.bench_passed`); chưa có test cấp Session cho Diagnostic degraded; docstring `tests/test_serde_golden.py` và ADR 0009(h) ghi 207k trong khi record đo 181–212k; ADR 0009 "~150k". File issue hay sửa trong đợt ADR |

## 5. Khối C — ADR (≈4–6 h, có thể chia nhiều ngày)

Đầu vào: bảng §5 của [`docs-review-2026-10-12.md`](docs-review-2026-10-12.md) (khuyến nghị từng
ADR), ADR gốc trong `docs/adr/`, và với 0015 là PR #161 (`docs/adr/0015-*.md` +
`docs/audits/adr-0015-gate-2026-10-12.md` trên branch `docs/adr-0015-store`). Review theo mức ảnh
hưởng tới pilot, không theo số thứ tự. Lọc mục Proposed **theo header section**, không theo tên file
(ADR 0001 và 0002 có section Proposed bên trong ADR Accepted).

| Thứ tự | ADR | Câu hỏi phải trả lời | Bằng chứng (fact) | Khuyến nghị của review (input, không ràng buộc) | Chi phí nếu cần thí nghiệm |
|---|---|---|---|---|---|
| 1 | **0015** store SQLite (Proposed, PR #161) | Accept / amend / reject? Quyết định này mở khóa #143 → #127 → repeat practice ở M2 | record 0015 ghi "both gate conditions hold" là quá: restore check chưa chạy `load_priors`, `.unreconciled` không phải input; "keep legacy readers" không làm được ở 0.3.0 vì `usage.ledger_path` và `config.Settings.ledger_db` chỉ đọc một đường | accept with amendments: legacy readers trong 0.3.x, restore check đầy đủ | 0 token |
| 2 | **0009** bench gate + addenda a–h | Giữ gate median-of-k k=3; sửa bốn record sai, câu về #96, dạng `--only a b` (action=append). E4 có chạy không? | code enforce (`config.BENCH_VALIDATED_JUDGES`, `tests/test_judge_lock.py`); `judge.lock` → RED 34/35 | amend text | E4 ≈0,2–0,4M, 10–15 h, viết cho 29 case nên phải sửa gate trước |
| 3 | **0007** language first-class | ADR nói gate có pair tolerance; `bench.bench_passed` không có. Thêm pair gate vào code hay sửa ADR? | `bench.language_deltas` chỉ vào report | amend hoặc thêm pair gate | 0 token (code) hoặc một lần confirm nếu đổi gate |
| 4 | **0011** derived confidence (Proposed, E4/E5) | Giữ Proposed, hay reject vì E5 (shadow cutover) 2,7–6M token không đáng cho pilot? | self-critique trigger dormant; E4/E5 chưa chạy | amend gates trước khi chạy; E5 not now | E5 2,7–6M |
| 5 | **0001** control hierarchy + Amendment Proposed (E1, E4) | Giữ Supervisor với một LLM "deviate?" call hay bỏ call đó? Câu "over the full exchange" sai (judge chỉ thấy một lượt) | E1 chưa chạy | amend text | E1 ≈1,0M, 8–12 h |
| 6 | **0002** Bayesian priors + Addendum Proposed (E2) | Chạy thêm E2 (cần 2 persona) hay reject addendum? Câu "starvation" sai (`supervisor._extra_probe_required`) | E2 n=1 âm | amend | E2 ≈0,1M, 3–6 h |
| 7 | **0014** taxonomy as pack data (Proposed, E6) | Chạy E6 (0 token, 25–40 h) hay để nguyên? Phần "cảnh báo role lạ" đứng riêng được và #173 đã làm phần đó | premise tái hiện được | amend scope | E6 0 token |
| 8 | **0005** intent/infra/budget | Giữ; bổ sung `usage.AccountingUnavailable` và case quota-rồi-failover (issue #186) | holds | amend | 0 |
| 9 | **0006** + slice 0027 Panel | Sửa câu "higher-confidence of two passes": `evaluator.evaluate` escalate rồi giữ verdict vô điều kiện; `raw_mastery` cũng xuyên Session | holds, tested | amend wording | 0 |
| 10 | **0003** tool-use confined | Addenda mô tả plumbing MiMo đã xóa (`3f19c99`); E3 có chạy không? | core holds | amend; E3 | E3 0,7–1,2M |
| 11 | **0008** packs as data | Mô tả selection/rotation sai; trỏ sang 0014 | lint holds | amend | 0 |
| 12 | **0010** per-role routing | Dòng `Status:` còn "until it lands" dù #73 đóng (PR #95, 2026-07-19) | implemented | amend Status line + Why | 0 |
| 13 | **0004** hand-roll trước LangGraph | historical; ghi chú có ngày: Micro-loop chưa migrate | historical | keep + note | 0 |

Quyết định ghi: **D-C1…D-C13**, mỗi dòng một ADR: keep / amend (addendum có ngày) / supersede /
reject section Proposed, và với thí nghiệm: chạy (budget, khi nào) / không chạy. Sau đó một PR ADR
duy nhất; chỉ maintainer đổi dòng `Status:`.

Opinion về thứ tự chi phí: nếu chỉ chạy một thí nghiệm trong hai tháng tới thì là **E2** (rẻ nhất,
trả lời câu hỏi có ảnh hưởng điểm số). E1, E3, E5 không phục vụ pilot.

## 6. Khối D — docs evergreen (≈1,5 h)

Sau khi merge PR #166, đọc lại từng file một lần, hỏi hai câu: *còn đúng với code tại `2ceaf81`
không* và *còn cần tồn tại không*.

| Doc | Hỏi | Quyết định |
|---|---|---|
| `CLAUDE.md` | Mục "Where the ADRs override the MVP docs" còn cần khi MVP docs đã xóa? Câu "All LLM calls go through LLMRouter" đã sửa (judge dùng `llm._pinned_role_client`) | **D-D1** giữ / rút gọn |
| `CONTEXT.md` | 4 finding thuật ngữ (`X3-02` self-critique, `X3-04` tên row ledger) đã sửa; có term nào thiếu (Skill history, feedback)? | **D-D2** |
| `README.md` | bảng Known limits đủ 14 vấn đề của plan §1 chưa; setup `PRIMARY_PROVIDER` | **D-D3** |
| `docs/roadmap.md` | §1 viết lại hôm nay; §2–§5 giữ? | **D-D4** |
| `docs/pilot-runbook.md`, `docs/deploy.md` | viết lại theo D-E2 (hosting) trong #179 | theo #179 |
| `docs/issues/00NN-*.md` (37 slice spec, ~30 có note Superseded/Partial) | giữ tại chỗ như lịch sử (README nói `## Status` là historical) hay chuyển vào `docs/issues/archive/`? | **D-D5**; opinion: giữ, vì link từ issue và record còn trỏ tới |
| `docs/research/*` (2026-09-02) | Report 1/2 viết theo ưu tiên cũ (learning-first); thêm note có ngày hay để nguyên | **D-D6** |
| `docs/audits/implementation-plan-2026-09-13.md` | đã superseded as sequence; giữ | — |
| `CHANGELOG.md` | không đổi cho tới release `v0.4.0` | — |

## 7. Mẫu record quyết định

`docs/audits/direction-decisions-<ngày>.md`:

```
# Direction decisions — <ngày> (tại <commit>)
| ID | Quyết định | Đã đọc | Hệ quả (ADR Status / milestone / issue / doc) | Budget nếu có |
|---|---|---|---|---|
| D-E1 | … | #139, runbook §1 | #139 đóng | 0 |
| D-C1 | 0015: accept with amendments | PR #161, record 0015, review §5 | Status: Accepted (ngày); #143 mở khóa | 0 |
```

Một dòng một quyết định; "chưa quyết" cũng là một dòng, kèm điều kiện để quyết.

## 8. Khóa `N*`/`S*` của plan → issue trên GitHub

Filed on 2026-10-14. Mỗi body đi qua hai agent: một soạn, một bác bỏ lại từng claim với code tại
`2ceaf81` (0 token provider); 24/27 cần sửa ít nhất một chỗ, không bản nào bị bỏ. Báo cáo phản biện
nằm ngoài repo, trong thư mục phiên làm việc. `S9` là lỗi người phản biện `N4` tìm thêm và phiên chính đã chạy lại bằng chứng (demo, 0 token): resume một
Session đã xong trên web không bị từ chối và ghi lại Skill ledger. `N8` được tách thành `N8` (hiển
thị, không đổi `src/`) và `N8b` (ghi concept id, đổi golden). #88 đóng, gộp vào #184.

| Khóa plan | Issue | Milestone | Severity | Title |
|---|---|---|---|---|
| `N1` | #167 | M1 | blocker | Web resume keeps the old `started_at`, so a resumed Session ends on the 30-min rail |
| `N2` | #168 | M1 | blocker | Demo Sessions write the real Skill ledger; `auto` quietly turns pilot Sessions into demo |
| `N3` | #169 | M1 | high | The 30-minute rail counts typing time; the web UI never sends, shows, or explains it |
| `N4` | #170 | M1 | high | A completed Session's id is reused for the next Start, so the second interview is refused |
| `S9` | #171 | M1 | medium | Web resume of a finished Session is not refused and re-writes the Skill ledger |
| `N5` | #172 | M1 | high | Setup: remember/validate the Candidate id, name a bad token, default to 5 questions |
| `N6` | #173 | M1 | high | Unrecognised target roles silently get all-PERIPHERAL Role criticality |
| `N7` | #174 | M1 | high | First question per Skill comes only from exact-difficulty matches (13/45 at target 3) |
| `N8` | #175 | M1 | high | Web report hides the evidence behind each score: quotes, per-turn scores, stop reasons |
| `N8b` | #176 | M1 | medium | Show each question's expected_concepts notes in the report and export |
| `N9` | #177 | M1 | medium | Study Plan ranks Skills the Session never asked, showing a self-claim as a measurement |
| `N10` | #178 | M1 | medium | UI copy is maintainer jargon: raw enums, env-var names in errors, a `uv sync` banner |
| `N11` | #179 | M1 | blocker | Pilot hosting path with HTTPS, a daily off-machine backup, and a daily health report |
| `N12` | #180 | M1 | high | Feedback link on the report screen with the Session id; runbook §2 says answers go to OpenAI |
| `N13` | #181 | M1 | high | Live smoke of one `vn` and one `mixed` Session on the pilot stack, ≤ 150k tokens |
| `N14` | #182 | M2 | medium | `mlops_awareness` is anchored at 1 and 5 only: the missing-middle hole of ADR 0009(d) |
| `N15` | #183 | M2 | high | A returning Candidate gets the same first questions: nothing records what was asked |
| `N16` | #184 | M2 | medium | LLM/RAG questions, `vietnamese_nlp` to 9 questions, and two company packs (absorbs #88) |
| `N17` | #185 | M2 | medium | One token per friend mapped to a principal, and in-app feedback stored with the Session id |
| `S1` | #186 | M2 | low | Quota dead on the primary and the fallback fails: one zero-evidence `failed` question |
| `S2` | #187 | M2 | low | CLI `--ledger-db` / `--checkpoint-db` defaults ignore COACH_LEDGER_DB and COACH_CHECKPOINT_DB |
| `S3` | #188 | M2 | low | `coach ingest-concepts` passes `embedding_model=None` and skips the per-embedder persist dir |
| `S4` | #189 | M2 | low | Stale comments in src and compose: 'Green today 35/35', `--log-file`, nginx 'no curl' |
| `S5` | #190 | M2 | low | `PANEL_MAX_ESCALATIONS_PER_QUESTION` is read from the environment and documented nowhere |
| `S6` | #191 | M2 | low | Session token estimate ignores turns; the 2026-10-12 smoke cost 2.3x the estimate |
| `S7` | #192 | M2 | low | CLI `--resume` ignores the checkpoint's `candidate_id`; the ledger write is skipped |
| `S8` | #193 | M2 | low | The bench's `english_delivery` gate rests on 5 cases whose labels are only 2 or 5 |

Sửa đáng chú ý nhất trong vòng phản biện (fact, đã đo): test P6 ban đầu của #174 không thể fail
(một cặp id chọn tay đã khác nhau ≥3/5 Skill với selector cũ, khoảng 69% số cặp), nay là test tỷ lệ
trên 1.000 cặp với ngưỡng 80%; bước chứng minh 0 token của #184 trỏ tới một lệnh CLI không tồn tại
và có tốn token, nay là test `DemoLLMClient`.

## 9. Sau khi có record quyết định — việc agent làm được

- ADR: soạn addendum/amendment theo D-C*, không đổi `Status:`; một PR.
- Tracker: sửa mô tả milestone, body issue theo D-A*/D-B*; đóng/mở theo quyết định.
- Docs: đồng bộ `CLAUDE.md`, `CONTEXT.md`, `README.md`, `roadmap.md` theo D-D*.
- Code: bắt đầu M1 theo thứ tự, mỗi issue một PR, `scripts/gate.sh` trước mỗi push; #181 (smoke
  live) chỉ chạy khi có budget ghi trước.
