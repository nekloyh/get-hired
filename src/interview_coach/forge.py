"""Question Forge: a Writer plus three ordered gates that queue new bank questions (issue 0028, GH #29).

Attacks the thin-bank problem from the supply side. ``coach forge --skill X --n 5`` runs a
hand-rolled plain-Python pipeline (ADR 0004 — no LangGraph below the Session layer) of single-shot
``chat_json`` agents (ADR 0003 — tool-calling stays confined to the Interviewer):

1. **Writer** — one structured call drafting candidate questions grounded in the Skill's concept
   notes.
2. **Gate 1 — contract** (cheap, offline): each draft must satisfy the exact bank/pack contract,
   reusing :func:`bank.validate_question` so "valid" is defined once (ADR 0008).
3. **Gate 2 — novelty** (cheap, offline): token-overlap duplicate detection against every existing
   bank/pack prompt, with a ``similarity_fn`` seam for an embedding-based ranker.
4. **Gate 3 — admission** (expensive, live): generate a strong/weak answer pair and require the
   Evaluator to *separate* them into the bench's bands, reusing the golden-answer machinery
   (issues 0012/0022). A question the judge cannot discriminate on is a bad question.

Survivors land in a review-queue YAML under ``data/forge/`` that a human merges by hand — nothing
ever enters ``data/questions.yaml`` or a pack automatically (the import-time bank load makes a bad
auto-merge brick the whole package, so the human promotion gate is a hard invariant). Every
rejection records which gate killed it and why, so gate ordering and yield are measurable.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel

from .bank import BankError, validate_question
from .concepts import SEED_CONCEPTS, ConceptNote
from .eval_harness import GoldenAnswerCase, GoldenAnswerResult, run_golden_answer_harness
from .llm import LLMClient, Message, StructuredOutputError
from .rubric import TECHNICAL_DIMENSIONS
from .seeds import QUESTION_BANK, SeedQuestion

logger = logging.getLogger(__name__)

# Hard cap on --n. Gate 3 spends ~2 answer-generation + 2 evaluate() calls per surviving draft (and
# each evaluate() is 1–4 chat calls worst case: retry, self-critique, evidence degrade), while the
# LLM stack has NO rate-limit/backoff logic anywhere — batch size is the only free-tier budget rail.
MAX_DRAFTS = 10

# Gate 2 near-duplicate threshold on token-set Jaccard similarity (same ASCII tokenizer as
# concepts.InMemoryConceptStore). Measured over the shipped corpus (42 bank + 20 FPT-pack prompts),
# the most similar pair of *distinct* questions scores 0.478 while a verbatim copy scores 1.0 —
# 0.6 sits above every legitimate pair with margin yet still catches light rephrasings. Calibrated
# for Jaccard only: an embedding ``similarity_fn`` needs its own threshold (BGE cosine of unrelated
# text already sits near 0.6).
NOVELTY_SIMILARITY_THRESHOLD = 0.6

# Gate 3 admission bands — the same thresholds bench.BenchCase derives is_strong/is_weak from
# (expected_min >= 3.5 / expected_max <= 3.0), so "strong band" and "weak band" mean one thing
# across the whole eval stack.
STRONG_BAND = (3.5, 5.0)
WEAK_BAND = (1.0, 3.0)

# Gate names — the rejection attribution vocabulary the run report and tests key on.
GATE_CONTRACT = "contract"
GATE_NOVELTY = "novelty"
GATE_ADMISSION = "admission"

# Gate 1 validates the full bank contract, but answers are generated only at gate 3 (the issue's
# whole point is cheap-before-expensive ordering), so the contract check runs with this placeholder
# in the required non-empty ``answers`` slot. The real answers land in the review queue, whose
# round-trip through the same validator is pinned by tests.
_GATE1_PLACEHOLDER_ANSWER = "(answers are generated at gate 3 — placeholder for the contract check)"


class ForgeError(RuntimeError):
    """The forge pipeline itself failed (e.g. the Writer produced nothing usable).

    Distinct from a draft rejection: rejections are results (errors-as-results, like
    ``bench.run_bench``), while this aborts the run — the CLI maps it to exit 1.
    """


# --- typed models -------------------------------------------------------------------------------


class QuestionDraft(BaseModel):
    """One Writer draft: exactly the fields a bank question needs, minus the answers.

    Deliberately loose on semantics (``difficulty`` bounds, rubric dimension names, concept-id
    existence): those rules belong to the shared bank validator at gate 1, so a bad value becomes a
    recorded contract rejection instead of a burned Writer retry — and the semantics are never
    re-implemented here.
    """

    question: str
    difficulty: int
    rubric_weights: dict[str, float]
    expected_concepts: list[str]
    follow_up_seeds: list[str]


class QuestionDraftSet(BaseModel):
    """The Writer's single structured reply."""

    drafts: list[QuestionDraft]


