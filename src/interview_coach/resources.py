"""Learning resource retrieval for the Study Planner (slice 0011).

One store: the deterministic in-memory ASCII-Jaccard one. There used to be a Chroma-backed
alternative behind ``--resource-store chroma``; it was deleted under GH #130 and this is the
reasoning, so nobody rebuilds it by accident.

``SEED_RESOURCES`` is 10 entries across 5 Skills — two each — and ``InMemoryResourceStore.search``
hard-filters on ``skill=`` before it ranks. The ranker is therefore choosing between two candidates,
and no embedder improves a choice between two candidates. Meanwhile the Chroma half was never on any
default path: the web API hardcoded ``memory``, both CLI call sites defaulted to it, there was no
``Settings`` field and no ``"auto"`` branch, so it was a flag, an ingest command and ~110 lines
carrying a maintenance cost against zero measured benefit — including a hand-written guard against
e5-family embedders it could not encode for.

Rebuild it when the catalog passes the shelf-size threshold already recorded for concepts
(``concepts.py:351``, ~20-25 per Skill), or when ADR 0014 taxonomy-as-data grows it. The concept
store's prefix-aware path is the model to copy; `git log --diff-filter=D -- src/interview_coach`
finds the deleted class if it is ever wanted back.

The Planner never calls this as a tool; Python retrieves resource candidates first, then injects
them into the single-shot Planner prompt.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LearningResource:
    """A catalog entry the Study Planner may assign to a Candidate."""

    id: str
    skill: str
    title: str
    url: str
    summary: str
    resource_type: str = "article"
    effort_minutes: int = 45
    tags: tuple[str, ...] = ()

    def metadata(self) -> dict[str, str | int]:
        return {
            "id": self.id,
            "skill": self.skill,
            "title": self.title,
            "url": self.url,
            "resource_type": self.resource_type,
            "effort_minutes": self.effort_minutes,
            "tags": ",".join(self.tags),
        }


@dataclass(frozen=True)
class ResourceMatch:
    """A retrieved resource plus a store-specific similarity score."""

    resource: LearningResource
    score: float | None = None

    def render(self) -> str:
        score = "n/a" if self.score is None else f"{self.score:.3f}"
        return (
            f"ID: {self.resource.id}\n"
            f"TITLE: {self.resource.title}\n"
            f"SKILL: {self.resource.skill}\n"
            f"TYPE: {self.resource.resource_type}\n"
            f"EFFORT_MINUTES: {self.resource.effort_minutes}\n"
            f"URL: {self.resource.url}\n"
            f"SIMILARITY: {score}\n"
            f"SUMMARY:\n{self.resource.summary}"
        )


class ResourceStore(Protocol):
    """Store abstraction used by the Study Planner."""

    def ingest(self, resources: Iterable[LearningResource]) -> int: ...

    def search(
        self,
        query: str,
        *,
        skill: str | None = None,
        n_results: int = 3,
    ) -> list[ResourceMatch]: ...


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text) if len(t) > 2}


class InMemoryResourceStore:
    """Small deterministic store for tests and local demos."""

    def __init__(self, resources: Sequence[LearningResource] = ()) -> None:
        self._resources: dict[str, LearningResource] = {}
        self.search_calls: list[dict[str, str | int | None]] = []
        self.ingest(resources)

    def ingest(self, resources: Iterable[LearningResource]) -> int:
        count = 0
        for resource in resources:
            self._resources[resource.id] = resource
            count += 1
        return count

    def search(
        self,
        query: str,
        *,
        skill: str | None = None,
        n_results: int = 3,
    ) -> list[ResourceMatch]:
        if n_results < 1:
            raise ValueError("n_results must be >= 1")
        self.search_calls.append({"query": query, "skill": skill, "n_results": n_results})
        candidates = [resource for resource in self._resources.values() if skill is None or resource.skill == skill]
        if not candidates:
            raise LookupError(f"no resources match skill={skill!r}")

        q = _tokens(query)

        def rank(resource: LearningResource) -> tuple[float, str]:
            body = _tokens(f"{resource.title} {resource.summary} {' '.join(resource.tags)}")
            overlap = len(q & body)
            denom = max(1, len(q | body))
            return (overlap / denom, resource.id)

        ordered = sorted(candidates, key=rank, reverse=True)[:n_results]
        return [ResourceMatch(resource=resource, score=rank(resource)[0]) for resource in ordered]


SEED_RESOURCES: tuple[LearningResource, ...] = (
    LearningResource(
        id="ml_fundamentals_cross_validation",
        skill="ml_fundamentals",
        title="scikit-learn: Cross-validation",
        url="https://scikit-learn.org/stable/modules/cross_validation.html",
        summary=(
            "A practical reference for validation splits, cross-validation iterators, leakage traps, "
            "and when grouped or time-aware evaluation is required."
        ),
        resource_type="documentation",
        effort_minutes=60,
        tags=("cross_validation", "evaluation", "leakage", "model_selection"),
    ),
    LearningResource(
        id="ml_fundamentals_ridge_regularization",
        skill="ml_fundamentals",
        title="scikit-learn: Ridge regression and L2 regularization",
        url="https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html",
        summary=(
            "A focused reference for L2-regularized linear models, useful for connecting penalties, "
            "coefficient shrinkage, variance control, and model selection."
        ),
        resource_type="documentation",
        effort_minutes=35,
        tags=("regularization", "ridge", "l2", "bias_variance"),
    ),
    LearningResource(
        id="deep_learning_resnet_d2l",
        skill="deep_learning",
        title="Dive into Deep Learning: Residual Networks",
        url="https://d2l.ai/chapter_convolutional-modern/resnet.html",
        summary=(
            "A hands-on chapter on residual connections, ResNet blocks, and why skip paths make "
            "very deep networks easier to optimize."
        ),
        resource_type="book_chapter",
        effort_minutes=75,
        tags=("resnet", "skip_connections", "optimization", "gradient_flow"),
    ),
    LearningResource(
        id="deep_learning_pytorch_transfer_learning",
        skill="deep_learning",
        title="PyTorch Tutorial: Transfer Learning for Computer Vision",
        url="https://docs.pytorch.org/tutorials/beginner/transfer_learning_tutorial.html",
        summary=(
            "A practical PyTorch tutorial for fine-tuning and feature-extraction workflows, useful "
            "for discussing representation reuse and training loops concretely."
        ),
        resource_type="tutorial",
        effort_minutes=90,
        tags=("pytorch", "fine_tuning", "transfer_learning", "training_loop"),
    ),
    LearningResource(
        id="mlops_google_rules",
        skill="mlops",
        title="Google: Rules of Machine Learning",
        url="https://developers.google.com/machine-learning/guides/rules-of-ml",
        summary=(
            "A production-minded guide to launching, monitoring, iterating, and debugging ML systems "
            "as they move from heuristics to learned models."
        ),
        resource_type="guide",
        effort_minutes=90,
        tags=("production_ml", "monitoring", "launch", "debugging"),
    ),
    LearningResource(
        id="mlops_google_cloud_architecture",
        skill="mlops",
        title="Google Cloud: ML applications and operations architecture guides",
        url="https://docs.cloud.google.com/architecture/ai-ml/ml-application-operations-architecture-guides",
        summary=(
            "A catalog of MLOps architecture guides covering custom training, pipelines, model "
            "serving, and operational concerns across the ML lifecycle."
        ),
        resource_type="documentation",
        effort_minutes=60,
        tags=("mlops", "pipelines", "serving", "architecture", "lifecycle"),
    ),
    LearningResource(
        id="system_design_backpressure_rate_limiting",
        skill="system_design",
        title="Microsoft Azure Architecture Center: Rate Limiting pattern",
        url="https://learn.microsoft.com/en-us/azure/architecture/patterns/rate-limiting-pattern",
        summary=(
            "A cloud architecture pattern for protecting downstream systems, setting limits, and "
            "making overload behavior explicit instead of letting queues grow without bound."
        ),
        resource_type="documentation",
        effort_minutes=45,
        tags=("rate_limiting", "backpressure", "resilience", "overload"),
    ),
    LearningResource(
        id="system_design_event_driven_architecture",
        skill="system_design",
        title="Microsoft Azure Architecture Center: Event-driven architecture",
        url="https://learn.microsoft.com/en-us/azure/architecture/guide/architecture-styles/event-driven",
        summary=(
            "A reference for event-driven architecture tradeoffs, asynchronous processing, brokered "
            "messages, consumers, scaling, and back pressure."
        ),
        resource_type="documentation",
        effort_minutes=60,
        tags=("event_driven", "queues", "scaling", "backpressure"),
    ),
    LearningResource(
        id="vietnamese_nlp_phobert",
        skill="vietnamese_nlp",
        title="VinAI PhoBERT model card",
        url="https://huggingface.co/vinai/phobert-base",
        summary=(
            "The PhoBERT model card, useful for discussing Vietnamese pretrained language models, "
            "tokenization assumptions, and when to fine-tune domain data."
        ),
        resource_type="model_card",
        effort_minutes=35,
        tags=("phobert", "pretraining", "tokenization", "fine_tuning"),
    ),
    LearningResource(
        id="vietnamese_nlp_vncorenlp",
        skill="vietnamese_nlp",
        title="VnCoreNLP: Vietnamese NLP toolkit",
        url="https://github.com/vncorenlp/VnCoreNLP",
        summary=(
            "The VnCoreNLP toolkit repository, covering Vietnamese word segmentation, POS tagging, "
            "NER, and dependency parsing with a practical command-line and API workflow."
        ),
        resource_type="repository",
        effort_minutes=45,
        tags=("vncorenlp", "word_segmentation", "ner", "pos_tagging", "vietnamese"),
    ),
)


def seed_resource_store(store: ResourceStore | None = None) -> ResourceStore:
    """Create or fill a resource store with the built-in seed catalog."""
    target = store or InMemoryResourceStore()
    target.ingest(SEED_RESOURCES)
    return target


def build_resource_store(*, seed: bool = True) -> ResourceStore:
    """Build the resource store used by the Study Planner."""
    store: ResourceStore = InMemoryResourceStore()
    if seed:
        store.ingest(SEED_RESOURCES)
    return store


def search_resources(
    store: ResourceStore,
    query: str,
    *,
    skill: str | None = None,
    n_results: int = 3,
) -> list[ResourceMatch]:
    """Search the learning-resource catalog."""
    logger.info("search_resources(query=%r, skill=%r, n_results=%d)", query, skill, n_results)
    return store.search(query, skill=skill, n_results=n_results)
