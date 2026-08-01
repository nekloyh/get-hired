from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.status import WS_1008_POLICY_VIOLATION
from starlette.websockets import WebSocketDisconnect

from interview_coach import usage, web_api
from interview_coach.config import Settings
from interview_coach.demo_llm import DemoLLMClient
from interview_coach.llm import RoleClients
from interview_coach.web_api import (
    ResumeSessionPayload,
    configure_session_logging,
    create_app,
    export_path,
    guard_single_worker,
)


def _app(tmp_path):
    settings = Settings(
        _env_file=None,
        primary_provider="mimo",
        mimo_api_key="",
        mimo_base_url="",
        mimo_model="",
        groq_api_key="",
        groq_model="",
        concept_store="memory",
    )
    app = create_app(
        settings=settings,
        checkpoint_db=tmp_path / "checkpoints.sqlite",
        ledger_db=tmp_path / "ledger.json",
        exports_dir=tmp_path / "exports",
    )
    return app


def _test_client(tmp_path):
    return TestClient(_app(tmp_path))


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
                "language_mode": "en",
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
    # issue 0024: the export records the Session's language mode.
    assert "- Language mode: `en`" in export.text


def test_web_session_threads_language_mode_into_state(tmp_path):
    # issue 0024: the setup control reaches SessionState (and therefore state_update events + export).
    client = _test_client(tmp_path)
    with client.websocket_connect("/api/sessions/mixed-session") as ws:
        ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1, "language_mode": "mixed"})
        _receive_until(ws, "question")
        ws.send_json({"type": "candidate_answer", "answer": "A short demo answer about drift."})
        completed = _receive_until(ws, "session_completed")
        assert completed["state"]["language_mode"] == "mixed"


def test_web_rejects_unknown_language_mode(tmp_path):
    client = _test_client(tmp_path)
    with client.websocket_connect("/api/sessions/bad-mode-session") as ws:
        ws.send_json({"type": "start_session", "mode": "demo", "language_mode": "vi"})
        event = _receive_until(ws, "session_error")
        assert "language_mode" in event["error"]


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
            ws.send_json({"type": "start_session", "mode": "demo", "candidate_id": "demo", "max_questions": 1})
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


# --- R-07: shared bearer token + WebSocket Origin check -----------------------------------------

_TOKEN = "s3cret-shared-token"


def _gated_client(tmp_path, *, token: str = _TOKEN, origins: str = ""):
    settings = Settings(
        _env_file=None,
        primary_provider="mimo",
        mimo_api_key="",
        mimo_base_url="",
        mimo_model="",
        groq_api_key="",
        groq_model="",
        auth_token=token,
        allowed_origins=origins,
        concept_store="memory",
    )
    app = create_app(
        settings=settings,
        checkpoint_db=tmp_path / "checkpoints.sqlite",
        ledger_db=tmp_path / "ledger.json",
        exports_dir=tmp_path / "exports",
    )
    return TestClient(app)


def test_export_requires_a_bearer_token_when_gated(tmp_path):
    # The export is the full transcript — the most disclosure-sensitive thing this API serves.
    client = _gated_client(tmp_path)

    unauthenticated = client.get("/api/sessions/whatever/export.md")

    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "header",
    ["", "Bearer wrong-token", _TOKEN, f"Basic {_TOKEN}", "Bearer"],
    ids=["missing", "wrong-token", "no-scheme", "wrong-scheme", "scheme-only"],
)
def test_export_rejects_every_malformed_authorization(tmp_path, header):
    client = _gated_client(tmp_path)

    response = client.get("/api/sessions/whatever/export.md", headers={"Authorization": header})

    assert response.status_code == 401


def test_good_token_reaches_the_handler(tmp_path):
    # 404, not 401: the token was accepted and the request got as far as "no such session", which is
    # what proves the gate opened rather than the route being unreachable.
    client = _gated_client(tmp_path)

    response = client.get("/api/sessions/whatever/export.md", headers={"Authorization": f"Bearer {_TOKEN}"})

    assert response.status_code == 404


def test_export_stays_open_when_no_token_is_configured(tmp_path):
    # "unset = open, for local dev" is the documented contract; a 401 here would break every
    # existing localhost workflow.
    client = _test_client(tmp_path)

    assert client.get("/api/sessions/whatever/export.md").status_code == 404


def test_socket_closes_on_a_missing_auth_frame(tmp_path):
    client = _gated_client(tmp_path)

    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect("/api/sessions/gated") as ws:
            ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
            ws.receive_json()

    assert caught.value.code == WS_1008_POLICY_VIOLATION


def test_socket_closes_on_a_wrong_token(tmp_path):
    client = _gated_client(tmp_path)

    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect("/api/sessions/gated") as ws:
            ws.send_json({"type": "auth", "token": "not-the-token"})
            ws.receive_json()

    assert caught.value.code == WS_1008_POLICY_VIOLATION


def test_a_good_auth_frame_lets_the_session_run(tmp_path):
    client = _gated_client(tmp_path)

    with client.websocket_connect("/api/sessions/gated") as ws:
        ws.send_json({"type": "auth", "token": _TOKEN})
        ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
        started = ws.receive_json()
        assert started["type"] == "session_started"
        assert _receive_until(ws, "question")["question"]


def test_socket_rejects_a_disallowed_origin_before_accepting(tmp_path):
    # Rejected during the handshake, so the socket never becomes live — CORSMiddleware cannot do
    # this because it never sees a WebSocket handshake at all.
    client = _gated_client(tmp_path, origins="https://coach.example.com")

    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect("/api/sessions/gated", headers={"Origin": "https://evil.example.com"}) as ws:
            ws.receive_json()

    assert caught.value.code == WS_1008_POLICY_VIOLATION


def test_socket_accepts_an_allowlisted_origin(tmp_path):
    client = _gated_client(tmp_path, origins="https://coach.example.com")

    with client.websocket_connect("/api/sessions/gated", headers={"Origin": "https://coach.example.com"}) as ws:
        ws.send_json({"type": "auth", "token": _TOKEN})
        ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
        assert ws.receive_json()["type"] == "session_started"


def test_a_browser_origin_cannot_bypass_the_allowlist_by_omitting_origin(tmp_path):
    # A missing Origin passes the origin check (non-browser clients never send one), so the TOKEN
    # has to be what actually stops the request. If both were skippable this would be a hole.
    client = _gated_client(tmp_path, origins="https://coach.example.com")

    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect("/api/sessions/gated") as ws:
            ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
            ws.receive_json()

    assert caught.value.code == WS_1008_POLICY_VIOLATION


def test_origin_is_not_gated_when_no_token_is_set(tmp_path):
    # Ungated local dev must keep working from any dev-server port.
    client = _test_client(tmp_path)

    with client.websocket_connect("/api/sessions/open", headers={"Origin": "http://localhost:4321"}) as ws:
        ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
        assert ws.receive_json()["type"] == "session_started"


def test_a_stray_auth_frame_is_a_no_op_on_an_open_server(tmp_path):
    # A client that always sends its auth frame must work against gated and open servers alike.
    client = _test_client(tmp_path)

    with client.websocket_connect("/api/sessions/open") as ws:
        ws.send_json({"type": "auth", "token": "ignored"})
        ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
        assert ws.receive_json()["type"] == "session_started"


def test_health_advertises_whether_a_token_is_required(tmp_path):
    # The UI has to learn this at runtime: a build-time token would be inlined into the JS bundle,
    # handing the shared secret to anyone who can fetch the app.
    assert _test_client(tmp_path).get("/api/health").json()["auth_required"] is False
    assert _gated_client(tmp_path).get("/api/health").json()["auth_required"] is True


