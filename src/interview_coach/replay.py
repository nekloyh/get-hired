"""Simulated Candidate + Supervisor replay bench (issue 0029).

The calibration bench (0022) measures the *judge*; this measures the *loop* — whether a whole Session
converges on the truth about a candidate. A persona-driven Candidate with a ground-truth mastery
profile is plugged into the existing Candidate seam, a runner drives a full unattended Session, and
the run asserts *trajectory* properties (final posterior mastery ordering vs ground truth; the
Supervisor not burning budget on a Skill the persona is strong at) rather than per-call outputs.

The checkpointed trajectory is dumped as a versioned replay artifact so the Supervisor's decision node
can be re-run over it in isolation — the seed of decision-level regression testing (e.g. swap the
model behind ``decide_next_move`` and compare).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .diagnostic import SKILLS, CandidateProfile, diagnose
from .language import DEFAULT_LANGUAGE_MODE
from .llm import LLMClient, Message
from .seeds import SeedQuestion
from .skill import SkillState
from .supervisor import (
    SupervisorDecision,
    build_session_graph,
    decide_next_move,
    initial_session_state,
    session_config,
)

REPLAY_ARTIFACT_VERSION = 1


@dataclass(frozen=True)
class Persona:
    """A simulated Candidate with a ground-truth mastery profile."""

    name: str
    mastery: Mapping[str, float]  # ground-truth competence in [0, 1] per Skill
    style: str = "answers plainly"
    target_role: str = "machine learning engineer"
    target_companies: tuple[str, ...] = ()

    def level_word(self, skill: str) -> str:
        m = self.mastery.get(skill, 0.5)
        return "strong" if m > 0.66 else "weak" if m < 0.34 else "moderate"

    def profile(self) -> CandidateProfile:
        # The persona does not self-claim: ground truth must emerge from how the judge scores its
        # answers, not from a claim seeding the prior (ADR 0002).
        return CandidateProfile(target_role=self.target_role, target_companies=self.target_companies)


def ground_truth_ordering(persona: Persona) -> list[str]:
    """Skills ranked by the persona's true mastery, strongest first."""
    return sorted(SKILLS, key=lambda s: persona.mastery.get(s, 0.5), reverse=True)


class PersonaCandidate:
    """An LLM-backed Candidate that answers in character for a persona's mastery of the asked Skill.

    Created per question via ``candidate_factory(seed)``, so it knows the Skill being probed and can
    answer strongly on the persona's strong Skills and vaguely on its weak ones. Uses its *own* client
    so the persona's answers never draw from the judge/supervisor call budget.
    """

    def __init__(self, client: LLMClient, persona: Persona, skill: str) -> None:
        self._client = client
        self._persona = persona
        self._skill = skill

    def answer(self, question: str) -> str:
        level = self._persona.level_word(self._skill)
        system = (
            "You are a job candidate in a technical interview. Answer in the first person, in 2–4 "
            f"sentences. Your true ability on this topic ({self._skill}) is {level}. {self._persona.style}. "
            "If your ability is strong, give a correct, specific, well-reasoned answer; if weak, give a "
            "vague, partially-incorrect, or incomplete answer; if moderate, give a mostly-right but "
            "shallow answer. Stay consistent with that ability — do not overperform or underperform it."
        )
        messages: list[Message] = [
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ]
        return self._client.chat(messages)


def persona_candidate_factory(client: LLMClient, persona: Persona) -> Callable[[SeedQuestion], PersonaCandidate]:
    return lambda seed: PersonaCandidate(client, persona, seed.skill)


def run_persona_session(
    judge_client: LLMClient,
    persona: Persona,
    *,
    session_id: str,
    candidate_client: LLMClient | None = None,
    max_questions: int = 5,
    checkpointer: Any | None = None,
    now: Callable[[], float] = time.time,
    language_mode: str = DEFAULT_LANGUAGE_MODE,
) -> dict[str, Any]:
    """Drive a full unattended Session with the persona answering; return the final state.

    ``judge_client`` scores answers and runs the Supervisor; ``candidate_client`` (default: the judge
    client) generates the persona's answers. The Topic Plan is the deterministic offline plan so the
    trajectory depends only on the persona and the judge. ``language_mode`` (0024) lets a replay
    exercise a vn/mixed trajectory — without it the loop-level bench would be structurally en-only.
    """
    factory = persona_candidate_factory(candidate_client or judge_client, persona)
    graph = build_session_graph(judge_client, checkpointer=checkpointer, candidate_factory=factory, now=now)
    diagnostic = diagnose(persona.profile(), None)
    state = initial_session_state(
        session_id, diagnostic, max_questions=max_questions, started_at=now(), language_mode=language_mode
    )
    return graph.invoke(state, session_config(session_id))


def posterior_masteries(final_state: Mapping[str, Any]) -> dict[str, float]:
    """Per-Skill posterior mastery from a finished Session's state."""
    out: dict[str, float] = {}
    for skill, raw in final_state.get("skill_states", {}).items():
        out[skill] = SkillState(skill=str(raw["skill"]), alpha=float(raw["alpha"]), beta=float(raw["beta"])).mastery
    return out


def probed_ordering(final_state: Mapping[str, Any]) -> list[str]:
    """Skills that were actually probed, ranked by posterior mastery (strongest first)."""
    probed = {item["skill"] for item in final_state.get("transcript", []) if item.get("turns")}
    masteries = posterior_masteries(final_state)
    return sorted(probed, key=lambda s: masteries.get(s, 0.5), reverse=True)


def attempts_by_skill(final_state: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in final_state.get("transcript", []):
        counts[item["skill"]] = counts.get(item["skill"], 0) + 1
    return counts


@dataclass(frozen=True)
class ReplayArtifact:
    """A versioned dump of a Session trajectory for decision-level replay."""

    version: int
    persona: str
    final_state: dict[str, Any]
    ground_truth: dict[str, float] = field(default_factory=dict)


def dump_replay_artifact(path: str | Path, persona: Persona, final_state: Mapping[str, Any]) -> Path:
    """Persist a trajectory as a versioned JSON replay artifact."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": REPLAY_ARTIFACT_VERSION,
        "persona": persona.name,
        "ground_truth": dict(persona.mastery),
        "final_state": dict(final_state),
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def load_replay_artifact(path: str | Path) -> ReplayArtifact:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != REPLAY_ARTIFACT_VERSION:
        raise ValueError(f"unsupported replay artifact version {data.get('version')!r}")
    return ReplayArtifact(
        version=int(data["version"]),
        persona=str(data["persona"]),
        final_state=dict(data["final_state"]),
        ground_truth={k: float(v) for k, v in data.get("ground_truth", {}).items()},
    )


def replay_decision(
    artifact: ReplayArtifact,
    client: LLMClient,
    *,
    now: Callable[[], float] = time.time,
) -> SupervisorDecision:
    """Re-run the Supervisor's decision node over a dumped trajectory with a (possibly different) model.

    The counterfactual: "given exactly this state, what would model X decide?" — the seed of
    decision-level regression testing across model swaps.
    """
    return decide_next_move(client, artifact.final_state, now=now)
