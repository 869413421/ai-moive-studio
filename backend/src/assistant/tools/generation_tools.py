from __future__ import annotations

from typing import Any, Callable

from src.assistant.types import ToolEffect


DispatchFn = Callable[[str], Any]


class CanvasAssistantGenerationTools:
    def __init__(
        self,
        generation_service: Any | None = None,
        dispatch_text: DispatchFn | None = None,
        dispatch_image: DispatchFn | None = None,
        dispatch_video: DispatchFn | None = None,
    ) -> None:
        self.generation_service = generation_service
        self.dispatch_text = dispatch_text
        self.dispatch_image = dispatch_image
        self.dispatch_video = dispatch_video

    async def _commit_if_possible(self) -> None:
        commit = getattr(self.generation_service, "commit", None)
        if callable(commit):
            await commit()

    async def submit_generation(self, user_id: str, item_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not item_id:
            raise ValueError("generation.submit requires resolved item_id")
        if self.generation_service is None:
            effect = ToolEffect(mutated=True, submitted_task_ids=[f"task-{item_id}"], summary="已提交生成任务。")
            return {"submitted": [{"item_id": item_id, "kind": kind, "task_id": f"task-{item_id}", "status": "submitted"}], "effect": effect}

        normalized_kind = str(kind or "").strip() or "image"
        if normalized_kind == "text":
            _item, generation = await self.generation_service.prepare_text_generation(item_id, user_id, payload)
            task_id = self.dispatch_text(str(generation.id)) if self.dispatch_text else ""
        elif normalized_kind == "video":
            _item, generation = await self.generation_service.prepare_video_generation(item_id, user_id, payload)
            task_id = self.dispatch_video(str(generation.id)) if self.dispatch_video else ""
        else:
            _item, generation = await self.generation_service.prepare_image_generation(item_id, user_id, payload)
            task_id = self.dispatch_image(str(generation.id)) if self.dispatch_image else ""
        _item, generation = await self.generation_service.attach_task(str(generation.id), task_id)
        await self._commit_if_possible()
        effect = ToolEffect(mutated=True, submitted_task_ids=[task_id] if task_id else [str(generation.id)], summary="已提交生成任务。")
        return {
            "submitted": [
                {
                    "item_id": item_id,
                    "kind": normalized_kind,
                    "generation_id": str(generation.id),
                    "task_id": task_id,
                    "status": "submitted",
                }
            ],
            "effect": effect,
        }

    async def read_task_statuses(self, task_ids: list[str]) -> list[dict[str, Any]]:
        # 第一版先返回已知 task_id 摘要；后续可接真实 provider/status 查询。
        return [{"task_id": str(task_id), "status": "submitted"} for task_id in task_ids if str(task_id).strip()]
