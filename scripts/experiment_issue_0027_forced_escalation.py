"""Forced-escalation experiment for issue 0027's Panel Verdict — hits the real configured provider.

The calibration bench answers "did the judge stay calibrated?", but it cannot answer the panel's
design question — "when the committee actually convenes, does the verdict beat the first pass?" —
because on gpt-5.4-mini the escalation triggers essentially never fire naturally (first-pass
confidence is uniformly >= 0.9). This experiment forces the committee to convene on every selected
case by raising the confidence trigger above 1.0, so the full Skeptic → Advocate → verdict path
runs through the production ``evaluate()`` code, and compares the first pass against the verdict
on the bench's own expected bands.

Run: ``uv run python scripts/experiment_issue_0027_forced_escalation.py`` (prints a Markdown
report to stdout — redirect it next to the audit). Skips cleanly (exit 0) when no provider is
configured; exits 1 only on infrastructure failure, not on score movement: the experiment is a
measurement, not a gate.
"""

from __future__ import annotations

import sys

from interview_coach import evaluator
from interview_coach.bench import load_bench_data
from interview_coach.config import load_settings
from interview_coach.llm import build_client

# A deliberate mix: the borderline pairs authored for 0027, the adversarial injection case, a
# genuinely-medium pair, the eloquence traps, and two clean anchors the verdict must not wreck.
CASE_IDS = (
    "panel_sd_retry_storm_en",
    "panel_sd_retry_storm_vi",
    "panel_ml_eval_on_train_en",
    "panel_ml_eval_on_train_vi",
    "prompt_injection_en",
    "ml_regularization_medium_en",
    "ml_regularization_medium_vi",
    "mixed_ml_leakage_broken_english",
    "ml_bias_variance_strong_en",
    "dl_overfitting_weak_en",
)

NATURAL_THRESHOLD = evaluator.SELF_CRITIQUE_CONFIDENCE_THRESHOLD


def main() -> int:
    settings = load_settings()
    if not settings.configured:
        print("skipped: no provider configured (set PRIMARY_PROVIDER and credentials)")
        return 0
    client = build_client(settings)

    data = load_bench_data()
    by_id = {case.case_id: case for case in data.cases}
    missing = [cid for cid in CASE_IDS if cid not in by_id]
    if missing:
        print(f"unknown case ids: {missing}", file=sys.stderr)
        return 1

    # Force the committee to convene: every first pass now reads as "low confidence". The panel
    # path is otherwise the production one — prompts, guards, and verdict-keeps-unconditionally.
    evaluator.SELF_CRITIQUE_CONFIDENCE_THRESHOLD = 1.01

    rows: list[dict] = []
    for cid in CASE_IDS:
        case = by_id[cid]
        try:
            ev = evaluator.evaluate(
                client, case.question, case.answer, case.rubric, language_mode=case.language_mode
            )
        except Exception as err:  # noqa: BLE001 - report, keep measuring the rest
            print(f"| {cid} | ERROR: {type(err).__name__}: {err} |")
            rows.append({"case": cid, "error": str(err)})
            continue
        if ev.panel is None:
            print(f"{cid}: escalation did not fire despite the forced threshold", file=sys.stderr)
            return 1
        p = ev.panel
        rows.append(
            {
                "case": cid,
                "lo": case.expected_min,
                "hi": case.expected_max,
                "first": p.initial_score,
                "verdict": ev.weighted_score,
                "delta": ev.weighted_score - p.initial_score,
                "skeptic": p.skeptic.recommended_score,
                "advocate": p.advocate.recommended_score,
                "disagreement": p.disagreement,
                "first_in": case.expected_min <= p.initial_score <= case.expected_max,
                "verdict_in": case.expected_min <= ev.weighted_score <= case.expected_max,
                "natural": p.initial_confidence < NATURAL_THRESHOLD,
                "first_conf": p.initial_confidence,
            }
        )

    ok = [r for r in rows if "error" not in r]
    print("# Forced-escalation experiment (issue 0027)")
    print()
    print(f"Provider: {settings.primary_provider}; cases: {len(ok)}/{len(CASE_IDS)} evaluated.")
    print()
    print(
        "| case | band | first | verdict | Δ | skeptic | advocate | disagree | first in band "
        "| verdict in band | natural? | first conf |"
    )
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | :-: | :-: | :-: | ---: |")
    for r in ok:
        print(
            f"| {r['case']} | {r['lo']:.1f}-{r['hi']:.1f} | {r['first']:.2f} | {r['verdict']:.2f} "
            f"| {r['delta']:+.2f} | {r['skeptic']:g} | {r['advocate']:g} | {r['disagreement']:.1f} "
            f"| {'Y' if r['first_in'] else 'N'} | {'Y' if r['verdict_in'] else 'N'} "
            f"| {'Y' if r['natural'] else 'N'} | {r['first_conf']:.2f} |"
        )
    print()
    moved = [r for r in ok if abs(r["delta"]) >= 0.3]
    print(f"- First pass in band: {sum(r['first_in'] for r in ok)}/{len(ok)}")
    print(f"- Verdict in band:    {sum(r['verdict_in'] for r in ok)}/{len(ok)}")
    print(f"- Verdict moved >= 0.3 points on {len(moved)}/{len(ok)} cases")
    print(f"- Mean |delta|: {sum(abs(r['delta']) for r in ok) / len(ok):.2f}")
    print(f"- Mean committee disagreement: {sum(r['disagreement'] for r in ok) / len(ok):.2f}")
    print(f"- Natural escalations (first conf < {NATURAL_THRESHOLD}): {sum(r['natural'] for r in ok)}/{len(ok)}")
    return 0 if len(ok) == len(CASE_IDS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
