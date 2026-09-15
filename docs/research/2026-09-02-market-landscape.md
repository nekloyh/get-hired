# AI mock-interview / interview-prep market landscape (global + Vietnam)

- Date accessed: 2026-09-02 (all URLs fetched that day unless noted)
- Scope: commercial candidate-side prep products (global), employer-side AI interviewers candidates face, and the Vietnamese market.
- Method: primary sources only for claims (vendor pages, pricing pages, docs, store listings, press releases). Listicles were used only to discover names. Where a vendor page could not be fetched or a fact could not be verified, that is stated explicitly.
- Tags in the synthesis: `[SOURCED]` = backed by a cited primary URL; `[INFERRED]` = my inference from the sourced facts.
- Status: COMPLETE for this run. Unverifiable items are stated as such per section; see C0 for the Vietnamese-search limitation and D6 for the gap list.

Per-product fields: URL; positioning/target; modality; question source; adaptivity; scoring/feedback; progress tracking; languages; integrations; pricing/free tier; platform; traction evidence; published quality/calibration claim.

---

## A. Candidate-side, global

### A1. Final Round AI (Interview Copilot + AI Mock Interview)
- URL: https://www.finalroundai.com/pricing
- Positioning/target: general job seekers; flagship is a *live* "Interview CoPilot" that feeds answers during real interviews, with a practice-interview product alongside.
- Modality: live audio/video call assist (desktop app) plus AI practice interviews; works "with Zoom, Meet, Teams, Webex, HackerRank, CoderPad and phone screens".
- Question source: JD-tailored ("Job description parsing and prep checklist") plus resume/"materials" uploaded as "Goals".
- Adaptivity: not stated on the pricing page.
- Scoring/feedback: "Automatic AI debriefs" after sessions; "Screen help with Auto-capture" for coding/system-design questions. No rubric or dimensions published.
- Progress tracking: not stated.
- Languages: claims "143 Languages & accents" (Vietnamese not individually verified).
- Integrations: desktop app ("macOS 14.4+ and Windows"), meeting tools above; "Stealth Mode" hides guidance from screen shares.
- Pricing: Free plan $0 (goals, JD parsing, desktop app); Pro "$25+/mo" ("Unlimited live Interview CoPilot sessions", practice interviews, debriefs).
- Traction (vendor-claimed, same page): "10M+" job seekers, "80+ countries", "4.9 on Product Hunt".
- Published quality/calibration claim: none found.
- Policy stance on live copilot: see A10 (copilots) below.

### A2. Yoodli
- URL: https://yoodli.ai/pricing
- Positioning/target: AI "roleplay" communication coach — interview prep is one use case next to public speaking and sales; heavy enterprise push ("hundreds of enterprise teams", Snowflake, Google Cloud, Harness named).
- Modality: voice/video roleplay with an AI persona; also feedback on uploaded recordings.
- Question source: scenario/persona-driven; enterprise tier offers "Custom AI scenarios". No CV/JD import stated on the pricing page.
- Adaptivity: not stated on the pricing page.
- Scoring/feedback: enterprise tier advertises "rubric-based scoring aligned to your sales methodology" (rubric is customer-defined, not a published interview rubric). Delivery analytics — see homepage note below if verified.
- Progress tracking: "team dashboards" (enterprise).
- Languages: not listed on the pricing page.
- Integrations: SSO, SCIM, "LMS/HRIS integrations" (enterprise).
- Pricing: Starter free — "5 lifetime sessions"; Pro $8/mo (annual) — "up to 10 roleplays per week"; Advanced $20/mo (annual) — "unlimited roleplays", data excluded from AI training; Team/Enterprise custom.
- Platform: web (desktop/mobile availability not stated on that page). "SOC 2 Type 2 certified", "GDPR compliant".
- Traction: no user counts on the pricing page beyond the enterprise-logo claim.
- Published quality/calibration claim: none found.

