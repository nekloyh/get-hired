"""Slice 0001 entry point: evaluate a fixture answer and print the typed judgment."""

from __future__ import annotations

import argparse
import sys

from .config import load_settings
from .evaluator import Evaluation, evaluate
from .fixtures import QUESTION, STRONG_ANSWER, WEAK_ANSWER
from .llm import build_client

ANSWERS = {"strong": STRONG_ANSWER, "weak": WEAK_ANSWER}


def _print_evaluation(label: str, answer: str, ev: Evaluation) -> None:
    print(f"\n=== {label.upper()} ANSWER ===")
    print(answer)
    print("\n--- EVALUATION ---")
    for dim, ds in ev.dimensions.items():
        print(f"  {dim:<18} {ds.score}/5   evidence: {ds.evidence!r}")
    print(f"  {'weighted_score':<18} {ev.weighted_score:.2f}/5")
    print(f"  {'confidence':<18} {ev.confidence:.2f}")
    print(f"  {'follow_up':<18} {ev.follow_up_recommended} — {ev.follow_up_rationale}")
    print("\n  JSON:")
    print(ev.model_dump_json(indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Slice 0001 — evaluate one answer.")
    parser.add_argument(
        "--answer",
        choices=[*ANSWERS, "both"],
        default="both",
        help="Which fixture answer to evaluate (default: both).",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    if not settings.configured:
        print(
            "LLM is not configured. Copy .env.example to .env and set "
            "LLM_API_KEY, LLM_BASE_URL, and LLM_MODEL.",
            file=sys.stderr,
        )
        return 2

    client = build_client(settings)
    print(f"QUESTION (skill: {QUESTION.skill}):\n{QUESTION.question}")

    labels = list(ANSWERS) if args.answer == "both" else [args.answer]
    for label in labels:
        ev = evaluate(client, QUESTION.question, ANSWERS[label], QUESTION.rubric)
        _print_evaluation(label, ANSWERS[label], ev)
    return 0
