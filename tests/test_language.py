from __future__ import annotations

import re

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
    assert answer_is_english("Overfitting happens when the model memorizes the training data instead of generalizing.")


def test_vietnamese_answer_is_not_english():
    assert not answer_is_english("Overfitting xảy ra khi mô hình học thuộc dữ liệu train thay vì tổng quát hoá.")


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
    # The exact panel symptom R-23 was filed on: against the inherited word list it reached only one
    # hit ("em", 1/17) and shipped as English. It now scores 5/17 — anchor {tren}, corroborated by
    # {bi, em, se, va}, the two the AC names among them. Note the anchor is carrying it: strip the
    # corroborators and "tren" alone still would not, which is what the next test pins.
    assert not answer_is_english(
        "Model bi overfit tren tap train, em se them dropout va early stopping roi do lai metric."
    )


@pytest.mark.parametrize(
    "answer",
    [
        # The copula definition — "X la ..." — the single commonest shape in a Vietnamese answer.
        "Overfitting la hien tuong model hoc thuoc du lieu train nen ket qua tren tap test rat te.",
        "Precision la ty le du doan dung tren tong so du doan positive ma model dua ra.",
        # The example framing — "vi du ve ...". Its only anchor is "dung"; every other hit
        # ("vi", "du", "ve", "la", "lieu") is a word English also uses.
        "Vi du ve du lieu mat can bang la bai toan phat hien gian lan the tin dung.",
    ],
)
def test_the_commonest_vietnamese_answer_shapes_are_not_english(answer):
    # R-23's own goal, and the axis a fix aimed only at English false positives silently trades away:
    # an earlier pass removed "la"/"vi"/"du"/"lieu" from the list because they recur in English, and
    # took all three of these sentences with them (4/18 -> 1/18, 4/17 -> 1/17, 6/18 -> 1/18). Keeping
    # them as corroborators instead of deleting them is what makes both directions work at once.
    assert not answer_is_english(answer)


# Committed English-collision corpus. Deliberately spans BI / warehouse / infra / editor / cloud
# region / acronym vocabulary rather than the ML-only prose the first audit sampled — that blind
# spot is precisely why "bi" and "va" shipped: "bi encoder" is this repo's own retrieval vocabulary
# and "Power BI" never appears in an ML corpus. Every entry must read as English.
_ENGLISH_COLLISION_CORPUS = [
    # "bi" — recurring inside one answer, the shape that defeats an occurrence-counted minimum.
    "Our BI layer reads from the warehouse, and the BI dashboards refresh hourly for the data team.",
    "I owned the BI stack: BI reports on top of dbt models, with row level security per tenant.",
    "Power BI sits on top of the star schema; BI users never touch the raw event stream.",
    "The encoder is bi directional and the decoder is uni directional, so bi doubles the state.",
    "A bi encoder embeds query and document separately, so a bi encoder can be indexed offline.",
    # "va" — a US cloud region, and it recurs for the same reason a region always does.
    "We replicate to the VA region for latency and keep a warm standby in VA for failover.",
    "We moved the VA and CA replicas behind one balancer, so a VA outage no longer pages anyone.",
    # "cho" — Kyunghyun Cho, the GRU paper's author, in an ML interview coach.
    "Cho et al. proposed the GRU. Cho later showed the gate count can drop to two.",
    "Cho reports the GRU converges faster, and our own bi encoder ablation agrees with Cho.",
    # Two DIFFERENT colliding words in one answer — distinct-counting alone does not touch this
    # class, and it is the one that survives every hand-curated blocklist.
    "We fit with EM, following Cho et al.",
    "In vi we set the LA endpoint and the VA endpoint side by side.",
    "Run du -h on the mount, then open the log in vi to find the stall.",
    "The a la carte plan and the EM baseline both shipped in the same release.",
    "We keep the VA standby warm; Cho et al. call this an active-passive pair.",
    "The BI team schedules a nightly du -sh audit of the warehouse mount before the BI extract runs.",
    "In vi I set the retention to 30 days, then vi again to bump the BI refresh window.",
    # Acronyms that are also pure Vietnamese function words — the reason those three are
    # corroborators and not anchors.
    "Our BI dashboard tracks CAC and LTV per cohort, and CAC rose after the channel mix changed.",
    "We ship to SE Asia from the VA region, and CAC there is half our EU number.",
    "A senior SE reviewed the bi encoder change and Cho signed off on the ablation.",
    "The GI cohort model and the BI extract share one feature store.",
    # Contractions: the tokenizer must not shed a bare "ve" off "we've" / "I've" / "they've".
    "We've seen the EM algorithm stall, and we've since switched to variational inference.",
    "We've cited Cho et al. for the GRU, and we've reproduced their ablation.",
    "We've kept the VA replica warm and we've never had to fail over to it.",
    "You've got a bi encoder here; we've benchmarked it against a cross encoder.",
    # Single-word incidentals, each naming a word the list carries.
    "We fit a Gaussian mixture with EM. EM alternates between the E step and the M step until "
    "the log likelihood converges.",
    "The a la carte pricing page and the LA region both went down, so we failed over to us-east.",
    "I opened the config in vi, fixed the port, and closed vi before restarting the worker.",
    "Run du -h on the mount, then du -sh per shard to find the hot partition.",
    "We cache the embedding in lieu of recomputing it, following Cho et al.",
    "We train a bi-directional LSTM over bi-gram features and log a va_scores column per epoch.",
    # Ordinary ML training vocabulary. Nothing here collides today; it is in the corpus so that the
    # structural check below has something to bite on if someone adds "set", "batch" or "loss".
    "We set the batch size to 64 and watched the validation loss stop improving after epoch three.",
    "The batch scheduler retries a failed step, and we set the loss scale before each restart.",
]


