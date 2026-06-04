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

_GENERIC_RUBRIC = Rubric(
    weights={
        "correctness": 0.35,
        "depth": 0.25,
        "communication": 0.2,
        "system_thinking": 0.15,
        "mlops_awareness": 0.05,
    }
)

QUESTION_BANK: dict[str, tuple[SeedQuestion, ...]] = {
    "ml_fundamentals": SEED_QUESTIONS,
    # Each non-ml_fundamentals Skill now carries ≥2 distinct seeds, each with ≥2 scripted answers, so
    # a Supervisor `extra_question` rotates to a *different* question (not a verbatim repeat) and a
    # single probe can resolve after one Follow-up instead of always tripping the safety cap.
    "deep_learning": (
        SeedQuestion(
            skill="deep_learning",
            question=(
                "Explain why residual connections help train deep neural networks, and name one "
                "failure mode they do not automatically solve."
            ),
            rubric=_GENERIC_RUBRIC,
            answers=(
                "Residual connections let layers learn a delta around an identity path, which improves "
                "gradient flow and makes very deep networks easier to optimize. They do not by "
                "themselves fix data leakage, label noise, or poor objective design.",
                "Concretely the skip path keeps the Jacobian close to identity, so gradients reach "
                "early layers without vanishing; but a wrong loss or leaked features still train a "
                "confidently wrong model — depth is no longer the bottleneck, the objective is.",
            ),
        ),
        SeedQuestion(
            skill="deep_learning",
            question=(
                "Why does batch normalization speed up training, and when can it behave surprisingly "
                "or hurt?"
            ),
            rubric=_GENERIC_RUBRIC,
            answers=(
                "It normalizes layer inputs per mini-batch, which smooths the loss landscape and lets "
                "you use higher learning rates. It can misbehave with very small batches and at "
                "inference, where it switches to running statistics.",
                "With tiny or non-i.i.d. batches the batch statistics are noisy and train/inference "
                "skew appears, so I switch to group or layer norm; in RNNs and some fine-tuning regimes "
                "I freeze the running stats to stop them drifting away from the deployment distribution.",
            ),
        ),
    ),
    "mlops": (
        SeedQuestion(
            skill="mlops",
            question=(
                "How would you monitor a production model for data drift and decide when retraining is "
                "actually justified?"
            ),
            rubric=_GENERIC_RUBRIC,
            answers=(
                "I would track input distributions, prediction distributions, calibration, and delayed "
                "ground-truth metrics. Drift alone is a signal, not an automatic retrain trigger; I would "
                "compare it with business impact, model quality degradation, and retraining risk before "
                "promoting a new model.",
                "Concretely I alert on population-stability index and prediction-distribution shifts, "
                "but gate retraining on a measured drop in the delayed ground-truth metric versus its "
                "baseline, because covariate drift without an accuracy hit usually does not justify the "
                "retraining and redeployment risk.",
            ),
        ),
        SeedQuestion(
            skill="mlops",
            question=(
                "How would you roll out a new model version safely, and how would you detect and roll "
                "back a regression?"
            ),
            rubric=_GENERIC_RUBRIC,
            answers=(
                "I would shadow the new model first, then canary it on a small traffic slice behind a "
                "feature flag, watch live and offline metrics, and promote gradually with an automatic "
                "rollback if guardrail metrics regress.",
                "The rollback trigger is a guardrail metric (latency p99, error rate, and the business "
                "KPI proxy) breaching a preset threshold versus the control arm; I keep the previous "
                "version warm so the flag flips back instantly, and I log the canary verdict for the "
                "post-mortem.",
            ),
        ),
    ),
    "system_design": (
        SeedQuestion(
            skill="system_design",
            question=(
                "Design a high-level architecture for an online feature store used by a real-time ML "
                "ranking service. What consistency risks matter?"
            ),
            rubric=_GENERIC_RUBRIC,
            answers=(
                "I would separate offline feature computation from a low-latency online store, enforce "
                "shared feature definitions, and monitor freshness. The main consistency risks are "
                "training-serving skew, stale online values, and partial backfills changing historical "
                "semantics.",
                "I close the skew gap by computing online and offline features from one declarative "
                "definition and logging served feature values for point-in-time-correct training; "
                "freshness I bound with a TTL plus a staleness metric so a lagging stream surfaces as "
                "an alert rather than silently degrading ranking quality.",
            ),
        ),
        SeedQuestion(
            skill="system_design",
            question=(
                "Design the serving path for a recommendation API under a strict p99 latency budget. "
                "What do you cache, and what breaks under load?"
            ),
            rubric=_GENERIC_RUBRIC,
            answers=(
                "I would precompute candidate sets offline, cache user and item embeddings in a "
                "low-latency store, and do only light reranking online. Under load the tail latency and "
                "cache misses are what break the budget.",
                "I protect the p99 with a candidate cache keyed by user segment, request hedging, and a "
                "timeout that falls back to a cheaper popularity ranker; the failure mode under load is "
                "a cold-cache stampede, so I add request coalescing and stale-while-revalidate rather "
                "than letting every miss hit the model.",
            ),
        ),
    ),
    "vietnamese_nlp": (
        SeedQuestion(
            skill="vietnamese_nlp",
            question=(
                "What makes Vietnamese word segmentation important for NLP models, and when might a "
                "subword transformer reduce that need?"
            ),
            rubric=_GENERIC_RUBRIC,
            answers=(
                "Vietnamese uses spaces between syllables, not always words, so segmentation changes "
                "the units seen by classical models and affects named entities and phrase meaning. "
                "Subword transformers reduce the hard dependency, but domain text and tokenization "
                "quality still matter.",
                "A compound like 'học máy' is two syllables but one concept, so a syllable-level model "
                "can split the entity; subword transformers learn the merge from data, yet a tokenizer "
                "trained mostly on English fragments Vietnamese badly, so in-domain subword vocab and "
                "diacritic-correct input still carry the result.",
            ),
        ),
        SeedQuestion(
            skill="vietnamese_nlp",
            question=(
                "How would you handle diacritic restoration for noisy Vietnamese user text, and why "
                "does it matter downstream?"
            ),
            rubric=_GENERIC_RUBRIC,
            answers=(
                "Users often type without diacritics, so 'toi di hoc' is ambiguous; I would restore "
                "diacritics with a sequence model before downstream NLP, because the un-accented form "
                "collapses distinct words and wrecks meaning.",
                "I frame it as sequence labeling or seq2seq over syllables trained on accented text "
                "with synthetic accent-stripping for parallel data; it matters because 'ma' maps to "
                "several words (ma, má, mà, mã, mạ), so skipping restoration pushes that ambiguity into "
                "every downstream classifier and degrades NER and intent detection.",
            ),
        ),
    ),
}


def select_seed_question(skill: str, question_number: int = 0) -> SeedQuestion:
    """Pick a fixture question for a Skill, rotating when the Supervisor probes the same Skill again.

    The Supervisor's seed gate keeps ``question_number`` below ``seed_count(skill)`` for deviations,
    so the modulo never re-asks an already-used seed in practice; it stays as a final safety wrap.
    """
    questions = QUESTION_BANK.get(skill)
    if not questions:
        raise ValueError(f"no seed question available for Skill {skill!r}")
    return questions[question_number % len(questions)]


def seed_count(skill: str) -> int:
    """How many distinct seed questions exist for a Skill — the Supervisor's deviation budget."""
    questions = QUESTION_BANK.get(skill)
    if not questions:
        raise ValueError(f"no seed question available for Skill {skill!r}")
    return len(questions)
