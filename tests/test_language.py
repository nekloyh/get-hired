from __future__ import annotations

import pytest

from interview_coach import language
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


def test_toneless_vietnamese_is_not_english():
    # The diacritic ratio is 0.0 here — the text carries no Vietnamese-specific letter at all — so
    # only the function-word signal can catch it. Without that second signal a whole Vietnamese
    # answer reads as English, which is the failure R-23 exists to keep dead.
    assert not answer_is_english(
        "Overfitting la khi model hoc thuoc du lieu train, khong tong quat hoa duoc nen ket qua tren tap test rat te."
    )


def test_toneless_vietnamese_with_bi_and_va_is_not_english():
    # The exact panel symptom R-23 was filed on. It reaches only one hit ("em", 1/17 = 0.059) against
    # the word list this issue inherited, so it shipped as English; "bi" and "va" — the two words the
    # AC names — are what carry it. Every other content word here is English jargon or a toneless
    # syllable no curated list can hold, which is why the AC picked these two.
    assert not answer_is_english(
        "Model bi overfit tren tap train, em se them dropout va early stopping roi do lai metric."
    )


@pytest.mark.parametrize(
    "answer",
    [
        # "em": the EM algorithm — mainline vocabulary for this product, and it recurs by nature.
        "We fit a Gaussian mixture with EM. EM alternates between the E step and the M step until "
        "the log likelihood converges.",
        # "la": `ls -la`, a la carte, the LA region.
        "The a la carte pricing page and the LA region both went down, so we failed over to us-east.",
        # "vi": the editor.
        "I opened the config in vi, fixed the port, and closed vi before restarting the worker.",
        # "du": disk usage.
        "Run du -h on the mount, then du -sh per shard to find the hot partition.",
        # "lieu": "in lieu of" cannot recur, but it only needs one companion — here a cited surname.
        "We cache the embedding in lieu of recomputing it, following Cho et al.",
    ],
)
def test_english_technical_prose_is_never_read_as_vietnamese(answer):
    # The inverse of R-23, and the more dangerous direction because it fails silently: a false
    # "Vietnamese" verdict drops english_delivery from an English answer (ADR 0007's activation is
    # deterministic, so nothing downstream notices) and makes require_vietnamese a no-op in vn mode.
    # Every one of these cleared both gates against the shipped list; re-adding the single word each
    # is named for turns that one case red again, so no removal here can be undone unnoticed.
    assert answer_is_english(answer)


def test_english_delivery_still_activates_on_an_answer_about_the_em_algorithm():
    # The activation half of the case above, asserted where the damage actually lands: a mixed
    # Session must still grade delivery on a pure-English answer.
    rubric = rubric_with_delivery(
        _RUBRIC,
        "mixed",
        "We fit a Gaussian mixture with EM. EM alternates between the E step and the M step until "
        "the log likelihood converges.",
    )
    assert "english_delivery" in rubric.active


def test_hyphenated_and_underscored_compounds_are_one_token():
    # "bi" earns its place only because the tokenizer stops at the joiner. Split on it and this
    # sentence donates three phantom hits — "bi" twice from the compounds, "va" from the identifier,
    # 3/18 = 0.167 — convicting plainly English prose on vocabulary that never stands alone.
    assert answer_is_english(
        "We train a bi-directional LSTM over bi-gram features and log a va_scores column per epoch."
    )


def test_a_single_stray_function_word_never_flips_english():
    # Pins _VN_WORD_MIN_HITS. One genuine hit ("cho" — Kyunghyun Cho, the GRU paper) at 1/11 = 0.091
    # is already past the density floor, so the hit count is the only thing holding this English.
    # The residual English collisions left in the list are all of this shape: at most one per answer.
    assert answer_is_english("Cho et al. introduced the GRU, which drops one LSTM gate.")


def test_sparse_function_words_never_flip_long_english():
    # Pins _VN_WORD_RATIO_THRESHOLD. Two genuine hits ("cho", "va" as the Virginia region) satisfy
    # the hit count outright, so only the density floor (2/28 = 0.071 < 0.08) keeps this English —
    # a long English answer must not be convicted by two incidental tokens.
    assert answer_is_english(
        "Cho et al. published the GRU in 2014, and after we moved the encoder into our VA region "
        "the tail latency held, so the two-gate variant stayed in production."
    )


def test_toneless_code_switched_vietnamese_stays_vietnamese():
    # The toneless twin of test_code_switched_vietnamese_stays_vietnamese: Vietnamese grammar
    # carrying English jargon, typed the way the target users actually type. The diacriticked version
    # short-circuits on the letter ratio and never reaches this branch.
    assert not answer_is_english(
        "Minh se dung read-through cache, neu miss thi fallback ve database, va set TTL khoang 5 phut cho hot key."
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


def test_function_word_gate_changes_no_bench_case(monkeypatch):
    """The calibration corpus classifies identically with and without the function-word signal.

    This is the standing substitute for a `coach bench` run on every change to the word list. The
    detector decides english_delivery activation, so a flipped bench case would change what the
    judge is asked to score and would put the change under ADR 0009's gate; measured on the shipped
    corpus, the second signal touches zero of them (every bench answer is either diacriticked
    Vietnamese, caught by the letter ratio, or English that never reaches two hits). Pinning that
    here makes the gate a deterministic CI fact instead of a stochastic, ~207k-token judgement call.

    If this ever goes red, the word list has started moving bench cases — do NOT relax the assert:
    the change needs a real bench run and the repo owner's decision.
    """
    from interview_coach.bench import load_bench_data

    cases = load_bench_data().cases
    assert cases, "the bench corpus must not be empty or this test asserts nothing"
    with_gate = {c.case_id: (answer_is_english(c.answer), answer_is_english(c.question)) for c in cases}

    # Emptying the word list leaves exactly the letter-ratio signal — a real disable, not a re-
    # implementation of the branch that could drift away from the code it is meant to mirror.
    monkeypatch.setattr(language, "_VIETNAMESE_FUNCTION_WORDS", frozenset())
    ratio_only = {c.case_id: (answer_is_english(c.answer), answer_is_english(c.question)) for c in cases}

    assert with_gate == ratio_only


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


def test_mixed_mode_never_activates_delivery_on_toneless_vietnamese():
    # R-23's production symptom: a Vietnamese answer graded on English delivery because the text
    # carried no tone marks. The fixture is 22 words, well clear of _MIN_DELIVERY_WORDS, so a green
    # result here can only come from the detector and never from the too-short-to-grade floor.
    rubric = rubric_with_delivery(
        _RUBRIC,
        "mixed",
        "Overfitting la khi model hoc thuoc du lieu train, khong tong quat hoa duoc nen ket qua tren tap test rat te.",
    )
    assert "english_delivery" not in rubric.active


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
