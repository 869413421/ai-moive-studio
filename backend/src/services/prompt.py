"""
AI导演引擎 - 提示词生成服务（优化版，含完整注释）

提供服务：
- 批量生成图像提示词
- 支持多种 LLM 提供商（Volcengine、DeepSeek）
- 提示词模板与风格预设
- 异常处理统一、方法职责清晰
"""

import asyncio
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.core.exceptions import NotFoundError
from src.core.logging import get_logger
from src.models import Sentence, APIKey, ChapterStatus, SentenceStatus, Paragraph, Chapter
from src.services import ChapterService
from src.services.api_key import APIKeyService
from src.services.base import BaseService
from src.services.provider.gateway import GatewayProvider as BaseLLMProvider
from src.services.provider.factory import ProviderFactory

logger = get_logger(__name__)


# ============================================================
# 单句处理逻辑（支持并发限流）
# ============================================================

async def process_sentence(
        sentence: Sentence,
        api_key: APIKey,
        llm_provider: BaseLLMProvider,
        system_prompt: str,
        semaphore: asyncio.Semaphore,
        model: str = None,
):
    """
    处理单个句子，调用 LLM 生成英文绘画提示词。

    Args:
        sentence (Sentence): 单个小说句子对象
        api_key (APIKey): 当前使用的 API Key
        llm_provider (BaseLLMProvider): LLM 提供商实例
        system_prompt (str): 系统指令提示词
        semaphore (asyncio.Semaphore): 并发控制信号量
        model (str): 模型名称，如果提供则使用该模型

    Returns:
        Tuple[Sentence, str]: (句子对象, 生成的英文提示词)

    Raises:
        Exception: LLM 调用失败等异常
    """
    model_name = model

    logger.debug(f"[LLM] 使用模型: {model_name} (Provider: {api_key.provider})")
    # 使用信号量控制并发，避免过度同时请求
    async with semaphore:
        logger.info(
            f"[LLM] 开始处理句子: id={sentence.id}, 字符数={len(sentence.content)}, 模型={model_name}"
        )

        try:
            # 调用 LLM 生成提示词
            response = await llm_provider.completions(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": sentence.content},
                ],
            )

            # 提取生成内容
            prompt = response.choices[0].message.content.strip()
            logger.debug(f"[LLM] 生成完成: id={sentence.id}, prompt_len={len(prompt)}")

            return sentence, prompt

        except Exception as e:
            logger.error(f"[LLM] 处理失败: sentence_id={sentence.id}, error={e}")
            raise


# ============================================================
# 主业务服务类
# ============================================================

