"""The ``coach`` command line.

- ``coach diagnose`` (slice 0009): turn a Candidate profile into a Topic Plan and seeded priors.
- ``coach session`` (slice 0010): run/resume a multi-question Session through LangGraph + SqliteSaver.
- ``coach eval-harness`` (slice 0012): run held-out golden answers through the Evaluator.
- ``coach api`` (slice 0012): run the FastAPI/WebSocket backend for the React UI.
- ``coach ingest-concepts`` (slice 0007): fill a Chroma ``concepts`` collection with seed notes.
- ``coach forge`` (issue 0028): Writer + three ordered gates that queue new bank questions for
  human review under ``data/forge/``.

A bare ``coach`` prints the help and exits 2.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from . import telemetry
from .bank import BankError, load_pack
from .bench import (
    bench_passed,
    bias_warnings,
    load_bench_data,
    render_bench_report,
    repeatability_warnings,
    run_bench,
)
from .cli_parser import build_parser
from .cli_session import _print_study_plan
from .concepts import (
    BGE_SMALL_EN,
    E5_SMALL_MULTILINGUAL,
    SEED_CONCEPTS,
    ChromaConceptStore,
)
from .config import load_settings
from .diagnostic import CandidateProfile, diagnose_or_degrade
from .eval_harness import (
    GOLDEN_ANSWER_CASES,
    harness_passed,
    render_golden_answer_report,
    run_golden_answer_harness,
)
from .forge import MAX_DRAFTS, ForgeError, render_forge_report, run_forge, write_forge_outputs
from .llm import (
    UNKNOWN_PROVIDER,
    LLMClient,
    RoleClients,
    build_client,
    build_role_clients,
    ensure_role_clients,
    provider_label,
)
from .microloop import (
    DEFAULT_MAX_TURNS,
    CandidateIntent,
    InteractiveCandidate,
    ScriptedCandidate,
)
from .postmortem import (
    MAX_ELICITATION_QUESTIONS,
    PostmortemResult,
    export_postmortem_markdown,
    run_postmortem,
)
from .resources import build_resource_store
from .seeds import QUESTION_BANK
from .skill import POSTMORTEM_WEIGHT_RATIO, confidence_weight
from .supervisor import (
    DEFAULT_MAX_QUESTIONS,
)
from .usage import (
    WORST_CASE_TOKENS_PER_CALL,
    AccountingUnavailable,
    ProviderQuotaExhausted,
    accounting_block_reason,
    daily_question_cap,
    daily_reset_hint,
    daily_token_budget,
    estimated_session_tokens,
    ledger_path,
    metered_command_refusal_reason,
    reconcile_accounting,
    remaining_today,
    session_ceiling_multiple,
    session_scope,
    session_token_budget,
    sessions_for_day,
    usage_for_day,
    utc_date,
    worst_case_session_calls,
    worst_case_session_tokens,
)

# What every subcommand receives (ADR 0010): the per-role bundle from main(), a bare client when a
# test drives a command directly, or None on the offline path. ``ensure_role_clients`` normalizes.
type ClientArg = RoleClients | LLMClient | None


def _model_label(client: LLMClient) -> str:
    """The model actually behind ``client`` — report labels must name the real judge (ADR 0009a)."""
    return getattr(client, "model_name", "") or "unknown"


# The A/B audit (docs/audits/concept-retrieval-embedder-ab-2026-07-11.md) recommends the
# multilingual embedder for vn-mode practice; the default stays BGE because vectors are not
# portable across embedders — an existing --persist-dir collection must be re-ingested when
# switching. Only meaningful with --concept-store=chroma.
_CONCEPT_EMBEDDER_HELP = (
    "SentenceTransformer model for the Chroma concept store. Unset, it follows the Session's "
    f"language (R-14): vn/mixed use {E5_SMALL_MULTILINGUAL}, en uses {BGE_SMALL_EN}. BGE is "
    "English-only and collapses Vietnamese text onto a hub, so a vn Session retrieving with it "
    "ranks near-randomly. The persist dir is namespaced per embedder — vectors from different "
    "models do not mix."
)


def _parse_claim(raw: str) -> tuple[str, float]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("claims must be formatted as skill=score, e.g. mlops=4")
    skill, value = raw.split("=", 1)
    try:
        score = float(value)
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"claim score must be numeric: {raw!r}") from err
    return skill.strip(), score


# What a "Session's worth" is for a batch command, in the ledger's own measured units. Each is a
# FLOOR on what the day must be able to fund, never a ceiling on what the run can spend — a
# ceiling-sized start gate refuses runs the day could have paid for.
#   eval-harness : one judgment per golden case at the largest call ever measured.
#   postmortem   : MAX_ELICITATION_QUESTIONS turns + reconstruction + study plan.
#   forge        : ~4 live calls per draft that survives to the admission gate, x --n.
HARNESS_MIN_BUDGET_TOKENS = len(GOLDEN_ANSWER_CASES) * WORST_CASE_TOKENS_PER_CALL
POSTMORTEM_MIN_BUDGET_TOKENS = (MAX_ELICITATION_QUESTIONS + 2) * WORST_CASE_TOKENS_PER_CALL
FORGE_MIN_BUDGET_TOKENS_PER_DRAFT = 4 * WORST_CASE_TOKENS_PER_CALL


def _refuse_metered_start(
    client: LLMClient, *, work: str, needed: int, allow_overspend: bool = False, hint: str = ""
) -> str | None:
    """The start gate every metered command shares (NEW-10): the refusal to print, or None.

    `coach session` has had one since R-25; the batch commands had none, so `coach bench --k 3` —
    ~210,000 tokens, about 8 default Sessions of the shared allowance, and the two heaviest sweeps in
    the ledger are 455 and 778 calls — could drain the daily allowance out from under a Candidate
    mid-interview and suspend their Session (ADR 0005).

    A client with no provider identity (demo, test fakes) spends nobody's allowance, so the rail is
    inert for it: the same UNKNOWN_PROVIDER exemption `_cmd_session` grants.

    ``allow_overspend`` (the `--ignore-budget` flag) zeroes only the ARITHMETIC comparison, because
    that number is our own count and can be wrong — an operator who knows their real allowance is
    larger must always be able to re-bench a judge (ADR 0009). It deliberately cannot buy a working
    ledger or a live quota: the accounting-fault and dead-quota refusals still fire.
    """
    provider = provider_label(client)
    if provider == UNKNOWN_PROVIDER:
        return None
    reason = metered_command_refusal_reason(provider, work=work, needed=0 if allow_overspend else needed)
    if reason is None:
        return None
    sessions = max(1, round(needed / estimated_session_tokens(DEFAULT_MAX_QUESTIONS)))
    return (
        f"{reason} At ~{needed:,} tokens this run is worth about {sessions} default "
        f"{DEFAULT_MAX_QUESTIONS}-question Session(s) of the same allowance.{hint}"
    )


def _cmd_diagnose(client: ClientArg, args: argparse.Namespace) -> int:
    profile = CandidateProfile(
        target_role=args.target_role,
        target_companies=tuple(args.company),
        claimed_skills=dict(args.claim),
    )
    roles = ensure_role_clients(client)
    if roles is not None and (
        refusal := _refuse_metered_start(roles.diagnostic, work="a Diagnostic", needed=estimated_session_tokens(0))
    ):
        print(f"Refusing to run `coach diagnose`: {refusal}", file=sys.stderr)
        return 2
    with session_scope("diagnose"):
        result = diagnose_or_degrade(profile, roles.diagnostic if roles is not None else None)
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


def _print_postmortem(result: PostmortemResult) -> None:
    print(f"=== POST-MORTEM DEBRIEF ({result.candidate_id}) — {len(result.transcript)} question(s) elicited ===")
    print(
        f"\n=== RECONSTRUCTED SCORECARD (second-hand evidence, fused at {POSTMORTEM_WEIGHT_RATIO:g}x live weight) ==="
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
    _print_study_plan(result.study_plan, result.study_plan_error, title="REGENERATED STUDY PLAN")


def _cmd_postmortem(client: ClientArg, args: argparse.Namespace) -> int:
    roles = ensure_role_clients(client)
    if roles is None:
        raise RuntimeError("postmortem requires an LLM client")
    if refusal := _refuse_metered_start(
        roles.diagnostic, work="a post-mortem debrief", needed=POSTMORTEM_MIN_BUDGET_TOKENS
    ):
        print(f"Refusing to run `coach postmortem`: {refusal}", file=sys.stderr)
        return 2
    resource_store = build_resource_store(seed=not args.no_seed_resources)
    candidate = ScriptedCandidate(args.scripted_recollection) if args.scripted_recollection else InteractiveCandidate()
    try:
        result = run_postmortem(
            roles.diagnostic,
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
            "Post-mortem aborted; the partial recollection was discarded and the Skill ledger was not touched.",
            file=sys.stderr,
        )
        return 2
    _print_postmortem(result)
    if args.export_markdown:
        path = export_postmortem_markdown(result, args.export_markdown)
        print(f"\nExported post-mortem Markdown to {path}")
    return 0


def _cmd_pack_lint(client: ClientArg, args: argparse.Namespace) -> int:
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


def _cmd_pack(client: ClientArg, args: argparse.Namespace) -> int:
    print("usage: coach pack lint <dir>", file=sys.stderr)
    return 2


def _cmd_eval_harness(client: ClientArg, args: argparse.Namespace) -> int:
    roles = ensure_role_clients(client)
    if roles is None:
        raise RuntimeError("eval-harness requires an LLM client")
    if refusal := _refuse_metered_start(
        roles.judge,
        work=f"the {len(GOLDEN_ANSWER_CASES)}-case golden-answer harness",
        needed=HARNESS_MIN_BUDGET_TOKENS,
    ):
        print(f"Refusing to run `coach eval-harness`: {refusal}", file=sys.stderr)
        return 2
    with session_scope("eval-harness"):
        results = run_golden_answer_harness(roles.judge)
    print(render_golden_answer_report(results))
    return 0 if harness_passed(results) else 1


# One full sweep of the case list measures ~50–70k tokens including retries; the gate runs k of
# them, so the preflight scales with k. Starting a run with less than this in the day's budget risks
# dying mid-run on insufficient_quota with a half-written report.
BENCH_MIN_BUDGET_TOKENS_PER_PASS = 70_000


def _usage_delta(before: dict[str, dict[str, int]], after: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """Per-provider token deltas across one run — ALL providers, so failover spend counts too.

    Clamped at zero per stat: a run crossing UTC midnight diffs two different day buckets, and a
    negative "run cost" would be nonsense in the report.
    """
    stats = ("prompt", "completion", "total", "calls")
    delta: dict[str, dict[str, int]] = {}
    for prov in before.keys() | after.keys():
        b, a = before.get(prov, {}), after.get(prov, {})
        row = {key: max(0, a.get(key, 0) - b.get(key, 0)) for key in stats}
        if any(row.values()):
            delta[prov] = row
    return delta


def _cmd_bench(client: ClientArg, args: argparse.Namespace) -> int:
    roles = ensure_role_clients(client)
    if roles is None:
        raise RuntimeError("bench requires an LLM client")
    # The bench measures the JUDGE role (ADR 0009c): with a role override in play, the pinned judge
    # client — not the session router — is what runs, and the report is labeled with its identity.
    judge = roles.judge
    provider = provider_label(judge)
    k = max(1, int(args.k))
    budget = daily_token_budget()
    usage_before = usage_for_day()
    left = max(0, budget - usage_before.get(provider, {}).get("total", 0))
    needed = BENCH_MIN_BUDGET_TOKENS_PER_PASS * k
    print(f"Daily budget check ({provider}): ~{left:,} of {budget:,} tokens left by our count.")
    if refusal := _refuse_metered_start(
        judge,
        work=f"a {k}-sweep calibration bench",
        needed=needed,
        allow_overspend=args.ignore_budget,
        hint=(" Pass --ignore-budget to spend it deliberately (that cannot override a broken ledger or a dead quota)."),
    ):
        # Refused, not warned (NEW-10): the warning let a `--k 3` sweep drain the day under a live
        # Session. Exit 2 is neither the gate's green (0) nor its red (1), and NO report is written,
        # so a refusal can never be mistaken for a judge verdict (ADR 0009).
        print(f"Refusing to run `coach bench`: {refusal}", file=sys.stderr)
        return 2
    if args.ignore_budget and left < needed:
        print(
            f"WARNING (--ignore-budget): under {needed:,} tokens left (k={k} sweeps) — a full bench "
            "run may die mid-run on insufficient_quota, and any Session running now may suspend.",
            file=sys.stderr,
        )
    telemetry_before = telemetry.snapshot()
    data = load_bench_data(args.cases or None)
    if k > 1:
        print(f"Running {k} sweeps of {len(data.cases)} cases (gate = median-of-k, ADR 0009d)...")
    results = run_bench(judge, data.cases, k=k)
    telemetry_after = telemetry.snapshot()
    usage_after = usage_for_day()
    run_usage = _usage_delta(usage_before, usage_after)
    report = render_bench_report(
        results,
        anchors=data.anchors,
        provider=provider,
        model=_model_label(judge),
        date=utc_date(),
        telemetry_delta=telemetry.delta(telemetry_before, telemetry_after),
        token_usage=run_usage,
    )
    out = Path(args.out) if args.out else Path("docs/audits") / f"calibration-bench-{utc_date()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    within = sum(1 for r in results if r.within_band)
    spent = sum(stats["total"] for stats in run_usage.values())
    left_after = max(0, budget - usage_after.get(provider, {}).get("total", 0))
    print(
        f"Bench: {within}/{len(results)} cases within band. Report written to {out}. "
        f"Run cost ~{spent:,} tokens; ~{left_after:,} left today."
    )
    for warning in bias_warnings(results):
        # Drift warning, not a gate: the run stays green, but a systematically drifting dimension
        # deserves a re-anchor pass before it starts costing in-band cases.
        print(f"BIAS TRIPWIRE: {warning}", file=sys.stderr)
    for warning in repeatability_warnings(results):
        # Also not a gate (the median is the verdict) — this is the signal that a case is one
        # provider nudge from flipping, which no single-run report can show (GH #92).
        print(f"REPEATABILITY: {warning}", file=sys.stderr)
    return 0 if bench_passed(results) else 1


def _cmd_usage(client: ClientArg, args: argparse.Namespace) -> int:
    """Today's client-side token ledger — the daily free-tier budget is invisible to the API."""
    ledger = ledger_path()
    if getattr(args, "reconcile", False):
        # M0a / F1: replay the rows a failed write parked, then clear the fault. Explicitly an
        # operator action: the rail refuses metered work until someone has looked, precisely because
        # the alternative — clearing itself — is indistinguishable from counting the lost spend as 0.
        try:
            print(reconcile_accounting())
        except OSError as err:
            print(
                f"Could not reconcile: {type(err).__name__}: {err}. Nothing was replayed for the ledger "
                f"at {ledger}, so the held rows stay held and metered calls stay refused.",
                file=sys.stderr,
            )
            return 2
    # Printed before the totals, not after: every number below is arithmetic over this file, so a
    # reader who does not know the file is broken would read a full budget off an empty ledger.
    if blocked := accounting_block_reason():
        print(f"ACCOUNTING: {blocked}\n", file=sys.stderr)
    else:
        print(f"Accounting healthy (ledger: {ledger}).")
    totals = usage_for_day()
    if not totals:
        print(f"No recorded usage today (ledger: {ledger}).")
    for provider, stats in sorted(totals.items()):
        print(
            f"{provider}: {stats['total']:,} tokens across {stats['calls']} call(s) "
            f"({stats['prompt']:,} prompt + {stats['completion']:,} completion)"
        )
    per_session = sessions_for_day()
    if attributed := {sid: spent for sid, spent in per_session.items() if sid}:
        # R-25: which Session id spent what. "Per id", not "per run", and labeled as such — an id is
        # reused across runs, which is the whole reason the rail measures a per-run delta instead.
        # Unattributed rows are batch tools (bench, forge, one-off commands), not a Session that
        # lost its label — they are shown apart rather than hidden.
        print("\nPer Session id today (all runs on that id):")
        for session_id, spent in sorted(attributed.items()):
            print(f"  {session_id}: {spent:,} tokens")
    if loose := per_session.get(""):
        print(f"  unattributed (bench/forge/one-off): {loose:,} tokens")
    budget = daily_token_budget()
    settings = load_settings()
    primary = settings.primary_provider
    print(f"\nPrimary ({primary}): ~{remaining_today(primary):,} of {budget:,} daily tokens left by our count.")
    default_calls = worst_case_session_calls(DEFAULT_MAX_QUESTIONS, DEFAULT_MAX_TURNS)
    print(
        f"Per-run budget for a default {DEFAULT_MAX_QUESTIONS}x{DEFAULT_MAX_TURNS} Session: "
        f"{session_token_budget(max_questions=DEFAULT_MAX_QUESTIONS, max_turns=DEFAULT_MAX_TURNS):,} tokens "
        f"({session_ceiling_multiple(DEFAULT_MAX_TURNS)}x the "
        f"~{estimated_session_tokens(DEFAULT_MAX_QUESTIONS):,} a measured Session runs; a full retry "
        f"storm would be {worst_case_session_tokens(DEFAULT_MAX_QUESTIONS, DEFAULT_MAX_TURNS):,} "
        f"over {default_calls} worst-case provider calls)."
    )
    print(f"Daily question cap: {daily_question_cap()} question(s) per token identity.")
    return 0


