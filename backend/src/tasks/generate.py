"""
内容生成相关的 Celery 任务
"""
from typing import Any, Dict, List
from src.tasks.app import celery_app
from src.tasks.base import async_task_decorator
from src.core.logging import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

@celery_app.task(
    bind=True,
    max_retries=0,
    name="generate.generate_prompts"
)
@async_task_decorator
async def generate_prompts(db_session: AsyncSession, self, chapter_id: str, api_key_id: str, style: str, model: str = None, custom_prompt: str = None):
    """为章节生成提示词的 Celery 任务"""
    from src.services.prompt import PromptService
    logger.info(f"Celery任务开始: generate_prompts (chapter_id={chapter_id})")
    
    service = PromptService(db_session)
    result = await service.generate_prompts_batch(chapter_id, api_key_id, style, model, custom_prompt)
    
    logger.info(f"Celery任务成功: generate_prompts (chapter_id={chapter_id})")
    return result

@celery_app.task(
    bind=True,
    max_retries=0,
    name="generate.generate_prompts_by_ids"
)
@async_task_decorator
async def generate_prompts_by_ids(db_session: AsyncSession, self, sentence_ids: List[str], api_key_id: str, style: str, model: str = None, custom_prompt: str = None):
    """为指定句子生成提示词的 Celery 任务"""
    from src.services.prompt import PromptService
    logger.info(f"Celery任务开始: generate_prompts_by_ids (sentence_ids={sentence_ids})")
    
    service = PromptService(db_session)
    result = await service.generate_prompts_by_ids(sentence_ids, api_key_id, style, model, custom_prompt)
    
    logger.info(f"Celery任务成功: generate_prompts_by_ids")
    return result

@celery_app.task(
    bind=True,
    max_retries=0,
    name="generate.generate_images"
)
@async_task_decorator
async def generate_images(db_session: AsyncSession, self, api_key_id: str, sentences_ids: list[str], model: str = None):
    """批量生成图片的 Celery 任务"""
    from src.services.image import ImageService
    logger.info(f"Celery任务开始: generate_images (sentences_ids={sentences_ids})")
    
    service = ImageService(db_session)
    result = await service.generate_images(api_key_id, sentences_ids, model)
    
    logger.info(f"Celery任务成功: generate_images")
    return result

@celery_app.task(
    bind=True,
    max_retries=0,
    name="generate.generate_audio"
)
@async_task_decorator
async def generate_audio(db_session: AsyncSession, self, api_key_id: str, sentences_ids: list[str], voice: str = None, model: str = None):
    """批量生成音频的 Celery 任务"""
    from src.services.audio import AudioService
    logger.info(f"Celery任务开始: generate_audio (sentences_ids={sentences_ids})")
    
    service = AudioService(db_session)
    result = await service.generate_audio(api_key_id, sentences_ids, voice, model)
    
    logger.info(f"Celery任务成功: generate_audio")
    return result

@celery_app.task(
    bind=True,
    max_retries=0,
    name="generate.synthesize_video"
)
@async_task_decorator
async def synthesize_video(db_session: AsyncSession, self, video_task_id: str):
    """视频合成的 Celery 任务 - 根据项目类型路由到不同服务"""
    from src.services.video_task import VideoTaskService
    from src.services.chapter import ChapterService
    
    logger.info(f"Celery任务开始: synthesize_video (video_task_id={video_task_id})")
    
    # 1. 加载任务
    task_service = VideoTaskService(db_session)
    task = await task_service.get_video_task_by_id(video_task_id)
    
    # 2. 加载章节判断项目类型
    chapter_service = ChapterService(db_session)
    chapter = await chapter_service.get_chapter_by_id(task.chapter_id)
    
    # 3. 显式加载项目以避免懒加载问题
    from src.services.project import ProjectService
    project_service = ProjectService(db_session)
    project = await project_service.get_project_by_id(chapter.project_id)
    
    # 4. 根据项目类型路由到不同服务
    if project.type == 'ai_movie':
        # 电影类型 - 使用MovieVideoService从过渡视频合成
        logger.info(f"检测到电影类型项目,使用MovieVideoService.synthesize_movie_from_transitions")
        from src.services.movie_video_service import MovieVideoService
        service = MovieVideoService(db_session)
        result = await service.synthesize_movie_from_transitions(video_task_id)
    else:
        # 图解说类型 - 使用VideoSynthesisService
        logger.info(f"检测到图解说类型项目,使用VideoSynthesisService")
        from src.services.video_synthesis import VideoSynthesisService
        service = VideoSynthesisService(db_session)
        result = await service.synthesize_video(video_task_id)
    
    logger.info(f"Celery任务成功: synthesize_video (video_task_id={video_task_id})")
    return result
