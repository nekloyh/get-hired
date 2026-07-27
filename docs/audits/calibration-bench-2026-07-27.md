# Judge Calibration Bench

- Date: `2026-07-27`
- Provider / model: `openai` / `gpt-5.4-mini`
- Gate: **median-of-k, k=3** (ADR 0009 addendum d)
- Cases within band: **35/35**

> **Verdict: GREEN.** This closes GH #92 (the 2026-07-19 AMBER gate). The body below is the canonical
> `coach bench --k 3` run; the sections immediately following are the repeatability evidence and the
> judge-guide re-anchor that got there. Everything here judged on `LLM_TEMPERATURE=0.2` — the
> production sampler.

## GH #92 resolution — what changed and what it bought

Three changes, in one PR because the gate change had to land before the case admission could be
interpreted:

1. **The gate is median-of-k (k=3)**, resolving the open choice in ADR 0009 addendum (b). Rejected
   `temperature=0`: it certifies a sampler production never runs, and hosted inference is not
   bitwise reproducible at temperature 0 anyway. Recorded as ADR 0009 addendum (d).
2. **The judge guide was re-anchored** — `correctness` and `communication` gained the missing `3`
   band, and the language-invariance rule became an operational test rather than an instruction.
3. **Six cases admitted** from `data/bench/pending-cases-2026-07-11.yaml` (29 → 35 cases), three of
   them amended at admission.

### DoD: repeatability

`coach bench` was invoked **4 times**, each internally k=3 — **12 full sweeps of all 35 cases, 420
judgments**, on unchanged code:

| invocation | within band | gate exit |
| --- | --- | --- |
| 1 | 35/35 | **0** |
| 2 | 35/35 | **0** |
| 3 | 35/35 | **0** |
| 4 (canonical, this report) | 35/35 | **0** |

**Same exit code four consecutive times, and zero straddling cases in any of them** — no case had
runs landing partly inside and partly outside its band. Compare 2026-07-19, where the identical
command returned exit 1, 1, 0.

Three cases' medians moved *between* invocations (`dl_overfitting_weak_vi`,
`vnlp_segmentation_weak_vi`, `panel_ml_eval_on_train_en`), all by ≤1.00 and all deep inside wide
bands. That is ordinary judge stochasticity: the point of the median is that it absorbs it instead of
letting it decide the gate.

### The flaky case: diagnosed, not re-banded

`dl_overfitting_weak_vi` was the case that made the gate a coin flip. ADR 0009 addendum (d)'s
procedure says diagnose before re-banding, so both twins were scored k=3 per dimension. The twins are
exact translations of each other and carry identical human labels:

| dimension | EN before | VN before | EN after | VN after | human label |
| --- | --- | --- | --- | --- | --- |
| correctness | 2/2/2 | **4/4/4** | 3/3/3 | 4/4/3 | 3 |
| communication | 3/3/3 | **4/4/4** | 3/3/3 | **3/3/3** | 3 |
| depth | 2/2/2 | 2/2/2 | 2/2/2 | 2/2/2 | 2 |
| system_thinking | 2/2/2 | 2/2/2 | 2/2/2 | 2/2/2 | 2 |
| **holistic** | 2.17 | 3.27 | **3.00** | **3.00** | 2.65 |

**Root cause: `correctness` had BARS anchors at 1, 2, 4, 5 and none at 3.** "Names the right
technique, justifies it with a bare *so it is better*" had nowhere to land, so the judge fell off
whichever side the *phrasing* suggested — and idiomatic Vietnamese reads as more authoritative than
clumsy English. `communication`, which already had a 3 anchor, split by only 1 point on the identical
pair. The size of the split tracked the size of the hole in the scale.

The band was **not** widened. It is still `1.6–3.2`; the judge moved into it. Across all 12 sweeps the
VN twin's highest single draw was 3.20 — at the edge, never over it (it was 3.30 twice in three runs
on 2026-07-19).

### Bias and language fairness vs 2026-07-19

| dimension | 07-19 bias | 07-27 bias | n | note |
| --- | ---: | ---: | ---: | --- |
| communication | −0.28 | **−0.17** | 35 | improved |
| correctness | −0.31 | **−0.26** | 35 | improved |
| depth | −0.17 | **+0.03** | 35 | improved |
| system_thinking | +0.00 | +0.09 | 35 | flat |
| mlops_awareness | +0.00 (n=4 ⚠) | +0.25 (**n=8, ok**) | 8 | now statistically grounded |
| english_delivery | +0.00 (n=3 ⚠) | +0.00 (n=5 ⚠) | 5 | still under `BIAS_MIN_SAMPLES` |

