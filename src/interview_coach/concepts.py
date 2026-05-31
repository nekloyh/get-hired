"""Concept retrieval for the Interviewer's single tool (slice 0007, ADR 0003).

The production path is a Chroma ``concepts`` collection using ``BAAI/bge-small-en-v1.5`` embeddings.
Tests and offline demos can use the same interface with the small in-memory store below, so the
Interviewer can exercise the tool loop without downloading an embedding model.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

CONCEPT_COLLECTION = "concepts"
BGE_SMALL_EN = "BAAI/bge-small-en-v1.5"


@dataclass(frozen=True)
class ConceptNote:
    """A retrievable note the Interviewer can ground a Follow-up in."""

    id: str
    skill: str
    title: str
    content: str
    language: str = "en"
    tags: tuple[str, ...] = ()

    def metadata(self) -> dict[str, str]:
        return {
            "id": self.id,
            "skill": self.skill,
            "title": self.title,
            "language": self.language,
            "tags": ",".join(self.tags),
        }


@dataclass(frozen=True)
class ConceptLookup:
    """The retrieved concept note plus a store-specific similarity score."""

    note: ConceptNote
    score: float | None = None

    def render(self) -> str:
        score = "n/a" if self.score is None else f"{self.score:.3f}"
        return (
            f"TITLE: {self.note.title}\n"
            f"SKILL: {self.note.skill}\n"
            f"LANGUAGE: {self.note.language}\n"
            f"SIMILARITY: {score}\n"
            f"CONTENT:\n{self.note.content}"
        )


class ConceptStore(Protocol):
    """Store abstraction used by the Interviewer; Chroma is one implementation."""

    def ingest(self, notes: Iterable[ConceptNote]) -> int: ...

    def lookup(self, query: str, *, skill: str | None = None, language: str | None = None) -> ConceptLookup: ...


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text) if len(t) > 2}


class InMemoryConceptStore:
    """Small deterministic store for tests and local demos.

    It still honors the important production contract: Skill/language metadata filters are applied
    before ranking, which is how Vietnamese notes are reachable without trusting an English embedder
    to understand Vietnamese text.
    """

    def __init__(self, notes: Sequence[ConceptNote] = ()) -> None:
        self._notes: dict[str, ConceptNote] = {}
        self.lookup_calls: list[dict[str, str | None]] = []
        self.ingest(notes)

    def ingest(self, notes: Iterable[ConceptNote]) -> int:
        count = 0
        for note in notes:
            self._notes[note.id] = note
            count += 1
        return count

    def lookup(self, query: str, *, skill: str | None = None, language: str | None = None) -> ConceptLookup:
        self.lookup_calls.append({"query": query, "skill": skill, "language": language})
        candidates = [
            note
            for note in self._notes.values()
            if (skill is None or note.skill == skill) and (language is None or note.language == language)
        ]
        if not candidates:
            raise LookupError(f"no concept notes match skill={skill!r}, language={language!r}")

        q = _tokens(query)

        def rank(note: ConceptNote) -> tuple[float, str]:
            body = _tokens(f"{note.title} {note.content} {' '.join(note.tags)}")
            overlap = len(q & body)
            denom = max(1, len(q | body))
            return (overlap / denom, note.id)

        best = max(candidates, key=rank)
        return ConceptLookup(note=best, score=rank(best)[0])


class ChromaConceptStore:
    """Chroma-backed concept store using the BGE small English embedder."""

    def __init__(self, collection) -> None:
        self._collection = collection

    @classmethod
    def create(
        cls,
        *,
        persist_dir: str | Path | None = None,
        collection_name: str = CONCEPT_COLLECTION,
        embedding_model: str = BGE_SMALL_EN,
    ) -> ChromaConceptStore:
        try:
            import chromadb
            from chromadb.utils import embedding_functions
        except ImportError as err:
            raise RuntimeError(
                "Chroma concept retrieval requires optional packages: chromadb and sentence-transformers"
            ) from err

        embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=embedding_model)
        client = chromadb.PersistentClient(path=str(persist_dir)) if persist_dir else chromadb.Client()
        collection = client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        return cls(collection)

    def ingest(self, notes: Iterable[ConceptNote]) -> int:
        batch = list(notes)
        if not batch:
            return 0
        self._collection.upsert(
            ids=[note.id for note in batch],
            documents=[note.content for note in batch],
            metadatas=[note.metadata() for note in batch],
        )
        return len(batch)

    def lookup(self, query: str, *, skill: str | None = None, language: str | None = None) -> ConceptLookup:
        where = _metadata_filter({"skill": skill, "language": language})
        query_kwargs = {
            "query_texts": [query],
            "n_results": 1,
            "include": ["documents", "metadatas", "distances"],
        }
        if where is not None:
            query_kwargs["where"] = where
        result = self._collection.query(**query_kwargs)
        ids = result.get("ids", [[]])[0]
        if not ids:
            raise LookupError(f"no concept notes match skill={skill!r}, language={language!r}")
        metadata: Mapping[str, object] = result["metadatas"][0][0]
        distance = result.get("distances", [[None]])[0][0]
        note = ConceptNote(
            id=str(metadata.get("id") or ids[0]),
            skill=str(metadata["skill"]),
            title=str(metadata["title"]),
            content=str(result["documents"][0][0]),
            language=str(metadata.get("language", "en")),
            tags=tuple(str(metadata.get("tags", "")).split(",")) if metadata.get("tags") else (),
        )
        score = None if distance is None else 1.0 - float(distance)
        logger.info("lookup_concept returned %r for skill=%r language=%r", note.id, skill, language)
        return ConceptLookup(note=note, score=score)


def _metadata_filter(values: Mapping[str, str | None]) -> dict | None:
    clauses = [{key: value} for key, value in values.items() if value is not None]
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


SEED_CONCEPTS: tuple[ConceptNote, ...] = (
    ConceptNote(
        id="ml_fundamentals_l2_regularization",
        skill="ml_fundamentals",
        title="L2 regularization and variance",
        content=(
            "L2 regularization adds a squared-weight penalty to the loss. The optimizer accepts a "
            "little more training error in exchange for smaller weights, which smooths the learned "
            "function and lowers variance. The strength is usually chosen with validation or "
            "cross-validation on a log-spaced grid."
        ),
        tags=("regularization", "variance", "validation"),
    ),
    ConceptNote(
        id="ml_fundamentals_cv_leakage",
        skill="ml_fundamentals",
        title="Cross-validation leakage traps",
        content=(
            "K-fold cross-validation misleads when folds violate the data-generating structure. "
            "Time series need forward-chaining splits, grouped data needs grouped folds, and all "
            "preprocessing that learns from data must be fit inside each training fold."
        ),
        tags=("cross_validation", "leakage", "folds"),
    ),
    ConceptNote(
        id="mlops_drift_monitoring",
        skill="mlops",
        title="Drift monitoring and retraining",
        content=(
            "Production ML systems need data-quality checks, feature drift and prediction drift "
            "monitoring, labeled performance audits when labels arrive, and a retraining trigger "
            "that is tied to business risk rather than a fixed calendar alone."
        ),
        tags=("drift", "monitoring", "retraining"),
    ),
    ConceptNote(
        id="system_design_backpressure",
        skill="system_design",
        title="Backpressure in asynchronous systems",
        content=(
            "Backpressure prevents an overloaded consumer from being buried by producers. Common "
            "mechanisms include bounded queues, admission control, retry budgets, load shedding, and "
            "explicit signals that slow upstream senders."
        ),
        tags=("queues", "backpressure", "resilience"),
    ),
    ConceptNote(
        id="vietnamese_nlp_word_segmentation",
        skill="vietnamese_nlp",
        title="Vietnamese word segmentation",
        language="vi",
        content=(
            "Tiếng Việt dùng khoảng trắng giữa âm tiết, không luôn luôn giữa từ. Nhiều mô hình NLP "
            "cần xử lý tách từ hoặc thiết kế tokenizer phù hợp để tránh nhầm ranh giới từ ghép, tên "
            "riêng và thực thể."
        ),
        tags=("tokenization", "word_segmentation", "metadata_routed"),
    ),
)


def seed_concept_store(store: ConceptStore | None = None) -> ConceptStore:
    """Create or fill a concept store with the small built-in seed set."""
    target = store or InMemoryConceptStore()
    target.ingest(SEED_CONCEPTS)
    return target


def build_concept_store(
    kind: str = "memory",
    *,
    persist_dir: str | Path | None = None,
    seed: bool = True,
) -> ConceptStore:
    """Build the concept store used by the Interviewer."""
    if kind == "memory":
        store: ConceptStore = InMemoryConceptStore()
    elif kind == "chroma":
        store = ChromaConceptStore.create(persist_dir=persist_dir)
    else:
        raise ValueError(f"unknown concept store kind: {kind!r}")
    if seed:
        store.ingest(SEED_CONCEPTS)
    return store


def lookup_concept(
    store: ConceptStore,
    query: str,
    *,
    skill: str | None = None,
    language: str | None = None,
) -> ConceptLookup:
    """The Interviewer's one tool."""
    logger.info("lookup_concept(query=%r, skill=%r, language=%r)", query, skill, language)
    return store.lookup(query, skill=skill, language=language)
