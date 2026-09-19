"""The `coach` argparse table: every subcommand, flag, default and help string.

Split out of ``cli`` under GH #124. One reason to change: the command-line surface. It was 310 lines
inside ``main``, 22% of the file, sitting between the handlers it wires and the dispatch that runs
them — so every flag edit and every handler edit touched the same function.

The handlers stay in ``cli``. ``build_parser`` reaches them through a deferred import, which is also
what keeps a test that monkeypatches a handler before calling ``main()`` working: the table is built
inside ``main``, so it picks up whatever ``cli._cmd_x`` is at that moment.
"""

from __future__ import annotations

import argparse

from .bench import BENCH_DEFAULT_K
from .diagnostic import SKILLS
from .forge import MAX_DRAFTS
from .language import DEFAULT_LANGUAGE_MODE, LANGUAGE_MODES
from .microloop import DEFAULT_MAX_TURNS
from .supervisor import DEFAULT_MAX_ELAPSED_SECONDS, DEFAULT_MAX_QUESTIONS


def build_parser() -> argparse.ArgumentParser:
    """The whole `coach` command line. Pure construction — it parses nothing and runs nothing."""
    # Imported here rather than at module scope: `cli` imports this module, so a top-level import
    # back would be a cycle at interpreter start.
    from . import cli, cli_session

    parser = argparse.ArgumentParser(description="Adaptive Interview Coach.")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show provider and internal INFO logs. By default the CLI hides noisy demo logs.",
    )
    sub = parser.add_subparsers(dest="command")

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
        type=cli._parse_claim,
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
    diag_parser.set_defaults(func=cli._cmd_diagnose, requires_llm=False, prefers_llm=True)

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
        type=cli._parse_claim,
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
        choices=["auto", "memory", "chroma"],
        default="auto",
        help=(
            "Concept store used by lookup_concept during Follow-up generation. 'auto' (default) "
            "uses Chroma wherever the rag extras are installed and warns loudly when falling back "
            "to the keyword ranker, so the measured retrieval path is also the default one."
        ),
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
        "--concept-embedder",
        default=None,
        help=cli._CONCEPT_EMBEDDER_HELP,
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
    session_parser.set_defaults(func=cli_session._cmd_session, requires_llm=True)

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
        "--no-seed-resources",
        action="store_true",
        help="Do not upsert the built-in learning resources before planning.",
    )
    pm_parser.add_argument(
        "--export-markdown",
        help="Write the post-mortem debrief (scorecard, ledger delta, regenerated plan) to this Markdown path.",
    )
    pm_parser.set_defaults(func=cli._cmd_postmortem, requires_llm=True)

    harness_parser = sub.add_parser("eval-harness", help="Slice 0012: run Evaluator golden-answer checks")
    harness_parser.set_defaults(func=cli._cmd_eval_harness, requires_llm=True)

    usage_parser = sub.add_parser("usage", help="Show today's token spend per provider (client-side daily ledger)")
    usage_parser.add_argument(
        "--reconcile",
        action="store_true",
        help=(
            "Replay the ledger rows a failed write parked beside the ledger, then clear the "
            "accounting fault that is refusing metered calls (M0a). Fix the path first."
        ),
    )
    usage_parser.set_defaults(func=cli._cmd_usage, requires_llm=False)

    bench_parser = sub.add_parser("bench", help="Issue 0022: bilingual Judge calibration bench")
    bench_parser.add_argument("--cases", default="", help="Path to a cases YAML (default: data/bench/cases.yaml).")
    bench_parser.add_argument(
        "--k",
        type=int,
        default=BENCH_DEFAULT_K,
        help=(
            f"Runs per case; the gate judges the MEDIAN (default: {BENCH_DEFAULT_K}). One draw of a "
            "stochastic judge is not a measurement — see ADR 0009 addendum (d). Use --k 1 for a "
            "cheap indicative run, never to gate a merge."
        ),
    )
    bench_parser.add_argument(
        "--out", default="", help="Report output path (default: docs/audits/calibration-bench-<date>.md)."
    )
    bench_parser.add_argument(
        "--ignore-budget",
        action="store_true",
        help=(
            "Run even when today's budget cannot fund the sweep. The daily budget is OUR count, not "
            "the provider's, so an operator re-benching a judge must always be able to spend "
            "deliberately (ADR 0009). Loud, never silent; it cannot override a broken ledger or a "
            "dead quota."
        ),
    )
    bench_parser.set_defaults(func=cli._cmd_bench, requires_llm=True)

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
        type=cli._forge_batch_size,
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
    forge_parser.add_argument(
        "--ignore-budget",
        action="store_true",
        help=(
            "Run even when today's budget cannot fund the batch. Loud, never silent; it cannot "
            "override a broken ledger or a dead quota."
        ),
    )
    forge_parser.set_defaults(func=cli._cmd_forge, requires_llm=True)

    pack_parser = sub.add_parser("pack", help="Issue 0025: manage external content packs")
    pack_parser.set_defaults(func=cli._cmd_pack, requires_llm=False)
    pack_sub = pack_parser.add_subparsers(dest="pack_command")
    lint_parser = pack_sub.add_parser("lint", help="Validate a pack directory (fail-loud, non-zero on violation)")
    lint_parser.add_argument("pack_dir", help="Path to the pack directory to validate.")
    lint_parser.set_defaults(func=cli._cmd_pack_lint, requires_llm=False)

    ingest_parser = sub.add_parser("ingest-concepts", help="Slice 0007: seed the Chroma concepts collection")
    ingest_parser.add_argument("--persist-dir", default=".chroma", help="Chroma persistence directory.")
    ingest_parser.add_argument(
        "--concept-embedder",
        default=None,
        help=cli._CONCEPT_EMBEDDER_HELP,
    )
    ingest_parser.set_defaults(func=cli._cmd_ingest_concepts, requires_llm=False)

    api_parser = sub.add_parser("api", help="Slice 0012: run the FastAPI WebSocket backend")
    api_parser.add_argument("--host", default="127.0.0.1")
    api_parser.add_argument("--port", type=int, default=8000)
    api_parser.add_argument("--reload", action="store_true")
    api_parser.add_argument(
        "--log-file",
        default="",
        help=(
            "Also write the server log (session lifecycle + the per-call `llm-call` trace) to this "
            "file, rotating at 10 MB × 5. Default: stderr only, which a container restart discards."
        ),
    )
    api_parser.set_defaults(func=cli._cmd_api, requires_llm=False)

    return parser
