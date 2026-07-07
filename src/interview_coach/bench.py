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
from .llm import LLMClient
from .rubric import Rubric


@dataclass(frozen=True)
class BenchCase:
    """One hand-labelled Evaluator input for the calibration bench."""

    case_id: str
    paired_id: str
    skill: str
    language: str
    question: str
    answer: str
    rubric: Rubric
    labels: dict[str, int]  # human per-dimension scores (1–5) on the active dimensions
    expected_min: float
    expected_max: float

    @property
    def expected_range(self) -> str:
        return f"{self.expected_min:.1f}-{self.expected_max:.1f}"

    @property
    def is_strong(self) -> bool:
        return self.expected_min >= 3.5

    @property
    def is_weak(self) -> bool:
        return self.expected_max <= 3.0


@dataclass(frozen=True)
class BenchResult:
    case: BenchCase
    evaluation: Evaluation | None = None
    error: str | None = None

    @property
    def score(self) -> float | None:
        return None if self.evaluation is None else self.evaluation.weighted_score

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
        )
        for c in raw_cases
    )
    anchors = data.get("anchors", {}) if isinstance(data, dict) else {}
    return BenchData(cases=cases, anchors=anchors)


def run_bench(client: LLMClient, cases: Iterable[BenchCase]) -> list[BenchResult]:
    """Run the Evaluator over every case, capturing provider/schema failures as errored results."""
    results: list[BenchResult] = []
    for case in cases:
        try:
            evaluation = evaluate(client, case.question, case.answer, case.rubric)
        except Exception as err:  # noqa: BLE001 - the bench reports provider/schema failures as cases
            results.append(BenchResult(case=case, error=f"{type(err).__name__}: {err}"))
        else:
            results.append(BenchResult(case=case, evaluation=evaluation))
    return results


def bench_passed(results: Sequence[BenchResult]) -> bool:
    """The regression gate: every case must land inside its recorded band."""
    return all(result.within_band for result in results)


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
    return {
        dim: {"bias": sum(deltas) / len(deltas), "n": len(deltas)}
        for dim, deltas in totals.items()
        if deltas
    }


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
        delta = abs(en - vi) if (en is not None and vi is not None) else None
        rows.append({"paired_id": paired_id, "en": en, "vi": vi, "delta": delta})
    return rows


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


def render_bench_report(results: Sequence[BenchResult], *, anchors: Mapping[str, Mapping[str, str]] | None = None,
                        provider: str = "unknown", model: str = "unknown", date: str = "unknown") -> str:
    """Render the full Markdown calibration report written into docs/audits/."""
    total = len(results)
    passed = sum(1 for r in results if r.within_band)
    lines = [
        "# Judge Calibration Bench",
        "",
        f"- Date: `{date}`",
        f"- Provider / model: `{provider}` / `{model}`",
        f"- Cases within band: **{passed}/{total}**",
        "",
        "## Per-case scores",
        "",
        "| case | skill | lang | expected | score | conf | in-band |",
        "| --- | --- | --- | --- | ---: | ---: | :---: |",
    ]
    for r in results:
        score = "ERR" if r.score is None else f"{r.score:.2f}"
        conf = "ERR" if r.confidence is None else f"{r.confidence:.2f}"
        mark = "✅" if r.within_band else "❌"
        lines.append(
            f"| {r.case.case_id} | {r.case.skill} | {r.case.language} | {r.case.expected_range} "
            f"| {score} | {conf} | {mark} |"
        )
        if r.error:
            lines.append(f"| | | | | | | `{r.error}` |")

    lines += ["", "## Per-dimension bias (judge − human label)", "",
              "| dimension | bias | n |", "| --- | ---: | ---: |"]
    for dim, stats in sorted(dimension_bias(results).items()):
        lines.append(f"| {dim} | {stats['bias']:+.2f} | {int(stats['n'])} |")

    sep = weak_strong_separation(results)
    lines += ["", "## Weak/strong separation", ""]
    lines.append(f"- mean weak-labelled score: {_fmt(sep['mean_weak'])}")
    lines.append(f"- mean strong-labelled score: {_fmt(sep['mean_strong'])}")
    lines.append(f"- separation gap: {_fmt(sep['gap'])}")

    lines += ["", "## EN vs VN paired deltas", "",
              "| paired_id | EN | VN | |Δ| |", "| --- | ---: | ---: | ---: |"]
    deltas = language_deltas(results)
    for row in deltas:
        lines.append(f"| {row['paired_id']} | {_fmt(row['en'])} | {_fmt(row['vi'])} | {_fmt(row['delta'])} |")
    finite = [row["delta"] for row in deltas if row["delta"] is not None]
    if finite:
        lines.append("")
        lines.append(f"- mean |Δ|: {sum(finite) / len(finite):.2f}; max |Δ|: {max(finite):.2f}")

    lines += ["", "## Confidence calibration", "",
              "| confidence bucket | n | mean conf | hit rate |", "| --- | ---: | ---: | ---: |"]
    for row in confidence_calibration(results):
        lines.append(
            f"| {row['bucket']} | {row['n']} | {row['mean_confidence']:.2f} | {row['hit_rate']:.0%} |"
        )

    if anchors:
        lines += ["", "## BARS anchors used for labelling", ""]
        for dim, bands in anchors.items():
            lines.append(f"- **{dim}** — 2: {bands.get('2', '')} | 4: {bands.get('4', '')}")

    return "\n".join(lines).rstrip() + "\n"


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"
