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
from src.assistant.workflow_service import CanvasAssistantWorkflowService
from src.assistant.tools.canvas_tools import CanvasAssistantCanvasExecutionTools, CanvasAssistantCanvasInspectionTools
from src.assistant.tools.generation_tools import CanvasAssistantGenerationTools
from src.services.api_key import APIKeyService
from src.services.provider.factory import ProviderFactory

SYSTEM_PROMPT = (
    "你是 Aicon Canvas Agent，一个工作在无限画布中的 AI 视频创作编排助手。"
    "你不是普通聊天助手，你的首要目标是帮助用户在画布上创建、拆分、派生、优化、引用、连接节点。"
    "当前画布只有三种基础节点：text、image、video。"
    "你只能返回 JSON，不要输出 markdown，不要输出多余解释。"
    "如果需要调用工具，返回 {\"kind\":\"tool_call\",\"tool_name\":\"...\",\"args\":{},\"message\":\"\"}。"
    "如果任务已完成或需要澄清，返回 {\"kind\":\"final\",\"message\":\"...\"}。"
    "你在每次响应前都必须先思考：用户想创建哪类节点、是否需要复用已有节点、是否需要引用、是否需要连线、应该输出一个节点还是多个节点。"
    "复杂任务必须先识别节点，再识别引用关系，再识别连线关系，最后再给节点具体内容。"
    "默认优先服务画布操作，而不是泛泛解释。"
    "如果用户目标不明确、缺少必要信息、或当前没有可引用的上游节点，优先澄清，不要伪造上下文。"
    "如果任务是拆分、派生、继续创作，默认保留创作链路：优先为新节点保留对上游节点的引用，并自动建立连线。"
    "如果任务涉及多个节点、多个分镜、多个步骤或批量落图，必须优先使用批量工具，禁止循环多次调用单节点 create/update。"
    "如果任务要求“写到画布上”，完成标准必须是真实发生了画布变更，而不是仅给出一段文字。"
    "如果任务要求“拆成 8 个分镜”，完成标准必须是创建了 8 个节点，不允许用一个总节点替代。"
    "如果需要基于已有剧本、图片、视频继续创作，优先先 inspect 再执行。"
    "generation_submit 只适用于给已有节点提交生成任务，不适用于代替批量拆分落图。"
    "同一个工具调用如果在当前回合失败一次，不要原样重试；你必须换参数、换工具或回到澄清。"
    "删除和破坏性动作属于高风险操作，必须经过人工确认。"
    "常见链路包括：创意/故事→剧本→分镜→图片→视频；角色设定→角色图→镜头图→视频；参考图→提示词→视频提示词→视频。"
    "如果上下文里给出了 workflow.target_stages，你必须把它视为本轮主链路意图，优先围绕这些阶段选择工具与组织输出。"
    "当任务属于视频创作主链路（剧本、预备节点、角色三视图、关键帧、视频）时，优先使用 workflow_* 工具，禁止直接用 canvas_create_item 伪造占位节点。"
    "如果 workflow.parameters 里已经有参数，就视为用户已经确认过，不要重复索取。"
    "如果缺少 workflow_* 工具所需参数，先向用户追问最小缺失信息，不要调用低层画布工具硬创建空节点。"
    "如果 workflow.missing_fields 非空，绝对不要调用 workflow_prepare_script；先告诉用户还缺哪些字段。"
    "当目标涉及剧本、预备节点、角色三视图、关键帧、视频时，优先按阶段推进：先补前置资产，再推进下游生成。"
    "如果用户要求继续执行，或者说“继续”“下一步”“那怎么办”，默认基于现有节点和上次中断前的目标续跑，不要回退到无关阶段。"
    "在生成角色三视图、关键帧、视频前，要优先检查是否已有可复用的角色、参考图、分镜或关键帧节点。"
    "旧系统的刚性规则必须保留：剧本阶段锁定 idea、script_type、style_id、language、duration_target、shot_duration_seconds；角色阶段输出稳定角色名和 three_view_prompt；分镜阶段输出 storyboard_text、keyframe_prompt、video_prompt。"
    "当任务涉及多阶段工作流时，先 inspect/locate，再批量创建或提交生成，最后总结当前已完成阶段和下一阶段。"
)


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


