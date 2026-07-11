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
- ``coach forge`` (issue 0028): Writer + three ordered gates that queue new bank questions for
  human review under ``data/forge/``.

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

from . import telemetry
from .bank import BankError, load_pack
from .bench import bench_passed, load_bench_data, render_bench_report, run_bench
from .concepts import SEED_CONCEPTS, ChromaConceptStore, InMemoryConceptStore, build_concept_store
from .config import load_settings
from .diagnostic import SKILLS, CandidateProfile, diagnose_or_degrade
from .eval_harness import harness_passed, render_golden_answer_report, run_golden_answer_harness
from .evaluator import Evaluation, evaluate
from .exporter import export_session_markdown
from .fixtures import QUESTION, STRONG_ANSWER, WEAK_ANSWER
from .forge import MAX_DRAFTS, ForgeError, render_forge_report, run_forge, write_forge_outputs
from .language import DEFAULT_LANGUAGE_MODE, LANGUAGE_MODES
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
from .postmortem import PostmortemResult, export_postmortem_markdown, run_postmortem
from .resources import SEED_RESOURCES, ChromaResourceStore, build_resource_store
from .seeds import QUESTION_BANK, SEED_QUESTIONS
from .skill import POSTMORTEM_WEIGHT_RATIO, SkillState, apply_evaluation, confidence_weight
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
from .usage import daily_token_budget, remaining_today, usage_for_day

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
            language_mode=args.language,
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
    print(
        f"questions: {state['question_count']}   stop_reason: {state.get('stop_reason')}   "
        f"language_mode: {state.get('language_mode', 'en')}"
    )
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
                checkpoint_mode = resumed.get("language_mode", DEFAULT_LANGUAGE_MODE)
                if args.language is not None and args.language != checkpoint_mode:
                    # language_mode is Session state (ADR 0007): a resume continues the recorded
                    # mode; silently honoring a different flag mid-Session would be worse than
                    # ignoring it, but ignoring it silently hides the mismatch — say so.
                    print(
                        f"note: resuming with the checkpoint's language_mode={checkpoint_mode!r}; "
                        f"--language {args.language!r} is ignored on --resume",
                        file=sys.stderr,
                    )
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
                    language_mode=args.language or DEFAULT_LANGUAGE_MODE,
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


def _print_postmortem(result: PostmortemResult) -> None:
    print(
        f"=== POST-MORTEM DEBRIEF ({result.candidate_id}) — "
        f"{len(result.transcript)} question(s) elicited ==="
    )
    print(
        f"\n=== RECONSTRUCTED SCORECARD (second-hand evidence, fused at "
        f"{POSTMORTEM_WEIGHT_RATIO:g}x live weight) ==="
    )
    for entry in result.scorecard.entries:
        weight = POSTMORTEM_WEIGHT_RATIO * confidence_weight(entry.confidence)
        print(
            f"  {entry.skill:<18} estimated {entry.estimated_score:.1f}/5   "
            f"confidence {entry.confidence:.2f}   evidence_weight {weight:.2f}"
        )
        print(f"    rationale: {entry.rationale}")
        print(f"    recollection: {entry.recollection_evidence!r}")
    # Deterministic diff layer — always shown, mirrors the SINCE LAST SESSION block (issue 0023).
    print("\n=== STUDY PRIORITIES: BEFORE -> AFTER FUSION ===")
    rank_before = {t.skill: i for i, t in enumerate(result.targets_before, start=1)}
    before_by_skill = {t.skill: t for t in result.targets_before}
    for rank, target in enumerate(result.targets_after, start=1):
        before = before_by_skill.get(target.skill)
        if before is None:
            continue
        print(
            f"  {target.skill}: mastery {before.mastery:.2f} -> {target.mastery:.2f} "
            f"({target.mastery - before.mastery:+.2f})   "
            f"priority #{rank_before.get(target.skill, '—')} -> #{rank}"
        )
    if plan := result.study_plan:
        print("\n=== REGENERATED STUDY PLAN ===")
        print(f"readiness_estimate={plan['readiness_estimate']:.0%} — {plan['readiness_rationale']}")
        for topic in plan.get("prioritized_topics", []):
            resources = ", ".join(resource["id"] for resource in topic.get("resources", []))
            print(
                f"{topic['priority']}. {topic['skill']} "
                f"(mastery={topic['mastery']:.0%}, criticality={topic['role_criticality']}): {resources}"
            )
    elif error := result.study_plan_error:
        # The fusion still stands; only the optional regenerated plan was unavailable.
        print(f"\n=== REGENERATED STUDY PLAN ===\n(planner unavailable: {error})")


