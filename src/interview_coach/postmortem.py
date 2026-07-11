"""Rejection post-mortem agent (issue 0026): elicit, reconstruct, fuse at reduced weight.

Nobody serves the post-rejection moment, where the strongest learning signal of a job search lives.
``coach postmortem`` debriefs the Candidate about a real interview they just lost — 5–8 adaptive
clarifying questions — and reconstructs the scorecard the company never shared, as *typed* evidence
per probed Skill with an explicit second-hand confidence.

Three ADRs shape this module:

- ADR 0002 — the belief update stays pure arithmetic: reconstructed entries enter only through the
  sanctioned ``SkillState.observe(weight=...)`` seam, discounted by ``POSTMORTEM_WEIGHT_RATIO`` so
  fresh live evidence still dominates within an answer or two.
- ADR 0005 — the Candidate saying "stop" mid-debrief is intent, never evidence: ``CandidateIntent``
  propagates out of every net, the CLI aborts with exit 2, and the partial recollection is
  discarded with zero ledger writes — never silently fabricated into evidence.
- ADR 0006 — cross-session memory stays a decayed-prior channel: the fused posterior lands in the
  Skill ledger (``ledger.load_states`` decays *before* we observe, because ``save_posteriors``
  restamps the decay clock), not in any prompt.

Orchestration is hand-rolled plain Python (ADR 0004) and every LLM step is a single-shot
``chat_json`` with the accumulated transcript injected — no tools, no graph (ADR 0003).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .diagnostic import CRITICALITY_SETTINGS, SKILLS, RoleCriticality, role_criticality
from .exporter import _md
from .ledger import load_states, save_posteriors
from .llm import LLMClient, Message, Validator
from .microloop import Candidate, CandidateIntent
from .resources import ResourceStore
from .skill import POSTMORTEM_WEIGHT_RATIO, SkillState, confidence_weight, score_to_quality
from .study_planner import StudyTarget, plan_study, rank_study_targets

logger = logging.getLogger(__name__)

# The elicitation budget (issue 0026). Loop discipline is Python's, not the model's: fewer than 5
# answers is too thin a recollection to reconstruct a scorecard from, so a premature `done` is
# ignored; past 8 the debrief turns into an interrogation of someone who just got rejected, so
# `done` is forced regardless of what the model wants.
MIN_ELICITATION_QUESTIONS = 5
MAX_ELICITATION_QUESTIONS = 8


class ElicitationStep(BaseModel):
    """One elicitor turn: the next debrief question, plus whether coverage is already sufficient."""

    done: bool
    next_question: str
    coverage: list[str] = Field(
        default_factory=list,
        description="Canonical Skills the recollection so far shows were probed.",
    )


class ReconstructedSkillEntry(BaseModel):
    """One probed Skill's reconstructed scorecard line — typed, second-hand evidence."""

    skill: str
    estimated_score: float = Field(ge=1, le=5, description="1–5, the scale a live weighted_score uses.")
    confidence: float = Field(
        ge=0,
        le=1,
        description="Same semantics as Evaluation.confidence, discounted for second-hand recall.",
    )
    rationale: str = Field(min_length=1)
    recollection_evidence: str = Field(
        min_length=1,
        description="The Candidate's own recollection this entry rests on (quote or close paraphrase).",
    )


class ReconstructedScorecard(BaseModel):
    """The scorecard the company never shared, rebuilt from the debrief transcript."""

    entries: list[ReconstructedSkillEntry] = Field(min_length=1)


@dataclass(frozen=True)
class RecollectionTurn:
    """One ask→recall exchange of the elicitation dialogue."""

    question: str
    answer: str


