import asyncio
import pytest
from unittest.mock import AsyncMock, Mock, patch

from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.integration


async def _update_canvas_generation_later(generation_id, final_payload, *, final_status="completed", intermediate_steps=None, delay=0.02):
    from src.services.canvas import CanvasService

    await asyncio.sleep(delay)
    async with TestSessionLocal() as session:
        canvas_service = CanvasService(session)
        generation = await canvas_service.get_generation(generation_id)
        item = await canvas_service.get_item_by_id(str(generation.item_id))

        for step in intermediate_steps or []:
            await canvas_service.update_generation(
                generation,
                item,
                step.get("status", "processing"),
                result_payload=step.get("result_payload"),
                error_message=step.get("error_message"),
            )
            await session.commit()
            await asyncio.sleep(step.get("delay", delay))

        await canvas_service.update_generation(
            generation,
            item,
            final_status,
            result_payload=final_payload,
        )
        await session.commit()


class TestCanvasDocumentApi:
    @pytest.mark.asyncio
    async def test_canvas_document_crud_and_graph_roundtrip(self, client, auth_headers):
        create_response = await client.post(
            "/api/v1/canvas-documents",
            headers=auth_headers,
            json={"title": "My Canvas"},
        )

        assert create_response.status_code == 201
        created = create_response.json()
        assert created["title"] == "My Canvas"
        canvas_id = created["id"]

        list_response = await client.get("/api/v1/canvas-documents", headers=auth_headers)
        assert list_response.status_code == 200
        listed = list_response.json()
        assert listed["total"] == 1
        assert listed["documents"][0]["id"] == canvas_id

        graph_payload = {
            "items": [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "item_type": "text",
                    "title": "Script Node",
                    "position_x": 120,
                    "position_y": 180,
                    "width": 360,
                    "height": 220,
                    "z_index": 1,
                    "content": {"text": "", "prompt": "write an opening scene"},
                    "generation_config": {},
                }
            ],
            "connections": [],
        }

        save_graph_response = await client.put(
            f"/api/v1/canvas-documents/{canvas_id}/graph",
            headers=auth_headers,
            json=graph_payload,
        )
        assert save_graph_response.status_code == 200

        get_graph_response = await client.get(
            f"/api/v1/canvas-documents/{canvas_id}/graph",
            headers=auth_headers,
        )
        assert get_graph_response.status_code == 200
        graph = get_graph_response.json()
        assert graph["document"]["id"] == canvas_id
        assert len(graph["items"]) == 1
        assert graph["items"][0]["title"] == "Script Node"
        assert graph["items"][0]["content"]["prompt"] == "write an opening scene"

    @pytest.mark.asyncio
    async def test_generate_text_creates_pending_generation_record(self, client, auth_headers):
        create_response = await client.post(
            "/api/v1/canvas-documents",
            headers=auth_headers,
            json={"title": "Generator Canvas"},
        )
        assert create_response.status_code == 201
        canvas_id = create_response.json()["id"]

        item_id = "22222222-2222-2222-2222-222222222222"
        save_graph_response = await client.put(
            f"/api/v1/canvas-documents/{canvas_id}/graph",
            headers=auth_headers,
            json={
                "items": [
                    {
                        "id": item_id,
                        "item_type": "text",
                        "title": "Text Generator",
                        "position_x": 0,
                        "position_y": 0,
                        "width": 360,
                        "height": 220,
                        "z_index": 1,
                        "content": {"text": "", "prompt": "Generate a suspenseful intro"},
                        "generation_config": {
                            "api_key_id": "33333333-3333-3333-3333-333333333333",
                            "model": "deepseek-chat",
                        },
                    }
                ],
                "connections": [],
            },
        )
        assert save_graph_response.status_code == 200

        with (
            patch("src.api.v1.canvas.dispatch_canvas_text_generation", return_value="task-text-1"),
        ):
            generate_response = await client.post(
                f"/api/v1/canvas-items/{item_id}/generate-text",
                headers=auth_headers,
                json={},
            )

        assert generate_response.status_code == 200
        generated = generate_response.json()
        assert generated["status"] == "pending"
        assert generated["message"] == "文本生成任务已提交"
        assert generated["generation"]["status"] == "pending"
        assert generated["generation"]["result_payload"]["task_id"] == "task-text-1"
        assert generated["item"]["content"]["text"] == ""
        assert generated["item"]["last_run_status"] == "pending"

        history_response = await client.get(
            f"/api/v1/canvas-items/{item_id}/generations",
            headers=auth_headers,
        )
        assert history_response.status_code == 200
        history = history_response.json()
        assert history["total"] == 1
        assert history["generations"][0]["generation_type"] == "text"
        assert history["generations"][0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_generate_image_creates_pending_generation_record(self, client, auth_headers):
        create_response = await client.post(
            "/api/v1/canvas-documents",
            headers=auth_headers,
            json={"title": "Image Canvas"},
        )
        assert create_response.status_code == 201
        canvas_id = create_response.json()["id"]

        item_id = "44444444-4444-4444-4444-444444444444"
        save_graph_response = await client.put(
            f"/api/v1/canvas-documents/{canvas_id}/graph",
            headers=auth_headers,
            json={
                "items": [
                    {
                        "id": item_id,
                        "item_type": "image",
                        "title": "Image Generator",
                        "position_x": 0,
                        "position_y": 0,
                        "width": 360,
                        "height": 220,
                        "z_index": 1,
                        "content": {"prompt": "A bright white studio desk"},
                        "generation_config": {
                            "api_key_id": "33333333-3333-3333-3333-333333333333",
                            "model": "gpt-image-1",
                        },
                    }
                ],
                "connections": [],
            },
        )
        assert save_graph_response.status_code == 200

        with patch("src.api.v1.canvas.dispatch_canvas_image_generation", return_value="task-image-1"):
            generate_response = await client.post(
                f"/api/v1/canvas-items/{item_id}/generate-image",
                headers=auth_headers,
                json={},
            )

        assert generate_response.status_code == 200
        generated = generate_response.json()
        assert generated["status"] == "pending"
        assert generated["message"] == "图片生成任务已提交"
        assert generated["generation"]["status"] == "pending"
        assert generated["generation"]["result_payload"]["task_id"] == "task-image-1"
        assert generated["item"]["last_run_status"] == "pending"

    @pytest.mark.asyncio
    async def test_generate_image_uses_prompt_mentions_and_style_reference_object_keys(self, client, auth_headers):
        create_response = await client.post(
            "/api/v1/canvas-documents",
            headers=auth_headers,
            json={"title": "Styled Image Canvas"},
        )
        assert create_response.status_code == 201
        canvas_id = create_response.json()["id"]

        item_id = "44444444-4444-4444-4444-444444444444"
        storage_client = Mock()
        storage_client.get_presigned_url.side_effect = lambda object_key: f"https://cdn.example.com/{object_key}"

        with (
            patch("src.services.canvas.get_storage_client", new_callable=AsyncMock, return_value=storage_client),
            patch("src.api.v1.canvas.get_storage_client", new_callable=AsyncMock, return_value=storage_client),
        ):
            save_graph_response = await client.put(
                f"/api/v1/canvas-documents/{canvas_id}/graph",
                headers=auth_headers,
                json={
                    "items": [
                        {
                            "id": item_id,
                            "item_type": "image",
                            "title": "Image Generator",
                            "position_x": 0,
                            "position_y": 0,
                            "width": 360,
                            "height": 220,
                            "z_index": 1,
                            "content": {
                                "prompt": "A poster portrait",
                                "reference_image_object_key": "uploads/style-ref.png",
                                "reference_image_url": "https://example.com/style-ref.png",
                            },
                            "generation_config": {
                                "api_key_id": "33333333-3333-3333-3333-333333333333",
                                "model": "gpt-image-1",
                            },
                        }
                    ],
                    "connections": [],
                },
            )
        assert save_graph_response.status_code == 200

        with (
            patch("src.api.v1.canvas.dispatch_canvas_image_generation", return_value="task-image-structured"),
            patch("src.services.canvas.get_storage_client", new_callable=AsyncMock, return_value=storage_client),
            patch("src.api.v1.canvas.get_storage_client", new_callable=AsyncMock, return_value=storage_client),
        ):
            generate_response = await client.post(
                f"/api/v1/canvas-items/{item_id}/generate-image",
                headers=auth_headers,
                json={
                    "prompt_plain_text": "以 @参考图 为风格生成海报",
                    "prompt_tokens": [
                        {"type": "text", "text": "以 "},
                        {
                            "type": "mention",
                            "mentionId": "mention-image-1",
                            "nodeId": "image-ref-1",
                            "nodeType": "image",
                            "nodeTitleSnapshot": "参考图",
                        },
                        {"type": "text", "text": " 为风格生成海报"},
                    ],
                    "resolved_mentions": [
                        {
                            "mentionId": "mention-image-1",
                            "nodeId": "image-ref-1",
                            "nodeType": "image",
                            "nodeTitle": "参考图",
                            "status": "resolved",
                            "resolvedContent": {
                                "object_key": "uploads/mention-ref.png",
                                "url": "https://example.com/mention-ref.png",
                            },
                        }
                    ],
                },
            )

        assert generate_response.status_code == 200
        generated = generate_response.json()
        request_payload = generated["generation"]["request_payload"]
        assert request_payload["prompt"] == "以 为风格生成海报"
        assert request_payload["prompt_plain_text"] == "以 @参考图 为风格生成海报"
        assert request_payload["options"]["reference_image_object_keys"] == ["uploads/mention-ref.png"]
        assert request_payload["options"]["style_reference_image_object_key"] == "uploads/style-ref.png"
        assert "reference_image_urls" not in request_payload["options"]
        assert "style_reference_image_url" not in request_payload["options"]
        assert request_payload["resolved_mentions"][0]["resolvedContent"]["object_key"] == "uploads/mention-ref.png"
        assert "url" not in request_payload["resolved_mentions"][0]["resolvedContent"]

    @pytest.mark.asyncio
    async def test_generate_video_creates_pending_generation_record(self, client, auth_headers):
        create_response = await client.post(
            "/api/v1/canvas-documents",
            headers=auth_headers,
            json={"title": "Video Canvas"},
        )
        assert create_response.status_code == 201
        canvas_id = create_response.json()["id"]

        item_id = "55555555-5555-5555-5555-555555555555"
        save_graph_response = await client.put(
            f"/api/v1/canvas-documents/{canvas_id}/graph",
            headers=auth_headers,
            json={
                "items": [
                    {
                        "id": item_id,
                        "item_type": "video",
                        "title": "Video Generator",
                        "position_x": 0,
                        "position_y": 0,
                        "width": 360,
                        "height": 220,
                        "z_index": 1,
                        "content": {"prompt": "A slow cinematic push-in over a clean desk"},
                        "generation_config": {
                            "api_key_id": "33333333-3333-3333-3333-333333333333",
                            "model": "veo_3_1-fast",
                        },
                    }
                ],
                "connections": [],
            },
        )
        assert save_graph_response.status_code == 200

        with patch("src.api.v1.canvas.dispatch_canvas_video_generation", return_value="task-video-1"):
            generate_response = await client.post(
                f"/api/v1/canvas-items/{item_id}/generate-video",
                headers=auth_headers,
                json={},
            )

        assert generate_response.status_code == 200
        generated = generate_response.json()
        assert generated["status"] == "pending"
        assert generated["message"] == "视频生成任务已提交"
        assert generated["generation"]["status"] == "pending"
        assert generated["generation"]["result_payload"]["task_id"] == "task-video-1"
        assert generated["item"]["last_run_status"] == "pending"

    @pytest.mark.asyncio
    async def test_generate_text_uses_prompt_tokens_and_resolved_mentions(self, client, auth_headers):
        create_response = await client.post(
            "/api/v1/canvas-documents",
            headers=auth_headers,
            json={"title": "Structured Text Canvas"},
        )
        assert create_response.status_code == 201
        canvas_id = create_response.json()["id"]

        item_id = "66666666-6666-6666-6666-666666666666"
        save_graph_response = await client.put(
            f"/api/v1/canvas-documents/{canvas_id}/graph",
            headers=auth_headers,
            json={
                "items": [
                    {
                        "id": item_id,
                        "item_type": "text",
                        "title": "Narration",
                        "position_x": 0,
                        "position_y": 0,
                        "width": 360,
                        "height": 220,
                        "z_index": 1,
                        "content": {"text": "", "prompt": "fallback prompt"},
                        "generation_config": {
                            "api_key_id": "33333333-3333-3333-3333-333333333333",
                            "model": "deepseek-chat",
                        },
                    }
                ],
                "connections": [],
            },
        )
        assert save_graph_response.status_code == 200

        with patch("src.api.v1.canvas.dispatch_canvas_text_generation", return_value="task-text-structured"):
            generate_response = await client.post(
                f"/api/v1/canvas-items/{item_id}/generate-text",
                headers=auth_headers,
                json={
                    "prompt_plain_text": "总结 @角色设定",
                    "prompt_tokens": [
                        {"type": "text", "text": "总结 "},
                        {
                            "type": "mention",
                            "mentionId": "mention-text-1",
                            "nodeId": "text-ref-1",
                            "nodeType": "text",
                            "nodeTitleSnapshot": "角色设定",
                        },
                    ],
                    "resolved_mentions": [
                        {
                            "mentionId": "mention-text-1",
                            "nodeId": "text-ref-1",
                            "nodeType": "text",
                            "nodeTitle": "角色设定",
                            "status": "resolved",
                            "resolvedContent": {
                                "text": "<p>主角是一名摄影师</p><p>沉默、克制。</p>",
                            },
                        }
                    ],
                },
            )

        assert generate_response.status_code == 200
        generated = generate_response.json()
        request_payload = generated["generation"]["request_payload"]
        assert request_payload["prompt"] == "总结 主角是一名摄影师\n\n沉默、克制。"
        assert request_payload["prompt_plain_text"] == "总结 @角色设定"
        assert request_payload["prompt_tokens"][1]["nodeId"] == "text-ref-1"
        assert request_payload["resolved_mentions"][0]["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_stream_generate_text_returns_sse_events_and_persists_result(self, client, auth_headers):
        create_response = await client.post(
            "/api/v1/canvas-documents",
            headers=auth_headers,
            json={"title": "Streaming Text Canvas"},
        )
        assert create_response.status_code == 201
        canvas_id = create_response.json()["id"]

        item_id = "67676767-6767-6767-6767-676767676767"
        save_graph_response = await client.put(
            f"/api/v1/canvas-documents/{canvas_id}/graph",
            headers=auth_headers,
            json={
                "items": [
                    {
                        "id": item_id,
                        "item_type": "text",
                        "title": "Streaming Narration",
                        "position_x": 0,
                        "position_y": 0,
                        "width": 360,
                        "height": 220,
                        "z_index": 1,
                        "content": {"text": "", "prompt": "写一段开场白"},
                        "generation_config": {
                            "api_key_id": "33333333-3333-3333-3333-333333333333",
                            "model": "deepseek-chat",
                        },
                    }
                ],
                "connections": [],
            },
        )
        assert save_graph_response.status_code == 200

        class _FakeChunk:
            def __init__(self, content):
                self.choices = [type("Choice", (), {"delta": type("Delta", (), {"content": content})()})()]

        async def _fake_stream():
            yield _FakeChunk("第一句。")
            yield _FakeChunk("第二句。")

        fake_api_key = Mock()
        fake_api_key.provider = "deepseek"
        fake_api_key.get_api_key.return_value = "test-key"

        fake_provider = Mock()
        fake_provider.completions = AsyncMock(return_value=_fake_stream())

        with (
            patch("src.services.canvas.CanvasGenerationService._resolve_api_key", AsyncMock(return_value=fake_api_key)),
            patch("src.services.canvas.CanvasGenerationService._build_provider", return_value=fake_provider),
        ):
            async with client.stream(
                "POST",
                f"/api/v1/canvas-items/{item_id}/generate-text/stream",
                headers=auth_headers,
                json={},
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                body = ""
                async for chunk in response.aiter_text():
                    body += chunk

        assert "event: start" in body
        assert "event: delta" in body
        assert "event: complete" in body
        assert '"delta": "第一句。"' in body
        assert '"delta": "第二句。"' in body
        assert "第一句。第二句。" in body

        history_response = await client.get(
            f"/api/v1/canvas-items/{item_id}/generations",
            headers=auth_headers,
        )
        assert history_response.status_code == 200
        history = history_response.json()
        assert history["total"] == 1
        assert history["generations"][0]["status"] == "completed"
        assert history["generations"][0]["result_payload"]["text"] == "第一句。第二句。"

    @pytest.mark.asyncio
    async def test_stream_generate_image_returns_sse_events_and_persists_result(self, client, auth_headers):
        create_response = await client.post(
            "/api/v1/canvas-documents",
            headers=auth_headers,
            json={"title": "Streaming Image Canvas"},
        )
        assert create_response.status_code == 201
        canvas_id = create_response.json()["id"]

        item_id = "68686868-6868-6868-6868-686868686868"
        save_graph_response = await client.put(
            f"/api/v1/canvas-documents/{canvas_id}/graph",
            headers=auth_headers,
            json={
                "items": [
                    {
                        "id": item_id,
                        "item_type": "image",
                        "title": "Streaming Image",
                        "position_x": 0,
                        "position_y": 0,
                        "width": 360,
                        "height": 220,
                        "z_index": 1,
                        "content": {"prompt": "画一张桌面图"},
                        "generation_config": {
                            "api_key_id": "33333333-3333-3333-3333-333333333333",
                            "model": "gpt-image-1",
                        },
                    }
                ],
                "connections": [],
            },
        )
        assert save_graph_response.status_code == 200

        storage_client = Mock()
        storage_client.get_presigned_url.side_effect = lambda object_key: f"https://cdn.example.com/{object_key}"

        def fake_dispatch(generation_id):
            asyncio.create_task(
                _update_canvas_generation_later(
                    generation_id,
                    {
                        "result_image_object_key": "uploads/generated.png",
                    },
                    intermediate_steps=[
                        {"status": "processing", "result_payload": {"task_id": "task-image-stream-1"}}
                    ],
                )
            )
            return "task-image-stream-1"

        with (
            patch("src.api.v1.canvas.dispatch_canvas_image_generation", side_effect=fake_dispatch),
            patch("src.services.canvas.get_storage_client", new_callable=AsyncMock, return_value=storage_client),
            patch("src.api.v1.canvas.get_storage_client", new_callable=AsyncMock, return_value=storage_client),
        ):
            async with client.stream(
                "POST",
                f"/api/v1/canvas-items/{item_id}/generate-image/stream",
                headers=auth_headers,
                json={},
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                body = ""
                async for chunk in response.aiter_text():
                    body += chunk

            item_response = await client.get(
                f"/api/v1/canvas-documents/{canvas_id}/items/{item_id}",
                headers=auth_headers,
            )

        assert "event: start" in body
        assert "event: complete" in body
        assert "https://cdn.example.com/uploads/generated.png" in body
        assert "uploads/generated.png" in body
        assert item_response.status_code == 200
        assert item_response.json()["content"]["result_image_url"] == "https://cdn.example.com/uploads/generated.png"

        async with TestSessionLocal() as session:
            from src.services.canvas import CanvasService

            persisted_item = await CanvasService(session).get_item_by_id(item_id)
            assert persisted_item.content_json["result_image_object_key"] == "uploads/generated.png"
            assert "result_image_url" not in persisted_item.content_json

    @pytest.mark.asyncio
    async def test_stream_generate_video_returns_sse_events_and_persists_result(self, client, auth_headers):
        create_response = await client.post(
            "/api/v1/canvas-documents",
            headers=auth_headers,
            json={"title": "Streaming Video Canvas"},
        )
        assert create_response.status_code == 201
        canvas_id = create_response.json()["id"]

        item_id = "69696969-6969-6969-6969-696969696969"
        save_graph_response = await client.put(
            f"/api/v1/canvas-documents/{canvas_id}/graph",
            headers=auth_headers,
            json={
                "items": [
                    {
                        "id": item_id,
                        "item_type": "video",
                        "title": "Streaming Video",
                        "position_x": 0,
                        "position_y": 0,
                        "width": 360,
                        "height": 220,
                        "z_index": 1,
                        "content": {"prompt": "生成一段慢推镜头"},
                        "generation_config": {
                            "api_key_id": "33333333-3333-3333-3333-333333333333",
                            "model": "veo_3_1-fast",
                        },
                    }
                ],
                "connections": [],
            },
        )
        assert save_graph_response.status_code == 200

        storage_client = Mock()
        storage_client.get_presigned_url.side_effect = lambda object_key: f"https://cdn.example.com/{object_key}"

        def fake_dispatch(generation_id):
            asyncio.create_task(
                _update_canvas_generation_later(
                    generation_id,
                    {
                        "provider_task_id": "provider-task-1",
                        "result_video_object_key": "uploads/generated.mp4",
                    },
                    intermediate_steps=[
                        {
                            "status": "processing",
                            "result_payload": {
                                "task_id": "task-video-stream-1",
                                "provider_task_id": "provider-task-1",
                                "provider_response": {"status": "processing"},
                            },
                            "delay": 1.2,
                        }
                    ],
                )
            )
            return "task-video-stream-1"

        with (
            patch("src.api.v1.canvas.dispatch_canvas_video_generation", side_effect=fake_dispatch),
            patch("src.services.canvas.get_storage_client", new_callable=AsyncMock, return_value=storage_client),
            patch("src.api.v1.canvas.get_storage_client", new_callable=AsyncMock, return_value=storage_client),
        ):
            async with client.stream(
                "POST",
                f"/api/v1/canvas-items/{item_id}/generate-video/stream",
                headers=auth_headers,
                json={},
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                body = ""
                async for chunk in response.aiter_text():
                    body += chunk

            item_response = await client.get(
                f"/api/v1/canvas-documents/{canvas_id}/items/{item_id}",
                headers=auth_headers,
            )

        assert "event: start" in body
        assert "event: progress" in body
        assert "event: complete" in body
        assert "https://cdn.example.com/uploads/generated.mp4" in body
        assert "uploads/generated.mp4" in body
        assert item_response.status_code == 200
        assert item_response.json()["content"]["result_video_url"] == "https://cdn.example.com/uploads/generated.mp4"

        async with TestSessionLocal() as session:
            from src.services.canvas import CanvasService

            persisted_item = await CanvasService(session).get_item_by_id(item_id)
            assert persisted_item.content_json["result_video_object_key"] == "uploads/generated.mp4"
            assert "result_video_url" not in persisted_item.content_json

    @pytest.mark.asyncio
    async def test_generate_video_builds_reference_images_from_prompt_mentions(self, client, auth_headers):
        create_response = await client.post(
            "/api/v1/canvas-documents",
            headers=auth_headers,
            json={"title": "Structured Video Canvas"},
        )
        assert create_response.status_code == 201
        canvas_id = create_response.json()["id"]

        item_id = "77777777-7777-7777-7777-777777777777"
        save_graph_response = await client.put(
            f"/api/v1/canvas-documents/{canvas_id}/graph",
            headers=auth_headers,
            json={
                "items": [
                    {
                        "id": item_id,
                        "item_type": "video",
                        "title": "Video Generator",
                        "position_x": 0,
                        "position_y": 0,
                        "width": 360,
                        "height": 220,
                        "z_index": 1,
                        "content": {"prompt": "fallback video prompt"},
                        "generation_config": {
                            "api_key_id": "33333333-3333-3333-3333-333333333333",
                            "model": "veo_3_1-fast",
                        },
                    }
                ],
                "connections": [],
            },
        )
        assert save_graph_response.status_code == 200

        with patch("src.api.v1.canvas.dispatch_canvas_video_generation", return_value="task-video-structured"):
            generate_response = await client.post(
                f"/api/v1/canvas-items/{item_id}/generate-video",
                headers=auth_headers,
                json={
                    "prompt_plain_text": "让镜头围绕 @参考图 缓慢推进，并体现 @文案",
                    "prompt_tokens": [
                        {"type": "text", "text": "让镜头围绕 "},
                        {
                            "type": "mention",
                            "mentionId": "mention-image-1",
                            "nodeId": "image-ref-1",
                            "nodeType": "image",
                            "nodeTitleSnapshot": "参考图",
                        },
                        {"type": "text", "text": " 缓慢推进，并体现 "},
                        {
                            "type": "mention",
                            "mentionId": "mention-text-1",
                            "nodeId": "text-ref-1",
                            "nodeType": "text",
                            "nodeTitleSnapshot": "文案",
                        },
                    ],
                    "resolved_mentions": [
                        {
                            "mentionId": "mention-image-1",
                            "nodeId": "image-ref-1",
                            "nodeType": "image",
                            "nodeTitle": "参考图",
                            "status": "resolved",
                            "resolvedContent": {
                                "object_key": "uploads/reference-1.png",
                                "url": "https://example.com/reference-1.png",
                            },
                        },
                        {
                            "mentionId": "mention-text-1",
                            "nodeId": "text-ref-1",
                            "nodeType": "text",
                            "nodeTitle": "文案",
                            "status": "resolved",
                            "resolvedContent": {"text": "夜色安静，镜头慢慢靠近桌面。"},
                        },
                    ],
                },
            )

        assert generate_response.status_code == 200
        generated = generate_response.json()
        request_payload = generated["generation"]["request_payload"]
        assert request_payload["prompt"] == "让镜头围绕 缓慢推进，并体现 夜色安静，镜头慢慢靠近桌面。"
        assert request_payload["options"]["reference_image_urls"] == ["uploads/reference-1.png"]
        assert request_payload["options"]["reference_text_ids"] == ["text-ref-1"]

    @pytest.mark.asyncio
    async def test_process_video_generation_converts_object_key_references_to_data_urls(self, db_session):
        from src.models.canvas import CanvasItem, CanvasItemGeneration
        from src.services.canvas import CanvasGenerationService

        item = CanvasItem(
            id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            document_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            item_type="video",
            title="Video Generator",
            position_x=0,
            position_y=0,
            width=360,
            height=220,
            z_index=1,
            content_json={"prompt": "肥猪动起来"},
            generation_config_json={"api_key_id": "33333333-3333-3333-3333-333333333333", "model": "veo3.1"},
            last_run_status="pending",
            last_output_json={},
        )
        generation = CanvasItemGeneration(
            id="cccccccc-cccc-cccc-cccc-cccccccccccc",
            item_id=item.id,
            document_id=item.document_id,
            user_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
            generation_type="video",
            request_payload_json={
                "prompt": "肥猪动起来",
                "api_key_id": "33333333-3333-3333-3333-333333333333",
                "model": "veo3.1",
                "options": {
                    "reference_image_urls": ["uploads/reference-1.jpg"],
                    "reference_text_ids": [],
                },
            },
            status="pending",
            result_payload_json={},
        )
        db_session.add(item)
        db_session.add(generation)
        await db_session.commit()

        service = CanvasGenerationService(db_session)
        fake_api_key = Mock()
        fake_api_key.provider = "vectorengine"
        fake_api_key.base_url = "https://api.aiconapi.me/v1"
        fake_api_key.get_api_key.return_value = "test-key"

        storage_client = Mock()
        storage_client.download_file = AsyncMock(return_value=b"\xff\xd8\xff\xdbfake-jpeg")

        with (
            patch.object(service, "_resolve_api_key", AsyncMock(return_value=fake_api_key)),
            patch("src.services.canvas.get_storage_client", new_callable=AsyncMock, return_value=storage_client),
            patch("src.services.canvas.VectorEngineProvider.create_video", new_callable=AsyncMock) as create_video,
            patch.object(service, "_poll_video_result", AsyncMock(return_value="https://example.com/generated.mp4")),
            patch.object(
                service,
                "_store_remote_video",
                AsyncMock(return_value={"object_key": "uploads/generated.mp4", "url": "https://ignored.example.com/generated.mp4"}),
            ),
        ):
            create_video.return_value = {"id": "provider-task-1"}
            result = await service.process_video_generation(str(generation.id))

        assert result["status"] == "completed"
        assert result["result_video_object_key"] == "uploads/generated.mp4"
        create_video.assert_awaited_once()
        kwargs = create_video.await_args.kwargs
        assert kwargs["images"] == ["data:image/jpeg;base64,/9j/22Zha2UtanBlZw=="]
        assert "reference_image_urls" not in kwargs
        assert "reference_text_ids" not in kwargs

    @pytest.mark.asyncio
    async def test_process_image_generation_passes_style_and_prompt_references_to_custom_provider(self, db_session):
        from src.models.canvas import CanvasItem, CanvasItemGeneration
        from src.services.canvas import CanvasGenerationService

        item = CanvasItem(
            id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            document_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            item_type="image",
            title="Image Generator",
            position_x=0,
            position_y=0,
            width=360,
            height=220,
            z_index=1,
            content_json={
                "prompt": "A poster portrait",
                "reference_image_object_key": "uploads/style-ref.png",
                "reference_image_url": "https://example.com/style-ref.png",
            },
            generation_config_json={
                "api_key_id": "33333333-3333-3333-3333-333333333333",
                "model": "gpt-image-1",
            },
            last_run_status="pending",
            last_output_json={},
        )
        generation = CanvasItemGeneration(
            id="cccccccc-cccc-cccc-cccc-cccccccccccc",
            item_id=item.id,
            document_id=item.document_id,
            user_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
            generation_type="image",
            request_payload_json={
                "prompt": "以 为风格生成海报",
                "prompt_plain_text": "以 @参考图 为风格生成海报",
                "api_key_id": "33333333-3333-3333-3333-333333333333",
                "model": "gpt-image-1",
                "options": {
                    "reference_image_object_keys": ["uploads/mention-ref.png"],
                    "style_reference_image_object_key": "uploads/style-ref.png",
                },
            },
            status="pending",
            result_payload_json={},
        )
        db_session.add(item)
        db_session.add(generation)
        await db_session.commit()

        service = CanvasGenerationService(db_session)
        fake_api_key = Mock()
        fake_api_key.provider = "custom"
        fake_api_key.base_url = "https://api.example.com/v1"
        fake_api_key.get_api_key.return_value = "test-key"

        fake_provider = Mock()
        fake_provider.generate_image = AsyncMock(return_value={"data": [{"url": "https://example.com/generated.png"}]})

        with (
            patch.object(service, "_resolve_api_key", AsyncMock(return_value=fake_api_key)),
            patch.object(service, "_build_provider", return_value=fake_provider),
            patch.object(service, "_resolve_image_result", AsyncMock(return_value={"object_key": "uploads/generated.png"})),
        ):
            result = await service.process_image_generation(str(generation.id))

        assert result["status"] == "completed"
        assert result["result_image_object_key"] == "uploads/generated.png"
        fake_provider.generate_image.assert_awaited_once()
        kwargs = fake_provider.generate_image.await_args.kwargs
        assert kwargs["reference_images"] == ["uploads/style-ref.png", "uploads/mention-ref.png"]
        assert "style_reference_image_object_key" not in kwargs
        assert "reference_image_object_keys" not in kwargs

    @pytest.mark.asyncio
    async def test_poll_video_result_tolerates_transient_status_failures(self, db_session):
        from src.services.canvas import CanvasGenerationService

        service = CanvasGenerationService(db_session)
        provider = Mock()
        provider.get_task_status = AsyncMock(side_effect=[
            RuntimeError("temporary status failure"),
            {"status": "processing"},
            {"status": "completed", "video_url": "https://example.com/generated.mp4"},
        ])
        provider.get_video_content = AsyncMock()

        result = await service._poll_video_result(provider, "provider-task-1")

        assert result == "https://example.com/generated.mp4"
        assert provider.get_task_status.await_count == 3
        provider.get_video_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_lite_snapshot_and_item_crud_flow(self, client, auth_headers):
        create_response = await client.post(
            "/api/v1/canvas-documents",
            headers=auth_headers,
            json={"title": "Workbench Canvas"},
        )
        assert create_response.status_code == 201
        canvas_id = create_response.json()["id"]

        create_item_response = await client.post(
            f"/api/v1/canvas-documents/{canvas_id}/items",
            headers=auth_headers,
            json={
                "item_type": "text",
                "title": "Opening Beat",
                "position_x": 80,
                "position_y": 120,
                "width": 360,
                "height": 220,
                "z_index": 1,
                "content": {"text": "Opening text", "prompt": "Write a better intro"},
                "generation_config": {"model": "deepseek-chat"},
            },
        )
        assert create_item_response.status_code == 201
        item = create_item_response.json()
        item_id = item["id"]
        assert item["title"] == "Opening Beat"

        lite_response = await client.get(
            f"/api/v1/canvas-documents/{canvas_id}",
            headers=auth_headers,
            params={"mode": "lite"},
        )
        assert lite_response.status_code == 200
        lite_snapshot = lite_response.json()
        assert lite_snapshot["document"]["id"] == canvas_id
        assert len(lite_snapshot["items"]) == 1
        assert lite_snapshot["items"][0]["id"] == item_id
        assert "text_preview" in lite_snapshot["items"][0]["content"]
        assert "text" not in lite_snapshot["items"][0]["content"]

        detail_response = await client.get(
            f"/api/v1/canvas-documents/{canvas_id}/items/{item_id}",
            headers=auth_headers,
        )
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["id"] == item_id
        assert detail["content"]["text"] == "Opening text"

        patch_response = await client.patch(
            f"/api/v1/canvas-documents/{canvas_id}/items/{item_id}",
            headers=auth_headers,
            json={
                "title": "Opening Beat v2",
                "content": {"text": "Updated opening text"},
            },
        )
        assert patch_response.status_code == 204

        patched_detail_response = await client.get(
            f"/api/v1/canvas-documents/{canvas_id}/items/{item_id}",
            headers=auth_headers,
        )
        assert patched_detail_response.status_code == 200
        patched = patched_detail_response.json()
        assert patched["title"] == "Opening Beat v2"
        assert patched["content"]["text"] == "Updated opening text"

        delete_response = await client.delete(
            f"/api/v1/canvas-documents/{canvas_id}/items/{item_id}",
            headers=auth_headers,
        )
        assert delete_response.status_code == 204

        after_delete_response = await client.get(
            f"/api/v1/canvas-documents/{canvas_id}",
            headers=auth_headers,
            params={"mode": "lite"},
        )
        assert after_delete_response.status_code == 200
        assert after_delete_response.json()["items"] == []

    @pytest.mark.asyncio
    async def test_connection_crud_and_preview_patch_flow(self, client, auth_headers):
        create_response = await client.post(
            "/api/v1/canvas-documents",
            headers=auth_headers,
            json={"title": "Connection Canvas"},
        )
        assert create_response.status_code == 201
        canvas_id = create_response.json()["id"]

        first_item_response = await client.post(
            f"/api/v1/canvas-documents/{canvas_id}/items",
            headers=auth_headers,
            json={
                "item_type": "image",
                "title": "Reference Image",
                "position_x": 60,
                "position_y": 80,
                "width": 340,
                "height": 280,
                "z_index": 1,
                "content": {
                    "prompt": "White studio desk",
                    "result_image_url": "https://example.com/reference.png",
                },
                "generation_config": {"model": "gpt-image-1"},
            },
        )
        assert first_item_response.status_code == 201
        first_item_id = first_item_response.json()["id"]

        second_item_response = await client.post(
            f"/api/v1/canvas-documents/{canvas_id}/items",
            headers=auth_headers,
            json={
                "item_type": "video",
                "title": "Downstream Video",
                "position_x": 480,
                "position_y": 80,
                "width": 360,
                "height": 300,
                "z_index": 2,
                "content": {
                    "prompt": "Slow push in",
                    "result_video_url": "https://example.com/clip.mp4",
                },
                "generation_config": {"model": "veo_3_1-fast"},
            },
        )
        assert second_item_response.status_code == 201
        second_item_id = second_item_response.json()["id"]

        connection_response = await client.post(
            f"/api/v1/canvas-documents/{canvas_id}/connections",
            headers=auth_headers,
            json={
                "source_item_id": first_item_id,
                "target_item_id": second_item_id,
                "source_handle": "right",
                "target_handle": "left",
            },
        )
        assert connection_response.status_code == 201
        connection = connection_response.json()
        assert connection["source_item_id"] == first_item_id
        assert connection["target_item_id"] == second_item_id

        preview_response = await client.post(
            f"/api/v1/canvas-documents/{canvas_id}/items/previews",
            headers=auth_headers,
            json={"item_ids": [first_item_id, second_item_id]},
        )
        assert preview_response.status_code == 200
        preview_payload = preview_response.json()
        assert len(preview_payload["items"]) == 2
        assert {item["id"] for item in preview_payload["items"]} == {first_item_id, second_item_id}

        delete_response = await client.delete(
            f"/api/v1/canvas-documents/{canvas_id}/connections/{connection['id']}",
            headers=auth_headers,
        )
        assert delete_response.status_code == 204

        snapshot_response = await client.get(
            f"/api/v1/canvas-documents/{canvas_id}",
            headers=auth_headers,
            params={"mode": "lite"},
        )
        assert snapshot_response.status_code == 200
        assert snapshot_response.json()["connections"] == []

    @pytest.mark.asyncio
    async def test_get_canvas_video_task_status(self, client, auth_headers):
        create_response = await client.post(
            "/api/v1/canvas-documents",
            headers=auth_headers,
            json={"title": "Video Task Canvas"},
        )
        assert create_response.status_code == 201
        canvas_id = create_response.json()["id"]

        item_id = "88888888-8888-8888-8888-888888888888"
        save_graph_response = await client.put(
            f"/api/v1/canvas-documents/{canvas_id}/graph",
            headers=auth_headers,
            json={
                "items": [
                    {
                        "id": item_id,
                        "item_type": "video",
                        "title": "Video Generator",
                        "position_x": 0,
                        "position_y": 0,
                        "width": 360,
                        "height": 220,
                        "z_index": 1,
                        "content": {"prompt": "fallback video prompt"},
                        "generation_config": {
                            "api_key_id": "33333333-3333-3333-3333-333333333333",
                            "model": "veo_3_1-fast",
                        },
                    }
                ],
                "connections": [],
            },
        )
        assert save_graph_response.status_code == 200

        with patch("src.api.v1.canvas.dispatch_canvas_video_generation", return_value="task-video-status"):
            generate_response = await client.post(
                f"/api/v1/canvas-items/{item_id}/generate-video",
                headers=auth_headers,
                json={"prompt": "Generate video"},
            )
        assert generate_response.status_code == 200

        generation_id = generate_response.json()["generation_id"]
        storage_client = Mock()
        storage_client.get_presigned_url.side_effect = lambda object_key: f"https://cdn.example.com/{object_key}"

        with (
            patch("src.services.canvas.CanvasGenerationService._resolve_api_key", new_callable=AsyncMock) as resolve_api_key,
            patch("src.services.canvas.VectorEngineProvider.get_task_status", new_callable=AsyncMock) as get_task_status,
            patch("src.services.canvas.VectorEngineProvider.get_video_content", new_callable=AsyncMock) as get_video_content,
            patch("src.api.v1.canvas.get_storage_client", new_callable=AsyncMock, return_value=storage_client),
        ):
            api_key = Mock()
            api_key.provider = "vectorengine"
            api_key.base_url = "https://api.vectorengine.ai/v1"
            api_key.get_api_key.return_value = "test-key"
            resolve_api_key.return_value = api_key
            get_task_status.return_value = {
                "id": "provider-task-1",
                "status": "completed",
                "video_url": "https://example.com/generated.mp4",
            }
            get_video_content.return_value = {}

            with patch("src.services.canvas.CanvasGenerationService._store_remote_video", new_callable=AsyncMock) as store_remote_video:
                store_remote_video.return_value = {
                    "object_key": "uploads/generated-video.mp4",
                    "url": "https://ignored.example.com/generated-video.mp4",
                }
                task_response = await client.get(
                    f"/api/v1/canvas-documents/{canvas_id}/items/{item_id}/video-tasks/{generation_id}",
                    headers=auth_headers,
                )

        assert task_response.status_code == 200
        payload = task_response.json()
        assert payload["task_id"] == generation_id
        assert payload["status"] == "completed"
        assert payload["result_video_url"] == "https://cdn.example.com/uploads/generated-video.mp4"
        assert payload["item"]["content"]["result_video_url"] == "https://cdn.example.com/uploads/generated-video.mp4"
        assert payload["item"]["content"]["result_video_object_key"] == "uploads/generated-video.mp4"

    @pytest.mark.asyncio
    async def test_get_canvas_video_task_status_keeps_task_alive_on_transient_status_fetch_failure(self, client, auth_headers):
        create_response = await client.post(
            "/api/v1/canvas-documents",
            headers=auth_headers,
            json={"title": "Video Task Canvas Retry"},
        )
        assert create_response.status_code == 201
        canvas_id = create_response.json()["id"]

        item_id = "89898989-8989-8989-8989-898989898989"
        save_graph_response = await client.put(
            f"/api/v1/canvas-documents/{canvas_id}/graph",
            headers=auth_headers,
            json={
                "items": [
                    {
                        "id": item_id,
                        "item_type": "video",
                        "title": "Retry Video Generator",
                        "position_x": 0,
                        "position_y": 0,
                        "width": 360,
                        "height": 220,
                        "z_index": 1,
                        "content": {"prompt": "fallback video prompt"},
                        "generation_config": {
                            "api_key_id": "33333333-3333-3333-3333-333333333333",
                            "model": "veo_3_1-fast",
                        },
                    }
                ],
                "connections": [],
            },
        )
        assert save_graph_response.status_code == 200

        with patch("src.api.v1.canvas.dispatch_canvas_video_generation", return_value="task-video-retry"):
            generate_response = await client.post(
                f"/api/v1/canvas-items/{item_id}/generate-video",
                headers=auth_headers,
                json={"prompt": "Generate video"},
            )
        assert generate_response.status_code == 200

        generation_id = generate_response.json()["generation_id"]
        storage_client = Mock()
        storage_client.get_presigned_url.side_effect = lambda object_key: f"https://cdn.example.com/{object_key}"

        with (
            patch("src.services.canvas.CanvasGenerationService._resolve_api_key", new_callable=AsyncMock) as resolve_api_key,
            patch("src.services.canvas.VectorEngineProvider.get_task_status", new_callable=AsyncMock, side_effect=RuntimeError("temporary status failure")),
            patch("src.api.v1.canvas.get_storage_client", new_callable=AsyncMock, return_value=storage_client),
        ):
            api_key = Mock()
            api_key.provider = "vectorengine"
            api_key.base_url = "https://api.vectorengine.ai/v1"
            api_key.get_api_key.return_value = "test-key"
            resolve_api_key.return_value = api_key
            task_response = await client.get(
                f"/api/v1/canvas-documents/{canvas_id}/items/{item_id}/video-tasks/{generation_id}",
                headers=auth_headers,
            )

        assert task_response.status_code == 200
        payload = task_response.json()
        assert payload["task_id"] == generation_id
        assert payload["status"] == "pending"
        assert payload["provider_payload"]["transient_status_issue"] is True
        assert "temporary status failure" in payload["provider_payload"]["status_fetch_error"]
        assert payload["item"]["last_run_status"] == "pending"

    @pytest.mark.asyncio
    async def test_process_video_generation_keeps_waiting_after_transient_status_failures(self, client, auth_headers):
        create_response = await client.post(
            "/api/v1/canvas-documents",
            headers=auth_headers,
            json={"title": "Video Task Canvas Worker"},
        )
        assert create_response.status_code == 201
        canvas_id = create_response.json()["id"]

        item_id = "90909090-9090-9090-9090-909090909090"
        save_graph_response = await client.put(
            f"/api/v1/canvas-documents/{canvas_id}/graph",
            headers=auth_headers,
            json={
                "items": [
                    {
                        "id": item_id,
                        "item_type": "video",
                        "title": "Worker Video Generator",
                        "position_x": 0,
                        "position_y": 0,
                        "width": 360,
                        "height": 220,
                        "z_index": 1,
                        "content": {"prompt": "fallback video prompt"},
                        "generation_config": {
                            "api_key_id": "33333333-3333-3333-3333-333333333333",
                            "model": "veo_3_1-fast",
                        },
                    }
                ],
                "connections": [],
            },
        )
        assert save_graph_response.status_code == 200

        with patch("src.api.v1.canvas.dispatch_canvas_video_generation", return_value="task-video-worker"):
            generate_response = await client.post(
                f"/api/v1/canvas-items/{item_id}/generate-video",
                headers=auth_headers,
                json={"prompt": "Generate video"},
            )
        assert generate_response.status_code == 200

        generation_id = generate_response.json()["generation_id"]

        from src.services.canvas import CanvasGenerationService

        fake_api_key = Mock()
        fake_api_key.provider = "vectorengine"
        fake_api_key.base_url = "https://api.vectorengine.ai/v1"
        fake_api_key.get_api_key.return_value = "test-key"

        provider = Mock()
        provider.create_video = AsyncMock(return_value={"id": "provider-task-1"})
        provider.get_task_status = AsyncMock(side_effect=[
            RuntimeError("temporary status failure 1"),
            RuntimeError("temporary status failure 2"),
            RuntimeError("temporary status failure 3"),
            RuntimeError("temporary status failure 4"),
            RuntimeError("temporary status failure 5"),
            RuntimeError("temporary status failure 6"),
            {"status": "processing"},
            {"status": "completed", "video_url": "https://example.com/generated.mp4"},
        ])
        provider.get_video_content = AsyncMock()

        async with TestSessionLocal() as session:
            service = CanvasGenerationService(session)
            with (
                patch.object(service, "_resolve_api_key", AsyncMock(return_value=fake_api_key)),
                patch("src.services.canvas.VectorEngineProvider", return_value=provider),
                patch("src.services.canvas.asyncio.sleep", new_callable=AsyncMock, return_value=None),
                patch.object(
                    service,
                    "_store_remote_video",
                    AsyncMock(return_value={"object_key": "uploads/generated.mp4", "url": "https://ignored.example.com/generated.mp4"}),
                ),
            ):
                result = await service.process_video_generation(generation_id)

            await session.commit()

        assert result["status"] == "completed"

        async with TestSessionLocal() as session:
            from src.services.canvas import CanvasService

            canvas_service = CanvasService(session)
            generation = await canvas_service.get_generation(generation_id)
            assert generation.status == "completed"
            assert generation.result_payload_json["result_video_object_key"] == "uploads/generated.mp4"

    @pytest.mark.asyncio
    async def test_upload_canvas_video_override(self, client, auth_headers):
        create_response = await client.post(
            "/api/v1/canvas-documents",
            headers=auth_headers,
            json={"title": "Upload Video Canvas"},
        )
        assert create_response.status_code == 201
        canvas_id = create_response.json()["id"]

        item_id = "99999999-9999-9999-9999-999999999999"
        save_graph_response = await client.put(
            f"/api/v1/canvas-documents/{canvas_id}/graph",
            headers=auth_headers,
            json={
                "items": [
                    {
                        "id": item_id,
                        "item_type": "video",
                        "title": "Manual Video",
                        "position_x": 0,
                        "position_y": 0,
                        "width": 360,
                        "height": 220,
                        "z_index": 1,
                        "content": {"prompt": "manual video"},
                        "generation_config": {},
                    }
                ],
                "connections": [],
            },
        )
        assert save_graph_response.status_code == 200

        with (
            patch("src.services.canvas.get_storage_client", new_callable=AsyncMock) as get_storage_client,
            patch("src.api.v1.canvas.get_storage_client", new_callable=AsyncMock) as api_get_storage_client,
        ):
            storage_client = Mock()
            storage_client.upload_file = AsyncMock(return_value={
                "bucket": "test",
                "object_key": "uploads/manual-video.mp4",
                "size": 4,
                "etag": "etag-1",
                "url": "https://example.com/manual-video.mp4",
            })
            storage_client.get_presigned_url.return_value = "https://cdn.example.com/uploads/manual-video.mp4"
            get_storage_client.return_value = storage_client
            api_get_storage_client.return_value = storage_client
            upload_response = await client.post(
                f"/api/v1/canvas-documents/{canvas_id}/items/{item_id}/upload-video",
                headers=auth_headers,
                files={"file": ("manual.mp4", b"test", "video/mp4")},
            )

        assert upload_response.status_code == 200
        payload = upload_response.json()
        assert payload["item"]["content"]["result_video_url"] == "https://cdn.example.com/uploads/manual-video.mp4"
        assert payload["item"]["content"]["result_video_object_key"] == "uploads/manual-video.mp4"
        assert payload["status"] == "completed"