def _cmd_postmortem(client: LLMClient | None, args: argparse.Namespace) -> int:
    if client is None:
        raise RuntimeError("postmortem requires an LLM client")
    resource_store = build_resource_store(
        args.resource_store,
        persist_dir=args.resource_persist_dir,
        seed=not args.no_seed_resources,
    )
    candidate = (
        ScriptedCandidate(args.scripted_recollection)
        if args.scripted_recollection
        else InteractiveCandidate()
    )
    try:
        result = run_postmortem(
            client,
            candidate,
            candidate_id=args.candidate,
            ledger_db=args.ledger_db,
            target_role=args.role,
            companies=tuple(args.company),
            resource_store=resource_store,
        )
    except CandidateIntent as err:
        # ADR 0005 / issue 0026: the Candidate asked to stop mid-debrief. Abort cleanly with the
        # designed exit code; the partial recollection is discarded — nothing was written to the
        # ledger, and no reconstructed evidence is fabricated from an unfinished elicitation.
        print(str(err), file=sys.stderr)
        print(
            "Post-mortem aborted; the partial recollection was discarded and the Skill ledger "
            "was not touched.",
            file=sys.stderr,
        )
        return 2
    _print_postmortem(result)
    if args.export_markdown:
        path = export_postmortem_markdown(result, args.export_markdown)
        print(f"\nExported post-mortem Markdown to {path}")
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


# A 29-case bench run measures ~100–200k tokens including retries; starting one with less than
# this in the day's budget risks dying mid-run on insufficient_quota with a half-written report.
BENCH_MIN_BUDGET_TOKENS = 200_000


def _cmd_bench(client: LLMClient | None, args: argparse.Namespace) -> int:
    if client is None:
        raise RuntimeError("bench requires an LLM client")
    provider = getattr(client, "primary_provider", "unknown")
    left = remaining_today(str(provider))
    print(f"Daily budget check ({provider}): ~{left:,} of {daily_token_budget():,} tokens left by our count.")
    if left < BENCH_MIN_BUDGET_TOKENS:
        print(
            f"WARNING: under {BENCH_MIN_BUDGET_TOKENS:,} tokens left — a full bench run may die "
            "mid-run on insufficient_quota. Consider waiting for the daily reset (00:00 UTC).",
            file=sys.stderr,
        )
    usage_before = usage_for_day().get(str(provider), {})
    telemetry_before = telemetry.snapshot()
    data = load_bench_data(args.cases or None)
    results = run_bench(client, data.cases)
    telemetry_after = telemetry.snapshot()
    usage_after = usage_for_day().get(str(provider), {})
    run_usage = {
        str(provider): {
            key: usage_after.get(key, 0) - usage_before.get(key, 0)
            for key in ("prompt", "completion", "total", "calls")
        }
    }
    settings = load_settings()
    report = render_bench_report(
        results,
        anchors=data.anchors,
        provider=str(provider),
        model=settings.primary_config.model or "unknown",
        date=_utc_date(),
        telemetry_delta=telemetry.delta(telemetry_before, telemetry_after),
        token_usage=run_usage,
    )
    out = Path(args.out) if args.out else Path("docs/audits") / f"calibration-bench-{_utc_date()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    within = sum(1 for r in results if r.within_band)
    spent = run_usage[str(provider)]["total"]
    print(
        f"Bench: {within}/{len(results)} cases within band. Report written to {out}. "
        f"Run cost ~{spent:,} tokens; ~{remaining_today(str(provider)):,} left today."
    )
    return 0 if bench_passed(results) else 1