@dataclass(frozen=True)
class PostmortemResult:
    """Everything one post-mortem produced: the debrief, the fusion, and the plan diff."""

    candidate_id: str
    transcript: tuple[RecollectionTurn, ...]
    scorecard: ReconstructedScorecard
    states_before: dict[str, SkillState]  # decayed ledger states (+ neutral fills for probed Skills)
    states_after: dict[str, SkillState]  # after fusion — exactly what was saved back
    targets_before: tuple[StudyTarget, ...]  # deterministic priority ranking, pre-fusion
    targets_after: tuple[StudyTarget, ...]
    study_plan: dict[str, Any] | None
    study_plan_error: str | None


ELICITATION_SYSTEM_PROMPT = (
    "You are the Post-mortem elicitor for an adaptive interview coach. The Candidate was just "
    "rejected after a real interview and the company shared nothing. You debrief them — with "
    "empathy, but concretely — to recover what actually happened: what was asked, where the "
    "interviewer pushed back or dug deeper, when the energy in the room shifted, and which Skills "
    "were probed.\n\n"
    f"Canonical Skills: {', '.join(SKILLS)}.\n\n"
    "Rules:\n"
    "- Ask exactly one clarifying question per turn, building on the Candidate's previous answers.\n"
    "- Set done=true only once the recollection could support a per-Skill scorecard; the "
    "orchestrator enforces the question budget, not you.\n"
    "- Always provide next_question, even alongside done=true.\n"
    "- This is a rejection debrief, not another interview: never grade or correct the Candidate.\n"
    "- Respond with one JSON object only — no prose, no code fences."
)

_ELICITATION_SCHEMA_HINT = (
    '{"done": <true|false>, "next_question": "<text>", "coverage": ["<canonical Skill>"]}'
)

RECONSTRUCTION_SYSTEM_PROMPT = (
    "You are the Post-mortem scorecard reconstructor for an adaptive interview coach. From a "
    "rejection-debrief transcript, reconstruct the scorecard the company never shared: one entry "
    "per canonical Skill the recollection shows was actually probed.\n\n"
    f"Canonical Skills: {', '.join(SKILLS)}.\n\n"
    "Rules:\n"
    "- This is SECOND-HAND evidence reconstructed from the Candidate's memory, not a live "
    "evaluation. confidence (0-1) must reflect that: keep it well below what a directly observed "
    "answer would earn, and lower it further wherever the recollection is vague, one-sided, or "
    "contradictory.\n"
    "- estimated_score is 1-5, the same scale as a live weighted_score.\n"
    "- recollection_evidence must quote or closely paraphrase the Candidate's own words from the "
    "transcript — never invent detail the Candidate did not report.\n"
    "- Include only canonical Skills that were probed; at most one entry per Skill.\n"
    "- Respond with one JSON object only — no prose, no code fences."
)

_SCORECARD_SCHEMA_HINT = (
    '{"entries": [{"skill": "<canonical Skill>", "estimated_score": <1-5>, "confidence": <0-1>, '
    '"rationale": "<text>", "recollection_evidence": "<text>"}]}'
)