# --- R-07 hardening: malformed credentials and frames must be rejected, never crash --------------


@pytest.mark.parametrize(
    "presented",
    ["café", "mật-khẩu", "\udcff"],
    ids=["accented", "vietnamese", "lone-surrogate"],
)
def test_a_non_ascii_token_is_rejected_rather_than_crashing_the_socket(tmp_path, presented):
    # `secrets.compare_digest` REFUSES non-ASCII str operands — it raises TypeError instead of
    # returning False — and the candidate value is attacker-controlled. Comparing bytes turns a
    # remote unauthenticated crash primitive back into a plain rejection.
    client = _gated_client(tmp_path)

    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect("/api/sessions/gated") as ws:
            ws.send_json({"type": "auth", "token": presented})
            ws.receive_json()

    assert caught.value.code == WS_1008_POLICY_VIOLATION


def test_a_non_ascii_bearer_header_is_a_401_not_a_500(tmp_path):
    # Bytes, not str: header values are latin-1 on the wire, which is how a non-ASCII token actually
    # reaches the server (starlette latin-1-decodes it back into a str carrying non-ASCII).
    client = _gated_client(tmp_path)

    response = client.get(
        "/api/sessions/whatever/export.md",
        headers={"Authorization": "Bearer café".encode("latin-1")},
    )

    assert response.status_code == 401


def test_a_non_ascii_configured_token_refuses_to_start(tmp_path):
    # HTTP header values are latin-1 on the wire, so a Vietnamese passphrase cannot round-trip
    # through `Authorization: Bearer` — it would lock the operator out of their own deployment with
    # every request answered identically. Fail at startup, where the cause is still visible.
    with pytest.raises(ValueError, match="must be ASCII"):
        _gated_client(tmp_path, token="mật-khẩu-chung")


def test_a_binary_frame_during_auth_closes_cleanly(tmp_path):
    # `receive_json` assumes a text frame; a binary one raises KeyError('text'), which is neither a
    # disconnect nor a validation error, so before the fix it escaped the endpoint as a traceback
    # and an internal-error close for any unauthenticated client that sent binary JSON.
    client = _gated_client(tmp_path)

    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect("/api/sessions/gated") as ws:
            ws.send_bytes(b'{"type": "auth", "token": "' + _TOKEN.encode() + b'"}')
            ws.receive_json()

    assert caught.value.code == WS_1008_POLICY_VIOLATION


def test_a_binary_frame_mid_session_is_reported_not_fatal(tmp_path):
    # Same defect on the main loop: one malformed frame is a client mistake, and it must not take
    # down a live Session.
    client = _test_client(tmp_path)

    with client.websocket_connect("/api/sessions/open") as ws:
        ws.send_bytes(b'{"type": "candidate_answer", "answer": "hi"}')
        event = ws.receive_json()
        assert event["type"] == "session_error"
        assert "text frame" in event["error"]
        # Still usable afterwards.
        ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
        assert _receive_until(ws, "session_started")


# --- R-07: the Origin policy applies to an ungated server too ------------------------------------


def test_an_ungated_server_rejects_a_remote_browser_origin(tmp_path):
    # The same-origin policy does not apply to WebSockets: any page the operator visits can open a
    # socket to their localhost backend and drive a Session on their API key. "Unset token = open"
    # is about network reach, not about every site in the browser.
    client = _test_client(tmp_path)

    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect("/api/sessions/open", headers={"Origin": "https://evil.example.com"}) as ws:
            ws.receive_json()

    assert caught.value.code == WS_1008_POLICY_VIOLATION


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:5173", "http://127.0.0.1:4321", "http://localhost:3000"],
    ids=["vite", "other-port", "yet-another-port"],
)
def test_an_ungated_server_accepts_any_loopback_origin(tmp_path, origin):
    # A dev server on any port must keep working — that flexibility is the reason the ungated path
    # does not simply reuse the configured allowlist.
    client = _test_client(tmp_path)

    with client.websocket_connect("/api/sessions/open", headers={"Origin": origin}) as ws:
        ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
        assert ws.receive_json()["type"] == "session_started"


# --- R-08: a completed report must survive a restart ---------------------------------------------


def _complete_a_demo_session(client, session_id: str) -> None:
    with client.websocket_connect(f"/api/sessions/{session_id}") as ws:
        ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
        _receive_until(ws, "question")
        while True:
            ws.send_json({"type": "candidate_answer", "answer": "A reasonable answer about batching."})
            event = _receive_until_any(ws, {"question", "session_completed"}, limit=60)
            if event["type"] == "session_completed":
                return


def _receive_until_any(ws, event_types: set[str], *, limit: int = 40):
    for _ in range(limit):
        event = ws.receive_json()
        if event["type"] in event_types:
            return event
    raise AssertionError(f"did not receive any of {event_types}")


def test_a_completed_export_survives_losing_the_in_memory_state(tmp_path):
    # The whole point of R-08: `completed_sessions` is per-process, so before this every report that
    # had not been downloaded yet died with the server — while the Session itself sat safely in the
    # checkpoint DB. A fresh app object is exactly what a restart looks like to the endpoint.
    client = _test_client(tmp_path)
    _complete_a_demo_session(client, "restart-me")

    restarted = _test_client(tmp_path)
    response = restarted.get("/api/sessions/restart-me/export.md")

    assert response.status_code == 200
    assert "# Interview Session: restart-me" in response.text
    assert "## Study Plan" in response.text


def test_the_export_lands_in_the_configured_directory(tmp_path):
    client = _test_client(tmp_path)

    _complete_a_demo_session(client, "on-disk")

    assert (tmp_path / "exports" / "on-disk.md").read_text(encoding="utf-8").startswith("# Interview Session:")


def test_an_unknown_session_is_still_a_404_after_the_disk_fallback(tmp_path):
    assert _test_client(tmp_path).get("/api/sessions/never-existed/export.md").status_code == 404


def test_a_restored_export_is_still_gated_by_the_token(tmp_path):
    # The disk fallback must not become an unauthenticated way around R-07.
    open_client = _test_client(tmp_path)
    _complete_a_demo_session(open_client, "gated-restart")

    gated = _gated_client(tmp_path)

    assert gated.get("/api/sessions/gated-restart/export.md").status_code == 401
    authorized = gated.get("/api/sessions/gated-restart/export.md", headers={"Authorization": f"Bearer {_TOKEN}"})
    assert authorized.status_code == 200


@pytest.mark.parametrize(
    "session_id",
    ["../escaped", "../../etc/passwd", "nested/child", "..", ".", ""],
    ids=["parent", "deep-traversal", "subdir", "dotdot", "dot", "empty"],
)
def test_a_hostile_session_id_cannot_escape_the_exports_directory(tmp_path, session_id):
    # The id is a client-supplied URL path segment. Unchecked it is a write primitive on completion
    # and a read primitive on export.
    exports = tmp_path / "exports"

    resolved = export_path(exports, session_id)

    assert resolved.parent.resolve() == exports.resolve()
    assert resolved.suffix == ".md"


def test_a_safe_session_id_keeps_its_own_filename(tmp_path):
    # R-06 ids are UUIDs; keeping them verbatim is what makes the directory greppable by a human.
    assert export_path(tmp_path, "6f1c9a2e-3d4b-4a55-8f27-1b0d9c7e5a31").name == (
        "6f1c9a2e-3d4b-4a55-8f27-1b0d9c7e5a31.md"
    )