### A3. Big Interview
- URL: https://biginterview.com/pricing/
- Positioning/target: the incumbent "interview simulator" for general job seekers, sold heavily B2B2C to "Education Career Centers", "Government Workforce Agencies", "Non-Profits".
- Modality: recorded video answers to a virtual interviewer.
- Question source: curated bank ("Master the most common interview questions"), organised as interview sets.
- Adaptivity: fixed question sets; no adaptive follow-ups claimed.
- Scoring/feedback: "VideoAI" gives "instant AI insights on delivery, clarity, and more"; separate "Big Resume" AI resume feedback; answer-builder tool. No scoring dimensions or rubric published.
- Progress tracking: not stated on pricing page.
- Languages: not stated (English product).
- Integrations: institutional licensing (career centres, libraries) rather than job-board integrations.
- Pricing: "Interview BootCamp" $39/mo (30 days); "Interview Accelerator" $99 (3 months); "Interview Pro" $299 lifetime; 30-day money-back guarantee. No free tier beyond institutional access.
- Traction (vendor-claimed): "Join over 2 million people who chose Big Interview".
- Published quality/calibration claim: none found.

### A4. interviewing.io
- URL: https://interviewing.io/
- Positioning/target: "Anonymous mock interviews with engineers from Meta, Google, OpenAI, Amazon, and other top companies" — premium, live-human, senior-SWE market.
- Modality: live human (anonymous video/voice + shared editor); also an **AI Interviewer** that "conducts coding and system design interviews, in the style of a FAANG mock interview".
- Question source: interviewer-chosen (human); AI Interviewer covers coding + system design. Tracks: algorithms/DS, coding, system design, "Machine learning (algorithms & system design)", front-end, eng management, behavioural, staff+/manager.
- Adaptivity: inherent for the human format; not stated for the AI Interviewer.
- Scoring/feedback: human written feedback per session (format not detailed on homepage); no published rubric.
- Progress tracking: not stated on the homepage.
- Languages: English only (no other language mentioned).
- Integrations: none stated (standalone).
- Pricing: per-session/dedicated-coaching packages ("3, 5, or 10 sessions" for Amazon/Google/Meta coaching); exact prices not on the homepage and `/pricing` returned 404 on 2026-09-02. Free: AI Interviewer, "over 200 problems from *Beyond Cracking the Coding Interview* for free", "9 chapters for free".
- Traction (vendor-claimed): "Our users have gotten over $50B in job offers from FAANG, OpenAI, Anthropic, and many more."
- Published quality/calibration claim: none found for the AI Interviewer.

### A5. Exponent — now rebranded "Aced" (includes Pramp peer mocks)
- URL: https://www.tryexponent.com/ (site now brands itself "Aced (formerly Exponent)"; `/pricing` returns 404, pricing lives at `/upgrade` — see A5 note below if fetched)
- Positioning/target: role-specific interview courses + mocks for PM, SWE, Data Science, Machine Learning, Data Engineering, System Design, EM, "Forward Deployed Engineering", TPM, UX, Security, Analytics.
- Modality: peer-to-peer live mocks (the Pramp lineage), "expert coaches from top companies" (paid), video courses, question bank with "100+ video answers".
- Question source: curated bank per role; "Real interview questions".
- Adaptivity: peer/coach sessions only; no AI adaptive interviewer claimed on the homepage.
- Scoring/feedback: peer/coach feedback; no rubric published on the homepage.
- Progress tracking: not stated.
- Languages: English (no other language mentioned).
- Integrations: none stated; B2B2C via universities ("Stanford GSB, Columbia Engineering, Cornell Johnson, Yale SOM" named).
- Pricing: free account ("Get started for free"); the paid tier lives at `/upgrade`, which rendered only navigation to the fetcher on 2026-09-02 — prices NOT verified.
- Traction (vendor-claimed): "Join over 600,000 people using Aced"; "500K+ candidates who've landed jobs at top companies".
- Published quality/calibration claim: none found.

### A6. Huru
- URL: https://huru.ai/
- Positioning/target: general job seekers; mock interviews generated from the job posting the user is applying to.
- Modality: recorded video answers with "Subtle, real-time tips as you answer"; playback for self-review.
- Question source: bank ("50,000+ Questions") **and** JD-tailored — "import job postings via Chrome extension, or upload job descriptions to generate custom interview questions".
- Adaptivity: not claimed (question set generated up front).
- Scoring/feedback: AI feedback on "answer accuracy, speech clarity, and confidence" (answer quality + speech patterns + confidence). No rubric dimensions published.
- Progress tracking: enterprise "admin dashboard and analytics"; individual tracking not described.
- Languages: explicit list includes **Vietnamese** (alongside English, French, Japanese, Hindi, Korean, German, Spanish, Italian, Portuguese, Russian, Filipino, Arabic, Chinese).
- Integrations: Chrome extension (job-post import), web, iOS app.
- Pricing: Starter $24.99/month; Growth $99/year; Enterprise custom; "Free trial with full platform access" (no permanent free tier stated).
- Traction (vendor-claimed): "4.8/5 rating by 20,000+" users.
- Published quality/calibration claim: none found.

