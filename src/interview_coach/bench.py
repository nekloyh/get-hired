"""Bilingual Judge calibration bench (issue 0022, ADR 0009).

Grows the golden-answer harness into a calibration bench: hand-labelled EN/VN paired cases, run live
against the configured provider, producing a Markdown report with per-dimension bias vs human labels,
weak/strong separation, EN-vs-VN paired deltas, and a confidence-calibration table. It exits non-zero
on a range regression (same convention as the eval-harness), so it can gate every judge change —
prompt, threshold, or provider.

The cases live in ``data/bench/cases.yaml`` (hand-editable, diff-friendly). The metric functions are
pure over the results, so the report plumbing is testable offline with a fake client; only the actual
run needs a live provider.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from .evaluator import Evaluation, evaluate
from .language import validate_language_mode
from .llm import LLMClient
from .rubric import Rubric


@dataclass(frozen=True)
class BenchCase:
    """One hand-labelled Evaluator input for the calibration bench."""

    case_id: str
    paired_id: str
    skill: str
    language: str  # the language the ANSWER is written in: "en" | "vi" | "mixed"
    question: str
    answer: str
    rubric: Rubric
    labels: dict[str, int]  # human per-dimension scores (1–5) on the active dimensions
    expected_min: float
    expected_max: float
    # The Session language_mode the judge is told (issue 0024): "en" | "vn" | "mixed". Distinct
    # vocabulary from ``language`` above — a case can carry a Vietnamese answer inside an
    # en-mode prompt (all legacy pairs do, keeping their prompts byte-identical to pre-0024 runs).
    language_mode: str = "en"

    @property
    def expected_range(self) -> str:
        return f"{self.expected_min:.1f}-{self.expected_max:.1f}"

    @property
    def is_strong(self) -> bool:
        return self.expected_min >= 3.5

    @property
    def is_weak(self) -> bool:
        return self.expected_max <= 3.0


# The gate runs each case this many times and judges the MEDIAN (ADR 0009 addendum d). One draw of
# a stochastic judge is not a measurement: on 2026-07-19 three identical runs returned 28/29, 28/29,
# 29/29 because `dl_overfitting_weak_vi` scored 3.30/3.30/3.20 against a band top of 3.2 — the band
# edge sat inside the judge's score distribution and the gate was a 1-in-3 coin flip (GH #92). Odd by
# construction so the median is always an actually-observed run, never a synthetic average.
BENCH_DEFAULT_K = 3


@dataclass(frozen=True)
class BenchResult:
    """One case's aggregate verdict over k runs.

    ``evaluation`` is the *representative* run — the one whose weighted score is the median — not a
    synthesized average, so every downstream metric (bias, confidence calibration, trust guards,
    delivery) reads one real, internally coherent judgment rather than a blend of several.
    """

    case: BenchCase
    evaluation: Evaluation | None = None
    error: str | None = None
    # Every successful run's weighted score, in run order. The gate reads the median of these; the
    # report shows the spread, which is what makes band-edge proximity visible BEFORE it flips a
    # verdict rather than after.
    scores: tuple[float, ...] = ()
    errored_runs: int = 0

    @property
    def score(self) -> float | None:
        return None if self.evaluation is None else self.evaluation.weighted_score

    @property
    def spread(self) -> float | None:
        """max − min across the k runs: this case's run-to-run instability, in score points."""
        return max(self.scores) - min(self.scores) if len(self.scores) > 1 else None

    @property
    def straddles_band_edge(self) -> bool:
        """Whether some runs landed in-band and others did not — the single-run coin-flip signature.

        This is the early warning the 2026-07-19 audit had to discover by accident: a case can carry
        a green median while its distribution still crosses the edge. It warns, it does not gate —
        the median is the verdict — but an unreported straddle is a gate that will flip without
        notice the next time the provider drifts.
        """
        if len(self.scores) < 2:
            return False
        inside = [self.case.expected_min <= s <= self.case.expected_max for s in self.scores]
        return any(inside) and not all(inside)

    @property
    def confidence(self) -> float | None:
        return None if self.evaluation is None else self.evaluation.confidence

    @property
    def within_band(self) -> bool:
        return (
            self.score is not None
            and self.error is None
            and self.case.expected_min <= self.score <= self.case.expected_max
        )

    # A judge may reasonably sit one point off a delivery label (BARS bands are coarse), but a
    # 2-point miss means it is not measuring delivery at all — and delivery never gates via
    # within_band (it is excluded from weighted_score by design), so without this check the
    # bench would wave through a judge that scores english_delivery by coin flip.
    DELIVERY_TOLERANCE = 1

    @property
    def delivery_within_band(self) -> bool:
        """Whether the judged english_delivery score sits within tolerance of the human label.

        Vacuously true for cases without an english_delivery label; false when the case is
        labelled but the judgment errored or skipped the dimension.
        """
        label = self.case.labels.get("english_delivery")
        if label is None:
            return True
        if self.evaluation is None or self.error is not None:
            return False
        judged = self.evaluation.dimensions.get("english_delivery")
        return judged is not None and abs(judged.score - label) <= self.DELIVERY_TOLERANCE


