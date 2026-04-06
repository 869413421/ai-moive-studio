from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from langgraph.types import Command

from src.api.schemas.canvas_assistant import CanvasAssistantChatRequest, CanvasAssistantResumeRequest
from src.assistant.serialization import to_jsonable
from src.assistant.session_store import InMemoryCanvasAssistantSessionStore
from src.assistant.tools.canvas_tools import CanvasAssistantCanvasExecutionTools, CanvasAssistantCanvasInspectionTools
from src.assistant.tools.generation_tools import CanvasAssistantGenerationTools
from src.assistant.types import AgentInterrupt, CanvasAgentSession, CanvasAssistantTurnResult


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact_observation_for_session(observation: dict[str, Any]) -> dict[str, Any]:
    canvas = dict(observation.get("canvas") or {})
    items = list(canvas.get("items") or [])
    connections = list(canvas.get("connections") or [])
    return {
        "canvas": {
            "document": dict(canvas.get("document") or {}),
            "counts": dict(canvas.get("counts") or {"items": len(items), "connections": len(connections)}),
            "items": [
                {
                    "id": str(item.get("id") or ""),
                    "title": str(item.get("title") or ""),
                    "item_type": str(item.get("item_type") or ""),
                }
                for item in items[:6]
            ],
            "connections": [
                {
                    "source_item_id": str(connection.get("source_item_id") or ""),
                    "target_item_id": str(connection.get("target_item_id") or ""),
                }
                for connection in connections[:6]
            ],
        },
        "targets": list(observation.get("targets") or [])[:4],
        "last_tool_effect": dict(observation.get("last_tool_effect") or {}),
        "task_statuses": list(observation.get("task_statuses") or [])[:4],
    }


def _normalize_message_content(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(message, dict):
        return str(message.get("content") or "").strip()
    return str(content or "").strip()


def _normalize_message_tool_calls(message: Any) -> list[dict[str, Any]]:
    tool_calls = getattr(message, "tool_calls", None)
    if isinstance(tool_calls, list):
        return [dict(tool_call) for tool_call in tool_calls]
    if isinstance(message, dict):
        return [dict(tool_call) for tool_call in list(message.get("tool_calls") or [])]
    return [] 


WORKFLOW_STAGE_DEFINITIONS = [
    ("script", ("剧本", "脚本")),
    ("prep_nodes", ("预备节点", "准备节点", "分镜", "拆分镜头", "镜头")),
    ("character_views", ("角色三视图", "三视图", "角色图", "角色设定")),
    ("keyframes", ("关键帧", "镜头图", "关键画面")),
    ("video", ("视频", "动画", "转场")),
]

WORKFLOW_STYLE_KEYWORDS = {
    "cinematic": ("沙丘", "imax", "70mm", "胶片感", "长焦", "史诗感", "预告片"),
    "anime-2d": ("日式动画", "二次元", "anime", "动画风"),
    "cyberpunk": ("赛博朋克", "cyberpunk"),
    "documentary": ("纪录片", "documentary"),
    "noir": ("黑色电影", "noir"),
}

WORKFLOW_SCRIPT_TYPE_KEYWORDS = {
    "trailer": ("预告片", "trailer"),
    "short_film": ("短片", "short film", "short_film"),
    "commercial": ("广告", "commercial"),
    "animation": ("动画", "animation"),
    "promotional": ("宣传片", "promotional"),
}

WORKFLOW_REQUIRED_FIELDS_BY_STAGE = {
    "script": ("idea", "script_type", "style_id", "language", "duration_target", "shot_duration_seconds"),
}


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))


def _extract_duration_target(text: str) -> str:
    match = re.search(r"(?P<value>\d+)\s*(秒|s|分钟|min)", str(text or ""), re.IGNORECASE)
    if not match:
        return ""
    value = match.group("value")
    unit = match.group(2).lower()
    return f"{value}min" if unit in {"分钟", "min"} else f"{value}s"


def _extract_shot_duration_seconds(text: str) -> int:
    patterns = [
        r"(?:单镜头|每个镜头|镜头平均时长|平均时长)\D{0,8}(\d+)\s*(?:秒|s)",
        r"(?:镜头)\D{0,8}(\d+)\s*(?:秒|s)",
    ]
    for pattern in patterns:
        match = re.search(pattern, str(text or ""), re.IGNORECASE)
        if match:
            return int(match.group(1))
    return 0


