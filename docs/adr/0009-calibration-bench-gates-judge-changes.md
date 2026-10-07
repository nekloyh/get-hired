# The calibration bench gates every judge change

Any change to the **Evaluator** — its prompt, self-critique thresholds, structured-output path, or
the provider/model behind it — must pass `coach bench` (the hand-labeled, bilingual golden-answer
set, issue 0022) with no range regression before it merges. **A provider swap is a judge change.**
Bench reports — per-dimension bias, EN/VN paired-answer deltas, and confidence calibration — are
versioned in `docs/audits/` so judge quality has a history, not a vibe.

## Why

The entire value chain flows through one LLM judgment: Evaluation → Beta skill state → Supervisor
deviation decisions → Study Plan. ADR 0001's single-judge design is only defensible if the judge
is *measured*; the 2026-07 audit found its trust resting on ~5 golden cases whose expected ranges
cannot even separate a weak answer from a strong one, and — after MiMo's expiry forced a provider
change — **zero** recorded validation of the replacement judge in either language. That is the
proof case: the model behind every score changed, and nothing in the repo would have caught a
drift.

Gating on the bench institutionalizes the project's eval-discipline lesson (goal #1 is learning
agentic patterns): judge meta-evaluation, confidence calibration ("does 0.9 mean right 90% of the
time?"), and drift detection across model swaps are the exact skills the harness exists to teach.

## Considered Options

Relying on the existing `eval-harness` CLI exit code alone was rejected: without hand labels,
per-band anchors, and paired-language cases it can go green while the judge drifts on precisely
the axes the product depends on (weak/strong separation, VN parity). Continuous live testing in CI
was rejected for cost and flakiness on free-tier providers — the bench is a deliberate,
pre-merge, human-triggered gate.

## Addendum (2026-07-19): gate-as-code, measurement ceiling, and the two-bench contract

Three extensions, each closing a hole the original text left open.

### (a) The gate must also hold at runtime: the judge role is pinned

This ADR gates *merges*, but the router un-gates the judge *at runtime*: a single transient
primary-provider error trips the blanket `except Exception` failover (`llm.py:392`) and the
hardcoded preference order (`config.py:69`) hands the judge role to Groq `llama-3.3-70b` — a model
that **fails this bench** (18/20, known VN over-scoring Δ=2.00) — silently, mid-Session, logged
only as a warning. A merge gate with a runtime hole is not a gate.

Decision: **the judge role is pinned to a model with a green bench artifact in `docs/audits/`.**
Judge-role failover is retry-same-model, degrade, or suspend (ADR 0005's budget-exhaustion
addendum) — **never a model swap**. Other roles may fail over freely.

**Both halves have landed.** The per-role router pins the judge to a single provider client with no
failover wrapper (ADR 0010, R-18/GH #73, PR #95), and the router's blanket `except Exception` is
gone (R-09/GH #64): failover is now typed to `is_provider_failure`, so a code bug or a
misconfiguration propagates instead of quietly buying a second provider's answer. Audits should
still state which model actually judged — that is cheap provenance, not a stopgap.

### (b) The measurement has a ceiling: labels and repeatability

The gate is currently a **single run of a stochastic judge** (global `LLM_TEMPERATURE=0.2`) over
n=29 cases labeled by one rater. That ceiling is now measured, not hypothetical: k=3 identical
runs on 2026-07-19 returned 28/29, 28/29, 29/29 — `dl_overfitting_weak_vi` scored 3.30/3.30/3.20
against a band top of 3.2, after passing 3/3 on 2026-07-11 on an unchanged judge path
(`docs/audits/calibration-bench-2026-07-19.md`, GH #92). The band edge sits inside the judge's
score distribution; single-run green/red on that case is a coin flip, and provider-side drift is
real (the communication bias flipped +0.65 → −0.28 between the two dates).

Decision: the judge role runs the bench at `temperature=0` **or** the gate becomes median-of-k
(k=3) per case — one of the two, recorded when implemented (GH #92). Bands are set from a score
*distribution* (k runs), never from a single observation, and never widened just to go green (the
one-way-ratchet failure). New labels enter from two provenances beyond the original rater: the
Forge review queue (`data/bench/pending-cases-*.yaml`) and replayed live-session answers — both
human-reviewed before admission.

### (c) The two-bench contract

`coach bench` measures **the judge** (scores vs hand labels). The replay bench (issue 0029)
measures **the loop** (does the Session's trajectory recover a persona's ground truth). Every
architecture experiment must name its gate up front: judge-touching changes gate on `coach bench`
(this ADR); Supervisor/evidence-semantics changes gate on the replay bench (experiments E1/E2);
changes touching both gate on both. "It passed a bench" without naming which one is not evidence.

*Source: ADR red-team review 2026-07-19 — verdict REAFFIRM + 3 AMENDs; Wave-0 execution k=3 data
(GH #92); remediation decisions B1 (judge pinning) and the R-15/R-17 label/backup-judge program.*

## Addendum (2026-07-27): the gate is median-of-k — resolving (b)'s open choice

Addendum (b) left one decision open: the judge runs the bench at `temperature=0` **or** the gate
becomes median-of-k. **Resolved: median-of-k, k=3, at the production temperature (`0.2`).**

### The decision, and why not temperature=0

`temperature=0` was rejected on two counts. First, it measures a judge configuration that never
ships — every real Session judges at `LLM_TEMPERATURE=0.2`, so a gate at 0 certifies a different
sampler than the one the value chain runs on. Second, it does not actually buy determinism: hosted
inference is not bitwise reproducible at temperature 0 (batching and expert-routing nondeterminism
survive greedy decoding), so it would have traded away production fidelity for an *appearance* of
repeatability, and the "three consecutive runs, same exit code" bar could still have failed.

Median-of-k keeps the production sampler and is self-consistent with this addendum's own rule about
bands: if a band must be derived from a score *distribution*, the gate should read that same
distribution rather than one draw from it. The median is the cheapest robust statistic of it, and at
odd k it is always an **observed** run — so the representative judgment every downstream metric
reads (bias, confidence calibration, trust guards, delivery) stays one internally coherent
judgment, never a blend.

**Costs, accepted:** k× tokens per gate (~150k for k=3 over 35 cases, against a 2.5M daily budget),
and the preflight scales with k. `--k 1` remains available for a cheap indicative run and is
explicitly **not** a merge gate.

**Errored runs are dropped, not fatal**, provided at least one run survived. With k draws instead of
one, a single transport blip became k times more likely to red the gate on infrastructure rather
than judge quality — the measurement-side reading of ADR 0005's "infrastructure noise must never
corrupt skill evidence". The surviving run count is reported; an all-errors case is still an error.

### The straddle tripwire

A case whose k runs land partly inside and partly outside its band is reported as **straddling**.
It does not gate — the median is the verdict — but it is the signal whose absence let GH #92 hide:
on 2026-07-11 `dl_overfitting_weak_vi` passed 3/3 and looked healthy, and eight days later the same
case was 1/3. A straddle says the band edge cuts through the judge's score distribution, i.e. the
case is one provider nudge from flipping, *while its median still reads green*. Straddles are
tracked and resolved, never tolerated as background noise.

### Band re-derivation procedure

1. Bands are derived from a **k≥3 distribution**, never a single observation, and are recorded with
   the run data that produced them.
2. **A band is never widened to turn a red run green.** That is the one-way ratchet this ADR exists
   to prevent: each widening buys one green run and permanently lowers the bar.
3. When a case's median sits outside its band, the order of investigation is **diagnose before
   re-band**: identify the dimension driving it (per-dimension scores, and for a paired case the
   EN/VN twin delta) and fix the *judge guide* if the judge is wrong. Re-deriving the band is the
   remedy only when the human **label** is wrong — which must be argued from the answer and the BARS
   anchors, not from the judge's output.
4. Re-anchor cadence: the bench is re-run k=3 on any judge-touching change, and the bands are
   re-examined whenever a bias tripwire fires (|bias| > 0.5 at n ≥ 8) or a case straddles.

### Worked precedent: `dl_overfitting_weak` (GH #92)

Rule 3 applied, and it found a real defect rather than a mis-set band. Per-dimension measurement
(k=3 on both twins) showed the judge scoring the **same answer in two languages** two points apart:

| dimension | EN | VN | human label |
| --- | --- | --- | --- |
| correctness | 2/2/2 | **4/4/4** | 3 |
| communication | 3/3/3 | **4/4/4** | 3 |
| depth · system_thinking | 2/2/2 · 2/2/2 | 2/2/2 · 2/2/2 | 2 · 2 |

Root cause: `correctness` carried BARS anchors at 1, 2, 4, 5 and **none at 3**. "Names the right
technique, justifies it with a bare *so it is better*" had no home on the scale, so the judge fell
off whichever side the *phrasing* suggested — and idiomatic Vietnamese reads as more authoritative
than clumsy English. `communication`, which already had a 3 anchor, split by only one point on the
identical pair: the size of the split tracked the size of the hole in the scale.

Remedy: add the missing 3 anchor to `correctness` (and to `communication`), and make the
language-invariance rule **operational** — restate the answer's claims as plain English propositions
and score that restatement, rather than merely instructing the judge to be unbiased. After the
re-anchor the EN twin matched the human label on all four dimensions and the pair's holistic delta
closed from +1.10 to 0.00.

The generalisable lesson, which is why this is in the ADR and not just an audit: **a missing middle
anchor is a language-fairness bug.** Any dimension with a gap in its BARS scale lets the judge
resolve the gap on style, and style is exactly what the bilingual bench exists to keep out of the
score. Every anchor gap is a latent EN/VN split.

That generalisation was then confirmed on a second pair in the same run. `panel_sd_retry_storm` —
the trap case whose confident prose recommends actions that would *worsen* an outage — carries a
stable |Δ| of 2.00, and the per-dimension split lands exactly where the remaining holes are:

| dimension | EN | VN | Δ | has a `3` anchor? |
| --- | ---: | ---: | ---: | :---: |
| communication · correctness | 4.00 · 1.00 | 4.00 · 2.00 | 0.00 · +1.00 | yes (added 2026-07-27) |
| depth | 2.00 | 3.33 | **+1.33** | **no — 2 and 4 only** |
| system_thinking | 1.33 | **3.67** | **+2.33** | **no — 2 and 4 only** |

The dimensions whose hole was filled now agree across languages; the two that still have one carry
the whole split. **`depth` and `system_thinking` remain to be anchored at 3**, tracked as GH #96:
both are weighted in every case, so re-anchoring them moves the whole set and must land with its own
k=3 evidence rather than riding along with the run that discovered it.

*Source: GH #92 resolution, 2026-07-27 — per-dimension EN/VN diagnosis, judge-guide re-anchor, and
admission of the six 2026-07-11 pending cases. Evidence:
`docs/audits/calibration-bench-2026-07-27.md`.*

## Addendum (2026-07-27b, landed 2026-10-06): a scale fix must name the boundary it decides — GH #96

These two rules were recorded on 2026-07-27 with the first attempt at #96. That attempt lived on a
draft branch that never merged (PR #104, closed 2026-10-06, code at tag
`archive/pr-104-anchor-depth-system-thinking`). **The anchor change itself is not on `main`**:
`depth` and `system_thinking` still lack their middle band, and #96 still owns that. The rules are what the
attempt taught, they hold for every judge change, and the project already treated them as binding, so
they land here on their own. Evidence: `docs/audits/calibration-bench-2026-07-27-anchor96.md`, a
record of that unmerged attempt.

Both findings generalise beyond that case, and both cost a red gate to learn.

### (e) An unscoped anchor is a bar change, not a scale fix

The first working wording added the middle band *and* an operational test for it ("a mechanism says
HOW the technique produces the effect, not merely what it does"). The test was correct, but the
judge applied it **everywhere**, not only at the 2/3 boundary it was written for: `depth` bias went
+0.03 → −0.11 and strong answers that had been stable at 4.00/4.00/4.00 began drawing 3.5–3.7, until
one fell below its 3.8 floor.

Rule: **every anchor clause states which boundary it decides and that it does not raise the bar
above it.** A clause phrased as a general principle will be applied as one. This is the mirror image
of the missing-anchor bug: a hole lets the judge invent a threshold, and an unscoped rule moves every
threshold. Both surface as band-edge instability rather than as an obviously wrong score.

### (f) One green invocation is not a measurement, and the gate must be re-run per wording

The unscoped wording returned **35/35, 35/35, 34/35**. Had the first invocation been taken as the
gate, a change that reds one run in three would have merged with a green artifact attached to it.
Addendum (d), the 2026-07-27 median-of-k addendum above, made the *gate* median-of-k; this one makes
the *evidence* multi-invocation. A judge change merges when repeated invocations agree, and each new
wording restarts that count: a green run of wording A says nothing about wording B. Where the daily
token budget cannot cover the repeats, the change waits. It does not merge on the runs that were
affordable.

*Source: GH #96, 2026-07-27: three measured wordings, a per-dimension EN/VN diagnosis on both
regressed pairs, and the strong-case regression that a single-invocation reading would have missed.
Landed on `main` 2026-10-06 (GH #141) when the branch that carried it was archived.*

## Addendum (2026-10-06): "is this a judge change?" is now a test — GH #141

### (g) Every judge change moves a hash that the suite pins

Until this addendum, the gate held only if a reviewer recognised a change as a judge change, and one
slipped through. #129 deleted `SelfCritiqueTrace` in `v0.2.0`, and the three Panel prompts, which
embed the first-pass JSON, lost their `"self_critique":null` key. By this ADR's first sentence that
is a prompt change. Nothing noticed it.

`interview_coach.judge_lock` computes a **judge fingerprint**: the sha256 of the exact requests the
judge would send for three canonical answers. A request means `model`, `temperature`, `messages` and
`response_format`, built by the production client's own `request_kwargs`. The three answers between
them walk every request path `evaluate` has: the first pass, the evidence and weak-delivery repairs,
and the Panel's skeptic, advocate and verdict. Scripted replies stand in for the provider.
`judge.lock` pins the fingerprint, and `tests/test_judge_lock.py` fails when the code's fingerprint
differs. A refactor that sends the same bytes passes. A change to a prompt, an anchor, the schema,
the escalation policy, the model, the temperature or the endpoint fails, and the failure message
names the procedure.

1. **A red `test_judge_lock` is this ADR's gate, not a test to update.** The lock moves only together
   with a confirm-bench artifact (k=3, repeated per (f)) that carries the new fingerprint. `coach
   bench` prints the fingerprint, says whether it matches the lock, and stamps it into the report.
2. **The lock pins what the code builds**: the bench-validated triple at the default temperature. An env
   override (`ROLE_JUDGE_TEMPERATURE`, `LLM_TEMPERATURE`) gives a different fingerprint in the bench
   report, and that is how a run on a non-default configuration shows it cannot be the lock's artifact.
3. **A measured baseline is not a green one.** The lock's first baseline is the 2026-09-15 artifact, RED
   at 34/35, and #96 owns the red case. Fixing that case is a judge change like any other.
4. **The fingerprint covers requests, not replies.** Provider-side drift inside a pinned model id is
   invisible to it. The 2026-09-15 red case moved with no code change (see that artifact's commit,
   `df45374`). Only re-running the bench sees that kind of drift.

*Source: GH #141, 2026-10-06. Recomputed at `df45374`, the code the 2026-09-15 bench ran, the
fingerprint differs from `main`'s only by the `self_critique` key above. That run never escalated
(105 calls = 35 cases × 3 sweeps), so every request it sent is byte-identical to what `main` sends.*
