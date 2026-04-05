from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from src.assistant.serialization import to_jsonable
from src.assistant.types import AgentInterrupt, CanvasAgentSession


def _session_from_payload(payload: dict[str, Any]) -> CanvasAgentSession:
    pending_interrupt = payload.get("pending_interrupt")
    return CanvasAgentSession(
        session_id=str(payload.get("session_id") or "").strip(),
        user_id=str(payload.get("user_id") or "").strip(),
        document_id=str(payload.get("document_id") or "").strip(),
        conversation=list(payload.get("conversation") or []),
        user_goal=str(payload.get("user_goal") or "").strip(),
        graph_state=dict(payload.get("graph_state") or {}),
        pending_interrupt=AgentInterrupt(**pending_interrupt) if isinstance(pending_interrupt, dict) else None,
        tool_history=list(payload.get("tool_history") or []),
        resume_in_flight=bool(payload.get("resume_in_flight")),
        status=str(payload.get("status") or "idle"),
    )


class RedisCanvasAssistantSessionStore:
    def __init__(self, redis_client: Any, ttl_seconds: int = 1800) -> None:
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds

    def _session_key(self, session_id: str) -> str:
        return f"canvas_agent:session:{session_id}"

    async def get_or_create(self, session_id: str, user_id: str, document_id: str) -> CanvasAgentSession:
        existing = await self.get(session_id)
        if existing is not None:
            if existing.user_id != user_id or existing.document_id != document_id:
                raise ValueError("assistant session does not belong to the current user or document")
            return existing
        session = CanvasAgentSession(session_id=session_id, user_id=user_id, document_id=document_id)
        await self.save(session)
        return session

    async def get(self, session_id: str) -> CanvasAgentSession | None:
        payload = await self.redis.get(self._session_key(session_id))
        if not payload:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return _session_from_payload(json.loads(payload))

    async def save(self, session: CanvasAgentSession) -> None:
        await self.redis.set(
            self._session_key(session.session_id),
            json.dumps(to_jsonable(asdict(session)), ensure_ascii=False),
            ex=self.ttl_seconds,
        )

    async def require(self, session_id: str, user_id: str, document_id: str) -> CanvasAgentSession:
        session = await self.get(session_id)
        if session is None:
            raise ValueError(f"assistant session not found: {session_id}")
        if session.user_id != user_id or session.document_id != document_id:
            raise ValueError("assistant session does not belong to the current user or document")
        return session

    async def begin_resume(
        self,
        session_id: str,
        user_id: str,
        document_id: str,
        interrupt_id: str,
    ) -> CanvasAgentSession:
        session = await self.require(session_id, user_id, document_id)
        if session.pending_interrupt is None:
            raise ValueError("assistant session has no pending interrupt")
        if session.pending_interrupt.interrupt_id != interrupt_id:
            raise ValueError("assistant interrupt id mismatch")
        if session.resume_in_flight:
            raise ValueError("assistant session is already resuming")
        session.resume_in_flight = True
        await self.save(session)
        return session

    async def clear_interrupt(self, session: CanvasAgentSession) -> None:
        session.pending_interrupt = None
        session.resume_in_flight = False
        await self.save(session)


class InMemoryCanvasAssistantSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, CanvasAgentSession] = {}

    async def get_or_create(self, session_id: str, user_id: str, document_id: str) -> CanvasAgentSession:
        session = self._sessions.get(session_id)
        if session is None:
            session = CanvasAgentSession(session_id=session_id, user_id=user_id, document_id=document_id)
            self._sessions[session_id] = session
        return CanvasAgentSession(**asdict(session))

    async def save(self, session: CanvasAgentSession) -> None:
        self._sessions[session.session_id] = _session_from_payload(to_jsonable(asdict(session)))

    async def require(self, session_id: str, user_id: str, document_id: str) -> CanvasAgentSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"assistant session not found: {session_id}")
        if session.user_id != user_id or session.document_id != document_id:
            raise ValueError("assistant session does not belong to the current user or document")
        return CanvasAgentSession(**asdict(session))

    async def begin_resume(self, session_id: str, user_id: str, document_id: str, interrupt_id: str) -> CanvasAgentSession:
        session = await self.require(session_id, user_id, document_id)
        if session.pending_interrupt is None:
            raise ValueError("assistant session has no pending interrupt")
        if session.pending_interrupt.interrupt_id != interrupt_id:
            raise ValueError("assistant interrupt id mismatch")
        if session.resume_in_flight:
            raise ValueError("assistant session is already resuming")
        session.resume_in_flight = True
        await self.save(session)
        return session

    async def clear_interrupt(self, session: CanvasAgentSession) -> None:
        session.pending_interrupt = None
        session.resume_in_flight = False
        await self.save(session)
