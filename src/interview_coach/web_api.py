"""FastAPI/WebSocket surface for the local React MVP."""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel, Field, ValidationError

from .concepts import build_concept_store
from .config import Settings, load_settings
from .demo_llm import DemoLLMClient
from .diagnostic import CandidateProfile, diagnose
from .exporter import render_session_markdown
from .llm import LLMClient, build_client
from .microloop import CandidateInputUnavailable
from .resources import build_resource_store
from .supervisor import (
    DEFAULT_MAX_ELAPSED_SECONDS,
    DEFAULT_MAX_QUESTIONS,
    SessionStatus,
    build_session_graph,
    initial_session_state,
    session_config,
)

logger = logging.getLogger(__name__)

SessionMode = Literal["auto", "demo", "live"]


class StartSessionPayload(BaseModel):
    type: Literal["start_session"]
    mode: SessionMode = "auto"
    target_role: str = "machine learning engineer"
    target_companies: list[str] = Field(default_factory=list)
    claimed_skills: dict[str, float] = Field(default_factory=dict)
    max_questions: int = Field(DEFAULT_MAX_QUESTIONS, ge=1, le=10)
    max_elapsed_seconds: float = Field(DEFAULT_MAX_ELAPSED_SECONDS, gt=0)


class ResumeSessionPayload(BaseModel):
    type: Literal["resume_session"]
    mode: SessionMode = "auto"


class CandidateAnswerPayload(BaseModel):
    type: Literal["candidate_answer"]
    answer: str


class CancelSessionPayload(BaseModel):
    type: Literal["cancel_session"]


ClientPayload = StartSessionPayload | ResumeSessionPayload | CandidateAnswerPayload | CancelSessionPayload


class QueueCandidate:
    """Candidate bridge: graph thread emits a question, then waits for browser input."""

    def __init__(
        self,
        emit: EventEmitter,
        answers: queue.Queue[str],
        cancelled: threading.Event,
    ) -> None:
        self._emit = emit
        self._answers = answers
        self._cancelled = cancelled

    def answer(self, question: str) -> str:
        self._emit({"type": "question", "question": question})
        while not self._cancelled.is_set():
            try:
                return self._answers.get(timeout=0.1)
            except queue.Empty:
                continue
        raise CandidateInputUnavailable("Session was cancelled while waiting for a Candidate answer.")


@dataclass
class EventEmitter:
    loop: asyncio.AbstractEventLoop
    outgoing: asyncio.Queue[dict[str, Any]]

    def __call__(self, event: dict[str, Any]) -> None:
        self.loop.call_soon_threadsafe(self.outgoing.put_nowait, event)


@dataclass
class RuntimeSession:
    session_id: str
    mode: str
    emit: EventEmitter
    answers: queue.Queue[str] = field(default_factory=queue.Queue)
    cancelled: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    def start(self, target, *args: Any) -> None:
        self.thread = threading.Thread(target=target, args=args, daemon=True)
        self.thread.start()


@dataclass
class WebApiState:
    settings: Settings
    checkpoint_db: str
    completed_sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    runtimes: dict[str, RuntimeSession] = field(default_factory=dict)


