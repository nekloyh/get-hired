from __future__ import annotations

import re

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


# --- toneless ("khong dau") Vietnamese, R-23 ------------------------------------------------------
#
# These corpora ARE the acceptance criteria. R-23 went through three implementation attempts, and
# every one of them fixed the reviewer's half of the problem while silently making the other half
# worse — because each was argued rather than measured. So the measurement is committed here and
# runs in CI: a change to the word list or the gates must beat these counts, in BOTH directions.
#
# Baseline on the code this replaced, for anyone tempted to "simplify" back: 14/18 and 14/20.

_TONELESS_VIETNAMESE = (
    "Overfitting la hien tuong model hoc thuoc du lieu train nen ket qua tren tap test rat te.",
    "Precision la ty le du doan dung tren tong so du doan positive ma model dua ra.",
    "Vi du ve du lieu mat can bang la bai toan phat hien gian lan the tin dung.",
    "Model bi overfit tren tap train, em se them dropout va early stopping roi do lai metric.",
    "Model se bi underfit vi thieu du lieu.",
    "Em se scale du lieu ve khoang 0 den 1.",
    "Vi du ve mot bai toan phan loai la loc spam email.",
    "Minh se dung read-through cache, neu miss thi fallback ve database, va set TTL ngan.",
    "Neu model cua ban bi overfit thi ban se lam gi de giam variance?",
    "Precision va recall doi nhau, tuy bai toan ma chon threshold sao cho phu hop.",
    "Khong nen dung accuracy khi du lieu mat can bang, nen dung F1 hoac AUC.",
    "Em nghi la do du lieu it nen model khong tong quat hoa duoc.",
    "Batch norm giup on dinh phan phoi dau vao cua moi layer nen train nhanh hon.",
    "Cac layer dau hoc dac trung don gian, cac layer sau hoc dac trung phuc tap hon.",
    "Bai toan nay minh se dung cross validation de chon hyperparameter cho on dinh.",
    "Neu latency cao thi em se them cache va giam so luong feature phai tinh online.",
    "Model nay bi data leakage vi feature duoc tinh tren toan bo tap du lieu.",
)

# Deliberately spans BI / warehouse / infra / editor / region / author vocabulary, not just ML.
# The audit that missed this class was ML-only, and `cracklib-small` — the dictionary it checked
# against — is all-lowercase with no acronyms, so "BI" was invisible to it by construction.
_ENGLISH_TECHNICAL_PROSE = (
    "We fit a Gaussian mixture with EM. EM alternates between the E step and the M step until it converges.",
    "Our BI layer reads from the warehouse, and the BI dashboards refresh hourly for the data team.",
    "I owned the BI stack: BI reports on top of dbt models, with row level security per tenant.",
    "Power BI sits on top of the star schema; BI users never touch the raw event stream.",
    "We replicate to the VA region for latency and keep a warm standby in VA for failover.",
    "The encoder is bi directional and the decoder is uni directional, so bi doubles the state.",
    "Cho et al. proposed the GRU. Cho later showed the gate count can drop to two.",
    "I run du -sh on the volume, open the log in vi, and set the padding in em units.",
    "Open the config in vi, then measure the em dash spacing in the rendered output.",
    "We use du to check disk usage and vi to patch the file on the box.",
    "The a la carte plan uses em units for spacing and vi keybindings in the editor.",
    "We compare a bi encoder against a cross encoder because the bi encoder serves at low latency.",
    "Gradient descent updates the weights against the gradient, and the learning rate sets the step size.",
    "Precision and recall trade off, so the threshold depends on the cost of a false positive.",
    "Batch norm stabilises the input distribution of each layer, which is why training converges faster.",
    "I would add dropout and early stopping, then re-measure the validation metric.",
    "The model overfits the training set, so we regularise and collect more data.",
    "We shard the index by tenant and keep a read-through cache in front of the database.",
)


@pytest.mark.parametrize("answer", _TONELESS_VIETNAMESE)
def test_toneless_vietnamese_is_not_english(answer):
    assert not answer_is_english(answer)


