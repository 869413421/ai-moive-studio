"""
API密钥数据模型 - 按照migration文件实现
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID

from src.core.logging import get_logger
from src.models.base import BaseModel
from src.utils.encryption import decrypt_api_key, encrypt_api_key, mask_api_key

logger = get_logger(__name__)


class APIKeyStatus(str, Enum):
    """API密钥状态枚举"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    EXPIRED = "expired"


class APIKeyProvider(str, Enum):
    """服务提供商枚举"""
    OPENAI = "openai"
    AZURE = "azure"
    GOOGLE = "google"
    BAIDU = "baidu"
    ALIBABA = "alibaba"
    VOLCENGINE = "volcengine"
    CUSTOM = "custom"
    SILICONFLOW = "siliconflow"
    ATLASCLOUD = "atlascloud"


class APIKey(BaseModel):
    """API密钥模型 - 存储用户配置的AI服务API密钥"""
    __tablename__ = 'api_keys'

    # 基础字段
    user_id = Column(PostgreSQLUUID(as_uuid=True), nullable=False, index=True, comment="用户ID")
    provider = Column(String(50), nullable=False, index=True, comment="服务提供商")
    name = Column(String(100), nullable=False, comment="密钥名称")
    api_key = Column(Text, nullable=False, comment="API密钥（加密存储）")
    base_url = Column(String(500), nullable=True, comment="API基础URL")

    # 状态字段
    status = Column(
        String(20),
        nullable=False,
        default=APIKeyStatus.ACTIVE,
        server_default='active',
        index=True,
        comment="密钥状态：active（激活）、inactive（未激活）、expired（过期）"
    )

    # 使用统计
    last_used_at = Column(DateTime(timezone=True), nullable=True, comment="最后使用时间")
    usage_count = Column(Integer, nullable=False, default=0, server_default='0', comment="使用次数统计")

    # 时间戳由BaseModel提供: created_at, updated_at

    # 索引定义
    __table_args__ = (
        {'comment': 'API密钥表 - 存储用户配置的AI服务API密钥'},
    )

    def set_api_key(self, plain_key: str) -> None:
        """
        设置API密钥（自动加密）
        
        Args:
            plain_key: 明文API密钥
        """
        try:
            self.api_key = encrypt_api_key(plain_key)
            logger.debug(f"API密钥已加密存储: {self.id}")
        except Exception as e:
            logger.error(f"API密钥加密失败: {e}")
            raise

    def get_api_key(self) -> str:
        """
        获取API密钥（自动解密）
        
        Returns:
            明文API密钥
        """
        try:
            return decrypt_api_key(self.api_key)
        except Exception as e:
            logger.error(f"API密钥解密失败: {e}")
            raise

    def get_masked_key(self, visible_chars: int = 4) -> str:
        """
        获取遮罩后的API密钥
        
        Args:
            visible_chars: 可见字符数量
            
        Returns:
            遮罩后的API密钥
        """
        try:
            plain_key = self.get_api_key()
            return mask_api_key(plain_key, visible_chars)
        except Exception as e:
            logger.error(f"API密钥遮罩失败: {e}")
            return "****"

    def update_usage(self) -> None:
        """更新使用统计"""
        self.usage_count += 1
        self.last_used_at = datetime.utcnow()
        logger.debug(f"API密钥使用次数更新: {self.id} - {self.usage_count}")

    def is_active(self) -> bool:
        """检查密钥是否激活"""
        return self.status == APIKeyStatus.ACTIVE

    def activate(self) -> None:
        """激活密钥"""
        self.status = APIKeyStatus.ACTIVE
        logger.info(f"API密钥已激活: {self.id}")

    def deactivate(self) -> None:
        """停用密钥"""
        self.status = APIKeyStatus.INACTIVE
        logger.info(f"API密钥已停用: {self.id}")

    def mark_expired(self) -> None:
        """标记为过期"""
        self.status = APIKeyStatus.EXPIRED
        logger.info(f"API密钥已过期: {self.id}")

    @classmethod
    async def get_by_user_id(cls, db_session, user_id: str):
        """
        获取用户的所有API密钥
        
        Args:
            db_session: 数据库会话
            user_id: 用户ID
            
        Returns:
            API密钥列表
        """
        from sqlalchemy import select

        result = await db_session.execute(
            select(cls).filter(cls.user_id == _normalize_uuid(user_id)).order_by(cls.created_at.desc())
        )
        return result.scalars().all()

    @classmethod
    async def get_by_id_and_user(cls, db_session, key_id: str, user_id: str):
        """
        根据ID和用户获取API密钥
        
        Args:
            db_session: 数据库会话
            key_id: 密钥ID
            user_id: 用户ID
            
        Returns:
            API密钥对象或None
        """
        from sqlalchemy import select

        result = await db_session.execute(
            select(cls).filter(
                cls.id == _normalize_uuid(key_id),
                cls.user_id == _normalize_uuid(user_id)
            )
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_active_by_provider(cls, db_session, user_id: str, provider: str):
        """
        获取用户指定提供商的激活密钥
        
        Args:
            db_session: 数据库会话
            user_id: 用户ID
            provider: 服务提供商
            
        Returns:
            API密钥列表
        """
        from sqlalchemy import select

        result = await db_session.execute(
            select(cls).filter(
                cls.user_id == _normalize_uuid(user_id),
                cls.provider == provider,
                cls.status == APIKeyStatus.ACTIVE
            ).order_by(cls.created_at.desc())
        )
        return result.scalars().all()

    def to_dict(self, include_key: bool = False, mask_key: bool = True) -> dict:
        """
        转换为字典
        
        Args:
            include_key: 是否包含API密钥
            mask_key: 是否遮罩密钥（仅当include_key=True时有效）
            
        Returns:
            字典表示
        """
        data = super().to_dict(exclude=['api_key'])

        if include_key:
            if mask_key:
                data['api_key'] = self.get_masked_key()
            else:
                data['api_key'] = self.get_api_key()

        return data


__all__ = [
    "APIKey",
    "APIKeyStatus",
    "APIKeyProvider",
]


def _normalize_uuid(value):
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
