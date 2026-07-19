"""Learning resource retrieval for the Study Planner (slice 0011).

The production path is a Chroma ``resources`` collection using the same BGE small English embedder
as concept retrieval. Tests and offline demos use a deterministic in-memory implementation, but the
Planner sees the same catalog IDs either way. The Planner never calls this as a tool; Python
retrieves resource candidates first, then injects them into the single-shot Planner prompt.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .concepts import BGE_SMALL_EN

logger = logging.getLogger(__name__)

RESOURCE_COLLECTION = "resources"


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
        candidates = [
            resource
            for resource in self._resources.values()
            if skill is None or resource.skill == skill
        ]
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


class ChromaResourceStore:
    """Chroma-backed resource store using the BGE small English embedder."""

    def __init__(self, collection) -> None:
        self._collection = collection

    @classmethod
    def create(
        cls,
        *,
        persist_dir: str | Path | None = None,
        collection_name: str = RESOURCE_COLLECTION,
        embedding_model: str = BGE_SMALL_EN,
    ) -> ChromaResourceStore:
        from .concepts import _EMBEDDING_PREFIXES

        if embedding_model in _EMBEDDING_PREFIXES:
            # The resource store has no prefix-aware encoding path yet: silently accepting an
            # e5-family id here would embed queries without their required "query: " prefix and
            # degrade ranking with no error — the exact bug the concept store just fixed.
            raise RuntimeError(
                f"{embedding_model!r} needs asymmetric query/passage prefixes, which the resource "
                "store does not implement yet — use the default embedder here, or port the concept "
                "store's prefix-aware path first"
            )
        try:
            import chromadb
            from chromadb.utils import embedding_functions
        except ImportError as err:
            raise RuntimeError(
                "Chroma resource retrieval requires optional packages: chromadb and sentence-transformers"
            ) from err

        embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=embedding_model)
        client = chromadb.PersistentClient(path=str(persist_dir)) if persist_dir else chromadb.Client()
        collection = client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        return cls(collection)

    def ingest(self, resources: Iterable[LearningResource]) -> int:
        batch = list(resources)
        if not batch:
            return 0
        self._collection.upsert(
            ids=[resource.id for resource in batch],
            documents=[resource.summary for resource in batch],
            metadatas=[resource.metadata() for resource in batch],
        )
        return len(batch)

    def search(
        self,
        query: str,
        *,
        skill: str | None = None,
        n_results: int = 3,
    ) -> list[ResourceMatch]:
        if n_results < 1:
            raise ValueError("n_results must be >= 1")
        where = _metadata_filter({"skill": skill})
        query_kwargs = {
            "query_texts": [query],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where is not None:
            query_kwargs["where"] = where
        result = self._collection.query(**query_kwargs)
        ids = result.get("ids", [[]])[0]
        if not ids:
            raise LookupError(f"no resources match skill={skill!r}")
        matches: list[ResourceMatch] = []
        for i, item_id in enumerate(ids):
            metadata: Mapping[str, object] = result["metadatas"][0][i]
            distance = result.get("distances", [[None]])[0][i]
            resource = LearningResource(
                id=str(metadata.get("id") or item_id),
                skill=str(metadata["skill"]),
                title=str(metadata["title"]),
                url=str(metadata["url"]),
                summary=str(result["documents"][0][i]),
                resource_type=str(metadata.get("resource_type", "article")),
                effort_minutes=int(metadata.get("effort_minutes", 45)),
                tags=tuple(str(metadata.get("tags", "")).split(",")) if metadata.get("tags") else (),
            )
            matches.append(ResourceMatch(resource=resource, score=None if distance is None else 1.0 - float(distance)))
        logger.info("resource search returned %d hit(s) for skill=%r", len(matches), skill)
        return matches


def _metadata_filter(values: Mapping[str, str | None]) -> dict | None:
    clauses = [{key: value} for key, value in values.items() if value is not None]
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


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


def build_resource_store(
    kind: str = "memory",
    *,
    persist_dir: str | Path | None = None,
    seed: bool = True,
) -> ResourceStore:
    """Build the resource store used by the Study Planner."""
    if kind == "memory":
        store: ResourceStore = InMemoryResourceStore()
    elif kind == "chroma":
        store = ChromaResourceStore.create(persist_dir=persist_dir)
    else:
        raise ValueError(f"unknown resource store kind: {kind!r}")
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