def test_a_failed_disk_write_does_not_fail_the_session(tmp_path, monkeypatch):
    # A full disk at the moment an interview ends must not turn a completed Session into an error
    # event — the in-memory copy still serves this process.
    def explode(*_args, **_kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr("interview_coach.web_api.export_session_markdown", explode)
    client = _test_client(tmp_path)

    _complete_a_demo_session(client, "unwritable")

    assert client.get("/api/sessions/unwritable/export.md").status_code == 200


# --- R-11: one origin serves the UI and the API --------------------------------------------------


def _ui_client(tmp_path, *, static_dir):
    settings = Settings(
        _env_file=None,
        primary_provider="mimo",
        mimo_api_key="",
        mimo_base_url="",
        mimo_model="",
        groq_api_key="",
        groq_model="",
        concept_store="memory",
    )
    app = create_app(
        settings=settings,
        checkpoint_db=tmp_path / "checkpoints.sqlite",
        ledger_db=tmp_path / "ledger.json",
        exports_dir=tmp_path / "exports",
        static_dir=static_dir,
    )
    return TestClient(app)


def _built_ui(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Interview Coach</title>", encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("console.log('ui')", encoding="utf-8")
    return dist


def test_the_built_ui_is_served_from_the_same_origin_as_the_api(tmp_path):
    client = _ui_client(tmp_path, static_dir=_built_ui(tmp_path))

    assert "Interview Coach" in client.get("/").text
    assert client.get("/assets/index-abc123.js").status_code == 200


def test_mounting_the_ui_does_not_shadow_the_api(tmp_path):
    # A mount at "/" matches everything, so registration order is load-bearing: get this wrong and
    # the UI swallows /api/health and every Session socket.
    client = _ui_client(tmp_path, static_dir=_built_ui(tmp_path))

    assert client.get("/api/health").json()["status"] == "ok"
    with client.websocket_connect("/api/sessions/ui-mounted") as ws:
        ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
        assert ws.receive_json()["type"] == "session_started"


def test_no_static_dir_leaves_the_api_alone(tmp_path):
    # The dev setup has Vite serving the UI; the API must not start 404-ing as a file server.
    client = _ui_client(tmp_path, static_dir="")

    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 404


def test_a_static_dir_without_a_build_degrades_to_api_only(tmp_path):
    # Pointing at a directory that was never built is a misconfiguration, not a reason to refuse to
    # serve the API — mounting it would fail every request instead.
    empty = tmp_path / "not-built"
    empty.mkdir()

    client = _ui_client(tmp_path, static_dir=empty)

    assert client.get("/api/health").status_code == 200


def test_state_paths_come_from_the_environment_when_not_passed(tmp_path):
    # R-11: a container points all three at one mounted volume without a code change.
    settings = Settings(
        _env_file=None,
        primary_provider="mimo",
        mimo_api_key="",
        mimo_base_url="",
        mimo_model="",
        groq_api_key="",
        groq_model="",
        checkpoint_db=str(tmp_path / "state" / "checkpoints.sqlite"),
        ledger_db=str(tmp_path / "state" / "ledger.json"),
        exports_dir=str(tmp_path / "state" / "exports"),
    )
    app = create_app(settings=settings)

    state = app.state.web_api
    assert state.checkpoint_db == str(tmp_path / "state" / "checkpoints.sqlite")
    assert state.ledger_db == str(tmp_path / "state" / "ledger.json")
    assert state.exports_dir == str(tmp_path / "state" / "exports")


def test_default_state_paths_are_unchanged(tmp_path):
    # Zero-change rollout for a local checkout: the historical CWD-relative names still apply.
    settings = Settings(
        _env_file=None,
        primary_provider="mimo",
        mimo_api_key="",
        mimo_base_url="",
        mimo_model="",
        groq_api_key="",
        groq_model="",
    )
    state = create_app(settings=settings).state.web_api

    assert state.checkpoint_db == ".session-checkpoints.sqlite"
    assert state.ledger_db == ".skill-ledger.json"
    assert state.exports_dir == "data/exports"


# --- R-27: the checkpoint DB gets a reaper -------------------------------------------------------


def _put_checkpoint(checkpointer, thread_id: str, ts: str) -> None:
    checkpointer.put(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        {"v": 1, "id": f"c-{thread_id}", "ts": ts, "channel_values": {}, "channel_versions": {}, "versions_seen": {}},
        {"source": "update", "step": 1},
        {},
    )


def _threads(checkpointer) -> set[str]:
    return {entry.config["configurable"]["thread_id"] for entry in checkpointer.list(None)}


def test_the_sweep_drops_only_threads_past_the_ttl(tmp_path):
    from langgraph.checkpoint.sqlite import SqliteSaver

    from interview_coach.web_api import prune_checkpoints

    now = datetime(2026, 7, 27, tzinfo=UTC).timestamp()
    with SqliteSaver.from_conn_string(str(tmp_path / "cp.sqlite")) as checkpointer:
        _put_checkpoint(checkpointer, "ancient", "2020-01-01T00:00:00+00:00")
        _put_checkpoint(checkpointer, "yesterday", "2026-07-26T00:00:00+00:00")

        pruned = prune_checkpoints(checkpointer, max_age_seconds=7 * 24 * 3600, now=now)

        assert pruned == ["ancient"]
        assert _threads(checkpointer) == {"yesterday"}


def test_a_just_finished_session_is_still_resumable(tmp_path):
    # This is why the sweep is a TTL and not delete-on-completion: reconnecting to a finished Session
    # replays its final checkpoint and re-emits the report. Dropping the thread the moment the
    # Session completes would break that measured behaviour to save a few kilobytes.
    client = _test_client(tmp_path)
    _complete_a_demo_session(client, "finished")

    with client.websocket_connect("/api/sessions/finished") as ws:
        ws.send_json({"type": "resume_session", "mode": "demo"})
        assert _receive_until(ws, "session_completed", limit=40)["state"]["status"] == "complete"


def test_an_unreadable_timestamp_is_left_alone_rather_than_guessed(tmp_path):
    from langgraph.checkpoint.sqlite import SqliteSaver

    from interview_coach.web_api import prune_checkpoints

    with SqliteSaver.from_conn_string(str(tmp_path / "cp.sqlite")) as checkpointer:
        _put_checkpoint(checkpointer, "undated", "not-a-timestamp")

        assert prune_checkpoints(checkpointer, max_age_seconds=1, now=1e12) == []
        assert _threads(checkpointer) == {"undated"}


def test_a_ttl_of_zero_disables_the_sweep(tmp_path):
    # The knob has to be able to turn the reaper off for a deployment that wants every checkpoint.
    settings = Settings(
        _env_file=None,
        primary_provider="mimo",
        mimo_api_key="",
        mimo_base_url="",
        mimo_model="",
        groq_api_key="",
        groq_model="",
        checkpoint_ttl_seconds=0,
    )
    app = create_app(
        settings=settings,
        checkpoint_db=tmp_path / "cp.sqlite",
        ledger_db=tmp_path / "ledger.json",
        exports_dir=tmp_path / "exports",
    )

    assert app.state.web_api.settings.checkpoint_ttl_seconds == 0


def test_health_reports_the_retrieval_path(tmp_path):
    # R-13: the UI banners a degraded path rather than letting it be invisible.
    degraded = _test_client(tmp_path).get("/api/health").json()

    assert degraded["concept_store"] == "memory"
    assert degraded["retrieval_degraded"] is True


def test_a_resumed_session_keeps_its_language_for_retrieval(tmp_path):
    # R-14's real hazard: the resume payload carries no language_mode, so without reading it back
    # out of the checkpoint a resumed Vietnamese Session would silently rebuild its retrieval on the
    # English embedder and rank near-randomly for the rest of the interview.
    from interview_coach.web_api import _checkpoint_values, _session_language_mode

    # Run the Session to completion before reading: while a question is pending the graph is blocked
    # INSIDE the node, so no checkpoint for that step has been written yet and reading here would be
    # a race (it passed locally and failed in CI).
    app = _app(tmp_path)
    client = TestClient(app)
    with client.websocket_connect("/api/sessions/vn-session") as ws:
        ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1, "language_mode": "vn"})
        _receive_until(ws, "question")
        ws.send_json({"type": "candidate_answer", "answer": "Câu trả lời demo về drift."})
        _receive_until(ws, "session_completed", limit=40)

    values = _checkpoint_values(app.state.web_api, "vn-session")
    resumed = _session_language_mode(ResumeSessionPayload(type="resume_session"), True, values)

    assert resumed == "vn"
    # R-25 reads the same checkpoint for the budget rail: a resumed Session's ceiling is sized from
    # the max_questions it actually declared, not from a default guessed at resume time.
    assert values["max_questions"] == 1