def create_app(
    *,
    settings: Settings | None = None,
    checkpoint_db: str | Path = ".session-checkpoints.sqlite",
) -> FastAPI:
    api_state = WebApiState(settings=settings or load_settings(), checkpoint_db=str(checkpoint_db))
    app = FastAPI(title="Adaptive Interview Coach API")
    app.state.web_api = api_state
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "primary_provider": api_state.settings.primary_provider,
            "primary_configured": api_state.settings.configured,
            "fallback_provider": api_state.settings.fallback_provider,
            "fallback_configured": api_state.settings.fallback_config.configured,
            "demo_available": True,
        }

    @app.websocket("/api/sessions/{session_id}")
    async def session_socket(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        outgoing: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        emit = EventEmitter(asyncio.get_running_loop(), outgoing)
        runtime = RuntimeSession(session_id=session_id, mode="pending", emit=emit)
        sender = asyncio.create_task(_send_events(websocket, outgoing))
        api_state.runtimes[session_id] = runtime
        try:
            while True:
                raw = await websocket.receive_json()
                try:
                    payload = _parse_payload(raw)
                except ValueError as err:
                    emit({"type": "session_error", "error": str(err)})
                    continue
                if isinstance(payload, StartSessionPayload):
                    if _is_running(runtime):
                        emit({"type": "session_error", "error": "A Session is already running on this socket."})
                        continue
                    runtime.mode = _select_mode(payload.mode, api_state.settings)
                    runtime.start(
                        _run_session_thread,
                        api_state,
                        runtime,
                        payload,
                        False,
                    )
                elif isinstance(payload, ResumeSessionPayload):
                    if _is_running(runtime):
                        emit({"type": "session_error", "error": "A Session is already running on this socket."})
                        continue
                    runtime.mode = _select_mode(payload.mode, api_state.settings)
                    runtime.start(
                        _run_session_thread,
                        api_state,
                        runtime,
                        payload,
                        True,
                    )
                elif isinstance(payload, CandidateAnswerPayload):
                    runtime.answers.put(payload.answer)
                else:
                    runtime.cancelled.set()
                    runtime.answers.put("")
                    emit({"type": "session_error", "error": "Session cancelled by client."})
        except WebSocketDisconnect:
            runtime.cancelled.set()
            runtime.answers.put("")
        finally:
            sender.cancel()
            api_state.runtimes.pop(session_id, None)

    @app.get("/api/sessions/{session_id}/export.md", response_class=PlainTextResponse)
    def export_markdown(session_id: str) -> str:
        state = api_state.completed_sessions.get(session_id)
        if state is None:
            raise HTTPException(status_code=404, detail="No completed Session found for this Session id.")
        if state.get("status") != SessionStatus.COMPLETE.value:
            raise HTTPException(status_code=409, detail="Session is not complete yet.")
        return render_session_markdown(state)

    return app


app = create_app()


async def _send_events(websocket: WebSocket, outgoing: asyncio.Queue[dict[str, Any]]) -> None:
    while True:
        event = await outgoing.get()
        await websocket.send_json(event)


def _parse_payload(raw: dict[str, Any]) -> ClientPayload:
    payload_type = raw.get("type")
    model: type[BaseModel]
    if payload_type == "start_session":
        model = StartSessionPayload
    elif payload_type == "resume_session":
        model = ResumeSessionPayload
    elif payload_type == "candidate_answer":
        model = CandidateAnswerPayload
    elif payload_type == "cancel_session":
        model = CancelSessionPayload
    else:
        raise ValueError(f"unknown WebSocket payload type: {payload_type!r}")
    try:
        return model.model_validate(raw)
    except ValidationError as err:
        raise ValueError(str(err)) from err


def _is_running(runtime: RuntimeSession) -> bool:
    return runtime.thread is not None and runtime.thread.is_alive()


def _select_mode(mode: SessionMode, settings: Settings) -> str:
    if mode == "demo":
        return "demo"
    if mode == "live":
        return "live"
    return "live" if settings.configured else "demo"


def _client_for_mode(mode: str, settings: Settings) -> LLMClient:
    if mode == "demo":
        return DemoLLMClient()
    if not settings.configured:
        raise RuntimeError(
            f"LLM primary provider {settings.primary_provider!r} is not configured; use demo mode or configure .env."
        )
    return build_client(settings)


def _run_session_thread(
    api_state: WebApiState,
    runtime: RuntimeSession,
    payload: StartSessionPayload | ResumeSessionPayload,
    resume: bool,
) -> None:
    try:
        client = _client_for_mode(runtime.mode, api_state.settings)
        concept_store = build_concept_store("memory", seed=True)
        resource_store = build_resource_store("memory", seed=True)
        with SqliteSaver.from_conn_string(api_state.checkpoint_db) as checkpointer:
            graph = build_session_graph(
                client,
                checkpointer=checkpointer,
                concept_store=concept_store,
                resource_store=resource_store,
                candidate_factory=lambda seed: QueueCandidate(runtime.emit, runtime.answers, runtime.cancelled),
            )
            config = session_config(runtime.session_id)
            initial_state = None
            if not resume:
                assert isinstance(payload, StartSessionPayload)
                profile = CandidateProfile(
                    target_role=payload.target_role,
                    target_companies=tuple(payload.target_companies),
                    claimed_skills=payload.claimed_skills,
                )
                diagnostic = diagnose(profile, client)
                initial_state = initial_session_state(
                    runtime.session_id,
                    diagnostic,
                    max_questions=payload.max_questions,
                    max_elapsed_seconds=payload.max_elapsed_seconds,
                )
            runtime.emit(
                {
                    "type": "session_started",
                    "session_id": runtime.session_id,
                    "mode": runtime.mode,
                    "resumed": resume,
                }
            )
            final_state = _stream_graph(graph, initial_state, config, runtime)
        if final_state is not None:
            api_state.completed_sessions[runtime.session_id] = final_state
            runtime.emit({"type": "session_completed", "state": final_state})
    except Exception as err:  # noqa: BLE001 - API boundary converts graph/provider failures to events
        logger.exception("Session %s failed", runtime.session_id)
        runtime.emit({"type": "session_error", "error": f"{type(err).__name__}: {err}"})


def _stream_graph(graph, initial_state: dict[str, Any] | None, config: dict[str, Any], runtime: RuntimeSession) -> dict:
    final_state: dict[str, Any] | None = None
    for event in graph.stream(initial_state, config, stream_mode="values"):
        if runtime.cancelled.is_set():
            raise CandidateInputUnavailable("Session was cancelled.")
        final_state = dict(event)
        runtime.emit({"type": "state_update", "state": final_state})
    if final_state is None:
        raise RuntimeError("Session graph produced no final state")
    return final_state
