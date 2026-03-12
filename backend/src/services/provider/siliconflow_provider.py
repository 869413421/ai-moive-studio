# src/services/providers/siliconflow_provider.py

import asyncio
from typing import Any, Dict, List
from openai import AsyncOpenAI

from src.core.logging import get_logger
from src.services.provider.base import BaseLLMProvider, log_provider_call

logger = get_logger(__name__)


class SiliconFlowProvider(BaseLLMProvider):
    """
    纯净 SiliconFlow Provider，不含任何业务逻辑。

    - 不拼接 prompt
    - 不封装风格
    - 不理解句子
    - 不处理提示词生成

    只提供 completions() 和 generate_image() 接口 → 等同于一个可并发的 SiliconFlow SDK wrapper
    """

    def __init__(self, api_key: str, max_concurrency: int = 5, base_url: str = "https://api.siliconflow.cn/v1"):
        # 规范化 base_url: 确保以斜杠结尾
        if not base_url.endswith('/'):
            base_url = base_url + '/'

        self.base_url = base_url
        
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=300.0  # 5分钟超时
        )
        self.semaphore = asyncio.Semaphore(max_concurrency)

    @log_provider_call("completions")
    async def completions(
            self,
            model: str,
            messages: List[Dict[str, Any]],
            **kwargs: Any
    ):
        """
        调用 SiliconFlow chat.completions.create（纯粹透传）
        """

        # 用 semaphore 限制并发
        async with self.semaphore:
            return await self.client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs
            )

    @log_provider_call("generate_image")
    async def generate_image(
            self,
            prompt: str,
            model: str = None,
            **kwargs: Any
    ):
        """
        调用 SiliconFlow images.generate（纯粹透传）
        """

        # 用 semaphore 限制并发
        async with self.semaphore:
            return await self.client.images.generate(
                model=model or "Kwai-Kolors/Kolors",
                prompt=prompt,
                **kwargs
            )

    @log_provider_call("generate_audio")
    async def generate_audio(
            self,
            input_text: str,
            voice: str = "alloy",
            model: str = "tts-1",
            **kwargs: Any
    ):
        """
        调用 OpenAI audio.speech.create（纯粹透传）
        """

        # 用 semaphore 限制并发
        async with self.semaphore:
            return await self.client.audio.speech.create(
                model=model,
                voice=voice,
                input=input_text,
                **kwargs
            )