def _cmd_forge(client: ClientArg, args: argparse.Namespace) -> int:
    roles = ensure_role_clients(client)
    if roles is None:
        raise RuntimeError("forge requires an LLM client")
    # The Forge's admission gate IS the live Evaluator, so the whole run rides the judge role
    # client (a forge admission scored by a non-bench-validated model would be meaningless).
    judge = roles.judge
    # Same preflight as the bench: gate 3 spends ~4+ calls per surviving draft, and a forge run
    # started blind into a nearly-dead quota dies mid-queue with a half-written review file.
    provider = provider_label(judge)
    print(
        f"Daily budget check ({provider}): ~{remaining_today(provider):,} of "
        f"{daily_token_budget():,} tokens left by our count."
    )
    if refusal := _refuse_metered_start(
        judge,
        work=f"a {args.n}-draft forge batch",
        needed=args.n * FORGE_MIN_BUDGET_TOKENS_PER_DRAFT,
        allow_overspend=args.ignore_budget,
        hint=" Pass --ignore-budget to spend it deliberately.",
    ):
        print(f"Refusing to run `coach forge`: {refusal}", file=sys.stderr)
        return 2
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
        run = run_forge(judge, args.skill, args.n, concepts=concepts, existing_prompts=corpus)
    except ForgeError as err:
        # Pipeline failure (the Writer produced nothing usable) — distinct from an honest
        # zero-admissions run, which still exits 0 with a full report (0 admitted is information).
        print(f"Forge FAILED: {err}", file=sys.stderr)
        return 1
    model = _model_label(judge)
    date = utc_date()
    queue_path = Path(args.out) if args.out else Path(args.queue_dir) / f"review-queue-{date}.yaml"
    queue, report = write_forge_outputs(run, queue_path=queue_path, provider=str(provider), model=model, date=date)
    print(render_forge_report(run, provider=str(provider), model=model, date=date))
    admitted = sum(1 for outcome in run.outcomes if outcome.admitted)
    print(
        f"Forge: {admitted}/{len(run.outcomes)} draft(s) admitted. Review queue written to {queue}; report to {report}."
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


def _cmd_ingest_concepts(client: ClientArg, args: argparse.Namespace) -> int:
    store = ChromaConceptStore.create(persist_dir=args.persist_dir, embedding_model=args.concept_embedder)
    count = store.ingest(SEED_CONCEPTS)
    print(
        f"Ingested {count} concept notes into Chroma collection at {args.persist_dir!r} using {args.concept_embedder}."
    )
    return 0


def _cmd_api(client: ClientArg, args: argparse.Namespace) -> int:
    import uvicorn

    # Logging for the server lives in `web_api.configure_session_logging`, not here: with `--reload`
    # uvicorn serves from a spawned subprocess that never runs this function, so anything configured
    # at this point is simply absent from the process that handles requests — which is where R-26's
    # per-call `llm-call provider=... model=... outcome=...` trace has to be visible for a silent
    # judge failover to be diagnosable at all. Uvicorn keeps its own log config (banner, access log).
    # For the same reason `--log-file` is handed over as an env var: it is the only channel that
    # crosses the spawn boundary into the process that actually writes the records. Set it before
    # web_api is imported below, since that import is what installs the file handler in-process.
    if args.log_file:
        os.environ["COACH_LOG_FILE"] = args.log_file
    # R-12: web_api runs the same guard at import — that is the copy that covers
    # `uvicorn interview_coach.web_api:app --workers 4`, which never reaches this function. Repeating
    # it here is only about the message: `coach api` is the image's CMD, and a module-scope raise
    # would otherwise reach the operator as a traceback out of uvicorn's app loader. The import
    # itself is not extra work — `uvicorn.run` on an import string loads the same module a few lines
    # down, in this same process (`config.load_app()`, reload or not).
    from .web_ops import guard_single_worker
    from .web_protocol import WS_MAX_FRAME_BYTES

    try:
        # argv=[] on purpose: `coach api` has no --workers flag, so argparse has already rejected
        # one, and sniffing this process's argv here would only read someone else's command line.
        guard_single_worker(argv=[])
    except RuntimeError as err:
        print(str(err), file=sys.stderr)
        return 2
    uvicorn.run(
        "interview_coach.web_api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        # Not a tuning knob: uvicorn's 16 MiB default is the only ceiling on an inbound Session
        # frame, because nginx's `client_max_body_size` does not apply once the socket is upgraded.
        ws_max_size=WS_MAX_FRAME_BYTES,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
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
        return _dispatch(args, None)

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
        return _dispatch(args, None)

    client = build_client(settings)
    # ADR 0010: commands receive the per-role bundle. With no ROLE_* overrides this is the same
    # router object for every role except the judge, which is pinned to its provider client
    # (ADR 0009a — judge failover must never swap the model mid-run).
    return _dispatch(args, build_role_clients(settings, client))


def _dispatch(args: argparse.Namespace, client: ClientArg) -> int:
    """Run the subcommand; the two typed operator stops exit 2 with their remedy, never a traceback.

    ``session`` handles both with richer, resume-aware text before they reach here; every other
    command (diagnose, postmortem, bench, forge, eval-harness) gets the same honest stop.
    """
    try:
        return args.func(client, args)
    except ProviderQuotaExhausted as err:
        print(f"{err} {daily_reset_hint()}", file=sys.stderr)
        return 2
    except AccountingUnavailable as err:
        print(str(err), file=sys.stderr)
        return 2
