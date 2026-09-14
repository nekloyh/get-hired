# Judge Calibration Bench

- Date: `2026-07-27`
- Provider / model: `openai` / `gpt-5.4-mini`
- Gate: **median-of-k, k=3** (ADR 0009 addendum d)
- Cases within band: **35/35**

> **Verdict: GREEN on this invocation (35/35, zero straddles) — but NOT yet merge-ready.**
> The ADR 0009 repeatability standard is *the same exit code across invocations*, and the daily
> token budget ran out after one invocation of the final wording. This session is itself the reason
> that matters: an earlier wording of this same change returned 35/35, 35/35, **34/35**. One green
> run is not a measurement. Confirming invocations are owed after the budget resets (GH #96).

## What changed, and the three wordings it took

`depth` and `system_thinking` gained the `3` band they were missing, in both `rubric.py`
(what the judge is told — the only file that moves scores) and `data/bench/cases.yaml` (what the
human labeler is told). Getting there took three measured attempts, and the two failures are more
instructive than the success.

### Attempt 1 — filled the hole, broke two cases (33/35)

Adding "3 = states a mechanism but stops there" closed the target split (`panel_sd_retry_storm`
|Δ| 2.00 → 1.00) but pushed `dl_overfitting_weak_vi` (3.40) and `vnlp_segmentation_weak_vi` (2.70)
out of band. Per-dimension measurement (k=3 per twin) located it precisely:

| pair | dimension | EN | VN | Δ | label |
| --- | --- | ---: | ---: | ---: | ---: |
| dl_overfitting_weak | depth | 2.00 | **3.00** | **+1.00** | 2 |
| dl_overfitting_weak | correctness · communication · system_thinking | 3.00 · 3.00 · 2.00 | 3.00 · 3.00 · 2.00 | 0.00 | 3 · 3 · 2 |
| vnlp_segmentation_weak | depth | 1.00 | **2.00** | **+1.00** | 1 |
| vnlp_segmentation_weak | correctness · communication · system_thinking | 3.00 · 3.00 · 2.00 | 3.00 · 3.00 · 2.00 | 0.00 | 2 · 3 · 1 |

Every other dimension agreed *exactly* across languages; `depth` alone carried the entire split, and
in both cases **the EN twin matched the human label while the VN twin sat one point high**. That is
the ADR 0009(d) diagnosis test passing cleanly: the judge is wrong on VN, the band is not stale, so
the remedy is the guide — not the band. No band was touched at any point in this work.

### Attempt 2 — fixed the target, dragged the strong cases down (35/35, 35/35, **34/35**)

The `HOW not WHAT` causal-step test worked at the 2/3 boundary but was read as a general bar:
`depth` bias went **+0.03 → −0.11**, and strong cases that had been dead-stable at 4.00/4.00/4.00
started producing 3.5–3.7 draws. `vnlp_segmentation_strong_en` eventually fell out at median 3.70
against a 3.8 floor. Three invocations disagreed with each other — which is exactly the failure the
median-of-k gate exists to expose, and it would have been invisible to a single run.

### Attempt 3 — scope each test to the boundary it decides (this report)

Both new tests now name the boundary they apply to and state that they do **not** raise the bar
above it, plus a `1 vs 2` test for the remaining case: *a 2 must introduce at least one idea the
question did not already supply*. `vnlp_segmentation_weak`'s VN twin echoes the question's own
vocabulary ("why is word segmentation important?" → "you need to split the words"), which the judge
had been reading as naming a concept — but only in Vietnamese, where it sounds more assertive.

## Result against the 2026-07-27 baseline

| metric | baseline (#92) | this run | |
| --- | ---: | ---: | --- |
| cases within band | 35/35 | 35/35 | held |
| straddling cases | 0 | 0 | held |
| **max \|Δ\| (EN/VN)** | **2.00** | **1.00** | **halved — the point of the change** |
| mean \|Δ\| | 0.17 | 0.20 | +0.03, noise-level |
| weak/strong separation | 2.37 | 2.37 | identical |
| depth bias | +0.03 | −0.03 | held |
| system_thinking bias | +0.09 | −0.03 | held |
| communication bias | −0.17 | −0.06 | improved |
| correctness bias | −0.26 | **−0.46** | **worse — see below** |

`panel_sd_retry_storm`, the case this issue was filed for, went from |Δ| 2.00 to **1.00** (EN 2.00,
VN 3.00, both stable 3/3 and both in band), meeting the issue's ≤1.00 target.

**`correctness` bias is the one metric that got worse** (−0.26 → −0.46) and it is now close to the
±0.5 tripwire. It was not touched by this change, so the most likely reading is that a sharper
`depth` scale pulls `correctness` down on the same weak answers by making the judge stricter
overall. It did not fire a tripwire and no case fell out, but it is the thing to watch on the
confirming runs — if it crosses 0.5 it needs its own diagnosis, not a band adjustment.

## The human label for `panel_sd_retry_storm`: recommended amendment, deliberately not applied

The issue asks for a decision. Measured per-dimension (k=3, attempt-2 wording): EN
`correctness 1.00 · depth 2.00 · communication 4.00 · system_thinking 2.00`; VN the same but +1.00
on correctness, depth and system_thinking.

The labels are `correctness 2 · depth 4 · communication 5 · system_thinking 2`. **`depth: 4` does
not survive contact with its own anchor.** A 4 requires "the mechanism AND one real trade-off or
failure mode". The answer — tighten the retry loop, remove the rate limiter, scale the callers —
names no cost of any kind, which is precisely what makes the advice dangerous. Under the anchors it
is a 3 (a mechanism asserted with no price named), which would move the pair's label from 3.00 to
2.80, still inside its untouched 1.0–3.2 band.

`communication: 5` stands: that dimension scores organization only, and the answer genuinely is
well-ordered. Rewarding the polish of harmful advice is the correct behaviour there — the danger is
`correctness`'s job, and `correctness: 2` already reflects it.

**Not applied in this run**, because changing a label while the gate evidence for the same change is
still incomplete makes the next measurement harder to read. It should land with the confirming
invocations.

## Per-case scores

The score column is the MEDIAN over k runs; `runs` shows every draw, so a case whose distribution sits on a band edge is visible here rather than discovered when it flips.

| case | skill | lang | expected | score | runs | conf | escalation | in-band |
| --- | --- | --- | --- | ---: | --- | ---: | --- | :---: |
| ml_bias_variance_weak_en | ml_fundamentals | en | 1.0-2.6 | 2.00 | 2.00/2.00/2.00 | 0.97 | — | ✅ |
| ml_bias_variance_weak_vi | ml_fundamentals | vi | 1.0-2.6 | 2.00 | 2.00/2.00/2.00 | 0.96 | — | ✅ |
| ml_bias_variance_strong_en | ml_fundamentals | en | 3.8-5.0 | 4.20 | 4.20/4.20/4.00 | 0.95 | — | ✅ |
| ml_bias_variance_strong_vi | ml_fundamentals | vi | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.92 | — | ✅ |
| ml_regularization_medium_en | ml_fundamentals | en | 2.8-4.2 | 4.00 | 3.60/4.00/4.00 | 0.95 | — | ✅ |
| ml_regularization_medium_vi | ml_fundamentals | vi | 2.8-4.2 | 4.00 | 4.00/4.00/4.00 | 0.92 | — | ✅ |
| dl_overfitting_weak_en | deep_learning | en | 1.6-3.2 | 2.20 | 2.20/2.20/2.20 | 0.95 | — | ✅ |
| dl_overfitting_weak_vi | deep_learning | vi | 1.6-3.2 | 2.00 | 2.00/2.20/2.00 | 0.93 | — | ✅ |
| dl_overfitting_strong_en | deep_learning | en | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.96 | — | ✅ |
| dl_overfitting_strong_vi | deep_learning | vi | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| vnlp_segmentation_weak_en | vietnamese_nlp | en | 1.0-2.6 | 2.00 | 2.00/2.00/2.00 | 0.96 | — | ✅ |
| vnlp_segmentation_weak_vi | vietnamese_nlp | vi | 1.0-2.6 | 2.00 | 2.00/2.00/2.00 | 0.96 | — | ✅ |
| vnlp_segmentation_strong_en | vietnamese_nlp | en | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| vnlp_segmentation_strong_vi | vietnamese_nlp | vi | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| sd_backpressure_strong_en | system_design | en | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| sd_backpressure_strong_vi | system_design | vi | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.90 | — | ✅ |
| mlops_monitoring_strong_en | mlops | en | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| mlops_monitoring_strong_vi | mlops | vi | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.93 | — | ✅ |
| prompt_injection_en | ml_fundamentals | en | 1.0-2.5 | 1.00 | 1.00/1.00/1.00 | 0.99 | — | ✅ |
| prompt_injection_vi | ml_fundamentals | vi | 1.0-2.5 | 1.00 | 1.00/1.00/1.00 | 0.99 | — | ✅ |
| mixed_dl_dropout_strong_vnmix | deep_learning | mixed | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.92 | — | ✅ |
| mixed_dl_dropout_weak_vnmix | deep_learning | mixed | 1.0-2.6 | 2.00 | 2.00/2.00/2.00 | 0.97 | — | ✅ |
| mixed_sd_cache_strong_en_delivery | system_design | mixed | 3.8-5.0 | 4.00 | 4.00/4.00/4.00 | 0.96 | — | ✅ |
| mixed_ml_leakage_broken_english | ml_fundamentals | mixed | 3.4-5.0 | 4.00 | 4.00/4.00/4.00 | 0.92 | — | ✅ |
| panel_sd_retry_storm_en | system_design | en | 1.0-3.2 | 2.00 | 2.00/2.00/2.00 | 0.97 | — | ✅ |
| panel_sd_retry_storm_vi | system_design | vi | 1.0-3.2 | 3.00 | 3.00/3.00/3.00 | 0.92 | — | ✅ |
| panel_ml_eval_on_train_en | ml_fundamentals | en | 1.2-3.4 | 2.00 | 2.00/3.00/2.00 | 0.95 | — | ✅ |
| panel_ml_eval_on_train_vi | ml_fundamentals | vi | 1.2-3.4 | 3.00 | 3.00/3.00/3.00 | 0.90 | — | ✅ |
| en_ml_leakage_broken_english | ml_fundamentals | en | 3.4-5.0 | 4.00 | 4.00/4.00/4.00 | 0.90 | — | ✅ |
| mlops_retraining_weak_en | mlops | en | 1.0-2.8 | 2.00 | 2.00/2.00/2.00 | 0.96 | — | ✅ |
| mlops_rollout_strong_en | mlops | en | 3.8-5.0 | 4.50 | 5.00/4.00/4.50 | 0.93 | — | ✅ |
| mlops_train_serve_skew_medium_en | mlops | en | 2.8-4.2 | 4.00 | 4.00/4.00/4.00 | 0.92 | — | ✅ |
| en_dl_batchnorm_broken_english | deep_learning | en | 3.4-5.0 | 4.00 | 4.00/4.00/4.00 | 0.95 | — | ✅ |
| mixed_mlops_drift_technical | mlops | mixed | 3.4-5.0 | 4.00 | 4.00/4.00/4.00 | 0.90 | — | ✅ |
| en_sd_idempotency_strong_delivery | system_design | en | 3.8-5.0 | 5.00 | 5.00/4.00/5.00 | 0.96 | — | ✅ |

## Repeatability (k=3)

Cases whose score moved between runs. A ⚠ straddle means some runs landed in-band and others did not — the band edge cuts through the judge's distribution, so the case is one provider nudge from flipping the gate even while its median reads green.

| case | runs | median | spread | band | straddles edge |
| --- | --- | ---: | ---: | --- | :---: |
| panel_ml_eval_on_train_en | 2.00/3.00/2.00 | 2.00 | 1.00 | 1.2-3.4 | no |
| mlops_rollout_strong_en | 5.00/4.00/4.50 | 4.50 | 1.00 | 3.8-5.0 | no |
| en_sd_idempotency_strong_delivery | 5.00/4.00/5.00 | 5.00 | 1.00 | 3.8-5.0 | no |
| ml_regularization_medium_en | 3.60/4.00/4.00 | 4.00 | 0.40 | 2.8-4.2 | no |
| ml_bias_variance_strong_en | 4.20/4.20/4.00 | 4.20 | 0.20 | 3.8-5.0 | no |
| dl_overfitting_weak_vi | 2.00/2.20/2.00 | 2.00 | 0.20 | 1.6-3.2 | no |

## Per-dimension bias (judge − human label)

| dimension | bias | n | stability |
| --- | ---: | ---: | --- |
| communication | -0.06 | 35 | ok |
| correctness | -0.46 | 35 | ok |
| depth | -0.03 | 35 | ok |
| english_delivery | +0.20 | 5 | ⚠ n<8 — unstable estimate |
| mlops_awareness | +0.50 | 8 | ok |
| system_thinking | -0.03 | 35 | ok |

## Weak/strong separation

- mean weak-labelled score: 1.75
- mean strong-labelled score: 4.12
- separation gap: 2.37

## EN vs VN paired deltas

| paired_id | EN | VN | |Δ| |
| --- | ---: | ---: | ---: |
| dl_overfitting_strong | 4.00 | 4.00 | 0.00 |
| dl_overfitting_weak | 2.20 | 2.00 | 0.20 |
| en_dl_batchnorm_broken_english | 4.00 | n/a | n/a |
| en_ml_leakage_broken_english | 4.00 | n/a | n/a |
| en_sd_idempotency_strong_delivery | 5.00 | n/a | n/a |
| ml_bias_variance_strong | 4.20 | 4.00 | 0.20 |
| ml_bias_variance_weak | 2.00 | 2.00 | 0.00 |
| ml_regularization_medium | 4.00 | 4.00 | 0.00 |
| mlops_monitoring_strong | 4.00 | 4.00 | 0.00 |
| mlops_retraining_weak | 2.00 | n/a | n/a |
| mlops_rollout_strong | 4.50 | n/a | n/a |
| mlops_train_serve_skew_medium | 4.00 | n/a | n/a |
| panel_ml_eval_on_train | 2.00 | 3.00 | 1.00 |
| panel_sd_retry_storm | 2.00 | 3.00 | 1.00 |
| prompt_injection | 1.00 | 1.00 | 0.00 |
| sd_backpressure_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_strong | 4.00 | 4.00 | 0.00 |
| vnlp_segmentation_weak | 2.00 | 2.00 | 0.00 |

- mean |Δ|: 0.20; max |Δ|: 1.00

## Mixed-mode cases (issue 0024)

| case | technical score | english_delivery (judge/label) | fixes | in-band |
| --- | ---: | :---: | ---: | :---: |
| mixed_dl_dropout_strong_vnmix | 4.00 | —/— | 0 | ✅ |
| mixed_dl_dropout_weak_vnmix | 2.00 | —/— | 0 | ✅ |
| mixed_sd_cache_strong_en_delivery | 4.00 | 5/5 | 0 | ✅ |
| mixed_ml_leakage_broken_english | 4.00 | 2/2 | 3 | ✅ |
| mixed_mlops_drift_technical | 4.00 | —/— | 0 | ✅ |

## Confidence calibration

| confidence bucket | n | mean conf | hit rate |
| --- | ---: | ---: | ---: |
| [0.9,1.0] | 35 | 0.94 | 100% |

## Trust guards (deterministic confidence caps)

- no case tripped a deterministic trust signal this run

- shadow escalations by trigger threshold (0.5 is live): <0.5 → 0; <0.6 → 0; <0.7 → 0

## Noise & transport telemetry (this run)

| event | count |
| --- | ---: |
| llm.calls | 105 |
| llm.calls.openai | 105 |

## Token usage (this run)

| provider | calls | prompt | completion | total |
| --- | ---: | ---: | ---: | ---: |
| openai | 105 | 185871 | 26268 | 212139 |

## BARS anchors used for labelling

- **system_thinking** — 2: Mentions a fix in isolation ("add more data", "use dropout") without connecting it to a diagnosis, trade-off, or downstream effect. | 3: The fix is tied to ONE link of the chain — either why it is needed or what it affects — but the interaction is asserted rather than traced (e.g. "remove the rate limiter so the queue drains faster", with nothing about what that does to the failing service). Monitoring or alerting added alongside a fix is not reasoning about that fix's effect on the system and does not by itself lift a 2 to a 3. An asserted chain is a 3 however fluently or confidently it is phrased, in any language. | 4: Reasons about the interaction: names a diagnosis, the trade-off it drives, and the consequence of the chosen fix on other parts of the system (e.g. "regularise, but that raises bias, so I cross-validate the strength").
- **correctness** — 2: Contains a real technical error or a vague statement that is only half-right (e.g. "L2 makes weights smaller which is always better"). | 3: Nothing wrong, but the claim is left as a bare assertion: the right technique or term is named and the justification is an unsupported "so it is better" / "it helps", with no mechanism given (e.g. "Dropout turns off some neurons so it is better"). A bare assertion cannot reach 4 however fluently or confidently it is phrased, in any language. | 4: Technically accurate with the key mechanism stated correctly, even if not exhaustive (e.g. "L2 penalises squared weights, trading a little fit for lower variance").
- **depth** — 2: Names the relevant concepts but no mechanism — keyword-level recall ("use regularization, cross-validation") without saying how or why they work. The 1/2 boundary: a 2 must introduce at least one idea the question did not already supply. Answering "why is word segmentation important?" with "you need to split the words so the model understands" echoes the question's own vocabulary and names nothing — a 1, and a 1 in Vietnamese too, where the judge's draws on that exact answer spanned 2.00–3.00 while its English twin sat at 2.00 on every draw (GH #96). | 3: States a mechanism but stops there: nothing about what it costs, when it fails, or what it trades away (e.g. "dropout randomly zeroes activations during training so the network cannot rely on any one unit" — how it works, with no price named). A mechanism with no cost attached is a 3 however fluently or confidently it is phrased, in any language. The 2/3 boundary is HOW, not WHAT: an answer must say how the technique produces the effect in question. "Dropout turns off some neurons so it is better" names the operation and asserts the benefit with no causal step between them — that is a 2, and it is a 2 in Vietnamese too, where the same sentence reads more authoritatively (GH #92/#96, the measured failure mode). This test decides 2 vs 3 and nothing above it: an answer that names a mechanism AND a trade-off is a 4 even when compressed. Stating it unscoped measurably dragged strong answers from 4 to 3 (depth bias +0.03 → −0.11, three strong cases straddling the 3.8 floor). | 4: States the mechanism and one real trade-off or failure mode, even briefly (e.g. "L2 shrinks weights which lowers variance but raises bias"). Edge-case coverage is a 5, not a bar for 4.
- **communication** — 2: Rambling or disorganized: the reader must reconstruct the argument's order themselves. Fluency does not rescue it — organization is what is scored. | 3: Readable sentences but unscoped or meandering, OR a bare claim with nothing after it to organize. An answer too short to HAVE a structure cannot score 4 for sounding natural. | 4: Ordered and well-scoped (claim, mechanism, example) with no filler. Merely fluent sentences without that structure are a 3.
- **english_delivery** — 2: Frequent broken phrasing that obscures the meaning ("model is overfit when data less"); the reader must re-read sentences to extract the idea. Judged on delivery only — the technical content may still be strong. | 4: Clear professional English with minor slips (an article or tense error) that never obscure the technical point.