No bias tripwire fired (all |bias| well under ±0.5). EN/VN paired deltas: **mean |Δ| 0.30 → 0.17**,
with `dl_overfitting_weak` 1.00 → **0.00**, `ml_regularization_medium` 0.60 → 0.00, and
`mlops_monitoring_strong` 1.00 → 0.00.

### Open finding: `panel_sd_retry_storm` — the same defect, two more dimensions

`max |Δ|` is still **2.00**, on `panel_sd_retry_storm`, and it widened (1.00 → 2.00) rather than
closing. This is reported, not hidden: both twins are in band in all 12 sweeps so the gate is
genuinely green, but the pair is a measured language split and the cause is now known.

Per-dimension, k=3 on both twins (same trap answer in two languages — advice that would *cause* a
retry storm, dressed in confident prose):

| dimension | EN | VN | Δ | human label | has a `3` anchor? |
| --- | ---: | ---: | ---: | ---: | :---: |
| communication | 4.00 | 4.00 | 0.00 | 5 | ✅ added today |
| correctness | 1.00 | 2.00 | +1.00 | 2 | ✅ added today |
| depth | 2.00 | 3.33 | **+1.33** | 4 | ❌ **anchors 2 and 4 only** |
| system_thinking | 1.33 | **3.67** | **+2.33** | 2 | ❌ **anchors 2 and 4 only** |

The VN twin is credited with system_thinking 3.67 for advice that would deepen an outage. This is
**exactly** the `correctness` failure mode, relocated: the two dimensions that still have a hole at 3
are the two carrying the split, and the dimensions whose hole was filled today now agree across
languages. It is the strongest available confirmation of addendum (d)'s generalisation — *a missing
middle anchor is a language-fairness bug.*

Deliberately **not** fixed in this PR. Extending the re-anchor to `depth` and `system_thinking` moves
scores on all 35 cases (both dimensions are weighted in every case), which invalidates the 12-sweep
evidence banked above and needs its own gated measurement — which is what ADR 0009 requires of any
judge change. Filed as **GH #96**.

A secondary question this raises, for that follow-up: whether the **human label** of 3.00 is right
here. It is held up by `communication: 5` and `depth: 4` — the case rewards the polish of actively
harmful advice — while the judge's EN holistic of 1.00 caps it as dangerous. Addendum (d) allows
re-deriving a label when the label is what is wrong, argued from the answer and the anchors.

## Per-case scores

The score column is the MEDIAN over k runs; `runs` shows every draw, so a case whose distribution sits on a band edge is visible here rather than discovered when it flips.

