# Roadmap — what to build next, on what hardware, and why in that order

Written 2026-09-15, at `v0.1.0-pilot`. This is the *direction* document: the sequencing table in
[`issues/README.md`](issues/README.md) stays canonical for what each milestone contains, and an ADR
still wins over both. What this adds is the two questions that plan does not answer — which work
unblocks the rest, and what the machine it runs on can and cannot host.

Priority is unchanged: **(1) learn agentic systems, (2) a usable prep tool, (3) recruiter signal.**

---

## 1. The binding constraint is the cost of measuring the judge, not the code

M0 and M1 are done. The one gate still red is the judge calibration bench — 34/35, an EN/VN split on
`depth` and `system_thinking`, both of which have a hole at 3 in their 1–5 scale
([#96](https://github.com/nekloyh/get-hired/issues/96)).

It is not stuck on difficulty. It is stuck on price. Every k=3 invocation costs roughly 181k–207k
tokens, a judge re-wording restarts the repeatability count from zero, and three green invocations
are required before a change is believed — because one green run is not a measurement (a #96 wording
already went 35/35, 35/35, 34/35). So every attempt costs ~600k tokens and most of that is spent
generating *candidate answers*, not judging them.

That is the lever. The judge must stay on an API — ADR 0009 pins it, and no model that fits in 6 GB
of VRAM passes the bench. **The candidate does not.** The replay bench
([0029](issues/0029-simulated-candidate-replay-bench.md)) already exists for exactly this, and it has
one defect in the way: replay artifacts record no pack, so the bench always measures the built-in
bank ([#113](https://github.com/nekloyh/get-hired/issues/113)).

**Fix #113, then put a local model behind the simulated candidate, and #96 becomes affordable.**

---

## 2. Hardware — buy nothing

| | |
|---|---|
| CPU | i7-12700H, 20 threads |
| RAM | 31 GB |
| GPU | **RTX 3060 Laptop, 6 GB VRAM** |
| Disk | 334 GB free |

6 GB of VRAM is the only real constraint, and it does not sit on the critical path.

| Workload | Local? | Note |
|---|---|---|
| **Judge** (`gpt-5.4-mini`) | **No** | pinned by ADR 0009 and its addendum a; the judge role never fails over, let alone to a local model. Any swap is a bench-gated change |
| **Simulated candidate** (replay bench) | **Yes** | a 7–8B at Q4 is ~4.5 GB. This is the lever in §1 |
| **Embeddings** (`bge-small-en-v1.5`, `bge-m3`) | **Yes**, easily | what an honest answer to [#130](https://github.com/nekloyh/get-hired/issues/130) would need if the "wire it" half is chosen |
| **Vietnamese STT** ([#87](https://github.com/nekloyh/get-hired/issues/87) voice spike) | **Yes** | `whisper-large-v3-turbo` quantized is ~1.6 GB; PhoWhisper is the VN-specific option. The cheapest spike in the backlog — no API spend at all |
| **Postgres/Supabase** ([#84](https://github.com/nekloyh/get-hired/issues/84)) | **Yes** | the images are already on this machine |

A second machine or a bigger GPU buys nothing that is currently blocking, because the thing that is
blocking is an API-priced measurement, not local compute.

---

## 3. Order of work

| # | Work | Why here |
|---|---|---|
| 1 | **[#113](https://github.com/nekloyh/get-hired/issues/113)** — replay artifacts carry pack/model/prompt provenance | unblocks §1. Until an artifact says which pack it was recorded against, the replay bench cannot be trusted as the cheap tier |
| 2 | **Local candidate behind the replay bench** | turns the expensive half of every judge experiment into local compute |
| 3 | **[#96](https://github.com/nekloyh/get-hired/issues/96)** (then [#103](https://github.com/nekloyh/get-hired/issues/103)) — anchor `depth` and `system_thinking` at 3 | the last red line on the milestone. A missing middle BARS anchor is a measured language-fairness bug, not a style question (ADR 0009 addendum d) |
| 4 | **Q1 — session/turn/role attribution on the trace** (continues [#81](https://github.com/nekloyh/get-hired/issues/81)) | every per-call `llm-call` line exists but carries no Session, turn or role. Without that a trajectory cannot be reconstructed — and reconstructing trajectories is learning goal #1 |
| 5 | **[#127](https://github.com/nekloyh/get-hired/issues/127) → [#83](https://github.com/nekloyh/get-hired/issues/83)** — Skill history, then the progress dashboard | closes the loop the tool exists for: practise → see it move → practise again. The ledger keeps **one snapshot per Candidate** today, so there is literally nothing to chart. #127 before #83, not beside it |
| 6 | **[#87](https://github.com/nekloyh/get-hired/issues/87)** — VN voice spike, go/no-go | runs entirely on this GPU. A spike with a stop point, per M5a |

Not next, deliberately: **[#84](https://github.com/nekloyh/get-hired/issues/84) (accounts/Postgres)**
is a public-launch gate, not a pilot dependency, and building it early means maintaining auth through
every schema change that #127 and #83 are about to make.

---

## 4. Build-with-AI practice — where this project already is, and what is missing

Assessed against practice as of this writing; re-check the tooling names before adopting one.

| Practice | State here | Work |
|---|---|---|
| **Model changes gate on an eval** | **done and unusually strict** — ADR 0009, median-of-k, "never widen a band to go green" | keep |
| **Cost accounting per call** | **done** — usage ledger, daily caps, `ACCOUNTING:` fails loud and blocks metered work | [#125](https://github.com/nekloyh/get-hired/issues/125)/[#126](https://github.com/nekloyh/get-hired/issues/126) are polish |
| **Structured output** | **done** — per-model `json_schema` capability | — |
| **Per-role model routing** | **done** — ADR 0010, judge pinned in code | this is where a local model slots in (§2) |
| **Two-tier evals** | **missing** — one tier, expensive, run by hand | cheap tier (replay/golden, zero API calls) on every PR; expensive tier only on judge/prompt changes. Depends on #113 |
| **Prompt versioning** | **missing** — prompts are inline, and a bench artifact does not record which prompt produced it | stamp a prompt hash into the bench artifact. Without it "which prompt was that 35/35 on?" is unanswerable |
| **Trace attribution** | **partial** — every call logs `llm-call provider= model= ms= …`; none of it carries Session/turn/role | Q1 above. OpenTelemetry GenAI semantic conventions plus a self-hosted viewer (Langfuse/Phoenix) both run comfortably on this box |
| **Trajectory eval** | **partial** — the replay bench exists, but its artifacts are pack-blind | #113 |
| **Human-in-the-loop labelling** | **half-built** — the Question Forge writes a review queue that nothing reads back | either close the loop or delete the writer; [#129](https://github.com/nekloyh/get-hired/issues/129) |
| **Refactor safety net** | **done** — `tests/test_serde_golden.py` is a byte-identity harness | use it, not `coach bench`, to prove a refactor changed nothing |

---

## 5. Not doing, and why

- **Score-averaging multi-judge consensus** — measured worthless on this judge: the verdict moved
  0.00 across 10 forced escalations. Cheap multi-vote as an *uncertainty* signal is ADR 0011, still
  Proposed and experiment-gated.
- **Modern RAG (HyDE / hybrid / rerank)** — the toy store scores 47/50 against embedders' 46–47/50 at
  the current shelf size. The Skill filter is doing the work. Triggers to revisit are in #68.
- **Transcript RAG for judging** — ADR 0006. Scoring memory stays decayed Beta priors.
- **A visual redesign as a release prerequisite** — [PR #50](https://github.com/nekloyh/get-hired/pull/50)
  stays open until feedback comprehension and repeat practice are done.
- **An operations dashboard** — `docker compose logs` and `coach usage` are the interface.
