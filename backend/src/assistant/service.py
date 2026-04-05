from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from langgraph.types import Command

from src.api.schemas.canvas_assistant import CanvasAssistantChatRequest, CanvasAssistantResumeRequest
from src.assistant.serialization import to_jsonable
from src.assistant.session_store import InMemoryCanvasAssistantSessionStore
from src.assistant.tools.canvas_tools import CanvasAssistantCanvasExecutionTools, CanvasAssistantCanvasInspectionTools
from src.assistant.tools.generation_tools import CanvasAssistantGenerationTools
from src.assistant.types import AgentInterrupt, CanvasAgentSession, CanvasAssistantTurnResult


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact_observation_for_session(observation: dict[str, Any]) -> dict[str, Any]:
    canvas = dict(observation.get("canvas") or {})
    items = list(canvas.get("items") or [])
    connections = list(canvas.get("connections") or [])
    return {
        "canvas": {
            "document": dict(canvas.get("document") or {}),
            "counts": dict(canvas.get("counts") or {"items": len(items), "connections": len(connections)}),
            "items": [
                {
                    "id": str(item.get("id") or ""),
                    "title": str(item.get("title") or ""),
                    "item_type": str(item.get("item_type") or ""),
                }
                for item in items[:6]
            ],
            "connections": [
                {
                    "source_item_id": str(connection.get("source_item_id") or ""),
                    "target_item_id": str(connection.get("target_item_id") or ""),
                }
                for connection in connections[:6]
            ],
        },
        "targets": list(observation.get("targets") or [])[:4],
        "last_tool_effect": dict(observation.get("last_tool_effect") or {}),
        "task_statuses": list(observation.get("task_statuses") or [])[:4],
    }


