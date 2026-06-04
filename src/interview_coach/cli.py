"""Entry point demos for the slices built so far.

- ``coach evaluate`` (slices 0001–0002): evaluate a fixture answer, then fold that judgment into the
  Skill's Beta state.
- ``coach interview`` (slice 0005): run the within-question micro-loop over the seed questions — the
  Interviewer asks, the fixture Candidate answers, the Evaluator scores every turn and a Follow-up is
  asked when flagged, until the question resolves; then the Skill state is updated.
- ``coach diagnose`` (slice 0009): turn a Candidate profile into a Topic Plan and seeded priors.
- ``coach session`` (slice 0010): run/resume a multi-question Session through LangGraph + SqliteSaver.
- ``coach eval-harness`` (slice 0012): run held-out golden answers through the Evaluator.
- ``coach api`` (slice 0012): run the FastAPI/WebSocket backend for the React UI.
- ``coach ingest-concepts`` (slice 0007): fill a Chroma ``concepts`` collection with seed notes.
- ``coach ingest-resources`` (slice 0011): fill a Chroma ``resources`` collection with study materials.

``interview`` is the default so the bare command shows the newest slice.
"""

from __future__ import annotations

import argparse
import logging
import sys

from langgraph.checkpoint.sqlite import SqliteSaver

from .concepts import SEED_CONCEPTS, ChromaConceptStore, build_concept_store
from .config import load_settings
from .diagnostic import CandidateProfile, diagnose
from .eval_harness import harness_passed, render_golden_answer_report, run_golden_answer_harness
from .evaluator import Evaluation, evaluate
from .exporter import export_session_markdown
from .fixtures import QUESTION, STRONG_ANSWER, WEAK_ANSWER
from .llm import LLMClient, build_client
from .microloop import (
    DEFAULT_MAX_TURNS,
    CandidateInputUnavailable,
    InteractiveCandidate,
    MicroLoopResult,
    ScriptedCandidate,
    StopReason,
    run_micro_loop,
)
from .resources import SEED_RESOURCES, ChromaResourceStore, build_resource_store
from .seeds import SEED_QUESTIONS
from .skill import SkillState, apply_evaluation
from .supervisor import (
    DEFAULT_MAX_ELAPSED_SECONDS,
    DEFAULT_MAX_QUESTIONS,
    build_session_graph,
    export_architecture_diagram,
    initial_session_state,
    session_config,
)
from .ui import render_skill_state_rows

ANSWERS = {"strong": STRONG_ANSWER, "weak": WEAK_ANSWER}


def _display_stop_reason(stop_reason: str | None) -> str:
    if stop_reason == StopReason.SAFETY_CAP.value:
        return "unresolved_by_safety_cap"
    if stop_reason == StopReason.FOLLOW_UP_UNAVAILABLE.value:
        return "degraded_follow_up_unavailable"
    return str(stop_reason)


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
        if turn.trace.evaluator_self_critique_triggers:
            print(f"  self_critique_triggers: {', '.join(turn.trace.evaluator_self_critique_triggers)}")
        if turn.trace.concept_lookup_query:
            hit = turn.trace.concept_hit_id or "none"
            print(f"  follow_up_lookup: {turn.trace.concept_lookup_query!r} -> {hit}")
        if turn.trace.stop_reason:
            print(f"  turn_stop_reason: {turn.trace.stop_reason.value}")
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


def _print_session_summary(state: dict) -> None:
    print(f"=== SESSION {state['session_id']} ({state['status']}) ===")
    print(f"questions: {state['question_count']}   stop_reason: {state.get('stop_reason')}")
    print("\n=== SKILL STATES ===")
    for row in render_skill_state_rows(state):
        print(row)
    for i, item in enumerate(state.get("transcript", []), start=1):
        print(
            f"\n--- QUESTION {i} ({item['skill']}) ---\n"
            f"score={item['resolved_weighted_score']:.2f}/5   "
            f"confidence={item['resolved_confidence']:.2f}   stop={_display_stop_reason(item['stop_reason'])}"
        )
        for turn_n, turn in enumerate(item["turns"], start=1):
            kind = "FOLLOW-UP" if turn["is_follow_up"] else "QUESTION"
            print(f"  {turn_n}. {kind}: {turn['question']}")
            trace = turn["trace"]
            if trace.get("concept_lookup_query"):
                print(f"     lookup: {trace['concept_lookup_query']!r} -> {trace.get('concept_hit_id') or 'none'}")
            if trace.get("stop_reason"):
                print(f"     turn_stop_reason: {_display_stop_reason(trace['stop_reason'])}")
    if state.get("supervisor_decisions"):
        print("\n=== SUPERVISOR DECISIONS ===")
        for decision in state["supervisor_decisions"]:
            print(
                f"- after Q{decision['after_question']}: {decision['action']} "
                f"(deviation={decision['deviation']}) — {decision['llm_reasoning']}"
            )
    if plan := state.get("study_plan"):
        print("\n=== STUDY PLAN ===")
        print(f"readiness_estimate={plan['readiness_estimate']:.0%} — {plan['readiness_rationale']}")
        for topic in plan.get("prioritized_topics", []):
            resources = ", ".join(resource["id"] for resource in topic.get("resources", []))
            print(
                f"{topic['priority']}. {topic['skill']} "
                f"(mastery={topic['mastery']:.0%}, criticality={topic['role_criticality']}): {resources}"
            )
    elif error := state.get("study_plan_error"):
        # The interview still completed; only the optional end-of-session plan was unavailable.
        print(f"\n=== STUDY PLAN ===\n(planner unavailable: {error})")


