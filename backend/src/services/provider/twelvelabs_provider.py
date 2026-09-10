from typing import Any, Dict, List, Optional

import httpx

from src.core.logging import get_logger
from src.services.provider.base import log_provider_call

logger = get_logger(__name__)


class TwelveLabsProvider:
    """
    TwelveLabs API 提供商 (api.twelvelabs.io)

    面向视频理解的可选 Provider：
    - Pegasus: 对视频做内容理解 / 分析（analyze），用于自动生成分镜描述、
      镜头摘要、内容审核等创作辅助。
    - Marengo: 生成视频 / 文本的多模态向量（512 维），用于素材检索、
      画布节点之间的语义匹配与去重。

    与其它 Provider 一样，这是一个纯粹的 HTTP wrapper，不含任何业务逻辑，
    完全可选：未配置 TwelveLabs API Key 时系统行为不变。
    免费 API Key 可在 https://twelvelabs.io 获取。
    """

    # REST 端点要求 multipart/form-data；Marengo 向量在响应里的字段名是 'float'。
    DEFAULT_EMBED_MODEL = "marengo3.0"
    DEFAULT_ANALYZE_MODEL = "pegasus1.5"

    def __init__(self, api_key: str, base_url: str = "https://api.twelvelabs.io/v1.3"):
        self.api_key = api_key
        # 规范化 base_url: 去掉结尾斜杠，便于拼接
        self.base_url = base_url.rstrip("/")
        self.headers = {"x-api-key": api_key}
        # 视频处理可能较慢，给足超时
        self.timeout = httpx.Timeout(300.0, connect=20.0)

    @log_provider_call("embed_text")
    async def embed_text(
        self,
        text: str,
        model: str = DEFAULT_EMBED_MODEL,
        **kwargs: Any,
    ) -> List[float]:
        """
        使用 Marengo 生成文本的多模态向量（512 维）。

        注意：/v1.3/embed 即使是纯文本请求也要求 multipart/form-data；
        因此这里用 files=（(None, value) 元组）强制 httpx 走 multipart 编码，
        而不是默认的 x-www-form-urlencoded。
        """
        url = f"{self.base_url}/embed"
        fields = {"model_name": model, "text": text}
        fields.update(kwargs)
        files = {k: (None, str(v)) for k, v in fields.items()}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(url, headers=self.headers, files=files)
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(f"TwelveLabs Embed Failed: {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"TwelveLabs Embed Error: {e}")
                raise

        return _extract_embedding(response.json())

    @log_provider_call("embed_video")
    async def embed_video(
        self,
        video_url: str,
        model: str = DEFAULT_EMBED_MODEL,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        使用 Marengo 为视频创建向量任务（异步）。

        返回任务信息（含 task id），实际向量需轮询 /embed/tasks/{id}/status 获取。
        公开 URL 最大支持 4GB。/v1.3/embed 同样要求 multipart/form-data。
        """
        url = f"{self.base_url}/embed/tasks"
        fields = {"model_name": model, "video_url": video_url}
        fields.update(kwargs)
        files = {k: (None, str(v)) for k, v in fields.items()}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(url, headers=self.headers, files=files)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"TwelveLabs Embed Video Failed: {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"TwelveLabs Embed Video Error: {e}")
                raise

    @log_provider_call("analyze")
    async def analyze(
        self,
        prompt: str,
        video_url: Optional[str] = None,
        asset_id: Optional[str] = None,
        model: str = DEFAULT_ANALYZE_MODEL,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        使用 Pegasus 对视频做内容理解 / 分析。

        Pegasus 1.5 不接受裸 video_id，必须提供公开 URL 或已上传的 asset_id；
        被分析的视频时长需 >= 4 秒，max_tokens 取值范围 512~98304。
        本地文件上传（assets, method=direct）上限 200MB，公开 URL 上限 4GB。
        """
        if not video_url and not asset_id:
            raise ValueError("必须提供 video_url 或 asset_id 之一")

        if video_url:
            video: Dict[str, Any] = {"type": "url", "url": video_url}
        else:
            video = {"type": "asset_id", "asset_id": asset_id}

        url = f"{self.base_url}/analyze"
        payload = {
            "model_name": model,
            "video": video,
            "prompt": prompt,
            "max_tokens": max_tokens,
        }
        payload.update(kwargs)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(url, headers=self.headers, json=payload)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"TwelveLabs Analyze Failed: {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"TwelveLabs Analyze Error: {e}")
                raise


def _extract_embedding(payload: Dict[str, Any]) -> List[float]:
    """从 /v1.3/embed 响应中提取文本向量。REST 原始字段名为 'float'。"""
    segments = (payload.get("text_embedding") or {}).get("segments") or []
    if not segments:
        raise ValueError(f"TwelveLabs 响应中未找到向量: {payload}")
    first = segments[0]
    vector = first.get("float") or first.get("float_") or first.get("embedding")
    if not vector:
        raise ValueError(f"TwelveLabs 向量字段为空: {first}")
    return vector
