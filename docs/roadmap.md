# Roadmap — what unblocks what, and what this machine can host

This is the *direction* document. **The [GitHub milestones](https://github.com/nekloyh/get-hired/milestones)
hold what each milestone contains and whether it is done.** This file does not repeat either, and an
ADR wins over both. It answers two questions a milestone list cannot: why this order, and what the
hardware can and cannot host.

Priority is unchanged: **(1) learn agentic systems, (2) a usable prep tool, (3) recruiter signal.**

---

## 1. Order: stable, then foundation, then features

| Milestone | Why it comes here |
|---|---|
| `v0.3.0 Stable` | The code was green; the system around it was not. Status copied into many documents drifted: `CLAUDE.md` called the judge green for two months after its gate went red. Two draft PRs aged 71 and 87 days, nothing ran against `main` during a pause, and one data-loss race (#122) is open. Nothing built on top of that can be trusted. |
| `v0.4.0 Foundation` | The next features touch the same two weak layers. **State:** every product step (#127 → #83, then #84) changes the usage and Skill ledgers, where the race and scaling defects cluster. One transactional store (#143) fixes four open issues by construction. **Measurement:** a judge change is affordable only if a wording can be screened cheaply (#145). A live problem is debuggable only if every call names its Session, turn and role (#144). The anchor fixes #96 and #103 come after both. |
| `Later` | Frozen until both close: features (#83–#88), the redesign (#60), and eval work gated on ADR sections that are still Proposed (#71, #72, #79). |

Not next, deliberately: **#84 (accounts/Postgres)** is a public-launch gate, not a pilot dependency.
Building it before #143 means porting several hand-rolled file formats instead of one schema, then maintaining auth
through every schema change #127 and #83 make.

---

## 2. A judge change costs judge tokens

A judge change (#96, #103) must pass `coach bench --k 3`, and pass it more than once (ADR 0009
addenda d–f). On all 35 cases one invocation costs ~181–207k tokens. One wording needs several
invocations, so it costs ~600k.

**All of it is judge spend.** The bench scores fixed, hand-labelled answers from
`data/bench/cases.yaml` (`bench._evaluate_case` → `evaluate`). Nothing generates a candidate answer.
An earlier version of this file blamed candidate generation and named a local simulated candidate as
the lever. That premise was wrong for this gate. Filtering by dimension does not help either: all 35
cases weight `depth` and `system_thinking`.

The lever is two speeds (#145):

- **Screen** a wording on ~10 target and sentinel cases (~60k tokens). A screen run is never gate evidence.
- **Confirm** only the wording that survives screening, on all 35 cases.

Screening three wordings and confirming the one that survives then costs ~0.8M tokens. Running all three on the full set three times each costs ~1.8M. A judge fingerprint (#141) ties
every confirm run to the exact judge configuration it measured.

The judge must stay on an API. ADR 0009 pins it, and no model that fits in 6 GB of VRAM passes the
bench. A local candidate is useful where candidates *are* generated, in the replay bench (slice 0029,
#146).

---

## 3. Hardware — buy nothing

| | |
|---|---|
| CPU | i7-12700H, 20 threads |
| RAM | 31 GB |
| GPU | **RTX 3060 Laptop, 6 GB VRAM** |
| Disk | 334 GB free |

The 6 GB of VRAM is the only real constraint, and nothing on the critical path needs more.

| Workload | Local? | Note |
|---|---|---|
| **Judge** (`gpt-5.4-mini`) | **No** | pinned by ADR 0009 and its addendum a; the judge role never fails over, let alone to a local model. Any swap is a bench-gated change |
| **Simulated candidate** (replay bench) | **Yes** | a 7–8B at Q4 is ~4.5 GB (#146). Not a lever for `coach bench`, which generates no answers (§2) |
| **Embeddings** (`bge-small-en-v1.5`, `bge-m3`) | **Yes**, easily | the concept store's optional Chroma path (`--extra rag`) |
| **Vietnamese STT** ([#87](https://github.com/nekloyh/get-hired/issues/87) voice spike) | **Yes** | `whisper-large-v3-turbo` quantized is ~1.6 GB; PhoWhisper is the VN-specific option. No API spend at all |
| **SQLite / Postgres** ([#143](https://github.com/nekloyh/get-hired/issues/143), [#84](https://github.com/nekloyh/get-hired/issues/84)) | **Yes** | SQLite is the stdlib; the Postgres images are already on this machine |

A second machine or a bigger GPU would not speed up anything on the critical path. What limits it is
API-priced measurement, and #145 is the lever for that.

---

## 4. Build-with-AI practice — where each one lives

The state of each practice is the state of the issue named here. This table does not record it.

| Practice | Where it lives in this repo | Gap tracked by |
|---|---|---|
| **Model changes gate on an eval** | ADR 0009: median-of-k, never widen a band to go green | #141 makes it mechanical |
| **Cost accounting per call** | the usage ledger; `ACCOUNTING:` fails loud and blocks metered work | #143 (storage), #125, #126 |
| **Structured output** | a per-model `json_schema` capability | — |
| **Per-role model routing** | ADR 0010; the judge role is pinned in code | — |
| **Two-tier evals** | **release tier**: `scripts/gate.sh` + browser specs + image build on every PR, no API spend. **Quality tier**: `coach bench`, only when the judge changes | #141, #145 |
| **Prompt versioning** | the judge fingerprint: a hash of the exact requests the judge receives | #141 |
| **Trace attribution** | the per-call `llm-call` line | #144 adds Session/turn/role |
| **Trajectory eval** | the replay bench (slice 0029), pack-aware since #113 | #146 (local candidate) |
| **Human-in-the-loop labelling** | the Question Forge review queue, one-way by design (#129) | — |
| **Refactor safety net** | `tests/test_serde_golden.py`, a byte-identity harness. Use it, not `coach bench`, to prove a refactor changed nothing | — |

---

## 5. Not doing, and why

- **Score-averaging multi-judge consensus**: measured worthless on this judge. The verdict moved 0.00
  across 10 forced escalations. Cheap multi-vote as an *uncertainty* signal is ADR 0011, which is
  Proposed and experiment-gated.
- **Modern RAG (HyDE / hybrid / rerank)**: the toy store scores 47/50 against the embedders'
  46–47/50 at the current shelf size, because the Skill filter is doing the work. The triggers to
  revisit are in #68.
- **Transcript RAG for judging**: ADR 0006. Scoring memory stays decayed Beta priors.
- **A visual redesign as a release prerequisite**: the redesign (#60) waits until feedback
  comprehension and repeat practice are done. Its code is kept at tag `archive/pr-50-frontend-redesign`.
- **An operations dashboard**: `docker compose logs` and `coach usage` are the interface.
