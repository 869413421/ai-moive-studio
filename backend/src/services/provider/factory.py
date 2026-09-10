# src/services/providers/factory.py

from .openai_provider import OpenAIProvider
from .deepseek_provider import DeepSeekProvider
from .volcengine_provider import VolcengineProvider
from .siliconflow_provider import SiliconFlowProvider
from .custom_provider import CustomProvider
from .base import BaseLLMProvider


class ProviderFactory:

    @staticmethod
    def create(provider: str, api_key: str, **kwargs) -> BaseLLMProvider:
        provider = provider.lower()

        match provider:
            case "openai":
                return OpenAIProvider(api_key, kwargs.get("max_concurrency", 5))
            case "deepseek":
                return DeepSeekProvider(api_key, kwargs.get("max_concurrency", 5))
            case "volcengine":
                return VolcengineProvider(api_key, kwargs.get("max_concurrency", 5))
            case "siliconflow":
                return SiliconFlowProvider(api_key, kwargs.get("max_concurrency", 5))
            case "custom":
                return CustomProvider(api_key, kwargs.get("max_concurrency", 5),
                                      kwargs.get("base_url", "https://api.aiconapi.me/v1"))
            case "vectorengine":
                from .vector_engine_provider import VectorEngineProvider
                return VectorEngineProvider(api_key, kwargs.get("base_url", "https://api.vectorengine.ai/v1")) # type: ignore
            case "twelvelabs":
                from .twelvelabs_provider import TwelveLabsProvider
                return TwelveLabsProvider(api_key, kwargs.get("base_url", "https://api.twelvelabs.io/v1.3")) # type: ignore
            case _:
                raise ValueError(f"未知 provider: {provider}")
