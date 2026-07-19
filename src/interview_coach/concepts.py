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
from typing import Any, Protocol

from .bank import load_concepts

logger = logging.getLogger(__name__)

CONCEPT_COLLECTION = "concepts"
BGE_SMALL_EN = "BAAI/bge-small-en-v1.5"
# Candidate multilingual embedder (issue 0008 follow-up): same size-class as bge-small, actually
# trained on Vietnamese. The e5 family REQUIRES asymmetric instruction prefixes — encoding a query
# without "query: " silently degrades ranking, so the prefixes live next to the model id and the
# store applies them itself.
E5_SMALL_MULTILINGUAL = "intfloat/multilingual-e5-small"

# model id -> (query prefix, passage prefix). Models absent from this map embed text as-is via
# Chroma's stock SentenceTransformer embedding function.
_EMBEDDING_PREFIXES: dict[str, tuple[str, str]] = {
    E5_SMALL_MULTILINGUAL: ("query: ", "passage: "),
}


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
    """Chroma-backed concept store (BGE small English by default; e5-multilingual supported).

    Prefixed models (the e5 family) bypass Chroma's embedding function entirely: the store encodes
    queries and passages itself with the required asymmetric prefixes and hands Chroma raw vectors —
    Chroma's stock ``SentenceTransformerEmbeddingFunction`` cannot tell a query from a document, and
    e5 without prefixes ranks silently worse.
    """

    def __init__(self, collection, *, encoder=None, prefixes: tuple[str, str] | None = None) -> None:
        self._collection = collection
        self._encoder = encoder
        self._query_prefix, self._passage_prefix = prefixes or ("", "")

    @classmethod
    def create(
        cls,
        *,
        persist_dir: str | Path | None = None,
        collection_name: str = CONCEPT_COLLECTION,
        embedding_model: str = BGE_SMALL_EN,
    ) -> ChromaConceptStore:
        prefixes = _EMBEDDING_PREFIXES.get(embedding_model)
        try:
            import chromadb
            from chromadb.utils import embedding_functions

            if prefixes is not None:
                from sentence_transformers import SentenceTransformer
        except ImportError as err:
            raise RuntimeError(
                "Chroma concept retrieval requires optional packages: chromadb and sentence-transformers"
            ) from err

        client = chromadb.PersistentClient(path=str(persist_dir)) if persist_dir else chromadb.Client()
        # The embedder id is stamped into the collection metadata: bge-small and e5-small are BOTH
        # 384-dim, so Chroma would silently accept queries from the wrong model against a persisted
        # collection and return confidently-scored garbage. One index config for both branches.
        collection_kwargs: dict[str, Any] = {
            "name": collection_name,
            "metadata": {"hnsw:space": "cosine", "embedder": embedding_model},
        }
        encoder = None
        if prefixes is not None:
            encoder = SentenceTransformer(embedding_model)
        else:
            collection_kwargs["embedding_function"] = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=embedding_model
            )
        collection = client.get_or_create_collection(**collection_kwargs)
        stamped = (getattr(collection, "metadata", None) or {}).get("embedder")
        if stamped is not None and stamped != embedding_model:
            # get_or_create keeps an existing collection's metadata, so the stamp survives across
            # runs; pre-stamp legacy collections (stamped None) cannot be verified and pass through.
            raise RuntimeError(
                f"collection {collection_name!r} was built with embedder {stamped!r} but "
                f"{embedding_model!r} was requested — embeddings do not mix across models. "
                "Re-ingest into a fresh persist dir (or delete the old collection) to switch."
            )
        return cls(collection, encoder=encoder, prefixes=prefixes)

    def _encode(self, texts: list[str], prefix: str) -> list[list[float]]:
        vectors = self._encoder.encode([f"{prefix}{text}" for text in texts], normalize_embeddings=True)
        return [vector.tolist() for vector in vectors]

    def ingest(self, notes: Iterable[ConceptNote]) -> int:
        batch = list(notes)
        if not batch:
            return 0
        upsert_kwargs: dict = {
            "ids": [note.id for note in batch],
            "documents": [note.content for note in batch],
            "metadatas": [note.metadata() for note in batch],
        }
        if self._encoder is not None:
            upsert_kwargs["embeddings"] = self._encode([note.content for note in batch], self._passage_prefix)
        self._collection.upsert(**upsert_kwargs)
        return len(batch)

    def lookup(self, query: str, *, skill: str | None = None, language: str | None = None) -> ConceptLookup:
        where = _metadata_filter({"skill": skill, "language": language})
        query_kwargs = {
            "n_results": 1,
            "include": ["documents", "metadatas", "distances"],
        }
        if self._encoder is not None:
            query_kwargs["query_embeddings"] = self._encode([query], self._query_prefix)
        else:
            query_kwargs["query_texts"] = [query]
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


# The concept notes themselves live in data/concepts.yaml (issue 0008) so they are hand-editable and
# diff-friendly; they are loaded + validated here at import time (a malformed bank fails loudly).
SEED_CONCEPTS: tuple[ConceptNote, ...] = load_concepts()


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
    embedding_model: str = BGE_SMALL_EN,
) -> ConceptStore:
    """Build the concept store used by the Interviewer."""
    if kind == "memory":
        store: ConceptStore = InMemoryConceptStore()
    elif kind == "chroma":
        store = ChromaConceptStore.create(persist_dir=persist_dir, embedding_model=embedding_model)
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
