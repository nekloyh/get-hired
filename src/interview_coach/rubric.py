"""The fixed scoring rubric. A Skill is assessed against these five dimensions.

The vocabulary is closed (per issue 0001 / CONTEXT.md). Each question carries its own per-dimension
weights; a weight of 0 disables that dimension so the Evaluator does not score it.
"""

from __future__ import annotations

from pydantic import BaseModel, model_validator

# Canonical order — used everywhere active dimensions are listed.
DIMENSIONS: tuple[str, ...] = (
    "correctness",
    "depth",
    "communication",
    "system_thinking",
    "mlops_awareness",
    "english_delivery",
)

# The five knowledge dimensions. ``english_delivery`` (issue 0024, ADR 0007) is scored like any
# other dimension but is excluded from every weighted_score aggregation: the Beta skill posterior
# must move on technical evidence only, or an English-communication gap re-entangles with a
# knowledge gap — the exact misread of VN candidates the ADR separates.
TECHNICAL_DIMENSIONS: tuple[str, ...] = tuple(d for d in DIMENSIONS if d != "english_delivery")

# Short 1↔5 anchors so the Evaluator scores against a shared scale rather than vibes. The
# `correctness` and `system_thinking` anchors are spelled out at the 2/4 bands to mirror the BARS
# exemplars the calibration bench (issue 0022) labels against — without them the judge inflated
# correctness (+0.53) and under-credited system_thinking (−0.53), banking system-reasoning merit as
# raw correctness. Keep these in sync with `data/bench/cases.yaml:anchors`.
#
# The `correctness` 3 anchor was added 2026-07-27 (GH #92). Its absence was a measured defect, not a
# cosmetic gap: with anchors at 1/2/4/5 and nothing at 3, "names the right technique but justifies it
# with a bare 'so it is better'" had no home, so the judge fell off whichever side the *phrasing*
# suggested. On the `dl_overfitting_weak` pair — the same answer in two languages, human-labelled 3 —
# it scored the English 2/2/2 and the Vietnamese 4/4/4 across three runs: a two-point language split
# on identical content, and the reason the VN twin sat above its band top. `communication`, which
# already had a 3 anchor, split by only one point on the same pair.
DIMENSION_GUIDE: dict[str, str] = {
    "correctness": (
        "Are the claims technically accurate? 1 = mostly wrong/misleading; "
        "2 = a real technical error or a vague half-right statement; "
        "3 = nothing wrong, but the claim is left as a bare assertion — the right technique or term "
        "is named and the justification is an unsupported 'so it is better' / 'it helps', with no "
        "mechanism given; "
        "4 = accurate with the key mechanism stated correctly, even if not exhaustive; "
        "5 = precise AND complete. Being merely correct is a 4, not a 5 — reserve 5 for no gaps. "
        "A bare assertion cannot reach 4 however fluently or confidently it is phrased, in any "
        "language; an awkwardly worded but mechanism-bearing claim is a 4."
    ),
    "depth": (
        "Beyond surface recall? 1 = shallow/keyword-level; 2 = names concepts without mechanisms; "
        "3 = states a mechanism but stops there — nothing about what it costs, when it fails, or "
        "what it trades away; "
        "4 = states the mechanism AND one real trade-off or failure mode — award 4 for that pair "
        "even when brief; do NOT demand edge cases or exhaustive coverage for a 4; "
        "5 = also covers edge cases or limits of the approach. "
        "Deciding 1 vs 2 ONLY: a 2 must introduce at least one idea the question did not already "
        "supply. An answer that echoes the question's own vocabulary back and asserts that it "
        "matters has named nothing, so it is a 1 in any language. "
        "Deciding 2 vs 3 ONLY: a mechanism says HOW the technique produces the effect asked about, "
        "not merely what it does — 'it switches units off, so it is better' names an operation and "
        "asserts a benefit with no step between them, so it is a 2 in any language. Neither test "
        "applies above 3: an answer naming a mechanism and one trade-off is a 4 even if compressed. "
        "A mechanism with no cost attached is a 3 however fluently or confidently it is phrased, in "
        "any language; an awkwardly worded answer that does name the trade-off is a 4."
    ),
    "communication": (
        "Clear and well-structured? Judge ORGANIZATION, not fluency: 1 = rambling/confusing; "
        "3 = readable sentences but unscoped or meandering, OR a bare claim with nothing after it "
        "to organize; 4 = ordered and well-scoped (claim -> mechanism -> example), no filler; "
        "5 = also concise with clear signposting. "
        "Fluent phrasing alone is a 3, not a 4 — an eloquent but disorganized answer earns no "
        "communication credit for its eloquence, and an answer too short to HAVE a structure "
        "cannot score 4 for sounding natural."
    ),
    "system_thinking": (
        "Reasons about the whole system & trade-offs? Award 4 whenever the answer connects a "
        "diagnosis to the trade-off it drives and a downstream consequence — credit this chain "
        "generously even when stated briefly or implicitly; do not demand textbook phrasing. "
        "5 = also weighs alternatives and constraints. "
        "3 = the fix is tied to ONE link of that chain — either why it is needed or what it "
        "affects — but the interaction is asserted rather than traced; monitoring or alerting "
        "added ALONGSIDE a fix is not reasoning about that fix's effect on the system and does not "
        "by itself lift a 2 to a 3. "
        "Drop to 2 only when a fix is named in pure "
        "isolation ('add data', 'use dropout') with no reasoning about why or what it costs; "
        "1 = no systems reasoning at all. Err toward recognizing partial systems reasoning rather "
        "than withholding credit — but an asserted chain is a 3 however fluently or confidently it "
        "is phrased, in any language."
    ),
    "mlops_awareness": (
        "Aware of production realities (serving, monitoring, drift, retraining)? 1 = none, 5 = strong and concrete."
    ),
    "english_delivery": (
        "How clearly is the answer DELIVERED in English — wording, sentence structure, "
        "professional phrasing? Judge delivery only, never the technical content (that is what the "
        "other dimensions are for). 1 = very hard to follow; 2 = frequent broken phrasing that "
        "obscures the meaning; 3 = understandable but consistently awkward; 4 = clear professional "
        "English with minor slips; 5 = crisp, natural, well-structured."
    ),
}