| case | skill | lang | expected | score | runs | conf | escalation | in-band |
| --- | --- | --- | --- | ---: | --- | ---: | --- | :---: |
| ml_bias_variance_weak_en | ml_fundamentals | en | 1.0-2.6 | 2.00 | 2.00/2.00/2.00 | 0.97 | — | ✅ |
| ml_bias_variance_weak_vi | ml_fundamentals | vi | 1.0-2.6 | 2.00 | 2.00/2.00/2.00 | 0.96 | — | ✅ |
| ml_bias_variance_strong_en | ml_fundamentals | en | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| ml_bias_variance_strong_vi | ml_fundamentals | vi | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.89 | — | ✅ |
| ml_regularization_medium_en | ml_fundamentals | en | 2.8-4.2 | 4.00 | 4.00/4.00/3.40 | 0.95 | — | ✅ |
| ml_regularization_medium_vi | ml_fundamentals | vi | 2.8-4.2 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| dl_overfitting_weak_en | deep_learning | en | 1.6-3.2 | 3.00 | 3.00/3.00/3.00 | 0.95 | — | ✅ |
| dl_overfitting_weak_vi | deep_learning | vi | 1.6-3.2 | 3.00 | 3.00/2.80/3.20 | 0.95 | — | ✅ |
| dl_overfitting_strong_en | deep_learning | en | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.95 | — | ✅ |
| dl_overfitting_strong_vi | deep_learning | vi | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.96 | — | ✅ |
| vnlp_segmentation_weak_en | vietnamese_nlp | en | 1.0-2.6 | 2.10 | 2.00/2.20/2.10 | 0.96 | — | ✅ |
| vnlp_segmentation_weak_vi | vietnamese_nlp | vi | 1.0-2.6 | 2.10 | 2.10/2.60/2.00 | 0.98 | — | ✅ |
| vnlp_segmentation_strong_en | vietnamese_nlp | en | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.94 | — | ✅ |
| vnlp_segmentation_strong_vi | vietnamese_nlp | vi | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.92 | — | ✅ |
| sd_backpressure_strong_en | system_design | en | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.90 | — | ✅ |
| sd_backpressure_strong_vi | system_design | vi | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.90 | — | ✅ |
| mlops_monitoring_strong_en | mlops | en | 3.8-5.0 | 4.00 | 4.00/4.50/4.00 | 0.92 | — | ✅ |
| mlops_monitoring_strong_vi | mlops | vi | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| prompt_injection_en | ml_fundamentals | en | 1.0-2.5 | 1.00 | 1.00/1.00/1.00 | 0.99 | — | ✅ |
| prompt_injection_vi | ml_fundamentals | vi | 1.0-2.5 | 1.00 | 1.00/1.00/1.00 | 0.99 | — | ✅ |
| mixed_dl_dropout_strong_vnmix | deep_learning | mixed | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| mixed_dl_dropout_weak_vnmix | deep_learning | mixed | 1.0-2.6 | 2.00 | 2.00/2.00/2.00 | 0.96 | — | ✅ |
| mixed_sd_cache_strong_en_delivery | system_design | mixed | 3.8-5.0 | 5.00 | 5.00/5.00/5.00 | 0.95 | — | ✅ |
| mixed_ml_leakage_broken_english | ml_fundamentals | mixed | 3.4-5.0 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| panel_sd_retry_storm_en | system_design | en | 1.0-3.2 | 1.00 | 1.00/1.00/1.00 | 0.97 | — | ✅ |
| panel_sd_retry_storm_vi | system_design | vi | 1.0-3.2 | 3.00 | 3.00/3.00/3.00 | 0.92 | — | ✅ |
| panel_ml_eval_on_train_en | ml_fundamentals | en | 1.2-3.4 | 3.00 | 3.00/3.00/3.00 | 0.93 | — | ✅ |
| panel_ml_eval_on_train_vi | ml_fundamentals | vi | 1.2-3.4 | 3.00 | 3.00/2.80/3.00 | 0.91 | — | ✅ |
| en_ml_leakage_broken_english | ml_fundamentals | en | 3.4-5.0 | 4.00 | 4.00/4.00/4.00 | 0.92 | — | ✅ |
| mlops_retraining_weak_en | mlops | en | 1.0-2.8 | 2.00 | 1.50/2.00/2.00 | 0.95 | — | ✅ |
| mlops_rollout_strong_en | mlops | en | 3.8-5.0 | 5.00 | 5.00/5.00/5.00 | 0.95 | — | ✅ |
| mlops_train_serve_skew_medium_en | mlops | en | 2.8-4.2 | 4.00 | 4.00/4.00/4.00 | 0.90 | — | ✅ |
| en_dl_batchnorm_broken_english | deep_learning | en | 3.4-5.0 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| mixed_mlops_drift_technical | mlops | mixed | 3.4-5.0 | 4.00 | 4.00/4.00/4.00 | 0.90 | — | ✅ |
| en_sd_idempotency_strong_delivery | system_design | en | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.97 | — | ✅ |

## Repeatability (k=3)

Cases whose score moved between runs. A ⚠ straddle means some runs landed in-band and others did not — the band edge cuts through the judge's distribution, so the case is one provider nudge from flipping the gate even while its median reads green.

| case | runs | median | spread | band | straddles edge |
| --- | --- | ---: | ---: | --- | :---: |
| ml_regularization_medium_en | 4.00/4.00/3.40 | 4.00 | 0.60 | 2.8-4.2 | no |
| vnlp_segmentation_weak_vi | 2.10/2.60/2.00 | 2.10 | 0.60 | 1.0-2.6 | no |
| mlops_monitoring_strong_en | 4.00/4.50/4.00 | 4.00 | 0.50 | 3.8-5.0 | no |
| mlops_retraining_weak_en | 1.50/2.00/2.00 | 2.00 | 0.50 | 1.0-2.8 | no |
| dl_overfitting_weak_vi | 3.00/2.80/3.20 | 3.00 | 0.40 | 1.6-3.2 | no |
| vnlp_segmentation_weak_en | 2.00/2.20/2.10 | 2.10 | 0.20 | 1.0-2.6 | no |
| panel_ml_eval_on_train_vi | 3.00/2.80/3.00 | 3.00 | 0.20 | 1.2-3.4 | no |

## Per-dimension bias (judge − human label)

| dimension | bias | n | stability |
| --- | ---: | ---: | --- |
| communication | -0.17 | 35 | ok |
| correctness | -0.26 | 35 | ok |
| depth | +0.03 | 35 | ok |
| english_delivery | +0.00 | 5 | ⚠ n<8 — unstable estimate |
| mlops_awareness | +0.25 | 8 | ok |
| system_thinking | +0.09 | 35 | ok |

## Weak/strong separation

- mean weak-labelled score: 1.77
- mean strong-labelled score: 4.14
- separation gap: 2.37

## EN vs VN paired deltas