def run_postmortem(
    client: LLMClient,
    candidate: Candidate,
    *,
    candidate_id: str,
    ledger_db: str | Path,
    target_role: str = "machine learning engineer",
    companies: tuple[str, ...] = (),
    resource_store: ResourceStore | None = None,
    now: float | None = None,
) -> PostmortemResult:
    """Run the full post-mortem: elicit → reconstruct → fuse into the ledger → re-plan with a diff.

    The ledger write happens only *after* elicitation and reconstruction both succeed, so a
    ``CandidateIntent`` abort (ADR 0005) — which propagates from ``candidate.answer`` untouched —
    structurally cannot leave a partial record behind.
    """
    if not candidate_id:
        raise ValueError("postmortem requires a candidate id — the Skill ledger is the whole point")
    now = time.time() if now is None else now

    transcript = run_elicitation(client, candidate, target_role=target_role, companies=companies)
    scorecard = reconstruct_scorecard(client, transcript, target_role=target_role, companies=companies)

    # Decay-before-observe (ADR 0006): load_states already decayed the carried params to `now`;
    # Skills never seen before start from the weak neutral prior.
    states_before = load_states(ledger_db, candidate_id, now=now) or {}
    for entry in scorecard.entries:
        states_before.setdefault(entry.skill, SkillState.neutral(entry.skill))
    states_after = fuse_scorecard(states_before, scorecard)
    # save_posteriors replaces the whole record and restamps the decay clock, so the untouched
    # Skills' *decayed* states ride along — their mass is preserved, not silently un-decayed.
    save_posteriors(ledger_db, candidate_id, states_after, now=now)

    before_state = _synthesized_session_state(candidate_id, states_before, target_role, companies)
    after_state = _synthesized_session_state(candidate_id, states_after, target_role, companies)
    targets_before = tuple(rank_study_targets(before_state))
    targets_after = tuple(rank_study_targets(after_state))

    # LLM layer of the diff is best effort: the deterministic before/after ranking above is always
    # shown, and a planner failure degrades exactly like supervisor.study_plan_node — never fatal.
    study_plan: dict[str, Any] | None = None
    study_plan_error: str | None = None
    try:
        study_plan = plan_study(client, after_state, resource_store=resource_store).model_dump(mode="json")
    except CandidateIntent:  # ADR 0005: intent propagates out of every net, always re-raised first
        raise
    except Exception as err:  # noqa: BLE001 — optional end-matter; a planner blip must not void the fusion
        logger.warning("post-mortem study planner failed; keeping the ledger fusion without a plan: %s", err)
        study_plan_error = f"{type(err).__name__}: {err}"

    return PostmortemResult(
        candidate_id=candidate_id,
        transcript=transcript,
        scorecard=scorecard,
        states_before=states_before,
        states_after=states_after,
        targets_before=targets_before,
        targets_after=targets_after,
        study_plan=study_plan,
        study_plan_error=study_plan_error,
    )


def run_elicitation(
    client: LLMClient,
    candidate: Candidate,
    *,
    target_role: str = "",
    companies: tuple[str, ...] = (),
) -> tuple[RecollectionTurn, ...]:
    """The adaptive elicitation loop: one chat_json step per turn, budget owned by this loop.

    ``candidate.answer`` may raise :class:`CandidateIntent` (EOF/Ctrl-D, scripted answers running
    out); nothing here catches it — per ADR 0005 it must reach the command boundary untouched.
    """
    transcript: list[RecollectionTurn] = []
    while len(transcript) < MAX_ELICITATION_QUESTIONS:
        step = client.chat_json(
            _build_elicitation_messages(transcript, target_role=target_role, companies=companies),
            ElicitationStep,
            validators=[_validate_elicitation_step],
            max_retries=1,
        )
        # Loop discipline is Python's, not the model's: a premature `done` (before the minimum) is
        # ignored, and exhausting the maximum ends the loop without consulting the model again.
        if step.done and len(transcript) >= MIN_ELICITATION_QUESTIONS:
            break
        answer = candidate.answer(step.next_question)
        transcript.append(RecollectionTurn(question=step.next_question, answer=answer))
    return tuple(transcript)


def reconstruct_scorecard(
    client: LLMClient,
    transcript: Sequence[RecollectionTurn],
    *,
    target_role: str = "",
    companies: tuple[str, ...] = (),
) -> ReconstructedScorecard:
    """One single-shot chat_json call turning the debrief into typed per-Skill evidence."""
    return client.chat_json(
        _build_reconstruction_messages(transcript, target_role=target_role, companies=companies),
        ReconstructedScorecard,
        validators=_make_scorecard_validators(),
        max_retries=1,
    )