class PromptService(BaseService):
    """
    提示词生成服务

    - 将中文小说句子转换为英文 Stable Diffusion 绘画提示词
    - 支持多句处理、批量并发、风格预设
    - 支持多 LLM 提供商
    """

    # 风格预设模板，用于增强 LLM 输出的绘画风格一致性
    STYLE_TEMPLATES = {
        "cinematic": "Cinematic lighting, 8k resolution, photorealistic, movie still, detailed texture, dramatic atmosphere.",
        "anime": "Anime style, Makoto Shinkai style, vibrant colors, detailed background, high quality.",
        "illustration": "Digital illustration, artstation, concept art, fantasy style, detailed.",
        "ink": "Chinese ink painting style, watercolor, traditional art, artistic, abstract.",
    }

    # 基础系统提示语（作为所有风格的基础指令）
    BASE_SYSTEM_PROMPT = """
你是一个专业的AI绘画提示词生成专家(AI Director)。
你的任务是将中文小说句子转换为高质量的提示词。

请遵循以下规则：
1. 输出必须是纯文本，不要包含markdown语法或解释性内容。
2. 不要加入前缀/后缀，例如“Here is the prompt:”。
3. 提示词结构建议为：Subject, Action, Background, Lighting, Style, Quality。
4. 正确表达句子的视觉元素、情绪与意境。
5. 如果句子没有明确画面（如心理描写），请生成符合氛围的意象画面。
"""

    # ------------------------------------------------------------
    # 工具方法：系统提示词构建
    # ------------------------------------------------------------
    def _build_system_prompt(self, style: str) -> str:
        """
        组合系统提示词与风格预设。

        Args:
            style (str): 风格名称

        Returns:
            str: 完整系统提示语
        """
        style_suffix = self.STYLE_TEMPLATES.get(style, self.STYLE_TEMPLATES["cinematic"])
        return self.BASE_SYSTEM_PROMPT + f"\n风格要求：{style_suffix}"

    # ------------------------------------------------------------
    # 工具方法：加载并校验 API Key
    # ------------------------------------------------------------
    async def _load_api_key(self, api_key_id: str, user_id: str) -> APIKey:
        """
        读取并校验 API Key 是否存在。

        Args:
            api_key_id (str): API Key ID
            user_id (str): 用户 ID

        Raises:
            NotFoundError: API Key 不存在

        Returns:
            APIKey: API Key 对象
        """
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id, user_id)

        if not api_key:
            raise NotFoundError("未找到API密钥", resource_id=api_key_id, resource_type="api_key")

        return api_key

    # ------------------------------------------------------------
    # 核心共用逻辑：并发生成 + 保存数据库 + 更新状态
    # ------------------------------------------------------------

    async def _generate_prompts(self, sentences: List[Sentence], api_key: APIKey, style: str,
                                update: bool = True, model: str = None, custom_prompt: str = None) -> dict:
        """
        核心执行方法：批量生成提示词 + 写数据库 + 更新章节状态。

        Args:
            sentences (List[Sentence]): 待处理句子列表
            api_key (APIKey): API Key 对象
            style (str): 生成提示词的风格
            update (bool): 是否更新章节，默认为 True
            model (str): 模型名称
            custom_prompt (str): 自定义系统提示词
            
        Returns:
            dict: 统计信息 {"total": int, "success": int, "failed": int}
        """

        # 创建 LLM provider 实例
        llm_provider = ProviderFactory.from_key(api_key, max_concurrency=20)

        # 建立并发信号量（限制同一时刻的 LLM 请求数量）
        semaphore = asyncio.Semaphore(20)

        # 构建所有句子的任务列表
        tasks = [
            process_sentence(sentence, api_key, llm_provider, custom_prompt, semaphore, model)
            for sentence in sentences
        ]

        logger.info(f"[LLM] 开始批量生成提示词，总数={len(sentences)}")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("[LLM] 所有句子处理完成")

        # 统计成功和失败数量
        success_count = 0
        failed_count = 0

        # 写入返回结果到数据库
        logger.info("[DB] 写入生成结果到数据库")
        for result in results:
            if isinstance(result, Exception):
                # 处理失败
                failed_count += 1
                logger.error(f"[LLM] 句子处理失败: {result}")
                continue
            
            sentence, prompt = result
            sentence.image_prompt = prompt
            sentence.status = SentenceStatus.GENERATED_PROMPTS
            sentence.image_style = style
            success_count += 1

        chapter = sentences[0].paragraph.chapter
        if update:
            # 统一更新章节状态
            chapter.status = ChapterStatus.GENERATED_PROMPTS.value

        # 更新 API Key 使用次数
        api_key_service = APIKeyService(self.db_session)
        await api_key_service.update_usage(api_key.id, chapter.project.owner_id)
        logger.info("[API KEY] 使用统计已更新")

        # 提交数据库
        await self.db_session.flush()
        await self.db_session.commit()
        logger.info("[DB] 数据库更新完成")
        
        # 返回统计信息
        statistics = {
            "total": len(sentences),
            "success": success_count,
            "failed": failed_count
        }
        logger.info(f"[STATS] 提示词生成统计: {statistics}")
        return statistics

    # ============================================================
    # 对外方法：按章节处理
    # ============================================================

    async def generate_prompts_batch(self, chapter_id: str, api_key_id: str, style: str = "cinematic", model: str = None, custom_prompt: str = None) -> dict:
        """
        批量生成提示词（按章节 ID 获取所有待处理句子）
        """
        # 查询章节句子
        chapter_service = ChapterService(self.db_session)
        sentences = await chapter_service.get_sentences(chapter_id)

        if not sentences:
            raise NotFoundError("未找到待处理句子", resource_id=chapter_id, resource_type="chapter")

        # 加载 API Key
        user_id = sentences[0].paragraph.chapter.project.owner_id
        api_key = await self._load_api_key(api_key_id, user_id)

        # 统一执行批量处理
        return await self._generate_prompts(sentences, api_key, style, True, model, custom_prompt)

    # ============================================================
    # 对外方法：按句子 ID 数组处理
    # ============================================================

    async def generate_prompts_by_ids(self, sentence_ids: List[str], api_key_id: str, style: str = "cinematic", model: str = None, custom_prompt: str = None) -> dict:
        """
        批量生成提示词（按句子 ID 列表处理）
        """
        # 根据 ID 查询句子
        stmt = select(Sentence).where(Sentence.id.in_(sentence_ids)).options(
            selectinload(Sentence.paragraph).selectinload(Paragraph.chapter).selectinload(Chapter.project)
        )

        result = await self.execute(stmt)
        sentences = result.scalars().all()

        if not sentences:
            raise NotFoundError(
                "未找到待处理句子",
                resource_id=",".join(sentence_ids),
                resource_type="sentence",
            )

        # 加载 API Key
        user_id = sentences[0].paragraph.chapter.project.owner_id
        api_key = await self._load_api_key(api_key_id, user_id)

        # 执行批量生成
        return await self._generate_prompts(sentences, api_key, style, False, model, custom_prompt)


__all__ = ["PromptService"]
