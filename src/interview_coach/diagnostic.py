"""Diagnostic profile reader: Topic Plan + seeded Skill priors (slice 0009, ADR 0002).

This is deliberately deterministic for the early hand-rolled slices. It behaves like the future
Diagnostic agent's state preparation step: read the Candidate profile, produce a Topic Plan, and seed
weak Beta priors. Cross-skill correlations are applied once here and nowhere in the evidence updater.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field

from .llm import LLMClient, Message, Validator
from .skill import SkillState

logger = logging.getLogger(__name__)

SKILLS: tuple[str, ...] = (
    "ml_fundamentals",
    "deep_learning",
    "mlops",
    "system_design",
    "vietnamese_nlp",
)


class RoleCriticality(StrEnum):
    MUST_HAVE = "must_have"
    CORE = "core"
    PERIPHERAL = "peripheral"


@dataclass(frozen=True)
class CriticalitySetting:
    """How hard the Supervisor should require evidence for a Skill."""

    target_confidence: float
    evidence_bar: float
    ordering_rank: int


CRITICALITY_SETTINGS: dict[RoleCriticality, CriticalitySetting] = {
    # Must-haves get the weakest prior confidence and highest early-termination bar: probe hard.
    RoleCriticality.MUST_HAVE: CriticalitySetting(target_confidence=0.0, evidence_bar=4.0, ordering_rank=0),
    RoleCriticality.CORE: CriticalitySetting(target_confidence=0.15, evidence_bar=3.0, ordering_rank=1),
    # Peripheral skills can rely a little more on the claim and need less direct evidence.
    RoleCriticality.PERIPHERAL: CriticalitySetting(target_confidence=0.3, evidence_bar=2.0, ordering_rank=2),
}


@dataclass(frozen=True)
class CandidateProfile:
    """Inputs the Diagnostic reads at Session start."""

    target_role: str
    claimed_skills: Mapping[str, float] = field(default_factory=dict)
    target_companies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        unknown = set(self.claimed_skills) - set(SKILLS)
        if unknown:
            raise ValueError(f"unknown Skill claim(s): {sorted(unknown)}")
        for skill, value in self.claimed_skills.items():
            if not 1 <= value <= 5:
                raise ValueError(f"self-assessment for {skill!r} must be on the 1–5 scale")


@dataclass(frozen=True)
class TopicPlanEntry:
    """One item in the Supervisor's default script."""

    skill: str
    target_difficulty: int
    rationale: str


@dataclass(frozen=True)
class SeededSkillPrior:
    """A Skill prior plus the criticality metadata the Supervisor will later consume."""

    state: SkillState
    role_criticality: RoleCriticality
    evidence_bar: float

    @property
    def prior_strength(self) -> float:
        return self.state.alpha + self.state.beta


class TopicPlanSource(StrEnum):
    """Which path produced the Topic Plan — the LLM agent (primary) or the offline fallback."""

    LLM = "llm"
    DETERMINISTIC = "deterministic"


@dataclass(frozen=True)
class DiagnosticResult:
    topic_plan: tuple[TopicPlanEntry, ...]
    priors: dict[str, SeededSkillPrior]
    topic_plan_source: TopicPlanSource


class DiagnosticPlanItem(BaseModel):
    skill: str
    target_difficulty: int = Field(ge=1, le=5)
    rationale: str = Field(min_length=1)


class DiagnosticPlanResponse(BaseModel):
    topic_plan: list[DiagnosticPlanItem]


