"""#144: every `llm-call` line names its Session, question, turn and role.

Since R-26 every provider call logs one `llm-call provider= model= ms= ... outcome=` line, but none of
those lines said which Session, question, turn or role made the call. When two Sessions overlap,
their calls could not be told apart, and a live trajectory could not be rebuilt from the log.
"""

from __future__ import annotations

import logging
import threading

import httpx
import openai as openai_sdk

from conftest import FakeOpenAI
from interview_coach import llm as llm_module
from interview_coach import supervisor, telemetry, usage
from interview_coach.config import ProviderSettings
from interview_coach.llm import CALL_LOG_PREFIX, GroqClient
from interview_coach.microloop import ScriptedCandidate, run_micro_loop
from interview_coach.supervisor import build_session_graph, initial_session_state, session_config
from test_microloop import _eval, _followup, _seed, _tool
from test_supervisor import _decision, _diagnostic, _fake_micro_loop, _plan


def _calls(caplog) -> list[dict[str, str]]:
    return [dict(kv.split("=", 1) for kv in m.split()[1:]) for m in caplog.messages if m.startswith(CALL_LOG_PREFIX)]


def _client(model: str, replies: list) -> tuple[GroqClient, FakeOpenAI]:
    fake = FakeOpenAI(replies)
    settings = ProviderSettings(name="groq", api_key="test", base_url="http://groq.test", model=model)
    return GroqClient(settings, client=fake), fake


def _meet_on_first_call(fake: FakeOpenAI, barrier: threading.Barrier) -> None:
    """Hold this Session's first provider call until the other Session has reached its own."""
    real = fake.chat.completions.create

    def create(**kwargs):
        if not fake.chat.completions.calls:
            barrier.wait(5)
        return real(**kwargs)

    fake.chat.completions.create = create  # type: ignore[method-assign]


def test_two_overlapping_sessions_attribute_every_call_exactly_once(monkeypatch, caplog):
    monkeypatch.setattr(llm_module, "_sleep", lambda _seconds: None)
    answers = ["an okay answer with a real gap", "a fuller follow-up answer this time"]
    transient = openai_sdk.APIStatusError(
        "boom", response=httpx.Response(503, request=httpx.Request("POST", "http://groq.test")), body=None
    )
    loop = [_eval(3, follow_up=True), _tool(), _followup(), _eval(4, follow_up=False)]
    client_a, fake_a = _client("model-a", [transient, *loop])  # A's first judge call is retried
    client_b, fake_b = _client("model-b", list(loop))
    barrier = threading.Barrier(2)
    _meet_on_first_call(fake_a, barrier)
    _meet_on_first_call(fake_b, barrier)
    errors: list[BaseException] = []

    def session(sid: str, client: GroqClient) -> None:
        try:
            with usage.session_scope(sid), telemetry.trace_scope(question=1):
                run_micro_loop(client, _seed(answers), ScriptedCandidate(answers))
        except BaseException as err:  # surfaced below; a thread swallows it otherwise
            errors.append(err)

    with caplog.at_level(logging.INFO, logger="interview_coach.llm"):
        threads = [
            threading.Thread(target=session, args=("sess-a", client_a)),
            threading.Thread(target=session, args=("sess-b", client_b)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)

    assert not errors, errors
    calls = _calls(caplog)
    assert len(calls) == len(fake_a.chat.completions.calls) + len(fake_b.chat.completions.calls) == 9

    def walk(model: str) -> list[tuple[str, str, str, str, str]]:
        return [(c["session"], c["question"], c["turn"], c["role"], c["outcome"]) for c in calls if c["model"] == model]

    assert walk("model-a") == [
        ("sess-a", "1", "1", "judge", "retry:APIStatusError"),  # the retry is attributed too
        ("sess-a", "1", "1", "judge", "ok"),
        ("sess-a", "1", "1", "interviewer", "ok"),  # the lookup_concept tool turn
        ("sess-a", "1", "1", "interviewer", "ok"),  # the follow-up it grounds
        ("sess-a", "1", "2", "judge", "ok"),
    ]
    assert walk("model-b") == [
        ("sess-b", "1", "1", "judge", "ok"),
        ("sess-b", "1", "1", "interviewer", "ok"),
        ("sess-b", "1", "1", "interviewer", "ok"),
        ("sess-b", "1", "2", "judge", "ok"),
    ]


def test_a_call_outside_any_session_says_so(caplog):
    client, _ = _client("model-x", ['{"ok": true}'])
    with caplog.at_level(logging.INFO, logger="interview_coach.llm"):
        client.chat([{"role": "user", "content": "go"}])

    (call,) = _calls(caplog)
    assert (call["session"], call["question"], call["turn"], call["role"]) == ("-", "-", "-", "-")


def test_the_graph_numbers_questions_and_names_the_supervisor_and_planner(monkeypatch, make_client, caplog):
    # The scopes must survive langgraph's copied node context, as usage.session_scope already does.
    base = _fake_micro_loop(4.0)

    def micro_loop_that_calls(client, seed, candidate, state=None, *, max_turns=4, concept_store=None, **_):
        client.chat([{"role": "user", "content": "probe"}])  # stands in for the question's judge call
        return base(client, seed, candidate, state, max_turns=max_turns, concept_store=concept_store)

    monkeypatch.setattr(supervisor, "run_micro_loop", micro_loop_that_calls)
    client, _ = make_client(
        [
            '{"probe": 1}',
            _decision("advance_plan", "One answer per Skill; move on."),
            '{"probe": 2}',
            _plan("mlops", "system_design", "vietnamese_nlp"),
        ]
    )
    state = initial_session_state("trace-graph", _diagnostic(), max_questions=2, started_at=0)

    with caplog.at_level(logging.INFO, logger="interview_coach.llm"), usage.session_scope("trace-graph"):
        build_session_graph(client, now=lambda: 1).invoke(state, session_config("trace-graph"))

    assert [(c["session"], c["question"], c["role"]) for c in _calls(caplog)] == [
        ("trace-graph", "1", "-"),
        ("trace-graph", "-", "supervisor"),
        ("trace-graph", "2", "-"),
        ("trace-graph", "-", "planner"),
    ]