### A7. HackerRank — candidate side (Interview Preparation Kit)
- URL: https://www.hackerrank.com/interview/interview-preparation-kit
- Positioning/target: free curated DS&A challenge list for candidates ("Learnings from 1000+ Companies").
- Modality: text/coding challenges only; "no mention of mock interviews, AI interviewers, or AI-powered candidate features" on this page — hints come from "Discussion and Editorial sections".
- Question source: fixed bank grouped by 13 topics, each tagged with a frequency such as "70% of companies test this subject" (Arrays).
- Adaptivity: none. Scoring: automated test-case pass/fail only. Progress: per-challenge completion. Languages: English. Pricing: free.
- Employer-side HackerRank AI interviewing is covered in section B.
- Published quality/calibration claim: none.

### A8. LeetCode — Premium / interview features
- URL attempted: https://leetcode.com/subscribe/ and https://leetcode.com/interview/ — the site returned HTTP 403 to the fetcher on 2026-09-02, so no first-hand claims are recorded here. (Widely known features — company-tagged questions, timed "mock" assessments — are NOT cited because they could not be verified from a primary page in this run.)

### A9. Google Interview Warmup
- URL attempted: https://grow.google/certificates/interview-warmup/ — on 2026-09-02 this URL served a generic "How to prepare for an interview" guide that recommends practising with **Gemini Live** and does not mention the Interview Warmup product. The original product page could not be retrieved; treat Interview Warmup as **not verifiably live** on 2026-09-02, with Google's own guidance now pointing at Gemini Live for AI practice. (No pricing, language, or feature claims are recorded for this reason.)

