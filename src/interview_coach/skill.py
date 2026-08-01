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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

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

# Ratio applied to post-mortem reconstructed evidence (issue 0026): a scorecard rebuilt from the
# Candidate's memory of a rejected interview is second-hand — filtered through recall, emotion, and
# the missing interviewer's side — so it enters the ledger at half the weight the same score would
# earn live. It multiplies confidence_weight(), so shaky reconstructions are discounted twice: once
# for the reconstructor's own stated confidence, once for being second-hand at all. Documented here,
# next to EVIDENCE_WEIGHT, because the issue demands the ratio be an explicit, visible contract.
POSTMORTEM_WEIGHT_RATIO = 0.5


def _beta_variance(alpha: float, beta: float) -> float:
    n = alpha + beta
    return (alpha * beta) / (n * n * (n + 1.0))


# Variance of the neutral prior — the reference point that makes confidence 0 when we know nothing.
_NEUTRAL_VARIANCE = _beta_variance(NEUTRAL_ALPHA, NEUTRAL_BETA)


def score_to_quality(weighted_score: float) -> float:
    """Map an Evaluator ``weighted_score`` (1–5) onto a Beta success probability in [0, 1]."""
    return (weighted_score - 1.0) / 4.0


def panel_agreement_weight(disagreement: float) -> float:
    """Evidence weight for a panel-escalated judgment, from committee disagreement (issue 0027).

    On an escalated question the committee's agreement, not the judge's stated confidence, is the
    evidence-quality signal: a verdict the Skeptic and Advocate converged on is trustworthy evidence
    even though the *first pass* was shaky, while a verdict they split on should move the Beta less.
    ``disagreement`` is |skeptic − advocate| in score points (0–4). Linear and strictly decreasing,
    reusing the confidence-weight floor so a maximally split committee still counts as weak — not
    zero — evidence, and full consensus restores exactly ``EVIDENCE_WEIGHT`` (parity with a
    fully-confident unescalated judgment).
    """
    clamped = max(0.0, min(1.0, disagreement / 4.0))
    return EVIDENCE_WEIGHT * (CONFIDENCE_WEIGHT_FLOOR + (1.0 - CONFIDENCE_WEIGHT_FLOOR) * (1.0 - clamped))


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

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> SkillState:
        """Rehydrate a persisted Beta belief — the single rehydration point (R-20).

        This expression used to be copy-pasted at eight sites across five modules, which is how a
        serialization detail ends up being re-decided independently in five places.

        Subscripts deliberately: a malformed entry must raise rather than quietly become the neutral
        prior, because a 50%-mastery row looks entirely plausible in a report and would be believed.
        The ``str()``/``float()`` coercions absorb JSON-round-tripped ints and stringly values from
        older checkpoints, and ``__post_init__``'s ``alpha``/``beta`` > 0 check stays the one
        validation point it already is.
        """
        return cls(skill=str(raw["skill"]), alpha=float(raw["alpha"]), beta=float(raw["beta"]))

    def to_dict(self) -> dict[str, float | str]:
        """The persisted form. Key order matches every existing writer, byte for byte."""
        return {"skill": self.skill, "alpha": self.alpha, "beta": self.beta}

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


def evidence_weight_for(evaluation: Evaluation) -> float:
    """THE evidence weight for one judgment — the single source of truth (issues 0021/0027).

    Panel-escalated judgments weigh by committee agreement; everything else by the Evaluator's
    confidence. This is the *per-turn* weight, and every consumer routes through it: the belief
    update (:func:`apply_evaluations`) and the transcript's recorded ``evidence_weight``
    (:func:`aggregate_evidence_weight`, in the Supervisor's dump) must call this same function, or
    the export lies about the weight that was actually applied.
    """
    if evaluation.panel is not None:
        return panel_agreement_weight(evaluation.panel.disagreement)
    return confidence_weight(evaluation.confidence)


def apply_evaluations(state: SkillState, evaluations: Sequence[Evaluation]) -> SkillState:
    """Fold one *question* — every turn the Micro-loop scored — into a Skill's belief (R-24).

    Every turn is evidence: the loop keeps only the last turn's score for display, and folding only
    that one meant a strong seed answer followed by one weak follow-up contributed literally zero
    pseudo-counts — every Follow-up the Evaluator asked for silently erased the answer that
    motivated it (ADR 0002, evidence-aggregation addendum).

    But the *number* of turns is the Evaluator's chattiness, not the Candidate's competence: folding
    each turn at its full weight would let a 4-turn question outvote a 1-turn one 4:1 for a reason no
    candidate can influence, and the Beta's α+β is precisely what the Supervisor reads as "how sure
    are we". Dividing each turn's own weight by the turn count keeps a question's total at the *mean*
    per-turn weight, so the question is the unit of evidence and the turn is only how it is
    apportioned. Each turn keeps its own dispatch through :func:`evidence_weight_for`, so a
    panel-escalated follow-up inside an unescalated question is still priced by committee agreement.

    n == 1 divides by 1.0, which is exact in IEEE-754: a single-turn question updates bit for bit as
    it did before R-24, which is why no persisted checkpoint or golden moves.
    """
    if not evaluations:
        raise ValueError("a question folds at least one turn of evidence")
    share = float(len(evaluations))
    for evaluation in evaluations:
        state = state.observe(
            score_to_quality(evaluation.weighted_score),
            weight=evidence_weight_for(evaluation) / share,
        )
    return state


def aggregate_evidence_weight(evaluations: Sequence[Evaluation]) -> float:
    """Total pseudo-counts one question folds — the number :func:`apply_evaluations` actually adds.

    Kept next to the updater so the export cannot drift from the belief: it is the same mean, and a
    question with no scored turns (a crash — ADR 0005 keeps the prior and skips the fold) reports
    zero evidence rather than raising, because the export still has to render that row.
    """
    if not evaluations:
        return 0.0
    return sum(evidence_weight_for(evaluation) for evaluation in evaluations) / len(evaluations)


def apply_evaluation(state: SkillState, evaluation: Evaluation) -> SkillState:
    """Update a Skill's belief from a single Evaluator judgment (consumes slice 0001's output).

    Evidence weight scales with the Evaluator's confidence (issue 0021), or with committee
    agreement on a panel-escalated question (issue 0027): shaky or contested judgments move the
    posterior less than confident, consensual ones at the same score.

    A one-turn question, and there is exactly one implementation: the general case — a Micro-loop
    exchange of several turns — is :func:`apply_evaluations`. Kept for the genuinely single-shot
    judgments (``coach eval``, the Diagnostic's priors) rather than making every caller wrap a list.
    """
    return apply_evaluations(state, (evaluation,))