def _cmd_usage(client: LLMClient | None, args: argparse.Namespace) -> int:
    """Today's client-side token ledger — the daily free-tier budget is invisible to the API."""
    totals = usage_for_day()
    if not totals:
        print("No recorded usage today (ledger: logs/usage-ledger.jsonl).")
    for provider, stats in sorted(totals.items()):
        print(
            f"{provider}: {stats['total']:,} tokens across {stats['calls']} call(s) "
            f"({stats['prompt']:,} prompt + {stats['completion']:,} completion)"
        )
    budget = daily_token_budget()
    settings = load_settings()
    primary = settings.primary_provider
    print(f"Primary ({primary}): ~{remaining_today(primary):,} of {budget:,} daily tokens left by our count.")
    return 0


def _cmd_forge(client: LLMClient | None, args: argparse.Namespace) -> int:
    if client is None:
        raise RuntimeError("forge requires an LLM client")
    # Gate 2 must dedup across everything the merged install would serve: the built-in bank plus,
    # when the drafts target a pack, that pack's questions. The pack's concept notes then also
    # become valid Writer grounding / expected_concepts targets.
    corpus = [q.question for questions in QUESTION_BANK.values() for q in questions]
    concepts = list(SEED_CONCEPTS)
    if args.pack:
        pack = load_pack(args.pack)
        corpus.extend(q.question for questions in pack.questions.values() for q in questions)
        concepts.extend(pack.concepts)
    try:
        run = run_forge(client, args.skill, args.n, concepts=concepts, existing_prompts=corpus)
    except ForgeError as err:
        # Pipeline failure (the Writer produced nothing usable) — distinct from an honest
        # zero-admissions run, which still exits 0 with a full report (0 admitted is information).
        print(f"Forge FAILED: {err}", file=sys.stderr)
        return 1
    provider = getattr(client, "primary_provider", "unknown")
    settings = load_settings()
    model = settings.primary_config.model or "unknown"
    date = _utc_date()
    queue_path = Path(args.out) if args.out else Path(args.queue_dir) / f"review-queue-{date}.yaml"
    queue, report = write_forge_outputs(
        run, queue_path=queue_path, provider=str(provider), model=model, date=date
    )
    print(render_forge_report(run, provider=str(provider), model=model, date=date))
    admitted = sum(1 for outcome in run.outcomes if outcome.admitted)
    print(
        f"Forge: {admitted}/{len(run.outcomes)} draft(s) admitted. "
        f"Review queue written to {queue}; report to {report}."
    )
    return 0


