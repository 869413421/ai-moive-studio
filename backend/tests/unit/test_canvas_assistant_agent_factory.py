import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.assistant.agent_factory import CanvasAssistantAgentFactory, CanvasAssistantToolCallingChatModel
from src.services.api_key import APIKeyService
from src.services.provider.factory import ProviderFactory


@pytest.mark.asyncio
async def test_tool_calling_model_bind_tools_does_not_deepcopy_async_session() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        model = CanvasAssistantToolCallingChatModel(
            api_key_id="key-1",
            chat_model_id="model-1",
            user_id="user-1",
            document_id="doc-1",
            observation_summary={},
            api_key_service=APIKeyService(session),
            provider_factory=ProviderFactory,
        )

        rebound = model.bind_tools([])

    assert isinstance(rebound, CanvasAssistantToolCallingChatModel)
    assert rebound._bound_tools == []


@pytest.mark.asyncio
async def test_tool_calling_model_serializes_uuid_observation_summary() -> None:
    class _FakeAPIKey:
        provider = "custom"
        base_url = "https://example.com"

        def get_api_key(self):
            return "secret"

    class _FakeAPIKeyService(APIKeyService):
        def __init__(self):
            pass

        async def get_api_key_by_id(self, key_id, user_id):
            return _FakeAPIKey()

    captured_messages = {}

    class _FakeProviderFactory:
        @staticmethod
        def create(provider: str, api_key: str, **kwargs):
            class _Provider:
                async def completions(self, **completion_kwargs):
                    captured_messages["messages"] = completion_kwargs["messages"]
                    return {"choices": [{"message": {"content": '{"kind":"final","message":"ok"}'}}]}

            return _Provider()

    model = CanvasAssistantToolCallingChatModel(
        api_key_id="key-1",
        chat_model_id="model-1",
        user_id="user-1",
        document_id="doc-1",
        observation_summary={
            "canvas": {
                "document": {"id": uuid.uuid4()},
                "items": [{"id": uuid.uuid4(), "title": "节点"}],
            }
        },
        api_key_service=_FakeAPIKeyService(),
        provider_factory=_FakeProviderFactory,
    )

    result = await model.ainvoke("你好")

    assert result.content == "ok"
    observation_payload = captured_messages["messages"][1]["content"]
    assert "UUID(" not in observation_payload


@pytest.mark.asyncio
async def test_canvas_create_item_tool_accepts_flattened_args() -> None:
    execution_tools = AsyncMock()
    execution_tools.create_item.return_value = {
        "item": {"id": "item-1", "item_type": "text", "title": "剧本草稿", "content": {"text": "请在此处输入"}},
        "effect": {"mutated": True, "created_item_ids": ["item-1"], "summary": "已创建节点。"},
    }

    factory = CanvasAssistantAgentFactory(
        db_session=AsyncMock(),
        inspection_tools=AsyncMock(),
        canvas_execution_tools=execution_tools,
        generation_tools=AsyncMock(),
    )
    tools = factory._build_tools()
    create_tool = next(tool for tool in tools if tool.name == "canvas_create_item")

    result = await create_tool.ainvoke(
        {
            "title": "剧本草稿",
            "item_type": "text",
            "content": "请在此处输入您的剧本构思",
        },
        config={"configurable": {"document_id": "doc-1", "user_id": "user-1"}},
    )

    execution_tools.create_item.assert_awaited_once_with(
        "doc-1",
        "user-1",
        {
            "title": "剧本草稿",
            "item_type": "text",
            "content": {"text": "请在此处输入您的剧本构思"},
        },
    )
    assert result["ok"] is True
    assert result["effect"]["needs_refresh"] is True


@pytest.mark.asyncio
async def test_generation_submit_tool_accepts_target_item_id_and_string_payload() -> None:
    generation_tools = AsyncMock()
    generation_tools.submit_generation.return_value = {
        "submitted": [{"item_id": "item-1", "kind": "text", "task_id": "task-1", "status": "submitted"}],
        "effect": {"mutated": True, "submitted_task_ids": ["task-1"], "summary": "已提交生成任务。"},
    }

    factory = CanvasAssistantAgentFactory(
        db_session=AsyncMock(),
        inspection_tools=AsyncMock(),
        canvas_execution_tools=AsyncMock(),
        generation_tools=generation_tools,
    )
    tools = factory._build_tools()
    submit_tool = next(tool for tool in tools if tool.name == "generation_submit")

    result = await submit_tool.ainvoke(
        {
            "target_item_id": "item-1",
            "payload": "请根据剧本输出八个分镜",
        },
        config={"configurable": {"user_id": "user-1", "api_key_id": "key-1", "chat_model_id": "model-1"}},
    )

    generation_tools.submit_generation.assert_awaited_once_with(
        "user-1",
        "item-1",
        "text",
        {
            "prompt": "请根据剧本输出八个分镜",
            "api_key_id": "key-1",
            "model": "model-1",
        },
    )
    assert result["ok"] is True
    assert result["effect"]["needs_refresh"] is True