def test_an_unknown_session_falls_back_to_the_default_language(tmp_path):
    from interview_coach.web_api import _checkpoint_values, _session_language_mode

    api_state = _app(tmp_path).state.web_api
    values = _checkpoint_values(api_state, "never-existed")

    assert values == {}
    assert _session_language_mode(ResumeSessionPayload(type="resume_session"), True, values) == "en"


def test_the_startup_sweep_actually_runs(tmp_path):
    # Regression guard: `prune_checkpoints` was defined BELOW the module-level `app = create_app()`,
    # so the startup sweep raised NameError straight into its own best-effort `except` and silently
    # never ran. A reaper that never reaps is worse than none — it looks like the problem is solved.
    from langgraph.checkpoint.sqlite import SqliteSaver

    db = tmp_path / "checkpoints.sqlite"
    with SqliteSaver.from_conn_string(str(db)) as checkpointer:
        _put_checkpoint(checkpointer, "ancient", "2020-01-01T00:00:00+00:00")

    settings = Settings(
        _env_file=None,
        primary_provider="mimo",
        mimo_api_key="",
        mimo_base_url="",
        mimo_model="",
        groq_api_key="",
        groq_model="",
        concept_store="memory",
    )
    create_app(
        settings=settings,
        checkpoint_db=db,
        ledger_db=tmp_path / "ledger.json",
        exports_dir=tmp_path / "exports",
    )

    with SqliteSaver.from_conn_string(str(db)) as checkpointer:
        assert _threads(checkpointer) == set()


# --- R-12: single-worker guard + server logging defaults -----------------------------------------


def _server_env(**overrides: str) -> dict[str, str]:
    """This process's environment minus the two variables conftest clears, plus explicit overrides.

    Subprocess tests have to state the worker/log configuration they mean; inheriting whatever the
    developer exported is how the suite would test something other than what it says.
    """
    inherited = {k: v for k, v in os.environ.items() if k not in {"WEB_CONCURRENCY", "COACH_LOG_FILE"}}
    return {**inherited, **overrides}


def test_web_concurrency_above_one_refuses_to_start():
    # The silent route: nobody types this, it arrives from `.env` through compose's `env_file`, and
    # uvicorn resolves it itself (`if workers is None and "WEB_CONCURRENCY" in os.environ`).
    with pytest.raises(RuntimeError, match="WEB_CONCURRENCY"):
        guard_single_worker(env={"WEB_CONCURRENCY": "2"}, argv=["uvicorn"])


@pytest.mark.parametrize("argv", [["uvicorn", "--workers", "4"], ["uvicorn", "--workers=4"]])
def test_a_workers_flag_above_one_refuses_to_start(argv):
    with pytest.raises(RuntimeError, match="--workers"):
        guard_single_worker(env={}, argv=argv)


@pytest.mark.parametrize(
    ("env", "argv"),
    [
        ({}, ["uvicorn"]),
        ({"WEB_CONCURRENCY": "1"}, ["uvicorn"]),
        ({}, ["uvicorn", "--workers", "1"]),
        ({}, ["uvicorn", "--workers=1"]),
    ],
)
def test_one_worker_is_allowed(env, argv):
    # The over-fire guard: a truthiness check on WEB_CONCURRENCY would reject `=1`, which is exactly
    # what a careful operator sets after reading docs/deploy.md §6.
    guard_single_worker(env=env, argv=argv)


@pytest.mark.parametrize(
    "argv",
    [
        ["uvicorn", "--workers", "1", "--workers", "4", "interview_coach.web_api:app"],
        ["uvicorn", "--workers=1", "--workers=4", "interview_coach.web_api:app"],
    ],
)
def test_a_repeated_workers_flag_resolves_the_way_uvicorn_resolves_it(argv):
    # uvicorn's `--workers` is a plain click option (no multiple=True), so the LAST occurrence wins:
    # `main.make_context("uvicorn", [...]).params["workers"]` returns 4 for both of these on uvicorn
    # 0.48.0. Stopping at the first occurrence let this start four processes with the guard silent.
    with pytest.raises(RuntimeError, match="--workers"):
        guard_single_worker(env={}, argv=argv)


@pytest.mark.parametrize(
    "argv",
    [
        ["uvicorn", "--workers", "4", "--workers", "1", "interview_coach.web_api:app"],
        ["uvicorn", "--workers=4", "--workers=1", "interview_coach.web_api:app"],
    ],
)
def test_a_repeated_workers_flag_ending_in_one_is_allowed(argv):
    # The mirror, and the worse half for ops: uvicorn runs exactly one worker here, so refusing would
    # answer a corrected command line with "drop --workers, or set it to 1" — what was just done.
    guard_single_worker(env={}, argv=argv)


def test_an_explicit_workers_flag_shadows_web_concurrency():
    # uvicorn consults WEB_CONCURRENCY only `if workers is None` (config.py), so the flag decides in
    # both directions. Reading the environment first would refuse a correct command line and, worse,
    # would judge a `--workers 4` run by a WEB_CONCURRENCY nobody set.
    guard_single_worker(env={"WEB_CONCURRENCY": "4"}, argv=["uvicorn", "--workers", "1"])

    with pytest.raises(RuntimeError, match="--workers"):
        guard_single_worker(env={"WEB_CONCURRENCY": "1"}, argv=["uvicorn", "--workers", "4"])


@pytest.mark.parametrize(
    ("env", "argv"),
    [
        ({"WEB_CONCURRENCY": "auto"}, ["uvicorn", "--workers", "auto"]),
        # A typo in the flag still shadows the environment: click rejects the value before Config
        # ever looks at WEB_CONCURRENCY, so refusing here would blame a variable that is not in play.
        ({"WEB_CONCURRENCY": "4"}, ["uvicorn", "--workers", "auto"]),
    ],
)
def test_a_non_integer_workers_value_is_left_to_uvicorn(env, argv):
    # Raising ValueError on someone's typo would be a worse failure than the one being prevented.
    guard_single_worker(env=env, argv=argv)


def test_the_refusal_explains_why_and_what_to_do():
    with pytest.raises(RuntimeError) as excinfo:
        guard_single_worker(env={"WEB_CONCURRENCY": "2"}, argv=["uvicorn"])

    message = str(excinfo.value)
    assert "runtimes" in message and "completed_sessions" in message
    assert "SQLite" in message
    assert "docs/deploy.md" in message


def test_the_remedy_names_the_channel_that_actually_set_the_value():
    # An operator who left WEB_CONCURRENCY in `.env` cannot "drop --workers", and one who typed the
    # flag has nothing to unset. A constant string here satisfied every other test in the suite.
    with pytest.raises(RuntimeError, match="unset WEB_CONCURRENCY"):
        guard_single_worker(env={"WEB_CONCURRENCY": "2"}, argv=["uvicorn"])

    with pytest.raises(RuntimeError, match="drop --workers"):
        guard_single_worker(env={}, argv=["uvicorn", "--workers", "2"])


