from unittest.mock import AsyncMock

import pytest
from langgraph.types import Command

from src.api.schemas.canvas_assistant import CanvasAssistantChatRequest, CanvasAssistantResumeRequest
from src.assistant.service import CanvasAssistantService
from src.assistant.sse import encode_sse_event
from src.assistant.types import CanvasAgentSession


class _FakeInterrupt:
    def __init__(self, interrupt_id: str, value: dict):
        self.id = interrupt_id
        self.value = value


class _FakeAgentGraph:
    def __init__(self, chunks=None, error: Exception | None = None):
        self.chunks = list(chunks or [])
        self.error = error
        self.calls = []

    async def astream(self, payload, config=None, context=None, stream_mode=None):
        self.calls.append(
            {
                "payload": payload,
                "config": config,
                "context": context,
                "stream_mode": stream_mode,
            }
        )
        if self.error is not None:
            raise self.error
        for chunk in self.chunks:
            yield chunk


def test_sse_event_writer_serializes_agent_event() -> None:
    body = encode_sse_event("agent.message.delta", {"delta": "hello"})
    assert body == 'data: {"type":"agent.message.delta","data":{"delta":"hello"}}\n\n'


@pytest.mark.asyncio
async def test_chat_uses_official_agent_and_emits_normalized_events() -> None:
    store = AsyncMock()
    store.get_or_create.return_value = CanvasAgentSession(
        session_id="session-1",
        user_id="user-1",
        document_id="doc-1",
    )
    inspection_tools = AsyncMock()
    inspection_tools.inspect_graph.return_value = {
        "document": {"id": "doc-1"},
        "items": [],
        "connections": [],
        "counts": {"items": 0, "connections": 0},
    }
    fake_graph = _FakeAgentGraph(
        chunks=[
            {
                "agent": {
                    "messages": [
                        {
                            "id": "assistant-1",
                            "type": "ai",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "name": "canvas.find_items",
                                    "args": {"query": "开场节点"},
                                    "type": "tool_call",
                                }
                            ],
                        }
                    ]
                }
            },
            {
                "tools": {
                    "messages": [
                        {
                            "tool_call_id": "call-1",
                            "name": "canvas.find_items",
                            "content": (
                                '{"ok": true, "summary": "找到 1 个候选节点。", '
                                '"effect": {"mutated": false, "needs_refresh": false, "refresh_scopes": [], "side_effects": []}}'
                            ),
                        }
                    ]
                }
            },
            {
                "agent": {
                    "messages": [
                        {
                            "id": "assistant-2",
                            "type": "ai",
                            "content": "已找到开场节点。",
                            "tool_calls": [],
                        }
                    ]
                }
            },
        ]
    )
    agent_factory = AsyncMock(return_value=fake_graph)

    service = CanvasAssistantService(
        session_store=store,
        agent_factory=agent_factory,
        inspection_tools=inspection_tools,
        canvas_execution_tools=AsyncMock(),
        generation_tools=AsyncMock(),
    )

    result = await service.chat(
        CanvasAssistantChatRequest(
            document_id="doc-1",
            message="查找开场节点",
            api_key_id="key-1",
            chat_model_id="model-1",
        ),
        user_id="user-1",
    )

    agent_factory.assert_awaited_once()
    assert fake_graph.calls[0]["stream_mode"] == "updates"
    assert fake_graph.calls[0]["config"]["configurable"]["thread_id"] == "session-1"
    assert fake_graph.calls[0]["context"]["observation"]["canvas"]["document"]["id"] == "doc-1"
    assert [event["type"] for event in result.events] == [
        "agent.session.started",
        "agent.tool.call",
        "agent.tool.result",
        "agent.message.delta",
        "agent.message.completed",
        "agent.done",
    ]
    tool_call_event = result.events[1]["data"]
    tool_result_event = result.events[2]["data"]
    done_event = result.events[-1]["data"]
    assert tool_call_event["correlation_id"] == "call-1"
    assert tool_result_event["correlation_id"] == "call-1"
    assert tool_result_event["effect"]["needs_refresh"] is False
    assert done_event["event_id"]
    assert done_event["sequence"] == 6
    assert done_event["run_id"] == tool_call_event["run_id"]
    assert result.message == "已找到开场节点。"


