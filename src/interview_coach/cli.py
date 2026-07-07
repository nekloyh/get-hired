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
import time
from datetime import UTC, datetime
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from .bank import BankError, load_pack
from .bench import bench_passed, load_bench_data, render_bench_report, run_bench
from .concepts import SEED_CONCEPTS, ChromaConceptStore, InMemoryConceptStore, build_concept_store
from .config import load_settings
from .diagnostic import CandidateProfile, diagnose_or_degrade
from .eval_harness import harness_passed, render_golden_answer_report, run_golden_answer_harness
from .evaluator import Evaluation, evaluate
from .exporter import export_session_markdown
from .fixtures import QUESTION, STRONG_ANSWER, WEAK_ANSWER
from .ledger import load_priors, save_posteriors
from .llm import LLMClient, build_client
from .microloop import (
    DEFAULT_MAX_TURNS,
    CandidateIntent,
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
    SessionStatus,
    build_session_graph,
    export_architecture_diagram,
    initial_session_state,
    resumable_session_state,
    session_config,
    skill_states_from_state,
)
from .ui import render_skill_state_rows

ANSWERS = {"strong": STRONG_ANSWER, "weak": WEAK_ANSWER}


def _display_stop_reason(stop_reason: str | None) -> str:
    if stop_reason == StopReason.SAFETY_CAP.value:
        return "unresolved_by_safety_cap"
    if stop_reason == StopReason.FOLLOW_UP_UNAVAILABLE.value:
        return "degraded_follow_up_unavailable"
    if stop_reason == StopReason.FAILED.value:
        return "failed_recorded_and_skipped"
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
    verdict_by_reason = {
        StopReason.RESOLVED: "resolved normally",
        StopReason.SAFETY_CAP: "halted by SAFETY CAP",
        StopReason.FOLLOW_UP_UNAVAILABLE: "degraded because a Follow-up was unavailable",
        StopReason.FAILED: "failed and was recorded by the Session",
    }
    verdict = verdict_by_reason[result.stop_reason]
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
    result = diagnose_or_degrade(profile, client)
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
    if prior := state.get("ledger_prior_mastery"):
        # A returning Candidate (issue 0023): show progress since their last Session.
        print("\n=== SINCE LAST SESSION ===")
        skill_states = state.get("skill_states", {})
        for skill in sorted(prior):
            raw = skill_states.get(skill)
            if raw is None:
                continue
            after = float(raw["alpha"]) / (float(raw["alpha"]) + float(raw["beta"]))
            before = float(prior[skill])
            print(f"  {skill}: {before:.2f} -> {after:.2f} ({after - before:+.2f})")
    for i, item in enumerate(state.get("transcript", []), start=1):
        print(
            f"\n--- QUESTION {i} ({item['skill']}) ---\n"
            f"score={item['resolved_weighted_score']:.2f}/5   "
            f"confidence={item['resolved_confidence']:.2f}   stop={_display_stop_reason(item['stop_reason'])}"
        )
        if error := item.get("error"):
            # A genuinely failed question (issue 0014) carries the recorded error; surface the reason
            # here so it is visible without opening the Markdown export (issue 0018).
            print(f"  error: {error}")
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


def _run_session_graph(graph, state: dict | None, config: dict, *, live: bool, already_seen: int = 0) -> dict:
    if not live:
        return graph.invoke(state, config)

    # On resume, ``already_seen`` is the number of questions already resolved in the checkpoint, so
    # the stream prints only genuinely new questions instead of replaying history as live (issue 0019).
    final: dict | None = None
    seen_questions = already_seen
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


def _known_session_ids(checkpointer) -> list[str]:
    """Best-effort list of Session ids that have a checkpoint, for a friendly unknown-id message."""
    try:
        rows = checkpointer.conn.execute("SELECT DISTINCT thread_id FROM checkpoints").fetchall()
    except Exception:  # noqa: BLE001 — listing ids is a convenience; never let it mask the real error
        return []
    return sorted(str(row[0]) for row in rows)


def _unknown_session_message(session_id: str, checkpointer, checkpoint_db: str) -> str:
    known = _known_session_ids(checkpointer)
    if known:
        hint = "Known Session ids: " + ", ".join(known) + "."
    else:
        hint = f"No saved Sessions found in {checkpoint_db!r}; start one without --resume."
    return f"No saved Session found for --session-id {session_id!r}. {hint}"