def _extract_workflow_draft(conversation: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    draft: dict[str, Any] = {
        "idea": "",
        "script_type": "",
        "style_id": "",
        "language": "",
        "duration_target": "",
        "shot_duration_seconds": 0,
        "dialogue_mode": "",
        "tone": "",
        "constraints": [],
        "creative_spec": {},
    }
    for message in list(conversation or []):
        if str(message.get("role") or "").strip() != "user":
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        lowered = content.lower()
        if not draft["idea"] and len(content) >= 12 and not any(token in content for token in ("你好", "怎么办", "帮我", "继续", "生成剧本")):
            draft["idea"] = content
        for script_type, keywords in WORKFLOW_SCRIPT_TYPE_KEYWORDS.items():
            if not draft["script_type"] and any(keyword in lowered or keyword in content for keyword in keywords):
                draft["script_type"] = script_type
                break
        for style_id, keywords in WORKFLOW_STYLE_KEYWORDS.items():
            if not draft["style_id"] and any(keyword in lowered or keyword in content for keyword in keywords):
                draft["style_id"] = style_id
                break
        if not draft["language"]:
            if "英文" in content:
                draft["language"] = "英文"
            elif "日文" in content or "日语" in content:
                draft["language"] = "日文"
            elif _contains_cjk(content):
                draft["language"] = "中文"
        if not draft["duration_target"]:
            draft["duration_target"] = _extract_duration_target(content) or draft["duration_target"]
        if not draft["shot_duration_seconds"]:
            draft["shot_duration_seconds"] = _extract_shot_duration_seconds(content) or draft["shot_duration_seconds"]
    return draft


def _infer_workflow_stages(goal: str, observation: dict[str, Any] | None = None) -> list[str]:
    normalized = str(goal or "").strip()
    if not normalized:
        return []
    detected = [stage for stage, keywords in WORKFLOW_STAGE_DEFINITIONS if any(keyword in normalized for keyword in keywords)]
    if detected:
        return detected
    items = list(((observation or {}).get("canvas") or {}).get("items") or [])
    item_titles = " ".join(str(item.get("title") or "") for item in items[:12])
    item_types = " ".join(str(item.get("item_type") or "") for item in items[:12])
    fallback = []
    if "剧本" in item_titles or "script" in item_types.lower():
        fallback.append("prep_nodes")
    if "角色" in item_titles:
        fallback.append("character_views")
    if "image" in item_types.lower():
        fallback.append("video")
    return fallback


def _build_workflow_context(
    goal: str,
    observation: dict[str, Any] | None = None,
    *,
    workflow_draft: dict[str, Any] | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    stages = _infer_workflow_stages(goal, observation)
    if not stages:
        stages = ["script"] if "生成" in str(goal or "") else []
    normalized_draft = dict(workflow_draft or {})
    missing_fields: list[str] = []
    if stages:
        for stage in stages:
            required_fields = WORKFLOW_REQUIRED_FIELDS_BY_STAGE.get(stage) or ()
            if required_fields:
                missing_fields = [field for field in required_fields if not normalized_draft.get(field)]
                break
    summary_parts: list[str] = []
    stage_labels = {
        "script": "剧本",
        "prep_nodes": "预备节点",
        "character_views": "角色三视图",
        "keyframes": "关键帧",
        "video": "视频",
    }
    if stages:
        summary_parts.append(" → ".join(stage_labels.get(stage, stage) for stage in stages))
    if missing_fields:
        summary_parts.append("待补参数：" + "、".join(missing_fields))
    if resume:
        summary_parts.append("继续执行已确认步骤")
    return {
        "target_stages": stages,
        "summary": "；".join(summary_parts) if summary_parts else "",
        "parameters": normalized_draft,
        "missing_fields": missing_fields,
        "resume": resume,
    }


def _build_thinking_delta(workflow: dict[str, Any], *, resume: bool = False) -> str:
    stages = list(workflow.get("target_stages") or [])
    missing_fields = list(workflow.get("missing_fields") or [])
    if not stages:
        return "已收到确认，继续执行当前步骤。" if resume else "先检查当前画布上下文，再决定下一步。"
    stage_labels = {
        "script": "剧本",
        "prep_nodes": "预备节点",
        "character_views": "角色三视图",
        "keyframes": "关键帧",
        "video": "视频",
    }
    chain = " → ".join(stage_labels.get(stage, stage) for stage in stages)
    if missing_fields:
        return f"先补齐必要参数：{'、'.join(missing_fields)}，再推进{chain}。"
    if resume:
        return f"已收到确认，继续执行：{chain}。"
    return f"先规划工作流：{chain}。"


def _normalize_tool_message(message: Any) -> tuple[str, str, Any]:
    tool_call_id = str(getattr(message, "tool_call_id", "") or (message.get("tool_call_id") if isinstance(message, dict) else "") or "").strip()
    tool_name = str(getattr(message, "name", "") or (message.get("name") if isinstance(message, dict) else "") or "").strip()
    content = getattr(message, "content", None)
    if isinstance(message, dict):
        content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
        if not text:
            return tool_call_id, tool_name, {}
        try:
            return tool_call_id, tool_name, json.loads(text)
        except Exception:
            return tool_call_id, tool_name, {"content": text}
    if content is None:
        return tool_call_id, tool_name, {}
    return tool_call_id, tool_name, to_jsonable(content)


def _tool_signature(tool_name: str, args: Any) -> str:
    normalized_args = to_jsonable(args or {})
    return f"{str(tool_name or '').strip()}::{json.dumps(normalized_args, ensure_ascii=False, sort_keys=True)}"


def _is_tool_failure(result: Any) -> bool:
    if isinstance(result, dict):
        if result.get("ok") is False:
            return True
        if result.get("error"):
            return True
        content = str(result.get("content") or "").strip()
        if content.lower().startswith("error invoking tool"):
            return True
    if isinstance(result, str):
        return result.strip().lower().startswith("error invoking tool")
    return False


def _goal_requires_canvas_mutation(goal: str) -> bool:
    normalized = str(goal or "").strip()
    if not normalized:
        return False
    keywords = ("写到画布", "写入画布", "创建", "新建", "拆成", "拆分", "生成", "节点", "分镜")
    return any(keyword in normalized for keyword in keywords)


def _message_claims_canvas_success(message: str) -> bool:
    normalized = str(message or "").strip()
    if not normalized:
        return False
    keywords = ("已在画布", "已创建", "已写入", "已生成", "已新增", "已拆成")
    return any(keyword in normalized for keyword in keywords)


class CanvasAssistantService:
    def __init__(
        self,
        session_store: Any | None = None,
        inspection_tools: Any | None = None,
        canvas_execution_tools: Any | None = None,
        generation_tools: Any | None = None,
        agent_factory: Any | None = None,
    ) -> None:
        if agent_factory is None:
            raise ValueError("CanvasAssistantService requires an official agent_factory")
        self.session_store = session_store or InMemoryCanvasAssistantSessionStore()
        self.inspection_tools = inspection_tools or CanvasAssistantCanvasInspectionTools()
        self.canvas_execution_tools = canvas_execution_tools or CanvasAssistantCanvasExecutionTools()
        self.generation_tools = generation_tools or CanvasAssistantGenerationTools()
        self.agent_factory = agent_factory

    async def chat(self, request: CanvasAssistantChatRequest, user_id: str) -> CanvasAssistantTurnResult:
        session_id = request.session_id or str(uuid4())
        session = await self.session_store.get_or_create(session_id, user_id, request.document_id)
        session.user_goal = request.message if not session.user_goal else session.user_goal
        session.conversation.append({"role": "user", "content": request.message})
        workflow_draft = _extract_workflow_draft(session.conversation)
        graph = await self.agent_factory(
            document_id=request.document_id,
            user_id=user_id,
            api_key_id=request.api_key_id or "",
            chat_model_id=request.chat_model_id or "",
            session_id=session.session_id,
        )
        consumed = await self._consume_agent_stream(
            graph=graph,
            payload={"messages": [{"role": "user", "content": request.message}]},
            context=await self._build_agent_context(
                request.document_id,
                user_id,
                request.api_key_id or "",
                request.chat_model_id or "",
                request.message,
                workflow_draft=workflow_draft,
            ),
            config=self._build_config(
                session_id=session.session_id,
                document_id=request.document_id,
                user_id=user_id,
                api_key_id=request.api_key_id or "",
                chat_model_id=request.chat_model_id or "",
            ),
            session_id=session.session_id,
        )
        return await self._finalize_session(session, consumed)

    async def resume(self, request: CanvasAssistantResumeRequest, user_id: str) -> CanvasAssistantTurnResult:
        session = await self.session_store.begin_resume(
            request.session_id,
            user_id,
            request.document_id,
            request.interrupt_id,
        )
        graph = await self.agent_factory(
            document_id=request.document_id,
            user_id=user_id,
            api_key_id=session.graph_state.get("api_key_id", ""),
            chat_model_id=session.graph_state.get("chat_model_id", ""),
            session_id=session.session_id,
        )
        consumed = await self._consume_agent_stream(
            graph=graph,
            payload=Command(
                resume={
                    "decision": request.decision,
                    "selected_model_id": request.selected_model_id or "",
                }
            ),
            context=await self._build_agent_context(
                request.document_id,
                user_id,
                session.graph_state.get("api_key_id", ""),
                session.graph_state.get("chat_model_id", ""),
                session.user_goal or (session.conversation[-1]["content"] if session.conversation else ""),
                workflow_draft=dict(session.graph_state.get("workflow_draft") or _extract_workflow_draft(session.conversation)),
                resume=True,
            ),
            config=self._build_config(
                session_id=session.session_id,
                document_id=request.document_id,
                user_id=user_id,
                api_key_id=session.graph_state.get("api_key_id", ""),
                chat_model_id=session.graph_state.get("chat_model_id", ""),
            ),
            session_id=session.session_id,
            resume_decision=request.decision,
            resume_interrupt_id=request.interrupt_id,
        )
        return await self._finalize_session(session, consumed)

    async def _build_agent_context(
        self,
        document_id: str,
        user_id: str,
        api_key_id: str,
        chat_model_id: str,
        user_goal: str = "",
        workflow_draft: dict[str, Any] | None = None,
        resume: bool = False,
    ) -> dict[str, Any]:
        snapshot = await self.inspection_tools.inspect_graph(document_id, user_id)
        observation = _compact_observation_for_session({"canvas": snapshot})
        return {
            "document_id": document_id,
            "user_id": user_id,
            "api_key_id": api_key_id,
            "chat_model_id": chat_model_id,
            "observation": observation,
            "workflow": _build_workflow_context(user_goal, observation, workflow_draft=workflow_draft, resume=resume),
        }

    def _build_config(
        self,
        *,
        session_id: str,
        document_id: str,
        user_id: str,
        api_key_id: str,
        chat_model_id: str,
    ) -> dict[str, Any]:
        return {
            "configurable": {
                "thread_id": session_id,
                "session_id": session_id,
                "document_id": document_id,
                "user_id": user_id,
                "api_key_id": api_key_id,
                "chat_model_id": chat_model_id,
            },
            "recursion_limit": 12,
        }

    async def _consume_agent_stream(
        self,
        *,
        graph: Any,
        payload: Any,
        context: dict[str, Any] | None,
        config: dict[str, Any],
        session_id: str,
        resume_decision: str = "",
        resume_interrupt_id: str = "",
    ) -> dict[str, Any]:
        run_id = f"run-{uuid4()}"
        sequence = 0
        events: list[dict[str, Any]] = []
        final_message = ""
        pending_interrupt: AgentInterrupt | None = None
        tool_history: list[dict[str, Any]] = []
        last_failed_message = ""
        call_signatures: dict[str, str] = {}
        failed_signatures: set[str] = set()

        def emit(event_type: str, payload_data: dict[str, Any], correlation_id: str = "") -> None:
            nonlocal sequence
            sequence += 1
            normalized_payload = to_jsonable(payload_data)
            data = {
                **dict(normalized_payload or {}),
                "event_id": f"{session_id}-{sequence}",
                "session_id": session_id,
                "thread_id": session_id,
                "run_id": run_id,
                "timestamp": _utc_now_iso(),
                "sequence": sequence,
                "correlation_id": str(correlation_id or dict(normalized_payload or {}).get("correlation_id") or ""),
            }
            events.append({"type": event_type, "data": data})

        emit("agent.session.started", {"session_id": session_id})
        workflow = dict(context.get("workflow") or {}) if isinstance(context, dict) else {}
        thinking_delta = _build_thinking_delta(workflow, resume=bool(resume_decision))
        if resume_decision:
            emit(
                "agent.interrupt.resolved",
                {"interrupt_id": resume_interrupt_id, "decision": resume_decision},
                correlation_id=resume_interrupt_id,
            )
        if thinking_delta:
            emit("agent.thinking.delta", {"delta": thinking_delta})

        try:
            async for chunk in graph.astream(payload, config=config, context=context, stream_mode="updates"):
                if not isinstance(chunk, dict):
                    continue
                if "__interrupt__" in chunk:
                    for interrupt in list(chunk.get("__interrupt__") or []):
                        value = getattr(interrupt, "value", None)
                        if not isinstance(value, dict):
                            value = {"message": str(value or "")}
                        pending_interrupt = AgentInterrupt(
                            interrupt_id=str(getattr(interrupt, "id", "") or value.get("interrupt_id") or f"interrupt-{uuid4()}"),
                            kind=str(value.get("kind") or "confirm_execute"),
                            title=str(value.get("title") or "请确认执行"),
                            message=str(value.get("message") or "请确认是否继续。"),
                            actions=list(value.get("actions") or ["approve", "reject"]),
                            selected_model_id=str(value.get("selected_model_id") or ""),
                            model_options=list(value.get("model_options") or []),
                            tool_name=str(value.get("tool_name") or ""),
                            args=dict(value.get("args") or {}),
                        )
                        emit(
                            "agent.interrupt.requested",
                            {
                                "interrupt_id": pending_interrupt.interrupt_id,
                                "kind": pending_interrupt.kind,
                                "title": pending_interrupt.title,
                                "message": pending_interrupt.message,
                                "actions": pending_interrupt.actions,
                                "selected_model_id": pending_interrupt.selected_model_id,
                                "model_options": pending_interrupt.model_options,
                                "tool_name": pending_interrupt.tool_name,
                                "args": pending_interrupt.args,
                            },
                            correlation_id=pending_interrupt.interrupt_id,
                        )
                    continue

                agent_payload = chunk.get("agent")
                if isinstance(agent_payload, dict):
                    for message in list(agent_payload.get("messages") or []):
                        tool_calls = _normalize_message_tool_calls(message)
                        if tool_calls:
                            for tool_call in tool_calls:
                                signature = _tool_signature(tool_call.get("name"), tool_call.get("args"))
                                if signature in failed_signatures:
                                    final_message = "检测到同一工具调用重复失败，已停止继续重试，请调整参数或改用其他策略。"
                                    emit("agent.error", {"message": final_message})
                                    emit("agent.done", {"session_id": session_id})
                                    return {
                                        "events": events,
                                        "message": final_message,
                                        "pending_interrupt": pending_interrupt,
                                        "tool_history": tool_history,
                                        "graph_state": {
                                            "api_key_id": str(config.get("configurable", {}).get("api_key_id") or ""),
                                            "chat_model_id": str(config.get("configurable", {}).get("chat_model_id") or ""),
                                            "run_id": run_id,
                                            "workflow_draft": dict((context or {}).get("workflow", {}).get("parameters") or {}),
                                        },
                                    }
                                call_signatures[str(tool_call.get("id") or "")] = signature
                                emit(
                                    "agent.tool.call",
                                    {
                                        "id": str(tool_call.get("id") or ""),
                                        "tool_name": str(tool_call.get("name") or ""),
                                        "args": dict(tool_call.get("args") or {}),
                                        "status": "requested",
                                    },
                                    correlation_id=str(tool_call.get("id") or ""),
                                )
                            continue
                        content = _normalize_message_content(message)
                        if content:
                            final_message = content
                            message_id = str(getattr(message, "id", "") or (message.get("id") if isinstance(message, dict) else "") or "")
                            emit(
                                "agent.message.delta",
                                {"id": message_id, "role": "assistant", "delta": content},
                            )
                            emit(
                                "agent.message.completed",
                                {"id": message_id, "role": "assistant", "content": content},
                            )

                tools_payload = chunk.get("tools")
                if isinstance(tools_payload, dict):
                    for message in list(tools_payload.get("messages") or []):
                        correlation_id, tool_name, result = _normalize_tool_message(message)
                        normalized_result = to_jsonable(result)
                        status = "failed" if _is_tool_failure(normalized_result) else "completed"
                        if status == "failed":
                            signature = call_signatures.get(correlation_id, "")
                            if signature:
                                failed_signatures.add(signature)
                            if isinstance(normalized_result, dict) and str(normalized_result.get("message") or "").strip():
                                last_failed_message = str(normalized_result.get("message") or "").strip()
                        tool_history.append(
                            {
                                "correlation_id": correlation_id,
                                "tool_name": tool_name,
                                "result": normalized_result,
                                "status": status,
                            }
                        )
                        emit(
                            "agent.tool.result",
                            {
                                "id": correlation_id,
                                "tool_name": tool_name,
                                "status": status,
                                "result": normalized_result,
                                "effect": dict(normalized_result.get("effect") or {}) if isinstance(normalized_result, dict) else {},
                            },
                            correlation_id=correlation_id,
                        )
        except Exception as exc:
            final_message = str(exc).strip() or "assistant stream failed"
            emit("agent.error", {"message": final_message})

        if not final_message and last_failed_message:
            final_message = last_failed_message
            fallback_message_id = f"assistant-{uuid4()}"
            emit("agent.message.delta", {"id": fallback_message_id, "role": "assistant", "delta": final_message})
            emit("agent.message.completed", {"id": fallback_message_id, "role": "assistant", "content": final_message})
        emit("agent.done", {"session_id": session_id})
        return {
            "events": events,
            "message": final_message,
            "pending_interrupt": pending_interrupt,
            "tool_history": tool_history,
            "graph_state": {
                "api_key_id": str(config.get("configurable", {}).get("api_key_id") or ""),
                "chat_model_id": str(config.get("configurable", {}).get("chat_model_id") or ""),
                "run_id": run_id,
                "workflow_draft": dict((context or {}).get("workflow", {}).get("parameters") or {}),
            },
        }

    async def _finalize_session(self, session: CanvasAgentSession, consumed: dict[str, Any]) -> CanvasAssistantTurnResult:
        events = list(consumed.get("events") or [])
        message = str(consumed.get("message") or "").strip()
        pending_interrupt = consumed.get("pending_interrupt")
        any_mutation = any(
            bool((entry.get("result") or {}).get("effect", {}).get("mutated"))
            for entry in list(consumed.get("tool_history") or [])
            if isinstance(entry, dict) and isinstance(entry.get("result"), dict)
        )
        if _goal_requires_canvas_mutation(session.user_goal) and _message_claims_canvas_success(message) and not any_mutation:
            message = "尚未成功写入画布：本轮没有产生真实节点变更，请补充更明确的目标或先指定上游节点。"
            events.insert(
                max(len(events) - 1, 0),
                {
                    "type": "agent.error",
                    "data": {
                        "message": message,
                        "event_id": f"{session.session_id}-consistency",
                        "session_id": session.session_id,
                        "thread_id": session.session_id,
                        "run_id": str((consumed.get("graph_state") or {}).get("run_id") or ""),
                        "timestamp": _utc_now_iso(),
                        "sequence": len(events),
                        "correlation_id": "",
                    },
                },
            )
        if message:
            session.conversation.append({"role": "assistant", "content": message})
        session.graph_state = dict(consumed.get("graph_state") or {})
        session.pending_interrupt = pending_interrupt if isinstance(pending_interrupt, AgentInterrupt) else None
        session.tool_history = list(consumed.get("tool_history") or [])[-8:]
        session.resume_in_flight = False
        session.status = "failed" if any(event.get("type") == "agent.error" for event in events) else ("interrupted" if session.pending_interrupt else "completed")
        await self.session_store.save(session)
        return CanvasAssistantTurnResult(
            session_id=session.session_id,
            message=message,
            events=events,
            pending_interrupt=session.pending_interrupt,
        )
