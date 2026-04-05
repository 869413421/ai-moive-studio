from types import SimpleNamespace

import pytest

from src.api.v1.canvas_assistant import get_canvas_assistant_service
from src.main import app

pytestmark = pytest.mark.integration


class FakeAssistantService:
    def __init__(self, result):
        self._result = result

    async def chat(self, request, user_id: str):
        return self._result

    async def resume(self, request, user_id: str):
        return self._result


@pytest.mark.asyncio
async def test_canvas_assistant_chat_route_streams_agent_events(client, auth_headers):
    result = SimpleNamespace(
        session_id="session-1",
        message="准备执行",
        events=[
            {"type": "agent.session.started", "data": {"session_id": "session-1"}},
            {"type": "agent.interrupt.requested", "data": {"interrupt_id": "interrupt-1", "session_id": "session-1"}},
            {"type": "agent.done", "data": {"session_id": "session-1"}},
        ],
        pending_interrupt=None,
    )

    app.dependency_overrides[get_canvas_assistant_service] = lambda: FakeAssistantService(result)
    try:
        response = await client.post(
            "/api/v1/canvas-assistant/chat",
            headers=auth_headers,
            json={
                "document_id": "doc-1",
                "message": "把这个节点改掉",
            },
        )
    finally:
        app.dependency_overrides.pop(get_canvas_assistant_service, None)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "agent.interrupt.requested" in response.text


@pytest.mark.asyncio
async def test_canvas_assistant_resume_route_streams_agent_events(client, auth_headers):
    result = SimpleNamespace(
        session_id="session-1",
        message="已完成",
        events=[
            {"type": "agent.tool.call", "data": {"tool_name": "canvas.update_item"}},
            {"type": "agent.tool.result", "data": {"tool_name": "canvas.update_item", "result": {"effect": {"updated_item_ids": ["item-1"]}}}},
            {"type": "agent.done", "data": {"session_id": "session-1"}},
        ],
        pending_interrupt=None,
    )

    app.dependency_overrides[get_canvas_assistant_service] = lambda: FakeAssistantService(result)
    try:
        response = await client.post(
            "/api/v1/canvas-assistant/resume",
            headers=auth_headers,
            json={
                "document_id": "doc-1",
                "session_id": "session-1",
                "interrupt_id": "interrupt-1",
                "decision": "approve",
            },
        )
    finally:
        app.dependency_overrides.pop(get_canvas_assistant_service, None)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "agent.tool.call" in response.text
