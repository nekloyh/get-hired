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
_VIETNAMESE_CHARS = frozenset("ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ")

# An English answer quoting one Vietnamese term (e.g. "từ ghép" in an answer about segmentation)
# stays English; a code-switched Vietnamese answer full of English jargon is still saturated with
# tone marks. 3% of alphabetic characters is comfortably between the two.
_VIETNAMESE_RATIO_THRESHOLD = 0.03

# The target users often type Vietnamese WITHOUT diacritics ("khong dau" — the fast-typing style
# this product's own question bank documents), which carries zero Vietnamese-specific letters, so a
# second deterministic signal catches it: high-frequency Vietnamese function words in their
# unaccented form.
#
# The list is NOT disjoint from English and cannot be — unaccented Vietnamese syllables are two to
# five letters, so something always collides. Curating the collisions away was tried and fails in
# both directions at once: dropping every colliding word ("la", "vi", "du", ...) also drops the two
# commonest shapes in a Vietnamese technical answer, the copula definition ("X **la** ...") and the
# example framing ("**vi du** ve ..."), while the words that survive curation still collide in pairs.
# So the collisions are handled structurally instead, by splitting the list in two:
#
#   * anchors (below) are tokens English simply does not use, so their presence IS the evidence;
#   * corroborators are ordinary English tokens — they may add to the count, never carry a verdict.
#
# A Vietnamese verdict therefore always rests on at least one token that is not an English word.
# That is the whole safety property, and it is what makes the residual English collisions harmless
# rather than merely unlikely: an English answer full of "BI", "VA", "EM", "Cho" and "vi" reaches a
# high hit count and still classifies English, because none of those is an anchor.
#
# Two dictionary words sit among the anchors on judgement, not structure: "dung" and "nay" are
# English words ("dung"; the archaic "nay") that a technical interview answer never reaches for,
# and both are load-bearing for Vietnamese recall. Everything else here is a non-word in English.
# fmt: off
_VN_ANCHOR_WORDS = frozenset(
    {
        "khong", "duoc", "nhung", "khi", "neu", "hoac", "cua", "chua", "moi",
        "nen", "nao", "vao", "cung", "minh", "vay", "toi", "anh", "khac",
        "voi", "nay", "trong", "truoc", "sau", "giua", "cach", "dung", "hieu",
        "biet", "phai", "nhieu", "theo", "hinh", "giai", "thich", "tren",
        "nhu", "thi", "thay", "het",
    }
)

# Ordinary English tokens that are also high-frequency Vietnamese. Demoting rather than deleting is
# what lets the list stay a *frequency* list: "la"/"vi"/"du"/"lieu" carry the copula and example
# framings, "va" ("and") and "bi" (the passive marker) are the two #78's AC names, and the three
# acronyms are why this tier exists rather than a shorter blocklist — "cac" is CAC, "se" is SE,
# "gi" is GI, all three at home in the data/BI prose this detector must leave alone.
#
# Membership in both tiers is deliberately redundant: a Vietnamese sentence normally trips several
# entries, so removing any one word rarely changes a verdict, and no per-word necessity is claimed.
# What the tests do pin is the part that matters — the tier each word sits in, and the thin answers
# (exactly one anchor plus one corroborator) where a deletion would cost real recall.
_VN_CORROBORATING_WORDS = frozenset(
    {"la", "vi", "du", "em", "va", "bi", "cho", "ve", "lieu", "cac", "se", "gi"}
)
# fmt: on
_VIETNAMESE_FUNCTION_WORDS = _VN_ANCHOR_WORDS | _VN_CORROBORATING_WORDS

# Counted over DISTINCT words, not occurrences. A word that recurs in one English answer ("the BI
# layer ... the BI dashboards") would otherwise clear the minimum on its own, which is how a single
# unlucky list entry used to convict a whole English answer.
_VN_WORD_MIN_HITS = 2
_VN_WORD_RATIO_THRESHOLD = 0.08

# A hyphen-, underscore- or apostrophe-joined compound is ONE token. Splitting on the joiner
# manufactures function-word hits out of English that never stands alone: "bi-gram" would donate a
# bare "bi", "va_scores" a bare "va", and — the one that reaches almost every English answer — every
# "we've"/"I've"/"they've" would donate a bare "ve".
_TOKEN_PATTERN = re.compile(r"[^\W\d_]+(?:[-_'’][^\W\d_]+)*")

# Fenced blocks and inline code spans are language-neutral: a Vietnamese answer that pastes a long
# Python snippet must not read as English because the code diluted the prose ratio.
_CODE_PATTERN = re.compile(r"```.*?```|`[^`]*`", re.DOTALL)


def answer_is_english(text: str) -> bool:
    """Whether ``text`` reads as English (deterministic — no LLM in the activation path).

    Two signals over the prose (code blocks stripped first), either of which marks the text as
    Vietnamese: the ratio of Vietnamese-specific letters, and the density of *distinct* unaccented
    Vietnamese function words — the latter only when at least one of them is a word English does
    not use, so English prose cannot be convicted by its own vocabulary. Empty or symbol-only text
    is not English: there is no delivery to score.
    """
    prose = unicodedata.normalize("NFC", _CODE_PATTERN.sub(" ", text)).lower()
    alpha = [ch for ch in prose if ch.isalpha()]
    if not alpha:
        return False
    vietnamese = sum(1 for ch in alpha if ch in _VIETNAMESE_CHARS)
    if vietnamese / len(alpha) > _VIETNAMESE_RATIO_THRESHOLD:
        return False
    tokens = _TOKEN_PATTERN.findall(prose)
    hits = {token for token in tokens if token in _VIETNAMESE_FUNCTION_WORDS}
    if (
        tokens
        and len(hits) >= _VN_WORD_MIN_HITS
        and len(hits) / len(tokens) >= _VN_WORD_RATIO_THRESHOLD
        # ...and the evidence is not made up entirely of words English also uses.
        and hits & _VN_ANCHOR_WORDS
    ):
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
    active = language_mode != "vn" and len(answer.split()) >= _MIN_DELIVERY_WORDS and answer_is_english(answer)
    currently = rubric.weights.get("english_delivery", 0.0) > 0
    if active == currently:
        return rubric
    weight = ENGLISH_DELIVERY_WEIGHT if active else 0.0
    return Rubric(weights={**rubric.weights, "english_delivery": weight})
