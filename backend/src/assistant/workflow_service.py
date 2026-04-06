from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.assistant.serialization import to_jsonable
from src.assistant.workflow_prompts import (
    build_prepare_workflow_character_prompt,
    build_prepare_workflow_script_prompt,
    build_prepare_workflow_storyboard_prompt,
)
from src.services.api_key import APIKeyService
from src.services.canvas import CanvasGenerationService, CanvasService
from src.services.provider.factory import ProviderFactory


WORKFLOW_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "script": ("idea", "script_type", "style_id", "language", "duration_target", "shot_duration_seconds"),
}

STAGE_LABELS = {
    "script": "剧本",
    "character_views": "角色三视图",
    "prep_nodes": "预备节点",
    "keyframes": "关键帧",
    "video": "视频",
}


@dataclass
class WorkflowItemBuckets:
    scripts: list[Any]
    characters: list[Any]
    storyboards: list[Any]
    keyframes: list[Any]
    videos: list[Any]


def _string(value: Any) -> str:
    return str(value or "").strip()


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _normalize_model_response_text(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content.strip()
    if isinstance(response, dict):
        choices = response.get("choices") or []
        if choices:
            content = ((choices[0] or {}).get("message") or {}).get("content")
            if isinstance(content, str):
                return content.strip()
    return str(response or "").strip()


def _extract_json_payload(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model response does not contain json object")
    return json.loads(text[start : end + 1])


def _tool_effect(*, mutated: bool = False, summary: str = "", **kwargs: Any) -> dict[str, Any]:
    return {
        "mutated": mutated,
        "created_item_ids": list(kwargs.get("created_item_ids") or []),
        "updated_item_ids": list(kwargs.get("updated_item_ids") or []),
        "deleted_item_ids": list(kwargs.get("deleted_item_ids") or []),
        "created_connection_ids": list(kwargs.get("created_connection_ids") or []),
        "deleted_connection_ids": list(kwargs.get("deleted_connection_ids") or []),
        "submitted_task_ids": list(kwargs.get("submitted_task_ids") or []),
        "summary": summary,
    }


class CanvasAssistantWorkflowService:
    def __init__(
        self,
        *,
        canvas_service: CanvasService,
        generation_service: CanvasGenerationService,
        api_key_service: APIKeyService,
        provider_factory: Any = ProviderFactory,
        dispatch_text: Any | None = None,
        dispatch_image: Any | None = None,
        dispatch_video: Any | None = None,
    ) -> None:
        self.canvas_service = canvas_service
        self.generation_service = generation_service
        self.api_key_service = api_key_service
        self.provider_factory = provider_factory
        self.dispatch_text = dispatch_text
        self.dispatch_image = dispatch_image
        self.dispatch_video = dispatch_video

    async def get_workflow_status(self, document_id: str, user_id: str) -> dict[str, Any]:
        graph = await self.canvas_service.get_graph(document_id, user_id)
        buckets = self._bucket_items(list(graph.get("items") or []))
        recommended_stage = "script"
        if buckets.scripts and not buckets.characters:
            recommended_stage = "character_views"
        elif buckets.characters and not buckets.storyboards:
            recommended_stage = "prep_nodes"
        elif buckets.storyboards and not buckets.keyframes:
            recommended_stage = "keyframes"
        elif buckets.keyframes and not buckets.videos:
            recommended_stage = "video"
        elif buckets.videos:
            recommended_stage = "video"
        return {
            "ok": True,
            "summary": "已读取当前工作流状态。",
            "effect": _tool_effect(summary="已读取当前工作流状态。"),
            "status": {
                "script_count": len(buckets.scripts),
                "character_view_count": len(buckets.characters),
                "storyboard_count": len(buckets.storyboards),
                "keyframe_count": len(buckets.keyframes),
                "video_count": len(buckets.videos),
                "recommended_stage": recommended_stage,
            },
        }

    async def prepare_script(
        self,
        *,
        document_id: str,
        user_id: str,
        api_key_id: str,
        chat_model_id: str,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        graph = await self.canvas_service.get_graph(document_id, user_id)
        buckets = self._bucket_items(list(graph.get("items") or []))
        normalized = self._normalize_script_input(input_data)
        if buckets.scripts and not _string(normalized.get("script_item_id")):
            latest_script = buckets.scripts[-1]
            return await self.prepare_workflow_from_script(
                document_id=document_id,
                user_id=user_id,
                api_key_id=api_key_id,
                chat_model_id=chat_model_id,
                script_item_id=str(getattr(latest_script, "id", "")),
            )
        missing_fields = [field for field in WORKFLOW_REQUIRED_FIELDS["script"] if not normalized.get(field)]
        if missing_fields:
            field_labels = {
                "idea": "故事创意/梗概",
                "script_type": "脚本类型",
                "style_id": "视觉风格",
                "language": "输出语言",
                "duration_target": "目标总时长",
                "shot_duration_seconds": "单镜头秒数",
            }
            readable = "、".join(field_labels.get(field, field) for field in missing_fields)
            return {
                "ok": False,
                "summary": f"缺少必要信息：{readable}。",
                "effect": _tool_effect(summary=f"缺少必要信息：{readable}。"),
                "missing_fields": missing_fields,
                "message": f"要开始生成剧本，还缺少：{readable}。请先补齐这些信息，我再继续。",
            }

        provider = await self._build_provider(api_key_id, user_id)
        prompt = build_prepare_workflow_script_prompt(normalized)
        response = await provider.completions(
            model=chat_model_id,
            messages=[
                {"role": "system", "content": "你是电影编剧与预制作统筹，只输出最终剧本文本。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
        )
        script_text = _normalize_model_response_text(response)
        title = _string(normalized.get("title")) or "剧本"
        script_item_id = _string(normalized.get("script_item_id"))
        payload = {
            "title": title,
            "item_type": "text",
            "content": {
                "text": script_text,
                "draft_text": script_text,
                "text_preview": script_text,
                "draft_prompt": prompt,
                "workflow_kind": "script",
                "workflow_step": "script",
                "workflow_source": "assistant",
                "idea": normalized["idea"],
                "script_type": normalized["script_type"],
                "style_id": normalized["style_id"],
                "dialogue_mode": normalized.get("dialogue_mode") or "sparse",
                "language": normalized["language"],
                "duration_target": normalized["duration_target"],
                "shot_duration_seconds": normalized["shot_duration_seconds"],
                "tone": normalized.get("tone") or "",
                "constraints": list(normalized.get("constraints") or []),
                "creative_spec": dict(normalized.get("creative_spec") or {}),
            },
        }
        if script_item_id:
            item = await self.canvas_service.update_item(document_id, script_item_id, user_id, payload)
            created_item_ids: list[str] = []
            updated_item_ids = [str(item.id)]
        else:
            payload.update({"position_x": 0, "position_y": 0, "width": 320, "height": 220, "z_index": 0})
            item = await self.canvas_service.create_item(document_id, user_id, payload)
            created_item_ids = [str(item.id)]
            updated_item_ids = []
        await self.canvas_service.commit()
        return {
            "ok": True,
            "summary": "已生成剧本，请先确认剧本内容，再继续生成角色和分镜。",
            "effect": _tool_effect(
                mutated=True,
                summary="已生成剧本，请先确认剧本内容，再继续生成角色和分镜。",
                created_item_ids=created_item_ids,
                updated_item_ids=updated_item_ids,
            ),
            "item": self._serialize_item(item),
            "message": "已生成剧本，请先确认剧本内容，再继续生成角色和分镜。",
        }

    async def prepare_workflow_from_script(
        self,
        *,
        document_id: str,
        user_id: str,
        api_key_id: str,
        chat_model_id: str,
        script_item_id: str,
    ) -> dict[str, Any]:
        script_item = await self.canvas_service.get_item(script_item_id, user_id)
        script_content = _json_object(getattr(script_item, "content_json", {}) or {})
        script_text = _string(script_content.get("text") or script_content.get("draft_prompt"))
        if not script_text:
            return {
                "ok": False,
                "summary": "剧本节点缺少文本内容。",
                "effect": _tool_effect(summary="剧本节点缺少文本内容。"),
                "message": "当前剧本节点没有可用文本，请先生成或补全剧本内容。",
            }

        provider = await self._build_provider(api_key_id, user_id)
        base_context = {
            "script_text": script_text,
            "script_type": _string(script_content.get("script_type")),
            "style_id": _string(script_content.get("style_id")),
            "tone": _string(script_content.get("tone")),
            "constraints": list(script_content.get("constraints") or []),
            "creative_spec": dict(script_content.get("creative_spec") or {}),
        }
        character_prompt = build_prepare_workflow_character_prompt(base_context)
        character_response = await provider.completions(
            model=chat_model_id,
            messages=[
                {"role": "system", "content": "你是角色设定师，只输出符合约束的 JSON。"},
                {"role": "user", "content": character_prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        characters_payload = _extract_json_payload(_normalize_model_response_text(character_response))
        characters = [entry for entry in list(characters_payload.get("characters") or []) if isinstance(entry, dict)]

        character_summaries: list[str] = []
        character_names: list[str] = []
        for character in characters:
            name = _string(character.get("name"))
            if name:
                character_names.append(name)
            summary_parts = [name, _string(character.get("role_description")), _string(character.get("visual_traits"))]
            character_summaries.append("：".join(part for part in summary_parts if part))

        storyboard_prompt = build_prepare_workflow_storyboard_prompt(
            {
                **base_context,
                "granularity": "详细",
                "shot_duration_seconds": int(script_content.get("shot_duration_seconds") or 5),
                "character_names": character_names,
                "character_summaries": character_summaries,
            }
        )
        storyboard_response = await provider.completions(
            model=chat_model_id,
            messages=[
                {"role": "system", "content": "你是分镜设计师，只输出符合约束的 JSON。"},
                {"role": "user", "content": storyboard_prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        storyboard_payload = _extract_json_payload(_normalize_model_response_text(storyboard_response))
        scenes = [entry for entry in list(storyboard_payload.get("scenes") or []) if isinstance(entry, dict)]

        created_items: list[Any] = []
        created_connections: list[Any] = []
        character_nodes_by_name: dict[str, Any] = {}
        story_index = 0

        for row, character in enumerate(characters):
            character_name = _string(character.get("name")) or f"角色{row + 1}"
            character_item = await self.canvas_service.create_item(
                document_id,
                user_id,
                {
                    "item_type": "image",
                    "title": f"{character_name} 三视图",
                    "position_x": 420,
                    "position_y": row * 244,
                    "width": 320,
                    "height": 220,
                    "z_index": row + 1,
                        "content": {
                            **to_jsonable(character),
                            "text_preview": _string(character.get("role_description") or character.get("visual_traits")),
                            "prompt": _string(character.get("three_view_prompt")),
                        "draft_prompt": _string(character.get("three_view_prompt")),
                        "workflow_kind": "character_view",
                        "workflow_step": "character_views",
                        "workflow_source": "assistant",
                        "style_id": _string(script_content.get("style_id")),
                        "script_item_id": str(script_item.id),
                    },
                },
            )
            created_items.append(character_item)
            character_nodes_by_name[character_name] = character_item
            created_connections.append(
                await self.canvas_service.create_connection(
                    document_id,
                    user_id,
                    {
                        "source_item_id": str(script_item.id),
                        "target_item_id": str(character_item.id),
                        "source_handle": "right",
                        "target_handle": "left",
                    },
                )
            )

        for scene in scenes:
            scene_index = int(scene.get("order_index") or (story_index + 1))
            scene_name = _string(scene.get("scene")) or f"场景 {scene_index}"
            for shot in [entry for entry in list(scene.get("shots") or []) if isinstance(entry, dict)]:
                story_index += 1
                shot_index = int(shot.get("order_index") or story_index)
                storyboard_title = f"分镜 {scene_index:02d}-{shot_index:02d}"
                storyboard_text = _string(shot.get("storyboard_text") or shot.get("narrative") or scene_name)
                storyboard_item = await self.canvas_service.create_item(
                    document_id,
                    user_id,
                    {
                        "item_type": "text",
                        "title": storyboard_title,
                        "position_x": 840,
                        "position_y": (story_index - 1) * 244,
                        "width": 320,
                        "height": 220,
                        "z_index": 100 + story_index,
                        "content": {
                            "text": storyboard_text,
                            "draft_text": storyboard_text,
                            "text_preview": storyboard_text,
                            "storyboard_text": storyboard_text,
                            "scene": scene_name,
                            "scene_order_index": scene_index,
                            "shot_order_index": shot_index,
                            "narrative": _string(shot.get("narrative")),
                            "characters": list(shot.get("characters") or []),
                            "keyframe_prompt": _string(shot.get("keyframe_prompt")),
                            "video_prompt": _string(shot.get("video_prompt")),
                            "workflow_kind": "storyboard",
                            "workflow_step": "storyboards",
                            "workflow_source": "assistant",
                            "script_item_id": str(script_item.id),
                            "style_id": _string(script_content.get("style_id")),
                        },
                    },
                )
                created_items.append(storyboard_item)
                created_connections.append(
                    await self.canvas_service.create_connection(
                        document_id,
                        user_id,
                        {
                            "source_item_id": str(script_item.id),
                            "target_item_id": str(storyboard_item.id),
                            "source_handle": "right",
                            "target_handle": "left",
                        },
                    )
                )
                resolved_mentions = []
                for name in list(shot.get("characters") or []):
                    character_item = character_nodes_by_name.get(_string(name))
                    if character_item is None:
                        continue
                    created_connections.append(
                        await self.canvas_service.create_connection(
                            document_id,
                            user_id,
                            {
                                "source_item_id": str(character_item.id),
                                "target_item_id": str(storyboard_item.id),
                                "source_handle": "right",
                                "target_handle": "left",
                            },
                        )
                    )
                    resolved_mentions.append(
                        {
                            "mentionId": f"character-{character_item.id}",
                            "nodeId": str(character_item.id),
                            "nodeType": "image",
                            "nodeTitle": _string(getattr(character_item, "title", "")),
                            "status": "pending",
                        }
                    )
                keyframe_prompt = _string(shot.get("keyframe_prompt"))
                keyframe_item = await self.canvas_service.create_item(
                    document_id,
                    user_id,
                    {
                        "item_type": "image",
                        "title": f"{storyboard_title} 关键帧",
                        "position_x": 1260,
                        "position_y": (story_index - 1) * 244,
                        "width": 320,
                        "height": 220,
                        "z_index": 200 + story_index,
                        "content": {
                            "prompt": keyframe_prompt,
                            "draft_prompt": keyframe_prompt,
                            "prompt_plain_text": keyframe_prompt,
                            "resolved_mentions": resolved_mentions,
                            "resolvedMentions": resolved_mentions,
                            "character_image_mentions": resolved_mentions,
                            "characterImageMentions": resolved_mentions,
                            "workflow_kind": "keyframe",
                            "workflow_step": "images",
                            "workflow_source": "assistant",
                            "source_storyboard_item_id": str(storyboard_item.id),
                            "style_id": _string(script_content.get("style_id")),
                        },
                    },
                )
                created_items.append(keyframe_item)
                created_connections.append(
                    await self.canvas_service.create_connection(
                        document_id,
                        user_id,
                        {
                            "source_item_id": str(storyboard_item.id),
                            "target_item_id": str(keyframe_item.id),
                            "source_handle": "right",
                            "target_handle": "left",
                        },
                    )
                )
                for mention in resolved_mentions:
                    created_connections.append(
                        await self.canvas_service.create_connection(
                            document_id,
                            user_id,
                            {
                                "source_item_id": str(mention.get("nodeId") or ""),
                                "target_item_id": str(keyframe_item.id),
                                "source_handle": "right",
                                "target_handle": "left",
                            },
                        )
                    )
                video_prompt = _string(shot.get("video_prompt"))
                video_item = await self.canvas_service.create_item(
                    document_id,
                    user_id,
                    {
                        "item_type": "video",
                        "title": f"{storyboard_title} 视频",
                        "position_x": 1680,
                        "position_y": (story_index - 1) * 244,
                        "width": 320,
                        "height": 220,
                        "z_index": 300 + story_index,
                        "content": {
                            "prompt": video_prompt,
                            "draft_prompt": video_prompt,
                            "prompt_plain_text": video_prompt,
                            "resolved_mentions": [
                                {
                                    "mentionId": f"keyframe-{keyframe_item.id}",
                                    "nodeId": str(keyframe_item.id),
                                    "nodeType": "image",
                                    "nodeTitle": _string(getattr(keyframe_item, "title", "")),
                                    "status": "pending",
                                }
                            ],
                            "resolvedMentions": [
                                {
                                    "mentionId": f"keyframe-{keyframe_item.id}",
                                    "nodeId": str(keyframe_item.id),
                                    "nodeType": "image",
                                    "nodeTitle": _string(getattr(keyframe_item, "title", "")),
                                    "status": "pending",
                                }
                            ],
                            "workflow_kind": "video",
                            "workflow_step": "videos",
                            "workflow_source": "assistant",
                            "source_storyboard_item_id": str(storyboard_item.id),
                            "source_item_id": str(keyframe_item.id),
                            "style_id": _string(script_content.get("style_id")),
                        },
                    },
                )
                created_items.append(video_item)
                created_connections.append(
                    await self.canvas_service.create_connection(
                        document_id,
                        user_id,
                        {
                            "source_item_id": str(keyframe_item.id),
                            "target_item_id": str(video_item.id),
                            "source_handle": "right",
                            "target_handle": "left",
                        },
                    )
                )

        await self.canvas_service.commit()
        return {
            "ok": True,
            "summary": "已基于已确认剧本准备角色三视图、分镜、关键帧和视频占位节点。",
            "effect": _tool_effect(
                mutated=True,
                summary="已基于已确认剧本准备角色三视图、分镜、关键帧和视频占位节点。",
                created_item_ids=[str(item.id) for item in created_items],
                created_connection_ids=[str(connection.id) for connection in created_connections],
            ),
            "items": [self._serialize_item(item) for item in created_items],
            "counts": {
                "character_views": len(characters),
                "storyboards": story_index,
                "keyframes": story_index,
                "videos": story_index,
            },
            "message": "已基于已确认剧本准备角色三视图、分镜、关键帧和视频占位节点。",
        }

    async def generate_character_views(self, *, document_id: str, user_id: str, api_key_id: str, chat_model_id: str, item_ids: list[str] | None = None, model: str = "") -> dict[str, Any]:
        return await self._submit_generation_batch(document_id=document_id, user_id=user_id, api_key_id=api_key_id, chat_model_id=chat_model_id, stage="character_views", item_ids=item_ids, kind="image", model=model)

    async def generate_keyframes(self, *, document_id: str, user_id: str, api_key_id: str, chat_model_id: str, item_ids: list[str] | None = None, model: str = "") -> dict[str, Any]:
        return await self._submit_generation_batch(document_id=document_id, user_id=user_id, api_key_id=api_key_id, chat_model_id=chat_model_id, stage="keyframes", item_ids=item_ids, kind="image", model=model)

    async def generate_videos(self, *, document_id: str, user_id: str, api_key_id: str, chat_model_id: str, item_ids: list[str] | None = None, model: str = "") -> dict[str, Any]:
        return await self._submit_generation_batch(document_id=document_id, user_id=user_id, api_key_id=api_key_id, chat_model_id=chat_model_id, stage="video", item_ids=item_ids, kind="video", model=model)

    async def _submit_generation_batch(self, *, document_id: str, user_id: str, api_key_id: str, chat_model_id: str, stage: str, item_ids: list[str] | None, kind: str, model: str) -> dict[str, Any]:
        graph = await self.canvas_service.get_graph(document_id, user_id)
        buckets = self._bucket_items(list(graph.get("items") or []))
        stage_items = {"character_views": buckets.characters, "keyframes": buckets.keyframes, "video": buckets.videos}.get(stage, [])
        selected_ids = {str(item_id).strip() for item_id in list(item_ids or []) if str(item_id).strip()}
        if selected_ids:
            stage_items = [item for item in stage_items if str(getattr(item, "id", "")) in selected_ids]
        if not stage_items:
            return {
                "ok": False,
                "summary": f"未找到可用于生成{STAGE_LABELS.get(stage, stage)}的节点。",
                "effect": _tool_effect(summary=f"未找到可用于生成{STAGE_LABELS.get(stage, stage)}的节点。"),
                "message": f"当前画布里没有可用于生成{STAGE_LABELS.get(stage, stage)}的节点，请先完成上游阶段。",
            }

        submitted: list[dict[str, Any]] = []
        task_ids: list[str] = []
        for item in stage_items:
            content = _json_object(getattr(item, "content_json", {}) or {})
            prompt = _string(content.get("draft_prompt") or content.get("prompt") or content.get("prompt_plain_text"))
            payload = {"prompt": prompt, "api_key_id": api_key_id, "model": _string(model) or chat_model_id}
            if kind == "video":
                _item, generation = await self.generation_service.prepare_video_generation(str(item.id), user_id, payload)
                task_id = self.dispatch_video(str(generation.id)) if self.dispatch_video else str(generation.id)
            else:
                _item, generation = await self.generation_service.prepare_image_generation(str(item.id), user_id, payload)
                task_id = self.dispatch_image(str(generation.id)) if self.dispatch_image else str(generation.id)
            _item, generation = await self.generation_service.attach_task(str(generation.id), task_id)
            task_ids.append(task_id or str(generation.id))
            submitted.append({"item_id": str(item.id), "generation_id": str(generation.id), "task_id": task_id, "status": "submitted"})
        await self.generation_service.commit()
        label = STAGE_LABELS.get(stage, stage)
        return {
            "ok": True,
            "summary": f"已提交{len(submitted)}个{label}生成任务。",
            "effect": _tool_effect(mutated=True, summary=f"已提交{len(submitted)}个{label}生成任务。", submitted_task_ids=task_ids),
            "submitted": submitted,
            "message": f"已提交{len(submitted)}个{label}生成任务。",
        }

    async def _build_provider(self, api_key_id: str, user_id: str) -> Any:
        api_key = await self.api_key_service.get_api_key_by_id(api_key_id, user_id)
        return self.provider_factory.create(provider=api_key.provider, api_key=api_key.get_api_key(), base_url=api_key.base_url)

    def _normalize_script_input(self, input_data: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(input_data or {})
        normalized["idea"] = _string(normalized.get("idea"))
        normalized["script_type"] = _string(normalized.get("script_type"))
        normalized["style_id"] = _string(normalized.get("style_id"))
        normalized["language"] = _string(normalized.get("language"))
        normalized["duration_target"] = _string(normalized.get("duration_target"))
        normalized["shot_duration_seconds"] = int(normalized.get("shot_duration_seconds") or 0)
        normalized["dialogue_mode"] = _string(normalized.get("dialogue_mode") or "sparse")
        normalized["tone"] = _string(normalized.get("tone"))
        normalized["title"] = _string(normalized.get("title"))
        normalized["script_item_id"] = _string(normalized.get("script_item_id"))
        normalized["constraints"] = [str(value).strip() for value in list(normalized.get("constraints") or []) if str(value).strip()]
        normalized["creative_spec"] = dict(normalized.get("creative_spec") or {})
        return normalized

    def _bucket_items(self, items: list[Any]) -> WorkflowItemBuckets:
        buckets = WorkflowItemBuckets(scripts=[], characters=[], storyboards=[], keyframes=[], videos=[])
        for item in items:
            item_type = _string(getattr(item, "item_type", ""))
            title = _string(getattr(item, "title", ""))
            content = _json_object(getattr(item, "content_json", {}) or {})
            workflow_step = _string(content.get("workflow_step"))
            workflow_kind = _string(content.get("workflow_kind"))
            if workflow_step == "script" or workflow_kind == "script" or (item_type == "text" and title == "剧本"):
                buckets.scripts.append(item)
            elif workflow_step == "character_views" or workflow_kind == "character_view":
                buckets.characters.append(item)
            elif workflow_step in {"storyboards", "prep_nodes"} or workflow_kind == "storyboard":
                buckets.storyboards.append(item)
            elif workflow_step == "images" or workflow_kind == "keyframe":
                buckets.keyframes.append(item)
            elif workflow_step == "videos" or workflow_kind == "video" or item_type == "video":
                buckets.videos.append(item)
        return buckets

    def _serialize_item(self, item: Any) -> dict[str, Any]:
        return {
            "id": str(getattr(item, "id", "")),
            "document_id": str(getattr(item, "document_id", "")),
            "item_type": getattr(item, "item_type", ""),
            "title": getattr(item, "title", ""),
            "position_x": getattr(item, "position_x", 0),
            "position_y": getattr(item, "position_y", 0),
            "width": getattr(item, "width", 0),
            "height": getattr(item, "height", 0),
            "content_json": to_jsonable(getattr(item, "content_json", {}) or {}),
        }
