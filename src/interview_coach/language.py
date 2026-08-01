"""Language as first-class Session state (issue 0024, ADR 0007).

A Session carries an explicit ``language_mode`` — ``en`` | ``vn`` | ``mixed`` — chosen at setup and
threaded through the Session state; every prompt-bearing agent (Interviewer, Evaluator, Study
Planner) respects it. English communication quality is scored in the dedicated ``english_delivery``
rubric dimension, active only when the answer actually is English — the activation decision is
deterministic (this module), never the judge's, so a pure-VN Session can never grow phantom
delivery scores.

The bench's per-case ``language`` field ("en"/"vi"/"mixed" — the language the *answer* is written
in) is a different vocabulary from ``language_mode`` ("en"/"vn"/"mixed" — how the *Session* is
conducted); do not conflate them.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from .rubric import Rubric

LanguageMode = Literal["en", "vn", "mixed"]

LANGUAGE_MODES: tuple[str, ...] = ("en", "vn", "mixed")
DEFAULT_LANGUAGE_MODE: LanguageMode = "en"

# Weight used when english_delivery is activated. The value only signals "active": delivery is
# excluded from the weighted_score aggregation entirely (see evaluator.linear_weighted_score), so
# no weight tuning can re-entangle delivery with knowledge — the failure ADR 0007 exists to prevent.
ENGLISH_DELIVERY_WEIGHT = 1.0

# Every Vietnamese letter that plain English text never uses: đ, the breve/circumflex/horn vowels,
# and all tone-marked vowels (both bare-vowel tones like "à" and stacked forms like "ậ"). Shared
# accented letters (é, à, ô, ...) do appear in European loanwords, so detection is by *ratio*, not
# presence — see :func:`answer_is_english`.
_VIETNAMESE_CHARS = frozenset(
    "ăâđêôơư"
    "àáảãạằắẳẵặầấẩẫậ"
    "èéẻẽẹềếểễệ"
    "ìíỉĩị"
    "òóỏõọồốổỗộờớởỡợ"
    "ùúủũụừứửữự"
    "ỳýỷỹỵ"
)

# An English answer quoting one Vietnamese term (e.g. "từ ghép" in an answer about segmentation)
# stays English; a code-switched Vietnamese answer full of English jargon is still saturated with
# tone marks. 3% of alphabetic characters is comfortably between the two.
_VIETNAMESE_RATIO_THRESHOLD = 0.03

# The target users often type Vietnamese WITHOUT diacritics ("khong dau" — the fast-typing style
# this product's own question bank documents), which carries zero Vietnamese-specific letters, so a
# second deterministic signal catches it: high-frequency Vietnamese function words in their
# unaccented form.
#
# The list is NOT disjoint from English, and cannot be: unaccented Vietnamese syllables are two to
# five letters and something always collides. What every entry IS curated against is *recurrence in
# English technical prose* — a token that can appear twice in one English answer defeats the
# min-hit gate by itself, and then english_delivery silently stops activating (ADR 0007) on a
# perfectly English answer. That is why "em" (the EM algorithm; an em dash), "la" (`ls -la`, a la
# carte, the LA region), "vi" (the editor) and "du" (`du -sh`) are absent — each was measured taking
# an ordinary English answer over both gates on its own — and "lieu" with them, since "in lieu of"
# needs only one companion hit. What remains is either a non-word in English ("khong", "duoc",
# "hoac", ...) or an incidental that appears at most once in a technical answer: "dung" and "nay"
# are dictionary words no technical answer uses, "cho" is a surname (Cho et al., the GRU paper),
# "va" a US state code. Those survive on the gates rather than on curation — BOTH a minimum hit
# count AND a token-density floor must clear, so one stray token can never flip an English answer.
# fmt: off
_VIETNAMESE_FUNCTION_WORDS = frozenset(
    {
        "khong", "duoc", "nhung", "khi", "neu", "hoac", "cua", "chua", "moi",
        "nen", "nao", "vao", "cung", "minh", "vay", "toi", "va", "bi", "anh",
        "gi", "khac", "voi", "cho", "nay", "trong", "truoc", "sau", "giua",
        "cach", "dung", "hieu", "biet", "phai", "nhieu", "theo", "hinh",
        "giai", "thich",
    }
)
# fmt: on
_VN_WORD_MIN_HITS = 2
_VN_WORD_RATIO_THRESHOLD = 0.08

# A hyphen- or underscore-joined compound is ONE token. Splitting on the joiner manufactures
# function-word hits out of English technical vocabulary that never stands alone: "bi-gram" and
# "bi-directional" would each donate a bare "bi", "va_scores" a bare "va" — two hits from one
# English sentence, exactly the recurrence the curation above is meant to exclude.
_TOKEN_PATTERN = re.compile(r"[^\W\d_]+(?:[-_][^\W\d_]+)*")

# Fenced blocks and inline code spans are language-neutral: a Vietnamese answer that pastes a long
# Python snippet must not read as English because the code diluted the prose ratio.
_CODE_PATTERN = re.compile(r"```.*?```|`[^`]*`", re.DOTALL)


def answer_is_english(text: str) -> bool:
    """Whether ``text`` reads as English (deterministic — no LLM in the activation path).

    Two signals over the prose (code blocks stripped first): the ratio of Vietnamese-specific
    letters, and the density of unaccented Vietnamese function words — either marks the text as
    Vietnamese. Empty or symbol-only text is not English: there is no delivery to score.
    """
    prose = unicodedata.normalize("NFC", _CODE_PATTERN.sub(" ", text)).lower()
    alpha = [ch for ch in prose if ch.isalpha()]
    if not alpha:
        return False
    vietnamese = sum(1 for ch in alpha if ch in _VIETNAMESE_CHARS)
    if vietnamese / len(alpha) > _VIETNAMESE_RATIO_THRESHOLD:
        return False
    tokens = _TOKEN_PATTERN.findall(prose)
    hits = sum(1 for token in tokens if token in _VIETNAMESE_FUNCTION_WORDS)
    if tokens and hits >= _VN_WORD_MIN_HITS and hits / len(tokens) >= _VN_WORD_RATIO_THRESHOLD:
        return False
    return True


def validate_language_mode(mode: str) -> LanguageMode:
    """Fail loudly on an unknown mode — a typo must not silently run an English session."""
    if mode not in LANGUAGE_MODES:
        raise ValueError(f"unknown language_mode {mode!r}; expected one of {LANGUAGE_MODES}")
    return mode  # type: ignore[return-value]


# An answer this short ("yes", "ok, correct") has no English delivery to assess — activating the
# dimension would force the judge to grade the delivery of a shrug.
_MIN_DELIVERY_WORDS = 5


def rubric_with_delivery(rubric: Rubric, language_mode: str, answer: str) -> Rubric:
    """Activate (or force off) ``english_delivery`` for one answer.

    Active iff the Session assesses English (``en``/``mixed``) AND this answer is substantial
    English — a Vietnamese answer mid-``mixed``-session must not be scored on English delivery,
    and a ``vn`` Session never activates the dimension at all (issue 0024 acceptance criterion).
    Question packs never carry the dimension themselves; it is injected here, per answer.
    """
    active = (
        language_mode != "vn"
        and len(answer.split()) >= _MIN_DELIVERY_WORDS
        and answer_is_english(answer)
    )
    currently = rubric.weights.get("english_delivery", 0.0) > 0
    if active == currently:
        return rubric
    weight = ENGLISH_DELIVERY_WEIGHT if active else 0.0
    return Rubric(weights={**rubric.weights, "english_delivery": weight})
