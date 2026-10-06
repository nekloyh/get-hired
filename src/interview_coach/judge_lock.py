"""The judge fingerprint and its lock (#141, ADR 0009 addendum g).

ADR 0009: any change to the Evaluator (its prompt, its structured-output path, the model behind it)
must pass ``coach bench`` before it merges. Before this module, deciding whether a change *was* a
judge change was up to whoever reviewed it. The fingerprint turns that into a fact a test checks. It is the
sha256 of the exact requests the judge would send — ``model``, ``temperature``, ``messages`` and
``response_format``, built by the production client's own ``request_kwargs`` — for three canonical
answers that between them walk every request path ``evaluate`` has: the first pass, both
judge-specific repair messages (evidence, weak delivery), and the Panel's skeptic, advocate and
verdict. Scripted replies stand in for the provider, so nothing is called, billed or written to the
usage ledger.

A refactor that sends the same bytes leaves the fingerprint unchanged. A change to a prompt, a rubric
anchor, the schema, the escalation policy, the model, the temperature or the endpoint moves it.

``judge.lock`` at the repo root names the fingerprint the current bench baseline measured, and
``tests/test_judge_lock.py`` fails when the code's fingerprint differs from it. That failure IS the
ADR 0009 gate surfacing in CI: run the confirm bench, then update the lock with the new artifact.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .config import BENCH_VALIDATED_JUDGES, ProviderName, ProviderSettings, Settings
from .evaluator import evaluate
from .language import ENGLISH_DELIVERY_WEIGHT
from .llm import _CLIENT_CLASSES, LLMClient, Message, ResponseFormat, _OpenAICompatibleClient
from .rubric import Rubric

JUDGE_LOCK_PATH = Path(__file__).resolve().parents[2] / "judge.lock"

_EN_ANSWER = (
    "Bias is error from wrong assumptions, so the model underfits. Variance is error from sensitivity "
    "to the training sample, so the model overfits. Regularization and more data trade one for the other."
)
_VN_ANSWER = (
    "Overfitting là khi mô hình học thuộc dữ liệu huấn luyện nên lỗi trên tập validation tăng. "
    "Có thể dùng dropout, early stopping hoặc thêm dữ liệu để giảm overfitting."
)
_MIXED_ANSWER = (
    "A cache sits in front of the database. Khi cache miss thì đọc từ database rồi ghi vào cache, "
    "and a TTL bounds how stale the cached data can be before it is read again."
)


def _evaluation(
    rubric: Rubric,
    quote: str,
    *,
    score: int = 4,
    confidence: float = 0.9,
    delivery: int | None = None,
    fixes: Sequence[str] = (),
) -> str:
    """One scripted judge reply. Every technical score is ``score``, so the cross-check never fires."""
    dimensions = {name: {"score": score, "evidence": quote} for name in rubric.active}
    if delivery is not None:
        dimensions["english_delivery"] = {"score": delivery, "evidence": quote}
    body: dict[str, Any] = {
        "dimensions": dimensions,
        "weighted_score": float(score),
        "confidence": confidence,
        "follow_up_recommended": False,
        "follow_up_rationale": "The answer states the core idea; nothing is left to probe.",
    }
    if "english_delivery" in rubric.active:
        body["delivery_fixes"] = list(fixes)
    return json.dumps(body, ensure_ascii=False)


def _opinion(score: float, argument: str, evidence: str) -> str:
    return json.dumps({"recommended_score": score, "argument": argument, "key_evidence": evidence}, ensure_ascii=False)


@dataclass(frozen=True)
class CanonicalCase:
    """One fixed answer plus the provider replies that walk it down a known request path."""

    case_id: str
    path: str
    question: str
    answer: str
    rubric: Rubric
    language_mode: str
    replies: tuple[str, ...]


_EN_RUBRIC = Rubric(weights={"correctness": 0.4, "depth": 0.3, "communication": 0.2, "mlops_awareness": 0.1})
_VN_RUBRIC = Rubric(weights={"correctness": 0.4, "depth": 0.3, "system_thinking": 0.3})
_MIXED_RUBRIC = Rubric(
    weights={
        "correctness": 0.5,
        "system_thinking": 0.3,
        "communication": 0.2,
        "english_delivery": ENGLISH_DELIVERY_WEIGHT,
    }
)
_MIXED_QUOTE = "a TTL bounds how stale the cached data can be"
_MIXED_FIXES = (
    "'sits in front of the database' -> 'sits between the service and the database'",
    "'read again' -> 'refreshed from the source'",
    "'how stale the cached data can be' -> 'how stale a cached entry may get'",
)

# Between them the three cases activate every rubric dimension, every Session language mode, both
# system-prompt variants (with and without the delivery rules) and every request path in `evaluate`.
# `judge_requests` refuses a case whose scripted replies are not consumed exactly, so a change that
# moves a case off its path fails loudly instead of silently fingerprinting a shorter walk.
CANONICAL_CASES: tuple[CanonicalCase, ...] = (
    CanonicalCase(
        case_id="en_first_pass",
        path="confident first pass: one request",
        question="Explain the bias-variance trade-off.",
        answer=_EN_ANSWER,
        rubric=_EN_RUBRIC,
        language_mode="en",
        replies=(_evaluation(_EN_RUBRIC, "so the model underfits"),),
    ),
    CanonicalCase(
        case_id="vn_panel",
        path="low-confidence first pass escalates: first pass, skeptic, advocate, verdict",
        question="Overfitting là gì và làm sao để giảm nó?",
        answer=_VN_ANSWER,
        rubric=_VN_RUBRIC,
        language_mode="vn",
        replies=(
            _evaluation(_VN_RUBRIC, "thêm dữ liệu", score=3, confidence=0.3),
            _opinion(2.0, "Names remedies without saying why they reduce variance.", "dropout, early stopping"),
            _opinion(4.0, "Defines overfitting by its symptom on held-out data.", "lỗi trên tập validation tăng"),
            _evaluation(_VN_RUBRIC, "thêm dữ liệu", score=3, confidence=0.8),
        ),
    ),
    CanonicalCase(
        case_id="mixed_repairs",
        path="evidence repair, then weak-delivery repair, then a valid reply",
        question="How would you put a cache in front of a slow database?",
        answer=_MIXED_ANSWER,
        rubric=_MIXED_RUBRIC,
        language_mode="mixed",
        replies=(
            _evaluation(_MIXED_RUBRIC, "the TTL limits staleness"),
            _evaluation(_MIXED_RUBRIC, _MIXED_QUOTE, delivery=2),
            _evaluation(_MIXED_RUBRIC, _MIXED_QUOTE, delivery=2, fixes=_MIXED_FIXES),
        ),
    ),
)


class _RecordingJudge(LLMClient):
    """The production judge client's request builder, with a script where the provider would be."""

    def __init__(self, judge: _OpenAICompatibleClient, replies: Sequence[str]) -> None:
        self._judge = judge
        self._replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    @property
    def supports_json_schema(self) -> bool:
        return self._judge.supports_json_schema

    @property
    def unused_replies(self) -> int:
        return len(self._replies) - len(self.requests)

    def chat(self, messages: Sequence[Message], *, response_format: ResponseFormat | None = None) -> str:
        if len(self.requests) == len(self._replies):
            raise RuntimeError("the judge asked for more replies than this canonical case scripts")
        # Round-trip through JSON so the record is plain data and later mutation cannot reach it.
        self.requests.append(
            json.loads(json.dumps(self._judge.request_kwargs(messages, response_format=response_format)))
        )
        return self._replies[len(self.requests) - 1]


