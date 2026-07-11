"""Demo-only LLM client for the local web MVP.

This client exists so the React UI can be reviewed without provider credentials. It deliberately
lives outside provider routing: real Sessions still use ``build_client(load_settings())`` and all
production agents continue to depend only on ``LLMClient``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from .diagnostic import SKILLS
from .llm import LLMClient, Message, ResponseFormat, Validator
from .resources import SEED_RESOURCES
from .rubric import DIMENSIONS

T = TypeVar("T", bound=BaseModel)


class DemoLLMClient(LLMClient):
    """Schema-valid deterministic responses for offline UX review."""

    def chat(
        self,
        messages: Sequence[Message],
        *,
        response_format: ResponseFormat | None = None,
        disable_thinking: bool = False,
    ) -> str:
        return json.dumps({"demo": True})

    def chat_json(
        self,
        messages: Sequence[Message],
        response_model: type[T],
        *,
        validators: Sequence[Validator] = (),
        max_retries: int = 1,
        disable_thinking: bool = False,
    ) -> T:
        payload = self._payload_for(response_model, messages)
        parsed = response_model.model_validate(payload)
        for validate in validators:
            validate(parsed)
        return parsed

    def _payload_for(self, response_model: type[BaseModel], messages: Sequence[Message]) -> dict[str, Any]:
        name = response_model.__name__
        text = "\n\n".join(str(message.get("content", "")) for message in messages)
        if name == "DiagnosticPlanResponse":
            return {
                "topic_plan": [
                    {
                        "skill": skill,
                        "target_difficulty": 3 if skill != "mlops" else 4,
                        "rationale": f"Demo Topic Plan probes {skill} with role-aware priority.",
                    }
                    for skill in SKILLS
                ]
            }
        if name == "Evaluation":
            return self._evaluation_payload(text)
        if name == "SupervisorDecision":
            return {
                "action": "advance_plan",
                "reasoning": "Demo Supervisor follows the Topic Plan unless a hard cap completes the Session.",
                "target_skill": None,
                "target_plan_index": None,
            }
        if name == "StudyPlanDraft":
            return self._study_plan_payload(text)
        if name == "ConceptToolRequest":
            return {
                "query": "core mechanism and failure mode",
                "skill": self._target_skill(text),
                "language": "vi" if self._target_skill(text) == "vietnamese_nlp" else None,
                "reason": "Demo lookup grounds the Follow-up in the active Skill.",
            }
        if name == "FollowUp":
            return {
                "question": "Using the retrieved mechanism, what concrete failure mode would you watch for?",
                "targets": "mechanism and failure-mode depth from the retrieved concept note",
            }
        return {}

    def _evaluation_payload(self, prompt: str) -> dict[str, Any]:
        answer = self._section(prompt, "CANDIDATE ANSWER", "RUBRIC")
        active = self._active_dimensions(prompt)
        score = self._score_answer(answer)
        evidence = self._evidence(answer)
        payload: dict[str, Any] = {
            "dimensions": {dim: {"score": score, "evidence": evidence} for dim in active},
            "weighted_score": float(score),
            "confidence": 0.82 if answer.strip() else 0.7,
            "follow_up_recommended": False,
            "follow_up_rationale": "Demo Evaluator keeps the loop short so the web workflow can be reviewed.",
        }
        if "english_delivery" in active and score <= 3:
            # Issue 0024: a weak english_delivery score must carry >= 3 phrase-level fixes or the
            # Evaluator's validator rejects the payload.
            payload["delivery_fixes"] = [
                'Demo fix: "model is overfit" — "the model is overfitting"',
                'Demo fix: "it depend on data" — "it depends on the data"',
                'Demo fix: "we should to monitor" — "we should monitor"',
            ]
        return payload

    def _study_plan_payload(self, prompt: str) -> dict[str, Any]:
        skills = self._priority_skills(prompt) or list(SKILLS[:3])
        ids_by_skill: dict[str, list[str]] = {}
        for resource in SEED_RESOURCES:
            ids_by_skill.setdefault(resource.skill, []).append(resource.id)
        topics = [
            {
                "priority": i,
                "skill": skill,
                "title": f"Sharpen {skill.replace('_', ' ')}",
                "rationale": "Demo Study Planner prioritizes the weakest or most role-critical Skill state.",
                "target_mastery": "Give a concise answer with mechanism, trade-off, and deployment implication.",
                "resource_ids": ids_by_skill.get(skill, [SEED_RESOURCES[0].id])[:2],
            }
            for i, skill in enumerate(skills, start=1)
        ]
        schedule = []
        flat_ids = [rid for topic in topics for rid in topic["resource_ids"]]
        for day in range(1, 15):
            if day in {7, 14}:
                schedule.append(
                    {
                        "day": day,
                        "focus": "Review and mock interview synthesis",
                        "outcome": "Record one timed answer and compare it against the rubric.",
                        "resource_ids": [],
                    }
                )
            else:
                schedule.append(
                    {
                        "day": day,
                        "focus": f"Practice {skills[(day - 1) % len(skills)].replace('_', ' ')}",
                        "outcome": "Write one answer with a concrete trade-off and failure mode.",
                        "resource_ids": [flat_ids[(day - 1) % len(flat_ids)]],
                    }
                )
        return {
            "readiness_estimate": 0.58,
            "readiness_rationale": "Demo estimate: usable baseline with several targeted gaps to practice.",
            "prioritized_topics": topics,
            "schedule": schedule,
            "milestones": [
                {
                    "week": 1,
                    "description": "Answer the top-priority Skill without notes.",
                    "evidence": "A recorded three-minute answer covers mechanism and trade-offs.",
                },
                {
                    "week": 2,
                    "description": "Run a mixed mock interview under time pressure.",
                    "evidence": "Every planned Skill has one complete answer and one Follow-up response.",
                },
            ],
        }

    def _active_dimensions(self, prompt: str) -> list[str]:
        found = []
        for dim in DIMENSIONS:
            # english_delivery renders with an "assessed separately" marker instead of a weight
            # (issue 0024), but the judge must still score it when listed.
            if re.search(rf"^- {re.escape(dim)} \((?:weight |assessed separately)", prompt, flags=re.MULTILINE):
                found.append(dim)
        return found or ["correctness"]

    def _score_answer(self, answer: str) -> int:
        words = re.findall(r"[A-Za-z0-9_]+", answer)
        lower = answer.lower()
        if not words:
            return 1
        score = 2
        if len(words) >= 25:
            score += 1
        if any(term in lower for term in ("trade", "because", "monitor", "validation", "regularization")):
            score += 1
        if any(term in lower for term in ("failure", "rollback", "latency", "leakage", "drift")):
            score += 1
        return max(1, min(score, 5))

    def _evidence(self, answer: str) -> str:
        words = answer.strip().split()
        if not words:
            return "no evidence"
        return " ".join(words[: min(12, len(words))])

    def _priority_skills(self, prompt: str) -> list[str]:
        skills = []
        for line in prompt.splitlines():
            match = re.match(r"\d+\.\s+([a-z_]+)\s+priority_score=", line.strip())
            if match:
                skills.append(match.group(1))
        return skills

    def _target_skill(self, prompt: str) -> str | None:
        match = re.search(r"TARGET SKILL:\n([a-z_]+)", prompt)
        return match.group(1) if match else None

    def _section(self, prompt: str, start: str, end: str) -> str:
        pattern = rf"{re.escape(start)}:\n(.*?)(?:\n\n{re.escape(end)}|$)"
        match = re.search(pattern, prompt, flags=re.DOTALL)
        return match.group(1).strip() if match else ""
