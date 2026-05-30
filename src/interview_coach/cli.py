"""Entry point demos for the slices built so far.

- ``coach evaluate`` (slices 0001–0002): evaluate a fixture answer, then fold that judgment into the
  Skill's Beta state.
- ``coach interview`` (slice 0005): run the within-question micro-loop over the seed questions — the
  Interviewer asks, the fixture Candidate answers, the Evaluator scores every turn and a Follow-up is
  asked when flagged, until the question resolves; then the Skill state is updated.

``interview`` is the default so the bare command shows the newest slice.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_settings
from .evaluator import Evaluation, evaluate
from .fixtures import QUESTION, STRONG_ANSWER, WEAK_ANSWER
from .llm import LLMClient, build_client
from .microloop import DEFAULT_MAX_TURNS, MicroLoopResult, ScriptedCandidate, StopReason, run_micro_loop
from .seeds import SEED_QUESTIONS
from .skill import SkillState, apply_evaluation

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


def _print_skill_update(before: SkillState, after: SkillState) -> None:
    print(f"\n--- SKILL STATE ({before.skill}) — no LLM, pure Beta update ---")
    print(
        f"  before   mastery {before.mastery:.3f}   confidence {before.confidence:.3f}   "
        f"Beta(α={before.alpha:.2f}, β={before.beta:.2f})"
    )
    print(
        f"  after    mastery {after.mastery:.3f}   confidence {after.confidence:.3f}   "
        f"Beta(α={after.alpha:.2f}, β={after.beta:.2f})"
    )
    print(
        f"  Δ        mastery {after.mastery - before.mastery:+.3f}   "
        f"confidence {after.confidence - before.confidence:+.3f}"
    )


def _cmd_evaluate(client: LLMClient, args: argparse.Namespace) -> int:
    print(f"QUESTION (skill: {QUESTION.skill}):\n{QUESTION.question}")
    labels = list(ANSWERS) if args.answer == "both" else [args.answer]
    for label in labels:
        ev = evaluate(client, QUESTION.question, ANSWERS[label], QUESTION.rubric)
        _print_evaluation(label, ANSWERS[label], ev)
        # Each answer starts from a neutral prior, so strong vs. weak visibly move mastery in
        # opposite directions while both shrink variance (confidence rises).
        before = SkillState.neutral(QUESTION.skill)
        _print_skill_update(before, apply_evaluation(before, ev))
    return 0


def _print_micro_loop(result: MicroLoopResult) -> None:
    for i, turn in enumerate(result.turns, start=1):
        kind = "FOLLOW-UP" if turn.is_follow_up else "QUESTION"
        ev = turn.evaluation
        print(f"\n--- TURN {i} ({kind}) ---")
        print(f"  Q: {turn.question}")
        print(f"  A: {turn.answer}")
        scores = "  ".join(f"{d}={ds.score}" for d, ds in ev.dimensions.items())
        print(f"  scored: {scores}")
        print(
            f"  weighted_score {ev.weighted_score:.2f}/5   confidence {ev.confidence:.2f}   "
            f"follow_up_recommended={ev.follow_up_recommended}"
        )
    verdict = "resolved normally" if result.stop_reason is StopReason.RESOLVED else "halted by SAFETY CAP"
    print(f"\n  stop: {result.stop_reason.value} ({verdict}) after {len(result.turns)} turn(s)")
    print(
        f"  resolved skill state ({result.skill_state.skill}): "
        f"mastery {result.skill_state.mastery:.3f}   confidence {result.skill_state.confidence:.3f}"
    )


def _cmd_interview(client: LLMClient, args: argparse.Namespace) -> int:
    for n, seed in enumerate(SEED_QUESTIONS, start=1):
        print(f"\n========== SEED QUESTION {n}/{len(SEED_QUESTIONS)} (skill: {seed.skill}) ==========")
        print(seed.question)
        result = run_micro_loop(
            client,
            seed,
            ScriptedCandidate(seed.answers),
            max_turns=args.max_turns,
        )
        _print_micro_loop(result)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Adaptive Interview Coach — slice demos.")
    sub = parser.add_subparsers(dest="command")

    ev_parser = sub.add_parser("evaluate", help="Slices 0001–0002: evaluate fixture answers + skill update")
    ev_parser.add_argument(
        "--answer",
        choices=[*ANSWERS, "both"],
        default="both",
        help="Which fixture answer to evaluate (default: both).",
    )
    ev_parser.set_defaults(func=_cmd_evaluate)

    iv_parser = sub.add_parser("interview", help="Slice 0005: run the within-question micro-loop")
    iv_parser.add_argument(
        "--max-turns",
        type=int,
        default=DEFAULT_MAX_TURNS,
        help=f"Safety cap on turns per question (default: {DEFAULT_MAX_TURNS}).",
    )
    iv_parser.set_defaults(func=_cmd_interview)

    # Default to the newest slice when no subcommand is given.
    parser.set_defaults(func=_cmd_interview, max_turns=DEFAULT_MAX_TURNS)
    args = parser.parse_args(argv)

    settings = load_settings()
    if not settings.configured:
        print(
            f"LLM primary provider {settings.primary_provider!r} is not configured. Copy "
            ".env.example to .env, set PRIMARY_PROVIDER, and fill that provider's API key, "
            "base URL, and model.",
            file=sys.stderr,
        )
        return 2

    client = build_client(settings)
    return args.func(client, args)