def fuse_scorecard(
    states: Mapping[str, SkillState],
    scorecard: ReconstructedScorecard,
) -> dict[str, SkillState]:
    """Fuse reconstructed entries into the belief through the sanctioned ``observe()`` seam.

    Each entry contributes ``POSTMORTEM_WEIGHT_RATIO * confidence_weight(confidence)`` pseudo-counts
    — half of what the same score+confidence would earn live (issue 0026). Skills the scorecard
    does not mention pass through untouched, so their already-decayed mass survives the re-save.
    Entries for Skills absent from ``states`` start from the weak neutral prior.
    """
    fused = dict(states)
    for entry in scorecard.entries:
        before = fused.get(entry.skill, SkillState.neutral(entry.skill))
        fused[entry.skill] = before.observe(
            score_to_quality(entry.estimated_score),
            weight=POSTMORTEM_WEIGHT_RATIO * confidence_weight(entry.confidence),
        )
    return fused


def _validate_elicitation_step(step: ElicitationStep) -> None:
    if not step.next_question.strip():
        raise ValueError(
            "next_question must always carry the next debrief question, even alongside done=true — "
            "the orchestrator owns the question budget, not you"
        )


def _make_scorecard_validators() -> list[Validator]:
    known = set(SKILLS)

    def validate(scorecard: ReconstructedScorecard) -> None:
        unknown = sorted({entry.skill for entry in scorecard.entries} - known)
        if unknown:
            raise ValueError(f"unknown Skill(s) {unknown}; use only canonical Skills: {', '.join(SKILLS)}")
        seen: set[str] = set()
        for entry in scorecard.entries:
            if entry.skill in seen:
                raise ValueError(f"at most one entry per Skill; {entry.skill!r} appears more than once")
            seen.add(entry.skill)
            if not entry.recollection_evidence.strip():
                raise ValueError(
                    f"recollection_evidence for {entry.skill!r} must quote or paraphrase the "
                    "Candidate's own words — it cannot be blank"
                )

    return [validate]


def _interview_context(target_role: str, companies: tuple[str, ...]) -> str:
    lines = []
    if target_role:
        lines.append(f"- target_role: {target_role}")
    if companies:
        lines.append(f"- company: {', '.join(companies)}")
    return "\n".join(lines) or "- unknown"


def _render_transcript(transcript: Sequence[RecollectionTurn]) -> str:
    return "\n".join(
        f"Q{i}: {turn.question}\nA{i}: {turn.answer}" for i, turn in enumerate(transcript, start=1)
    ) or "- none yet"


