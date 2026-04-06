from unittest.mock import AsyncMock

import pytest
from langgraph.types import Command

from src.api.schemas.canvas_assistant import CanvasAssistantChatRequest, CanvasAssistantResumeRequest
from src.assistant.service import CanvasAssistantService, _build_workflow_context, _extract_workflow_draft
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


def test_extract_workflow_draft_accumulates_old_workflow_slots_from_conversation() -> None:
    draft = _extract_workflow_draft(
        [
            {"role": "user", "content": "做一个像《沙丘》一样的史诗感荒漠预告片，画面是低饱和赭石与废土沙色调，强调 70MM IMAX 胶片感和长焦压缩空间。"},
            {"role": "assistant", "content": "请提供总时长和单镜头秒数。"},
            {"role": "user", "content": "总时长 60 秒，单镜头 3 秒。"},
        ]
    )

    assert draft["script_type"] == "trailer"
    assert draft["style_id"] == "cinematic"
    assert draft["language"] == "中文"
    assert draft["duration_target"] == "60s"
    assert draft["shot_duration_seconds"] == 3
    assert "沙丘" in draft["idea"]


def test_build_workflow_context_reports_missing_fields_from_draft() -> None:
    workflow = _build_workflow_context(
        "帮我生成剧本",
        {"canvas": {"items": []}},
        workflow_draft={"idea": "荒漠史诗预告片", "script_type": "trailer", "language": "中文"},
    )

    assert workflow["target_stages"] == ["script"]
    assert "style_id" in workflow["missing_fields"]
    assert "duration_target" in workflow["missing_fields"]


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
            message="先生成剧本，再继续角色三视图和关键帧",
            api_key_id="key-1",
            chat_model_id="model-1",
        ),
        user_id="user-1",
    )

    agent_factory.assert_awaited_once()
    assert fake_graph.calls[0]["stream_mode"] == "updates"
    assert fake_graph.calls[0]["config"]["configurable"]["thread_id"] == "session-1"
    assert fake_graph.calls[0]["context"]["observation"]["canvas"]["document"]["id"] == "doc-1"
    assert fake_graph.calls[0]["context"]["workflow"]["target_stages"] == [
        "script",
        "character_views",
        "keyframes",
    ]
    assert [event["type"] for event in result.events] == [
        "agent.session.started",
        "agent.thinking.delta",
        "agent.tool.call",
        "agent.tool.result",
        "agent.message.delta",
        "agent.message.completed",
        "agent.done",
    ]
    thinking_event = result.events[1]["data"]
    tool_call_event = result.events[2]["data"]
    tool_result_event = result.events[3]["data"]
    done_event = result.events[-1]["data"]
    assert "剧本" in thinking_event["delta"]
    assert "角色三视图" in thinking_event["delta"]
    assert tool_call_event["correlation_id"] == "call-1"
    assert tool_result_event["correlation_id"] == "call-1"
    assert tool_result_event["effect"]["needs_refresh"] is False
    assert done_event["event_id"]
    assert done_event["sequence"] == 7
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
        "agent.thinking.delta",
        "agent.interrupt.requested",
        "agent.done",
    ]
    assert interrupted.pending_interrupt is not None
    assert isinstance(resume_graph.calls[0]["payload"], Command)
    assert [event["type"] for event in resumed.events] == [
        "agent.session.started",
        "agent.interrupt.resolved",
        "agent.thinking.delta",
        "agent.tool.result",
        "agent.message.delta",
        "agent.message.completed",
        "agent.done",
    ]
    resolved_event = resumed.events[1]["data"]
    thinking_event = resumed.events[2]["data"]
    tool_result_event = resumed.events[3]["data"]
    assert resolved_event["correlation_id"] == "interrupt-1"
    assert "继续执行" in thinking_event["delta"]
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
        "agent.thinking.delta",
        "agent.error",
        "agent.done",
    ]
    assert "stream crashed" in result.events[2]["data"]["message"]
    assert "stream crashed" in result.message


@pytest.mark.asyncio
async def test_chat_stops_when_same_failed_tool_call_repeats() -> None:
    store = AsyncMock()
    store.get_or_create.return_value = CanvasAgentSession(
        session_id="session-1",
        user_id="user-1",
        document_id="doc-1",
    )
    inspection_tools = AsyncMock()
    inspection_tools.inspect_graph.return_value = {
        "document": {"id": "doc-1"},
        "items": [{"id": "script-1", "title": "剧本"}],
        "connections": [],
        "counts": {"items": 1, "connections": 0},
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
                                    "name": "generation_submit",
                                    "args": {"item_id": "script-1", "kind": "text", "payload": {"prompt": "生成八个分镜"}},
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
                            "name": "generation_submit",
                            "content": "Error invoking tool 'generation_submit' with kwargs {'item_id': 'script-1'} with error: 缺少 api_key_id",
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
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-2",
                                    "name": "generation_submit",
                                    "args": {"item_id": "script-1", "kind": "text", "payload": {"prompt": "生成八个分镜"}},
                                    "type": "tool_call",
                                }
                            ],
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
            message="根据剧本分出八个分镜并写到画布",
            api_key_id="key-1",
            chat_model_id="model-1",
        ),
        user_id="user-1",
    )

    assert [event["type"] for event in result.events] == [
        "agent.session.started",
        "agent.thinking.delta",
        "agent.tool.call",
        "agent.tool.result",
        "agent.error",
        "agent.done",
    ]
    assert "重复失败" in result.events[4]["data"]["message"]


@pytest.mark.asyncio
async def test_chat_does_not_claim_canvas_success_without_mutation() -> None:
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
                            "content": "已在画布上创建了 8 个分镜节点。",
                            "tool_calls": [],
                        }
                    ]
                }
            }
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
            message="把内容写到画布上",
            api_key_id="key-1",
            chat_model_id="model-1",
        ),
        user_id="user-1",
    )

    assert result.events[-2]["type"] == "agent.error"
    assert "尚未成功写入画布" in result.events[-2]["data"]["message"]
    assert "尚未成功写入画布" in result.message
