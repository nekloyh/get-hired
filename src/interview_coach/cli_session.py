"""Running a Session from the terminal: the driver, the resume refusals, and what gets printed.

Split out of ``cli`` under GH #124. One reason to change: what `coach session` does and shows. It is
the largest single responsibility in the CLI and it sat in the middle of the file, between the
argparse table and the other subcommands.

Imports run one way — ``cli`` imports this, never the reverse at runtime. ``ClientArg`` comes in
under ``TYPE_CHECKING`` only, which is enough because every annotation in this package is a string
(``from __future__ import annotations``).

Note for tests: a name this module calls is patched HERE, not on ``cli`` — `diagnose_or_degrade` and
`resumable_session_state` are resolved from this module's globals.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.sqlite import SqliteSaver

from .bank import load_pack
from .concepts import ConceptStore, build_concept_store, embedder_for_language, embedder_persist_dir
from .diagnostic import CandidateProfile, diagnose_or_degrade
from .exporter import export_session_markdown
from .filelock import claimed
from .language import DEFAULT_LANGUAGE_MODE
from .ledger import SAFE_CANDIDATE_ID, is_safe_candidate_id, load_priors, save_measured_posteriors
from .llm import UNKNOWN_PROVIDER, ensure_role_clients, provider_label
from .microloop import CandidateIntent, InteractiveCandidate, display_stop_reason
from .resources import build_resource_store
from .session_serde import measured_skill_states
from .skill import SkillState
from .supervisor import (
    SessionStatus,
    build_session_graph,
    export_architecture_diagram,
    initial_session_state,
    resumable_session_state,
    session_config,
)
from .ui import render_skill_state_rows
from .usage import (
    AccountingUnavailable,
    ProviderQuotaExhausted,
    SessionBudgetSuspended,
    begin_session_run,
    clear_run_rails_for_resume,
    daily_reset_hint,
    session_budget_guard,
    session_scope,
    start_refusal_reason,
)

if TYPE_CHECKING:
    from .cli import ClientArg


def _print_session_summary(state: Mapping[str, Any]) -> None:
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
            after = SkillState.from_dict(raw).mastery
            before = float(prior[skill])
            print(f"  {skill}: {before:.2f} -> {after:.2f} ({after - before:+.2f})")
    for i, item in enumerate(state.get("transcript", []), start=1):
        print(
            f"\n--- QUESTION {i} ({item['skill']}) ---\n"
            f"score={item['resolved_weighted_score']:.2f}/5   "
            f"confidence={item['resolved_confidence']:.2f}   stop={display_stop_reason(item['stop_reason'])}"
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
            if trace.get("llm_calls"):
                split = ", ".join(f"{name} {n}" for name, n in trace.get("llm_calls_by_provider") or ())
                print(f"     llm_calls: {trace['llm_calls']}" + (f" ({split})" if split else ""))
            if trace.get("stop_reason"):
                print(f"     turn_stop_reason: {display_stop_reason(trace['stop_reason'])}")
    if state.get("supervisor_decisions"):
        print("\n=== SUPERVISOR DECISIONS ===")
        for decision in state["supervisor_decisions"]:
            print(
                f"- after Q{decision['after_question']}: {decision['action']} "
                f"(deviation={decision['deviation']}) — {decision['llm_reasoning']}"
            )
    _print_study_plan(state.get("study_plan"), state.get("study_plan_error"))


def _print_study_plan(plan: Mapping[str, Any] | None, error: str | None, *, title: str = "STUDY PLAN") -> None:
    """The plan when there is one; otherwise the planner error — the interview itself still stands."""
    if plan:
        print(f"\n=== {title} ===")
        print(f"readiness_estimate={plan['readiness_estimate']:.0%} — {plan['readiness_rationale']}")
        for topic in plan.get("prioritized_topics", []):
            resources = ", ".join(resource["id"] for resource in topic.get("resources", []))
            print(
                f"{topic['priority']}. {topic['skill']} "
                f"(mastery={topic['mastery']:.0%}, criticality={topic['role_criticality']}): {resources}"
            )
    elif error:
        print(f"\n=== {title} ===\n(planner unavailable: {error})")


def _print_live_question_update(state: dict, item: dict, question_number: int) -> None:
    print(f"\n=== LIVE UPDATE: QUESTION {question_number} RESOLVED ({item['skill']}) ===")
    print(
        f"score={item['resolved_weighted_score']:.2f}/5   "
        f"confidence={item['resolved_confidence']:.2f}   stop={display_stop_reason(item['stop_reason'])}"
    )
    print("--- SKILL STATES ---")
    for row in render_skill_state_rows(state):
        print(row)


def _run_session_graph(
    graph,
    state: Mapping[str, Any] | None,
    config: dict,
    *,
    live: bool,
    already_seen: int = 0,
    budget_stop: Callable[[Mapping[str, Any]], str | None] | None = None,
) -> dict:
    """Drive the Session graph, printing live updates and enforcing the budget rail between nodes.

    ``--no-live`` streams too rather than calling ``invoke``: the two are equal (an identical
    Session id gives ``graph.invoke(...) == the last streamed value``, zero differing keys — pinned
    by the ``--no-live`` tests), and only the streaming form has a node boundary at which the rail
    can suspend. Without the collapse, ``--no-live`` — a perfectly ordinary live-provider mode —
    would have no rail at all.

    ``budget_stop`` is checked at each ``stream_mode="values"`` event, which includes the input
    state BEFORE the first node runs. Raising HERE, outside the graph, is the whole design (ADR
    0005): a stop raised inside a node lands in ``question_node``'s ``except Exception`` net and
    becomes a zero-evidence ``failed`` question. The checkpoint is already durable at each event, so
    breaking out leaves a Session that ``--resume`` picks up exactly where it stopped.
    """
    # On resume, ``already_seen`` is the number of questions already resolved in the checkpoint, so
    # the stream prints only genuinely new questions instead of replaying history as live (issue 0019).
    final: dict | None = None
    seen_questions = already_seen
    for event in graph.stream(state, config, stream_mode="values"):
        final = dict(event)
        transcript = final.get("transcript", [])
        if live and len(transcript) > seen_questions:
            for question_index in range(seen_questions, len(transcript)):
                _print_live_question_update(final, transcript[question_index], question_index + 1)
            seen_questions = len(transcript)
        # Checked AFTER the live update, so the question the Candidate just finished is acknowledged
        # before the suspend banner — it IS in the checkpoint, and a suspend that looks like it ate
        # the last answer is indistinguishable from a crash.
        if budget_stop is not None and (reason := budget_stop(final)):
            # The banner names no cause: this one rail now carries two of them (budget exhaustion
            # and a broken usage ledger), and the reason below states which. Labelling an accounting
            # fault "(budget)" would send the operator to wait for 00:00 UTC for a file permission.
            print(f"\n=== SESSION SUSPENDED ===\n{reason}", file=sys.stderr)
            raise SessionBudgetSuspended(reason)
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


def _completed_session_message(session_id: str) -> str:
    return (
        f"A Session with id {session_id!r} has already finished. Choose a different --session-id — "
        "starting fresh would overwrite its report, and --resume cannot re-open a finished Session."
    )


def _finished_session_message(session_id: str) -> str:
    return (
        f"Session {session_id!r} already finished; there is nothing to resume. Re-opening it would "
        "print that earlier interview's report as this run's result. Start a new interview with a "
        "different --session-id."
    )


def _busy_session_message(session_id: str) -> str:
    return (
        f"Session {session_id!r} is already being driven by another process (the server, or a second "
        "shell). One checkpoint thread takes one writer — wait for that run to finish, or choose a "
        "different --session-id."
    )


def _checkpoint_lock_target(checkpoint_db: str, session_id: str) -> Path:
    """The per-Session inter-process lock target beside the checkpoint DB.

    Keyed by Session id, not by the DB: one file holds every thread, so a DB-wide lock would refuse
    unrelated Sessions. The id is hashed rather than spelled into the name because it is unvalidated
    input — a ``--session-id`` carrying a path separator would otherwise pick the lock's directory.
    """
    db = Path(checkpoint_db).resolve()  # so a relative and an absolute --checkpoint-db agree
    return db.with_name(f"{db.name}.{hashlib.sha256(session_id.encode('utf-8')).hexdigest()[:16]}")


def _print_resume_recap(state: Mapping[str, Any]) -> None:
    """Compact recap of what a resumed Session already resolved, instead of replaying history."""
    transcript = state.get("transcript", [])
    print(f"=== RESUMING SESSION {state.get('session_id')} ===")
    print(f"resolved so far: {len(transcript)} question(s)   current Skill: {state.get('next_skill') or '—'}")
    for i, item in enumerate(transcript, start=1):
        print(
            f"  Q{i} {item['skill']}: {item['resolved_weighted_score']:.2f}/5 "
            f"({display_stop_reason(item['stop_reason'])})"
        )


def _cmd_session(client: ClientArg, args: argparse.Namespace) -> int:
    roles = ensure_role_clients(client)
    if roles is None:
        raise RuntimeError("session requires an LLM client")
    if args.diagram:
        path = export_architecture_diagram(args.diagram, roles)
        print(f"Exported architecture diagram to {path}")
        return 0
    if args.candidate and not is_safe_candidate_id(args.candidate):
        # Refuse BEFORE the interview: save_posteriors is silent by contract, so a bad --candidate
        # would otherwise run the whole Session and then persist none of its Skill evidence.
        print(
            f"Refusing to start this Session: --candidate {args.candidate!r} is not a valid Skill "
            f"ledger key (expected {SAFE_CANDIDATE_ID.pattern}).",
            file=sys.stderr,
        )
        return 2

    question_bank = None
    if args.pack:
        # Run entirely from the pack (0025): its questions drive selection and its concept notes back
        # the Interviewer's lookups, instead of the built-in reference bank.
        pack = load_pack(args.pack)
        question_bank = pack.questions
        # R-13: a pack Session used to be pinned to the keyword ranker regardless of what was
        # installed, so every pack interview ran on the un-measured retrieval path — and Vietnamese
        # pack notes carry almost no signal in it. Seed the resolved store with the PACK's notes
        # (never the built-in seeds: running "entirely from the pack" is the point of 0025).
        concept_store: ConceptStore = build_concept_store(
            args.concept_store, persist_dir=args.concept_persist_dir, seed=False
        )
        concept_store.ingest(pack.concepts)
        print(f"Running from pack {pack.metadata.get('name')!r} ({args.pack}).")
    else:
        # R-14: unless the operator names one, the embedder follows the Session's language.
        embedder = args.concept_embedder or embedder_for_language(args.language or DEFAULT_LANGUAGE_MODE)
        concept_store = build_concept_store(
            args.concept_store,
            persist_dir=embedder_persist_dir(args.concept_persist_dir, embedder),
            seed=not args.no_seed_concepts,
            embedding_model=embedder,
        )
    resource_store = build_resource_store(seed=not args.no_seed_resources)
    # R-25: the provider whose daily allowance this Session actually spends — the judge role, same
    # as the bench and forge preflights read. A client with no provider identity (demo, test fakes)
    # spends nobody's allowance, so every rail below is inert for it.
    provider = provider_label(roles.judge)
    metered = provider != UNKNOWN_PROVIDER
    if metered and not args.resume and (refusal := start_refusal_reason(provider, questions=args.max_questions)):
        # Refuse BEFORE the Diagnostic call: a start gate that has already spent tokens is not one.
        print(f"Refusing to start this Session: {refusal}", file=sys.stderr)
        return 2

    budget_stop = (
        session_budget_guard(
            args.session_id,
            provider,
            max_turns=args.max_turns,
            complete_status=SessionStatus.COMPLETE.value,
        )
        if metered
        else None
    )

    # The scope covers the Diagnostic call too, so every token this Session spends is attributed.
    with (
        # NEW-20: one writer per checkpoint thread, across processes. Non-blocking on purpose — a
        # drive lasts as long as the interview, so a second one is refused with a message instead of
        # being parked for half an hour on a lock it cannot see.
        claimed(_checkpoint_lock_target(args.checkpoint_db, args.session_id)) as sole_driver,
        SqliteSaver.from_conn_string(args.checkpoint_db) as checkpointer,
        session_scope(args.session_id),
    ):
        if not sole_driver:
            print(_busy_session_message(args.session_id), file=sys.stderr)
            return 2
        candidate_factory = None if args.scripted else lambda seed: InteractiveCandidate()
        graph = build_session_graph(
            roles,
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
                if resumed.get("status") == SessionStatus.COMPLETE.value:
                    # NEW-19: a finished interview has no next node, so the stream yields its stored
                    # values once and hands them back — exit 0 and a full "(complete)" report for the
                    # EARLIER interview, under a "RESUMING SESSION" banner, as if it were this run's.
                    print(_finished_session_message(args.session_id), file=sys.stderr)
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
                if metered and (
                    cleared := clear_run_rails_for_resume(
                        args.session_id,
                        provider,
                        max_questions=int(resumed.get("max_questions", args.max_questions)),
                        max_turns=args.max_turns,
                    )
                ):
                    # The rails that latch on this run's own state cannot clear themselves, so a
                    # resume that did not clear them would re-trip at stream event 0 forever. Said
                    # out loud because a grant of more budget is exactly the thing a user must not
                    # discover from the ledger a day later.
                    print(f"note: resuming clears the budget stop — {cleared}", file=sys.stderr)
                _print_resume_recap(resumed)
                final = _run_session_graph(
                    graph,
                    None,
                    config,
                    live=not args.no_live,
                    already_seen=len(resumed.get("transcript", [])),
                    budget_stop=budget_stop,
                )
            else:
                existing = resumable_session_state(graph, args.session_id)
                if existing is not None:
                    # Don't silently restart over a Session on this id (0019) — in-flight OR
                    # finished. QA-01: a completed checkpoint is an interview whose report a fresh
                    # start would overwrite, so it is refused too, with its own remedy.
                    print(
                        _completed_session_message(args.session_id)
                        if existing.get("status") == SessionStatus.COMPLETE.value
                        else _inflight_session_message(args.session_id),
                        file=sys.stderr,
                    )
                    return 2
                profile = CandidateProfile(
                    target_role=args.target_role,
                    target_companies=tuple(args.company),
                    claimed_skills=dict(args.claim),
                )
                if metered:
                    # Stamp this run's baseline before the Diagnostic — the first token it spends
                    # must land on THIS run's side of the line. Without it the rail would measure
                    # everything the id ever spent, and --session-id defaults to one constant, so
                    # the day's third interview would suspend for spending nothing of its own.
                    begin_session_run(args.session_id)
                carried = load_priors(args.ledger_db, args.candidate, now=time.time())
                diagnostic = diagnose_or_degrade(
                    profile,
                    roles.diagnostic,
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
                final = _run_session_graph(graph, state, config, live=not args.no_live, budget_stop=budget_stop)
        except SessionBudgetSuspended:
            # ADR 0005's third category: budget exhaustion is anticipated scarcity, not intent and
            # not an infrastructure failure. The reason is already on stderr; add the exact command
            # that picks the Session back up, because a suspend without a resume path is a stall.
            print(
                f"Resume it with: coach session --resume --session-id {args.session_id} "
                f"--checkpoint-db {args.checkpoint_db}",
                file=sys.stderr,
            )
            return 2
        except ProviderQuotaExhausted as err:
            # GH #119: the daily quota died mid-Session. The typed raise carried it past the
            # per-question net, so the checkpoint holds only real evidence; the remedy is time.
            print(f"\n=== SESSION SUSPENDED ===\n{err} {daily_reset_hint()}", file=sys.stderr)
            if resumable_session_state(graph, args.session_id) is None:
                # It died on the Diagnostic, before the graph wrote anything: there is no
                # checkpoint to resume, and saying otherwise would send the user to an unknown-id error.
                print("Nothing was checkpointed yet; start the Session again after the reset.", file=sys.stderr)
            else:
                print(
                    f"Resume it with: coach session --resume --session-id {args.session_id} "
                    f"--checkpoint-db {args.checkpoint_db}",
                    file=sys.stderr,
                )
            return 2
        except AccountingUnavailable as err:
            # M0a / F1: a call was refused because usage accounting is broken. Not intent, and not
            # the per-question failure net's business — the questions resolved so far are in the
            # checkpoint and nothing was recorded as `failed`. The remedy is bookkeeping, not time,
            # so the resume line is printed under the reason rather than instead of it.
            print(f"\n=== SESSION STOPPED (accounting) ===\n{err}", file=sys.stderr)
            print(
                f"Once accounting is healthy, resume it with: coach session --resume --session-id "
                f"{args.session_id} --checkpoint-db {args.checkpoint_db}",
                file=sys.stderr,
            )
            return 2
        except CandidateIntent as err:
            # ADR 0005 / issue 0018: the Candidate asked to stop (EOF/Ctrl-D, or a scripted Candidate
            # with nothing left). Abort cleanly with the designed exit code — no partial "complete"
            # Session, no fabricated failed questions.
            print(str(err), file=sys.stderr)
            return 2
    if args.candidate and final.get("status") == SessionStatus.COMPLETE.value:
        # Persist the final posteriors so the next Session for this Candidate starts warm (0023).
        # NEW-17: only Skills this Session actually measured — see `measured_skill_states`.
        save_measured_posteriors(args.ledger_db, args.candidate, measured_skill_states(final), now=time.time())
    _print_session_summary(final)
    if args.export_markdown:
        path = export_session_markdown(final, args.export_markdown)
        print(f"\nExported Session Markdown to {path}")
    return 0