@pytest.mark.parametrize("prose", _ENGLISH_TECHNICAL_PROSE)
def test_english_technical_prose_is_never_read_as_vietnamese(prose):
    assert answer_is_english(prose)


@pytest.mark.xfail(strict=True, reason="R-23 residual: a Vietnamese given name plus one collision")
@pytest.mark.parametrize(
    "prose",
    [
        "Minh and I shipped the VA failover last quarter.",
        "Hieu wrote the dbt models and the BI extract on top of them.",
    ],
)
def test_a_vietnamese_name_in_english_prose_is_a_known_gap(prose):
    # `minh`/`hieu` are real Vietnamese function words AND real Vietnamese given names, and a
    # candidate writing in English about Vietnamese colleagues hits both at once. Dropping them was
    # measured and rejected: it fixes 0 of this repo's 2,216 English sentences and costs 3 real
    # Vietnamese ones. Recorded as a strict xfail so the gap is CI-enforced rather than prose — if a
    # future change fixes it, this test goes red and should be promoted, not deleted.
    assert answer_is_english(prose)


def test_the_gate_counts_distinct_words_not_repeats():
    # The whole reason the list can tolerate collisions. "BI" four times is ONE collision; four
    # different Vietnamese function words is Vietnamese. Occurrence counting cannot tell them apart.
    repeated_collision = "The BI team owns BI dashboards, so BI stays in the BI warehouse."
    assert answer_is_english(repeated_collision)
    assert not answer_is_english("Neu du lieu it thi minh se dung cross validation cho on dinh.")


def test_a_lone_collision_never_flips_english():
    # One matched word contributes 1, below `_VN_WORD_MIN_HITS`, whatever the sentence length.
    assert answer_is_english("Cho et al. proposed the GRU in 2014.")
    assert answer_is_english("We fit it with EM.")


def test_english_delivery_activates_on_an_english_answer_full_of_collisions():
    # The production consequence, not just the predicate. This answer is what an ML candidate
    # actually writes, and before R-23 it lost `english_delivery` in mixed mode — ADR 0007's
    # deterministic activation silently dropped on a wholly English answer.
    em = "We fit a Gaussian mixture with EM. EM alternates between the E step and the M step until it converges."
    assert "english_delivery" in rubric_with_delivery(_RUBRIC, "mixed", em).weights
    vn = "Model bi overfit tren tap train, em se them dropout va early stopping roi do lai metric."
    assert "english_delivery" not in rubric_with_delivery(_RUBRIC, "mixed", vn).weights


def test_both_gates_are_load_bearing():
    # Each threshold is pinned by a text that sits between the two settings, so neither constant can
    # be quietly relaxed or removed. Without these, mutating either one left the suite fully green.
    from interview_coach import language

    # 1 distinct hit at a high ratio: passes a min of 1, fails the shipped min of 2.
    one_hit_dense = "Cho."
    assert language._VN_WORD_MIN_HITS == 2
    assert answer_is_english(one_hit_dense)

    # 2 distinct hits diluted below the ratio floor: passes a floor of 0, fails the shipped 0.08.
    two_hits_sparse = (
        "Cho et al. published the recurrent unit that later replaced the long short term memory "
        "cell in most sequence models, and the paper was widely cited by researchers who wanted a "
        "cheaper gate, va so the architecture spread quickly through the literature of that decade."
    )
    words = re.findall(r"[^\W\d]+", two_hits_sparse.lower())
    tokens = len(words)
    matched = {w for w in words if w in language._VIETNAMESE_FUNCTION_WORDS}
    assert len(matched) >= language._VN_WORD_MIN_HITS
    assert len(matched) / tokens < language._VN_WORD_RATIO_THRESHOLD
    assert answer_is_english(two_hits_sparse)


