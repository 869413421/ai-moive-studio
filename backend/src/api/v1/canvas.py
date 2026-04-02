import inspect
from typing import Union

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user_required
from src.api.schemas.canvas import (
    CanvasApplyGenerationResponse,
    CanvasDocumentCreate,
    CanvasDocumentListResponse,
    CanvasDocumentResponse,
    CanvasDocumentUpdate,
    CanvasConnectionCreate,
    CanvasConnectionPayload,
    CanvasGenerateRequest,
    CanvasGenerateResultResponse,
    CanvasGenerationListResponse,
    CanvasGenerationResponse,
    CanvasGraphResponse,
    CanvasGraphUpdate,
    CanvasItemCreate,
    CanvasItemPayload,
    CanvasItemUpdate,
    CanvasPreviewItemsRequest,
    CanvasPreviewItemsResponse,
    CanvasStageDocumentResponse,
    CanvasStageSnapshotResponse,
    CanvasVideoTaskResponse,
    CanvasVideoUploadResponse,
)
from src.core.database import get_db
from src.models.user import User
from src.services.api_key import APIKeyService
from src.services.canvas import CanvasGenerationService, CanvasService
from src.tasks.canvas import generate_canvas_image, generate_canvas_text, generate_canvas_video
from src.utils.storage import get_storage_client

router = APIRouter()


async def resolve_canvas_media_fields(payload: dict) -> dict:
    content = dict(payload or {})
    storage_client = get_storage_client()
    if inspect.isawaitable(storage_client):
        storage_client = await storage_client

    image_object_key = str(content.get("result_image_object_key") or "").strip()
    if image_object_key:
        content["result_image_url"] = storage_client.get_presigned_url(image_object_key)

    reference_image_object_key = str(content.get("reference_image_object_key") or "").strip()
    if reference_image_object_key:
        content["reference_image_url"] = storage_client.get_presigned_url(reference_image_object_key)

    video_object_key = str(content.get("result_video_object_key") or "").strip()
    if video_object_key:
        content["result_video_url"] = storage_client.get_presigned_url(video_object_key)

    return content


async def build_item_payload(item) -> CanvasItemPayload:
    item_id = item["id"] if isinstance(item, dict) else item.id
    item_type = item["item_type"] if isinstance(item, dict) else item.item_type
    title = item.get("title", "") if isinstance(item, dict) else (item.title or "")
    position_x = item.get("position_x", 0) if isinstance(item, dict) else float(item.position_x or 0)
    position_y = item.get("position_y", 0) if isinstance(item, dict) else float(item.position_y or 0)
    width = item.get("width", 0) if isinstance(item, dict) else float(item.width or 0)
    height = item.get("height", 0) if isinstance(item, dict) else float(item.height or 0)
    z_index = item.get("z_index", 0) if isinstance(item, dict) else int(item.z_index or 0)
    content = item.get("content", {}) if isinstance(item, dict) else (item.content_json or {})
    generation_config = item.get("generation_config", {}) if isinstance(item, dict) else (item.generation_config_json or {})
    last_run_status = item.get("last_run_status") if isinstance(item, dict) else item.last_run_status
    last_run_error = item.get("last_run_error") if isinstance(item, dict) else item.last_run_error
    last_output = item.get("last_output", {}) if isinstance(item, dict) else (item.last_output_json or {})
    return CanvasItemPayload(
        id=item_id,
        item_type=item_type,
        title=title,
        position_x=position_x,
        position_y=position_y,
        width=width,
        height=height,
        z_index=z_index,
        content=await resolve_canvas_media_fields(content),
        generation_config=generation_config,
        last_run_status=last_run_status,
        last_run_error=last_run_error,
        last_output=await resolve_canvas_media_fields(last_output),
    )


async def build_generation_response(generation) -> CanvasGenerationResponse:
    if isinstance(generation, dict):
        data = dict(generation)
    else:
        data = {
            **generation.to_dict(),
            "request_payload": generation.request_payload_json,
            "result_payload": generation.result_payload_json,
        }
    data["result_payload"] = await resolve_canvas_media_fields(data.get("result_payload") or {})
    return CanvasGenerationResponse.from_dict(data)


def dispatch_canvas_text_generation(generation_id: str) -> str:
    return generate_canvas_text.delay(generation_id).id


def dispatch_canvas_image_generation(generation_id: str) -> str:
    return generate_canvas_image.delay(generation_id).id


