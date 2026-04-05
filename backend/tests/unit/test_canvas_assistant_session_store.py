import json
import uuid

import pytest

from src.assistant.session_store import RedisCanvasAssistantSessionStore
from src.assistant.types import AgentInterrupt, CanvasAgentSession
from src.models.canvas import CanvasItem


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def delete(self, *keys: str):
        removed = 0
        for key in keys:
            if key in self.values:
                removed += 1
                self.values.pop(key, None)
        return removed


@pytest.mark.asyncio
async def test_redis_session_store_persists_pending_interrupt_and_graph_state() -> None:
    store = RedisCanvasAssistantSessionStore(FakeRedis(), ttl_seconds=600)
    session = CanvasAgentSession(
        session_id="session-1",
        user_id="user-1",
        document_id="doc-1",
        conversation=[{"role": "user", "content": "hello"}],
        user_goal="删除开场节点",
        pending_interrupt=AgentInterrupt(
            interrupt_id="interrupt-1",
            kind="confirm_delete",
            title="确认删除节点",
            message="准备执行",
            actions=["approve", "reject"],
            tool_name="canvas.delete_items",
            args={"item_ids": ["item-1"]},
        ),
        graph_state={"route": "request_interrupt", "resolved_targets": [{"item_id": "item-1"}]},
        tool_history=[{"tool_name": "canvas.find_items", "result": {"items": [{"id": "item-1"}]}}],
        status="interrupted",
    )

    await store.save(session)
    restored = await store.require("session-1", "user-1", "doc-1")

    assert restored.pending_interrupt is not None
    assert restored.pending_interrupt.interrupt_id == "interrupt-1"
    assert restored.graph_state == {"route": "request_interrupt", "resolved_targets": [{"item_id": "item-1"}]}
    assert restored.tool_history[0]["tool_name"] == "canvas.find_items"


@pytest.mark.asyncio
async def test_redis_session_store_rejects_duplicate_resume_lock() -> None:
    redis = FakeRedis()
    store = RedisCanvasAssistantSessionStore(redis, ttl_seconds=600)
    session = CanvasAgentSession(
        session_id="session-1",
        user_id="user-1",
        document_id="doc-1",
        pending_interrupt=AgentInterrupt(
            interrupt_id="interrupt-1",
            kind="confirm_delete",
            title="确认删除节点",
            message="准备执行",
            actions=["approve", "reject"],
        ),
    )
    await store.save(session)

    resumed = await store.begin_resume("session-1", "user-1", "doc-1", "interrupt-1")
    assert resumed.session_id == "session-1"

    with pytest.raises(ValueError, match="already resuming"):
        await store.begin_resume("session-1", "user-1", "doc-1", "interrupt-1")

    payload = json.loads(redis.values[store._session_key("session-1")])
    assert payload["resume_in_flight"] is True


@pytest.mark.asyncio
async def test_redis_session_store_serializes_canvas_models_in_tool_history() -> None:
    store = RedisCanvasAssistantSessionStore(FakeRedis(), ttl_seconds=600)
    item = CanvasItem(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        item_type="text",
        title="新标题",
        content_json={"text": "内容"},
        generation_config_json={},
        last_output_json={},
    )
    session = CanvasAgentSession(
        session_id="session-serialize",
        user_id="user-1",
        document_id="doc-1",
        tool_history=[{"tool_name": "canvas.update_item", "result": {"item": item}}],
    )

    await store.save(session)
    restored = await store.require("session-serialize", "user-1", "doc-1")

    serialized_item = restored.tool_history[0]["result"]["item"]
    assert serialized_item["title"] == "新标题"