@pytest.mark.parametrize(
    "prose",
    [
        "We log va_scores and bi_grams to the metrics table for each run.",
        "The bi_encoder and cross_encoder share a tokenizer but not a projection head.",
        "We store va_region and bi_layer as separate columns in the fact table.",
    ],
)
def test_a_snake_case_identifier_is_one_token(prose):
    # The tokenizer must NOT split on `_`, or every `va_scores` / `bi_encoder` manufactures a
    # phantom `va` / `bi` hit — and two phantoms are enough to flip an English answer about
    # retrieval, which is vocabulary this product uses constantly. An earlier attempt's only English
    # fixture passed *because* of this artefact, so it pinned the bug rather than the behaviour.
    assert answer_is_english(prose)


def test_the_function_word_gate_flips_no_calibration_bench_case():
    """The bench substitute, and the reason no `coach bench` run gates this change.

    ADR 0009 gates the judge, and the delivery-activation rule decides part of what the judge is
    asked to score — so in principle a change here is bench-relevant. In practice it is not, and
    this test is what keeps that true: on all 35 bench cases (question and answer, 70 texts), the
    function-word signal never disagrees with the letter-ratio signal alone. The judge's inputs are
    therefore byte-identical with the gate on or off, and a stochastic ~207k-token bench invocation
    would be measuring nothing. If a future edit to the word list breaks that, this goes red and the
    change genuinely does need the bench.
    """
    import unicodedata as _ud

    from interview_coach import language
    from interview_coach.bench import load_bench_data

    def letters_only_verdict(text: str) -> bool:
        prose = _ud.normalize("NFC", language._CODE_PATTERN.sub(" ", text)).lower()
        alpha = [ch for ch in prose if ch.isalpha()]
        if not alpha:
            return False
        vn = sum(1 for ch in alpha if ch in language._VIETNAMESE_CHARS)
        return vn / len(alpha) <= language._VIETNAMESE_RATIO_THRESHOLD

    texts = [
        (case.case_id, field, value)
        for case in load_bench_data().cases
        for field, value in (("question", case.question), ("answer", case.answer))
        if isinstance(value, str) and value.strip()
    ]
    assert len(texts) == 70, "bench corpus changed size; re-measure before trusting this invariant"
    disagreements = [
        (case_id, field) for case_id, field, value in texts
        if answer_is_english(value) != letters_only_verdict(value)
    ]
    assert disagreements == []


# Each clause below carries EXACTLY two distinct function words, one of which is the word under
# test — so deleting that word drops the clause to a single hit and it flips to English. Without
# these, every word this rule added or deliberately kept was removable with a fully green suite,
# which is how a measured decision quietly becomes an unmeasured one.
#
# `la` and `du` are here for a specific reason: they collide with English ("a la carte", "du -sh")
# and the obvious fix is to drop them with `vi` and `em`. That was measured and rejected — dropping
# them costs 9 real Vietnamese sentences from this repo's own de-accented prose and fixes zero
# English ones, because under distinct counting a lone collision never reaches the minimum of 2.
@pytest.mark.parametrize(
    ("word", "clause"),
    [
        ("tren", "Accuracy tren test set khong cao."),
        ("ve", "Scale feature ve range chuan truoc."),
        ("cac", "Cac epoch dau nen giam loss."),
        ("nhu", "Coi ensemble nhu bagging vay."),
        ("thi", "Neu miss thi query database."),
        ("mot", "Day la mot classifier nhi phan."),
        ("hon", "Model quantize chay nhanh hon nhieu."),
        ("va", "Precision va recall thi doi nhau."),
        ("bi", "Model bi overfit tren tap train."),
        ("la", "Overfitting la khi model memorize."),
        ("du", "Du doan sai nhieu."),
    ],
)
def test_every_word_this_rule_turns_on_is_load_bearing(word, clause):
    from interview_coach import language

    assert word in language._VIETNAMESE_FUNCTION_WORDS
    assert not answer_is_english(clause)

    hits = {t for t in re.findall(r"[^\W\d]+", clause.lower()) if t in language._VIETNAMESE_FUNCTION_WORDS}
    assert word in hits
    assert len(hits) == 2, f"{clause!r} must isolate {word!r}: exactly two distinct hits, got {sorted(hits)}"
