"""Question Forge pipeline tests (issue 0028, GH #29).

Gates 1–2 are pure Python and tested with fixtures; gate 3 and the Writer run against the scripted
``FakeOpenAI`` fixture so ``chat_json`` retry/validation is exercised end-to-end without a provider.
One ``@pytest.mark.live`` smoke drives the real pipeline within the n=2 budget. The review-queue
round-trip test is the spec for the human promotion gate: forge output must parse through the same
bank validator that guards ``data/questions.yaml``, and the shipped bank must never be touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from interview_coach import cli
from interview_coach.bank import validate_question
from interview_coach.concepts import ConceptNote
from interview_coach.config import load_settings
from interview_coach.forge import (
    GATE_ADMISSION,
    GATE_CONTRACT,
    GATE_NOVELTY,
    NOVELTY_SIMILARITY_THRESHOLD,
    DraftOutcome,
    ForgeError,
    ForgeRun,
    GateRejection,
    QuestionDraft,
    admission_gate,
    contract_gate,
    draft_questions,
    jaccard_similarity,
    novelty_gate,
    render_forge_report,
    run_forge,
    write_forge_outputs,
)
from interview_coach.llm import build_client
from interview_coach.rubric import Rubric
from interview_coach.seeds import QUESTION_BANK, SeedQuestion

SKILL = "ml_fundamentals"

# Grounding fixture: the only concept ids the Writer/gate 1 may reference in these tests.
_NOTE = ConceptNote(
    id="mlf_regularization",
    skill=SKILL,
    title="Regularization and the bias-variance tradeoff",
    content="L2 shrinks weights smoothly; strength is tuned by cross-validation.",
)

_WEIGHTS = {"correctness": 0.5, "depth": 0.3, "communication": 0.2}


def _draft_dict(
    question: str = "How does weight decay interact with early stopping when both control capacity?",
    *,
    difficulty: int = 3,
    weights: dict | None = None,
    concepts: list[str] | None = None,
    seeds: list[str] | None = None,
) -> dict:
    return {
        "question": question,
        "difficulty": difficulty,
        "rubric_weights": weights if weights is not None else dict(_WEIGHTS),
        "expected_concepts": concepts if concepts is not None else [_NOTE.id],
        "follow_up_seeds": seeds
        if seeds is not None
        else ["Push for when the two disagree.", "Ask for a failure case."],
    }


def _draft_set_json(*drafts: dict) -> str:
    return json.dumps({"drafts": list(drafts)})


def _draft(**kwargs) -> QuestionDraft:
    return QuestionDraft.model_validate(_draft_dict(**kwargs))


def _answer_pair_json() -> str:
    return json.dumps(
        {
            "strong_answer": "Weight decay penalizes norm growth every step while early stopping bounds "
            "the optimization trajectory; both cap effective capacity, so I tune them jointly on "
            "validation curves.",
            "weak_answer": "They both help with overfitting somehow. You just use them and it works.",
        }
    )


def _eval_json(weighted: float, dim_score: int, *, confidence: float = 0.9) -> str:
    """A schema-valid Evaluator reply over exactly the active dims of ``_WEIGHTS``.

    Confidence stays >= 0.5 and the holistic score within 1.0 of the linear mean so neither the
    self-critique nor the cross-check burns extra scripted calls (fake.call_count is the budget pin).
    """
    return json.dumps(
        {
            "dimensions": {d: {"score": dim_score, "evidence": "no evidence"} for d in _WEIGHTS},
            "weighted_score": weighted,
            "confidence": confidence,
            "follow_up_recommended": False,
            "follow_up_rationale": "resolved",
        }
    )


def _validated(question: str = "A validated prompt about regularization tradeoffs?") -> SeedQuestion:
    return SeedQuestion(
        skill=SKILL,
        question=question,
        rubric=Rubric(weights=dict(_WEIGHTS)),
        answers=("placeholder",),
        difficulty=3,
        expected_concepts=(_NOTE.id,),
        follow_up_seeds=("Probe deeper.",),
    )


# --- Writer ---------------------------------------------------------------------------------------


def test_writer_returns_typed_drafts(make_client):
    client, fake = make_client([_draft_set_json(_draft_dict(), _draft_dict(question="Second distinct prompt?"))])
    drafts = draft_questions(client, SKILL, [_NOTE], 2)
    assert [type(d) for d in drafts] == [QuestionDraft, QuestionDraft]
    assert drafts[0].expected_concepts == [_NOTE.id]
    assert fake.call_count == 1
    # the grounding context (concept ids + titles) is injected into the prompt
    prompt = fake.chat.completions.calls[0]["messages"][1]["content"]
    assert _NOTE.id in prompt and _NOTE.title in prompt


def test_writer_schema_invalid_reply_retries_once(make_client):
    client, fake = make_client(['{"nonsense": true}', _draft_set_json(_draft_dict())])
    drafts = draft_questions(client, SKILL, [_NOTE], 1)
    assert len(drafts) == 1
    assert fake.call_count == 2  # exactly one retry


def test_writer_overproduction_is_truncated_to_n(make_client):
    overproduced = _draft_set_json(*(_draft_dict(question=f"Distinct prompt number {i}?") for i in range(5)))
    client, _ = make_client([overproduced])
    drafts = draft_questions(client, SKILL, [_NOTE], 2)
    assert len(drafts) == 2  # budget cap: extra drafts would cost live gate-3 calls


def test_unusable_writer_is_a_pipeline_failure(make_client):
    client, fake = make_client(['{"nonsense": true}', "still not drafts"])
    with pytest.raises(ForgeError, match="no usable drafts"):
        run_forge(client, SKILL, 2, concepts=[_NOTE], existing_prompts=[])
    assert fake.call_count == 2


# --- Gate 1: contract -------------------------------------------------------------------------------


def _gate1(draft: QuestionDraft, *, seen: set[str] | None = None):
    return contract_gate(
        draft, skill=SKILL, concept_ids={_NOTE.id}, seen_prompts=seen if seen is not None else set(), where="draft[0]"
    )


def test_contract_gate_passes_a_valid_draft():
    validated, rejection = _gate1(_draft())
    assert rejection is None
    assert isinstance(validated, SeedQuestion)
    assert validated.skill == SKILL


def test_contract_gate_rejects_unknown_rubric_dimension():
    validated, rejection = _gate1(_draft(weights={"correctness": 0.5, "creativity": 0.5}))
    assert validated is None
    assert rejection.gate == GATE_CONTRACT
    assert "unknown rubric dimensions" in rejection.reason and "creativity" in rejection.reason


def test_contract_gate_rejects_english_delivery():
    # Issue 0024 / ADR 0007: delivery is Session state; content must never author it.
    _, rejection = _gate1(_draft(weights={"correctness": 0.5, "english_delivery": 0.5}))
    assert rejection.gate == GATE_CONTRACT
    assert "english_delivery" in rejection.reason


def test_contract_gate_rejects_nonexistent_expected_concept():
    _, rejection = _gate1(_draft(concepts=["ghost_concept"]))
    assert rejection.gate == GATE_CONTRACT
    assert "unknown concept id" in rejection.reason and "ghost_concept" in rejection.reason


def test_contract_gate_rejects_empty_follow_up_seeds():
    _, rejection = _gate1(_draft(seeds=[]))
    assert rejection.gate == GATE_CONTRACT
    assert "follow_up_seeds" in rejection.reason


def test_contract_gate_rejects_out_of_range_difficulty():
    _, rejection = _gate1(_draft(difficulty=7))
    assert rejection.gate == GATE_CONTRACT
    assert "1–5" in rejection.reason


def test_contract_gate_rejects_duplicate_prompt_within_batch():
    seen: set[str] = set()
    first, rejection = _gate1(_draft(), seen=seen)
    assert rejection is None
    _, rejection = _gate1(_draft(), seen=seen)
    assert rejection.gate == GATE_CONTRACT
    assert "duplicate question prompt" in rejection.reason


# --- Gate 2: novelty --------------------------------------------------------------------------------


def test_novelty_gate_rejects_verbatim_bank_copy():
    existing = next(iter(QUESTION_BANK[SKILL])).question
    rejection, nearest, similarity = novelty_gate(existing, [existing])
    assert rejection is not None and rejection.gate == GATE_NOVELTY
    assert "near-duplicate" in rejection.reason
    assert nearest == existing
    assert similarity == pytest.approx(1.0)


def test_novelty_gate_passes_a_novel_question():
    corpus = [q.question for qs in QUESTION_BANK.values() for q in qs]
    rejection, nearest, similarity = novelty_gate(
        "Describe how conformal prediction gives distribution-free coverage guarantees for tabular models.",
        corpus,
    )
    assert rejection is None
    assert nearest is not None and similarity < NOVELTY_SIMILARITY_THRESHOLD


def test_novelty_threshold_boundary():
    # Hand-built token sets: |A∩B|=3, |A∪B|=5 → Jaccard exactly 0.6 == threshold → rejected (>=);
    # |A∩B|=3, |A∪B|=6 → 0.5 < threshold → passes.
    corpus = ["alpha bravo charlie delta"]
    at_threshold = "alpha bravo charlie echo"
    assert jaccard_similarity(at_threshold, corpus[0]) == pytest.approx(NOVELTY_SIMILARITY_THRESHOLD)
    rejection, _, similarity = novelty_gate(at_threshold, corpus)
    assert rejection is not None and similarity == pytest.approx(0.6)

    below = "alpha bravo charlie echo foxtrot"
    assert jaccard_similarity(below, corpus[0]) == pytest.approx(0.5)
    rejection, _, _ = novelty_gate(below, corpus)
    assert rejection is None


def test_novelty_gate_accepts_a_custom_similarity_fn():
    # The embedding seam: any callable scoring [0, 1] can replace the Jaccard default.
    rejection, nearest, similarity = novelty_gate(
        "anything", ["unrelated"], similarity_fn=lambda a, b: 0.99
    )
    assert rejection is not None and rejection.gate == GATE_NOVELTY
    assert similarity == pytest.approx(0.99)


# --- Gate 3: admission ------------------------------------------------------------------------------


def test_admission_gate_admits_when_both_answers_land_in_band(make_client):
    client, fake = make_client([_answer_pair_json(), _eval_json(4.2, 4), _eval_json(2.0, 2)])
    outcome = admission_gate(client, _validated())
    assert outcome.rejection is None
    assert outcome.strong_score == pytest.approx(4.2)
    assert outcome.weak_score == pytest.approx(2.0)
    assert outcome.strong_answer and outcome.weak_answer
    assert fake.call_count == 3  # 1 answer pair + 2 evaluate calls, no hidden extras


def test_admission_gate_rejects_when_strong_answer_scores_too_low(make_client):
    client, _ = make_client([_answer_pair_json(), _eval_json(2.9, 3), _eval_json(2.0, 2)])
    outcome = admission_gate(client, _validated())
    assert outcome.rejection is not None
    assert outcome.rejection.gate == GATE_ADMISSION
    # the actual score and the violated band are named in the report
    assert "2.90" in outcome.rejection.reason and "3.5-5.0" in outcome.rejection.reason


def test_admission_gate_rejects_when_judge_cannot_separate_the_pair(make_client):
    # An indiscriminate judge (weak answer scores high) fails the weak band → rejection.
    client, _ = make_client([_answer_pair_json(), _eval_json(4.2, 4), _eval_json(4.0, 4)])
    outcome = admission_gate(client, _validated())
    assert outcome.rejection is not None and outcome.rejection.gate == GATE_ADMISSION
    assert "weak answer" in outcome.rejection.reason


def test_admission_gate_turns_judge_exception_into_rejection_not_crash(make_client):
    client, _ = make_client([_answer_pair_json(), ConnectionError("provider down")])
    outcome = admission_gate(client, _validated())
    assert outcome.rejection is not None and outcome.rejection.gate == GATE_ADMISSION
    assert "judge unavailable" in outcome.rejection.reason


def test_admission_gate_turns_answer_generation_failure_into_rejection(make_client):
    client, fake = make_client([ConnectionError("provider down")])
    outcome = admission_gate(client, _validated())
    assert outcome.rejection is not None and outcome.rejection.gate == GATE_ADMISSION
    assert "answer generation unavailable" in outcome.rejection.reason
    assert fake.call_count == 1  # no judge calls are spent once the pair is unavailable


# --- pipeline + report ------------------------------------------------------------------------------


def test_zero_drafts_surviving_to_gate_3_is_not_reported_as_success(make_client):
    # Both drafts die at gate 1 → gate 3 must spend nothing and the report must say so explicitly
    # (harness_passed([]) is vacuously True; the report guard is the defense).
    client, fake = make_client(
        [
            _draft_set_json(
                _draft_dict(weights={"correctness": 0.5, "creativity": 0.5}),
                _draft_dict(question="Second draft with a ghost concept?", concepts=["ghost"]),
            )
        ]
    )
    run = run_forge(client, SKILL, 2, concepts=[_NOTE], existing_prompts=[])
    assert fake.call_count == 1  # the Writer call only — the expensive gate never ran
    assert all(o.rejection is not None for o in run.outcomes)
    report = render_forge_report(run, provider="mimo", model="test-model", date="2026-07-11")
    assert "no draft reached the admission gate; nothing was admitted" in report
    assert "admitted: 0/2" in report


def test_full_pipeline_orders_gates_cheap_to_expensive(make_client):
    # Three drafts: one dies at gate 1 (free), one at gate 2 (free), one goes through gate 3.
    existing = "Explain how alpha bravo charlie delta interact in production systems."
    client, fake = make_client(
        [
            _draft_set_json(
                _draft_dict(weights={"correctness": 0.5, "creativity": 0.5}),
                _draft_dict(question=existing),  # verbatim copy of a corpus prompt
                _draft_dict(),
            ),
            _answer_pair_json(),
            _eval_json(4.2, 4),
            _eval_json(2.0, 2),
        ]
    )
    run = run_forge(client, SKILL, 3, concepts=[_NOTE], existing_prompts=[existing])
    assert fake.call_count == 4  # writer + (pair + 2 evaluations) for the single survivor
    gates = [o.rejection.gate if o.rejection else None for o in run.outcomes]
    assert gates == [GATE_CONTRACT, GATE_NOVELTY, None]
    assert run.outcomes[1].nearest_similarity == pytest.approx(1.0)
    report = render_forge_report(run, provider="mimo", model="test-model", date="2026-07-11")
    assert "- drafted: 3" in report
    assert "- gate 1 (contract): 3 -> 2" in report
    assert "- gate 2 (novelty): 2 -> 1" in report
    assert "- gate 3 (admission): 1 -> 1" in report
    assert "- admitted: 1/3" in report
    assert "gate contract:" in report and "gate novelty:" in report  # rejection attribution names gates


def test_report_renders_from_hand_built_outcomes_without_an_llm():
    run = ForgeRun(
        skill=SKILL,
        requested=2,
        outcomes=[
            DraftOutcome(
                draft=_draft(),
                validated=_validated(),
                nearest_question="Nearest existing prompt",
                nearest_similarity=0.31,
                strong_answer="s",
                weak_answer="w",
                strong_score=4.1,
                weak_score=1.9,
            ),
            DraftOutcome(
                draft=_draft(question="Rejected one?"),
                rejection=GateRejection(
                    gate=GATE_ADMISSION, reason="weak answer scored 3.40, outside its expected band 1.0-3.0"
                ),
            ),
        ],
    )
    report = render_forge_report(run, provider="openai", model="gpt-5.4-mini", date="2026-07-11")
    assert "- admitted: 1/2" in report
    assert "openai" in report and "gpt-5.4-mini" in report
    assert "sim 0.31" in report and "strong 4.10" in report and "weak 1.90" in report
    assert "draft 2 — gate admission: weak answer scored 3.40" in report


def test_review_queue_round_trips_through_the_bank_validator(make_client, tmp_path):
    client, _ = make_client(
        [_draft_set_json(_draft_dict()), _answer_pair_json(), _eval_json(4.2, 4), _eval_json(2.0, 2)]
    )
    run = run_forge(client, SKILL, 1, concepts=[_NOTE], existing_prompts=[])
    queue, report = write_forge_outputs(
        run, queue_path=tmp_path / "review-queue-test.yaml", provider="mimo", model="test-model", date="2026-07-11"
    )
    assert report.name == "review-queue-test-report.md"
    text = queue.read_text(encoding="utf-8")
    assert "HUMAN MERGE ONLY" in text  # provenance header survives
    data = yaml.safe_load(text)
    assert set(data) == {SKILL}
    seen: set[str] = set()
    for i, raw in enumerate(data[SKILL]):
        parsed = validate_question(
            raw, skill=SKILL, concept_ids={_NOTE.id}, seen_questions=seen, where=f"queue[{i}]"
        )
        assert isinstance(parsed, SeedQuestion)
        # answers[0] is the admitted strong answer per the bank contract (answers[0] answers the seed)
        assert parsed.answers[0].startswith("Weight decay penalizes")


def test_forge_never_touches_the_shipped_bank_files(make_client, tmp_path):
    import interview_coach

    data_dir = Path(interview_coach.__file__).parent / "data"
    bank_path = data_dir / "questions.yaml"
    concepts_path = data_dir / "concepts.yaml"
    before = (bank_path.read_bytes(), concepts_path.read_bytes())
    client, _ = make_client(
        [_draft_set_json(_draft_dict()), _answer_pair_json(), _eval_json(4.2, 4), _eval_json(2.0, 2)]
    )
    run = run_forge(client, SKILL, 1, concepts=[_NOTE], existing_prompts=[])
    write_forge_outputs(
        run, queue_path=tmp_path / "q.yaml", provider="mimo", model="test-model", date="2026-07-11"
    )
    assert (bank_path.read_bytes(), concepts_path.read_bytes()) == before


def test_run_forge_rejects_out_of_budget_n(make_client):
    client, fake = make_client(["{}"])
    with pytest.raises(ValueError, match="between 1 and 10"):
        run_forge(client, SKILL, 11, concepts=[_NOTE], existing_prompts=[])
    assert fake.call_count == 0  # fail before any spend


# --- CLI --------------------------------------------------------------------------------------------


def _cli_settings() -> SimpleNamespace:
    return SimpleNamespace(
        configured=True,
        primary_provider="mimo",
        primary_config=SimpleNamespace(model="test-model"),
    )


def test_cli_forge_writes_queue_and_report_and_exits_zero(monkeypatch, make_client, tmp_path, capsys):
    client, fake = make_client(
        [
            _draft_set_json(
                _draft_dict(concepts=["ml_fundamentals_bias_variance"])  # a real shipped concept id
            ),
            _answer_pair_json(),
            _eval_json(4.2, 4),
            _eval_json(2.0, 2),
        ]
    )
    monkeypatch.setattr(cli, "load_settings", _cli_settings)
    monkeypatch.setattr(cli, "build_client", lambda settings: client)
    out = tmp_path / "review-queue-cli.yaml"

    rc = cli.main(["forge", "--skill", SKILL, "--n", "1", "--out", str(out)])

    assert rc == 0
    assert out.exists()
    assert (tmp_path / "review-queue-cli-report.md").exists()
    assert fake.call_count == 4
    printed = capsys.readouterr().out
    assert "Per-gate yield" in printed  # the report is printed, not only written
    assert "Forge: 1/1 draft(s) admitted." in printed


def test_cli_forge_exits_one_on_pipeline_failure(monkeypatch, make_client, tmp_path, capsys):
    client, _ = make_client(["nonsense", "still nonsense"])
    monkeypatch.setattr(cli, "load_settings", _cli_settings)
    monkeypatch.setattr(cli, "build_client", lambda settings: client)

    rc = cli.main(["forge", "--skill", SKILL, "--n", "1", "--out", str(tmp_path / "q.yaml")])

    assert rc == 1
    assert "Forge FAILED" in capsys.readouterr().err


def test_cli_forge_zero_admitted_still_exits_zero(monkeypatch, make_client, tmp_path, capsys):
    # 0 admitted is information, not a pipeline failure — the queue (empty) + report are written.
    client, _ = make_client([_draft_set_json(_draft_dict(weights={"correctness": 1.0, "creativity": 1.0}))])
    monkeypatch.setattr(cli, "load_settings", _cli_settings)
    monkeypatch.setattr(cli, "build_client", lambda settings: client)
    out = tmp_path / "empty-queue.yaml"

    rc = cli.main(["forge", "--skill", SKILL, "--n", "1", "--out", str(out)])

    assert rc == 0
    assert out.exists()
    assert "Forge: 0/1 draft(s) admitted." in capsys.readouterr().out


def test_cli_forge_caps_n_at_the_budget_rail(monkeypatch):
    monkeypatch.setattr(cli, "load_settings", _cli_settings)
    monkeypatch.setattr(cli, "build_client", lambda settings: object())
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["forge", "--skill", SKILL, "--n", "11"])
    assert excinfo.value.code == 2  # argparse usage error, the config/usage exit code


# --- live smoke -------------------------------------------------------------------------------------


@pytest.mark.live
def test_live_forge_pipeline_completes_and_writes_a_queue(tmp_path):
    settings = load_settings()
    if not settings.configured:
        pytest.skip("LLM primary provider not configured — set PRIMARY_PROVIDER and provider credentials")
    client = build_client(settings)

    # n=2 keeps the worst case within the free-tier budget (~2 writer/pair calls + 4 evaluate calls).
    run = run_forge(client, SKILL, 2)

    queue, report = write_forge_outputs(
        run,
        queue_path=tmp_path / "review-queue-live.yaml",
        provider=str(getattr(client, "primary_provider", "unknown")),
        model=settings.primary_config.model or "unknown",
        date="live-smoke",
    )
    assert queue.exists() and report.exists()
    assert 1 <= len(run.outcomes) <= 2
    # every draft got a definite outcome: admitted or a gate-attributed rejection (never a crash)
    for outcome in run.outcomes:
        assert outcome.admitted or outcome.rejection.gate in {GATE_CONTRACT, GATE_NOVELTY, GATE_ADMISSION}
