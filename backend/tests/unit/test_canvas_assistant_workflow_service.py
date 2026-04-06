from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.assistant.workflow_service import CanvasAssistantWorkflowService


class _FakeAPIKey:
    provider = "custom"
    base_url = "https://example.com"

    def get_api_key(self):
        return "secret"


class _FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def completions(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_prepare_script_requires_old_workflow_fields() -> None:
    canvas_service = AsyncMock()
    canvas_service.get_graph.return_value = {"items": []}
    service = CanvasAssistantWorkflowService(
        canvas_service=canvas_service,
        generation_service=AsyncMock(),
        api_key_service=AsyncMock(),
    )

    result = await service.prepare_script(
        document_id="doc-1",
        user_id="user-1",
        api_key_id="key-1",
        chat_model_id="model-1",
        input_data={"idea": "机器人冒险"},
    )

    assert result["ok"] is False
    assert "script_type" in result["missing_fields"]
    assert result["effect"]["mutated"] is False


@pytest.mark.asyncio
async def test_prepare_script_generates_script_node_with_prompt_constraints() -> None:
    canvas_service = AsyncMock()
    canvas_service.get_graph.return_value = {"items": []}
    canvas_service.create_item.return_value = SimpleNamespace(
        id="script-1",
        document_id="doc-1",
        item_type="text",
        title="剧本",
        position_x=0,
        position_y=0,
        width=320,
        height=220,
        content_json={"text": "剧本文本"},
    )
    api_key_service = AsyncMock()
    api_key_service.get_api_key_by_id.return_value = _FakeAPIKey()
    provider = _FakeProvider([
        {"choices": [{"message": {"content": "第一场，机器人在荒漠中苏醒。"}}]}
    ])

    service = CanvasAssistantWorkflowService(
        canvas_service=canvas_service,
        generation_service=AsyncMock(),
        api_key_service=api_key_service,
        provider_factory=SimpleNamespace(create=lambda **_: provider),
    )

    result = await service.prepare_script(
        document_id="doc-1",
        user_id="user-1",
        api_key_id="key-1",
        chat_model_id="model-1",
        input_data={
            "idea": "机器人在荒漠寻找记忆",
            "script_type": "short_film",
            "style_id": "cinematic",
            "language": "中文",
            "duration_target": "60s",
            "shot_duration_seconds": 5,
            "constraints": ["不要喜剧化", "保持末世感"],
        },
    )

    assert result["ok"] is True
    assert result["effect"]["created_item_ids"] == ["script-1"]
    call_payload = canvas_service.create_item.await_args.args[2]
    assert call_payload["content"]["workflow_step"] == "script"
    assert call_payload["content"]["style_id"] == "cinematic"
    assert call_payload["content"]["draft_text"] == "第一场，机器人在荒漠中苏醒。"
    assert "不要喜剧化" in provider.calls[0]["messages"][1]["content"]


@pytest.mark.asyncio
async def test_prepare_script_auto_advances_when_script_already_exists() -> None:
    canvas_service = AsyncMock()
    existing_script = SimpleNamespace(
        id="script-1",
        document_id="doc-1",
        item_type="text",
        title="剧本",
        content_json={"text": "现有剧本", "workflow_kind": "script", "workflow_step": "script", "style_id": "cinematic"},
    )
    canvas_service.get_graph.return_value = {"items": [existing_script]}
    canvas_service.get_item.return_value = existing_script
    created_ids = iter(["char-1", "story-1", "key-1", "video-1"])
    connection_ids = iter(["conn-1", "conn-2", "conn-3", "conn-4", "conn-5", "conn-6"])

    async def create_item(_doc, _user, payload):
        return SimpleNamespace(
            id=next(created_ids),
            document_id="doc-1",
            item_type=payload["item_type"],
            title=payload["title"],
            position_x=payload.get("position_x", 0),
            position_y=payload.get("position_y", 0),
            width=payload.get("width", 320),
            height=payload.get("height", 220),
            content_json=payload.get("content", {}),
        )

    async def create_connection(_doc, _user, payload):
        return SimpleNamespace(id=next(connection_ids), **payload)

    canvas_service.create_item.side_effect = create_item
    canvas_service.create_connection.side_effect = create_connection
    api_key_service = AsyncMock()
    api_key_service.get_api_key_by_id.return_value = _FakeAPIKey()
    provider = _FakeProvider([
        {"choices": [{"message": {"content": '{"characters":[{"name":"探路者","era_background":"近未来","occupation":"机器人","role_description":"孤独的探索者","visual_traits":"白色机体","key_visual_traits":["白色机体","橙色眼睛","磨损边缘"],"dialogue_traits":"克制","character_type":"machine","three_view_prompt":"机器人三视图"}]}'}}]},
        {"choices": [{"message": {"content": '{"scenes":[{"order_index":1,"scene":"荒漠山脊","characters":["探路者"],"shots":[{"order_index":1,"narrative":"机器人迎风前行","characters":["探路者"],"storyboard_text":"荒漠中机器人前行","keyframe_prompt":"荒漠中机器人关键帧","video_prompt":"荒漠中机器人视频提示词"}]}]}'}}]},
    ])

    service = CanvasAssistantWorkflowService(
        canvas_service=canvas_service,
        generation_service=AsyncMock(),
        api_key_service=api_key_service,
        provider_factory=SimpleNamespace(create=lambda **_: provider),
    )

    result = await service.prepare_script(
        document_id="doc-1",
        user_id="user-1",
        api_key_id="key-1",
        chat_model_id="model-1",
        input_data={"idea": "ignored", "script_type": "trailer", "style_id": "cinematic", "language": "中文", "duration_target": "30s", "shot_duration_seconds": 8},
    )

    assert result["ok"] is True
    assert result["counts"]["videos"] == 1


@pytest.mark.asyncio
async def test_prepare_workflow_from_script_creates_chain_nodes() -> None:
    canvas_service = AsyncMock()
    script_item = SimpleNamespace(
        id="script-1",
        document_id="doc-1",
        item_type="text",
        title="剧本",
        content_json={
            "text": "机器人在荒漠醒来。",
            "script_type": "short_film",
            "style_id": "cinematic",
            "shot_duration_seconds": 5,
            "constraints": ["保持肃杀感"],
        },
    )
    canvas_service.get_item.return_value = script_item
    created_ids = iter(["char-1", "story-1", "key-1", "video-1"])
    connection_ids = iter(["conn-1", "conn-2", "conn-3", "conn-4", "conn-5", "conn-6"])

    def _make_item(**kwargs):
        return SimpleNamespace(
            id=next(created_ids),
            document_id="doc-1",
            item_type=kwargs["item_type"],
            title=kwargs["title"],
            position_x=kwargs.get("position_x", 0),
            position_y=kwargs.get("position_y", 0),
            width=kwargs.get("width", 320),
            height=kwargs.get("height", 220),
            content_json=kwargs.get("content", {}),
        )

    def _make_conn(**kwargs):
        return SimpleNamespace(id=next(connection_ids), **kwargs)

    async def create_item(_doc, _user, payload):
        return _make_item(**payload)

    async def create_connection(_doc, _user, payload):
        return _make_conn(**payload)

    canvas_service.create_item.side_effect = create_item
    canvas_service.create_connection.side_effect = create_connection
    api_key_service = AsyncMock()
    api_key_service.get_api_key_by_id.return_value = _FakeAPIKey()
    provider = _FakeProvider([
        {"choices": [{"message": {"content": '{"characters":[{"name":"探路者","era_background":"近未来","occupation":"机器人","role_description":"孤独的探索者","visual_traits":"白色机体，橙色眼睛","key_visual_traits":["白色机体","橙色眼睛","磨损边缘"],"dialogue_traits":"克制","character_type":"machine","three_view_prompt":"机器人三视图，正侧背，电影写实风格"}]}'}}]},
        {"choices": [{"message": {"content": '{"scenes":[{"order_index":1,"scene":"荒漠山脊","characters":["探路者"],"shots":[{"order_index":1,"narrative":"机器人迎风前行","characters":["探路者"],"storyboard_text":"荒漠中机器人前行","keyframe_prompt":"荒漠中机器人关键帧","video_prompt":"荒漠中机器人视频提示词"}]}]}'}}]},
    ])

    service = CanvasAssistantWorkflowService(
        canvas_service=canvas_service,
        generation_service=AsyncMock(),
        api_key_service=api_key_service,
        provider_factory=SimpleNamespace(create=lambda **_: provider),
    )

    result = await service.prepare_workflow_from_script(
        document_id="doc-1",
        user_id="user-1",
        api_key_id="key-1",
        chat_model_id="model-1",
        script_item_id="script-1",
    )

    assert result["ok"] is True
    assert result["counts"] == {"character_views": 1, "storyboards": 1, "keyframes": 1, "videos": 1}
    assert len(result["effect"]["created_item_ids"]) == 4
    assert len(result["effect"]["created_connection_ids"]) == 6
    keyframe_item = next(item for item in result["items"] if item["title"] == "分镜 01-01 关键帧")
    assert keyframe_item["content_json"]["resolvedMentions"][0]["nodeId"] == "char-1"


@pytest.mark.asyncio
async def test_generate_keyframes_submits_existing_workflow_items() -> None:
    canvas_service = AsyncMock()
    canvas_service.get_graph.return_value = {
        "items": [
            SimpleNamespace(
                id="key-1",
                item_type="image",
                title="分镜 01-01 关键帧",
                content_json={"workflow_kind": "keyframe", "workflow_step": "images", "draft_prompt": "关键帧 prompt"},
            )
        ]
    }
    generation_service = AsyncMock()
    generation_service.prepare_image_generation.return_value = (
        SimpleNamespace(id="key-1"),
        SimpleNamespace(id="gen-1"),
    )
    generation_service.attach_task.return_value = (
        SimpleNamespace(id="key-1"),
        SimpleNamespace(id="gen-1"),
    )

    service = CanvasAssistantWorkflowService(
        canvas_service=canvas_service,
        generation_service=generation_service,
        api_key_service=AsyncMock(),
        dispatch_image=lambda generation_id: f"task-{generation_id}",
    )

    result = await service.generate_keyframes(
        document_id="doc-1",
        user_id="user-1",
        api_key_id="key-1",
        chat_model_id="model-1",
    )

    assert result["ok"] is True
    generation_service.prepare_image_generation.assert_awaited_once()
    assert result["effect"]["submitted_task_ids"] == ["task-gen-1"]