_ROLE_CRITICALITY: dict[str, dict[str, RoleCriticality]] = {
    "machine learning engineer": {
        "ml_fundamentals": RoleCriticality.MUST_HAVE,
        "mlops": RoleCriticality.MUST_HAVE,
        "system_design": RoleCriticality.CORE,
        "deep_learning": RoleCriticality.CORE,
        "vietnamese_nlp": RoleCriticality.PERIPHERAL,
    },
    "ml engineer": {
        "ml_fundamentals": RoleCriticality.MUST_HAVE,
        "mlops": RoleCriticality.MUST_HAVE,
        "system_design": RoleCriticality.CORE,
        "deep_learning": RoleCriticality.CORE,
        "vietnamese_nlp": RoleCriticality.PERIPHERAL,
    },
    "research scientist": {
        "ml_fundamentals": RoleCriticality.MUST_HAVE,
        "deep_learning": RoleCriticality.MUST_HAVE,
        "system_design": RoleCriticality.CORE,
        "mlops": RoleCriticality.PERIPHERAL,
        "vietnamese_nlp": RoleCriticality.PERIPHERAL,
    },
}

_COMPANY_CRITICALITY: dict[str, dict[str, RoleCriticality]] = {
    "vinai": {"vietnamese_nlp": RoleCriticality.CORE},
    "zalo": {"vietnamese_nlp": RoleCriticality.CORE},
    "viettel": {"vietnamese_nlp": RoleCriticality.CORE, "mlops": RoleCriticality.CORE},
}

_CRITICALITY_ORDER = {
    RoleCriticality.MUST_HAVE: 0,
    RoleCriticality.CORE: 1,
    RoleCriticality.PERIPHERAL: 2,
}

_CORRELATIONS: dict[str, dict[str, float]] = {
    "ml_fundamentals": {"deep_learning": 0.16},
    "deep_learning": {"ml_fundamentals": 0.12},
    "system_design": {"mlops": 0.10},
    "mlops": {"system_design": 0.10},
    "vietnamese_nlp": {"ml_fundamentals": 0.05, "deep_learning": 0.05},
}


DIAGNOSTIC_SYSTEM_PROMPT = (
    "You are the Diagnostic agent for an adaptive technical interview. You run once at Session start. "
    "You produce the Topic Plan only: an ordered list of Skill probes with target difficulty and "
    "rationale. You do not judge answers, update Skill state, call tools, or act as Supervisor.\n\n"
    "Rules:\n"
    "- Use only the canonical Skills provided in the prompt.\n"
    "- Include every canonical Skill exactly once.\n"
    "- Role criticality tells you how hard to probe and how early to schedule a Skill; it never means "
    "the Candidate is better or worse.\n"
    "- The seeded priors are weak cold-start hints. Direct evidence will override them.\n"
    "- Respond with a single JSON object only — no prose, no code fences."
)

_DIAGNOSTIC_SCHEMA_HINT = (
    '{"topic_plan": [{"skill": "<canonical Skill>", "target_difficulty": <1-5>, "rationale": "<text>"}]}'
)


def diagnose(
    profile: CandidateProfile,
    client: LLMClient | None = None,
    *,
    ledger_priors: Mapping[str, float] | None = None,
) -> DiagnosticResult:
    """Produce the Topic Plan and seeded priors for a Candidate.

    The single-shot LLM agent is the primary Topic Plan path; the deterministic ordering is the
    offline fallback used only when no ``client`` is supplied. ``topic_plan_source`` records which
    path ran.

    ``ledger_priors`` (ADR 0006) optionally carries a returning Candidate's *decayed* per-Skill prior
    means, which override the cold-start baseline for those Skills. With none supplied the Diagnostic
    behaves exactly as a first-ever Session (cold start).
    """
    criticality = role_criticality(profile.target_role, profile.target_companies)
    means = _initial_mastery_means(profile, ledger_priors)
    priors = {
        skill: _seed_prior(skill, means[skill], criticality[skill])
        for skill in SKILLS
    }
    if client is None:
        plan = tuple(_topic_plan_entry(skill, priors[skill], means[skill]) for skill in _ordered_skills(priors))
        source = TopicPlanSource.DETERMINISTIC
    else:
        plan = _diagnose_topic_plan(client, profile, priors)
        source = TopicPlanSource.LLM
    logger.info("Diagnostic Topic Plan source: %s", source.value)
    return DiagnosticResult(topic_plan=plan, priors=priors, topic_plan_source=source)


