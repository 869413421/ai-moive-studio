from unittest.mock import AsyncMock

import pytest

from src.assistant.tools.canvas_tools import CanvasAssistantCanvasExecutionTools
from src.assistant.tools.generation_tools import CanvasAssistantGenerationTools


@pytest.mark.asyncio
async def test_canvas_execution_tools_commit_mutations() -> None:
    service = AsyncMock()
    service.create_item.return_value = {"id": "item-1", "item_type": "text", "title": "剧本草稿"}

    tools = CanvasAssistantCanvasExecutionTools(service)
    result = await tools.create_item("doc-1", "user-1", {"item_type": "text", "title": "剧本草稿"})

    service.create_item.assert_awaited_once_with("doc-1", "user-1", {"item_type": "text", "title": "剧本草稿"})
    service.commit.assert_awaited_once()
    assert result["effect"].mutated is True
    assert result["effect"].created_item_ids == ["item-1"]


@pytest.mark.asyncio
async def test_generation_tools_commit_after_attach_task() -> None:
    generation_service = AsyncMock()
    generation = type("Generation", (), {"id": "gen-1"})()
    generation_service.prepare_text_generation.return_value = (object(), generation)
    generation_service.attach_task.return_value = (object(), generation)

    tools = CanvasAssistantGenerationTools(
        generation_service=generation_service,
        dispatch_text=lambda generation_id: f"task-{generation_id}",
    )
    result = await tools.submit_generation("user-1", "item-1", "text", {"prompt": "写一个科幻分镜脚本"})

    generation_service.prepare_text_generation.assert_awaited_once_with("item-1", "user-1", {"prompt": "写一个科幻分镜脚本"})
    generation_service.attach_task.assert_awaited_once_with("gen-1", "task-gen-1")
    generation_service.commit.assert_awaited_once()
    assert result["effect"].mutated is True
    assert result["submitted"][0]["task_id"] == "task-gen-1"
