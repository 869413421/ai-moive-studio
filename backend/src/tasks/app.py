"""
Celery 应用初始化模块
"""
from celery import Celery
from src.core.config import settings

from celery.signals import worker_process_init, worker_process_shutdown
from src.core.database import initialize_database, close_database_connections
from src.tasks.base import run_async_task

celery_app = Celery(
    "aicon",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "src.tasks.project",
        "src.tasks.generate",
        "src.tasks.canvas",
        "src.tasks.movie",
        "src.tasks.movie_composition",  # 电影合成任务
        "src.tasks.bilibili_task"
    ]
)

@worker_process_init.connect
def init_worker(**kwargs):
    """Worker 进程启动时初始化数据库引擎"""
    run_async_task(initialize_database())

@worker_process_shutdown.connect
def shutdown_worker(**kwargs):
    """Worker 进程关闭时清理数据库连接"""
    run_async_task(close_database_connections())

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=getattr(settings, "CELERY_TASK_TIME_LIMIT", 600),
    task_soft_time_limit=getattr(settings, "CELERY_TASK_SOFT_TIME_LIMIT", 480),
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    result_expires=3600,
    beat_schedule={
        "sync-canvas-video-status-every-30s": {
            "task": "canvas.sync_video_status",
            "schedule": 30.0,
        },
        "sync-video-status-every-30s": {
            "task": "movie.sync_transition_video_status",
            "schedule": 30.0,
        },
    }
)