def test_no_anchor_word_ever_appears_in_the_english_corpus():
    # The structural form of the whole safety property, and the one that survives new list entries:
    # anchors are supposed to be tokens English does not use, so no anchor may appear anywhere in a
    # corpus of English technical prose. A per-sentence classification test only catches a bad entry
    # once some sentence happens to reach two hits; this catches it the moment it is added.
    #
    # Split naively — on letters alone, ignoring the joiners _TOKEN_PATTERN respects — on purpose.
    # The anchor tier must be safe on its own merits and not because the tokenizer currently hides
    # the collision: "we've", "bi-gram" and "va_scores" all yield a bare anchor candidate here, so
    # promoting "ve", "bi" or "va" reddens immediately instead of waiting for a second, unrelated
    # change to the tokenizer to expose it.
    for answer in _ENGLISH_COLLISION_CORPUS:
        tokens = set(re.findall(r"[^\W\d_]+", answer.lower()))
        offenders = tokens & language._VN_ANCHOR_WORDS
        assert not offenders, f"{sorted(offenders)} is an anchor but appears in English: {answer}"


def test_the_words_the_issue_ac_names_are_present_but_cannot_carry_a_verdict():
    # #78's AC names "va" and "bi" explicitly, so their absence would be a silent regression against
    # the issue; their promotion to anchors would resurrect the contamination this fix exists to kill
    # ("Power BI", "bi encoder", the VA region). Pin both halves — membership AND tier.
    for word in ("va", "bi"):
        assert word in language._VIETNAMESE_FUNCTION_WORDS
        assert word in language._VN_CORROBORATING_WORDS
        assert word not in language._VN_ANCHOR_WORDS


def test_acronym_collisions_are_corroborators_never_anchors():
    # "cac"/"se"/"gi" are ordinary Vietnamese function words that are also CAC, SE and GI — acronyms
    # that turn up in exactly the data/BI prose this detector must leave alone. They may corroborate
    # a verdict; anchoring one would convict "Our BI dashboard tracks CAC and LTV per cohort".
    for word in ("cac", "se", "gi"):
        assert word in language._VN_CORROBORATING_WORDS
        assert word not in language._VN_ANCHOR_WORDS


@pytest.mark.parametrize("answer", _ENGLISH_COLLISION_CORPUS)
def test_english_technical_prose_is_never_read_as_vietnamese(answer):
    # The inverse of R-23, and the more dangerous direction because it fails silently: a false
    # "Vietnamese" verdict drops english_delivery from an English answer (ADR 0007's activation is
    # deterministic, so nothing downstream notices) and makes require_vietnamese a no-op in vn mode.
    # This corpus is the standing replacement for the one-off audit script that missed both.
    assert answer_is_english(answer)


def test_english_delivery_still_activates_across_the_whole_collision_corpus():
    # Asserted where the damage actually lands. answer_is_english is a private-ish signal; what a
    # mixed Session observes is the dimension quietly not activating, so pin it on the rubric too.
    for answer in _ENGLISH_COLLISION_CORPUS:
        if len(answer.split()) >= 5:
            assert "english_delivery" in rubric_with_delivery(_RUBRIC, "mixed", answer).active, answer


def test_corroborating_words_alone_never_convict_english():
    # Pins the anchor rule, the one gate that handles two DIFFERENT colliding words. Three distinct
    # hits at 3/14 = 0.214 clear the minimum and the density floor outright; the verdict is English
    # only because "vi", "la" and "va" are all words English uses, so nothing anchors it.
    assert answer_is_english("In vi we set the LA endpoint and the VA endpoint side by side.")


def test_a_single_anchor_never_flips_english():
    # Pins _VN_WORD_MIN_HITS, and pins it on a sentence that actually reaches the other two gates:
    # one anchor ("khong", quoted as data) at 1/7 = 0.143 is past the density floor and satisfies the
    # anchor rule, so only the two-distinct-word minimum holds this English.
    assert answer_is_english("The tokenizer splits khong into two subwords.")


def test_sparse_anchors_never_flip_long_english():
    # Pins _VN_WORD_RATIO_THRESHOLD: an English answer *about* Vietnamese text. Two distinct anchors
    # satisfy both the minimum and the anchor rule, so only the density floor (2/47 = 0.043 < 0.08)
    # keeps it English — quoting a couple of Vietnamese tokens must not convict the answer carrying
    # them.
    assert answer_is_english(
        "The dataset labels are Vietnamese, so tokens like khong and nhieu show up in almost every "
        "row of the corpus that we trained this intent classifier on, which skewed the learned "
        "vocabulary toward function words instead of the content words we actually wanted it to "
        "key on."
    )


