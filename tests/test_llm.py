from __future__ import annotations

import pytest
from pydantic import BaseModel

from interview_coach.llm import StructuredOutputError


class Foo(BaseModel):
    x: int
    label: str


def test_parses_valid_json(make_client):
    client, fake = make_client(['{"x": 7, "label": "ok"}'])
    out = client.chat_json([{"role": "user", "content": "go"}], Foo)
    assert out == Foo(x=7, label="ok")
    assert fake.call_count == 1


def test_retries_once_then_succeeds(make_client):
    client, fake = make_client(["not json at all", '{"x": 1, "label": "fixed"}'])
    out = client.chat_json([{"role": "user", "content": "go"}], Foo)
    assert out.label == "fixed"
    assert fake.call_count == 2  # one retry


def test_raises_after_exhausting_retries(make_client):
    client, fake = make_client(["bad", "still bad"])
    with pytest.raises(StructuredOutputError):
        client.chat_json([{"role": "user", "content": "go"}], Foo)
    assert fake.call_count == 2  # max_retries=1 -> 2 attempts total


def test_reasoning_content_is_ignored(make_client):
    client, _ = make_client([('{"x": 3, "label": "y"}', "<long chain-of-thought>")])
    out = client.chat_json([{"role": "user", "content": "go"}], Foo)
    assert out.x == 3


def test_strips_code_fences(make_client):
    client, _ = make_client(['```json\n{"x": 5, "label": "z"}\n```'])
    out = client.chat_json([{"role": "user", "content": "go"}], Foo)
    assert out.x == 5


def test_extracts_json_wrapped_in_prose(make_client):
    client, _ = make_client(['Here you go: {"x": 9, "label": "w"} — done.'])
    out = client.chat_json([{"role": "user", "content": "go"}], Foo)
    assert out.x == 9


def test_empty_content_is_retried(make_client):
    client, fake = make_client(["", '{"x": 2, "label": "ok"}'])
    out = client.chat_json([{"role": "user", "content": "go"}], Foo)
    assert out.x == 2
    assert fake.call_count == 2


def test_custom_validator_triggers_retry(make_client):
    calls = {"n": 0}

    def reject_first(_foo: Foo) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("nope")

    client, fake = make_client(['{"x": 1, "label": "a"}', '{"x": 1, "label": "b"}'])
    out = client.chat_json([{"role": "user", "content": "go"}], Foo, validators=[reject_first])
    assert out.label == "b"
    assert fake.call_count == 2