def diagnose_or_degrade(
    profile: CandidateProfile,
    client: LLMClient | None = None,
    *,
    ledger_priors: Mapping[str, float] | None = None,
) -> DiagnosticResult:
    """ADR 0005 backstop for the Diagnostic phase (issue 0030).

    The Diagnostic runs *before* the LangGraph Session starts, so its LLM call has no node-level
    transport backstop like ``question_node`` / ``study_plan_node`` / ``decide_next_move``. A
    provider/transport failure here (timeout, rate limit, a 4xx after fallback exhaustion) — or a
    schema-invalid plan after retry — must degrade to the deterministic Topic Plan instead of
    crashing the run with a raw traceback. Runtime entry points (CLI/web) call this; benches and
    tests that want the raw error keep calling :func:`diagnose` directly.

    With ``client=None`` this is exactly :func:`diagnose` (the deterministic path never raises a
    transport error, so there is nothing to degrade from). A genuine bug in the pure prep helpers
    still surfaces loudly: it raises again on the deterministic retry, which is not caught.
    """
    try:
        return diagnose(profile, client, ledger_priors=ledger_priors)
    except Exception as err:  # noqa: BLE001 — pre-graph call site; degrade instead of crash (ADR 0005)
        if client is None:
            raise
        logger.warning(
            "Diagnostic LLM Topic Plan failed (%s: %s); degrading to the deterministic Topic Plan",
            type(err).__name__,
            err,
        )
        return diagnose(profile, None, ledger_priors=ledger_priors)


def _diagnose_topic_plan(
    client: LLMClient,
    profile: CandidateProfile,
    priors: Mapping[str, SeededSkillPrior],
) -> tuple[TopicPlanEntry, ...]:
    response = client.chat_json(
        _build_diagnostic_messages(profile, priors),
        DiagnosticPlanResponse,
        validators=_make_plan_validators(),
        max_retries=1,
    )
    return tuple(
        TopicPlanEntry(
            skill=item.skill,
            target_difficulty=item.target_difficulty,
            rationale=item.rationale,
        )
        for item in response.topic_plan
    )


def _make_plan_validators() -> list[Validator]:
    expected = set(SKILLS)

    def check_plan(response: DiagnosticPlanResponse) -> None:
        skills = [item.skill for item in response.topic_plan]
        got = set(skills)
        if unknown := got - expected:
            raise ValueError(f"unknown Skills in Topic Plan: {sorted(unknown)}")
        if missing := expected - got:
            raise ValueError(f"missing Skills from Topic Plan: {sorted(missing)}")
        if len(skills) != len(got):
            raise ValueError("Topic Plan must include each Skill exactly once; duplicates found")

    return [check_plan]


