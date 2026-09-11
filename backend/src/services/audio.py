import uuid
import asyncio
import random
import io
import aiohttp
from typing import List

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from src.core.exceptions import NotFoundError
from src.core.logging import get_logger
from src.models import Sentence, SentenceStatus, Paragraph, Chapter
from src.services.api_key import APIKeyService
from src.services.base import BaseService
from src.services.provider.gateway import GatewayProvider as BaseLLMProvider
from src.services.provider.factory import ProviderFactory
from src.utils.storage import get_storage_client

logger = get_logger(__name__)


async def retry_with_backoff(task_fn, max_retries=5):
    """
    针对 429 限流错误加入指数退避重试机制
    """
    delay = 1.0

    for attempt in range(max_retries):
        try:
            return await task_fn()
        except Exception as e:
            # 只对 429 或 RateLimitError 做重试，其余立即抛出
            if getattr(e, 'status_code', None) == 429:
                if attempt == max_retries - 1:
                    raise

                # 指数退避 + 随机抖动
                sleep_time = delay + random.random() * 0.5
                print(f"[Retry] 限流，{sleep_time:.2f} 秒后重试 attempt={attempt + 1}/{max_retries}")
                await asyncio.sleep(sleep_time)

                delay = min(delay * 2, 20)  # 最长等待 20 秒
            else:
                # 非限流错误直接抛出
                raise


# ============================================================
# 处理单句 – 音频版
# ============================================================

async def process_sentence(
        sentence: Sentence,
        llm_provider: BaseLLMProvider,
        semaphore: asyncio.Semaphore,
        storage_client,
        user_id: str,
        voice: str = None,
        model: str = None
):
    """
    单句 LLM 音频生成任务（含限流、错误透传）。

    Args:
        sentence: 待处理的 Sentence 实例
        llm_provider: LLM 提供者实例
        semaphore: 并发控制信号量
        storage_client: 存储客户端实例
        user_id: 用户ID
        db_session: 可选的数据库会话
        voice: 语音风格
        model: 模型名称
    """
    async with semaphore:
        try:
            logger.info(f"[LLM] 处理句子音频 {sentence.id}")

            # 加入重试机制
            # 注意：OpenAI audio API 返回的是二进制内容，不是 URL
            # 对于 SiliconFlow，voice 格式为 "model:voice_name"，例如 "FunAudioLLM/CosyVoice2-0.5B:alex"
            response = await retry_with_backoff(
                lambda: llm_provider.generate_audio(
                    input_text=sentence.content,
                    voice=voice,
                    model=model,
                )
            )

            # OpenAI SDK audio.speech.create 返回的是 HttpxBinaryResponseContent
            # 需要读取 content
            content = response.content

            # --- 上传 MinIO ---
            file_id = str(uuid.uuid4())
            upload_file = UploadFile(
                filename=f"{file_id}.{response.extension}",
                file=io.BytesIO(content),
            )

            storage_result = await storage_client.upload_file(
                user_id=user_id,
                file=upload_file,
                metadata={
                    "user_id": user_id,
                    "file_id": file_id,
                    "file_type": response.mime,
                    "original_filename": f"{file_id}.{response.extension}"
                }
            )
            object_key = storage_result["object_key"]

            # --- 计算音频时长 ---
            try:
                from src.utils.ffmpeg_utils import get_audio_duration
                import tempfile
                import os
                
                # 下载音频文件到临时位置以计算时长
                temp_audio_path = os.path.join(tempfile.gettempdir(), f"{file_id}.{response.extension}")
                await storage_client.download_file_to_path(object_key, temp_audio_path)
                
                # 获取时长
                duration = get_audio_duration(temp_audio_path)
                
                # 清理临时文件
                if os.path.exists(temp_audio_path):
                    os.remove(temp_audio_path)
                    
                logger.info(f"[AUDIO] 句子 {sentence.id} 音频时长: {duration}秒")
            except Exception as e:
                logger.warning(f"[AUDIO] 无法获取音频时长: {e}")
                duration = None

            # --- 更新数据库 ---
            sentence.audio_url = object_key
            sentence.audio_duration = duration
            sentence.status = SentenceStatus.GENERATED_AUDIO
            sentence.mark_material_updated()  # 标记需要重新生成视频
            # 注意：不在这里 flush/commit，避免并发冲突
            # 统一在主函数中处理
            return True

        except Exception as e:
            logger.error(f"[LLM] 句子 {sentence.id} 音频生成错误: {e}", exc_info=True)
            return False


# ============================================================
# AudioService 主体
# ============================================================

class AudioService(BaseService):

    async def generate_audio(self, api_key_id: str, sentence_ids: List[str], voice: str = None,
                             model: str = None) -> dict:
        # --- 1. 查询 Sentence ----
        stmt = (
            select(Sentence)
            .where(Sentence.id.in_(sentence_ids))
            .options(
                selectinload(Sentence.paragraph)
                .selectinload(Paragraph.chapter)
                .selectinload(Chapter.project)
            )
        )
        result = await self.execute(stmt)
        sentences = result.scalars().all()

        if not sentences:
            raise NotFoundError("未找到待处理句子")

        chapter = sentences[0].paragraph.chapter
        user_id = chapter.project.owner_id

        # --- 2. 获取 API Key ---
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id, user_id)

        # --- 3. LLM Provider ---
        llm_provider = ProviderFactory.from_key(api_key, max_concurrency=5)
        logger.info(f"[LLM] 使用 Provider: {llm_provider}, API Key ID: {api_key.id},Base URL: {api_key.base_url}")

        # --- 4. 创建统一并发控制 ---
        semaphore = asyncio.Semaphore(5)

        # --- 5. 创建任务列表 ---
        storage_client = await get_storage_client()
        tasks = [
            process_sentence(sentence, llm_provider, semaphore, storage_client, user_id, voice, model)
            for sentence in sentences
        ]

        logger.info(f"[LLM] 开始并发处理音频，共 {len(tasks)} 项")

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 统计成功和失败数量
        success_count = 0
        failed_count = 0
        for res in results:
            if isinstance(res, Exception) or res is False:
                failed_count += 1
            else:
                success_count += 1

        await api_key_service.update_usage(api_key.id, user_id)

        # --- 7. 提交数据库 ---
        await self.db_session.flush()
        await self.db_session.commit()

        logger.info("[FINISH] 所有音频任务完成")

        # 返回统计信息
        statistics = {
            "total": len(sentences),
            "success": success_count,
            "failed": failed_count
        }
        logger.info(f"[STATS] 音频生成统计: {statistics}")
        return statistics


__all__ = ["AudioService"]
