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
    app = create_app(settings=settings, checkpoint_db=tmp_path / "checkpoints.sqlite")
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


def test_live_mode_errors_when_provider_is_unconfigured(tmp_path):
    client = _test_client(tmp_path)

    with client.websocket_connect("/api/sessions/live-session") as ws:
        ws.send_json({"type": "start_session", "mode": "live", "max_questions": 1})
        error = _receive_until(ws, "session_error")

    assert "is not configured" in error["error"]


def _receive_until(ws, event_type: str, *, limit: int = 20):
    for _ in range(limit):
        event = ws.receive_json()
        if event["type"] == event_type:
            return event
    raise AssertionError(f"did not receive event type {event_type!r}")
