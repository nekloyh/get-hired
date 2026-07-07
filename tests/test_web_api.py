from __future__ import annotations

from fastapi.testclient import TestClient

from interview_coach.config import Settings
from interview_coach.web_api import create_app


def _test_client(tmp_path):
    settings = Settings(
        _env_file=None,
        primary_provider="mimo",
        mimo_api_key="",
        mimo_base_url="",
        mimo_model="",
        groq_api_key="",
        groq_model="",
    )
    app = create_app(
        settings=settings,
        checkpoint_db=tmp_path / "checkpoints.sqlite",
        ledger_db=tmp_path / "ledger.json",
    )
    return TestClient(app)


def test_health_reports_provider_config_and_demo_availability(tmp_path):
    client = _test_client(tmp_path)

    response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["primary_provider"] == "mimo"
    assert data["primary_configured"] is False
    assert data["demo_available"] is True


def test_demo_websocket_start_answer_flow_and_export(tmp_path):
    client = _test_client(tmp_path)

    with client.websocket_connect("/api/sessions/demo-session") as ws:
        ws.send_json(
            {
                "type": "start_session",
                "mode": "demo",
                "target_role": "machine learning engineer",
                "target_companies": ["Viettel"],
                "claimed_skills": {"mlops": 3, "ml_fundamentals": 4},
                "max_questions": 1,
            }
        )
        started = ws.receive_json()
        assert started["type"] == "session_started"
        assert started["mode"] == "demo"

        question = _receive_until(ws, "question")
        assert "question" in question["question"].lower() or question["question"]

        ws.send_json(
            {
                "type": "candidate_answer",
                "answer": (
                    "I would compare training and validation behavior, watch for leakage and drift, "
                    "and explain the trade-off before choosing the model."
                ),
            }
        )

        update = _receive_until(ws, "state_update")
        assert update["state"]["question_count"] >= 1
        assert update["state"]["skill_states"]

        completed = _receive_until(ws, "session_completed")
        state = completed["state"]
        assert state["status"] == "complete"
        assert state["study_plan"]["readiness_estimate"] > 0
        assert state["transcript"][0]["turns"][0]["answer"].startswith("I would compare")

    export = client.get("/api/sessions/demo-session/export.md")
    assert export.status_code == 200
    assert "# Interview Session: demo-session" in export.text
    assert "## Study Plan" in export.text
    # issue 0021: the confidence-scaled evidence weight is auditable per question in the export.
    assert "evidence weight:" in export.text


def test_live_mode_errors_when_provider_is_unconfigured(tmp_path):
    client = _test_client(tmp_path)

    with client.websocket_connect("/api/sessions/live-session") as ws:
        ws.send_json({"type": "start_session", "mode": "live", "max_questions": 1})
        error = _receive_until(ws, "session_error")

    assert "is not configured" in error["error"]


def test_cancel_mid_question_does_not_score_an_empty_answer(tmp_path):
    # ADR 0005 / issue 0017: cancelling while a question is pending is intent, not data. It must not
    # produce an evaluation of an empty answer nor record the question as a zero-evidence failure.
    client = _test_client(tmp_path)

    with client.websocket_connect("/api/sessions/cancel-mid") as ws:
        ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
        _receive_until(ws, "session_started")
        _receive_until(ws, "question")
        ws.send_json({"type": "cancel_session"})
        error = _receive_until(ws, "session_error")
        assert "cancelled" in error["error"].lower()

    # Nothing was scored: no completed Session, so the export has nothing to render.
    export = client.get("/api/sessions/cancel-mid/export.md")
    assert export.status_code == 404


def test_resume_after_cancel_preserves_the_in_flight_question(tmp_path):
    # The cancelled question must survive: reconnect, resume, answer it for real, and the transcript
    # records the real answer — never the "" that the old cancel sentinel would have injected.
    client = _test_client(tmp_path)

    with client.websocket_connect("/api/sessions/resume-cancel") as ws:
        ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
        _receive_until(ws, "session_started")
        _receive_until(ws, "question")
        ws.send_json({"type": "cancel_session"})
        _receive_until(ws, "session_error")

    with client.websocket_connect("/api/sessions/resume-cancel") as ws:
        ws.send_json({"type": "resume_session", "mode": "demo"})
        _receive_until(ws, "session_started")
        _receive_until(ws, "question")
        ws.send_json(
            {"type": "candidate_answer", "answer": "A real answer about the bias-variance tradeoff and regularization."}
        )
        completed = _receive_until(ws, "session_completed")

    state = completed["state"]
    assert state["status"] == "complete"
    assert state["transcript"][0]["turns"][0]["answer"].startswith("A real answer")


def test_start_cancel_start_on_one_socket_clears_stale_state(tmp_path):
    # Without a per-run reset the second start inherits a set cancelled flag and a stale sentinel and
    # aborts instantly. A fresh run must reach a real question again.
    client = _test_client(tmp_path)

    with client.websocket_connect("/api/sessions/reuse-socket") as ws:
        ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
        _receive_until(ws, "session_started")
        _receive_until(ws, "question")
        ws.send_json({"type": "cancel_session"})
        _receive_until(ws, "session_error")

        ws.send_json({"type": "resume_session", "mode": "demo"})
        _receive_until(ws, "session_started")
        question = _receive_until(ws, "question")
        assert question["question"]


def test_second_connection_to_same_session_is_rejected(tmp_path):
    # Two tabs on one session_id must not run two graphs against one checkpoint thread.
    client = _test_client(tmp_path)

    with client.websocket_connect("/api/sessions/dup") as ws1:
        ws1.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
        _receive_until(ws1, "session_started")
        _receive_until(ws1, "question")

        with client.websocket_connect("/api/sessions/dup") as ws2:
            rejected = ws2.receive_json()
            assert rejected["type"] == "session_error"
            assert "active connection" in rejected["error"]


def test_returning_candidate_seeds_priors_and_carries_a_delta(tmp_path):
    # End-to-end 0023: a completed Session persists posteriors; the same candidate's next Session
    # loads them and carries the since-last-session prior means into its state.
    client = _test_client(tmp_path)

    def _run_one(session_id: str) -> dict:
        with client.websocket_connect(f"/api/sessions/{session_id}") as ws:
            ws.send_json(
                {"type": "start_session", "mode": "demo", "candidate_id": "demo", "max_questions": 1}
            )
            _receive_until(ws, "session_started")
            _receive_until(ws, "question")
            ws.send_json(
                {"type": "candidate_answer", "answer": "A solid answer about bias, variance, leakage, and drift."}
            )
            return _receive_until(ws, "session_completed")["state"]

    first = _run_one("s1")
    assert "ledger_prior_mastery" not in first  # first-ever Session is a cold start

    second = _run_one("s2")
    assert second["ledger_prior_mastery"]  # returning candidate: priors carried from the ledger


def _receive_until(ws, event_type: str, *, limit: int = 20):
    for _ in range(limit):
        event = ws.receive_json()
        if event["type"] == event_type:
            return event
    raise AssertionError(f"did not receive event type {event_type!r}")
