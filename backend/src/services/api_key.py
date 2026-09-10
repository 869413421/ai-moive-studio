"""
API密钥服务层 - 处理API密钥的业务逻辑
"""

import uuid
from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select, update

from src.core.exceptions import NotFoundError
from src.core.logging import get_logger
from src.models.api_key import APIKey, APIKeyStatus
from src.models.movie import MovieGenerationHistory
from src.services.base import BaseService

logger = get_logger(__name__)


class APIKeyService(BaseService):
    """API密钥服务类"""

    async def create_api_key(
            self,
            user_id: str,
            name: str,
            provider: str,
            api_key: str,
            base_url: Optional[str] = None
    ) -> APIKey:
        """
        创建新的API密钥
        
        Args:
            user_id: 用户ID
            name: 密钥名称
            provider: 服务提供商
            api_key: API密钥（明文）
            base_url: API基础URL
            
        Returns:
            创建的API密钥对象
        """

        # 创建API密钥对象
        new_key = APIKey(
            user_id=_normalize_uuid(user_id),
            name=name,
            provider=provider.lower(),
            base_url=base_url,
            status=APIKeyStatus.ACTIVE
        )

        # 设置加密的API密钥
        new_key.set_api_key(api_key)

        # 保存到数据库
        self.db_session.add(new_key)
        await self.flush()
        await self.refresh(new_key)

        logger.info(f"创建API密钥成功: {new_key.id} (用户: {user_id}, 提供商: {provider})")
        return new_key

    async def get_user_api_keys(
            self,
            user_id: str,
            provider: Optional[str] = None,
            key_status: Optional[str] = None,
            page: int = 1,
            size: int = 20
    ) -> Tuple[List[APIKey], int]:
        """
        获取用户的API密钥列表（分页）
        
        Args:
            user_id: 用户ID
            provider: 服务提供商过滤
            key_status: 状态过滤
            page: 页码
            size: 每页大小
            
        Returns:
            (API密钥列表, 总数)
        """

        # 构建查询条件
        conditions = [APIKey.user_id == _normalize_uuid(user_id)]

        if provider:
            conditions.append(APIKey.provider == provider.lower())

        if key_status:
            conditions.append(APIKey.status == key_status.lower())

        # 查询总数
        count_query = select(func.count()).select_from(APIKey).where(and_(*conditions))
        total_result = await self.db_session.execute(count_query)
        total = total_result.scalar()

        # 查询数据
        query = (
            select(APIKey)
            .where(and_(*conditions))
            .order_by(APIKey.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )

        result = await self.db_session.execute(query)
        api_keys = result.scalars().all()

        logger.debug(f"获取用户API密钥列表: 用户={user_id}, 总数={total}, 页={page}")
        return list(api_keys), total

    async def get_api_key_by_id(self, key_id: str, user_id: Optional[str] = None) -> APIKey:
        """
        根据ID获取API密钥
        
        Args:
            key_id: 密钥ID
            user_id: 用户ID（可选，如果不提供则不过滤用户）
            
        Returns:
            API密钥对象
            
        Raises:
            HTTPException: 密钥不存在或无权访问
        """
        if user_id:
            api_key = await APIKey.get_by_id_and_user(
                self.db_session,
                _normalize_uuid(key_id),
                _normalize_uuid(user_id),
            )
        else:
            # 不过滤用户，直接通过ID查询
            stmt = select(APIKey).where(APIKey.id == _normalize_uuid(key_id))
            result = await self.db_session.execute(stmt)
            api_key = result.scalar_one_or_none()

        if not api_key:
            raise NotFoundError("未找到到APIKEY", resource_id=key_id, resource_type="api_key")

        return api_key

    async def update_api_key(
            self,
            key_id: str,
            user_id: str,
            name: Optional[str] = None,
            base_url: Optional[str] = None,
            key_status: Optional[str] = None
    ) -> APIKey:
        """
        更新API密钥
        
        Args:
            key_id: 密钥ID
            user_id: 用户ID
            name: 新名称
            base_url: 新基础URL
            key_status: 新状态
            
        Returns:
            更新后的API密钥对象
        """

        # 获取API密钥
        api_key = await self.get_api_key_by_id(key_id, user_id)

        # 更新字段
        if name is not None:
            api_key.name = name

        if base_url is not None:
            api_key.base_url = base_url

        if key_status is not None:
            api_key.status = key_status.lower()

        await self.flush()
        await self.refresh(api_key)

        logger.info(f"更新API密钥成功: {key_id}")
        return api_key

    async def delete_api_key(self, key_id: str, user_id: str) -> None:
        """
        删除API密钥
        
        Args:
            key_id: 密钥ID
            user_id: 用户ID
        """

        # 获取API密钥
        api_key = await self.get_api_key_by_id(key_id, user_id)

        # 保留生成历史，但解除对已删除密钥的引用。
        await self.db_session.execute(
            update(MovieGenerationHistory)
            .where(MovieGenerationHistory.api_key_id == api_key.id)
            .values(api_key_id=None)
        )

        # 删除
        await self.db_session.delete(api_key)
        await self.flush()

        logger.info(f"删除API密钥成功: {key_id}")

    async def update_usage(self, key_id: str, user_id: str) -> APIKey:
        """
        更新API密钥使用统计
        
        Args:
            key_id: 密钥ID
            user_id: 用户ID
            
        Returns:
            更新后的API密钥对象
        """
        api_key = await self.get_api_key_by_id(key_id, user_id)
        api_key.update_usage()

        await self.flush()
        await self.refresh(api_key)

        logger.debug(f"更新API密钥使用统计: {key_id}, 使用次数: {api_key.usage_count}")
        return api_key

    async def get_active_keys_by_provider(
            self,
            user_id: str,
            provider: str
    ) -> List[APIKey]:
        """
        获取用户指定提供商的激活密钥
        
        Args:
            user_id: 用户ID
            provider: 服务提供商
            
        Returns:
            激活的API密钥列表
        """
        api_keys = await APIKey.get_active_by_provider(
            self.db_session,
            user_id,
            provider.lower()
        )

        logger.debug(f"获取激活密钥: 用户={user_id}, 提供商={provider}, 数量={len(api_keys)}")
        return api_keys


    async def get_models(self, key_id: str, user_id: str, model_type: str = "text") -> List[str]:
        """
        获取API密钥可用的模型列表
        
        Args:
            key_id: API密钥ID
            user_id: 用户ID
            model_type: 模型类型 (text/image/video/audio)
            
        Returns:
            List[str]: 模型列表
        """
        # 验证key存在且属于当前用户
        api_key = await self.get_api_key_by_id(key_id, user_id)
        
        provider = api_key.provider.lower()
        
        # SiliconFlow provider - 从API获取模型列表
        if provider == 'siliconflow':
            import httpx
            try:
                # 获取解密后的key
                decrypted_key = api_key.get_api_key()
                
                async with httpx.AsyncClient() as client:
                    # SiliconFlow API docs suggest query param 'type' or 'sub_type' for filtering
                    # But to be safe, we fetch all and filter manually
                    response = await client.get(
                        "https://api.siliconflow.cn/v1/models",
                        headers={"Authorization": f"Bearer {decrypted_key}"},
                        timeout=10.0
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        models = data.get("data", [])
                        
                        # 额外进行一次客户端代码过滤，确保类型一致
                        filtered_models = []
                        for m in models:
                            m_id = m.get("id", "")
                            # SiliconFlow models have 'type' or 'sub_type' field
                            m_type = (m.get("type") or m.get("sub_type") or "").lower()
                            
                            if model_type == "text":
                                if m_type in ["chat", "text", "llm"]:
                                    filtered_models.append(m_id)
                            elif model_type == "image":
                                if m_type in ["image", "text-to-image"]:
                                    filtered_models.append(m_id)
                            elif model_type == "video":
                                if m_type in ["video", "text-to-video"]:
                                    filtered_models.append(m_id)
                            elif model_type == "audio":
                                if m_type in ["audio", "text-to-speech", "tts"]:
                                    filtered_models.append(m_id)
                            else:
                                filtered_models.append(m_id)
                        
                        # 如果没有通过类型过滤出结果，且 model_type 为 image/video，
                        # 尝试通过 ID 关键字匹配作为兜底
                        if not filtered_models and models:
                            if model_type == "image":
                                filtered_models = [m["id"] for m in models if "flux" in m["id"].lower() or "sd" in m["id"].lower() or "kolors" in m["id"].lower()]
                            elif model_type == "video":
                                filtered_models = [m["id"] for m in models if "video" in m["id"].lower() or "svd" in m["id"].lower()]
                        
                        # 如果还是没有，返回所有（原行为）或前几个
                        if not filtered_models:
                            return [m["id"] for m in models[:20]]
                             
                        return filtered_models
                    else:
                        logger.error(f"获取SiliconFlow模型失败: {response.text}")
                        return []
            except Exception as e:
                logger.error(f"获取SiliconFlow模型异常: {e}")
                return []
        
        # Custom provider - 返回预定义模型列表
        elif provider == 'custom':
            if model_type == "image":
                return ['gemini-3.1-flash-image-preview','gemini-3-pro-image-preview']
            elif model_type == "audio":
                return ['gpt-4o-mini-tts', 'tts-1']
            elif model_type == "video":
                return [
                    'veo3.1',
                    'veo3.1-components',
                    'veo3.1-fast',
                    'veo3.1-4k',
                    'veo3.1-components-4k'
                ]
            else:  # text
                return ['gemini-3.1-flash-lite-preview','gemini-3.1-pro-preview']
        
        # Other provider defaults
        elif provider == 'openai':
            if model_type == "image":
                return ['dall-e-3', 'dall-e-2']
            elif model_type == "text":
                return ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo']
            elif model_type == "audio":
                return ['tts-1', 'tts-1-hd', 'whisper-1']
        
        elif provider == 'deepseek':
            if model_type == "text":
                return ['deepseek-chat', 'deepseek-reasoner']

        elif provider == 'google':
            if model_type == "text":
                return ['gemini-1.5-pro', 'gemini-1.5-flash']
            elif model_type == "image":
                return ['imagen-3']

        # TwelveLabs - 视频理解(Pegasus) 与 多模态向量(Marengo)
        elif provider == 'twelvelabs':
            if model_type == "video":
                return ['pegasus1.5']
            elif model_type == "embedding":
                return ['marengo3.0']

        return []


__all__ = [
    "APIKeyService",
]


def _normalize_uuid(value):
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