def _build_elicitation_messages(
    transcript: Sequence[RecollectionTurn],
    *,
    target_role: str,
    companies: tuple[str, ...],
) -> list[Message]:
    user = (
        f"INTERVIEW CONTEXT:\n{_interview_context(target_role, companies)}\n\n"
        f"DEBRIEF SO FAR ({len(transcript)} of {MAX_ELICITATION_QUESTIONS} questions asked):\n"
        f"{_render_transcript(transcript)}\n\n"
        "Decide whether coverage is sufficient and provide the next clarifying question.\n"
        f"Return JSON shaped like:\n{_ELICITATION_SCHEMA_HINT}"
    )
    return [
        {"role": "system", "content": ELICITATION_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _build_reconstruction_messages(
    transcript: Sequence[RecollectionTurn],
    *,
    target_role: str,
    companies: tuple[str, ...],
) -> list[Message]:
    user = (
        f"INTERVIEW CONTEXT:\n{_interview_context(target_role, companies)}\n\n"
        f"REJECTION-DEBRIEF TRANSCRIPT:\n{_render_transcript(transcript)}\n\n"
        "Reconstruct the scorecard.\n"
        f"Return JSON shaped like:\n{_SCORECARD_SCHEMA_HINT}"
    )
    return [
        {"role": "system", "content": RECONSTRUCTION_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _synthesized_session_state(
    candidate_id: str,
    states: Mapping[str, SkillState],
    target_role: str,
    companies: tuple[str, ...],
) -> dict[str, Any]:
    """A minimal session_state-shaped Mapping for rank_study_targets/plan_study.

    Skill metadata mirrors initial_session_state's shape (role_criticality + evidence_bar); the
    transcript is empty, which the planner's evidence helpers degrade over gracefully.
    """
    criticality = role_criticality(target_role, companies)
    metadata: dict[str, Any] = {}
    for skill in states:
        level = criticality.get(skill, RoleCriticality.PERIPHERAL)
        metadata[skill] = {
            "role_criticality": level.value,
            "evidence_bar": CRITICALITY_SETTINGS[level].evidence_bar,
        }
    return {
        "session_id": f"postmortem-{candidate_id}",
        "skill_states": {
            skill: {"skill": state.skill, "alpha": state.alpha, "beta": state.beta}
            for skill, state in states.items()
        },
        "skill_metadata": metadata,
        "transcript": [],
    }


# --- Markdown debrief (issue 0026: portfolio-style artifact, exporter escaping conventions) ------


def export_postmortem_markdown(result: PostmortemResult, path: str | Path) -> Path:
    """Write the post-mortem debrief Markdown (scorecard, ledger delta, regenerated plan)."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_postmortem_markdown(result), encoding="utf-8")
    return output


def render_postmortem_markdown(result: PostmortemResult) -> str:
    lines: list[str] = []
    lines.append(f"# Rejection Post-mortem: {_md(result.candidate_id)}")
    lines.append("")
    lines.append(
        f"Reconstructed from a {len(result.transcript)}-question debrief; second-hand evidence "
        f"fused at {POSTMORTEM_WEIGHT_RATIO:g}x the live evidence weight."
    )
    lines.append("")
    lines.append("## Reconstructed Scorecard")
    lines.append("")
    lines.append("| Skill | Estimated score | Confidence | Evidence weight | Rationale |")
    lines.append("| --- | ---: | ---: | ---: | --- |")
    for entry in result.scorecard.entries:
        weight = POSTMORTEM_WEIGHT_RATIO * confidence_weight(entry.confidence)
        lines.append(
            f"| `{_md(entry.skill)}` | {entry.estimated_score:.1f}/5 | {entry.confidence:.2f} | "
            f"{weight:.2f} | {_md(entry.rationale)} |"
        )
    lines.append("")
    for entry in result.scorecard.entries:
        lines.append(f"- `{_md(entry.skill)}` recollection: {_md(entry.recollection_evidence)}")
    lines.append("")
    lines.append("## Ledger Delta")
    lines.append("")
    lines.append("| Skill | Mastery before | Mastery after | Change | Priority before | Priority after |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    rank_before = {t.skill: i for i, t in enumerate(result.targets_before, start=1)}
    rank_after = {t.skill: i for i, t in enumerate(result.targets_after, start=1)}
    for skill in sorted(result.states_after):
        before = result.states_before.get(skill)
        after = result.states_after[skill]
        if before is None:
            continue
        lines.append(
            f"| `{_md(skill)}` | {before.mastery:.3f} | {after.mastery:.3f} | "
            f"{after.mastery - before.mastery:+.3f} | "
            f"#{rank_before.get(skill, '—')} | #{rank_after.get(skill, '—')} |"
        )
    lines.append("")
    lines.append("## Regenerated Plan")
    lines.append("")
    plan = result.study_plan
    if not isinstance(plan, Mapping):
        reason = result.study_plan_error or "no plan recorded"
        lines.append(f"Planner unavailable: `{_md(reason)}` — the ledger fusion above still stands.")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"
    lines.append(
        f"Readiness estimate: **{float(plan.get('readiness_estimate', 0)):.0%}**. "
        f"{_md(plan.get('readiness_rationale'))}"
    )
    lines.append("")
    for topic in plan.get("prioritized_topics", []):
        lines.append(
            f"{topic.get('priority')}. **{_md(topic.get('title'))}** (`{_md(topic.get('skill'))}`) - "
            f"{_md(topic.get('rationale'))}"
        )
        for resource in topic.get("resources", []):
            lines.append(f"   - [{_md(resource.get('title'))}]({resource.get('url')})")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"
