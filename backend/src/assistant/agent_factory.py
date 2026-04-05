from __future__ import annotations

import json
from typing import Any, Sequence
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_config
from langgraph.prebuilt import create_react_agent
from langgraph.types import interrupt
from pydantic import ConfigDict, PrivateAttr
from sqlalchemy.ext.asyncio import AsyncSession

from src.assistant.serialization import to_jsonable
from src.assistant.tools.canvas_tools import CanvasAssistantCanvasExecutionTools, CanvasAssistantCanvasInspectionTools
from src.assistant.tools.generation_tools import CanvasAssistantGenerationTools
from src.services.api_key import APIKeyService
from src.services.provider.factory import ProviderFactory


def _normalize_create_item_payload(
    *,
    item: dict[str, Any] | None = None,
    title: str = "",
    item_type: str = "",
    content: Any = None,
    position_x: Any = None,
    position_y: Any = None,
    width: Any = None,
    height: Any = None,
    z_index: Any = None,
    generation_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(item or {})
    if title and not payload.get("title"):
        payload["title"] = title
    if item_type and not payload.get("item_type"):
        payload["item_type"] = item_type
    if content is not None and "content" not in payload:
        payload["content"] = {"text": content} if isinstance(content, str) else content
    if generation_config and "generation_config" not in payload:
        payload["generation_config"] = generation_config
    optional_scalars = {
        "position_x": position_x,
        "position_y": position_y,
        "width": width,
        "height": height,
        "z_index": z_index,
    }
    for key, value in optional_scalars.items():
        if value is not None and key not in payload:
            payload[key] = value
    if not payload.get("item_type"):
        payload["item_type"] = "text"
    if "content" not in payload or payload.get("content") is None:
        payload["content"] = {}
    if not isinstance(payload.get("content"), dict):
        payload["content"] = {"text": str(payload.get("content") or "")}
    return payload


def _normalize_generation_payload(
    *,
    item_id: str = "",
    target_item_id: str = "",
    kind: str = "",
    payload: Any = None,
    prompt: str = "",
    api_key_id: str = "",
    model: str = "",
    options: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    normalized_item_id = str(item_id or target_item_id or "").strip()
    normalized_kind = str(kind or "").strip() or "text"

    if isinstance(payload, dict):
        normalized_payload = dict(payload)
    elif isinstance(payload, str):
        normalized_payload = {"prompt": payload}
    else:
        normalized_payload = {}

    if prompt and not normalized_payload.get("prompt"):
        normalized_payload["prompt"] = prompt
    if api_key_id and not normalized_payload.get("api_key_id"):
        normalized_payload["api_key_id"] = api_key_id
    if model and not normalized_payload.get("model"):
        normalized_payload["model"] = model
    if options and not normalized_payload.get("options"):
        normalized_payload["options"] = options

    return normalized_item_id, normalized_kind, normalized_payload


def _extract_message_content(response: Any) -> str:
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
    return ""


def _extract_json_payload(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model response does not contain json object")
    return json.loads(text[start : end + 1])


def _normalize_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    normalized = []
    for message in messages:
        role = getattr(message, "type", "user")
        if role == "human":
            role = "user"
        elif role == "ai":
            role = "assistant"
        elif role == "tool":
            role = "tool"
        normalized.append(
            {
                "role": role,
                "content": getattr(message, "content", "") or "",
                "tool_call_id": getattr(message, "tool_call_id", ""),
                "name": getattr(message, "name", ""),
            }
        )
    return normalized


class CanvasAssistantToolCallingChatModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    api_key_id: str
    chat_model_id: str
    user_id: str
    document_id: str
    observation_summary: dict[str, Any]
    api_key_service: APIKeyService
    provider_factory: Any = ProviderFactory
    _bound_tools: list[Any] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "canvas-assistant-tool-calling"

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: str | None = None, **kwargs: Any):
        rebound = self.model_copy(deep=False)
        rebound._bound_tools = list(tools)
        return rebound

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        raise NotImplementedError("Use async generation for CanvasAssistantToolCallingChatModel")

    async def _agenerate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        api_key = await self.api_key_service.get_api_key_by_id(self.api_key_id, self.user_id)
        provider = self.provider_factory.create(
            provider=api_key.provider,
            api_key=api_key.get_api_key(),
            base_url=api_key.base_url,
        )
        context_payload = to_jsonable(
            {
                "document_id": self.document_id,
                "observation": self.observation_summary,
            }
        )
        tool_catalog = [
            {
                "name": getattr(tool_item, "name", ""),
                "description": getattr(tool_item, "description", ""),
            }
            for tool_item in self._bound_tools
        ]
        context_payload["tools"] = tool_catalog
        response = await provider.completions(
            model=self.chat_model_id,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是 Aicon Canvas Agent。你只能返回 JSON。"
                        "如果需要调用工具，返回 {\"kind\":\"tool_call\",\"tool_name\":\"...\",\"args\":{},\"message\":\"\"}。"
                        "如果任务已完成，返回 {\"kind\":\"final\",\"message\":\"...\"}。"
                        "如果用户目标不明确、缺少必要信息、或存在多种合理执行方式，优先直接回复澄清问题，不要擅自创建、修改、删除任何节点。"
                        "只有当用户明确要求在画布上执行具体动作，且参数足够明确时，才调用工具。"
                        "删除和破坏性动作在工具层会触发人工确认。"
                    ),
                },
                {
                    "role": "system",
                    "content": json.dumps(context_payload, ensure_ascii=False),
                },
                *_normalize_messages(messages),
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        parsed = _extract_json_payload(_extract_message_content(response))
        kind = str(parsed.get("kind") or "final").strip().lower()
        if kind == "tool_call":
            message = AIMessage(
                content=str(parsed.get("message") or ""),
                tool_calls=[
                    {
                        "id": str(parsed.get("correlation_id") or f"call-{uuid4()}"),
                        "name": str(parsed.get("tool_name") or ""),
                        "args": dict(parsed.get("args") or {}),
                        "type": "tool_call",
                    }
                ],
            )
        else:
            message = AIMessage(content=str(parsed.get("message") or parsed.get("content") or ""))
        return ChatResult(generations=[ChatGeneration(message=message)])


class CanvasAssistantAgentFactory:
    def __init__(
        self,
        db_session: AsyncSession,
        inspection_tools: CanvasAssistantCanvasInspectionTools,
        canvas_execution_tools: CanvasAssistantCanvasExecutionTools,
        generation_tools: CanvasAssistantGenerationTools,
        checkpointer: Any | None = None,
    ) -> None:
        self.db_session = db_session
        self.inspection_tools = inspection_tools
        self.canvas_execution_tools = canvas_execution_tools
        self.generation_tools = generation_tools
        self.api_key_service = APIKeyService(db_session)
        self.checkpointer = checkpointer or InMemorySaver()
        self._graph = None

    async def __call__(self, **_: Any):
        if self._graph is None:
            self._graph = create_react_agent(
                model=self._select_model,
                tools=self._build_tools(),
                checkpointer=self.checkpointer,
                context_schema=dict,
                name="canvas_assistant",
            )
        return self._graph

    async def build_context(
        self,
        document_id: str,
        user_id: str,
        api_key_id: str,
        chat_model_id: str,
    ) -> dict[str, Any]:
        snapshot = await self.inspection_tools.inspect_graph(document_id, user_id)
        return {
            "document_id": document_id,
            "user_id": user_id,
            "api_key_id": api_key_id,
            "chat_model_id": chat_model_id,
            "observation": snapshot,
        }

    def _select_model(self, _state: dict[str, Any], runtime: Any) -> BaseChatModel:
        context = runtime.context or {}
        return CanvasAssistantToolCallingChatModel(
            api_key_id=str(context.get("api_key_id") or ""),
            chat_model_id=str(context.get("chat_model_id") or ""),
            user_id=str(context.get("user_id") or ""),
            document_id=str(context.get("document_id") or ""),
            observation_summary=dict(context.get("observation") or {}),
            api_key_service=self.api_key_service,
        ).bind_tools(self._build_tools())

    def _build_tools(self) -> list[Any]:
        inspection_tools = self.inspection_tools
        execution_tools = self.canvas_execution_tools
        generation_tools = self.generation_tools

        def _config() -> dict[str, Any]:
            return dict(get_config().get("configurable") or {})

        def _interrupt_payload(tool_name: str, args: dict[str, Any], title: str, message: str) -> dict[str, Any]:
            payload = interrupt(
                {
                    "kind": "confirm_execute",
                    "title": title,
                    "message": message,
                    "actions": ["approve", "reject"],
                    "tool_name": tool_name,
                    "args": args,
                }
            )
            if isinstance(payload, dict):
                return payload
            return {"decision": str(payload or "").strip()}

        @tool
        async def canvas_find_items(query: str) -> dict[str, Any]:
            """查找可能匹配用户意图的画布节点。"""
            conf = _config()
            result = await inspection_tools.find_items(conf["document_id"], conf["user_id"], query)
            return {
                "ok": True,
                "summary": f"找到 {len(result)} 个候选节点。",
                "effect": {"mutated": False, "needs_refresh": False, "refresh_scopes": [], "side_effects": []},
                "display": {"level": "info", "title": "已定位候选节点", "message": f"匹配到 {len(result)} 个节点"},
                "audit": {"tool_name": "canvas.find_items", "target_ids": [str(item.get('id') or '') for item in result], "risk_level": "low"},
                "error": None,
                "items": result,
            }

        @tool
        async def canvas_create_item(
            item: dict[str, Any] | None = None,
            title: str = "",
            item_type: str = "",
            content: Any = None,
            position_x: float | int | None = None,
            position_y: float | int | None = None,
            width: float | int | None = None,
            height: float | int | None = None,
            z_index: int | None = None,
            generation_config: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            """在画布上创建一个新节点。"""
            conf = _config()
            payload = _normalize_create_item_payload(
                item=item,
                title=title,
                item_type=item_type,
                content=content,
                position_x=position_x,
                position_y=position_y,
                width=width,
                height=height,
                z_index=z_index,
                generation_config=generation_config,
            )
            raw = await execution_tools.create_item(conf["document_id"], conf["user_id"], payload)
            normalized = to_jsonable(raw)
            return {
                **normalized,
                "ok": True,
                "summary": str((normalized.get("effect") or {}).get("summary") or "已创建节点。"),
                "effect": {
                    **dict(normalized.get("effect") or {}),
                    "needs_refresh": True,
                    "refresh_scopes": ["document"],
                    "side_effects": [],
                },
                "display": {"level": "info", "title": "已创建节点", "message": "画布已新增节点"},
                "audit": {"tool_name": "canvas.create_item", "target_ids": [str((normalized.get('item') or {}).get('id') or '')], "risk_level": "low"},
                "error": None,
            }

        @tool
        async def canvas_update_item(item_id: str, patch: dict[str, Any]) -> dict[str, Any]:
            """更新一个已有节点。"""
            conf = _config()
            raw = await execution_tools.update_item(conf["document_id"], conf["user_id"], item_id, patch)
            normalized = to_jsonable(raw)
            return {
                **normalized,
                "ok": True,
                "summary": str((normalized.get("effect") or {}).get("summary") or "已更新节点。"),
                "effect": {
                    **dict(normalized.get("effect") or {}),
                    "needs_refresh": True,
                    "refresh_scopes": ["document"],
                    "side_effects": [],
                },
                "display": {"level": "info", "title": "已更新节点", "message": "画布节点已更新"},
                "audit": {"tool_name": "canvas.update_item", "target_ids": [item_id], "risk_level": "low"},
                "error": None,
            }

        @tool
        async def canvas_delete_items(item_ids: list[str]) -> dict[str, Any]:
            """删除一个或多个已有节点。"""
            conf = _config()
            approval = _interrupt_payload("canvas.delete_items", {"item_ids": item_ids}, "确认删除节点", "删除后无法恢复，是否继续？")
            if str(approval.get("decision") or "").strip().lower() == "reject":
                return {
                    "ok": False,
                    "summary": "用户取消了删除操作。",
                    "effect": {"mutated": False, "needs_refresh": False, "refresh_scopes": [], "side_effects": []},
                    "display": {"level": "info", "title": "已取消删除", "message": "当前高风险操作已取消"},
                    "audit": {"tool_name": "canvas.delete_items", "target_ids": item_ids, "risk_level": "high"},
                    "error": None,
                }
            raw = await execution_tools.delete_items(conf["document_id"], conf["user_id"], item_ids)
            normalized = to_jsonable(raw)
            return {
                **normalized,
                "ok": True,
                "summary": str((normalized.get("effect") or {}).get("summary") or "已删除节点。"),
                "effect": {
                    **dict(normalized.get("effect") or {}),
                    "needs_refresh": True,
                    "refresh_scopes": ["document"],
                    "side_effects": [],
                },
                "display": {"level": "warning", "title": "已删除节点", "message": "目标节点已从画布移除"},
                "audit": {"tool_name": "canvas.delete_items", "target_ids": item_ids, "risk_level": "high"},
                "error": None,
            }

        @tool
        async def generation_submit(
            item_id: str = "",
            kind: str = "",
            payload: Any = None,
            target_item_id: str = "",
            prompt: str = "",
            api_key_id: str = "",
            model: str = "",
            options: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            """向目标节点提交生成任务。"""
            conf = _config()
            normalized_item_id, normalized_kind, normalized_payload = _normalize_generation_payload(
                item_id=item_id,
                target_item_id=target_item_id,
                kind=kind,
                payload=payload,
                prompt=prompt,
                api_key_id=api_key_id or str(conf.get("api_key_id") or ""),
                model=model or str(conf.get("chat_model_id") or ""),
                options=options,
            )
            raw = await generation_tools.submit_generation(
                conf["user_id"],
                normalized_item_id,
                normalized_kind,
                normalized_payload,
            )
            normalized = to_jsonable(raw)
            return {
                **normalized,
                "ok": True,
                "summary": str((normalized.get("effect") or {}).get("summary") or "已提交生成任务。"),
                "effect": {
                    **dict(normalized.get("effect") or {}),
                    "needs_refresh": True,
                    "refresh_scopes": ["document", "generation_history"],
                    "side_effects": ["generation_task_submitted"],
                },
                "display": {"level": "info", "title": "已提交生成任务", "message": "稍后可在历史记录中查看结果"},
                "audit": {"tool_name": "generation.submit", "target_ids": [normalized_item_id], "risk_level": "medium"},
                "error": None,
            }

        return [
            canvas_find_items,
            canvas_create_item,
            canvas_update_item,
            canvas_delete_items,
            generation_submit,
        ]