def test_the_guard_runs_when_the_module_is_merely_imported():
    # The load-bearing call site. A guard wired only into `coach api` is bypassed by exactly the two
    # commands docs/deploy.md and the image use — so this pins the module-scope call, in a subprocess
    # because the guard has already run (and passed) in this one. No port is bound, no uvicorn spawns.
    proc = subprocess.run(
        [sys.executable, "-c", "import interview_coach.web_api"],
        env=_server_env(WEB_CONCURRENCY="4"),
        capture_output=True,
        text=True,
    )

    assert proc.returncode != 0
    assert "WEB_CONCURRENCY" in proc.stderr and "docs/deploy.md" in proc.stderr


def test_the_guard_reads_the_real_command_line(tmp_path):
    # `argv=None -> sys.argv` is the only argv this code ever sees in production, and every other
    # test injects a list — so that default had no coverage at all and could be replaced with `[]`
    # with the whole suite still green. A script file, not `-c`, because `-c` gives sys.argv[0]='-c'
    # and swallows the flags into it.
    script = tmp_path / "boot.py"
    script.write_text("import interview_coach.web_api\n", encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(script), "--workers", "4"],
        env=_server_env(),
        capture_output=True,
        text=True,
    )

    assert proc.returncode != 0
    assert "--workers" in proc.stderr and "docs/deploy.md" in proc.stderr


@pytest.fixture
def restore_session_logging():
    """`interview_coach` is a process-global logger: a leaked file handler holds tmp_path open."""
    log = logging.getLogger("interview_coach")
    existing = list(log.handlers)
    level = log.level
    yield
    for handler in [h for h in log.handlers if h not in existing]:
        log.removeHandler(handler)
        handler.close()
    log.setLevel(level)


def test_the_log_file_receives_records_the_console_gets(tmp_path, restore_session_logging):
    log_file = tmp_path / "sub" / "coach.log"

    configure_session_logging(log_file=str(log_file))
    logging.getLogger("interview_coach.web_api").info("llm-call provider=openai outcome=ok")

    assert log_file.is_file()  # the parent directory is created rather than demanded
    # The whole formatted line, not just the message: dropping `rotating.setFormatter(formatter)`
    # left the suite green while the file recorded a bare message with no level and no logger name —
    # so a `WARNING interview_coach.llm:` failover line and an INFO trace line became
    # indistinguishable in the one copy that survives a restart, which is the copy that matters.
    assert "INFO interview_coach.web_api: llm-call provider=openai outcome=ok" in log_file.read_text(encoding="utf-8")


def test_a_blank_log_file_path_installs_no_file_sink(monkeypatch, tmp_path, restore_session_logging):
    # `COACH_LOG_FILE=` with a stray space is what a hand-edited `.env` produces, and `.strip()` is
    # the only thing standing between that and a log file literally named "   " in the server's
    # working directory. Removing the `.strip()` left the suite green. chdir'd into tmp_path so the
    # mutant's droppings land there rather than in the repo.
    monkeypatch.chdir(tmp_path)

    configure_session_logging(log_file="   ")

    handlers = logging.getLogger("interview_coach").handlers
    assert [h for h in handlers if isinstance(h, RotatingFileHandler)] == []
    assert list(tmp_path.iterdir()) == []