@pytest.mark.asyncio
async def test_chat_interrupt_and_resume_stay_on_official_agent_path() -> None:
    store = AsyncMock()
    store.get_or_create.return_value = CanvasAgentSession(
        session_id="session-1",
        user_id="user-1",
        document_id="doc-1",
    )
    store.begin_resume.return_value = CanvasAgentSession(
        session_id="session-1",
        user_id="user-1",
        document_id="doc-1",
        conversation=[{"role": "user", "content": "删除开场节点"}],
        graph_state={"api_key_id": "key-1", "chat_model_id": "model-1"},
    )
    inspection_tools = AsyncMock()
    inspection_tools.inspect_graph.return_value = {
        "document": {"id": "doc-1"},
        "items": [{"id": "item-1", "title": "开场节点"}],
        "connections": [],
        "counts": {"items": 1, "connections": 0},
    }
    interrupt_graph = _FakeAgentGraph(
        chunks=[
            {
                "__interrupt__": (
                    _FakeInterrupt(
                        "interrupt-1",
                        {
                            "kind": "confirm_execute",
                            "title": "确认删除",
                            "message": "删除后无法恢复，是否继续？",
                            "actions": ["approve", "reject"],
                            "tool_name": "canvas.delete_items",
                            "args": {"item_ids": ["item-1"]},
                        },
                    ),
                )
            }
        ]
    )
    resume_graph = _FakeAgentGraph(
        chunks=[
            {
                "tools": {
                    "messages": [
                        {
                            "tool_call_id": "interrupt-1",
                            "name": "canvas.delete_items",
                            "content": (
                                '{"ok": true, "summary": "已删除节点。", '
                                '"effect": {"mutated": true, "deleted_item_ids": ["item-1"], '
                                '"needs_refresh": true, "refresh_scopes": ["document"], "side_effects": []}}'
                            ),
                        }
                    ]
                }
            },
            {
                "agent": {
                    "messages": [
                        {
                            "id": "assistant-2",
                            "type": "ai",
                            "content": "已删除开场节点。",
                            "tool_calls": [],
                        }
                    ]
                }
            },
        ]
    )
    agent_factory = AsyncMock(side_effect=[interrupt_graph, resume_graph])

    service = CanvasAssistantService(
        session_store=store,
        agent_factory=agent_factory,
        inspection_tools=inspection_tools,
        canvas_execution_tools=AsyncMock(),
        generation_tools=AsyncMock(),
    )

    interrupted = await service.chat(
        CanvasAssistantChatRequest(
            document_id="doc-1",
            message="删除开场节点",
            api_key_id="key-1",
            chat_model_id="model-1",
        ),
        user_id="user-1",
    )
    resumed = await service.resume(
        CanvasAssistantResumeRequest(
            document_id="doc-1",
            session_id="session-1",
            interrupt_id="interrupt-1",
            decision="approve",
            selected_model_id="model-1",
        ),
        user_id="user-1",
    )

    assert [event["type"] for event in interrupted.events] == [
        "agent.session.started",
        "agent.interrupt.requested",
        "agent.done",
    ]
    assert interrupted.pending_interrupt is not None
    assert isinstance(resume_graph.calls[0]["payload"], Command)
    assert [event["type"] for event in resumed.events] == [
        "agent.session.started",
        "agent.interrupt.resolved",
        "agent.tool.result",
        "agent.message.delta",
        "agent.message.completed",
        "agent.done",
    ]
    resolved_event = resumed.events[1]["data"]
    tool_result_event = resumed.events[2]["data"]
    assert resolved_event["correlation_id"] == "interrupt-1"
    assert tool_result_event["effect"]["needs_refresh"] is True
    assert resumed.message == "已删除开场节点。"


@pytest.mark.asyncio
async def test_chat_returns_agent_error_event_when_official_stream_fails() -> None:
    store = AsyncMock()
    store.get_or_create.return_value = CanvasAgentSession(
        session_id="session-1",
        user_id="user-1",
        document_id="doc-1",
    )
    inspection_tools = AsyncMock()
    inspection_tools.inspect_graph.return_value = {
        "document": {"id": "doc-1"},
        "items": [],
        "connections": [],
        "counts": {"items": 0, "connections": 0},
    }
    agent_factory = AsyncMock(return_value=_FakeAgentGraph(error=RuntimeError("stream crashed")))
    service = CanvasAssistantService(
        session_store=store,
        agent_factory=agent_factory,
        inspection_tools=inspection_tools,
        canvas_execution_tools=AsyncMock(),
        generation_tools=AsyncMock(),
    )

    result = await service.chat(
        CanvasAssistantChatRequest(
            document_id="doc-1",
            message="查一下",
            api_key_id="key-1",
            chat_model_id="model-1",
        ),
        user_id="user-1",
    )

    assert [event["type"] for event in result.events] == [
        "agent.session.started",
        "agent.error",
        "agent.done",
    ]
    assert "stream crashed" in result.events[1]["data"]["message"]
    assert "stream crashed" in result.message