def _print_live_question_update(state: dict, item: dict, question_number: int) -> None:
    print(f"\n=== LIVE UPDATE: QUESTION {question_number} RESOLVED ({item['skill']}) ===")
    print(
        f"score={item['resolved_weighted_score']:.2f}/5   "
        f"confidence={item['resolved_confidence']:.2f}   stop={_display_stop_reason(item['stop_reason'])}"
    )
    print("--- SKILL STATES ---")
    for row in render_skill_state_rows(state):
        print(row)


def _run_session_graph(graph, state: dict | None, config: dict, *, live: bool) -> dict:
    if not live:
        return graph.invoke(state, config)

    final: dict | None = None
    seen_questions = 0
    for event in graph.stream(state, config, stream_mode="values"):
        final = dict(event)
        transcript = final.get("transcript", [])
        if len(transcript) <= seen_questions:
            continue
        for question_index in range(seen_questions, len(transcript)):
            _print_live_question_update(final, transcript[question_index], question_index + 1)
        seen_questions = len(transcript)
    if final is None:
        raise RuntimeError("Session graph produced no final state")
    return final


def _cmd_session(client: LLMClient | None, args: argparse.Namespace) -> int:
    if client is None:
        raise RuntimeError("session requires an LLM client")
    if args.diagram:
        path = export_architecture_diagram(args.diagram, client)
        print(f"Exported architecture diagram to {path}")
        return 0

    concept_store = build_concept_store(
        args.concept_store,
        persist_dir=args.concept_persist_dir,
        seed=not args.no_seed_concepts,
    )
    resource_store = build_resource_store(
        args.resource_store,
        persist_dir=args.resource_persist_dir,
        seed=not args.no_seed_resources,
    )
    with SqliteSaver.from_conn_string(args.checkpoint_db) as checkpointer:
        candidate_factory = None if args.scripted else lambda seed: InteractiveCandidate()
        graph = build_session_graph(
            client,
            checkpointer=checkpointer,
            concept_store=concept_store,
            resource_store=resource_store,
            candidate_factory=candidate_factory,
            max_turns_per_question=None if args.scripted else args.max_turns,
        )
        config = session_config(args.session_id)
        try:
            if args.resume:
                final = _run_session_graph(graph, None, config, live=not args.no_live)
            else:
                profile = CandidateProfile(
                    target_role=args.target_role,
                    target_companies=tuple(args.company),
                    claimed_skills=dict(args.claim),
                )
                diagnostic = diagnose(profile, client)
                state = initial_session_state(
                    args.session_id,
                    diagnostic,
                    max_questions=args.max_questions,
                    max_elapsed_seconds=args.max_elapsed_seconds,
                )
                final = _run_session_graph(graph, state, config, live=not args.no_live)
        except CandidateInputUnavailable as err:
            print(str(err), file=sys.stderr)
            return 2
    _print_session_summary(final)
    if args.export_markdown:
        path = export_session_markdown(final, args.export_markdown)
        print(f"\nExported Session Markdown to {path}")
    return 0


def _cmd_eval_harness(client: LLMClient | None, args: argparse.Namespace) -> int:
    if client is None:
        raise RuntimeError("eval-harness requires an LLM client")
    results = run_golden_answer_harness(client)
    print(render_golden_answer_report(results))
    return 0 if harness_passed(results) else 1


def _cmd_ingest_concepts(client: LLMClient | None, args: argparse.Namespace) -> int:
    store = ChromaConceptStore.create(persist_dir=args.persist_dir)
    count = store.ingest(SEED_CONCEPTS)
    print(f"Ingested {count} concept notes into Chroma collection at {args.persist_dir!r}.")
    return 0


