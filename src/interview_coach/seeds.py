"""Seed questions that give the micro-loop (slice 0005) real content to run on.

Three questions for the single ``ml_fundamentals`` Skill, each carrying its own rubric and a scripted
candidate transcript: ``answers[0]`` is the reply to the question itself, and ``answers[1:]`` are the
canned replies to successive Follow-ups (the fixture Candidate of ADR/issue 0005). A strong opening
answer is meant to resolve the question in one turn; a weak one invites the Evaluator to flag a
Follow-up, after which the scripted replies improve so the loop converges instead of running away.

A richer question bank and live (human) candidates are later slices (0013 / UI 0012); these seeds
exist so the loop has something honest to chew on while it is being built.
"""

from __future__ import annotations

from dataclasses import dataclass

from .rubric import Rubric

SKILL = "ml_fundamentals"

# Same shape as the slice-0001 fixture rubric: correctness-led, mlops disabled for these foundational
# questions. Per-question copies keep each seed self-contained (a later slice may vary the weights).
_ML_RUBRIC = Rubric(
    weights={
        "correctness": 0.4,
        "depth": 0.3,
        "communication": 0.2,
        "system_thinking": 0.1,
        "mlops_awareness": 0.0,  # disabled for foundational ML questions
    }
)


@dataclass(frozen=True)
class SeedQuestion:
    """One question plus the fixture Candidate's scripted transcript for it."""

    skill: str
    question: str
    rubric: Rubric
    answers: tuple[str, ...]  # answers[0] -> the question; answers[1:] -> successive follow-ups

    def __post_init__(self) -> None:
        if not self.answers:
            raise ValueError("a seed question needs at least one candidate answer")


SEED_QUESTIONS: tuple[SeedQuestion, ...] = (
    # Strong opener — meant to resolve in a single turn (no Follow-up expected).
    SeedQuestion(
        skill=SKILL,
        question=(
            "Explain the bias–variance tradeoff and how it guides model selection and regularization. "
            "What do you watch on the learning curves?"
        ),
        rubric=_ML_RUBRIC,
        answers=(
            "Bias is error from overly simple assumptions; variance is sensitivity to the particular "
            "training sample. Expected error decomposes into bias squared, variance, and irreducible "
            "noise, so lowering one often raises the other. A high-bias model underfits — train and "
            "validation error are both high and close; a high-variance model overfits — low train "
            "error but a wide gap to validation. I read learning curves to tell them apart: curves "
            "that converge at a high error mean I should add capacity or features; a persistent gap "
            "means I should regularize. L2 shrinks weights to cut variance, L1 also does feature "
            "selection, and I tune the strength with cross-validation, picking where validation error "
            "bottoms out before it climbs again.",
            # Backup reply if the Evaluator still probes (e.g. asks for a concrete diagnosis).
            "Concretely: if I see train MSE 0.1 and validation MSE 0.9, that wide gap is high variance, "
            "so I add L2, gather more data, or reduce model capacity, and I confirm the gap narrows.",
        ),
    ),
    # Weak opener that improves under probing — the loop should ask a Follow-up, then converge.
    SeedQuestion(
        skill=SKILL,
        question=(
            "Why does L2 regularization reduce overfitting, and how would you choose its strength?"
        ),
        rubric=_ML_RUBRIC,
        answers=(
            "L2 regularization stops overfitting by making the model simpler. You add it to the loss "
            "and it makes the weights smaller, which is better. You pick the strength by trying a few "
            "values and seeing what works.",
            "It adds a penalty proportional to the sum of squared weights, so the optimizer trades a "
            "little training fit for smaller weights. Smaller weights mean a smoother function that is "
            "less sensitive to individual training points, which is what lowers variance.",
            "I choose lambda with k-fold cross-validation over a log-spaced grid, picking the value "
            "where mean validation error is lowest; too large under-fits (bias rises), too small lets "
            "variance back in, so I look for the bottom of that validation curve.",
        ),
    ),
    # Partially-correct opener with a real gap (the failure modes) — invites one targeted Follow-up.
    SeedQuestion(
        skill=SKILL,
        question=(
            "Explain how k-fold cross-validation works and when it can still mislead you."
        ),
        rubric=_ML_RUBRIC,
        answers=(
            "You split the data into k folds, train on k-1 and validate on the held-out fold, rotate "
            "through all k, and average the scores. It gives a more stable estimate than a single "
            "split.",
            "It misleads when the folds break an assumption: with time series, random folds leak the "
            "future into training, so I use forward-chaining splits; with grouped or imbalanced data I "
            "use grouped or stratified folds; and any preprocessing fit on the whole set before "
            "splitting leaks information and inflates the score.",
        ),
    ),
)
