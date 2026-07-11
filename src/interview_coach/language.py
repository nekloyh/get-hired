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


def answer_is_english(text: str) -> bool:
    """Whether ``text`` reads as English (deterministic — no LLM in the activation path).

    Counts Vietnamese-specific letters against all alphabetic characters after NFC folding.
    Empty or symbol-only text is not English: there is no delivery to score.
    """
    folded = unicodedata.normalize("NFC", text).lower()
    alpha = [ch for ch in folded if ch.isalpha()]
    if not alpha:
        return False
    vietnamese = sum(1 for ch in alpha if ch in _VIETNAMESE_CHARS)
    return vietnamese / len(alpha) <= _VIETNAMESE_RATIO_THRESHOLD


def validate_language_mode(mode: str) -> LanguageMode:
    """Fail loudly on an unknown mode — a typo must not silently run an English session."""
    if mode not in LANGUAGE_MODES:
        raise ValueError(f"unknown language_mode {mode!r}; expected one of {LANGUAGE_MODES}")
    return mode  # type: ignore[return-value]


def rubric_with_delivery(rubric: Rubric, language_mode: str, answer: str) -> Rubric:
    """Activate (or force off) ``english_delivery`` for one answer.

    Active iff the Session assesses English (``en``/``mixed``) AND this answer is English — a
    Vietnamese answer mid-``mixed``-session must not be scored on English delivery, and a ``vn``
    Session never activates the dimension at all (issue 0024 acceptance criterion). Question packs
    never carry the dimension themselves; it is injected here, per answer.
    """
    active = language_mode != "vn" and answer_is_english(answer)
    currently = rubric.weights.get("english_delivery", 0.0) > 0
    if active == currently:
        return rubric
    weight = ENGLISH_DELIVERY_WEIGHT if active else 0.0
    return Rubric(weights={**rubric.weights, "english_delivery": weight})