class Rubric(BaseModel):
    """Per-question dimension weights. A weight of 0 disables that dimension."""

    weights: dict[str, float]

    @model_validator(mode="after")
    def _check(self) -> Rubric:
        unknown = set(self.weights) - set(DIMENSIONS)
        if unknown:
            raise ValueError(f"unknown rubric dimensions: {sorted(unknown)}")
        if any(w < 0 for w in self.weights.values()):
            raise ValueError("rubric weights must be >= 0")
        if not self.active_technical:
            # english_delivery alone cannot carry a question: weighted_score aggregates technical
            # dimensions only (ADR 0007), so a delivery-only rubric would have no score to keep.
            raise ValueError("at least one technical dimension must have weight > 0")
        return self

    @property
    def active(self) -> list[str]:
        """Dimensions to score, in canonical order (weight > 0)."""
        return [d for d in DIMENSIONS if self.weights.get(d, 0.0) > 0]

    @property
    def active_technical(self) -> list[str]:
        """Active dimensions that feed weighted_score — everything except english_delivery."""
        return [d for d in TECHNICAL_DIMENSIONS if self.weights.get(d, 0.0) > 0]

    def render(self) -> str:
        """Human-readable active rubric for the Evaluator prompt."""
        lines = []
        for d in self.active:
            marker = (
                " (assessed separately — NEVER counts toward weighted_score)"
                if d == "english_delivery"
                else f" (weight {self.weights[d]:g})"
            )
            lines.append(f"- {d}{marker}: {DIMENSION_GUIDE[d]}")
        return "\n".join(lines)