def _inflight_session_message(session_id: str) -> str:
    return (
        f"A Session with id {session_id!r} is already in progress. Pass --resume to continue it, or "
        "choose a different --session-id — starting fresh would discard its progress."
    )


def _print_resume_recap(state: dict) -> None:
    """Compact recap of what a resumed Session already resolved, instead of replaying history."""
    transcript = state.get("transcript", [])
    print(f"=== RESUMING SESSION {state.get('session_id')} ===")
    print(f"resolved so far: {len(transcript)} question(s)   current Skill: {state.get('next_skill') or '—'}")
    for i, item in enumerate(transcript, start=1):
        print(
            f"  Q{i} {item['skill']}: {item['resolved_weighted_score']:.2f}/5 "
            f"({_display_stop_reason(item['stop_reason'])})"
        )


def _cmd_session(client: LLMClient | None, args: argparse.Namespace) -> int:
    if client is None:
        raise RuntimeError("session requires an LLM client")
    if args.diagram:
        path = export_architecture_diagram(args.diagram, client)
        print(f"Exported architecture diagram to {path}")
        return 0

    question_bank = None
    if args.pack:
        # Run entirely from the pack (0025): its questions drive selection and its concept notes back
        # the Interviewer's lookups, instead of the built-in reference bank.
        pack = load_pack(args.pack)
        question_bank = pack.questions
        concept_store = InMemoryConceptStore(pack.concepts)
        print(f"Running from pack {pack.metadata.get('name')!r} ({args.pack}).")
    else:
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
            question_bank=question_bank,
        )
        config = session_config(args.session_id)
        try:
            if args.resume:
                resumed = resumable_session_state(graph, args.session_id)
                if resumed is None:
                    # An unknown --resume id would otherwise surface langgraph's EmptyInputError as a
                    # bare traceback; fail with a friendly one-liner that points at valid ids (0019).
                    print(_unknown_session_message(args.session_id, checkpointer, args.checkpoint_db), file=sys.stderr)
                    return 2
                # The max_elapsed_seconds rail bounds a single sitting, so resuming after a gap
                # restarts the time budget rather than force-completing on wall-clock since creation.
                graph.update_state(config, {"started_at": time.time()})
                _print_resume_recap(resumed)
                final = _run_session_graph(
                    graph, None, config, live=not args.no_live, already_seen=len(resumed.get("transcript", []))
                )
            else:
                existing = resumable_session_state(graph, args.session_id)
                if existing is not None and existing.get("status") != SessionStatus.COMPLETE.value:
                    # Don't silently restart over an in-flight Session on the same id (0019).
                    print(_inflight_session_message(args.session_id), file=sys.stderr)
                    return 2
                profile = CandidateProfile(
                    target_role=args.target_role,
                    target_companies=tuple(args.company),
                    claimed_skills=dict(args.claim),
                )
                carried = load_priors(args.ledger_db, args.candidate, now=time.time())
                diagnostic = diagnose_or_degrade(
                    profile,
                    client,
                    ledger_priors=carried.seed_means if carried else None,
                )
                state = initial_session_state(
                    args.session_id,
                    diagnostic,
                    max_questions=args.max_questions,
                    max_elapsed_seconds=args.max_elapsed_seconds,
                    candidate_id=args.candidate,
                    ledger_prior_mastery=carried.raw_mastery if carried else None,
                )
                final = _run_session_graph(graph, state, config, live=not args.no_live)
        except CandidateIntent as err:
            # ADR 0005 / issue 0018: the Candidate asked to stop (EOF/Ctrl-D, or a scripted Candidate
            # with nothing left). Abort cleanly with the designed exit code — no partial "complete"
            # Session, no fabricated failed questions.
            print(str(err), file=sys.stderr)
            return 2
    if args.candidate and final.get("status") == SessionStatus.COMPLETE.value:
        # Persist the final posteriors so the next Session for this Candidate starts warm (0023).
        save_posteriors(args.ledger_db, args.candidate, skill_states_from_state(final), now=time.time())
    _print_session_summary(final)
    if args.export_markdown:
        path = export_session_markdown(final, args.export_markdown)
        print(f"\nExported Session Markdown to {path}")
    return 0


