"""Canvas agent streaming API."""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user_required
from src.api.schemas.canvas_assistant import CanvasAssistantChatRequest, CanvasAssistantResumeRequest
from src.api.v1.canvas import dispatch_canvas_image_generation, dispatch_canvas_text_generation, dispatch_canvas_video_generation
from src.assistant.agent_factory import CanvasAssistantAgentFactory
from src.assistant.service import CanvasAssistantService
from src.assistant.session_store import InMemoryCanvasAssistantSessionStore, RedisCanvasAssistantSessionStore
from src.assistant.sse import encode_sse_event
from src.assistant.workflow_service import CanvasAssistantWorkflowService
from src.assistant.tools.canvas_tools import CanvasAssistantCanvasExecutionTools, CanvasAssistantCanvasInspectionTools
from src.assistant.tools.generation_tools import CanvasAssistantGenerationTools
from src.core.config import settings
from src.core.database import get_db
from src.models.user import User
from src.services.api_key import APIKeyService
from src.services.canvas import CanvasGenerationService, CanvasService

router = APIRouter()
_redis_client = None


def _get_redis_client():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as redis  # type: ignore
    except Exception:
        return None
    _redis_client = redis.from_url(settings.REDIS_URL)
    return _redis_client


def get_canvas_assistant_service(db: AsyncSession = Depends(get_db)) -> CanvasAssistantService:
    canvas_service = CanvasService(db)
    generation_service = CanvasGenerationService(db)
    inspection_tools = CanvasAssistantCanvasInspectionTools(canvas_service)
    redis_client = _get_redis_client()
    generation_tools = CanvasAssistantGenerationTools(
        generation_service=generation_service,
        dispatch_text=dispatch_canvas_text_generation,
        dispatch_image=dispatch_canvas_image_generation,
        dispatch_video=dispatch_canvas_video_generation,
    )
    workflow_service = CanvasAssistantWorkflowService(
        canvas_service=canvas_service,
        generation_service=generation_service,
        api_key_service=APIKeyService(db),
        dispatch_text=dispatch_canvas_text_generation,
        dispatch_image=dispatch_canvas_image_generation,
        dispatch_video=dispatch_canvas_video_generation,
    )
    agent_factory = CanvasAssistantAgentFactory(
        db_session=db,
        inspection_tools=inspection_tools,
        canvas_execution_tools=CanvasAssistantCanvasExecutionTools(canvas_service),
        generation_tools=generation_tools,
        workflow_service=workflow_service,
    )
    return CanvasAssistantService(
        session_store=RedisCanvasAssistantSessionStore(redis_client) if redis_client is not None else InMemoryCanvasAssistantSessionStore(),
        inspection_tools=inspection_tools,
        canvas_execution_tools=CanvasAssistantCanvasExecutionTools(canvas_service),
        generation_tools=generation_tools,
        agent_factory=agent_factory,
    )


def _iter_turn_events(result) -> Iterable[str]:
    for event in result.events:
        yield encode_sse_event(str(event.get("type") or ""), event.get("data") or {})


@router.post("/canvas-assistant/chat")
async def chat_canvas_assistant(
    payload: CanvasAssistantChatRequest,
    current_user: User = Depends(get_current_user_required),
    service: CanvasAssistantService = Depends(get_canvas_assistant_service),
):
    result = await service.chat(payload, user_id=str(current_user.id))
    return StreamingResponse(_iter_turn_events(result), media_type="text/event-stream")


@router.post("/canvas-assistant/resume")
async def resume_canvas_assistant(
    payload: CanvasAssistantResumeRequest,
    current_user: User = Depends(get_current_user_required),
    service: CanvasAssistantService = Depends(get_canvas_assistant_service),
):
    result = await service.resume(payload, user_id=str(current_user.id))
    return StreamingResponse(_iter_turn_events(result), media_type="text/event-stream")