def _cmd_ingest_resources(client: LLMClient | None, args: argparse.Namespace) -> int:
    store = ChromaResourceStore.create(persist_dir=args.persist_dir)
    count = store.ingest(SEED_RESOURCES)
    print(f"Ingested {count} learning resources into Chroma collection at {args.persist_dir!r}.")
    return 0

def _cmd_api(client: LLMClient | None, args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "interview_coach.web_api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Adaptive Interview Coach — slice demos.")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show provider and internal INFO logs. By default the CLI hides noisy demo logs.",
    )
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

    session_parser = sub.add_parser("session", help="Slice 0010: run/resume a LangGraph Session")
    session_parser.add_argument("--session-id", default="local-session", help="Stable id used as LangGraph thread_id.")
    session_parser.add_argument(
        "--checkpoint-db",
        default=".session-checkpoints.sqlite",
        help="SQLite checkpoint database used by SqliteSaver.",
    )
    session_parser.add_argument("--target-role", default="machine learning engineer")
    session_parser.add_argument(
        "--company",
        action="append",
        default=[],
        help="Target company; may be passed multiple times.",
    )
    session_parser.add_argument(
        "--claim",
        type=_parse_claim,
        action="append",
        default=[],
        help="Candidate self-assessment as skill=score on a 1–5 scale; may be repeated.",
    )
    session_parser.add_argument("--max-questions", type=int, default=DEFAULT_MAX_QUESTIONS)
    session_parser.add_argument(
        "--max-turns",
        type=int,
        default=DEFAULT_MAX_TURNS,
        help=f"Safety cap on turns per question for interactive Sessions (default: {DEFAULT_MAX_TURNS}).",
    )
    session_parser.add_argument("--max-elapsed-seconds", type=float, default=DEFAULT_MAX_ELAPSED_SECONDS)
    session_parser.add_argument(
        "--concept-store",
        choices=["memory", "chroma"],
        default="memory",
        help="Concept store used by lookup_concept during Follow-up generation.",
    )
    session_parser.add_argument(
        "--concept-persist-dir",
        default=".chroma",
        help="Chroma persistence directory when --concept-store=chroma.",
    )
    session_parser.add_argument(
        "--no-seed-concepts",
        action="store_true",
        help="Do not upsert the built-in seed concept notes before the Session.",
    )
    session_parser.add_argument(
        "--resource-store",
        choices=["memory", "chroma"],
        default="memory",
        help="Resource store used by the Study Planner.",
    )
    session_parser.add_argument(
        "--resource-persist-dir",
        default=".chroma",
        help="Chroma persistence directory when --resource-store=chroma.",
    )
    session_parser.add_argument(
        "--no-seed-resources",
        action="store_true",
        help="Do not upsert the built-in learning resources before planning.",
    )
    session_parser.add_argument(
        "--export-markdown",
        help="Write the completed Session transcript, evaluations, and Study Plan to this Markdown path.",
    )
    session_parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an existing checkpoint by --session-id instead of starting from Diagnostic.",
    )
    session_parser.add_argument(
        "--no-live",
        action="store_true",
        help="Suppress live Skill-state updates and print only the final Session summary.",
    )
    session_parser.add_argument(
        "--scripted",
        action="store_true",
        help="Use built-in scripted Candidate answers instead of prompting in the terminal.",
    )
    session_parser.add_argument(
        "--diagram",
        help="Export the LangGraph architecture PNG to this path and exit.",
    )
    session_parser.set_defaults(func=_cmd_session, requires_llm=True)

    harness_parser = sub.add_parser("eval-harness", help="Slice 0012: run Evaluator golden-answer checks")
    harness_parser.set_defaults(func=_cmd_eval_harness, requires_llm=True)

    ingest_parser = sub.add_parser("ingest-concepts", help="Slice 0007: seed the Chroma concepts collection")
    ingest_parser.add_argument("--persist-dir", default=".chroma", help="Chroma persistence directory.")
    ingest_parser.set_defaults(func=_cmd_ingest_concepts, requires_llm=False)

    resources_parser = sub.add_parser("ingest-resources", help="Slice 0011: seed the Chroma resources collection")
    resources_parser.add_argument("--persist-dir", default=".chroma", help="Chroma persistence directory.")
    resources_parser.set_defaults(func=_cmd_ingest_resources, requires_llm=False)

    api_parser = sub.add_parser("api", help="Slice 0012: run the FastAPI WebSocket backend")
    api_parser.add_argument("--host", default="127.0.0.1")
    api_parser.add_argument("--port", type=int, default=8000)
    api_parser.add_argument("--reload", action="store_true")
    api_parser.set_defaults(func=_cmd_api, requires_llm=False)

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
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.INFO if args.verbose else logging.WARNING)

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
