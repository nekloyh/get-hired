from __future__ import annotations

import pytest

from interview_coach.language import (
    DEFAULT_LANGUAGE_MODE,
    ENGLISH_DELIVERY_WEIGHT,
    LANGUAGE_MODES,
    answer_is_english,
    rubric_with_delivery,
    validate_language_mode,
)
from interview_coach.rubric import Rubric

_RUBRIC = Rubric(weights={"correctness": 0.6, "depth": 0.4})


# --- mode validation ------------------------------------------------------------------------------


def test_language_modes_and_default():
    assert LANGUAGE_MODES == ("en", "vn", "mixed")
    assert DEFAULT_LANGUAGE_MODE == "en"


@pytest.mark.parametrize("mode", ["en", "vn", "mixed"])
def test_validate_language_mode_accepts_known_modes(mode):
    assert validate_language_mode(mode) == mode


def test_validate_language_mode_rejects_typos_loudly():
    with pytest.raises(ValueError, match="unknown language_mode"):
        validate_language_mode("vi")  # the bench's answer-language vocabulary, not a session mode


# --- the deterministic detector -------------------------------------------------------------------


def test_english_answer_is_english():
    assert answer_is_english(
        "Overfitting happens when the model memorizes the training data instead of generalizing."
    )


def test_vietnamese_answer_is_not_english():
    assert not answer_is_english(
        "Overfitting xảy ra khi mô hình học thuộc dữ liệu train thay vì tổng quát hoá."
    )


def test_code_switched_vietnamese_stays_vietnamese():
    # Heavy English jargon inside a Vietnamese sentence must not flip the detection.
    assert not answer_is_english(
        "Dropout tắt ngẫu nhiên neuron để tránh co-adaptation, giống ensemble của nhiều sub-network."
    )


def test_english_quoting_one_vietnamese_term_stays_english():
    assert answer_is_english(
        'Vietnamese word segmentation matters because a token like "từ ghép" spans two syllables '
        "and PhoBERT assumes segmented input."
    )


def test_empty_or_symbol_answers_are_not_english():
    assert not answer_is_english("")
    assert not answer_is_english("   \n\t")
    assert not answer_is_english("42 + 7 = 49 !!!")


def test_nfd_composed_vietnamese_is_still_detected():
    # The same Vietnamese text in decomposed (NFD) form must not read as English.
    import unicodedata

    text = "Bias là khi mô hình sai, còn variance là khi nó thay đổi nhiều."
    assert not answer_is_english(unicodedata.normalize("NFD", text))


# --- delivery activation (the weight-0 mechanic, ADR 0007) ----------------------------------------


def test_en_mode_activates_delivery_on_english_answer():
    rubric = rubric_with_delivery(_RUBRIC, "en", "The model overfits when it memorizes noise.")
    assert rubric.weights["english_delivery"] == ENGLISH_DELIVERY_WEIGHT
    assert "english_delivery" in rubric.active
    # the original rubric is never mutated
    assert "english_delivery" not in _RUBRIC.weights


def test_mixed_mode_activates_delivery_only_on_english_answers():
    en = rubric_with_delivery(_RUBRIC, "mixed", "I would use a read-through cache with a TTL.")
    vn = rubric_with_delivery(_RUBRIC, "mixed", "Em sẽ dùng cache read-through với TTL ngắn.")
    assert "english_delivery" in en.active
    assert "english_delivery" not in vn.active


def test_vn_mode_never_activates_delivery_even_on_english_answers():
    # Issue 0024 acceptance criterion: a pure-VN Session simply never activates english_delivery.
    rubric = rubric_with_delivery(_RUBRIC, "vn", "The model overfits when it memorizes noise.")
    assert "english_delivery" not in rubric.active


def test_activation_is_idempotent_and_forces_off_a_preactivated_rubric():
    active = Rubric(weights={"correctness": 1.0, "english_delivery": 1.0})
    unchanged = rubric_with_delivery(active, "en", "A clear English answer about caching.")
    assert unchanged is active  # already correct: no copy
    forced_off = rubric_with_delivery(active, "vn", "A clear English answer about caching.")
    assert "english_delivery" not in forced_off.active


def test_technical_dimensions_never_include_delivery():
    from interview_coach.rubric import DIMENSIONS, TECHNICAL_DIMENSIONS

    assert "english_delivery" in DIMENSIONS
    assert "english_delivery" not in TECHNICAL_DIMENSIONS
    assert set(TECHNICAL_DIMENSIONS) == set(DIMENSIONS) - {"english_delivery"}


def test_delivery_only_rubric_is_rejected():
    # weighted_score aggregates technical dimensions only, so a delivery-only rubric has no score.
    with pytest.raises(ValueError, match="technical dimension"):
        Rubric(weights={"english_delivery": 1.0})