def _forge_batch_size(raw: str) -> int:
    """argparse type for ``forge --n``: the cap is the free-tier budget rail (see forge.MAX_DRAFTS)."""
    try:
        n = int(raw)
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"--n must be an integer, got {raw!r}") from err
    if not 1 <= n <= MAX_DRAFTS:
        raise argparse.ArgumentTypeError(
            f"--n must be between 1 and {MAX_DRAFTS}: gate 3 spends ~4+ LLM calls per surviving "
            "draft and there is no rate-limit backoff to lean on"
        )
    return n


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
    iv_parser.add_argument(
        "--language",
        choices=list(LANGUAGE_MODES),
        default=DEFAULT_LANGUAGE_MODE,
        help="language_mode for the demo micro-loop (0024): en, vn, or mixed.",
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
    session_parser.add_argument(
        "--language",
        choices=list(LANGUAGE_MODES),
        default=None,  # None = "not passed": lets --resume tell an explicit flag from the default
        help=(
            "Session language_mode (0024, ADR 0007): en = English interview; vn = Vietnamese; "
            "mixed = Vietnamese with natural English code-switching, like a VNG/FPT round. "
            f"Default: {DEFAULT_LANGUAGE_MODE}. Ignored on --resume (the checkpoint's mode wins)."
        ),
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

    pm_parser = sub.add_parser(
        "postmortem",
        help="Issue 0026: debrief a real rejected interview and fuse the reconstructed scorecard "
        "into the Skill ledger at reduced weight",
    )
    pm_parser.add_argument(
        "--candidate",
        required=True,
        help="Candidate id whose Skill ledger (0023) the reconstructed evidence is fused into.",
    )
    pm_parser.add_argument(
        "--ledger-db",
        default=".skill-ledger.json",
        help="JSON file holding per-Candidate decayed Beta priors (0023).",
    )
    pm_parser.add_argument(
        "--role",
        default="machine learning engineer",
        help="Target role, used for Role-criticality metadata in the Study Plan diff.",
    )
    pm_parser.add_argument(
        "--company",
        action="append",
        default=[],
        help="Target company; may be passed multiple times.",
    )
    pm_parser.add_argument(
        "--scripted-recollection",
        action="append",
        default=[],
        help="Scripted recollection answer for non-interactive runs; repeat once per answer. "
        "Omit to be debriefed interactively in the terminal.",
    )
    pm_parser.add_argument(
        "--resource-store",
        choices=["memory", "chroma"],
        default="memory",
        help="Resource store used by the regenerated Study Plan.",
    )
    pm_parser.add_argument(
        "--resource-persist-dir",
        default=".chroma",
        help="Chroma persistence directory when --resource-store=chroma.",
    )
    pm_parser.add_argument(
        "--no-seed-resources",
        action="store_true",
        help="Do not upsert the built-in learning resources before planning.",
    )
    pm_parser.add_argument(
        "--export-markdown",
        help="Write the post-mortem debrief (scorecard, ledger delta, regenerated plan) to this "
        "Markdown path.",
    )
    pm_parser.set_defaults(func=_cmd_postmortem, requires_llm=True)

    harness_parser = sub.add_parser("eval-harness", help="Slice 0012: run Evaluator golden-answer checks")
    harness_parser.set_defaults(func=_cmd_eval_harness, requires_llm=True)

    usage_parser = sub.add_parser("usage", help="Show today's token spend per provider (client-side daily ledger)")
    usage_parser.set_defaults(func=_cmd_usage, requires_llm=False)

    bench_parser = sub.add_parser("bench", help="Issue 0022: bilingual Judge calibration bench")
    bench_parser.add_argument("--cases", default="", help="Path to a cases YAML (default: data/bench/cases.yaml).")
    bench_parser.add_argument(
        "--out", default="", help="Report output path (default: docs/audits/calibration-bench-<date>.md)."
    )
    bench_parser.set_defaults(func=_cmd_bench, requires_llm=True)

    forge_parser = sub.add_parser(
        "forge", help="Issue 0028: Question Forge — draft, gate, and queue new bank questions for review"
    )
    forge_parser.add_argument(
        "--skill",
        required=True,
        choices=SKILLS,
        help="Canonical Skill the Writer drafts questions for.",
    )
    forge_parser.add_argument(
        "--n",
        type=_forge_batch_size,
        default=5,
        help=f"How many drafts the Writer produces (1–{MAX_DRAFTS}; the cap is the free-tier budget rail).",
    )
    forge_parser.add_argument(
        "--pack",
        default="",
        help="Also dedup against (and ground expected_concepts in) this content pack directory.",
    )
    forge_parser.add_argument(
        "--queue-dir",
        default="data/forge",
        help="Directory for the review queue + report (default: data/forge).",
    )
    forge_parser.add_argument(
        "--out",
        default="",
        help="Explicit review-queue YAML path (default: <queue-dir>/review-queue-<date>.yaml).",
    )
    forge_parser.set_defaults(func=_cmd_forge, requires_llm=True)

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
        language=DEFAULT_LANGUAGE_MODE,
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
