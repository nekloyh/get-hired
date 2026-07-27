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
addendum) — **never a model swap**. Other roles may fail over freely. Implemented by the per-role
router (ADR 0010, R-18/GH #73) and the typed-failover work (R-09/GH #64); until those land, every
audit must state which model actually judged.

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