| paired_id | EN | VN | |Δ| |
| --- | ---: | ---: | ---: |
| dl_overfitting_strong | 4.00 | 4.00 | 0.00 |
| dl_overfitting_weak | 3.00 | 3.00 | 0.00 |
| en_dl_batchnorm_broken_english | 4.00 | n/a | n/a |
| en_ml_leakage_broken_english | 4.00 | n/a | n/a |
| en_sd_idempotency_strong_delivery | 4.00 | n/a | n/a |
| ml_bias_variance_strong | 4.00 | 4.00 | 0.00 |
| ml_bias_variance_weak | 2.00 | 2.00 | 0.00 |
| ml_regularization_medium | 4.00 | 4.00 | 0.00 |
| mlops_monitoring_strong | 4.00 | 4.00 | 0.00 |
| mlops_retraining_weak | 2.00 | n/a | n/a |
| mlops_rollout_strong | 5.00 | n/a | n/a |
| mlops_train_serve_skew_medium | 4.00 | n/a | n/a |
| panel_ml_eval_on_train | 3.00 | 3.00 | 0.00 |
| panel_sd_retry_storm | 1.00 | 3.00 | 2.00 |
| prompt_injection | 1.00 | 1.00 | 0.00 |
| sd_backpressure_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_weak | 2.10 | 2.10 | 0.00 |

- mean |Δ|: 0.17; max |Δ|: 2.00

## Mixed-mode cases (issue 0024)

| case | technical score | english_delivery (judge/label) | fixes | in-band |
| --- | ---: | :---: | ---: | :---: |
| mixed_dl_dropout_strong_vnmix | 4.00 | —/— | 0 | ✅ |
| mixed_dl_dropout_weak_vnmix | 2.00 | —/— | 0 | ✅ |
| mixed_sd_cache_strong_en_delivery | 5.00 | 5/5 | 0 | ✅ |
| mixed_ml_leakage_broken_english | 4.00 | 2/2 | 3 | ✅ |
| mixed_mlops_drift_technical | 4.00 | —/— | 0 | ✅ |

## Confidence calibration

| confidence bucket | n | mean conf | hit rate |
| --- | ---: | ---: | ---: |
| [0.7,0.9] | 1 | 0.89 | 100% |
| [0.9,1.0] | 34 | 0.94 | 100% |

## Trust guards (deterministic confidence caps)

| case | self-reported | kept | unverifiable | divergence | noise |
| --- | ---: | ---: | ---: | ---: | --- |
| panel_sd_retry_storm_en | 0.97 | 0.97 | 0% | 0.80 | — |

- shadow escalations by trigger threshold (0.5 is live): <0.5 → 0; <0.6 → 0; <0.7 → 0

## Noise & transport telemetry (this run)

| event | count |
| --- | ---: |
| transport.backoff.openai | 4 |

## Token usage (this run)

| provider | calls | prompt | completion | total |
| --- | ---: | ---: | ---: | ---: |
| openai | 111 | 164093 | 28043 | 192136 |

## BARS anchors used for labelling

- **system_thinking** — 2: Mentions a fix in isolation ("add more data", "use dropout") without connecting it to a diagnosis, trade-off, or downstream effect. | 4: Reasons about the interaction: names a diagnosis, the trade-off it drives, and the consequence of the chosen fix on other parts of the system (e.g. "regularise, but that raises bias, so I cross-validate the strength").
- **correctness** — 2: Contains a real technical error or a vague statement that is only half-right (e.g. "L2 makes weights smaller which is always better"). | 3: Nothing wrong, but the claim is left as a bare assertion: the right technique or term is named and the justification is an unsupported "so it is better" / "it helps", with no mechanism given (e.g. "Dropout turns off some neurons so it is better"). A bare assertion cannot reach 4 however fluently or confidently it is phrased, in any language. | 4: Technically accurate with the key mechanism stated correctly, even if not exhaustive (e.g. "L2 penalises squared weights, trading a little fit for lower variance").
- **depth** — 2: Names the relevant concepts but no mechanism — keyword-level recall ("use regularization, cross-validation") without saying how or why they work. | 4: States the mechanism and one real trade-off or failure mode, even briefly (e.g. "L2 shrinks weights which lowers variance but raises bias"). Edge-case coverage is a 5, not a bar for 4.
- **communication** — 2: Rambling or disorganized: the reader must reconstruct the argument's order themselves. Fluency does not rescue it — organization is what is scored. | 3: Readable sentences but unscoped or meandering, OR a bare claim with nothing after it to organize. An answer too short to HAVE a structure cannot score 4 for sounding natural. | 4: Ordered and well-scoped (claim, mechanism, example) with no filler. Merely fluent sentences without that structure are a 3.
- **english_delivery** — 2: Frequent broken phrasing that obscures the meaning ("model is overfit when data less"); the reader must re-read sentences to extract the idea. Judged on delivery only — the technical content may still be strong. | 4: Clear professional English with minor slips (an article or tense error) that never obscure the technical point.
