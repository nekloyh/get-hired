from __future__ import annotations

import pytest

from interview_coach.concepts import (
    CONCEPT_COLLECTION,
    SEED_CONCEPTS,
    ChromaConceptStore,
    ConceptNote,
    InMemoryConceptStore,
    build_concept_store,
    lookup_concept,
    seed_concept_store,
)
from interview_coach.diagnostic import SKILLS


def test_seed_concepts_cover_every_canonical_skill():
    # The Interviewer applies a mandatory Skill filter in lookup_concept, so a Skill with no seed
    # note makes a Follow-up on that Skill crash with LookupError. Every canonical Skill needs ≥1.
    covered = {note.skill for note in SEED_CONCEPTS}
    assert set(SKILLS) <= covered, f"skills with no seed concept note: {sorted(set(SKILLS) - covered)}"


def test_concepts_ingest_and_lookup_by_similarity():
    store = InMemoryConceptStore()
    store.ingest(
        [
            ConceptNote(
                id="regularization",
                skill="ml_fundamentals",
                title="Regularization",
                content="L2 regularization uses a penalty to shrink weights and reduce variance.",
            ),
            ConceptNote(
                id="cv",
                skill="ml_fundamentals",
                title="Cross-validation",
                content="K-fold validation rotates held-out folds and can leak on time series.",
            ),
        ]
    )

    hit = lookup_concept(store, "why does a penalty lower variance?", skill="ml_fundamentals")

    assert hit.note.id == "regularization"


def test_lookup_uses_skill_metadata_for_vietnamese_notes():
    store = seed_concept_store(InMemoryConceptStore())

    hit = lookup_concept(
        store,
        "tokenizer boundaries",  # English query; routing should not depend on Vietnamese semantics.
        skill="vietnamese_nlp",
        language="vi",
    )

    assert hit.note.id == "vietnamese_nlp_word_segmentation"
    assert store.lookup_calls[-1] == {
        "query": "tokenizer boundaries",
        "skill": "vietnamese_nlp",
        "language": "vi",
    }


def test_build_memory_store_can_seed_concepts():
    store = build_concept_store("memory")

    hit = lookup_concept(store, "bounded queues and backpressure", skill="system_design")

    assert hit.note.id == "system_design_backpressure"


@pytest.mark.rag
def test_chroma_concepts_collection_ingests_and_queries_seed_notes(tmp_path):
    pytest.importorskip("chromadb")
    pytest.importorskip("sentence_transformers")

    store = ChromaConceptStore.create(persist_dir=tmp_path)
    assert store._collection.name == CONCEPT_COLLECTION

    seed_concept_store(store)
    store.ingest(
        [
            ConceptNote(
                id="vietnamese_nlp_sentiment",
                skill="vietnamese_nlp",
                title="Vietnamese sentiment classification",
                language="vi",
                content=(
                    "Phân loại cảm xúc tiếng Việt cần dữ liệu đúng miền, xử lý phủ định, từ lóng "
                    "và cách diễn đạt mỉa mai trong đánh giá sản phẩm hoặc mạng xã hội."
                ),
                tags=("sentiment", "classification", "vietnamese"),
            )
        ]
    )

    hit = lookup_concept(store, "squared weight penalty reduces variance", skill="ml_fundamentals")

    assert hit.note.id == "ml_fundamentals_l2_regularization"
    assert hit.score is not None

    vi_hit = lookup_concept(
        store,
        "tokenizer tiếng Việt bị nhầm ranh giới từ ghép vì khoảng trắng chỉ tách âm tiết",
        skill="vietnamese_nlp",
        language="vi",
    )

    assert vi_hit.note.id == "vietnamese_nlp_word_segmentation"
    assert vi_hit.note.skill == "vietnamese_nlp"
    assert vi_hit.note.language == "vi"
    assert vi_hit.score is not None

    filtered_hit = lookup_concept(
        store,
        "bounded queues retry budgets load shedding admission control",
        skill="vietnamese_nlp",
        language="vi",
    )

    assert filtered_hit.note.skill == "vietnamese_nlp"
    assert filtered_hit.note.language == "vi"


# --- e5 prefix wiring (asymmetric query:/passage: instructions) ----------------------------------


class _FakeVector:
    def __init__(self, values):
        self._values = values

    def tolist(self):
        return self._values


class _FakeEncoder:
    def __init__(self):
        self.encoded: list[list[str]] = []

    def encode(self, texts, normalize_embeddings=False):
        self.encoded.append(list(texts))
        return [_FakeVector([0.0, 1.0]) for _ in texts]


class _FakeCollection:
    def __init__(self):
        self.upserts: list[dict] = []
        self.queries: list[dict] = []

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return {
            "ids": [["n1"]],
            "documents": [["content"]],
            "metadatas": [[{"id": "n1", "skill": "mlops", "title": "t", "language": "en"}]],
            "distances": [[0.1]],
        }


def test_prefixed_store_encodes_passages_and_queries_asymmetrically():
    from interview_coach.concepts import ChromaConceptStore

    encoder = _FakeEncoder()
    collection = _FakeCollection()
    store = ChromaConceptStore(collection, encoder=encoder, prefixes=("query: ", "passage: "))

    store.ingest([ConceptNote(id="n1", skill="mlops", title="t", content="drift monitoring")])
    store.lookup("how to detect drift", skill="mlops")

    assert encoder.encoded[0] == ["passage: drift monitoring"]  # ingest side
    assert encoder.encoded[1] == ["query: how to detect drift"]  # query side
    assert "embeddings" in collection.upserts[0]
    assert "query_embeddings" in collection.queries[0]
    assert "query_texts" not in collection.queries[0]


def test_unprefixed_store_keeps_chroma_text_path():
    from interview_coach.concepts import ChromaConceptStore

    collection = _FakeCollection()
    store = ChromaConceptStore(collection)

    store.ingest([ConceptNote(id="n1", skill="mlops", title="t", content="c")])
    store.lookup("q", skill="mlops")

    assert "embeddings" not in collection.upserts[0]
    assert collection.queries[0]["query_texts"] == ["q"]


def test_resource_store_refuses_prefixed_embedder():
    # ChromaResourceStore has no prefix-aware path: accepting an e5 id would silently rank worse.
    from interview_coach.concepts import E5_SMALL_MULTILINGUAL
    from interview_coach.resources import ChromaResourceStore

    with pytest.raises(RuntimeError, match="prefixes"):
        ChromaResourceStore.create(embedding_model=E5_SMALL_MULTILINGUAL)