@contextmanager
def _quiet() -> Iterator[None]:
    """The scripted repairs log warnings a reader would take for real provider trouble; mute them."""
    root = logging.getLogger("interview_coach")
    previous = root.level
    root.setLevel(logging.ERROR)
    try:
        yield
    finally:
        root.setLevel(previous)


def validated_judges() -> list[_OpenAICompatibleClient]:
    """Every bench-validated judge, exactly as code defaults would seat it (no env, no API key)."""
    temperature = Settings.model_fields["temperature"].default
    judges: list[_OpenAICompatibleClient] = []
    for provider, model, base_url in sorted(BENCH_VALIDATED_JUDGES):
        name = cast(ProviderName, provider)
        settings = ProviderSettings(name=name, base_url=base_url, model=model, temperature=temperature)
        judges.append(_CLIENT_CLASSES[name](settings))
    return judges


def judge_requests(judge: _OpenAICompatibleClient) -> dict[str, list[dict[str, Any]]]:
    """The requests ``judge`` would send for each canonical case, keyed by case id."""
    recorded: dict[str, list[dict[str, Any]]] = {}
    with _quiet():
        for case in CANONICAL_CASES:
            recorder = _RecordingJudge(judge, case.replies)
            evaluate(recorder, case.question, case.answer, case.rubric, language_mode=case.language_mode)
            if recorder.unused_replies:
                raise RuntimeError(
                    f"canonical case {case.case_id!r} no longer walks its path ({case.path}): "
                    f"{recorder.unused_replies} scripted repl(ies) unused. The escalation or repair "
                    f"policy changed; update the case in judge_lock.py, then treat it as a judge change."
                )
            recorded[case.case_id] = recorder.requests
    return recorded


def judge_fingerprint(judges: Sequence[_OpenAICompatibleClient] | None = None) -> str:
    """``sha256:<hex>`` over what each judge would send for every canonical case.

    ``judges`` defaults to the bench-validated judges as code builds them. That is what
    ``judge.lock`` pins. ``coach bench`` passes the judge it actually ran, so an env override (say
    ``ROLE_JUDGE_TEMPERATURE``) shows up as a different fingerprint in the report.
    """
    seated = list(judges) if judges is not None else validated_judges()
    payload = [
        {
            "provider": judge.provider_name,
            "endpoint": judge._settings.base_url.rstrip("/"),
            "requests": judge_requests(judge),
        }
        for judge in seated
    ]
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fingerprint_of(judge: LLMClient) -> str | None:
    """The fingerprint of the judge ``coach bench`` actually ran, or None for a non-provider client.

    A demo brain has no request to fingerprint. A test double is a real provider client with a
    scripted transport, and it fingerprints like the real thing, because the transport is never used.
    """
    return judge_fingerprint([judge]) if isinstance(judge, _OpenAICompatibleClient) else None


def load_judge_lock(path: Path = JUDGE_LOCK_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data
