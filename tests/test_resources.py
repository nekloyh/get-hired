from __future__ import annotations

from interview_coach.diagnostic import SKILLS
from interview_coach.resources import (
    SEED_RESOURCES,
    InMemoryResourceStore,
    LearningResource,
    build_resource_store,
    search_resources,
)


def test_seed_resources_cover_every_canonical_skill():
    covered = {resource.skill for resource in SEED_RESOURCES}

    assert set(SKILLS) <= covered, f"skills with no seed learning resource: {sorted(set(SKILLS) - covered)}"


def test_resources_search_by_similarity_and_skill_filter():
    store = InMemoryResourceStore(
        [
            LearningResource(
                id="mlops",
                skill="mlops",
                title="Drift monitoring",
                url="https://example.com/mlops",
                summary="Feature drift, prediction drift, performance audits, and retraining triggers.",
                tags=("drift", "monitoring"),
            ),
            LearningResource(
                id="cv",
                skill="ml_fundamentals",
                title="Cross-validation",
                url="https://example.com/cv",
                summary="Validation folds and leakage controls.",
                tags=("validation", "leakage"),
            ),
        ]
    )

    hit = search_resources(store, "monitoring drift retraining trigger", skill="mlops", n_results=1)[0]

    assert hit.resource.id == "mlops"
    assert store.search_calls[-1] == {
        "query": "monitoring drift retraining trigger",
        "skill": "mlops",
        "n_results": 1,
    }


def test_build_memory_resource_store_can_seed_resources():
    store = build_resource_store()

    hit = search_resources(store, "PhoBERT Vietnamese tokenization", skill="vietnamese_nlp", n_results=1)[0]

    assert hit.resource.id == "vietnamese_nlp_phobert"