def _normalize_message_content(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(message, dict):
        return str(message.get("content") or "").strip()
    return str(content or "").strip()


def _normalize_message_tool_calls(message: Any) -> list[dict[str, Any]]:
    tool_calls = getattr(message, "tool_calls", None)
    if isinstance(tool_calls, list):
        return [dict(tool_call) for tool_call in tool_calls]
    if isinstance(message, dict):
        return [dict(tool_call) for tool_call in list(message.get("tool_calls") or [])]
    return []


def _normalize_tool_message(message: Any) -> tuple[str, str, Any]:
    tool_call_id = str(getattr(message, "tool_call_id", "") or (message.get("tool_call_id") if isinstance(message, dict) else "") or "").strip()
    tool_name = str(getattr(message, "name", "") or (message.get("name") if isinstance(message, dict) else "") or "").strip()
    content = getattr(message, "content", None)
    if isinstance(message, dict):
        content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
        if not text:
            return tool_call_id, tool_name, {}
        try:
            return tool_call_id, tool_name, json.loads(text)
        except Exception:
            return tool_call_id, tool_name, {"content": text}
    if content is None:
        return tool_call_id, tool_name, {}
    return tool_call_id, tool_name, to_jsonable(content)


class CanvasAssistantService:
    def __init__(
        self,
        session_store: Any | None = None,
        inspection_tools: Any | None = None,
        canvas_execution_tools: Any | None = None,
        generation_tools: Any | None = None,
        agent_factory: Any | None = None,
    ) -> None:
        if agent_factory is None:
            raise ValueError("CanvasAssistantService requires an official agent_factory")
        self.session_store = session_store or InMemoryCanvasAssistantSessionStore()
        self.inspection_tools = inspection_tools or CanvasAssistantCanvasInspectionTools()
        self.canvas_execution_tools = canvas_execution_tools or CanvasAssistantCanvasExecutionTools()
        self.generation_tools = generation_tools or CanvasAssistantGenerationTools()
        self.agent_factory = agent_factory

    async def chat(self, request: CanvasAssistantChatRequest, user_id: str) -> CanvasAssistantTurnResult:
        session_id = request.session_id or str(uuid4())
        session = await self.session_store.get_or_create(session_id, user_id, request.document_id)
        session.user_goal = request.message if not session.user_goal else session.user_goal
        session.conversation.append({"role": "user", "content": request.message})
        graph = await self.agent_factory(
            document_id=request.document_id,
            user_id=user_id,
            api_key_id=request.api_key_id or "",
            chat_model_id=request.chat_model_id or "",
            session_id=session.session_id,
        )
        consumed = await self._consume_agent_stream(
            graph=graph,
            payload={"messages": [{"role": "user", "content": request.message}]},
            context=await self._build_agent_context(
                request.document_id,
                user_id,
                request.api_key_id or "",
                request.chat_model_id or "",
            ),
            config=self._build_config(
                session_id=session.session_id,
                document_id=request.document_id,
                user_id=user_id,
                api_key_id=request.api_key_id or "",
                chat_model_id=request.chat_model_id or "",
            ),
            session_id=session.session_id,
        )
        return await self._finalize_session(session, consumed)

    async def resume(self, request: CanvasAssistantResumeRequest, user_id: str) -> CanvasAssistantTurnResult:
        session = await self.session_store.begin_resume(
            request.session_id,
            user_id,
            request.document_id,
            request.interrupt_id,
        )
        graph = await self.agent_factory(
            document_id=request.document_id,
            user_id=user_id,
            api_key_id=session.graph_state.get("api_key_id", ""),
            chat_model_id=session.graph_state.get("chat_model_id", ""),
            session_id=session.session_id,
        )
        consumed = await self._consume_agent_stream(
            graph=graph,
            payload=Command(
                resume={
                    "decision": request.decision,
                    "selected_model_id": request.selected_model_id or "",
                }
            ),
            context=await self._build_agent_context(
                request.document_id,
                user_id,
                session.graph_state.get("api_key_id", ""),
                session.graph_state.get("chat_model_id", ""),
            ),
            config=self._build_config(
                session_id=session.session_id,
                document_id=request.document_id,
                user_id=user_id,
                api_key_id=session.graph_state.get("api_key_id", ""),
                chat_model_id=session.graph_state.get("chat_model_id", ""),
            ),
            session_id=session.session_id,
            resume_decision=request.decision,
            resume_interrupt_id=request.interrupt_id,
        )
        return await self._finalize_session(session, consumed)

    async def _build_agent_context(
        self,
        document_id: str,
        user_id: str,
        api_key_id: str,
        chat_model_id: str,
    ) -> dict[str, Any]:
        snapshot = await self.inspection_tools.inspect_graph(document_id, user_id)
        return {
            "document_id": document_id,
            "user_id": user_id,
            "api_key_id": api_key_id,
            "chat_model_id": chat_model_id,
            "observation": _compact_observation_for_session({"canvas": snapshot}),
        }

    def _build_config(
        self,
        *,
        session_id: str,
        document_id: str,
        user_id: str,
        api_key_id: str,
        chat_model_id: str,
    ) -> dict[str, Any]:
        return {
            "configurable": {
                "thread_id": session_id,
                "session_id": session_id,
                "document_id": document_id,
                "user_id": user_id,
                "api_key_id": api_key_id,
                "chat_model_id": chat_model_id,
            },
            "recursion_limit": 12,
        }

    async def _consume_agent_stream(
        self,
        *,
        graph: Any,
        payload: Any,
        context: dict[str, Any] | None,
        config: dict[str, Any],
        session_id: str,
        resume_decision: str = "",
        resume_interrupt_id: str = "",
    ) -> dict[str, Any]:
        run_id = f"run-{uuid4()}"
        sequence = 0
        events: list[dict[str, Any]] = []
        final_message = ""
        pending_interrupt: AgentInterrupt | None = None
        tool_history: list[dict[str, Any]] = []

        def emit(event_type: str, payload_data: dict[str, Any], correlation_id: str = "") -> None:
            nonlocal sequence
            sequence += 1
            normalized_payload = to_jsonable(payload_data)
            data = {
                **dict(normalized_payload or {}),
                "event_id": f"{session_id}-{sequence}",
                "session_id": session_id,
                "thread_id": session_id,
                "run_id": run_id,
                "timestamp": _utc_now_iso(),
                "sequence": sequence,
                "correlation_id": str(correlation_id or dict(normalized_payload or {}).get("correlation_id") or ""),
            }
            events.append({"type": event_type, "data": data})

        emit("agent.session.started", {"session_id": session_id})
        if resume_decision:
            emit(
                "agent.interrupt.resolved",
                {"interrupt_id": resume_interrupt_id, "decision": resume_decision},
                correlation_id=resume_interrupt_id,
            )

        try:
            async for chunk in graph.astream(payload, config=config, context=context, stream_mode="updates"):
                if not isinstance(chunk, dict):
                    continue
                if "__interrupt__" in chunk:
                    for interrupt in list(chunk.get("__interrupt__") or []):
                        value = getattr(interrupt, "value", None)
                        if not isinstance(value, dict):
                            value = {"message": str(value or "")}
                        pending_interrupt = AgentInterrupt(
                            interrupt_id=str(getattr(interrupt, "id", "") or value.get("interrupt_id") or f"interrupt-{uuid4()}"),
                            kind=str(value.get("kind") or "confirm_execute"),
                            title=str(value.get("title") or "请确认执行"),
                            message=str(value.get("message") or "请确认是否继续。"),
                            actions=list(value.get("actions") or ["approve", "reject"]),
                            selected_model_id=str(value.get("selected_model_id") or ""),
                            model_options=list(value.get("model_options") or []),
                            tool_name=str(value.get("tool_name") or ""),
                            args=dict(value.get("args") or {}),
                        )
                        emit(
                            "agent.interrupt.requested",
                            {
                                "interrupt_id": pending_interrupt.interrupt_id,
                                "kind": pending_interrupt.kind,
                                "title": pending_interrupt.title,
                                "message": pending_interrupt.message,
                                "actions": pending_interrupt.actions,
                                "selected_model_id": pending_interrupt.selected_model_id,
                                "model_options": pending_interrupt.model_options,
                                "tool_name": pending_interrupt.tool_name,
                                "args": pending_interrupt.args,
                            },
                            correlation_id=pending_interrupt.interrupt_id,
                        )
                    continue

                agent_payload = chunk.get("agent")
                if isinstance(agent_payload, dict):
                    for message in list(agent_payload.get("messages") or []):
                        tool_calls = _normalize_message_tool_calls(message)
                        if tool_calls:
                            for tool_call in tool_calls:
                                emit(
                                    "agent.tool.call",
                                    {
                                        "id": str(tool_call.get("id") or ""),
                                        "tool_name": str(tool_call.get("name") or ""),
                                        "args": dict(tool_call.get("args") or {}),
                                        "status": "requested",
                                    },
                                    correlation_id=str(tool_call.get("id") or ""),
                                )
                            continue
                        content = _normalize_message_content(message)
                        if content:
                            final_message = content
                            message_id = str(getattr(message, "id", "") or (message.get("id") if isinstance(message, dict) else "") or "")
                            emit(
                                "agent.message.delta",
                                {"id": message_id, "role": "assistant", "delta": content},
                            )
                            emit(
                                "agent.message.completed",
                                {"id": message_id, "role": "assistant", "content": content},
                            )

                tools_payload = chunk.get("tools")
                if isinstance(tools_payload, dict):
                    for message in list(tools_payload.get("messages") or []):
                        correlation_id, tool_name, result = _normalize_tool_message(message)
                        normalized_result = to_jsonable(result)
                        tool_history.append(
                            {
                                "correlation_id": correlation_id,
                                "tool_name": tool_name,
                                "result": normalized_result,
                            }
                        )
                        emit(
                            "agent.tool.result",
                            {
                                "id": correlation_id,
                                "tool_name": tool_name,
                                "status": "completed",
                                "result": normalized_result,
                                "effect": dict(normalized_result.get("effect") or {}) if isinstance(normalized_result, dict) else {},
                            },
                            correlation_id=correlation_id,
                        )
        except Exception as exc:
            final_message = str(exc).strip() or "assistant stream failed"
            emit("agent.error", {"message": final_message})

        emit("agent.done", {"session_id": session_id})
        return {
            "events": events,
            "message": final_message,
            "pending_interrupt": pending_interrupt,
            "tool_history": tool_history,
            "graph_state": {
                "api_key_id": str(config.get("configurable", {}).get("api_key_id") or ""),
                "chat_model_id": str(config.get("configurable", {}).get("chat_model_id") or ""),
                "run_id": run_id,
            },
        }

    async def _finalize_session(self, session: CanvasAgentSession, consumed: dict[str, Any]) -> CanvasAssistantTurnResult:
        message = str(consumed.get("message") or "").strip()
        pending_interrupt = consumed.get("pending_interrupt")
        if message:
            session.conversation.append({"role": "assistant", "content": message})
        session.graph_state = dict(consumed.get("graph_state") or {})
        session.pending_interrupt = pending_interrupt if isinstance(pending_interrupt, AgentInterrupt) else None
        session.tool_history = list(consumed.get("tool_history") or [])[-8:]
        session.resume_in_flight = False
        session.status = "failed" if any(event.get("type") == "agent.error" for event in list(consumed.get("events") or [])) else ("interrupted" if session.pending_interrupt else "completed")
        await self.session_store.save(session)
        return CanvasAssistantTurnResult(
            session_id=session.session_id,
            message=message,
            events=list(consumed.get("events") or []),
            pending_interrupt=session.pending_interrupt,
        )
