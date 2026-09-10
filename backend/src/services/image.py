import asyncio
import random
from typing import List

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
from openai import RateLimitError

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
            # Retrying a timed-out generation may create and charge a duplicate.
            if getattr(e, 'status_code', None) != 429 or attempt == max_retries - 1:
                raise
            # 指数退避 + 随机抖动
            sleep_time = delay + random.random() * 0.5
            print(f"[Retry] 限流，{sleep_time:.2f} 秒后重试 attempt={attempt + 1}/{max_retries}")
            await asyncio.sleep(sleep_time)
            delay = min(delay * 2, 20)  # 最长等待 20 秒


# ============================================================
# 处理单句 – 优化版（返回异常信息）
# ============================================================

async def process_sentence(
        sentence: Sentence,
        llm_provider: BaseLLMProvider,
        semaphore: asyncio.Semaphore,
        storage_client,
        user_id: str,
        model: str = None,
):
    """
    单句 LLM 图片生成任务（含限流、错误透传）。

    Args:
        sentence: 待处理的 Sentence 实例
        llm_provider: LLM 提供者实例
        semaphore: 并发控制信号量
        storage_client: 存储客户端实例
        user_id: 用户ID
        db_session: 可选的数据库会话
        model: 模型名称
    """
    async with semaphore:
        try:
            logger.info(f"[LLM] 处理句子 {sentence.id}")

            # 加入重试机制
            result = await retry_with_backoff(
                lambda: llm_provider.generate_image(
                    prompt=sentence.image_prompt,
                    model=model,
                )
            )

            from src.utils.image_utils import extract_and_upload_image
            object_key = await extract_and_upload_image(result, user_id)

            # --- 更新数据库 ---
            sentence.image_url = object_key
            sentence.status = SentenceStatus.GENERATED_IMAGE
            sentence.mark_material_updated()  # 标记需要重新生成视频
            # 注意：不在这里 flush/commit，避免并发冲突
            # 统一在主函数中处理
            return True

        except Exception as e:
            logger.error(f"[LLM] 句子 {sentence.id} 错误: {e}", exc_info=True)
            return False


# ============================================================
# ImageService 主体
# ============================================================

class ImageService(BaseService):

    async def generate_images(self, api_key_id: str, sentence_ids: List[str], model: str = None) -> dict:
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
        llm_provider = ProviderFactory.from_key(api_key, max_concurrency=20)
        logger.info(f"[LLM] 使用 Provider: {llm_provider}, API Key ID: {api_key.id},Base URL: {api_key.base_url}")

        # --- 4. 创建统一并发控制 ---
        semaphore = asyncio.Semaphore(20)

        # --- 5. 创建任务列表 ---
        storage_client = await get_storage_client()
        tasks = [
            process_sentence(sentence, llm_provider, semaphore, storage_client, user_id, model)
            for sentence in sentences
        ]

        logger.info(f"[LLM] 开始并发处理，共 {len(tasks)} 项")

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

        logger.info("[FINISH] 所有任务完成")

        # 返回统计信息
        statistics = {
            "total": len(sentences),
            "success": success_count,
            "failed": failed_count
        }
        logger.info(f"[STATS] 图片生成统计: {statistics}")
        return statistics


__all__ = ["ImageService"]

if __name__ == "__main__":
    import asyncio


    async def test():
        service = ImageService()
        result = await service.generate_images(
            api_key_id="d538c04d-b2a5-49eb-b5cb-fbb6be3015cf",
            # api_key_id="6861e67b-6731-4dca-b215-aade208b627f",
            sentence_ids=["0bbe271a-e0d6-4565-be58-9c3d5898d732"],
            model='gemini-3-pro-image-preview'
            # model= 'sora_image'
        )
        print(result)


    asyncio.run(test())
