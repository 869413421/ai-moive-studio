"""One construction path for configured protocol adapters."""
from .gateway import GatewayProvider
from .registry import connection


class ProviderFactory:
    @staticmethod
    def create(provider: str, api_key: str, **kwargs) -> GatewayProvider:
        return GatewayProvider(api_key=api_key, provider=provider, **kwargs)

    @staticmethod
    def from_key(key, *, context=None, max_concurrency=5):
        if key.status != 'active':
            raise ValueError('此 API 密钥未启用')
        if context:
            if context.get('version') != 1:
                raise ValueError('视频任务协议版本不受支持')
            # Credentials must never be sent to a saved host after the key was moved.
            current = connection(key.provider, key.base_url)
            if current['base_url'] != context.get('base_url') or key.provider != context.get('provider'):
                raise ValueError('密钥连接已变更，请恢复提交任务时的连接后查询')
        return GatewayProvider(api_key=key.get_api_key(), provider=key.provider,
                               base_url=key.base_url, context=context, max_concurrency=max_concurrency)

    @staticmethod
    def resume_video(key, context):
        if context:
            return ProviderFactory.from_key(key, context=context)
        # Only historical tasks lacking a snapshot use the old query contract.
        if key.status != 'active':
            raise ValueError('此 API 密钥未启用')
        from .legacy_video import LegacyVideoQuery
        return LegacyVideoQuery(key.get_api_key(), key.base_url)
