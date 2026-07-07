"""The Beta-distributed Skill state and its pure-Python evidence updater (ADR 0002).

A Skill's mastery is modeled as a Beta(α, β) distribution rather than a moving average, so the
Supervisor can read *how sure we are*, not just a point estimate: ``mastery`` is the mean α/(α+β)
and ``confidence`` is derived from the variance — it rises as evidence concentrates the belief.

This node is deliberately no-LLM (ADR 0001 keeps judgment inside the Evaluator): turning an
already-produced score into an updated belief is arithmetic, so reaching for the model here would be
the wrong instinct. Correlations and informative priors are out of scope for this slice — every
Skill starts from a neutral prior and only direct evidence moves it (priors arrive with the
Diagnostic, slice 0009).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .evaluator import Evaluation

# A neutral, weak prior: Beta(1, 1) is uniform on [0, 1] — mastery 0.5 and maximal uncertainty, the
# right starting point for "no evidence yet" (ADR 0002: priors are weak, low pseudo-counts).
NEUTRAL_ALPHA = 1.0
NEUTRAL_BETA = 1.0

# Pseudo-observations a *fully confident* evaluation contributes. Deliberately small: a single answer
# is weak evidence, but ADR 0002 wants direct evidence to overtake the weak prior "within an answer or
# two". Scaled down by Evaluator confidence via confidence_weight() below.
EVIDENCE_WEIGHT = 2.0

# Floor on the confidence multiplier (issue 0021): even a zero-confidence judgment is *weak* evidence,
# not *no* evidence — a low-confidence answer still nudges the belief a little. Failed/degraded
# questions apply no evidence at all, but that is handled upstream by skipping the update entirely.
CONFIDENCE_WEIGHT_FLOOR = 0.25


def _beta_variance(alpha: float, beta: float) -> float:
    n = alpha + beta
    return (alpha * beta) / (n * n * (n + 1.0))


# Variance of the neutral prior — the reference point that makes confidence 0 when we know nothing.
_NEUTRAL_VARIANCE = _beta_variance(NEUTRAL_ALPHA, NEUTRAL_BETA)


def score_to_quality(weighted_score: float) -> float:
    """Map an Evaluator ``weighted_score`` (1–5) onto a Beta success probability in [0, 1]."""
    return (weighted_score - 1.0) / 4.0


def confidence_weight(confidence: float) -> float:
    """Evidence weight for one evaluation, scaled by the Evaluator's ``confidence`` in [0, 1] (0021).

    The Beta updater already accepts a per-observation ``weight``; this feeds it the Evaluator's own
    trustworthiness signal so a judgment the ``weighted_score`` cross-check (slice 0003) or Self-critique
    lowered the confidence of moves the posterior less than a fully confident one at the *same* score —
    the state the Supervisor steers by should not shift as hard on shaky evidence.

    Linear in confidence with a floor, so it is monotonic increasing: lower confidence ⇒ strictly
    smaller weight ⇒ strictly smaller posterior shift for an identical score. ``confidence == 1.0``
    returns exactly ``EVIDENCE_WEIGHT`` — full-confidence behavior is unchanged from the fixed-weight era.
    """
    clamped = max(0.0, min(1.0, confidence))
    return EVIDENCE_WEIGHT * (CONFIDENCE_WEIGHT_FLOOR + (1.0 - CONFIDENCE_WEIGHT_FLOOR) * clamped)


@dataclass(frozen=True)
class SkillState:
    """One Skill's mastery belief, held as a Beta(α, β) distribution."""

    skill: str
    alpha: float = NEUTRAL_ALPHA
    beta: float = NEUTRAL_BETA

    def __post_init__(self) -> None:
        if self.alpha <= 0 or self.beta <= 0:
            raise ValueError("Beta parameters alpha and beta must both be > 0")

    @classmethod
    def neutral(cls, skill: str) -> SkillState:
        """A fresh Skill carrying the weak, uninformative prior (no evidence yet)."""
        return cls(skill=skill)

    @property
    def mastery(self) -> float:
        """Point estimate of competence: the Beta mean α/(α+β), in [0, 1]."""
        return self.alpha / (self.alpha + self.beta)

    @property
    def variance(self) -> float:
        """Spread of the belief; shrinks as evidence accumulates."""
        return _beta_variance(self.alpha, self.beta)

    @property
    def confidence(self) -> float:
        """How sure we are, in [0, 1]: 0 at the neutral prior, → 1 as the variance collapses."""
        return max(0.0, min(1.0, 1.0 - self.variance / _NEUTRAL_VARIANCE))

    def observe(self, quality: float, *, weight: float = EVIDENCE_WEIGHT) -> SkillState:
        """Fold one soft observation (``quality`` in [0, 1]) in, returning a new state.

        Splits ``weight`` pseudo-observations between α (success) and β (failure) by ``quality``, so
        the mean moves toward ``quality`` while the total count α+β grows — and a larger count is
        exactly what shrinks the variance and therefore lifts ``confidence``.
        """
        if not 0.0 <= quality <= 1.0:
            raise ValueError(f"quality must be in [0, 1], got {quality}")
        if weight <= 0.0:
            raise ValueError(f"weight must be > 0, got {weight}")
        return replace(
            self,
            alpha=self.alpha + weight * quality,
            beta=self.beta + weight * (1.0 - quality),
        )


def apply_evaluation(state: SkillState, evaluation: Evaluation) -> SkillState:
    """Update a Skill's belief from an Evaluator judgment (consumes slice 0001's output).

    Evidence weight scales with the Evaluator's confidence (issue 0021): shaky judgments move the
    posterior less than confident ones at the same score.
    """
    return state.observe(
        score_to_quality(evaluation.weighted_score),
        weight=confidence_weight(evaluation.confidence),
    )