@dataclass(frozen=True)
class BenchData:
    cases: tuple[BenchCase, ...]
    anchors: dict[str, dict[str, str]] = field(default_factory=dict)


def _default_cases_path() -> Path:
    # data/bench/cases.yaml lives at the repo root (a content pack), not inside the package.
    return resources.files("interview_coach").joinpath("..", "..", "data", "bench", "cases.yaml").resolve()


def load_bench_data(path: str | Path | None = None) -> BenchData:
    """Load the calibration cases + BARS anchors from YAML."""
    target = Path(path) if path is not None else _default_cases_path()
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    raw_cases = data.get("cases", []) if isinstance(data, dict) else []
    cases = tuple(
        BenchCase(
            case_id=c["case_id"],
            paired_id=c["paired_id"],
            skill=c["skill"],
            language=c["language"],
            question=c["question"],
            answer=c["answer"],
            rubric=Rubric(weights={k: float(v) for k, v in c["rubric"].items()}),
            labels={k: int(v) for k, v in c.get("labels", {}).items()},
            expected_min=float(c["expected_min"]),
            expected_max=float(c["expected_max"]),
            # Fail loudly at load time on the designed-in "vi" (answer language) vs "vn" (session
            # mode) vocabulary clash — a typo'd mode would silently run an en-mode judge prompt.
            language_mode=validate_language_mode(c.get("language_mode", "en")),
        )
        for c in raw_cases
    )
    anchors = data.get("anchors", {}) if isinstance(data, dict) else {}
    return BenchData(cases=cases, anchors=anchors)


def _evaluate_case(client: LLMClient, case: BenchCase) -> tuple[Evaluation | None, str | None]:
    """One judgment attempt: the evaluation, or the provider/schema failure that replaced it."""
    try:
        evaluation = evaluate(client, case.question, case.answer, case.rubric, language_mode=case.language_mode)
    except Exception as err:  # noqa: BLE001 - the bench reports provider/schema failures as cases
        return None, f"{type(err).__name__}: {err}"
    return evaluation, None