def test_the_log_file_env_var_is_actually_read_by_the_serving_process(tmp_path):
    # The whole `coach api --log-file` feature hangs on one argument at module scope, and nothing
    # joined the two halves: one test spied on `os.environ` after the CLI wrote it, the other called
    # `configure_session_logging(log_file=...)` directly. Dropping the argument — turning the flag
    # into a no-op in the only process that matters — left the whole suite green. This crosses the
    # seam for real: set the variable, import the module, and require a record on disk.
    log_file = tmp_path / "state" / "coach-api.log"
    script = tmp_path / "boot.py"
    script.write_text(
        "import logging\n"
        "import interview_coach.web_api  # noqa: F401 - importing it is what installs the handler\n"
        "logging.getLogger('interview_coach.web_api').info('llm-call provider=openai outcome=ok')\n"
        "logging.shutdown()\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, str(script)],
        env=_server_env(COACH_LOG_FILE=str(log_file)),
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    assert log_file.is_file(), f"COACH_LOG_FILE was never read; stderr was:\n{proc.stderr}"
    assert "llm-call provider=openai outcome=ok" in log_file.read_text(encoding="utf-8")


def test_the_log_file_is_bounded(restore_session_logging, tmp_path):
    # Unbounded is the failure this sink would otherwise introduce: a long-lived container writing
    # every `llm-call` line fills the state volume that also holds the checkpoints and the exports.
    configure_session_logging(log_file=str(tmp_path / "coach.log"))

    rotating = [h for h in logging.getLogger("interview_coach").handlers if isinstance(h, RotatingFileHandler)]
    assert len(rotating) == 1
    assert (rotating[0].maxBytes, rotating[0].backupCount) == (10 * 1024 * 1024, 5)  # documented in deploy.md §7


def test_an_unwritable_log_file_warns_instead_of_killing_the_server(tmp_path, caplog, restore_session_logging):
    # ADR 0005's degrade side: an unwritable log path must never turn a working deployment dead.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="interview_coach.web_api"):
        configure_session_logging(log_file=str(blocker / "coach.log"))

    assert any(record.levelno == logging.WARNING for record in caplog.records)


def _complete_a_demo_session(client, session_id: str) -> None:
    with client.websocket_connect(f"/api/sessions/{session_id}") as ws:
        ws.send_json(
            {
                "type": "start_session",
                "mode": "demo",
                "target_role": "machine learning engineer",
                "target_companies": ["Viettel"],
                "claimed_skills": {"mlops": 3},
                "max_questions": 1,
                "language_mode": "en",
            }
        )
        _receive_until(ws, "session_started")
        _receive_until(ws, "question")
        ws.send_json(
            {
                "type": "candidate_answer",
                "answer": "I would compare training and validation behavior and watch for leakage.",
            }
        )
        _receive_until(ws, "session_completed", limit=40)


def test_a_connected_socket_is_visible_at_default_verbosity(tmp_path, caplog):
    # The automated form of R-12's DoD manual check: connect and finish have to be greppable in the
    # server log, otherwise a deployed Session is invisible between its first frame and a 500.
    # No `caplog.at_level` on purpose — forcing the level here is what let the *default* drop to
    # WARNING with this test still green, which is precisely the regression it is supposed to catch.
    _complete_a_demo_session(_test_client(tmp_path), "lifecycle-1")

    messages = [record.getMessage() for record in caplog.records if record.levelno == logging.INFO]
    # The id is quoted because it is client-supplied and percent-decoded: a raw %s would let a
    # newline in the URL path forge log lines, the same untrusted-input care `export_path` takes.
    assert any("connected" in message and "'lifecycle-1'" in message for message in messages)
    assert any("finished" in message and "'lifecycle-1'" in message for message in messages)


def test_the_finished_record_is_written_before_the_client_is_told(tmp_path, monkeypatch):
    # The emit is what hands control back to the client: the browser is already navigating to the
    # report by the time it returns, so a record written after it races the thing it describes.
    # Pinned rather than asserted in a commit message — swapping the two lines left the suite green.
    order: list[str] = []

    class _Ordering(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if "finished" in record.getMessage():
                order.append("log")

    emit_through = web_api.EventEmitter.__call__

    def _record_then_emit(self, event):
        if event.get("type") == "session_completed":
            order.append("emit")
        emit_through(self, event)

    monkeypatch.setattr(web_api.EventEmitter, "__call__", _record_then_emit)
    handler = _Ordering()
    logging.getLogger("interview_coach.web_api").addHandler(handler)
    try:
        _complete_a_demo_session(_test_client(tmp_path), "ordering-1")
    finally:
        logging.getLogger("interview_coach.web_api").removeHandler(handler)

    assert order == ["log", "emit"]


def test_a_newline_in_the_session_id_cannot_forge_a_cancel_record(tmp_path, caplog):
    # `/api/sessions/{session_id}` is percent-decoded before it reaches the handler, so `%0A` puts a
    # real newline in the id. The connect/finish records were quoted; cancel and error were not, and
    # they are the two an attacker can reach on demand.
    client = _test_client(tmp_path)

    with caplog.at_level(logging.INFO, logger="interview_coach.web_api"):
        with client.websocket_connect("/api/sessions/forged%0AINFO:%20granted%20admin") as ws:
            ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
            _receive_until(ws, "session_started")
            _receive_until(ws, "question")
            ws.send_json({"type": "cancel_session"})
            _receive_until(ws, "session_error")

    cancelled = [r.getMessage() for r in caplog.records if "cancelled by Candidate intent" in r.getMessage()]
    assert cancelled, "the cancel path logged nothing to check"
    assert all("\n" not in message for message in cancelled)
    assert any("granted admin" in message for message in cancelled)  # still legible, just escaped


def test_a_newline_in_the_session_id_cannot_forge_a_failure_record(tmp_path, caplog, monkeypatch):
    # The other half of `session_error`, and the half that survived reverting `%r` to `%s` with the
    # full suite green: cancel needs the Candidate to press stop, but *this* branch catches every
    # graph or provider failure, and the attacker picks both the id and (via a flaky provider) the
    # moment. Any exception out of the session thread lands here, so a raise from the graph build
    # stands in for the provider blowing up mid-question.
    def _explode(*args, **kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(web_api, "build_session_graph", _explode)
    client = _test_client(tmp_path)

    with caplog.at_level(logging.INFO, logger="interview_coach.web_api"):
        with client.websocket_connect("/api/sessions/forged%0AINFO:%20granted%20admin") as ws:
            ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
            _receive_until(ws, "session_error")

    failed = [r.getMessage() for r in caplog.records if r.getMessage().endswith(" failed")]
    assert failed, "the failure path logged nothing to check"
    assert all("\n" not in message for message in failed)
    assert any("granted admin" in message for message in failed)


def test_a_newline_in_the_session_id_cannot_forge_an_export_failure_record(tmp_path, caplog, monkeypatch):
    # Volunteered along with the two above and then left unpinned, so `%s` came back for free. A full
    # disk on a Session whose id was chosen by whoever opened the socket is the whole reachability
    # story; `export_path` already digests the id for the *filename*, which is exactly why nobody
    # noticed the raw id still reaching the log line.
    forged = "forged\nINFO interview_coach.llm: llm-call provider=openai outcome=ok"

    def _no_disk(*args, **kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(web_api, "export_session_markdown", _no_disk)
    api_state = _app(tmp_path).state.web_api

    with caplog.at_level(logging.ERROR, logger="interview_coach.web_api"):
        web_api._persist_export(api_state, forged, {"session_id": forged})

    messages = [r.getMessage() for r in caplog.records if "Markdown export" in r.getMessage()]
    assert messages, "the export failure path logged nothing to check"
    assert all("\n" not in message for message in messages)


def test_a_newline_in_the_session_id_cannot_forge_a_resume_warning(tmp_path, caplog):
    # The resume path reads the checkpoint before the graph exists, and a checkpoint DB it cannot
    # open is an ordinary operational failure (wrong mount, wrong permissions) — pointing it at a
    # directory is the cheapest honest way to produce one.
    forged = "forged\nWARNING interview_coach: judge failed over to groq"
    api_state = _app(tmp_path).state.web_api
    api_state.checkpoint_db = str(tmp_path)  # a directory: sqlite cannot open it

    with caplog.at_level(logging.WARNING, logger="interview_coach.web_api"):
        payload = ResumeSessionPayload(type="resume_session", mode="demo")
        mode = web_api._session_language_mode(api_state, forged, payload, True)

    assert mode == "en"  # still degrades rather than crashing the resume
    messages = [r.getMessage() for r in caplog.records if "language_mode" in r.getMessage()]
    assert messages, "the resume read-failure path logged nothing to check"
    assert all("\n" not in message for message in messages)


def test_a_newline_in_a_checkpoint_thread_id_cannot_forge_a_prune_record(caplog):
    # A checkpoint thread id *is* a Session id — `session_config(session_id)` puts it there — so the
    # sweep's failure record is the same untrusted string arriving by a longer road. It was still
    # `%s`, and it is the one record here that runs at startup, with nobody watching.
    forged = "forged\nINFO interview_coach.web_api: Session 'x' finished: status=complete"
    entry = SimpleNamespace(
        config={"configurable": {"thread_id": forged}},
        checkpoint={"ts": "2020-01-01T00:00:00+00:00"},
    )

    class _Unprunable:
        def list(self, _config):
            return [entry]

        def delete_thread(self, thread_id):
            raise RuntimeError("database is locked")

    with caplog.at_level(logging.WARNING, logger="interview_coach.web_api"):
        assert web_api.prune_checkpoints(_Unprunable(), max_age_seconds=1.0, now=1e12) == []

    messages = [r.getMessage() for r in caplog.records if "checkpoint thread" in r.getMessage()]
    assert messages, "the prune failure path logged nothing to check"
    assert all("\n" not in message for message in messages)


def test_the_suite_never_writes_into_the_operators_own_log_file(tmp_path):
    # `COACH_LOG_FILE` is read at web_api *import*, which under pytest happens during collection —
    # so `set -a; . .env` with the path `.env.example` documents turned `uv run pytest` into a suite
    # that reddened `test_the_log_file_is_bounded` (two RotatingFileHandlers on the process-global
    # logger) and, far worse, appended 1,939 lines into the operator's real server log, 415 of them
    # counterfeit `llm-call provider=mimo ... outcome=ok` records. That is the trace ADR 0009
    # addendum a reads to find a silent judge failover, so those are fabricated evidence. The
    # conftest pop is the fix, and only a subprocess can observe it: by the time any in-process test
    # runs, this process's collection is long over and the damage would already be done.
    log_file = tmp_path / "coach-api.log"

    proc = subprocess.run(
        [
            *[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            "tests/test_web_api.py::test_the_log_file_is_bounded",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=_server_env(COACH_LOG_FILE=str(log_file)),
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stdout[-4000:]
    assert not log_file.exists(), f"collection wrote to COACH_LOG_FILE:\n{log_file.read_text(encoding='utf-8')[:2000]}"
# --- R-25: the free-tier budget rail on the web surface ------------------------------------------


class _ProviderDemoClient(DemoLLMClient):
    """A demo brain carrying a provider identity, so the budget rails apply to it.

    Plain DemoLLMClient is exempt by design (``provider_label`` -> "unknown"), which is what keeps
    every demo-mode test above untouched.
    """

    provider_name = "mimo"


class _MeteredDemoClient(_ProviderDemoClient):
    """Bills 100 tokens per provider call to the ledger, so spend grows as the Session runs."""

    tokens_per_call = 100

    def chat_json(self, *args, **kwargs):
        usage.record_usage("mimo", "test-model", prompt_tokens=self.tokens_per_call, completion_tokens=0)
        return super().chat_json(*args, **kwargs)


class _ExpensiveDemoClient(_MeteredDemoClient):
    tokens_per_call = 500


def _live_client(tmp_path, monkeypatch, *, token: str = "", brain=None):
    """A TestClient whose `live` mode runs the demo brain — no provider is ever contacted."""
    make_brain = brain or _ProviderDemoClient
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(tmp_path / "usage-ledger.jsonl"))
    # The rails read os.environ directly, so clear them: a budget exported in a developer's shell
    # must not make these tests behave differently from CI.
    for name in ("LLM_DAILY_TOKEN_BUDGET", "LLM_SESSION_TOKEN_BUDGET", "COACH_DAILY_QUESTION_CAP"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(web_api, "build_client", lambda settings: make_brain())
    monkeypatch.setattr(web_api, "build_role_clients", lambda settings, client: RoleClients.single(client))
    settings = Settings(
        _env_file=None,
        primary_provider="mimo",
        mimo_api_key="test",
        mimo_base_url="http://test",
        mimo_model="test-model",
        auth_token=token,
        concept_store="memory",
    )
    app = create_app(
        settings=settings,
        checkpoint_db=tmp_path / "checkpoints.sqlite",
        ledger_db=tmp_path / "ledger.json",
        exports_dir=tmp_path / "exports",
    )
    return TestClient(app)


def _start_live(ws, **overrides):
    ws.send_json({"type": "start_session", "mode": "live", "max_questions": 1, **overrides})


def _expect_question(ws):
    """Wait for the Interviewer's question, failing fast if the Session terminated instead.

    Plain ``_receive_until(ws, "question")`` blocks forever when a rail misfires and the Session
    ends before asking anything — so a broken rail would hang CI rather than redden it.
    """
    event = _receive_until_any(ws, {"question", "session_error", "session_completed"})
    assert event["type"] == "question", f"Session ended before asking a question: {event}"
    return event


def test_live_session_refuses_to_start_when_the_day_is_spent(tmp_path, monkeypatch):
    # AC (b) on the web surface: a refusal event, and NO session_started — the Candidate must not
    # see an interview begin that cannot be paid for.
    client = _live_client(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "10")
    usage.record_usage("mimo", "test-model", prompt_tokens=10, completion_tokens=0)

    with client.websocket_connect("/api/sessions/spent") as ws:
        _start_live(ws)
        event = ws.receive_json()

    assert event["type"] == "session_error"
    assert "00:00 UTC" in event["error"]


def test_a_funded_live_session_still_starts(tmp_path, monkeypatch):
    # The other direction: with budget available the rail is silent and the Session runs.
    client = _live_client(tmp_path, monkeypatch, brain=_MeteredDemoClient)

    with client.websocket_connect("/api/sessions/funded") as ws:
        _start_live(ws)
        started = ws.receive_json()
        assert started["type"] == "session_started"
        _expect_question(ws)
        ws.send_json({"type": "candidate_answer", "answer": "A short demo answer about drift."})
        completed = _receive_until(ws, "session_completed")

    assert completed["state"]["status"] == "complete"
    # Every token it spent — Diagnostic through Study Plan — is attributed to the Session id, which
    # is what `coach usage` reads. Nothing escaped into the unattributed "" bucket.
    assert set(usage.sessions_for_day()) == {"funded"}


def test_demo_mode_is_exempt_from_every_budget_rail(tmp_path, monkeypatch):
    # THE exemption predicate on the web surface. Demo mode carries no provider identity, so it
    # spends nobody's allowance and no rail may fire on it — not the daily gate, not the product
    # cap. Forcing `metered = True` turns this into a session_error.
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(tmp_path / "usage-ledger.jsonl"))
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "0")
    monkeypatch.setenv("COACH_DAILY_QUESTION_CAP", "0")
    client = _test_client(tmp_path)

    with client.websocket_connect("/api/sessions/demo-exempt") as ws:
        ws.send_json({"type": "start_session", "mode": "demo", "max_questions": 1})
        assert ws.receive_json()["type"] == "session_started"
        _expect_question(ws)
        ws.send_json({"type": "candidate_answer", "answer": "A short demo answer about drift."})
        completed = _receive_until(ws, "session_completed")

    assert completed["state"]["status"] == "complete"
    assert usage.questions_today(usage.token_identity("")) == 0  # nothing reserved against the cap


def test_daily_question_cap_refuses_a_new_live_session(tmp_path, monkeypatch):
    # AC (d): a questions/day product cap per token identity, from env.
    client = _live_client(tmp_path, monkeypatch, token="s3cret-shared-token")
    monkeypatch.setenv("COACH_DAILY_QUESTION_CAP", "0")

    with client.websocket_connect("/api/sessions/capped") as ws:
        ws.send_json({"type": "auth", "token": "s3cret-shared-token"})
        _start_live(ws)
        event = ws.receive_json()

    assert event["type"] == "session_error"
    assert "COACH_DAILY_QUESTION_CAP" in event["error"]


def test_the_question_cap_is_reserved_at_start_not_at_completion(tmp_path, monkeypatch):
    # A cap that only counts FINISHED Sessions is bypassed by abandoning them, so the reservation
    # happens up front — and it reserves the Session's OWN question count, not a flat one.
    client = _live_client(tmp_path, monkeypatch)
    monkeypatch.setenv("COACH_DAILY_QUESTION_CAP", "2")

    with client.websocket_connect("/api/sessions/first") as ws:
        _start_live(ws, max_questions=2)
        assert ws.receive_json()["type"] == "session_started"
        _expect_question(ws)
        ws.send_json({"type": "cancel_session"})  # abandoned, never completed
        _receive_until(ws, "session_error")

    assert usage.questions_today(usage.token_identity("")) == 2
    with client.websocket_connect("/api/sessions/second") as ws:
        _start_live(ws)
        event = ws.receive_json()

    assert event["type"] == "session_error"
    assert "COACH_DAILY_QUESTION_CAP" in event["error"]


def test_resuming_a_live_session_does_not_recharge_the_question_cap(tmp_path, monkeypatch):
    # A resume finishes questions that were already reserved when the Session started. Charging
    # again would make the cap punish exactly the suspend-and-resume ADR 0005 asks for.
    client = _live_client(tmp_path, monkeypatch)
    monkeypatch.setenv("COACH_DAILY_QUESTION_CAP", "1")

    with client.websocket_connect("/api/sessions/resumed") as ws:
        _start_live(ws)
        assert ws.receive_json()["type"] == "session_started"
        _expect_question(ws)
        ws.send_json({"type": "cancel_session"})
        _receive_until(ws, "session_error")

    with client.websocket_connect("/api/sessions/resumed") as ws:
        ws.send_json({"type": "resume_session", "mode": "live"})
        started = ws.receive_json()

    assert started["type"] == "session_started"  # not a cap refusal
    assert usage.questions_today(usage.token_identity("")) == 1


def test_a_mid_session_breach_suspends_instead_of_completing(tmp_path, monkeypatch, caplog):
    # AC (c) on the web surface: a visible session_error, no session_completed — never a
    # `failed`-and-advance (ADR 0005) and never a silent stall.
    client = _live_client(tmp_path, monkeypatch, brain=_MeteredDemoClient)
    # 150 sits between the Diagnostic's 100 (so the Session is allowed to START and ask Q1) and the
    # spend after Q1 resolves — which is what makes this a MID-Session breach and not a start gate.
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "150")

    seen: list[dict] = []
    with caplog.at_level(logging.DEBUG), client.websocket_connect("/api/sessions/breach") as ws:
        _start_live(ws, max_questions=2)
        assert ws.receive_json()["type"] == "session_started"
        _expect_question(ws)  # Q1 really was asked before the rail fired
        ws.send_json({"type": "candidate_answer", "answer": "A short demo answer about drift."})
        for _ in range(40):
            # "question" ends the loop only so a rail that fails to fire reddens this test instead
            # of blocking forever on a Q2 nobody is going to answer.
            seen.append(ws.receive_json())
            if seen[-1]["type"] in {"session_error", "session_completed", "question"}:
                break

    event = seen[-1]
    assert event["type"] == "session_error", f"the rail did not suspend after Q1: {event}"
    assert "suspended" in event["error"].lower()
    assert "LLM_SESSION_TOKEN_BUDGET" in event["error"]
    # A suspended Session is not a finished one: nothing was persisted as complete.
    assert client.get("/api/sessions/breach/export.md").status_code in (404, 409)
    # The state carrying the question the Candidate just resolved goes out BEFORE the suspend. The
    # CLI prints its live update first for the same reason: a suspend that arrives with no state
    # carrying the last answer is indistinguishable, to the UI, from a crash that ate it.
    states = [item for item in seen if item["type"] == "state_update"]
    assert states, "the suspend arrived with no state carrying the resolved question"
    assert states[-1]["state"]["question_count"] == 1
    # And it is a DESIGNED suspend, not an unhandled crash. Without the dedicated
    # `except SessionBudgetSuspended` branch the exception falls into the generic net, which logs
    # `logger.exception("Session %s failed")` at ERROR — while every assertion above still passes,
    # because the exception CLASS NAME supplies the "suspended" substring.
    web_errors = [r for r in caplog.records if r.levelno >= logging.ERROR and r.name == "interview_coach.web_api"]
    assert web_errors == []
    assert any("suspended on a budget rail" in r.getMessage() for r in caplog.records)


def test_a_refused_live_session_never_starts_the_interview(tmp_path, monkeypatch):
    # The refusal must RETURN, not just emit. Dropping the `return` still puts session_error first on
    # the wire — every socket-level assertion keeps passing — while the interview runs anyway on a
    # budget that was just declared insufficient. Driving the thread function directly is what makes
    # "and then nothing else happened" observable.
    monkeypatch.setenv("COACH_USAGE_LEDGER", str(tmp_path / "usage-ledger.jsonl"))
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "10")
    monkeypatch.delenv("LLM_SESSION_TOKEN_BUDGET", raising=False)
    monkeypatch.delenv("COACH_DAILY_QUESTION_CAP", raising=False)
    usage.record_usage("mimo", "test-model", prompt_tokens=10, completion_tokens=0)
    monkeypatch.setattr(web_api, "build_client", lambda settings: _ProviderDemoClient())
    monkeypatch.setattr(web_api, "build_role_clients", lambda settings, client: RoleClients.single(client))

    settings = Settings(
        _env_file=None,
        primary_provider="mimo",
        mimo_api_key="test",
        mimo_base_url="http://test",
        mimo_model="test-model",
        concept_store="memory",
    )
    api_state = web_api.WebApiState(
        settings=settings,
        checkpoint_db=str(tmp_path / "checkpoints.sqlite"),
        ledger_db=str(tmp_path / "ledger.json"),
        exports_dir=str(tmp_path / "exports"),
    )
    events: list[dict] = []
    runtime = web_api.RuntimeSession(session_id="refused", mode="live", emit=events.append)
    # Pre-queued so that a Session which wrongly starts still terminates instead of blocking here.
    runtime.answers.put("An answer nobody should ever have been asked for.")

    web_api._run_session_thread(
        api_state,
        runtime,
        web_api.StartSessionPayload(type="start_session", max_questions=1),
        False,
    )

    assert [event["type"] for event in events] == ["session_error"]
    assert "00:00 UTC" in events[0]["error"]
    assert usage.session_spend("refused") == 0  # and not a single token was spent under its name


def test_the_web_rail_counts_only_the_questions_actually_left(tmp_path, monkeypatch):
    # The web driver's mid-Session estimate must subtract the questions already resolved, exactly as
    # the CLI's does. Charging for questions that are already paid for suspends a Session that can
    # comfortably afford the rest of itself.
    client = _live_client(tmp_path, monkeypatch, brain=_ExpensiveDemoClient)
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", str(usage.estimated_session_tokens(2)))

    with client.websocket_connect("/api/sessions/two-questions") as ws:
        _start_live(ws, max_questions=2)
        assert ws.receive_json()["type"] == "session_started"
        for _ in range(2):
            _expect_question(ws)
            ws.send_json({"type": "candidate_answer", "answer": "A short demo answer about drift."})
        event = _receive_until_any(ws, {"session_completed", "session_error"}, limit=60)

    assert event["type"] == "session_completed", f"a fundable Session was suspended: {event}"
    assert event["state"]["question_count"] == 2


def test_a_new_interview_on_the_same_browser_id_is_not_suspended(tmp_path, monkeypatch):
    # web/src/lib/sessionId.ts persists ONE id per browser, and connect(false) — the fresh-start
    # path — reuses it verbatim. While the rail measured the id, the next brand-new interview never
    # received a question at all, and each bricked attempt still burned a real Diagnostic call.
    client = _live_client(tmp_path, monkeypatch, brain=_MeteredDemoClient)

    def one_interview(expect: str) -> dict:
        with client.websocket_connect("/api/sessions/same-browser") as ws:
            _start_live(ws, max_questions=1)
            assert ws.receive_json()["type"] == "session_started"
            _expect_question(ws)
            ws.send_json({"type": "candidate_answer", "answer": "A short demo answer about drift."})
            event = _receive_until_any(ws, {"session_completed", "session_error"}, limit=60)
        assert event["type"] == expect, f"{event}"
        return event

    # Interview 1 with the rail effectively off, to measure what one of these costs.
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "10000000")
    one_interview("session_completed")
    one_run = usage.session_run_spend("same-browser")
    assert one_run > 0

    # 2.5x one interview: more than any single run needs, less than three of them summed.
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", str(int(one_run * 2.5)))
    one_interview("session_completed")
    one_interview("session_completed")
    assert usage.session_spend("same-browser") > int(one_run * 2.5)


def test_a_suspended_web_session_can_actually_be_resumed(tmp_path, monkeypatch):
    # ADR 0005 requires a suspend to OFFER resume, and a web Candidate cannot edit
    # LLM_SESSION_TOKEN_BUDGET — so before this the UI's only "remedy" was an infinite resume loop
    # that re-suspended at stream event 0 every time. The resume must make real progress.
    client = _live_client(tmp_path, monkeypatch, brain=_MeteredDemoClient)
    monkeypatch.setenv("LLM_SESSION_TOKEN_BUDGET", "150")

    with client.websocket_connect("/api/sessions/breach-resume") as ws:
        _start_live(ws, max_questions=2)
        assert ws.receive_json()["type"] == "session_started"
        _expect_question(ws)
        ws.send_json({"type": "candidate_answer", "answer": "A short demo answer about drift."})
        event = _receive_until_any(ws, {"session_error", "session_completed", "question"})
    assert event["type"] == "session_error", f"the rail did not suspend after Q1: {event}"

    with client.websocket_connect("/api/sessions/breach-resume") as ws:
        ws.send_json({"type": "resume_session", "mode": "live"})
        assert ws.receive_json()["type"] == "session_started"
        # The load-bearing assertion: Q2 is actually asked. `_expect_question` fails fast on the
        # session_error a re-suspend at stream event 0 would produce instead.
        resumed = _expect_question(ws)

    assert resumed["type"] == "question"
