"""Hard-coded question + fixture answers for slice 0001.

One question targeting the ``ml_fundamentals`` Skill. Note ``mlops_awareness`` has weight 0 here, so
it must NOT be scored — that exercises the weight-0 path. The strong/weak answers let us check that a
clearly weak answer scores below a strong one.
"""

from __future__ import annotations

from dataclasses import dataclass

from .rubric import Rubric


@dataclass(frozen=True)
class FixtureQuestion:
    skill: str
    question: str
    rubric: Rubric


QUESTION = FixtureQuestion(
    skill="ml_fundamentals",
    question=(
        "Explain the bias–variance tradeoff. How does it guide model selection and the use of "
        "regularization, and what do you watch on the learning curves?"
    ),
    rubric=Rubric(
        weights={
            "correctness": 0.4,
            "depth": 0.3,
            "communication": 0.2,
            "system_thinking": 0.1,
            "mlops_awareness": 0.0,  # disabled — must not be scored
        }
    ),
)

STRONG_ANSWER = (
    "Bias is error from overly simple assumptions; variance is sensitivity to the particular "
    "training sample. Total expected error decomposes into bias squared, variance, and irreducible "
    "noise, so lowering one often raises the other. A high-bias model like plain linear regression "
    "underfits — train and validation error are both high and close. A high-variance model like a "
    "deep unpruned tree overfits — low train error but a large gap to validation error. I use "
    "learning curves to tell them apart: if the curves converge at a high error, I add capacity or "
    "features; if there is a persistent gap, I regularize. L2 shrinks weights to reduce variance, "
    "L1 also does feature selection, and I tune the strength with cross-validation, picking the "
    "point where validation error bottoms out before it starts climbing again."
)

WEAK_ANSWER = (
    "Bias is when the model is biased and variance is just the randomness in the data. You want "
    "both to be low. If the model is bad you can usually fix it by adding more data or training for "
    "more epochs. Regularization makes the model regular so it works better."
)