class AnswerPair(BaseModel):
    """Gate 3's admission-test answers for one draft: one strong, one weak."""

    strong_answer: str
    weak_answer: str


@dataclass(frozen=True)
class GateRejection:
    """Which gate killed a draft, and the named reason — the report's attribution unit."""

    gate: str  # GATE_CONTRACT | GATE_NOVELTY | GATE_ADMISSION
    reason: str


@dataclass
class DraftOutcome:
    """Everything the run report needs about one draft's trip through the gates."""

    draft: QuestionDraft
    validated: SeedQuestion | None = None  # set once gate 1 passes
    rejection: GateRejection | None = None
    # Gate 2 evidence: questions have no id, so the nearest neighbour is recorded by its prompt.
    nearest_question: str | None = None
    nearest_similarity: float | None = None
    # Gate 3 evidence.
    strong_answer: str | None = None
    weak_answer: str | None = None
    strong_score: float | None = None
    weak_score: float | None = None

    @property
    def admitted(self) -> bool:
        """A draft is admitted only by surviving every gate — the gates run in order, so any
        non-rejected outcome of a completed run went through all three."""
        return self.rejection is None


@dataclass(frozen=True)
class AdmissionOutcome:
    """Gate 3's verdict plus the generated answers/scores (recorded even on rejection)."""

    rejection: GateRejection | None
    strong_answer: str | None = None
    weak_answer: str | None = None
    strong_score: float | None = None
    weak_score: float | None = None


@dataclass
class ForgeRun:
    """One completed forge pipeline run over a batch of drafts."""

    skill: str
    requested: int
    outcomes: list[DraftOutcome]


# --- Writer (one chat_json call, ADR 0003: single-shot, no tools) --------------------------------

WRITER_SYSTEM_PROMPT = (
    "You are the Writer in a Question Forge for mock technical interviews. You draft candidate "
    "interview questions for ONE Skill, grounded strictly in the concept notes provided. You only "
    "draft questions — you never score answers and you never talk to a candidate.\n\n"
    "Rules:\n"
    "- Ground every question in the provided concept notes. 'expected_concepts' may ONLY contain "
    "ids copied from that list.\n"
    "- 'rubric_weights' may only use the dimension names listed in the request. Weights are >= 0 "
    "and at least one must be > 0; a weight of 0 disables that dimension. NEVER use "
    "'english_delivery' — it is Session state, not question content.\n"
    "- 'difficulty' is an integer on the 1–5 scale.\n"
    "- 'follow_up_seeds' lists 2–3 short probe starters an interviewer could push with.\n"
    "- Do NOT write any answers. Answers are generated later, only for drafts that survive the "
    "cheap gates.\n"
    "- Each question must be self-contained, specific, and clearly distinct from the others in the "
    "batch and from standard textbook phrasings.\n"
    "- Respond with a single JSON object only — no prose, no code fences."
)

_WRITER_SCHEMA_HINT = (
    '{"drafts": [{"question": "<prompt>", "difficulty": <1-5>, '
    '"rubric_weights": {"<dimension>": <weight>, ...}, '
    '"expected_concepts": ["<concept id>", ...], '
    '"follow_up_seeds": ["<probe starter>", ...]}, ...]}'
)


