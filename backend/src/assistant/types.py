from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

AgentStatus = Literal["idle", "running", "interrupted", "waiting_user", "completed", "failed"]


@dataclass
class ToolEffect:
    mutated: bool = False
    created_item_ids: list[str] = field(default_factory=list)
    updated_item_ids: list[str] = field(default_factory=list)
    deleted_item_ids: list[str] = field(default_factory=list)
    created_connection_ids: list[str] = field(default_factory=list)
    deleted_connection_ids: list[str] = field(default_factory=list)
    submitted_task_ids: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class AgentInterrupt:
    interrupt_id: str
    kind: str
    title: str
    message: str
    actions: list[str] = field(default_factory=lambda: ["approve", "reject"])
    selected_model_id: str = ""
    model_options: list[dict[str, Any]] = field(default_factory=list)
    tool_name: str = ""
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class CanvasAgentSession:
    session_id: str
    user_id: str
    document_id: str
    conversation: list[dict[str, Any]] = field(default_factory=list)
    user_goal: str = ""
    graph_state: dict[str, Any] = field(default_factory=dict)
    pending_interrupt: AgentInterrupt | None = None
    tool_history: list[dict[str, Any]] = field(default_factory=list)
    resume_in_flight: bool = False
    status: AgentStatus = "idle"


@dataclass
class CanvasAssistantTurnResult:
    session_id: str
    message: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    pending_interrupt: AgentInterrupt | None = None
