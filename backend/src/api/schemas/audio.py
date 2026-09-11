from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AudioGenerateRequest(BaseModel):
    """音频生成请求"""
    api_key_id: UUID = Field(..., description="使用的API Key ID")
    sentences_ids: List[UUID] = Field(..., description="要生成音频的句子ID列表")
    voice: Optional[str] = Field(None, description="语音风格")
    model: Optional[str] = Field(None, description="模型名称")


class AudioGenerateResponse(BaseModel):
    """音频生成响应"""
    success: bool = Field(..., description="是否成功提交任务")
    message: str = Field(..., description="响应消息")
    task_id: Optional[str] = Field(None, description="Celery任务ID")