def _writer_messages(skill: str, concepts: Sequence[ConceptNote], n: int) -> list[Message]:
    notes = "\n".join(f"- {note.id}: {note.title}" for note in concepts)
    user = (
        f"SKILL: {skill}\n\n"
        f"Draft exactly {n} candidate interview question(s) for this Skill.\n\n"
        f"CONCEPT NOTES (the ONLY valid 'expected_concepts' ids):\n{notes}\n\n"
        f"RUBRIC DIMENSIONS (the only valid 'rubric_weights' keys): {', '.join(TECHNICAL_DIMENSIONS)}\n\n"
        f"Return JSON shaped like:\n{_WRITER_SCHEMA_HINT}"
    )
    return [
        {"role": "system", "content": WRITER_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def draft_questions(
    client: LLMClient, skill: str, concepts: Sequence[ConceptNote], n: int
) -> tuple[QuestionDraft, ...]:
    """The Writer: one structured call producing up to ``n`` typed drafts.

    A schema-invalid reply burns exactly one retry (``max_retries=1``, the repo-wide chat_json
    budget) before :class:`StructuredOutputError` propagates to the caller.
    """

    def check_nonempty(draft_set: QuestionDraftSet) -> None:
        if not draft_set.drafts:
            raise ValueError("'drafts' must contain at least one question draft")

    draft_set = client.chat_json(
        _writer_messages(skill, concepts, n),
        QuestionDraftSet,
        validators=[check_nonempty],
        max_retries=1,
    )
    # An over-producing model is truncated, never indulged: every extra draft that survives to
    # gate 3 costs ~4+ live calls, so n is a hard budget, not a suggestion.
    return tuple(draft_set.drafts[:n])


# --- Gate 1: contract (reuses the shared bank validator) -----------------------------------------


def contract_gate(
    draft: QuestionDraft,
    *,
    skill: str,
    concept_ids: set[str],
    seen_prompts: set[str],
    where: str,
) -> tuple[SeedQuestion | None, GateRejection | None]:
    """Gate 1: the exact rules ``bank.py``/pack-lint enforce, applied to one draft.

    Delegates to :func:`bank.validate_question` (unknown/english_delivery rubric dimensions, weight
    rules, difficulty range, expected_concepts existence, duplicate prompts within the batch via
    ``seen_prompts``) so the contract is never re-implemented. Adds the shipped bank's
    follow_up_seeds convention, which the loader leaves optional but the Writer must honour.
    """
    raw = {
        "question": draft.question,
        "difficulty": draft.difficulty,
        "rubric": {"weights": draft.rubric_weights},
        "answers": [_GATE1_PLACEHOLDER_ANSWER],
        "expected_concepts": draft.expected_concepts,
        "follow_up_seeds": draft.follow_up_seeds,
    }
    try:
        validated = validate_question(
            raw, skill=skill, concept_ids=concept_ids, seen_questions=seen_prompts, where=where
        )
    except BankError as err:
        return None, GateRejection(gate=GATE_CONTRACT, reason=str(err))
    if not validated.follow_up_seeds:
        # Optional in the loader, mandatory here: every shipped bank question carries probe starters
        # (pinned by test_bank), so a draft without them is not mergeable content.
        return None, GateRejection(
            gate=GATE_CONTRACT, reason=f"{where}: 'follow_up_seeds' must be a non-empty list of probe starters"
        )
    return validated, None


# --- Gate 2: novelty (deterministic token overlap; embedding path behind a seam) -----------------

# A similarity function over two question prompts, returning a score in [0, 1].
SimilarityFn = Callable[[str, str], float]

# Same ASCII tokenizer as concepts.InMemoryConceptStore — and the same caveat: it cannot see
# Vietnamese diacritics, so VN prompt novelty rides on the reviewer, not on this gate.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text) if len(t) > 2}


def jaccard_similarity(a: str, b: str) -> float:
    """Deterministic token-set Jaccard — the offline default for gate 2."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def build_embedding_similarity(model_name: str | None = None) -> SimilarityFn:
    """Optional embedding-based gate-2 ranker (cosine over BGE-small), for the ``rag`` extras.

    Mirrors ``ChromaConceptStore.create``'s deferred-import pattern so a bare install fails loudly
    only when this path is actually requested; the pipeline default stays the offline Jaccard.
    Callers wiring this into :func:`run_forge` must also pass a cosine-calibrated
    ``novelty_threshold`` — the Jaccard default of 0.6 is far too low for BGE cosine scores.
    """
    try:
        import chromadb  # noqa: F401 — presence check: the rag extra ships both packages together
        from chromadb.utils import embedding_functions
    except ImportError as err:
        raise RuntimeError(
            "embedding novelty detection requires optional packages: chromadb and sentence-transformers"
        ) from err

    from .concepts import BGE_SMALL_EN

    embed = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name or BGE_SMALL_EN)

    def similarity(a: str, b: str) -> float:
        va, vb = embed([a, b])
        dot = sum(x * y for x, y in zip(va, vb, strict=True))
        norm_a = sum(x * x for x in va) ** 0.5
        norm_b = sum(y * y for y in vb) ** 0.5
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

    return similarity


def novelty_gate(
    question: str,
    corpus: Sequence[str],
    *,
    similarity_fn: SimilarityFn | None = None,
    threshold: float = NOVELTY_SIMILARITY_THRESHOLD,
) -> tuple[GateRejection | None, str | None, float | None]:
    """Gate 2: near-duplicate detection against every existing bank/pack prompt.

    Returns ``(rejection_or_none, nearest_prompt, nearest_similarity)`` — the nearest neighbour is
    recorded either way so the report shows how close each draft came (questions have no id; the
    prompt is the identity).
    """
    if not corpus:
        return None, None, None
    score = similarity_fn or jaccard_similarity
    nearest, similarity = max(((prompt, score(question, prompt)) for prompt in corpus), key=lambda hit: hit[1])
    if similarity >= threshold:
        return (
            GateRejection(
                gate=GATE_NOVELTY,
                reason=(
                    f"near-duplicate of existing question {nearest!r} "
                    f"(similarity {similarity:.2f} >= threshold {threshold:.2f})"
                ),
            ),
            nearest,
            similarity,
        )
    return None, nearest, similarity


# --- Gate 3: admission (live — golden-answer machinery over a generated answer pair) -------------

ANSWER_SYSTEM_PROMPT = (
    "You write admission-test answers for a drafted mock-interview question: one STRONG answer a "
    "well-prepared candidate would give (technically accurate, mechanism-level, well-structured) "
    "and one WEAK answer (vague, surface-level, hedging, perhaps with a small real error). The "
    "pair is used to check that a judge can separate them, so make the quality gap unmistakable "
    "while keeping both plausible as real candidate answers.\n"
    "Respond with a single JSON object only — no prose, no code fences."
)


def _answer_messages(question: SeedQuestion) -> list[Message]:
    user = (
        f"QUESTION (skill: {question.skill}):\n{question.question}\n\n"
        f"RUBRIC the judge will score against:\n{question.rubric.render()}\n\n"
        'Return JSON shaped like:\n{"strong_answer": "<text>", "weak_answer": "<text>"}'
    )
    return [
        {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def generate_answer_pair(client: LLMClient, question: SeedQuestion) -> AnswerPair:
    """One structured call producing the strong/weak admission-test pair for a surviving draft."""

    def check_nonblank(pair: AnswerPair) -> None:
        if not pair.strong_answer.strip() or not pair.weak_answer.strip():
            raise ValueError("both 'strong_answer' and 'weak_answer' must be non-empty text")

    return client.chat_json(
        _answer_messages(question),
        AnswerPair,
        validators=[check_nonblank],
        max_retries=1,
    )


def _admission_failure(result: GoldenAnswerResult) -> str:
    if result.error is not None:
        # Errors-as-results: a provider failure during judging is a named gate-3 rejection, so a
        # free-tier 429 mid-batch degrades one draft instead of crashing the run (mirrors bench).
        return f"judge unavailable on the {result.case.case_id} answer: {result.error}"
    return (
        f"{result.case.case_id} answer scored {result.score:.2f}, "
        f"outside its expected band {result.case.expected_range}"
    )


def admission_gate(client: LLMClient, question: SeedQuestion) -> AdmissionOutcome:
    """Gate 3: the Evaluator must separate a generated strong/weak pair into the bench's bands.

    Reuses :class:`eval_harness.GoldenAnswerCase` + :func:`run_golden_answer_harness` with the
    draft's own question and rubric. Both answers in band → admitted; anything else — including a
    provider exception on either the answer generation or a judging call — is a recorded
    ``admission`` rejection carrying the actual scores or error, never a crash.
    """
    try:
        pair = generate_answer_pair(client, question)
    except Exception as err:  # noqa: BLE001 — errors-as-results at the expensive provider-facing gate
        return AdmissionOutcome(
            rejection=GateRejection(
                gate=GATE_ADMISSION,
                reason=f"answer generation unavailable: {type(err).__name__}: {err}",
            )
        )
    cases = (
        GoldenAnswerCase(
            case_id="strong",
            answer=pair.strong_answer,
            expected_min=STRONG_BAND[0],
            expected_max=STRONG_BAND[1],
            question=question.question,
            rubric=question.rubric,
        ),
        GoldenAnswerCase(
            case_id="weak",
            answer=pair.weak_answer,
            expected_min=WEAK_BAND[0],
            expected_max=WEAK_BAND[1],
            question=question.question,
            rubric=question.rubric,
        ),
    )
    # Exactly two cases are always submitted, so harness_passed's missing empty-guard (all([]) is
    # True) cannot bite here; the zero-drafts-reach-gate-3 case is guarded in the run report.
    strong_result, weak_result = run_golden_answer_harness(client, cases)
    failures = [_admission_failure(r) for r in (strong_result, weak_result) if not r.passed]
    return AdmissionOutcome(
        rejection=GateRejection(gate=GATE_ADMISSION, reason="; ".join(failures)) if failures else None,
        strong_answer=pair.strong_answer,
        weak_answer=pair.weak_answer,
        strong_score=strong_result.score,
        weak_score=weak_result.score,
    )


# --- pipeline -------------------------------------------------------------------------------------


def run_forge(
    client: LLMClient,
    skill: str,
    n: int,
    *,
    concepts: Sequence[ConceptNote] | None = None,
    existing_prompts: Sequence[str] | None = None,
    similarity_fn: SimilarityFn | None = None,
    novelty_threshold: float = NOVELTY_SIMILARITY_THRESHOLD,
) -> ForgeRun:
    """Run the full Writer → gate 1 → gate 2 → gate 3 pipeline for one Skill.

    Gates run cheap → expensive per draft: answers are generated (and the judge paid for) only for
    drafts that already passed the free contract and novelty checks. Every rejection is recorded
    with its gate and reason; a completed run with zero admissions is a *result*, not a failure.
    Raises :class:`ForgeError` only when the pipeline itself cannot proceed (Writer unusable) and
    :class:`ValueError` on caller mistakes (bad ``n``, no grounding notes).
    """
    if not 1 <= n <= MAX_DRAFTS:
        raise ValueError(f"n must be between 1 and {MAX_DRAFTS}, got {n}")
    pool = list(concepts) if concepts is not None else list(SEED_CONCEPTS)
    grounding = [note for note in pool if note.skill == skill]
    if not grounding:
        raise ValueError(f"no concept notes for Skill {skill!r} — the Writer has no grounding context")
    corpus = (
        list(existing_prompts)
        if existing_prompts is not None
        else [q.question for questions in QUESTION_BANK.values() for q in questions]
    )

    try:
        drafts = draft_questions(client, skill, grounding, n)
    except StructuredOutputError as err:
        raise ForgeError(f"the Writer produced no usable drafts: {err}") from err

    concept_ids = {note.id for note in grounding}
    seen_prompts: set[str] = set()
    outcomes: list[DraftOutcome] = []
    for i, draft in enumerate(drafts):
        outcome = DraftOutcome(draft=draft)
        outcomes.append(outcome)
        validated, rejection = contract_gate(
            draft, skill=skill, concept_ids=concept_ids, seen_prompts=seen_prompts, where=f"draft[{i}]"
        )
        if rejection is not None:
            outcome.rejection = rejection
            continue
        outcome.validated = validated
        rejection, outcome.nearest_question, outcome.nearest_similarity = novelty_gate(
            draft.question, corpus, similarity_fn=similarity_fn, threshold=novelty_threshold
        )
        if rejection is not None:
            outcome.rejection = rejection
            continue
        assert validated is not None  # for the type checker: gate 1 passed
        admission = admission_gate(client, validated)
        outcome.strong_answer = admission.strong_answer
        outcome.weak_answer = admission.weak_answer
        outcome.strong_score = admission.strong_score
        outcome.weak_score = admission.weak_score
        outcome.rejection = admission.rejection

    admitted = sum(1 for o in outcomes if o.admitted)
    logger.info("forge run for %s: %d drafted, %d admitted", skill, len(outcomes), admitted)
    return ForgeRun(skill=skill, requested=n, outcomes=outcomes)


# --- report + review queue ------------------------------------------------------------------------


def gate_yield(run: ForgeRun) -> dict[str, int]:
    """Survivor counts after each gate — the report's headline numbers."""
    rejected_at: dict[str, int] = {GATE_CONTRACT: 0, GATE_NOVELTY: 0, GATE_ADMISSION: 0}
    for outcome in run.outcomes:
        if outcome.rejection is not None:
            rejected_at[outcome.rejection.gate] += 1
    drafted = len(run.outcomes)
    after_contract = drafted - rejected_at[GATE_CONTRACT]
    after_novelty = after_contract - rejected_at[GATE_NOVELTY]
    after_admission = after_novelty - rejected_at[GATE_ADMISSION]
    return {
        "drafted": drafted,
        GATE_CONTRACT: after_contract,
        GATE_NOVELTY: after_novelty,
        GATE_ADMISSION: after_admission,
    }


def _excerpt(text: str, width: int = 70) -> str:
    flat = " ".join(text.split()).replace("|", "/")
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def render_forge_report(run: ForgeRun, *, provider: str, model: str, date: str) -> str:
    """The Markdown run report: per-gate yield, per-draft outcomes, rejection attribution."""
    counts = gate_yield(run)
    # ``all([]) is True``-style vacuous success must not creep in: when nothing reached gate 3,
    # the admission line says so explicitly instead of reading like a clean pass.
    admission_note = (
        " — no draft reached the admission gate; nothing was admitted"
        if counts[GATE_NOVELTY] == 0
        else ""
    )
    lines = [
        f"# Question Forge run — {run.skill}",
        "",
        f"- Date: {date}",
        f"- Judge provider: {provider} — model: {model}",
        "  (the configured primary; a mid-run provider failover silently swaps the judge — check "
        "WARNING logs before trusting borderline admissions)",
        f"- Requested drafts: {run.requested}",
        f"- Admission bands: strong {STRONG_BAND[0]:.1f}-{STRONG_BAND[1]:.1f} / "
        f"weak {WEAK_BAND[0]:.1f}-{WEAK_BAND[1]:.1f}",
        "",
        "## Per-gate yield",
        "",
        f"- drafted: {counts['drafted']}",
        f"- gate 1 (contract): {counts['drafted']} -> {counts[GATE_CONTRACT]}",
        f"- gate 2 (novelty): {counts[GATE_CONTRACT]} -> {counts[GATE_NOVELTY]}",
        f"- gate 3 (admission): {counts[GATE_NOVELTY]} -> {counts[GATE_ADMISSION]}{admission_note}",
        f"- admitted: {counts[GATE_ADMISSION]}/{counts['drafted']}",
        "",
        "## Per-draft outcomes",
        "",
        "| # | question | verdict | gate | detail |",
        "|---|----------|---------|------|--------|",
    ]
    for i, outcome in enumerate(run.outcomes, start=1):
        details: list[str] = []
        if outcome.nearest_similarity is not None and outcome.nearest_question is not None:
            details.append(
                f"nearest: {_excerpt(outcome.nearest_question, 40)} (sim {outcome.nearest_similarity:.2f})"
            )
        if outcome.strong_score is not None:
            details.append(f"strong {outcome.strong_score:.2f}")
        if outcome.weak_score is not None:
            details.append(f"weak {outcome.weak_score:.2f}")
        verdict = "ADMITTED" if outcome.admitted else "rejected"
        gate = "-" if outcome.rejection is None else outcome.rejection.gate
        lines.append(
            f"| {i} | {_excerpt(outcome.draft.question)} | {verdict} | {gate} | {'; '.join(details) or '-'} |"
        )
    lines += ["", "## Rejection attribution", ""]
    rejected = [(i, o) for i, o in enumerate(run.outcomes, start=1) if o.rejection is not None]
    if rejected:
        for i, outcome in rejected:
            assert outcome.rejection is not None
            lines.append(f"- draft {i} — gate {outcome.rejection.gate}: {outcome.rejection.reason}")
    else:
        lines.append("- (none)")
    lines.append("")
    return "\n".join(lines)


def render_review_queue(run: ForgeRun, *, provider: str, model: str, date: str) -> str:
    """The review-queue YAML: admitted drafts in bank-question shape plus a provenance header.

    Entries are copy-pasteable into ``questions.yaml``/a pack. ``answers[0]`` is the admitted
    strong answer (the bank contract: answers[0] answers the seed); the admission-test weak answer
    is kept as ``answers[1]`` for the reviewer's eyes and must be replaced with Follow-up replies
    on merge (seeds.py: answers[1:] answer successive Follow-ups). Nothing is ever written into the
    bank or a pack by the forge itself.
    """
    admitted = [o for o in run.outcomes if o.admitted]
    entries = []
    for outcome in admitted:
        question = outcome.validated
        assert question is not None and outcome.strong_answer is not None and outcome.weak_answer is not None
        entries.append(
            {
                "question": question.question,
                "difficulty": question.difficulty,
                "rubric": {"weights": dict(question.rubric.weights)},
                "answers": [outcome.strong_answer, outcome.weak_answer],
                "expected_concepts": list(question.expected_concepts),
                "follow_up_seeds": list(question.follow_up_seeds),
            }
        )
    header = (
        "# Question Forge review queue (issue 0028) — HUMAN MERGE ONLY.\n"
        f"# Generated {date} by `coach forge --skill {run.skill} --n {run.requested}` "
        f"(judge provider: {provider}, model: {model}).\n"
        "# Gates passed: contract, novelty, admission "
        f"(strong band {STRONG_BAND[0]:.1f}-{STRONG_BAND[1]:.1f}, weak band {WEAK_BAND[0]:.1f}-{WEAK_BAND[1]:.1f}).\n"
        "# answers[0] is the admitted strong answer; answers[1] is the admission-test WEAK answer,\n"
        "# kept for review — replace answers[1:] with Follow-up replies when merging.\n"
        "# Nothing here enters data/questions.yaml or any pack automatically.\n"
    )
    body = yaml.safe_dump({run.skill: entries}, sort_keys=False, allow_unicode=True, width=100)
    return f"{header}\n{body}"


def write_forge_outputs(
    run: ForgeRun, *, queue_path: str | Path, provider: str, model: str, date: str
) -> tuple[Path, Path]:
    """Write the review queue plus the run report next to it (the ``_cmd_bench`` file pattern)."""
    queue = Path(queue_path)
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.write_text(render_review_queue(run, provider=provider, model=model, date=date), encoding="utf-8")
    report = queue.with_name(f"{queue.stem}-report.md")
    report.write_text(render_forge_report(run, provider=provider, model=model, date=date), encoding="utf-8")
    return queue, report
