"""Entry point demos for the slices built so far.

- ``coach evaluate`` (slices 0001–0002): evaluate a fixture answer, then fold that judgment into the
  Skill's Beta state.
- ``coach interview`` (slice 0005): run the within-question micro-loop over the seed questions — the
  Interviewer asks, the fixture Candidate answers, the Evaluator scores every turn and a Follow-up is
  asked when flagged, until the question resolves; then the Skill state is updated.
- ``coach diagnose`` (slice 0009): turn a Candidate profile into a Topic Plan and seeded priors.
- ``coach ingest-concepts`` (slice 0007): fill a Chroma ``concepts`` collection with seed notes.

``interview`` is the default so the bare command shows the newest slice.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .concepts import SEED_CONCEPTS, ChromaConceptStore, build_concept_store
from .config import load_settings
from .diagnostic import CandidateProfile, diagnose
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


def _cmd_evaluate(client: LLMClient | None, args: argparse.Namespace) -> int:
    if client is None:
        raise RuntimeError("evaluate requires an LLM client")
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
        if turn.grounding_concept_id:
            print(f"  grounded_by: {turn.grounding_concept_id} ({turn.grounding_concept_title})")
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


def _cmd_interview(client: LLMClient | None, args: argparse.Namespace) -> int:
    if client is None:
        raise RuntimeError("interview requires an LLM client")
    concept_store = build_concept_store(
        args.concept_store,
        persist_dir=args.concept_persist_dir,
        seed=not args.no_seed_concepts,
    )
    for n, seed in enumerate(SEED_QUESTIONS, start=1):
        print(f"\n========== SEED QUESTION {n}/{len(SEED_QUESTIONS)} (skill: {seed.skill}) ==========")
        print(seed.question)
        result = run_micro_loop(
            client,
            seed,
            ScriptedCandidate(seed.answers),
            max_turns=args.max_turns,
            concept_store=concept_store,
        )
        _print_micro_loop(result)
    return 0


def _parse_claim(raw: str) -> tuple[str, float]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("claims must be formatted as skill=score, e.g. mlops=4")
    skill, value = raw.split("=", 1)
    try:
        score = float(value)
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"claim score must be numeric: {raw!r}") from err
    return skill.strip(), score


def _cmd_diagnose(client: LLMClient | None, args: argparse.Namespace) -> int:
    profile = CandidateProfile(
        target_role=args.target_role,
        target_companies=tuple(args.company),
        claimed_skills=dict(args.claim),
    )
    result = diagnose(profile, client)
    print(f"=== TOPIC PLAN (source: {result.topic_plan_source.value}) ===")
    for i, entry in enumerate(result.topic_plan, start=1):
        print(f"{i}. {entry.skill}  difficulty={entry.target_difficulty}  {entry.rationale}")
    print("\n=== SEEDED PRIORS ===")
    for skill, prior in result.priors.items():
        state = prior.state
        print(
            f"{skill:<18} mastery={state.mastery:.3f}  "
            f"Beta(α={state.alpha:.2f}, β={state.beta:.2f})  "
            f"criticality={prior.role_criticality.value}  evidence_bar={prior.evidence_bar:.1f}"
        )
    return 0


def _cmd_ingest_concepts(client: LLMClient | None, args: argparse.Namespace) -> int:
    store = ChromaConceptStore.create(persist_dir=args.persist_dir)
    count = store.ingest(SEED_CONCEPTS)
    print(f"Ingested {count} concept notes into Chroma collection at {args.persist_dir!r}.")
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
    ev_parser.set_defaults(func=_cmd_evaluate, requires_llm=True)

    iv_parser = sub.add_parser("interview", help="Slice 0005: run the within-question micro-loop")
    iv_parser.add_argument(
        "--max-turns",
        type=int,
        default=DEFAULT_MAX_TURNS,
        help=f"Safety cap on turns per question (default: {DEFAULT_MAX_TURNS}).",
    )
    iv_parser.add_argument(
        "--concept-store",
        choices=["memory", "chroma"],
        default="memory",
        help="Concept store used by lookup_concept during Follow-up generation.",
    )
    iv_parser.add_argument(
        "--concept-persist-dir",
        default=".chroma",
        help="Chroma persistence directory when --concept-store=chroma.",
    )
    iv_parser.add_argument(
        "--no-seed-concepts",
        action="store_true",
        help="Do not upsert the built-in seed concept notes before the interview.",
    )
    iv_parser.set_defaults(func=_cmd_interview, requires_llm=True)

    diag_parser = sub.add_parser("diagnose", help="Slice 0009: produce Topic Plan + seeded Skill priors")
    diag_parser.add_argument("--target-role", required=True, help="Target role, e.g. 'machine learning engineer'.")
    diag_parser.add_argument(
        "--company",
        action="append",
        default=[],
        help="Target company; may be passed multiple times.",
    )
    diag_parser.add_argument(
        "--claim",
        type=_parse_claim,
        action="append",
        default=[],
        help="Candidate self-assessment as skill=score on a 1–5 scale; may be repeated.",
    )
    diag_parser.add_argument(
        "--offline",
        action="store_true",
        help="Force the deterministic Topic Plan path even when an LLM is configured.",
    )
    # LLM agent is the primary Topic Plan path: used whenever a provider is configured, with the
    # deterministic ordering as the offline fallback (no error when unconfigured).
    diag_parser.set_defaults(func=_cmd_diagnose, requires_llm=False, prefers_llm=True)

    ingest_parser = sub.add_parser("ingest-concepts", help="Slice 0007: seed the Chroma concepts collection")
    ingest_parser.add_argument("--persist-dir", default=".chroma", help="Chroma persistence directory.")
    ingest_parser.set_defaults(func=_cmd_ingest_concepts, requires_llm=False)

    # Default to the newest slice when no subcommand is given.
    parser.set_defaults(
        func=_cmd_interview,
        max_turns=DEFAULT_MAX_TURNS,
        concept_store="memory",
        concept_persist_dir=".chroma",
        no_seed_concepts=False,
        requires_llm=True,
    )
    args = parser.parse_args(argv)

    # Three LLM modes: required (error if unconfigured), preferred (LLM when configured, else an
    # offline deterministic fallback), or none. ``--offline`` downgrades a preferred command to none.
    prefers_llm = getattr(args, "prefers_llm", False) and not getattr(args, "offline", False)
    if not args.requires_llm and not prefers_llm:
        return args.func(None, args)

    settings = load_settings()
    if not settings.configured:
        if args.requires_llm:
            print(
                f"LLM primary provider {settings.primary_provider!r} is not configured. Copy "
                ".env.example to .env, set PRIMARY_PROVIDER, and fill that provider's API key, "
                "base URL, and model.",
                file=sys.stderr,
            )
            return 2
        # LLM-preferred but unconfigured: fall back to the deterministic/offline path, not an error.
        print(
            f"LLM primary provider {settings.primary_provider!r} is not configured; running the "
            "deterministic offline path.",
            file=sys.stderr,
        )
        return args.func(None, args)

    client = build_client(settings)
    return args.func(client, args)