def _normalize_canvas_node_payload(item: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(item or {})
    node_type = str(payload.get("node_type") or payload.get("item_type") or "text").strip() or "text"
    content = payload.get("content")
    if isinstance(content, str):
        content = {"text": content}
    elif not isinstance(content, dict):
        content = {}
    purpose = str(payload.get("purpose") or "").strip()
    if purpose:
        content.setdefault("assistant_purpose", purpose)
    next_step = str(payload.get("next_step") or "").strip()
    if next_step:
        content.setdefault("assistant_next_step", next_step)
    references = payload.get("references")
    if references is not None:
        content["assistant_references"] = list(references or [])
    return {
        "client_id": str(payload.get("client_id") or payload.get("key") or "").strip(),
        "title": str(payload.get("title") or "").strip(),
        "item_type": node_type,
        "node_type": node_type,
        "purpose": purpose,
        "content": content,
        "references": list(payload.get("references") or []),
        "connections": list(payload.get("connections") or []),
        "next_step": next_step,
        "width": payload.get("width", 320),
        "height": payload.get("height", 220),
        "position_x": payload.get("position_x"),
        "position_y": payload.get("position_y"),
        "z_index": payload.get("z_index"),
    }


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
    workflow_summary: dict[str, Any]
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
                "workflow": self.workflow_summary,
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
                    "content": SYSTEM_PROMPT,
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
        workflow_service: CanvasAssistantWorkflowService | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        self.db_session = db_session
        self.inspection_tools = inspection_tools
        self.canvas_execution_tools = canvas_execution_tools
        self.generation_tools = generation_tools
        self.workflow_service = workflow_service
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
            workflow_summary=dict(context.get("workflow") or {}),
            api_key_service=self.api_key_service,
        ).bind_tools(self._build_tools())

    def _build_tools(self) -> list[Any]:
        inspection_tools = self.inspection_tools
        execution_tools = self.canvas_execution_tools
        generation_tools = self.generation_tools
        workflow_service = self.workflow_service

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
        async def workflow_get_status() -> dict[str, Any]:
            """读取当前视频工作流进度。用于判断当前画布是否已有剧本、角色三视图、分镜、关键帧或视频节点，以及下一步推荐做什么。视频创作主链路开始前或续跑前应优先调用。"""
            if workflow_service is None:
                return {
                    "ok": False,
                    "summary": "workflow service unavailable",
                    "effect": {"mutated": False, "needs_refresh": False, "refresh_scopes": [], "side_effects": []},
                }
            conf = _config()
            result = await workflow_service.get_workflow_status(conf["document_id"], conf["user_id"])
            return {
                **to_jsonable(result),
                "display": {"level": "info", "title": "已读取工作流状态", "message": "可继续决定下一阶段"},
                "audit": {"tool_name": "workflow.get_status", "target_ids": [], "risk_level": "low"},
                "error": None,
            }

        @tool
        async def workflow_prepare_script(
            idea: str = "",
            script_type: str = "",
            style_id: str = "",
            language: str = "",
            duration_target: str = "",
            shot_duration_seconds: int = 0,
            dialogue_mode: str = "",
            tone: str = "",
            constraints: list[str] | None = None,
            creative_spec: dict[str, Any] | None = None,
            title: str = "",
            script_item_id: str = "",
        ) -> dict[str, Any]:
            """生成剧本节点。只有在用户已经给出创意、脚本类型、视觉风格、语言、总时长和单镜头秒数时才调用；缺字段时先追问，不要硬创建空白剧本节点。"""
            if workflow_service is None:
                return {
                    "ok": False,
                    "summary": "workflow service unavailable",
                    "effect": {"mutated": False, "needs_refresh": False, "refresh_scopes": [], "side_effects": []},
                }
            conf = _config()
            result = await workflow_service.prepare_script(
                document_id=conf["document_id"],
                user_id=conf["user_id"],
                api_key_id=str(conf.get("api_key_id") or ""),
                chat_model_id=str(conf.get("chat_model_id") or ""),
                input_data={
                    "idea": idea,
                    "script_type": script_type,
                    "style_id": style_id,
                    "language": language,
                    "duration_target": duration_target,
                    "shot_duration_seconds": shot_duration_seconds,
                    "dialogue_mode": dialogue_mode,
                    "tone": tone,
                    "constraints": list(constraints or []),
                    "creative_spec": dict(creative_spec or {}),
                    "title": title,
                    "script_item_id": script_item_id,
                },
            )
            normalized = to_jsonable(result)
            return {
                **normalized,
                "effect": {
                    **dict(normalized.get("effect") or {}),
                    "needs_refresh": bool((normalized.get("effect") or {}).get("mutated")),
                    "refresh_scopes": ["document"] if (normalized.get("effect") or {}).get("mutated") else [],
                    "side_effects": [],
                },
                "display": {"level": "info", "title": "剧本阶段", "message": str(normalized.get("summary") or "")},
                "audit": {
                    "tool_name": "workflow.prepare_script",
                    "target_ids": list((normalized.get("effect") or {}).get("created_item_ids") or []) + list((normalized.get("effect") or {}).get("updated_item_ids") or []),
                    "risk_level": "medium",
                },
                "error": None,
            }

        @tool
        async def workflow_prepare_from_script(script_item_id: str) -> dict[str, Any]:
            """基于已确认剧本继续生成角色三视图、分镜、关键帧和视频占位节点。只在已有剧本节点时调用，不要跳过剧本阶段直接造节点。"""
            if workflow_service is None:
                return {
                    "ok": False,
                    "summary": "workflow service unavailable",
                    "effect": {"mutated": False, "needs_refresh": False, "refresh_scopes": [], "side_effects": []},
                }
            conf = _config()
            result = await workflow_service.prepare_workflow_from_script(
                document_id=conf["document_id"],
                user_id=conf["user_id"],
                api_key_id=str(conf.get("api_key_id") or ""),
                chat_model_id=str(conf.get("chat_model_id") or ""),
                script_item_id=script_item_id,
            )
            normalized = to_jsonable(result)
            return {
                **normalized,
                "effect": {
                    **dict(normalized.get("effect") or {}),
                    "needs_refresh": bool((normalized.get("effect") or {}).get("mutated")),
                    "refresh_scopes": ["document"] if (normalized.get("effect") or {}).get("mutated") else [],
                    "side_effects": [],
                },
                "display": {"level": "info", "title": "工作流预备阶段", "message": str(normalized.get("summary") or "")},
                "audit": {
                    "tool_name": "workflow.prepare_from_script",
                    "target_ids": list((normalized.get("effect") or {}).get("created_item_ids") or []),
                    "risk_level": "medium",
                },
                "error": None,
            }

        @tool
        async def workflow_generate_character_views(item_ids: list[str] | None = None, model: str = "") -> dict[str, Any]:
            """为角色三视图节点批量提交生成任务。只用于 workflow.prepare_from_script 已创建的角色三视图节点。"""
            if workflow_service is None:
                return {
                    "ok": False,
                    "summary": "workflow service unavailable",
                    "effect": {"mutated": False, "needs_refresh": False, "refresh_scopes": [], "side_effects": []},
                }
            conf = _config()
            result = await workflow_service.generate_character_views(
                document_id=conf["document_id"],
                user_id=conf["user_id"],
                api_key_id=str(conf.get("api_key_id") or ""),
                chat_model_id=str(conf.get("chat_model_id") or ""),
                item_ids=item_ids,
                model=model,
            )
            normalized = to_jsonable(result)
            return {
                **normalized,
                "effect": {
                    **dict(normalized.get("effect") or {}),
                    "needs_refresh": bool((normalized.get("effect") or {}).get("submitted_task_ids")),
                    "refresh_scopes": ["document", "generation_history"] if (normalized.get("effect") or {}).get("submitted_task_ids") else [],
                    "side_effects": ["generation_task_submitted"] if (normalized.get("effect") or {}).get("submitted_task_ids") else [],
                },
                "display": {"level": "info", "title": "角色三视图任务", "message": str(normalized.get("summary") or "")},
                "audit": {"tool_name": "workflow.generate_character_views", "target_ids": [], "risk_level": "medium"},
                "error": None,
            }

        @tool
        async def workflow_generate_keyframes(item_ids: list[str] | None = None, model: str = "") -> dict[str, Any]:
            """为关键帧节点批量提交生成任务。只用于 workflow.prepare_from_script 已创建的关键帧节点。"""
            if workflow_service is None:
                return {
                    "ok": False,
                    "summary": "workflow service unavailable",
                    "effect": {"mutated": False, "needs_refresh": False, "refresh_scopes": [], "side_effects": []},
                }
            conf = _config()
            result = await workflow_service.generate_keyframes(
                document_id=conf["document_id"],
                user_id=conf["user_id"],
                api_key_id=str(conf.get("api_key_id") or ""),
                chat_model_id=str(conf.get("chat_model_id") or ""),
                item_ids=item_ids,
                model=model,
            )
            normalized = to_jsonable(result)
            return {
                **normalized,
                "effect": {
                    **dict(normalized.get("effect") or {}),
                    "needs_refresh": bool((normalized.get("effect") or {}).get("submitted_task_ids")),
                    "refresh_scopes": ["document", "generation_history"] if (normalized.get("effect") or {}).get("submitted_task_ids") else [],
                    "side_effects": ["generation_task_submitted"] if (normalized.get("effect") or {}).get("submitted_task_ids") else [],
                },
                "display": {"level": "info", "title": "关键帧任务", "message": str(normalized.get("summary") or "")},
                "audit": {"tool_name": "workflow.generate_keyframes", "target_ids": [], "risk_level": "medium"},
                "error": None,
            }

        @tool
        async def workflow_generate_videos(item_ids: list[str] | None = None, model: str = "") -> dict[str, Any]:
            """为视频节点批量提交生成任务。只用于 workflow.prepare_from_script 已创建的视频节点。"""
            if workflow_service is None:
                return {
                    "ok": False,
                    "summary": "workflow service unavailable",
                    "effect": {"mutated": False, "needs_refresh": False, "refresh_scopes": [], "side_effects": []},
                }
            conf = _config()
            result = await workflow_service.generate_videos(
                document_id=conf["document_id"],
                user_id=conf["user_id"],
                api_key_id=str(conf.get("api_key_id") or ""),
                chat_model_id=str(conf.get("chat_model_id") or ""),
                item_ids=item_ids,
                model=model,
            )
            normalized = to_jsonable(result)
            return {
                **normalized,
                "effect": {
                    **dict(normalized.get("effect") or {}),
                    "needs_refresh": bool((normalized.get("effect") or {}).get("submitted_task_ids")),
                    "refresh_scopes": ["document", "generation_history"] if (normalized.get("effect") or {}).get("submitted_task_ids") else [],
                    "side_effects": ["generation_task_submitted"] if (normalized.get("effect") or {}).get("submitted_task_ids") else [],
                },
                "display": {"level": "info", "title": "视频任务", "message": str(normalized.get("summary") or "")},
                "audit": {"tool_name": "workflow.generate_videos", "target_ids": [], "risk_level": "high"},
                "error": None,
            }

        @tool
        async def canvas_find_items(query: str) -> dict[str, Any]:
            """查找可能匹配用户意图的画布节点。用于定位剧本、角色图、参考图、已有分镜等上游节点。任何需要基于现有节点继续创作、拆分、派生、连接的任务，都应优先先用这个工具定位目标。"""
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
        async def canvas_read_item_detail(item_id: str) -> dict[str, Any]:
            """读取一个节点的详细内容。用于在拆分、派生、改写、继续创作前确认节点内容与类型。找到候选节点后，如果后续操作依赖其正文、prompt、引用信息，应先读取细节。"""
            conf = _config()
            detail = await inspection_tools.read_item_detail(conf["document_id"], conf["user_id"], item_id)
            return {
                "ok": True,
                "summary": f"已读取节点 {item_id} 的详细信息。",
                "effect": {"mutated": False, "needs_refresh": False, "refresh_scopes": [], "side_effects": []},
                "display": {"level": "info", "title": "已读取节点细节", "message": "可继续基于该节点执行拆分或派生"},
                "audit": {"tool_name": "canvas.read_item_detail", "target_ids": [item_id], "risk_level": "low"},
                "error": None,
                "item": detail,
            }

        @tool
        async def canvas_read_neighbors(item_ids: list[str]) -> dict[str, Any]:
            """读取节点的相邻关系。用于判断已有工作流链路、是否需要复用上游节点、以及新增节点应如何连线。复杂关系型任务在落图前可先用它了解邻接结构。"""
            conf = _config()
            detail = await inspection_tools.read_neighbors(conf["document_id"], conf["user_id"], item_ids)
            return {
                "ok": True,
                "summary": "已读取相邻节点与连线关系。",
                "effect": {"mutated": False, "needs_refresh": False, "refresh_scopes": [], "side_effects": []},
                "display": {"level": "info", "title": "已读取邻接关系", "message": "可继续规划引用与连线"},
                "audit": {"tool_name": "canvas.read_neighbors", "target_ids": list(item_ids or []), "risk_level": "low"},
                "error": None,
                **to_jsonable(detail),
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
        async def canvas_create_items(
            items: list[dict[str, Any]],
            layout: dict[str, Any] | None = None,
            source_item_id: str = "",
        ) -> dict[str, Any]:
            """批量创建多个节点，并可自动排布、自动引用上游节点、自动建立连线。多分镜、多步骤、多卡片、多节点落图时必须优先使用这个工具，而不是多次调用 canvas_create_item。若任务来自同一个上游节点（如剧本拆分成多个分镜），请提供 source_item_id。items 中每个节点至少包含 node_type、title、purpose、content，可选 references、connections、next_step。"""
            conf = _config()
            normalized_items = [_normalize_canvas_node_payload(item) for item in list(items or [])]
            raw = await execution_tools.create_items(
                conf["document_id"],
                conf["user_id"],
                normalized_items,
                layout,
                source_item_id,
            )
            normalized = to_jsonable(raw)
            return {
                **normalized,
                "ok": True,
                "summary": str((normalized.get("effect") or {}).get("summary") or "已批量创建节点。"),
                "effect": {
                    **dict(normalized.get("effect") or {}),
                    "needs_refresh": True,
                    "refresh_scopes": ["document"],
                    "side_effects": [],
                },
                "display": {"level": "info", "title": "已批量创建节点", "message": "节点与关系已写入画布"},
                "audit": {
                    "tool_name": "canvas.create_items",
                    "target_ids": list((normalized.get("effect") or {}).get("created_item_ids") or []),
                    "risk_level": "low",
                },
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
        async def canvas_update_items(updates: list[dict[str, Any]]) -> dict[str, Any]:
            """批量更新多个节点。多个节点统一改写、统一风格、统一补全字段时必须优先使用这个工具，而不是循环调用 canvas_update_item。每项更新格式为 {item_id, patch}。"""
            conf = _config()
            raw = await execution_tools.update_items(conf["document_id"], conf["user_id"], updates)
            normalized = to_jsonable(raw)
            return {
                **normalized,
                "ok": True,
                "summary": str((normalized.get("effect") or {}).get("summary") or "已批量更新节点。"),
                "effect": {
                    **dict(normalized.get("effect") or {}),
                    "needs_refresh": True,
                    "refresh_scopes": ["document"],
                    "side_effects": [],
                },
                "display": {"level": "info", "title": "已批量更新节点", "message": "批量修改已写入画布"},
                "audit": {
                    "tool_name": "canvas.update_items",
                    "target_ids": list((normalized.get("effect") or {}).get("updated_item_ids") or []),
                    "risk_level": "low",
                },
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
            workflow_get_status,
            workflow_prepare_script,
            workflow_prepare_from_script,
            workflow_generate_character_views,
            workflow_generate_keyframes,
            workflow_generate_videos,
            canvas_find_items,
            canvas_read_item_detail,
            canvas_read_neighbors,
            canvas_create_item,
            canvas_create_items,
            canvas_update_item,
            canvas_update_items,
            canvas_delete_items,
            generation_submit,
        ]