def _aggregate(case: BenchCase, attempts: Sequence[tuple[Evaluation | None, str | None]]) -> BenchResult:
    """Collapse k attempts at one case into the median-run verdict.

    A run that errored is dropped rather than fatal: the transport layer already fights blips with
    retries, and with k draws instead of one a single blip would otherwise be k times more likely to
    red the gate on infrastructure rather than on judge quality (ADR 0005's "infrastructure noise
    must never corrupt skill evidence", applied to the measurement itself). If EVERY run errored the
    case is still an error result, exactly as it was pre-#92.
    """
    successes = [ev for ev, _ in attempts if ev is not None]
    failures = [err for ev, err in attempts if ev is None and err is not None]
    if not successes:
        return BenchResult(case=case, error=failures[0] if failures else "no runs", errored_runs=len(attempts))
    # Sorting by score and taking the middle index keeps the representative an OBSERVED run at any
    # k; for the odd default it is the exact median.
    representative = sorted(successes, key=lambda ev: ev.weighted_score)[len(successes) // 2]
    return BenchResult(
        case=case,
        evaluation=representative,
        scores=tuple(ev.weighted_score for ev in successes),
        errored_runs=len(failures),
    )


def run_bench(client: LLMClient, cases: Iterable[BenchCase], *, k: int = 1) -> list[BenchResult]:
    """Run the Evaluator over every case ``k`` times, returning one median verdict per case.

    Runs are **pass-major** — k complete sweeps of the case list, not k back-to-back calls on each
    case — which is both what the 2026-07-19 k=3 audit measured and the ordering that avoids
    sampling the provider's behaviour at a single instant.

    ``k=1`` is the byte-identical pre-#92 behaviour and is what the offline tests use; the gate runs
    at :data:`BENCH_DEFAULT_K` (see ``coach bench --k``).
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    cases = tuple(cases)
    passes = [[_evaluate_case(client, case) for case in cases] for _ in range(k)]
    return [_aggregate(case, [p[i] for p in passes]) for i, case in enumerate(cases)]


def bench_passed(results: Sequence[BenchResult]) -> bool:
    """The regression gate: at least one case ran, and every case lands inside its recorded band.

    The non-empty guard matters because ``all([])`` is ``True``: without it a malformed or empty
    ``cases.yaml`` (which yields zero results) would pass the gate vacuously and exit 0 green,
    silently waving through the very judge change the bench is meant to block. Delivery-labelled
    cases (issue 0024) additionally gate on english_delivery accuracy — the technical band cannot
    see that dimension by design, so it needs its own check.
    """
    return bool(results) and all(result.within_band and result.delivery_within_band for result in results)


# --- pure metrics over the results (offline-testable) -------------------------------------------


def dimension_bias(results: Sequence[BenchResult]) -> dict[str, dict[str, float]]:
    """Mean (judge - human) per dimension, plus the sample size — a signed calibration bias."""
    totals: dict[str, list[float]] = {}
    for result in results:
        if result.evaluation is None:
            continue
        for dim, label in result.case.labels.items():
            judged = result.evaluation.dimensions.get(dim)
            if judged is None:
                continue
            totals.setdefault(dim, []).append(judged.score - label)
    return {dim: {"bias": sum(deltas) / len(deltas), "n": len(deltas)} for dim, deltas in totals.items() if deltas}


# Below this many labelled cases a per-dimension bias estimate is noise, not signal: on a 1–5
# scale with n=3–4 a single case swings the mean by ±0.25–0.33 (mlops_awareness went +0.00 → +0.50
# between two same-day green runs on n=4). The report still shows the number but marks it unstable,
# and the tripwire ignores it.
BIAS_MIN_SAMPLES = 8

# |bias| beyond this on a sufficiently-sampled dimension means the judge and the human labels
# disagree systematically — the signal that triggered the July-11 re-anchor worklist. A warning,
# not a gate: bands still gate correctness; this catches drift while everything is still green.
BIAS_TRIPWIRE = 0.5


def bias_warnings(results: Sequence[BenchResult]) -> list[str]:
    """Tripwire lines for dimensions whose bias is both statistically grounded and drifting."""
    warnings = []
    for dim, stats in sorted(dimension_bias(results).items()):
        if stats["n"] >= BIAS_MIN_SAMPLES and abs(stats["bias"]) > BIAS_TRIPWIRE:
            warnings.append(
                f"{dim}: bias {stats['bias']:+.2f} over n={int(stats['n'])} exceeds ±{BIAS_TRIPWIRE:.1f} "
                "— re-anchor the judge guide for this dimension (see the 2026-07-11 re-anchor audit "
                "for the worklist pattern)"
            )
    return warnings


def repeatability_rows(results: Sequence[BenchResult]) -> list[dict[str, Any]]:
    """Per case that was run more than once: its run spread and whether it crosses a band edge.

    Sorted worst-first so the case closest to flipping the gate reads at the top. Only cases with an
    actual spread appear — a case that returned the same score k times is stable and says nothing.
    """
    rows = [
        {
            "case_id": r.case.case_id,
            "scores": r.scores,
            "median": r.score,
            # 0.0 rather than None when a case has a single surviving run: it is listed for its
            # errors, and "no spread observed" is honestly 0 across the draws that did land.
            "spread": r.spread or 0.0,
            "band": r.case.expected_range,
            "straddles": r.straddles_band_edge,
            "errored_runs": r.errored_runs,
        }
        for r in results
        # Errored runs qualify a case on their own. Gating this on spread would have hidden the very
        # case the errors matter most for — k-1 failures leave ONE surviving score, hence no spread.
        if r.scores and (r.errored_runs or (r.spread or 0.0) > 0)
    ]
    return sorted(rows, key=lambda row: (not row["straddles"], -row["spread"]))


def repeatability_warnings(results: Sequence[BenchResult]) -> list[str]:
    """Warning lines for cases whose distribution crosses a band edge, or that errored on some runs.

    Not a gate — the median is the verdict (ADR 0009 addendum d). This is the tripwire that would
    have caught GH #92 on 2026-07-11 instead of eight days later: a straddling case is one provider
    nudge away from flipping the gate, and it is invisible in any single-run report.
    """
    warnings = []
    for row in repeatability_rows(results):
        runs = "/".join(f"{s:.2f}" for s in row["scores"])
        if row["straddles"]:
            warnings.append(
                f"{row['case_id']}: runs {runs} straddle band {row['band']} (median {row['median']:.2f}) "
                "— the band edge cuts through the judge's score distribution; re-derive the band from "
                "this distribution or re-anchor the dimension driving it, but never widen to go green"
            )
        if row["errored_runs"]:
            warnings.append(
                f"{row['case_id']}: {row['errored_runs']} of {row['errored_runs'] + len(row['scores'])} "
                "runs errored — the median stands on fewer draws than the gate asked for"
            )
    return warnings


def weak_strong_separation(results: Sequence[BenchResult]) -> dict[str, float | None]:
    """Mean weighted_score of weak-labelled vs strong-labelled cases, and the gap between them."""
    weak = [r.score for r in results if r.case.is_weak and r.score is not None]
    strong = [r.score for r in results if r.case.is_strong and r.score is not None]
    mean_weak = sum(weak) / len(weak) if weak else None
    mean_strong = sum(strong) / len(strong) if strong else None
    gap = mean_strong - mean_weak if (mean_weak is not None and mean_strong is not None) else None
    return {"mean_weak": mean_weak, "mean_strong": mean_strong, "gap": gap}


def language_deltas(results: Sequence[BenchResult]) -> list[dict[str, Any]]:
    """Per paired_id: the EN and VN weighted_scores and the absolute delta (judge language fairness)."""
    by_pair: dict[str, dict[str, float]] = {}
    for result in results:
        if result.score is None:
            continue
        by_pair.setdefault(result.case.paired_id, {})[result.case.language] = result.score
    rows = []
    for paired_id, langs in sorted(by_pair.items()):
        en, vi = langs.get("en"), langs.get("vi")
        if en is None and vi is None:
            # A mixed-language pair (issue 0024) has no EN/VN twin to diff — it is reported in its
            # own mixed-mode section, not as an all-n/a delta row.
            continue
        delta = abs(en - vi) if (en is not None and vi is not None) else None
        rows.append({"paired_id": paired_id, "en": en, "vi": vi, "delta": delta})
    return rows


def mixed_mode_rows(results: Sequence[BenchResult]) -> list[dict[str, Any]]:
    """Per mixed-language case (issue 0024): technical score plus the english_delivery judgment.

    english_delivery is reported apart from the banded technical score — the whole point of the
    dimension (ADR 0007) is that the two never mix.
    """
    rows = []
    for result in results:
        if result.case.language != "mixed":
            continue
        delivery = None
        fixes = 0
        if result.evaluation is not None:
            scored = result.evaluation.dimensions.get("english_delivery")
            delivery = scored.score if scored is not None else None
            fixes = len(result.evaluation.delivery_fixes)
        rows.append(
            {
                "case_id": result.case.case_id,
                "score": result.score,
                "english_delivery": delivery,
                "delivery_label": result.case.labels.get("english_delivery"),
                "delivery_fixes": fixes,
                "within_band": result.within_band,
            }
        )
    return rows


def trust_guard_rows(results: Sequence[BenchResult]) -> list[dict[str, Any]]:
    """Per case where a deterministic trust signal moved (or would move) the judgment.

    The rows surface what the saturated self-report cannot: blanked citations, holistic-vs-linear
    divergence, and parse noise, next to the confidence actually kept after the graded caps.
    """
    rows = []
    for result in results:
        trust = result.evaluation.trust if result.evaluation is not None else None
        if trust is None:
            continue
        signal = (
            trust.unverifiable_fraction > 0
            or trust.noise_events
            or trust.divergence > 0.5
            or result.confidence != trust.pre_guard_confidence
        )
        if not signal:
            continue
        rows.append(
            {
                "case_id": result.case.case_id,
                "pre_guard": trust.pre_guard_confidence,
                "final": result.confidence,
                "unverifiable_fraction": trust.unverifiable_fraction,
                "divergence": trust.divergence,
                "noise_events": ", ".join(trust.noise_events) or "—",
            }
        )
    return rows


# The escalation thresholds the shadow analysis prices out. 0.5 is the live trigger; the higher
# rungs answer "what would raising it buy / cost?" without paying for a single real escalation.
SHADOW_TRIGGER_THRESHOLDS = (0.5, 0.6, 0.7)


def shadow_trigger_counts(results: Sequence[BenchResult]) -> dict[float, int]:
    """How many judgments would escalate at each candidate threshold, using guarded confidence."""
    confidences = [r.confidence for r in results if r.confidence is not None]
    return {threshold: sum(1 for c in confidences if c < threshold) for threshold in SHADOW_TRIGGER_THRESHOLDS}


def confidence_calibration(results: Sequence[BenchResult]) -> list[dict[str, Any]]:
    """Bucket cases by stated confidence; compare each bucket's mean confidence to its hit rate.

    "When the Evaluator says 0.9, is it right ~90% of the time?" — hit = the score landed in the band.
    """
    buckets = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)]
    rows = []
    for lo, hi in buckets:
        in_bucket = [r for r in results if r.confidence is not None and lo <= r.confidence < hi]
        if not in_bucket:
            continue
        hits = sum(1 for r in in_bucket if r.within_band)
        rows.append(
            {
                "bucket": f"[{lo:.1f},{hi if hi <= 1.0 else 1.0:.1f}]",
                "n": len(in_bucket),
                "mean_confidence": sum(r.confidence for r in in_bucket) / len(in_bucket),
                "hit_rate": hits / len(in_bucket),
            }
        )
    return rows


def render_bench_report(
    results: Sequence[BenchResult],
    *,
    anchors: Mapping[str, Mapping[str, str]] | None = None,
    provider: str = "unknown",
    model: str = "unknown",
    date: str = "unknown",
    telemetry_delta: Mapping[str, int] | None = None,
    token_usage: Mapping[str, Mapping[str, int]] | None = None,
) -> str:
    """Render the full Markdown calibration report written into docs/audits/."""
    total = len(results)
    passed = sum(1 for r in results if r.within_band)
    k = max((len(r.scores) + r.errored_runs for r in results), default=1)
    lines = [
        "# Judge Calibration Bench",
        "",
        f"- Date: `{date}`",
        f"- Provider / model: `{provider}` / `{model}`",
        f"- Gate: **median-of-k, k={k}** (ADR 0009 addendum d)" if k > 1 else "- Gate: single run (k=1)",
        f"- Cases within band: **{passed}/{total}**",
        "",
        "## Per-case scores",
        "",
        "The score column is the MEDIAN over k runs; `runs` shows every draw, so a case whose"
        " distribution sits on a band edge is visible here rather than discovered when it flips.",
        "",
        "| case | skill | lang | expected | score | runs | conf | escalation | in-band |",
        "| --- | --- | --- | --- | ---: | --- | ---: | --- | :---: |",
    ]
    for r in results:
        score = "ERR" if r.score is None else f"{r.score:.2f}"
        conf = "ERR" if r.confidence is None else f"{r.confidence:.2f}"
        mark = "✅" if r.within_band else "❌"
        runs = "/".join(f"{s:.2f}" for s in r.scores) if r.scores else "—"
        if r.straddles_band_edge:
            runs += " ⚠"
        if r.errored_runs:
            runs += f" (+{r.errored_runs} ERR)"
        escalation = "—"
        if r.evaluation is not None and r.evaluation.panel is not None:
            escalation = "panel: " + ", ".join(r.evaluation.panel.triggers)
        elif r.evaluation is not None and r.evaluation.self_critique is not None:
            escalation = ", ".join(r.evaluation.self_critique.triggers)
        lines.append(
            f"| {r.case.case_id} | {r.case.skill} | {r.case.language} | {r.case.expected_range} "
            f"| {score} | {runs} | {conf} | {escalation} | {mark} |"
        )
        if r.error:
            lines.append(f"| | | | | | | | | `{r.error}` |")

    if repeat_rows := repeatability_rows(results):
        lines += [
            "",
            f"## Repeatability (k={k})",
            "",
            "Cases whose score moved between runs. A ⚠ straddle means some runs landed in-band and"
            " others did not — the band edge cuts through the judge's distribution, so the case is one"
            " provider nudge from flipping the gate even while its median reads green.",
            "",
            "| case | runs | median | spread | band | straddles edge |",
            "| --- | --- | ---: | ---: | --- | :---: |",
        ]
        for row in repeat_rows:
            runs = "/".join(f"{s:.2f}" for s in row["scores"])
            median = "ERR" if row["median"] is None else f"{row['median']:.2f}"
            lines.append(
                f"| {row['case_id']} | {runs} | {median} | {row['spread']:.2f} | {row['band']} "
                f"| {'⚠ YES' if row['straddles'] else 'no'} |"
            )
        if repeat_warnings := repeatability_warnings(results):
            lines.append("")
            for warning in repeat_warnings:
                lines.append(f"- **REPEATABILITY** — {warning}")

    lines += [
        "",
        "## Per-dimension bias (judge − human label)",
        "",
        "| dimension | bias | n | stability |",
        "| --- | ---: | ---: | --- |",
    ]
    for dim, stats in sorted(dimension_bias(results).items()):
        stability = "ok" if stats["n"] >= BIAS_MIN_SAMPLES else f"⚠ n<{BIAS_MIN_SAMPLES} — unstable estimate"
        lines.append(f"| {dim} | {stats['bias']:+.2f} | {int(stats['n'])} | {stability} |")
    if tripwires := bias_warnings(results):
        lines.append("")
        for warning in tripwires:
            lines.append(f"- **BIAS TRIPWIRE** — {warning}")

    sep = weak_strong_separation(results)
    lines += ["", "## Weak/strong separation", ""]
    lines.append(f"- mean weak-labelled score: {_fmt(sep['mean_weak'])}")
    lines.append(f"- mean strong-labelled score: {_fmt(sep['mean_strong'])}")
    lines.append(f"- separation gap: {_fmt(sep['gap'])}")

    lines += ["", "## EN vs VN paired deltas", "", "| paired_id | EN | VN | |Δ| |", "| --- | ---: | ---: | ---: |"]
    deltas = language_deltas(results)
    for row in deltas:
        lines.append(f"| {row['paired_id']} | {_fmt(row['en'])} | {_fmt(row['vi'])} | {_fmt(row['delta'])} |")
    finite = [row["delta"] for row in deltas if row["delta"] is not None]
    if finite:
        lines.append("")
        lines.append(f"- mean |Δ|: {sum(finite) / len(finite):.2f}; max |Δ|: {max(finite):.2f}")

    mixed = mixed_mode_rows(results)
    if mixed:
        lines += [
            "",
            "## Mixed-mode cases (issue 0024)",
            "",
            "| case | technical score | english_delivery (judge/label) | fixes | in-band |",
            "| --- | ---: | :---: | ---: | :---: |",
        ]
        for row in mixed:
            judged = "—" if row["english_delivery"] is None else str(row["english_delivery"])
            label = "—" if row["delivery_label"] is None else str(row["delivery_label"])
            mark = "✅" if row["within_band"] else "❌"
            lines.append(
                f"| {row['case_id']} | {_fmt(row['score'])} | {judged}/{label} | {row['delivery_fixes']} | {mark} |"
            )

    lines += [
        "",
        "## Confidence calibration",
        "",
        "| confidence bucket | n | mean conf | hit rate |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in confidence_calibration(results):
        lines.append(f"| {row['bucket']} | {row['n']} | {row['mean_confidence']:.2f} | {row['hit_rate']:.0%} |")

    guard_rows = trust_guard_rows(results)
    lines += ["", "## Trust guards (deterministic confidence caps)", ""]
    if guard_rows:
        lines += [
            "| case | self-reported | kept | unverifiable | divergence | noise |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ]
        for row in guard_rows:
            lines.append(
                f"| {row['case_id']} | {row['pre_guard']:.2f} | {row['final']:.2f} "
                f"| {row['unverifiable_fraction']:.0%} | {row['divergence']:.2f} | {row['noise_events']} |"
            )
    else:
        lines.append("- no case tripped a deterministic trust signal this run")
    shadow = shadow_trigger_counts(results)
    if shadow:
        lines.append("")
        lines.append(
            "- shadow escalations by trigger threshold (0.5 is live): "
            + "; ".join(f"<{threshold:.1f} → {count}" for threshold, count in sorted(shadow.items()))
        )

    if telemetry_delta is not None:
        # Structural-noise telemetry (free-tier hardening): which sanitizer folds / retries /
        # backoffs THIS run triggered. A new noise mode from the live model shows up here as a
        # moving counter while the run is still green — before it ever costs an in-band case.
        lines += ["", "## Noise & transport telemetry (this run)", ""]
        if telemetry_delta:
            lines += ["| event | count |", "| --- | ---: |"]
            for key, count in sorted(telemetry_delta.items()):
                lines.append(f"| {key} | {count} |")
        else:
            lines.append("- clean run: no sanitizer folds, retries, or transport backoffs")

    if token_usage is not None:
        lines += [
            "",
            "## Token usage (this run)",
            "",
            "| provider | calls | prompt | completion | total |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for prov, stats in sorted(token_usage.items()):
            lines.append(
                f"| {prov} | {stats.get('calls', 0)} | {stats.get('prompt', 0)} "
                f"| {stats.get('completion', 0)} | {stats.get('total', 0)} |"
            )
        if not token_usage:
            lines.append("| (none recorded) | 0 | 0 | 0 | 0 |")

    if anchors:
        lines += ["", "## BARS anchors used for labelling", ""]
        for dim, bands in anchors.items():
            # Render every band the file defines rather than a hardcoded 2/4. A middle anchor added
            # to close a language split (GH #92) would otherwise be invisible in every report that
            # followed it — and the anchors section exists precisely to record the scale the labels
            # were set against.
            rendered = " | ".join(f"{band}: {bands[band]}" for band in sorted(bands))
            lines.append(f"- **{dim}** — {rendered}")

    return "\n".join(lines).rstrip() + "\n"


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"