def dispatch_canvas_video_generation(generation_id: str) -> str:
    return generate_canvas_video.delay(generation_id).id


@router.get("/canvas-model-catalog")
async def get_canvas_model_catalog(
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    api_key_service = APIKeyService(db)
    api_keys, _ = await api_key_service.get_user_api_keys(
        user_id=current_user.id,
        key_status="active",
        page=1,
        size=100,
    )

    catalog = {
        "text": [],
        "image": [],
        "video": [],
    }

    for model_type in catalog.keys():
        seen = set()
        for api_key in api_keys:
            try:
                models = await api_key_service.get_models(str(api_key.id), current_user.id, model_type)
            except Exception:
                continue
            for model in models or []:
                if model and model not in seen:
                    seen.add(model)
                    catalog[model_type].append(model)

    return catalog


@router.get("/canvas-documents", response_model=CanvasDocumentListResponse)
async def list_canvas_documents(
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    service = CanvasService(db)
    documents, total = await service.list_documents(str(current_user.id), page, size)
    return CanvasDocumentListResponse(
        documents=[CanvasDocumentResponse.from_dict(doc.to_dict()) for doc in documents],
        total=total,
        page=page,
        size=size,
        total_pages=(total + size - 1) // size if total else 0,
    )


@router.post("/canvas-documents", response_model=CanvasDocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_canvas_document(
    payload: CanvasDocumentCreate,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasService(db)
    document = await service.create_document(str(current_user.id), payload.title, payload.description)
    await db.commit()
    return CanvasDocumentResponse.from_dict(document.to_dict())


@router.get("/canvas-documents/{document_id}", response_model=Union[CanvasDocumentResponse, CanvasStageSnapshotResponse])
async def get_canvas_document(
    document_id: str,
    mode: str = Query("full"),
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasService(db)
    if mode == "lite":
        snapshot = await service.get_stage_snapshot(document_id, str(current_user.id))
        return CanvasStageSnapshotResponse(
            document=CanvasStageDocumentResponse(
                id=snapshot["document"].id,
                title=snapshot["document"].title,
            ),
            items=[await build_item_payload(item) for item in snapshot["items"]],
            connections=[
                CanvasConnectionPayload(
                    id=connection.id,
                    source_item_id=connection.source_item_id,
                    target_item_id=connection.target_item_id,
                    source_handle=connection.source_handle,
                    target_handle=connection.target_handle,
                )
                for connection in snapshot["connections"]
            ],
        )
    document = await service.get_document(document_id, str(current_user.id))
    return CanvasDocumentResponse.from_dict(document.to_dict())


@router.patch("/canvas-documents/{document_id}", response_model=CanvasDocumentResponse)
async def update_canvas_document(
    document_id: str,
    payload: CanvasDocumentUpdate,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasService(db)
    document = await service.update_document(document_id, str(current_user.id), payload.title, payload.description)
    await db.commit()
    return CanvasDocumentResponse.from_dict(document.to_dict())


@router.delete("/canvas-documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_canvas_document(
    document_id: str,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasService(db)
    await service.delete_document(document_id, str(current_user.id))
    await db.commit()


@router.post("/canvas-documents/{document_id}/items", response_model=CanvasItemPayload, status_code=status.HTTP_201_CREATED)
async def create_canvas_item(
    document_id: str,
    payload: CanvasItemCreate,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasService(db)
    item = await service.create_item(document_id, str(current_user.id), payload.model_dump())
    await db.commit()
    return await build_item_payload(item)


@router.get("/canvas-documents/{document_id}/items/{item_id}", response_model=CanvasItemPayload)
async def get_canvas_item(
    document_id: str,
    item_id: str,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasService(db)
    await service.get_document(document_id, str(current_user.id))
    item = await service.get_item(item_id, str(current_user.id))
    return await build_item_payload(item)


@router.patch("/canvas-documents/{document_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_canvas_item(
    document_id: str,
    item_id: str,
    payload: CanvasItemUpdate,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasService(db)
    await service.update_item(document_id, item_id, str(current_user.id), payload.model_dump(exclude_none=True))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/canvas-documents/{document_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_canvas_item(
    document_id: str,
    item_id: str,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasService(db)
    await service.delete_item(document_id, item_id, str(current_user.id))
    await db.commit()


@router.post("/canvas-documents/{document_id}/items/previews", response_model=CanvasPreviewItemsResponse)
async def get_canvas_item_previews(
    document_id: str,
    payload: CanvasPreviewItemsRequest,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasService(db)
    items = await service.get_item_previews(document_id, str(current_user.id), [str(item_id) for item_id in payload.item_ids])
    return CanvasPreviewItemsResponse(items=[await build_item_payload(item) for item in items])


@router.post("/canvas-documents/{document_id}/connections", response_model=CanvasConnectionPayload, status_code=status.HTTP_201_CREATED)
async def create_canvas_connection(
    document_id: str,
    payload: CanvasConnectionCreate,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasService(db)
    connection = await service.create_connection(document_id, str(current_user.id), payload.model_dump())
    await db.commit()
    return CanvasConnectionPayload(
        id=connection.id,
        source_item_id=connection.source_item_id,
        target_item_id=connection.target_item_id,
        source_handle=connection.source_handle,
        target_handle=connection.target_handle,
    )


@router.delete("/canvas-documents/{document_id}/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_canvas_connection(
    document_id: str,
    connection_id: str,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasService(db)
    await service.delete_connection(document_id, connection_id, str(current_user.id))
    await db.commit()


@router.get("/canvas-documents/{document_id}/graph", response_model=CanvasGraphResponse)
async def get_canvas_graph(
    document_id: str,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasService(db)
    graph = await service.get_graph(document_id, str(current_user.id))
    return CanvasGraphResponse(
        document=CanvasDocumentResponse.from_dict(graph["document"].to_dict()),
        items=[await build_item_payload(item) for item in graph["items"]],
        connections=[
            {
                "id": connection.id,
                "source_item_id": connection.source_item_id,
                "target_item_id": connection.target_item_id,
                "source_handle": connection.source_handle,
                "target_handle": connection.target_handle,
            }
            for connection in graph["connections"]
        ],
    )


@router.put("/canvas-documents/{document_id}/graph", response_model=CanvasGraphResponse)
async def save_canvas_graph(
    document_id: str,
    payload: CanvasGraphUpdate,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasService(db)
    await service.save_graph(
        document_id,
        str(current_user.id),
        [item.model_dump() for item in payload.items],
        [connection.model_dump() for connection in payload.connections],
    )
    await db.commit()
    graph = await service.get_graph(document_id, str(current_user.id))
    return CanvasGraphResponse(
        document=CanvasDocumentResponse.from_dict(graph["document"].to_dict()),
        items=[await build_item_payload(item) for item in graph["items"]],
        connections=[
            {
                "id": connection.id,
                "source_item_id": connection.source_item_id,
                "target_item_id": connection.target_item_id,
                "source_handle": connection.source_handle,
                "target_handle": connection.target_handle,
            }
            for connection in graph["connections"]
        ],
    )


@router.post("/canvas-items/{item_id}/generate-text", response_model=CanvasGenerateResultResponse)
async def generate_text_for_canvas_item(
    item_id: str,
    payload: CanvasGenerateRequest,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasGenerationService(db)
    _, generation = await service.prepare_text_generation(item_id, str(current_user.id), payload.model_dump(exclude_none=True))
    await db.commit()
    task_id = dispatch_canvas_text_generation(str(generation.id))
    item, generation = await service.attach_task(str(generation.id), task_id)
    await db.commit()
    return CanvasGenerateResultResponse(
        success=True,
        message="文本生成任务已提交",
        generation_id=generation.id,
        status="pending",
        item=await build_item_payload(item),
        generation=await build_generation_response(generation),
    )


@router.post("/canvas-items/{item_id}/generate-text/stream")
async def stream_generate_text_for_canvas_item(
    item_id: str,
    payload: CanvasGenerateRequest,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasGenerationService(db)

    async def event_stream():
        async for chunk in service.stream_text_generation(item_id, str(current_user.id), payload.model_dump(exclude_none=True)):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/canvas-items/{item_id}/generate-image", response_model=CanvasGenerateResultResponse)
async def generate_image_for_canvas_item(
    item_id: str,
    payload: CanvasGenerateRequest,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasGenerationService(db)
    _, generation = await service.prepare_image_generation(item_id, str(current_user.id), payload.model_dump(exclude_none=True))
    await db.commit()
    task_id = dispatch_canvas_image_generation(str(generation.id))
    item, generation = await service.attach_task(str(generation.id), task_id)
    await db.commit()
    return CanvasGenerateResultResponse(
        success=True,
        message="图片生成任务已提交",
        generation_id=generation.id,
        status="pending",
        item=await build_item_payload(item),
        generation=await build_generation_response(generation),
    )


@router.post("/canvas-items/{item_id}/generate-image/stream")
async def stream_generate_image_for_canvas_item(
    item_id: str,
    payload: CanvasGenerateRequest,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasGenerationService(db)
    _, generation = await service.prepare_image_generation(item_id, str(current_user.id), payload.model_dump(exclude_none=True))
    await db.commit()
    task_id = dispatch_canvas_image_generation(str(generation.id))
    _, generation = await service.attach_task(str(generation.id), task_id)
    await db.commit()

    return StreamingResponse(
        service.stream_generation_events(str(generation.id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/canvas-items/{item_id}/generate-video", response_model=CanvasGenerateResultResponse)
async def generate_video_for_canvas_item(
    item_id: str,
    payload: CanvasGenerateRequest,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasGenerationService(db)
    _, generation = await service.prepare_video_generation(item_id, str(current_user.id), payload.model_dump(exclude_none=True))
    await db.commit()
    task_id = dispatch_canvas_video_generation(str(generation.id))
    item, generation = await service.attach_task(str(generation.id), task_id)
    await db.commit()
    return CanvasGenerateResultResponse(
        success=True,
        message="视频生成任务已提交",
        generation_id=generation.id,
        status="pending",
        item=await build_item_payload(item),
        generation=await build_generation_response(generation),
    )


@router.post("/canvas-items/{item_id}/generate-video/stream")
async def stream_generate_video_for_canvas_item(
    item_id: str,
    payload: CanvasGenerateRequest,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasGenerationService(db)
    _, generation = await service.prepare_video_generation(item_id, str(current_user.id), payload.model_dump(exclude_none=True))
    await db.commit()
    task_id = dispatch_canvas_video_generation(str(generation.id))
    _, generation = await service.attach_task(str(generation.id), task_id)
    await db.commit()

    return StreamingResponse(
        service.stream_generation_events(str(generation.id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/canvas-items/{item_id}/generations", response_model=CanvasGenerationListResponse)
async def list_canvas_item_generations(
    item_id: str,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    service = CanvasService(db)
    generations, total = await service.list_generations(item_id, str(current_user.id), page, size)
    return CanvasGenerationListResponse(
        generations=[await build_generation_response(generation) for generation in generations],
        total=total,
        page=page,
        size=size,
        total_pages=(total + size - 1) // size if total else 0,
    )


@router.post("/canvas-items/{item_id}/generations/{generation_id}/apply", response_model=CanvasApplyGenerationResponse)
async def apply_canvas_generation(
    item_id: str,
    generation_id: str,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasService(db)
    item, generation = await service.apply_generation(item_id, generation_id, str(current_user.id))
    await db.commit()
    return CanvasApplyGenerationResponse(
        success=True,
        message="已应用历史结果",
        item=await build_item_payload(item),
        generation=await build_generation_response(generation),
    )


@router.get("/canvas-documents/{document_id}/items/{item_id}/video-tasks/{task_id}", response_model=CanvasVideoTaskResponse)
async def get_canvas_video_task(
    document_id: str,
    item_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasGenerationService(db)
    result = await service.get_video_task_status(document_id, item_id, task_id, str(current_user.id))
    resolved_video = await resolve_canvas_media_fields(
        {"result_video_object_key": result.get("result_video_object_key")}
    )
    return CanvasVideoTaskResponse(
        task_id=result["task_id"],
        provider_task_id=result.get("provider_task_id"),
        status=result["status"],
        result_video_url=resolved_video.get("result_video_url"),
        error_message=result.get("error_message"),
        provider_payload=result.get("provider_payload") or {},
        item=await build_item_payload(result["item"]),
    )


@router.post("/canvas-documents/{document_id}/items/{item_id}/upload-video", response_model=CanvasVideoUploadResponse)
async def upload_canvas_video(
    document_id: str,
    item_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    service = CanvasGenerationService(db)
    result = await service.upload_video_override(document_id, item_id, str(current_user.id), file)
    await db.commit()
    return CanvasVideoUploadResponse(
        success=True,
        message="视频已上传到画布节点",
        status="completed",
        item=await build_item_payload(result["item"]),
        storage_info=result["storage_info"],
    )