def _build_diagnostic_messages(
    profile: CandidateProfile,
    priors: Mapping[str, SeededSkillPrior],
) -> list[Message]:
    claims = "\n".join(
        f"- {skill}: {score:g}/5"
        for skill, score in sorted(profile.claimed_skills.items())
    ) or "- none"
    prior_lines = "\n".join(
        (
            f"- {skill}: mastery={prior.state.mastery:.3f}, "
            f"confidence={prior.state.confidence:.3f}, "
            f"criticality={prior.role_criticality.value}, evidence_bar={prior.evidence_bar:.1f}"
        )
        for skill, prior in sorted(
            priors.items(),
            key=lambda kv: (
                CRITICALITY_SETTINGS[kv[1].role_criticality].ordering_rank,
                kv[0],
            ),
        )
    )
    user = (
        f"CANDIDATE PROFILE:\n"
        f"- target_role: {profile.target_role}\n"
        f"- target_companies: {', '.join(profile.target_companies) or 'none'}\n"
        f"- claimed_skills:\n{claims}\n\n"
        f"CANONICAL SKILLS:\n{', '.join(SKILLS)}\n\n"
        f"SEEDED PRIORS AND ROLE CRITICALITY:\n{prior_lines}\n\n"
        "Produce the Topic Plan.\n"
        f"Return JSON shaped like:\n{_DIAGNOSTIC_SCHEMA_HINT}"
    )
    return [
        {"role": "system", "content": DIAGNOSTIC_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def role_criticality(target_role: str, target_companies: tuple[str, ...] = ()) -> dict[str, RoleCriticality]:
    """Hand-built Role criticality table; role/company changes never alter prior means."""
    role_key = target_role.strip().lower()
    result = {skill: RoleCriticality.PERIPHERAL for skill in SKILLS}
    result.update(_ROLE_CRITICALITY.get(role_key, {}))

    for company in target_companies:
        if overrides := _COMPANY_CRITICALITY.get(company.strip().lower()):
            for skill, value in overrides.items():
                if _CRITICALITY_ORDER[value] < _CRITICALITY_ORDER[result[skill]]:
                    result[skill] = value
    return result


def _initial_mastery_means(
    profile: CandidateProfile,
    ledger_priors: Mapping[str, float] | None = None,
) -> dict[str, float]:
    means = {skill: 0.5 for skill in SKILLS}
    for skill, value in profile.claimed_skills.items():
        means[skill] = _self_assessment_to_mean(value)

    # A returning Candidate's carried (decayed) mean is measured past evidence, so it overrides both
    # the cold-start baseline and any fresh self-claim for that Skill (ADR 0002: evidence beats claims;
    # ADR 0006: the ledger sets the mean, criticality still sets strength in _seed_prior).
    informed = set(profile.claimed_skills)
    if ledger_priors:
        for skill, mean in ledger_priors.items():
            if skill in means:
                means[skill] = _clamp_mean(mean)
                informed.add(skill)

    # Prior-only correlations: one cold-start nudge before direct evidence starts arriving. Skip any
    # Skill that already has an informative mean (a self-claim or a carried ledger prior).
    for source, related in _CORRELATIONS.items():
        source_mean = means[source]
        delta_from_neutral = source_mean - 0.5
        if delta_from_neutral == 0:
            continue
        for target, strength in related.items():
            if target in informed:
                continue
            means[target] = _clamp_mean(means[target] + delta_from_neutral * strength)
    return means


def _self_assessment_to_mean(value: float) -> float:
    # Keep even a 1/5 or 5/5 self-claim weak and defeasible; direct evidence can override quickly.
    return 0.2 + (value - 1.0) * 0.15


def _clamp_mean(value: float) -> float:
    return max(0.05, min(0.95, value))


def _seed_prior(skill: str, mean: float, criticality: RoleCriticality) -> SeededSkillPrior:
    setting = CRITICALITY_SETTINGS[criticality]
    target_variance = SkillState.neutral(skill).variance * (1.0 - setting.target_confidence)
    prior_strength = mean * (1.0 - mean) / target_variance - 1.0
    alpha = mean * prior_strength
    beta = (1.0 - mean) * prior_strength
    return SeededSkillPrior(
        state=SkillState(skill=skill, alpha=alpha, beta=beta),
        role_criticality=criticality,
        evidence_bar=setting.evidence_bar,
    )


def _ordered_skills(priors: Mapping[str, SeededSkillPrior]) -> list[str]:
    return sorted(
        priors,
        key=lambda skill: (
            CRITICALITY_SETTINGS[priors[skill].role_criticality].ordering_rank,
            -abs(priors[skill].state.mastery - 0.5),
            skill,
        ),
    )


def _topic_plan_entry(skill: str, prior: SeededSkillPrior, mean: float) -> TopicPlanEntry:
    target_difficulty = max(1, min(5, round(1 + 4 * mean)))
    return TopicPlanEntry(
        skill=skill,
        target_difficulty=target_difficulty,
        rationale=(
            f"{prior.role_criticality.value} for the target role; "
            f"start near difficulty {target_difficulty} from the Candidate's weak prior "
            f"(mastery {prior.state.mastery:.2f}, evidence bar {prior.evidence_bar:.1f})"
        ),
    )
