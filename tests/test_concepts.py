from __future__ import annotations

import pytest

from interview_coach.concepts import (
    CONCEPT_COLLECTION,
    ChromaConceptStore,
    ConceptNote,
    InMemoryConceptStore,
    build_concept_store,
    lookup_concept,
    seed_concept_store,
)


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
