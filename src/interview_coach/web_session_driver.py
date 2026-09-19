"""The graph-driver thread: the only LangGraph-aware code behind the web API.

Split out of ``web_api`` under GH #124. One reason to change: how a Session is driven from a browser
socket — mode selection, the run thread, budget rails, the checkpoint reads a route needs, and the
export written on completion.

It depends on ``web_protocol`` (what the client asked for) and ``web_runtime`` (what a live Session
is), and on nothing in ``web_api`` — the dependency runs one way so the routes can import this.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from typing import Any, cast

from langgraph.checkpoint.sqlite import SqliteSaver

from .concepts import (
    build_concept_store,
    embedder_for_language,
    embedder_persist_dir,
)
from .config import Settings
from .demo_llm import DemoLLMClient
from .diagnostic import CandidateProfile, diagnose_or_degrade
from .exporter import export_session_markdown
from .language import DEFAULT_LANGUAGE_MODE
from .ledger import load_priors, save_measured_posteriors
from .llm import UNKNOWN_PROVIDER, LLMClient, build_client, build_role_clients, provider_label
from .microloop import DEFAULT_MAX_TURNS, CandidateInputUnavailable, CandidateIntent
from .resources import build_resource_store
from .session_serde import measured_skill_states
from .supervisor import (
    DEFAULT_MAX_QUESTIONS,
    SessionStatus,
    build_session_graph,
    initial_session_state,
    session_config,
)
from .usage import (
    AccountingUnavailable,
    ProviderQuotaExhausted,
    SessionBudgetSuspended,
    begin_session_run,
    clear_run_rails_for_resume,
    daily_reset_hint,
    record_questions_released,
    reserve_questions,
    session_budget_guard,
    session_scope,
    start_refusal_reason,
    token_identity,
)
from .web_protocol import ResumeSessionPayload, SessionMode, StartSessionPayload
from .web_runtime import (
    _ALREADY_CHECKPOINTED,
    QueueCandidate,
    RuntimeSession,
    WebApiState,
    _remember_completed,
    export_path,
)

logger = logging.getLogger(__name__)


def _is_running(runtime: RuntimeSession) -> bool:
    return runtime.thread is not None and runtime.thread.is_alive()


def _select_mode(mode: SessionMode, settings: Settings) -> str:
    if mode == "demo":
        return "demo"
    if mode == "live":
        return "live"
    return "live" if settings.configured else "demo"


def _client_for_mode(mode: str, settings: Settings) -> LLMClient:
    if mode == "demo":
        return DemoLLMClient()
    if not settings.configured:
        raise RuntimeError(
            f"LLM primary provider {settings.primary_provider!r} is not configured; use demo mode or configure .env."
        )
    return build_client(settings)


def _run_session_thread(
    api_state: WebApiState,
    runtime: RuntimeSession,
    payload: StartSessionPayload | ResumeSessionPayload,
    resume: bool,
) -> None:
    # QA-08: what this run took off the daily question cap, so the `finally` can hand back what it
    # can never ask. Declared outside the `try`, because the first statement inside it can raise.
    reservation: tuple[str, int] | None = None
    try:
        # QA-01: a fresh start on an id that already has a checkpoint restarts the graph over it AND
        # overwrites exports/<id>.md, which the export endpoint can never get back — it reads RAM,
        # then that file, never the checkpoint. The browser keeps ONE id in localStorage
        # (web/src/lib/sessionId.ts) and renders it read-only, so a returning Candidate pressing
        # Start is exactly this case, not an edge case. Refuse it before anything is built or spent;
        # resuming and rotating the id are both one click away.
        if not resume and _checkpoint_values(api_state, runtime.session_id):
            logger.warning("refused a fresh start on Session %r: it already has a checkpoint", runtime.session_id)
            runtime.emit({"type": "session_error", "error": _ALREADY_CHECKPOINTED})
            return
        client = _client_for_mode(runtime.mode, api_state.settings)
        # ADR 0010: demo mode's client is not a router, so the bundle collapses to single-client
        # semantics; live mode pins the judge and applies any ROLE_* overrides.
        roles = build_role_clients(api_state.settings, client)
        # R-25: the free-tier rails, checked before ANY token is spent. A client with no provider
        # identity (demo mode, test fakes) spends nobody's allowance, so both gates are inert for it.
        provider = provider_label(roles.judge)
        metered = provider != UNKNOWN_PROVIDER
        checkpoint_values = _checkpoint_values(api_state, runtime.session_id) if resume else {}
        if resume and not checkpoint_values:
            # The CLI's --resume guard, ported (issue 0019). With nothing checkpointed,
            # graph.stream(None, ...) answers with langgraph's EmptyInputError, which reached the
            # Candidate as `session_error: EmptyInputError: Received no input for __start__`. Not an
            # edge case: the browser keeps one Session id in localStorage forever while checkpoints
            # expire on COACH_CHECKPOINT_TTL_SECONDS (7 days), so a Candidate returning after the
            # sweep clicks the UI's own "Reconnect & Resume" and is hard-stuck on a message about
            # `__start__`. Refused ABOVE the resume budget-rail clearing, which writes to the usage
            # ledger, and BEFORE `session_started` — the reducer appends "Session resumed from
            # checkpoint." on that frame, so emitting it here tells the Candidate their progress was
            # restored and then hands them the error.
            logger.warning("refused to resume Session %r: no checkpoint", runtime.session_id)
            runtime.emit({"type": "session_error", "error": _unknown_session_message(runtime.session_id)})
            return
        # QA-08: built HERE, before the cap reservation below, because building it is what rejects an
        # unknown Skill claim. Reserving first let 48 malformed frames at max_questions=10 fill a
        # 480-question cap for the whole UTC day at zero provider cost, and a client that crashes
        # between the two did the same by accident.
        profile: CandidateProfile | None = None
        if not resume:
            assert isinstance(payload, StartSessionPayload)
            profile = CandidateProfile(
                target_role=payload.target_role,
                target_companies=tuple(payload.target_companies),
                claimed_skills=payload.claimed_skills,
            )
        max_questions = (
            int(checkpoint_values.get("max_questions", DEFAULT_MAX_QUESTIONS))
            if resume
            else cast("StartSessionPayload", payload).max_questions
        )
        if metered and not resume:
            assert isinstance(payload, StartSessionPayload)
            identity = token_identity(api_state.settings.auth_token)
            # Budget rail first (read-only), then the cap: reserved at START, not at completion (a
            # cap that only counts finished Sessions is bypassed by abandoning them), check+record in
            # one locked step, and never consumed by a start the budget rail already refused.
            refusal = start_refusal_reason(provider, questions=payload.max_questions) or reserve_questions(
                identity, questions=payload.max_questions
            )
            if refusal is not None:
                # No `session_started`: the Candidate must never watch an interview begin that
                # cannot be paid for.
                logger.warning("refused to start Session %r: %s", runtime.session_id, refusal)
                runtime.emit({"type": "session_error", "error": refusal})
                return
            reservation = (identity, payload.max_questions)
        if metered and resume:
            # The Candidate clicked resume. The per-run ceiling and the insufficient_quota latch
            # both hang on this run's own state, so nothing but this clears them — and a resume
            # that cannot clear them re-suspends at stream event 0 forever, which is the stall
            # ADR 0005 forbids and which a Candidate with no shell has no way around.
            if cleared := clear_run_rails_for_resume(
                runtime.session_id,
                provider,
                max_questions=max_questions,
                max_turns=DEFAULT_MAX_TURNS,
            ):
                logger.warning("Session %r resumed past a budget stop: %s", runtime.session_id, cleared)
        # R-13: the measured path is the default path. Demo mode stays in-memory on purpose — it
        # runs on a fake model for UX review, and building a Chroma index (first run: downloading an
        # embedding model) to serve fake questions would be a slow answer to a question nobody asked.
        # R-14: the embedder follows the Session's language. BGE is English-only and collapses
        # Vietnamese onto a hub, so a vn/mixed Session retrieving with it ranks near-randomly.
        language_mode = _session_language_mode(payload, resume, checkpoint_values)
        embedder = embedder_for_language(language_mode)
        concept_store = build_concept_store(
            "memory" if runtime.mode == "demo" else api_state.settings.concept_store,
            persist_dir=embedder_persist_dir(api_state.settings.concept_persist_dir or None, embedder),
            seed=True,
            embedding_model=embedder,
        )
        resource_store = build_resource_store(seed=True)

        # The same guard the CLI installs, built from the same factory — the two surfaces must not
        # be able to disagree about when a Session suspends or what it is told.
        budget_stop = (
            session_budget_guard(
                runtime.session_id,
                provider,
                max_turns=DEFAULT_MAX_TURNS,
                complete_status=SessionStatus.COMPLETE.value,
            )
            if metered
            else None
        )

        # The scope attributes every provider call this Session makes — the graph runs on this same
        # thread, so the ContextVar reaches every node.
        with SqliteSaver.from_conn_string(api_state.checkpoint_db) as checkpointer, session_scope(runtime.session_id):
            graph = build_session_graph(
                roles,
                checkpointer=checkpointer,
                concept_store=concept_store,
                resource_store=resource_store,
                candidate_factory=lambda seed: QueueCandidate(
                    runtime.emit, runtime.answers, runtime.cancelled, runtime.begin_turn
                ),
            )
            config = session_config(runtime.session_id)
            initial_state = None
            if not resume:
                assert isinstance(payload, StartSessionPayload)
                if metered:
                    # Stamp this run's baseline before the Diagnostic spends anything. The browser
                    # persists ONE Session id in localStorage and reuses it for every fresh start
                    # until the Candidate asks for a new one, so without a baseline the rail would
                    # charge each new interview for every interview that came before it.
                    begin_session_run(runtime.session_id)
                assert profile is not None  # built above, before the cap reservation (QA-08)
                carried = load_priors(api_state.ledger_db, payload.candidate_id, now=time.time())
                diagnostic = diagnose_or_degrade(
                    profile,
                    roles.diagnostic,
                    ledger_priors=carried.seed_means if carried else None,
                )
                initial_state = initial_session_state(
                    runtime.session_id,
                    diagnostic,
                    max_questions=payload.max_questions,
                    max_elapsed_seconds=payload.max_elapsed_seconds,
                    candidate_id=payload.candidate_id,
                    ledger_prior_mastery=carried.raw_mastery if carried else None,
                    language_mode=payload.language_mode,
                )
            runtime.emit(
                {
                    "type": "session_started",
                    "session_id": runtime.session_id,
                    "mode": runtime.mode,
                    "resumed": resume,
                }
            )
            final_state = _stream_graph(graph, initial_state, config, runtime, budget_stop=budget_stop)
        if final_state is not None:
            # Persist posteriors for a returning Candidate (0023); candidate_id rides in the state so a
            # resumed Session saves too. save_posteriors no-ops on an empty id. The Markdown is written
            # BEFORE the state enters the bounded RAM cache, so an evicted id always has its file.
            if final_state.get("status") == SessionStatus.COMPLETE.value:
                _persist_export(api_state, runtime.session_id, final_state)
                save_measured_posteriors(
                    api_state.ledger_db,
                    str(final_state.get("candidate_id", "")),
                    # NEW-17: only Skills this Session actually measured. `skill_states` holds a
                    # belief for every Skill from the Diagnostic's seed onward, so the old write
                    # persisted an unprobed self-claim as a measured posterior.
                    measured_skill_states(final_state),
                    now=time.time(),
                )
            _remember_completed(api_state, runtime.session_id, final_state)
            # Logged before the emit, not after: the emit is what hands control to the client, and a
            # record written afterwards races the browser (and the test) that is already reacting.
            logger.info("Session %r finished: status=%s", runtime.session_id, final_state.get("status"))
            runtime.emit({"type": "session_completed", "state": final_state})
    except SessionBudgetSuspended as err:
        # ADR 0005's third category: budget exhaustion. Its own branch, ABOVE the completion block —
        # a suspended Session must never emit session_completed or be persisted as if it finished.
        # The checkpoint is durable, so the UI's resume picks it up once the budget allows.
        logger.warning("Session %r suspended on a budget rail: %s", runtime.session_id, err)
        runtime.emit({"type": "session_error", "error": f"Session suspended: {err}"})
    except ProviderQuotaExhausted as err:
        # GH #119: the daily quota died mid-Session. Same structural reason as the branch above —
        # nothing completed, so nothing is persisted as complete; the checkpoint stays resumable.
        logger.warning("Session %r suspended on a dead provider quota: %s", runtime.session_id, err)
        # A quota that dies on the Diagnostic leaves no checkpoint; offering a resume would be a stall.
        next_step = (
            "Resuming re-tries the provider once."
            if _checkpoint_values(api_state, runtime.session_id)
            else "Nothing was checkpointed yet; start a new Session after the reset."
        )
        runtime.emit({"type": "session_error", "error": f"Session suspended: {err} {daily_reset_hint()} {next_step}"})
    except AccountingUnavailable as err:
        # M0a / F1: a metered call was refused because usage accounting is broken or unreconciled.
        # Its own branch for the same structural reason as the one above — nothing completed, so
        # nothing may be persisted as complete — but a different remedy, which the Candidate-facing
        # text has to carry honestly: this one waits on an operator, not on 00:00 UTC.
        logger.error("Session %r stopped on an accounting fault: %s", runtime.session_id, err)
        runtime.emit({"type": "session_error", "error": f"Session stopped: {err}"})
    except CandidateIntent as err:
        # ADR 0005 / issue 0017: the Candidate asked to stop (web cancel/disconnect). This is intent,
        # not an infrastructure failure — a distinct control-flow branch. The supervisor re-raises it
        # past the per-question failure-isolation net, so the in-flight question is never recorded as a
        # zero-evidence `failed` and the checkpoint stays resumable. Report it, don't score anything.
        logger.info("Session %r cancelled by Candidate intent: %s", runtime.session_id, err)
        runtime.emit({"type": "session_error", "error": f"Session cancelled: {err}"})
    except Exception as err:  # noqa: BLE001 - API boundary converts graph/provider failures to events
        logger.exception("Session %r failed", runtime.session_id)
        runtime.emit({"type": "session_error", "error": f"{type(err).__name__}: {err}"})
    finally:
        # Outside the state lock on purpose: this reads the checkpoint DB and appends to the ledger,
        # and `_claim_session_id` and the socket handler are both blocked while that lock is held.
        _release_unused_questions(api_state, runtime, reservation)
        with api_state.lock:
            runtime.run_finished = True
            # The socket closed while this thread was still running: the registration was left for
            # this thread to release, so a waiting reconnect can now proceed.
            if runtime.socket_closed and api_state.runtimes.get(runtime.session_id) is runtime:
                api_state.runtimes.pop(runtime.session_id, None)


def _release_unused_questions(
    api_state: WebApiState, runtime: RuntimeSession, reservation: tuple[str, int] | None
) -> None:
    """Hand back the questions this run reserved and can never ask (QA-08).

    Only a run that can never come back for them. A cancelled or SUSPENDED Session keeps a resumable
    checkpoint and a resume does not re-reserve — ``reserve_questions`` is on the ``not resume``
    branch — so releasing there would hand the resumed run its remaining questions off the books, and
    it would reopen the bypass the up-front reservation exists to close: a cap that only counts
    finished Sessions is beaten by abandoning them.

    So exactly two cases release. Nothing checkpointed at all: the run died before the graph wrote a
    thing (an invalid payload, a store that would not build, a quota that died on the Diagnostic) and
    the Candidate has already been told to start a new Session, not to resume this one. COMPLETE: the
    interview is over, and a question the Supervisor ended early on is never going to be asked.
    """
    if reservation is None:
        return
    identity, reserved = reservation
    try:
        values = _checkpoint_values(api_state, runtime.session_id)
        if not values:
            unused = reserved
        elif str(values.get("status", "")) == SessionStatus.COMPLETE.value:
            unused = reserved - int(values.get("question_count", 0))
        else:
            return  # resumable: the reservation is still owed to this Session
        if unused > 0:
            record_questions_released(identity, unused, session=runtime.session_id)
    except Exception:  # noqa: BLE001 - a refund must never mask the run's own outcome, or wedge the id
        logger.warning("could not release the question reservation for %r", runtime.session_id, exc_info=True)


def _unknown_session_message(session_id: str) -> str:
    """The web's half of the CLI's unknown-``--resume``-id refusal, in the same opening words (0019).

    Deliberately NOT the CLI string verbatim: ``--session-id`` is meaningless in a browser, and the
    CLI's hint lists every thread_id in the checkpoint DB plus the DB's path — one Candidate's socket
    must never be handed the ids of everyone else's Sessions.
    """
    return (
        f"No saved Session found for {session_id!r}. It was never started here, or its checkpoint "
        "has expired. Start a new Session from Setup — there is nothing to resume."
    )


def _checkpoint_values(api_state: WebApiState, session_id: str) -> Mapping[str, Any]:
    """A resumed Session's stored state, read BEFORE the graph is built.

    A resume payload carries only a mode, so everything the driver must know up front —
    ``language_mode`` for the embedder, ``max_questions`` for the budget rail — comes from here.
    Returns ``{}`` on any read failure: a missing checkpoint is the "unknown session" path, which
    the graph reports far better than a crash in here would.
    """
    try:
        with SqliteSaver.from_conn_string(api_state.checkpoint_db) as checkpointer:
            checkpoint = checkpointer.get(cast("Any", session_config(session_id)))
        raw: Mapping[str, Any] = cast("Mapping[str, Any]", checkpoint or {})
        return cast("Mapping[str, Any]", raw.get("channel_values") or {})
    except Exception:
        logger.warning("could not read the checkpoint for resumed Session %r", session_id, exc_info=True)
        return {}


def _session_language_mode(
    payload: StartSessionPayload | ResumeSessionPayload,
    resume: bool,
    checkpoint_values: Mapping[str, Any],
) -> str:
    """The Session's language mode, known BEFORE the graph is built (R-14).

    A fresh Session carries it on the start payload. A *resumed* one does not, so it has to come out
    of the checkpoint, or resuming a Vietnamese Session would silently rebuild its retrieval on the
    English embedder and rank near-randomly for the rest of the interview.
    """
    if not resume:
        return getattr(payload, "language_mode", DEFAULT_LANGUAGE_MODE)
    return str(checkpoint_values.get("language_mode") or DEFAULT_LANGUAGE_MODE)


def _persist_export(api_state: WebApiState, session_id: str, final_state: dict[str, Any]) -> None:
    """Write the completed Session's Markdown to disk so a restart cannot eat the report.

    Best-effort on purpose: the Candidate has just finished an interview, and a full disk or a
    read-only mount must not turn a completed Session into an error event. The in-memory copy still
    serves this process, and the failure is logged rather than raised.
    """
    try:
        export_session_markdown(final_state, export_path(api_state.exports_dir, session_id))
    except OSError:
        logger.exception("could not persist the Markdown export for Session %r", session_id)


def _stream_graph(
    graph,
    initial_state: Mapping[str, Any] | None,
    config: dict[str, Any],
    runtime: RuntimeSession,
    *,
    budget_stop: Callable[[Mapping[str, Any]], str | None] | None = None,
) -> dict:
    """Drive the graph, converting the two out-of-band stop conditions into typed signals.

    The budget rail sits next to the cancel check on purpose (R-25): raised HERE, outside the graph,
    it can never reach ``question_node``'s ``except Exception`` net and be recorded as a
    zero-evidence ``failed`` question — the corruption ADR 0005 forbids. It is the same shape as the
    cancel path rather than a fourth degrade path.
    """
    final_state: dict[str, Any] | None = None
    for event in graph.stream(initial_state, config, stream_mode="values"):
        if runtime.cancelled.is_set():
            raise CandidateInputUnavailable("Session was cancelled.")
        final_state = dict(event)
        runtime.emit({"type": "state_update", "state": final_state})
        # Checked AFTER the state goes out, exactly as the CLI prints the live update first: the
        # question the Candidate just resolved IS in the checkpoint, and a suspend that arrives with
        # no state carrying it looks to the UI like a crash that ate the last answer.
        if budget_stop is not None and (reason := budget_stop(final_state)):
            raise SessionBudgetSuspended(reason)
    if final_state is None:
        raise RuntimeError("Session graph produced no final state")
    return final_state