def _cmd_pack_lint(client: LLMClient | None, args: argparse.Namespace) -> int:
    try:
        pack = load_pack(args.pack_dir)
    except BankError as err:
        # The contract dies at lint time with a named violation, never mid-interview (ADR 0008).
        print(f"Pack lint FAILED: {err}", file=sys.stderr)
        return 1
    n_questions = sum(len(qs) for qs in pack.questions.values())
    print(
        f"Pack {pack.metadata.get('name')!r} is valid: {n_questions} question(s) across "
        f"{len(pack.questions)} Skill(s) and {len(pack.concepts)} concept note(s)."
    )
    return 0


def _cmd_pack(client: LLMClient | None, args: argparse.Namespace) -> int:
    print("usage: coach pack lint <dir>", file=sys.stderr)
    return 2


def _cmd_eval_harness(client: LLMClient | None, args: argparse.Namespace) -> int:
    if client is None:
        raise RuntimeError("eval-harness requires an LLM client")
    results = run_golden_answer_harness(client)
    print(render_golden_answer_report(results))
    return 0 if harness_passed(results) else 1


def _utc_date() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _cmd_bench(client: LLMClient | None, args: argparse.Namespace) -> int:
    if client is None:
        raise RuntimeError("bench requires an LLM client")
    data = load_bench_data(args.cases or None)
    results = run_bench(client, data.cases)
    provider = getattr(client, "primary_provider", "unknown")
    settings = load_settings()
    report = render_bench_report(
        results,
        anchors=data.anchors,
        provider=str(provider),
        model=settings.primary_config.model or "unknown",
        date=_utc_date(),
    )
    out = Path(args.out) if args.out else Path("docs/audits") / f"calibration-bench-{_utc_date()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    within = sum(1 for r in results if r.within_band)
    print(f"Bench: {within}/{len(results)} cases within band. Report written to {out}.")
    return 0 if bench_passed(results) else 1


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
    session_parser.add_argument(
        "--candidate",
        default="",
        help="Candidate id for the cross-session Skill ledger (0023): seed priors from and persist "
        "posteriors to it. Omit for a one-shot cold-start Session.",
    )
    session_parser.add_argument(
        "--ledger-db",
        default=".skill-ledger.json",
        help="JSON file holding per-Candidate decayed Beta priors (0023).",
    )
    session_parser.add_argument(
        "--pack",
        default="",
        help="Run the Session from an external content pack directory instead of the built-in bank "
        "(0025). Lint it first with `coach pack lint <dir>`.",
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
    session_parser.add_argument(
        "--max-elapsed-seconds",
        type=float,
        default=DEFAULT_MAX_ELAPSED_SECONDS,
        help=(
            "Time budget for one sitting. It bounds active interviewing time: --resume restarts this "
            "budget so a Session picked up after a gap is not force-completed "
            f"(default: {DEFAULT_MAX_ELAPSED_SECONDS})."
        ),
    )
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
        help=(
            "Resume an existing checkpoint by --session-id instead of starting from Diagnostic. "
            "Restarts the elapsed-time budget and prints a recap instead of replaying history."
        ),
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

    bench_parser = sub.add_parser("bench", help="Issue 0022: bilingual Judge calibration bench")
    bench_parser.add_argument("--cases", default="", help="Path to a cases YAML (default: data/bench/cases.yaml).")
    bench_parser.add_argument(
        "--out", default="", help="Report output path (default: docs/audits/calibration-bench-<date>.md)."
    )
    bench_parser.set_defaults(func=_cmd_bench, requires_llm=True)

    pack_parser = sub.add_parser("pack", help="Issue 0025: manage external content packs")
    pack_parser.set_defaults(func=_cmd_pack, requires_llm=False)
    pack_sub = pack_parser.add_subparsers(dest="pack_command")
    lint_parser = pack_sub.add_parser("lint", help="Validate a pack directory (fail-loud, non-zero on violation)")
    lint_parser.add_argument("pack_dir", help="Path to the pack directory to validate.")
    lint_parser.set_defaults(func=_cmd_pack_lint, requires_llm=False)

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
