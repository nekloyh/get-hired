"""End-of-Session Study Planner (slice 0011).

The Study Planner is a single-shot LLM agent: final Skill states, transcript evidence, deterministic
priority targets, and retrieved resource candidates are injected directly into the prompt. Retrieval
happens in Python before the LLM call, so ADR 0003 still holds: the Interviewer remains the only
tool-using agent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from .llm import LLMClient, Message, Validator
from .resources import (
    InMemoryResourceStore,
    LearningResource,
    ResourceMatch,
    ResourceStore,
    search_resources,
    seed_resource_store,
)
from .skill import SkillState

DEFAULT_STUDY_TOPICS = 3
DEFAULT_RESOURCES_PER_TOPIC = 3
MAX_RESOURCELESS_SCHEDULE_DAYS = 2
_RESOURCELESS_DAY_MARKERS = (
    "review",
    "consolidat",
    "synthesis",
    "mock interview",
    "assessment",
    "retrospective",
)

_CRITICALITY_BONUS = {
    "must_have": 0.25,
    "core": 0.12,
    "peripheral": 0.0,
}
_CRITICALITY_RANK = {
    "must_have": 0,
    "core": 1,
    "peripheral": 2,
}


@dataclass(frozen=True)
class StudyTarget:
    """A deterministic priority target derived from final Skill state."""

    skill: str
    mastery: float
    confidence: float
    role_criticality: str
    priority_score: float
    query: str


class StudyResource(BaseModel):
    id: str
    skill: str
    title: str
    url: str
    summary: str
    resource_type: str
    effort_minutes: int = Field(ge=1)


class StudyTopic(BaseModel):
    priority: int = Field(ge=1)
    skill: str
    title: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    target_mastery: str = Field(min_length=1)
    mastery: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    role_criticality: str
    resources: list[StudyResource] = Field(min_length=1)


class StudyScheduleItem(BaseModel):
    day: int = Field(ge=1, le=14)
    focus: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    # Explicit consolidation/review days may cite no *new* resource. The validator bounds this so the
    # model cannot silently return an ungrounded schedule.
    resources: list[StudyResource] = Field(default_factory=list)


class StudyMilestone(BaseModel):
    week: int = Field(ge=1, le=2)
    description: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class StudyPlan(BaseModel):
    session_id: str
    readiness_estimate: float = Field(ge=0, le=1)
    readiness_rationale: str = Field(min_length=1)
    prioritized_topics: list[StudyTopic] = Field(min_length=1)
    schedule: list[StudyScheduleItem] = Field(min_length=14, max_length=14)
    milestones: list[StudyMilestone] = Field(min_length=2)


class StudyTopicDraft(BaseModel):
    priority: int = Field(ge=1)
    skill: str
    title: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    target_mastery: str = Field(min_length=1)
    resource_ids: list[str] = Field(min_length=1)


class StudyScheduleDraft(BaseModel):
    day: int = Field(ge=1, le=14)
    focus: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    # Empty only for explicit review/consolidation days — see the validator below.
    resource_ids: list[str] = Field(default_factory=list)


class StudyMilestoneDraft(BaseModel):
    week: int = Field(ge=1, le=2)
    description: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class StudyPlanDraft(BaseModel):
    readiness_estimate: float = Field(ge=0, le=1)
    readiness_rationale: str = Field(min_length=1)
    prioritized_topics: list[StudyTopicDraft] = Field(min_length=1)
    schedule: list[StudyScheduleDraft] = Field(min_length=14, max_length=14)
    milestones: list[StudyMilestoneDraft] = Field(min_length=2)


STUDY_PLANNER_SYSTEM_PROMPT = (
    "You are the Study Planner for an adaptive technical interview. You run once, after the Session "
    "is complete. You read the final Skill states and resolved transcript evidence, then produce a "
    "targeted two-week StudyPlan.\n\n"
    "Rules:\n"
    "- Use the priority targets exactly as provided; they already combine weakness and Role "
    "criticality.\n"
    "- Use only resource IDs listed in RESOURCE CANDIDATES. Do not invent URLs, titles, or IDs.\n"
    "- The final schedule must have exactly days 1 through 14.\n"
    "- Each schedule day should cite at least one resource_id unless it is explicitly a review, "
    "consolidation, synthesis, mock interview, or assessment day. Use at most two resource-free days.\n"
    "- Milestones should be evidence-based checks the Candidate can perform.\n"
    "- You do not ask questions, evaluate answers, call tools, or act as Supervisor.\n"
    "- Respond with one JSON object only."
)

_STUDY_PLAN_SCHEMA_HINT = (
    '{"readiness_estimate": <0-1>, "readiness_rationale": "<text>", '
    '"prioritized_topics": [{"priority": <1..N>, "skill": "<canonical Skill>", "title": "<text>", '
    '"rationale": "<text>", "target_mastery": "<text>", "resource_ids": ["<catalog id>"]}], '
    '"schedule": [{"day": <1..14>, "focus": "<text>", "outcome": "<text>", '
    '"resource_ids": ["<catalog id>"]}], '
    '"milestones": [{"week": <1|2>, "description": "<text>", "evidence": "<text>"}]}'
)


def plan_study(
    client: LLMClient,
    session_state: Mapping[str, Any],
    *,
    resource_store: ResourceStore | None = None,
    topic_count: int = DEFAULT_STUDY_TOPICS,
    resources_per_topic: int = DEFAULT_RESOURCES_PER_TOPIC,
) -> StudyPlan:
    """Produce a schema-valid StudyPlan from final Skill states and retrieved resources."""
    if topic_count < 1:
        raise ValueError("topic_count must be >= 1")
    if resources_per_topic < 1:
        raise ValueError("resources_per_topic must be >= 1")
    store = resource_store or seed_resource_store(InMemoryResourceStore())
    targets = rank_study_targets(session_state)[:topic_count]
    if not targets:
        raise ValueError("cannot plan study without Skill states")
    matches = retrieve_resource_matches(store, session_state, targets, resources_per_topic=resources_per_topic)
    catalog = _catalog_from_matches(matches)
    draft = client.chat_json(
        _build_study_planner_messages(session_state, targets, matches),
        StudyPlanDraft,
        validators=_make_study_plan_validators(targets, catalog),
        max_retries=1,
    )
    return _materialize_study_plan(
        str(session_state.get("session_id", "unknown-session")),
        draft,
        targets,
        catalog,
    )


def rank_study_targets(session_state: Mapping[str, Any]) -> list[StudyTarget]:
    """Rank Skills by final weakness, Role criticality, and residual uncertainty."""
    targets: list[StudyTarget] = []
    metadata = session_state.get("skill_metadata", {})
    for skill, raw in session_state.get("skill_states", {}).items():
        state = SkillState(skill=str(raw["skill"]), alpha=float(raw["alpha"]), beta=float(raw["beta"]))
        criticality = str(metadata.get(skill, {}).get("role_criticality", "peripheral"))
        weakness = 1.0 - state.mastery
        uncertainty = 1.0 - state.confidence
        priority_score = weakness + _CRITICALITY_BONUS.get(criticality, 0.0) + 0.1 * uncertainty
        targets.append(
            StudyTarget(
                skill=skill,
                mastery=state.mastery,
                confidence=state.confidence,
                role_criticality=criticality,
                priority_score=priority_score,
                query=_gap_query(session_state, skill, state, criticality),
            )
        )
    return sorted(
        targets,
        key=lambda t: (
            -t.priority_score,
            _CRITICALITY_RANK.get(t.role_criticality, 99),
            t.mastery,
            t.skill,
        ),
    )


def retrieve_resource_matches(
    store: ResourceStore,
    session_state: Mapping[str, Any],
    targets: Sequence[StudyTarget],
    *,
    resources_per_topic: int = DEFAULT_RESOURCES_PER_TOPIC,
) -> dict[str, list[ResourceMatch]]:
    """Retrieve learning materials for each target Skill from the resource catalog."""
    matches: dict[str, list[ResourceMatch]] = {}
    for target in targets:
        matches[target.skill] = search_resources(
            store,
            target.query,
            skill=target.skill,
            n_results=resources_per_topic,
        )
    return matches


def _build_study_planner_messages(
    session_state: Mapping[str, Any],
    targets: Sequence[StudyTarget],
    matches: Mapping[str, Sequence[ResourceMatch]],
) -> list[Message]:
    target_lines = "\n".join(
        (
            f"{i}. {target.skill} priority_score={target.priority_score:.3f} "
            f"mastery={target.mastery:.3f} confidence={target.confidence:.3f} "
            f"role_criticality={target.role_criticality}"
        )
        for i, target in enumerate(targets, start=1)
    )
    resource_blocks = []
    for target in targets:
        rendered = "\n\n".join(match.render() for match in matches.get(target.skill, ()))
        resource_blocks.append(f"## {target.skill}\n{rendered or 'No resources retrieved.'}")
    user = (
        f"SESSION:\n"
        f"- session_id: {session_state.get('session_id')}\n"
        f"- stop_reason: {session_state.get('stop_reason')}\n"
        f"- question_count: {session_state.get('question_count', 0)}\n\n"
        f"PRIORITY TARGETS (use these Skills in this exact order):\n{target_lines}\n\n"
        f"RESOURCE CANDIDATES (choose IDs only from here):\n{chr(10).join(resource_blocks)}\n\n"
        f"RESOLVED EVIDENCE:\n{_transcript_evidence(session_state)}\n\n"
        "Produce the StudyPlan. The prioritized_topics array must contain exactly the priority "
        "target Skills above, in the same order, with priorities 1..N. The schedule must contain "
        "exactly days 1 through 14.\n"
        f"Return JSON shaped like:\n{_STUDY_PLAN_SCHEMA_HINT}"
    )
    return [
        {"role": "system", "content": STUDY_PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _make_study_plan_validators(
    targets: Sequence[StudyTarget],
    catalog: Mapping[str, LearningResource],
) -> list[Validator]:
    expected_skills = [target.skill for target in targets]

    def validate(draft: StudyPlanDraft) -> None:
        skills = [topic.skill for topic in draft.prioritized_topics]
        if skills != expected_skills:
            raise ValueError(f"prioritized_topics must use target Skills in order: {expected_skills}")
        priorities = [topic.priority for topic in draft.prioritized_topics]
        if priorities != list(range(1, len(expected_skills) + 1)):
            raise ValueError("prioritized_topics priorities must be exactly 1..N")
        days = [item.day for item in draft.schedule]
        if sorted(days) != list(range(1, 15)):
            raise ValueError("schedule must contain exactly days 1 through 14")
        for topic in draft.prioritized_topics:
            _validate_resource_ids(topic.resource_ids, catalog, require_nonempty=True)
            wrong_skill = [rid for rid in topic.resource_ids if catalog[rid].skill != topic.skill]
            if wrong_skill:
                raise ValueError(f"topic {topic.skill!r} references resources from another Skill: {wrong_skill}")
        resourceless_days = [item.day for item in draft.schedule if not item.resource_ids]
        if len(resourceless_days) > MAX_RESOURCELESS_SCHEDULE_DAYS:
            raise ValueError(
                f"schedule may include at most {MAX_RESOURCELESS_SCHEDULE_DAYS} resource-free review days; "
                f"got days {resourceless_days}"
            )
        for item in draft.schedule:
            if not item.resource_ids and not _is_resource_optional_schedule_item(item):
                raise ValueError(
                    f"schedule day {item.day} has no resource_ids but is not explicitly a review, "
                    "consolidation, synthesis, mock interview, or assessment day"
                )
            # A bounded review day may cite no resource; only the ids it *does* cite must be from the catalog.
            _validate_resource_ids(item.resource_ids, catalog, require_nonempty=False)

    return [validate]


def _validate_resource_ids(
    resource_ids: Sequence[str],
    catalog: Mapping[str, LearningResource],
    *,
    require_nonempty: bool,
) -> None:
    if require_nonempty and not resource_ids:
        raise ValueError("each prioritized topic must include at least one resource_id")
    unknown = sorted(set(resource_ids) - set(catalog))
    if unknown:
        raise ValueError(f"unknown resource_id(s); choose only from retrieved catalog: {unknown}")


def _is_resource_optional_schedule_item(item: StudyScheduleDraft) -> bool:
    text = f"{item.focus} {item.outcome}".lower()
    return any(marker in text for marker in _RESOURCELESS_DAY_MARKERS)


def _materialize_study_plan(
    session_id: str,
    draft: StudyPlanDraft,
    targets: Sequence[StudyTarget],
    catalog: Mapping[str, LearningResource],
) -> StudyPlan:
    target_by_skill = {target.skill: target for target in targets}
    return StudyPlan(
        session_id=session_id,
        readiness_estimate=draft.readiness_estimate,
        readiness_rationale=draft.readiness_rationale,
        prioritized_topics=[
            StudyTopic(
                priority=topic.priority,
                skill=topic.skill,
                title=topic.title,
                rationale=topic.rationale,
                target_mastery=topic.target_mastery,
                mastery=target_by_skill[topic.skill].mastery,
                confidence=target_by_skill[topic.skill].confidence,
                role_criticality=target_by_skill[topic.skill].role_criticality,
                resources=[_dump_resource(catalog[rid]) for rid in topic.resource_ids],
            )
            for topic in draft.prioritized_topics
        ],
        schedule=[
            StudyScheduleItem(
                day=item.day,
                focus=item.focus,
                outcome=item.outcome,
                resources=[_dump_resource(catalog[rid]) for rid in item.resource_ids],
            )
            for item in sorted(draft.schedule, key=lambda item: item.day)
        ],
        milestones=[
            StudyMilestone(
                week=milestone.week,
                description=milestone.description,
                evidence=milestone.evidence,
            )
            for milestone in draft.milestones
        ],
    )


def _dump_resource(resource: LearningResource) -> StudyResource:
    return StudyResource(
        id=resource.id,
        skill=resource.skill,
        title=resource.title,
        url=resource.url,
        summary=resource.summary,
        resource_type=resource.resource_type,
        effort_minutes=resource.effort_minutes,
    )


def _catalog_from_matches(matches: Mapping[str, Sequence[ResourceMatch]]) -> dict[str, LearningResource]:
    catalog: dict[str, LearningResource] = {}
    for skill_matches in matches.values():
        for match in skill_matches:
            catalog[match.resource.id] = match.resource
    return catalog


def _gap_query(
    session_state: Mapping[str, Any],
    skill: str,
    state: SkillState,
    criticality: str,
) -> str:
    weak_dimensions: list[str] = []
    rationales: list[str] = []
    for item in session_state.get("transcript", []):
        if item.get("skill") != skill:
            continue
        for turn in item.get("turns", []):
            evaluation = turn.get("evaluation", {})
            rationales.append(str(evaluation.get("follow_up_rationale", "")))
            dimensions = evaluation.get("dimensions", {})
            for dim, score in sorted(
                dimensions.items(),
                key=lambda kv: kv[1].get("score", 5) if isinstance(kv[1], Mapping) else 5,
            ):
                if isinstance(score, Mapping) and float(score.get("score", 5)) <= 3:
                    weak_dimensions.append(dim)
    details = " ".join([*weak_dimensions[:4], *rationales[:2]])
    return (
        f"{skill} interview gap mastery {state.mastery:.2f} confidence {state.confidence:.2f} "
        f"role criticality {criticality} weak dimensions {details}"
    )


def _transcript_evidence(session_state: Mapping[str, Any]) -> str:
    rows = []
    for i, item in enumerate(session_state.get("transcript", []), start=1):
        rows.append(
            f"- Q{i} skill={item.get('skill')} score={float(item.get('resolved_weighted_score', 0)):.2f}/5 "
            f"confidence={float(item.get('resolved_confidence', 0)):.2f} stop={item.get('stop_reason')}"
        )
        for turn_n, turn in enumerate(item.get("turns", []), start=1):
            evaluation = turn.get("evaluation", {})
            weak = []
            for dim, score in evaluation.get("dimensions", {}).items():
                if isinstance(score, Mapping) and float(score.get("score", 5)) <= 3:
                    weak.append(f"{dim}={score.get('score')}")
            if weak:
                rows.append(f"  - turn {turn_n} weak_dimensions: {', '.join(weak)}")
            if rationale := evaluation.get("follow_up_rationale"):
                rows.append(f"  - turn {turn_n} follow_up_rationale: {rationale}")
    return "\n".join(rows) or "- none"
