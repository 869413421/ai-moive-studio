import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.provider.factory import ProviderFactory
from src.services.provider.twelvelabs_provider import (
    TwelveLabsProvider,
    _extract_embedding,
)


class TestTwelveLabsProvider:
    def test_factory_creates_provider(self):
        provider = ProviderFactory.create("twelvelabs", api_key="test-key")
        assert isinstance(provider, TwelveLabsProvider)
        assert provider.headers["x-api-key"] == "test-key"
        # base_url 应去掉结尾斜杠
        assert provider.base_url == "https://api.twelvelabs.io/v1.3"

    def test_extract_embedding_uses_rest_float_key(self):
        # REST /v1.3/embed 原始字段名是 'float'，且向量为 512 维
        payload = {"text_embedding": {"segments": [{"float": [0.1] * 512}]}}
        vector = _extract_embedding(payload)
        assert len(vector) == 512

    def test_extract_embedding_raises_on_empty(self):
        with pytest.raises(ValueError):
            _extract_embedding({"text_embedding": {"segments": []}})

    @pytest.mark.asyncio
    async def test_embed_text_posts_multipart_form_data(self):
        provider = TwelveLabsProvider(api_key="test-key")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "text_embedding": {"segments": [{"float": [0.0] * 512}]}
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch(
            "src.services.provider.twelvelabs_provider.httpx.AsyncClient"
        ) as client_cls:
            client_cls.return_value.__aenter__.return_value = mock_client
            vector = await provider.embed_text("a dramatic sunset")

        assert len(vector) == 512
        _, kwargs = mock_client.post.call_args
        # /v1.3/embed 必须用 multipart/form-data：用 files=（(None, value) 元组）
        # 强制 httpx 走 multipart，而不是 json= 或默认的 urlencoded
        assert "files" in kwargs and "json" not in kwargs
        files = kwargs["files"]
        assert files["model_name"] == (None, "marengo3.0")
        assert files["text"] == (None, "a dramatic sunset")

    @pytest.mark.asyncio
    async def test_analyze_requires_a_video_source(self):
        provider = TwelveLabsProvider(api_key="test-key")
        with pytest.raises(ValueError):
            await provider.analyze(prompt="describe")

    @pytest.mark.asyncio
    async def test_analyze_builds_url_video_payload(self):
        provider = TwelveLabsProvider(api_key="test-key")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"data": "a clip of an ocean sunset"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch(
            "src.services.provider.twelvelabs_provider.httpx.AsyncClient"
        ) as client_cls:
            client_cls.return_value.__aenter__.return_value = mock_client
            result = await provider.analyze(
                prompt="Describe this video.",
                video_url="https://example.com/clip.mp4",
            )

        assert result["data"] == "a clip of an ocean sunset"
        _, kwargs = mock_client.post.call_args
        payload = kwargs["json"]
        assert payload["model_name"] == "pegasus1.5"
        assert payload["video"] == {
            "type": "url",
            "url": "https://example.com/clip.mp4",
        }
        # Pegasus 1.5 要求 max_tokens 在 512~98304 之间
        assert payload["max_tokens"] >= 512


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("TWELVELABS_API_KEY"),
    reason="需要 TWELVELABS_API_KEY 环境变量才能进行真实 API 调用",
)
class TestTwelveLabsProviderLive:
    @pytest.mark.asyncio
    async def test_marengo_text_embedding_is_512_dim(self):
        provider = TwelveLabsProvider(api_key=os.environ["TWELVELABS_API_KEY"])
        vector = await provider.embed_text("a dramatic sunset over the ocean")
        assert len(vector) == 512
        assert all(isinstance(x, (int, float)) for x in vector)