### A10. "Interview copilot" products and their stated policy stance
- **Final Round AI — Interview Copilot** (https://www.finalroundai.com/interview-copilot): markets the tool as "completely invisible to interviewers", "Undetectable on Zoom, Teams, and Meet", running "silently in the background like a digital sticky note or teleprompter"; frames output as "subtle prompts, feedback, and suggestions" and "an expert coach whispering perfect answers". The page has **no** FAQ addressing whether live use is cheating. Claims "91 languages and regional accents" on this page (pricing page says 143). Has a mock-interview mode ("Start your mock interview session or open it in the background during a live call").
- **Sensei AI** (https://www.senseicopilot.com/): "Instant answers to any question during live interviews", "Fully undetectable and unnoticeable by interviewers across all types of interviews", "100% hands-free experience". Free plan: 15-minute copilot sessions + resume builder; Pro $24/mo annual or $89/mo monthly; "30+ Languages"; integrates with "Zoom, Microsoft Teams, and Google Meets"; a "Playground" sandbox stands in for mock interviews. Traction claims: "Join 11K+ Job Seekers", "96% Interview Success Rate", "7000+ Interviews Aced", "1500+ Offers" — none audited. Explicitly positions as "better than Final Round AI".
- **LockedIn AI** (https://www.lockedinai.com/pricing): products "Interview Copilot", "Coding Assistant", "Phone Interview Copilot", "Online Assessment Helper", "Mock Interview", and "LockedIn DUO (Remote Assist)" (human assistance during interviews). "Unlimited" vs "Credits" plans ("Credits never expire", "Money-back guarantee"); amounts not rendered on the fetched page. Web, desktop app, mobile app. "Trusted by 58,000+ professionals". No language list or policy statement on the pricing page Homepage (https://www.lockedinai.com/): "LockedIn AI runs quietly in the background and is visible only to you"; for the human-assist Duo mode "The interviewer sees only you and your normal screen share. There are no LockedIn AI overlays, no helper presence"; frames ethics as privacy/consent ("Your privacy comes first"), links to an "Is LockedIn AI Safe?" page whose content was not fetched. Claims "1M+ users", "4.8" over "2,739 reviews", "116ms average response speed", "50+ languages supported"; "The basic version...is free for everyone; premium plans are available".
- Common pattern: all three sell **live-interview answer generation** as the headline, position mock interviews as secondary, publish detectability claims rather than ethics policies, and none publishes an answer-quality or calibration measure.



## B. Employer-side AI interviewers candidates face (format only)

### B1. HireVue
- URL: https://www.hirevue.com/
- Format: on-demand ("automated") asynchronous video interviews; a separately listed "AI Interviewer" product; "Virtual Job Tryout", "Game-Based Assessments", "Technical Assessments" incl. "coding assessments", "Language Proficiency Tests"; "AI Hiring Agent" for "24/7 AI-driven engagement" and self-scheduling.
- Traction: outcome case studies only on the homepage ("92% candidate satisfaction" Nestlé, "60% less time screening", "90% faster time-to-hire"); no interview-volume figure on the page.

### B2. Paradox (Olivia)
- URL: https://www.paradox.ai/
- Format: conversational AI over SMS/chat ("SMS on Workday", chat career sites) doing "Applicant screening" ("Validate important qualifications upfront, through chat or text") and "Interview scheduling"; a "Video interviewing" module exists. High-volume hourly hiring, not technical interviewing.
- Traction: Chipotle, 7-Eleven, General Motors named; Compass Group "120,000 workers a year", 7-Eleven "40,000 hours per week" saved.

### B3. micro1 (Zara)
- URL: https://www.micro1.ai/ — on 2026-09-02 the homepage presents micro1 as a "data lab" (products "Realm", "Cortex", "Robotics" for AI-model training data) and **does not mention Zara or AI interviewing**. The AI-recruiter interview product could not be verified from a primary page in this run; no format claims recorded.

### B4. Mercor
- URL: https://mercor.com/
- Format: the homepage describes an expert marketplace ("30k+ experts: physicians, lawyers, engineers, consultants", "$4M+ Daily payouts", "Average contracted rate $113/hr", "427k Roles created") and its APEX benchmarks; the candidate-facing AI video interview flow is **not described on the homepage**, so no format claim is recorded. Site cites CNBC: "now valued at $10 billion with new $350 million funding round".

### B5. Apriora (Alex)
- URL: https://www.apriora.ai/ → 301 → https://www.alex.com/ (rebranded "Alex").
- Format: conversational AI first-round interviewer across "phone calls, video interviews, and text conversations"; "personalized interviews with each candidate, acting as your always-on first round interviewer"; customer quote on adaptivity: "Alex is able to carry out more of a conversation based on specific things that I'm mentioning"; a "Proctor" feature flags moments for review. "30 Languages". Coding-interview support not mentioned on the page.
- Scoring to employers: "Alex evaluates every candidate resume against your specific job criteria"; standardized evaluation claimed; no rubric or calibration figure published.
- Traction (vendor-claimed): "1,000,000 Candidates interviewed", "33 Officially supported ATS integrations", "We raised $20M".

### B6. HackerRank (employer-side, for contrast)
- URL: https://www.hackerrank.com/products/interview/
- Format: **live human-led** coding interviews where "Candidates work a ticket in a multi-file repository with prebuilt starter code" and "with an AI assistant the way they would on the job"; "Every session is recorded end to end"; interviewer sees "the prompts, the changes, and the reasoning as it happens". No autonomous AI interviewer on this page; no automated scoring claimed.

## C. Vietnam

### C0. How Vietnam was searched, and what could not be done
- The session's WebSearch quota was exhausted before this section; DuckDuckGo HTML returned a CAPTCHA for all three Vietnamese queries ("phỏng vấn thử AI", "luyện phỏng vấn AI Việt Nam", "X-Interview … Hà Nội"); Bing returned unrelated results for the same queries (ordinal-number pages; X/Twitter pages). **Vietnamese-language discovery therefore did not happen in this run.**
- Verified by direct fetch: ELSA (C1), Prep (C2). **Not fetched (call budget): TopCV, ITviec, VietnamWorks, JobsGO, X-Interview** — their AI-interview status is UNVERIFIED here (C3, C4) and is the first thing a follow-up run should do.

### C1. ELSA Speak (Vietnam site)
- URL: https://elsaspeak.com/vi/ → 307 → https://vn.elsaspeak.com/
- Positioning/target: English pronunciation/speaking app for Vietnamese learners; AI speech analysis "Xếp Top 5 thế giới".
- Modality: voice (mobile app, iOS/Android). Conversation practice via short dialogue scenarios.
- Interview feature: **none on the page** — no "Interview Coach", no "phỏng vấn xin việc" scenario is mentioned. The "ELSA Interview Coach" name given in the brief could not be verified as a live product on 2026-09-02.
- Scoring/feedback: pronunciation scoring; no interview rubric.
- Languages: Vietnamese UI, English target language.
- Pricing (VND, listed): Premium Lifetime 8,800,000₫ (promo 3,299,000₫); Premium 1 year 2,745,000₫ → 1,716,000₫; Pro Lifetime 3,395,000₫ → 2,195,000₫; Pro 1 year 1,595,000₫ → 1,095,000₫. Free tier not described on the page.
- Traction (vendor-claimed): "50,000,000+ lượt tải trên toàn cầu", "10,000,000+ lượt tải tại Việt Nam", "195+ quốc gia".
- Status: live (marketing + store links). Published calibration claim: none.

### C2. Prep (prep.vn)
- URL: https://prep.vn/ → 301 → https://prepedu.com/vi/
- Positioning/target: test-prep platform (IELTS incl. IELTS Junior, TOEIC 4 skills, VSTEP, HSK; PrepTalk conversational English); personalised routes ("Lộ trình học được 'may đo' theo 'thông số riêng'").
- Modality: web/app; "Prep AI Virtual Rooms" for speaking practice "không bị gò bó theo kịch bản cố định" (not bound to a fixed script) — i.e., adaptive *language* roleplay, not interviews.
- Interview feature: **none** — the page has "NO mention of job-interview practice (luyện phỏng vấn)".
- Scoring/feedback: AI pronunciation scoring; detailed written feedback on writing.
- Languages: Vietnamese UI; English/Chinese (Korean/Japanese in blog).
- Pricing: per course, not on homepage. Traction: "100.000+ học viên đạt thành tích cao". Status: live. Calibration claim: none.

### C3. Vietnamese job boards — TopCV, ITviec, VietnamWorks, JobsGO
- Not fetched in this run (see C0). No claim is recorded about whether any of them ships an AI mock-interview feature, whether it is live or only marketed, its language, or its price. Treat as an open question, not as absence.

### C4. X-Interview (Hanoi)
- No domain could be located (Bing returned only X/Twitter results for the query). Nothing verified; existence and status unknown in this run.


### C3a. Vietnamese job boards — direct homepage fetch (added 2026-09-02, after C0)
- TopCV (https://www.topcv.vn/): homepage shows CV builder, job matching, MBTI/MI tests, salary tools and the group's B2B products (HappyTime.vn, TestCenter.vn, SHiring.ai); **no AI mock-interview / "phỏng vấn thử" feature on the homepage**. `/ai-interview` → 404.
- ITviec (https://itviec.com/): passive job search, IT CV templates, Story Hub, 28,928 company reviews, IT salary report 2025-2026; **no interview-AI feature on the homepage**.
- VietnamWorks (https://www.vietnamworks.com/): job search, inTECH IT jobs, employer portal, WowCV builder, HR reports; **no interview-AI feature on the homepage**.
- Vieclam24h (https://vieclam24h.vn/): job search, career guides, HR Nexus, mobile app; **no interview-AI feature on the homepage**.
- JobsGO (https://jobsgo.vn/): HTTP 403 to the fetcher — unverified.
- Caveat: homepages only; a feature buried in a sub-product or blog would not be seen here.

### C4a. X-Interview (Hanoi) — verified (https://x-interview.com/, fetched 2026-09-02)
- Positioning: "Trợ lý phỏng vấn AI" — "Chinh phục mọi buổi phỏng vấn"; target: candidates Fresher → Senior across industries.
- Modality: **voice** mock interview; user "Trả lời câu hỏi và nhận góp ý tức thì từ AI"; responses recorded to simulate interview pressure.
- Question source: bank "20,000+ questions from actual companies" — examples name FPT Software, VNG, Shopee, Grab, Momo; technical + behavioural + role-specific.
- Adaptivity: not stated (bank-driven).
- Scoring/feedback: per-answer "điểm số và nhận xét cụ thể cho từng phần trả lời"; evaluates content relevance, communication clarity, structure, confidence. No rubric anchors, no calibration figure.
- Languages: **Vietnamese and English**.
- Pricing: freemium — free tier = question bank + mock interviews; premium = unlimited practice + advanced analytics (amounts not on homepage; `/pricing` and `/bang-gia` see below).
- Company: Hanoi (Tầng 21 tòa nhà Viwaseen, 48 Tố Hữu). Traction (vendor-claimed): "10,000+ practice sessions", "4.9-star rating".
- [INFERRED] This is the closest direct VN competitor: same audience (VN candidates incl. tech), bilingual, voice-first, bank-driven, generic across industries; no published judge quality.

## D. Synthesis

### D1. Feature matrix (from the pages fetched on 2026-09-02; "—" = not stated on the fetched page)

| Product | Modality | Question source | Adaptive follow-ups | Feedback type | Delivery analytics | VN language | Free tier | Entry price | Calibration claim |
|---|---|---|---|---|---|---|---|---|---|
| Final Round AI (A1/A10) | live-call copilot + AI mock | JD + resume | — | "AI debriefs", tone/structure tips | tone feedback | claims 143/91 langs, VN unverified | yes ($0, no copilot) | "$25+/mo" | none |
| Yoodli (A2) | voice/video roleplay | scenario/persona | — | customer-defined rubric (enterprise) | pacing, conciseness, sentence starters | — | 5 lifetime sessions | $8/mo annual | none |
| Big Interview (A3) | recorded video | curated bank | no | "delivery, clarity" insights | yes (delivery) | no | none (B2B2C access) | $39/mo | none |
| interviewing.io (A4) | live human; AI coding/sys-design | interviewer / AI | human yes; AI — | human written feedback | no | no | AI Interviewer free | packages, price n/a | none |
| Aced/Exponent (A5) | peer + coach live; courses | curated bank | human only | peer/coach | no | no | free account | n/a (not rendered) | none |
| Huru (A6) | recorded video + live tips | bank 50k + JD import | no | answer accuracy, speech clarity, confidence | yes | **yes (listed)** | trial only | $24.99/mo or $99/yr | none |
| HackerRank prep kit (A7) | coding | fixed bank | no | test cases | no | no | free | free | none |
| Sensei AI (A10) | live-call copilot | live transcript | n/a | none | no | 30+ langs, VN unverified | 15-min sessions | $24/mo annual | none |
| LockedIn AI (A10) | live-call copilot + mock | live transcript | — | — | no | 50+ langs, VN unverified | basic free | n/a | none |
| ELSA (C1) | voice app | dialogue scenarios | language roleplay | pronunciation score | pronunciation | VN UI | — | 1,095,000₫/yr | none |
| Prep (C2) | web/app | test-prep | language roleplay | pronunciation/writing feedback | pronunciation | VN UI | free assessment | per course | none |
| Employer-side (B1–B6) | async video / AI voice / chat / live coding | employer JD | Alex: conversational | employer scorecards | — | Alex 30 langs | n/a | n/a | none |

Unverified in this run (no row): Google Interview Warmup (A9), LeetCode (A8), Interview Query (429 ×3), micro1 Zara (B3), Mercor candidate flow (B4), TopCV/ITviec/VietnamWorks/JobsGO/X-Interview (C3/C4).

### D2. Table stakes (2026) vs differentiators
- Table stakes [SOURCED — present on ≥4 of the fetched candidate-side pages]: a free tier or trial; JD or resume import (Final Round, Huru, LockedIn free resume tools, Sensei resume builder); some AI feedback after each answer; voice or video modality; multi-language claims (Final Round, Sensei, LockedIn, Huru); meeting-tool or Chrome integration.
- Differentiators actually observed [SOURCED]: live human interviewers from named companies (interviewing.io); peer-mock network + university channel (Aced: "600,000 people"); institutional licensing (Big Interview: career centres, workforce agencies); enterprise rubric + SOC2/GDPR + LMS/HRIS (Yoodli); "undetectable" live assistance (all three copilots).
- Not observed anywhere [SOURCED by absence across all 20 fetched pages]: a published scoring rubric for interview *content*, published dimensions, a calibration/agreement figure, a language-fairness statement, or an adaptive (state-dependent) follow-up policy described as such. Yoodli's "rubric-based scoring" is customer-supplied and sales-oriented; Alex's "standardized evaluation" carries no figure. [INFERRED] Content-quality judging is therefore an unclaimed axis in the market as of this run.

### D3. Modality trend
- [SOURCED] Candidate-side products fetched are predominantly voice/video (Yoodli, Big Interview, Huru, all copilots, ELSA); text-only is confined to coding-challenge banks (HackerRank kit) and the AI Interviewer at interviewing.io (coding/system design). [SOURCED] Employer-side is converging on conversational AI voice/video/phone at scale (Alex "1,000,000 Candidates interviewed", HireVue "AI Interviewer", Paradox chat/SMS screening), while HackerRank frames live coding around "working with an AI assistant the way they would on the job".
- [SOURCED] A distinct "copilot" segment has formed whose headline is live-answer generation and whose marketing axis is detectability, not learning (A10). [INFERRED] The practice/mock function inside those products is a secondary funnel feature.

### D4. What nobody publishes
- [SOURCED] None of the fetched vendor pages publishes: judge model, rubric anchors, inter-rater or model-vs-human agreement, temperature/repeatability, or any language-fairness measurement. Traction numbers are self-reported and unaudited (e.g., Sensei "96% Interview Success Rate"; Final Round "10M+"; LockedIn "1M+ users").
- [INFERRED] The repo's calibration bench (median-of-k gate, bilingual VN/EN anchors, measured EN-vs-VN split) has no visible counterpart in the commercial set fetched.

### D5. Vietnam gaps (facts)
- [SOURCED] The two Vietnamese platforms verified (ELSA, Prep) are English-learning products with adaptive *language* roleplay and pronunciation scoring, and neither exposes a job-interview mode on its homepage (C1, C2).
- [SOURCED] Among global products, only Huru lists Vietnamese explicitly (A6); Final Round, Sensei, LockedIn make aggregate language-count claims without a verified Vietnamese entry; interviewing.io, Aced, Big Interview, Yoodli, HackerRank state no Vietnamese support.
- [SOURCED] No fetched product targets AI/ML fresh graduates in Vietnam or bilingual VN/EN technical answers. [INFERRED] Whether a Vietnamese job board already ships an AI mock interview remains the single largest unknown (C3).

### D6. Acquisition levers observed
- Free-tier shapes [SOURCED]: lifetime-capped sessions (Yoodli: "5 lifetime sessions"); free plan that withholds the core feature (Final Round: $0 without copilot); time-boxed sessions (Sensei: 15-minute copilot sessions); free AI interviewer + free book content as lead magnet (interviewing.io: "over 200 problems … for free", "9 chapters for free"); free account with paywalled courses (Aced); trial-only (Huru); no consumer free tier, institutional access instead (Big Interview); free companion tools (LockedIn resume builder/checker, LinkedIn optimizer, job tracker).
- Integrations [SOURCED]: Chrome extension importing job posts from boards (Huru); meeting-tool overlays "Zoom, Meet, Teams, Webex, HackerRank, CoderPad" (Final Round; Sensei); ATS integrations on the employer side (Alex "33"); LMS/HRIS/SSO (Yoodli enterprise).
- B2B2C [SOURCED]: universities (Aced: Stanford GSB, Columbia Engineering, Cornell Johnson, Yale SOM); career centres, government workforce agencies, non-profits (Big Interview); enterprise coaching (Yoodli: Google Cloud "15,000+ employees", Snowflake); enterprise admin dashboards (Huru).
- Communities/social proof [SOURCED]: Product Hunt rating (Final Round "4.9"); review counts (LockedIn "2,739 reviews"); "$50B in job offers" outcome claim (interviewing.io); comparative positioning against the leader (Sensei: "better than Final Round AI").
- [INFERRED] Vietnam-specific channels (job boards, bootcamps, university career offices) could not be observed in this run because the Vietnamese discovery step failed (C0).

