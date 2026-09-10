from src.core.logging import get_logger
from src.tasks.app import celery_app
from src.tasks.base import async_task_decorator

logger = get_logger(__name__)


@celery_app.task(bind=True, max_retries=0, name="canvas.generate_text")
@async_task_decorator
async def generate_canvas_text(db_session, self, generation_id: str):
    from src.services.canvas import CanvasGenerationService

    logger.info("Celery任务开始: canvas.generate_text (generation_id=%s)", generation_id)
    service = CanvasGenerationService(db_session)
    result = await service.process_text_generation(generation_id)
    logger.info("Celery任务成功: canvas.generate_text (generation_id=%s)", generation_id)
    return result


@celery_app.task(bind=True, max_retries=0, name="canvas.generate_image")
@async_task_decorator
async def generate_canvas_image(db_session, self, generation_id: str):
    from src.services.canvas import CanvasGenerationService

    logger.info("Celery任务开始: canvas.generate_image (generation_id=%s)", generation_id)
    service = CanvasGenerationService(db_session)
    result = await service.process_image_generation(generation_id)
    logger.info("Celery任务成功: canvas.generate_image (generation_id=%s)", generation_id)
    return result


@celery_app.task(bind=True, max_retries=0, name="canvas.generate_video")
@async_task_decorator
async def generate_canvas_video(db_session, self, generation_id: str):
    from src.services.canvas import CanvasGenerationService

    logger.info("Celery任务开始: canvas.generate_video (generation_id=%s)", generation_id)
    service = CanvasGenerationService(db_session)
    result = await service.process_video_generation(generation_id)
    logger.info("Celery任务成功: canvas.generate_video (generation_id=%s)", generation_id)
    return result


@celery_app.task(bind=True, max_retries=0, name="canvas.sync_video_status")
@async_task_decorator
async def sync_canvas_video_status(db_session, self):
    from sqlalchemy import select
    from src.models.canvas import CanvasItemGeneration

    rows = (await db_session.execute(
        select(CanvasItemGeneration.id, CanvasItemGeneration.result_payload_json)
        .where(CanvasItemGeneration.generation_type == 'video', CanvasItemGeneration.status.in_(['pending', 'processing']))
    )).all()
    submitted = 0
    for generation_id, payload in rows:
        if (payload or {}).get('provider_task_id'):
            poll_canvas_video_status.delay(str(generation_id))
            submitted += 1
    return {'checked': submitted}


@celery_app.task(bind=True, max_retries=0, name="canvas.poll_video_status")
@async_task_decorator
async def poll_canvas_video_status(db_session, self, generation_id):
    from redis.asyncio import Redis
    from redis.exceptions import LockError
    from src.core.config import settings
    from src.services.canvas import CanvasGenerationService

    # A slow upstream query must not pile up concurrent polls from successive beats.
    async with Redis.from_url(settings.REDIS_URL) as redis:
        lock = redis.lock(f'canvas:video-poll:{generation_id}', timeout=360, blocking=False)
        if not await lock.acquire():
            return {'skipped': True}
        try:
            service = CanvasGenerationService(db_session)
            generation, item = await service._load_generation_and_item(generation_id, 'video')
            if generation.status not in {'pending', 'processing'}:
                return {'status': generation.status}
            result = await service.get_video_task_status(str(item.document_id), str(item.id), generation_id, str(generation.user_id))
            await db_session.commit()
            return {'status': result['status']}
        finally:
            try:
                await lock.release()
            except LockError:
                pass