def test_toneless_code_switched_vietnamese_stays_vietnamese():
    # The toneless twin of test_code_switched_vietnamese_stays_vietnamese: Vietnamese grammar
    # carrying English jargon, typed the way the target users actually type. The diacriticked version
    # short-circuits on the letter ratio and never reaches this branch.
    assert not answer_is_english(
        "Minh se dung read-through cache, neu miss thi fallback ve database, va set TTL khoang 5 phut cho hot key."
    )


@pytest.mark.parametrize(
    "answer",
    [
        # 2 distinct hits / 19 tokens = 0.105. Anchor "trong", corroborated by "vi" ("vì" = because).
        "Recall quan trong hon precision trong bai toan phat hien benh vi bo sot ca benh rat nguy hiem.",
        # 2 distinct hits / 15 tokens = 0.133. Anchor "hieu", corroborated by "la" (the copula).
        "Feature engineering tot thuong hieu qua hon la doi sang mot model phuc tap hon.",
    ],
)
def test_a_thin_toneless_answer_is_still_vietnamese(answer):
    # The thin end of the range, where every gate is simultaneously load-bearing: exactly two
    # distinct hits (so the minimum cannot rise to 3), a density between 0.08 and 0.20 (so the floor
    # cannot rise), and exactly one anchor plus one corroborator — delete "la" or "vi" from the list
    # and these fall to a single hit and read as English. This is where an answer heavy in English
    # jargon actually lands, and it is the case a curated list that dropped the colliding words lost.
    assert not answer_is_english(answer)


@pytest.mark.parametrize(
    "answer",
    [
        "Em thay model bi bias ve class majority.",  # anchor "thay"
        "Job bi kill vi het memory, em se giam batch size.",  # anchor "het"
        "Em nghi la feature nay bi leak tu tap test.",  # anchor "nay"
        "Service bi cham khi traffic tang, em se them cache.",  # anchor "khi"
        "Em da thu tang epoch nhung model van bi underfit.",  # anchor "nhung"
    ],
)
def test_short_code_switched_toneless_answers_are_vietnamese(answer):
    # How the target users actually write mid-session: a short Vietnamese frame around English
    # jargon. Each of these carries exactly one anchor, so each pins that anchor's membership — and
    # collectively they are why the anchor tier cannot be trimmed to the "obviously Vietnamese"
    # words. Note "bi" and "em" appear throughout and never anchor anything.
    assert not answer_is_english(answer)


def test_a_long_toneless_answer_stays_vietnamese_under_distinct_counting():
    # Counting distinct words instead of occurrences makes the numerator stop growing while the
    # denominator keeps going, so the density floor could in principle starve a long answer. It does
    # not: real Vietnamese spends its length on *different* function words (23 distinct over 108
    # tokens = 0.213, well clear of 0.08). Pinned because the failure would be silent and would only
    # show up on exactly the substantial answers this product exists to grade.
    assert not answer_is_english(
        "Khi minh deploy mot model recommendation len production thi viec dau tien la phai co "
        "monitoring cho data drift, boi vi phan phoi cua user behavior thay doi rat nhanh theo mua "
        "va theo cac chien dich marketing. Minh se log lai feature distribution moi ngay roi so "
        "sanh voi baseline bang population stability index, neu PSI vuot nguong thi he thong canh "
        "bao va team se xem xet retrain. Ngoai ra minh cung phai co A B test framework de danh gia "
        "model moi truoc khi rollout toan bo, khong the tin hoan toan vao offline metric duoc vi "
        "offline va online thuong khac nhau kha nhieu."
    )


@pytest.mark.parametrize(
    ("compound", "joiner"),
    [
        ("bi-gram", "hyphen"),
        ("bi-directional", "hyphen"),
        ("va_scores", "underscore"),
        ("we've", "apostrophe"),
        ("i've", "apostrophe"),
        ("cho's", "apostrophe"),
    ],
)
def test_joined_compounds_tokenize_as_one_word(compound, joiner):
    # Pins every joiner in _TOKEN_PATTERN, asserted on the tokenizer rather than through a sentence,
    # because that is where the claim is actually observable — drop any one joiner and the split
    # halves become bare "bi" / "va" / "ve" hits. This is defence in depth, not the safety property:
    # the anchor rule is what keeps English English. What it buys is that the hit counts mean what
    # they look like, so the density floor is not quietly computed over phantom vocabulary.
    assert language._TOKEN_PATTERN.findall(compound) == [compound], joiner


def test_anchors_and_corroborators_are_disjoint_and_exhaustive():
    # The two tiers are a partition, not two overlapping lists: a word in both would make the anchor
    # rule depend on set-iteration luck, and a word in neither would be silently dead.
    assert not (language._VN_ANCHOR_WORDS & language._VN_CORROBORATING_WORDS)
    assert language._VIETNAMESE_FUNCTION_WORDS == (language._VN_ANCHOR_WORDS | language._VN_CORROBORATING_WORDS)


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
