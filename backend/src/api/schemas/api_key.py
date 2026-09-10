"""
API密钥相关的Pydantic模式
"""

from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .base import PaginatedResponse, UUIDMixin


class APIKeyCreate(BaseModel):
    """创建API密钥请求模型"""
    name: str = Field(..., min_length=1, max_length=100, description="密钥名称")
    provider: str = Field(..., min_length=1, max_length=50, description="服务提供商")
    api_key: str = Field(..., min_length=1, description="API密钥")
    base_url: Optional[str] = Field(None, max_length=500, description="API基础URL")

    @field_validator('provider')
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """验证服务提供商"""
        valid_providers = ['openai', 'azure', 'google', 'baidu', 'alibaba', 'volcengine', 'custom', 'deepseek','siliconflow','twelvelabs']
        if v.lower() not in valid_providers:
            raise ValueError(f"无效的服务提供商。支持的提供商: {', '.join(valid_providers)}")
        return v.lower()

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "My OpenAI Key",
                "provider": "openai",
                "api_key": "sk-proj-1234567890abcdef",
                "base_url": "https://api.openai.com/v1"
            }
        }
    }


class APIKeyUpdate(BaseModel):
    """更新API密钥请求模型"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="密钥名称")
    base_url: Optional[str] = Field(None, max_length=500, description="API基础URL")
    status: Optional[str] = Field(None, description="密钥状态")

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        """验证状态"""
        if v is not None:
            valid_statuses = ['active', 'inactive', 'expired']
            if v.lower() not in valid_statuses:
                raise ValueError(f"无效的状态。支持的状态: {', '.join(valid_statuses)}")
            return v.lower()
        return v

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Updated Key Name",
                "base_url": "https://api.openai.com/v1",
                "status": "active"
            }
        }
    }


class APIKeyResponse(UUIDMixin):
    """API密钥响应模型"""
    id: UUID = Field(..., description="密钥ID")
    user_id: UUID = Field(..., description="用户ID")
    provider: str = Field(..., description="服务提供商")
    name: str = Field(..., description="密钥名称")
    api_key: str = Field(..., description="遮罩后的API密钥")
    base_url: Optional[str] = Field(None, description="API基础URL")
    status: str = Field(..., description="密钥状态")
    last_used_at: Optional[str] = Field(None, description="最后使用时间")
    usage_count: int = Field(0, description="使用次数")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")

    model_config = {"from_attributes": True}

    @classmethod
    def from_dict(cls, data: dict, mask_key: bool = True) -> "APIKeyResponse":
        """从字典创建响应对象，处理时间格式和密钥遮罩"""
        # 处理时间字段
        time_fields = ['created_at', 'updated_at', 'last_used_at']
        for field in time_fields:
            if field in data and data[field] is not None:
                if hasattr(data[field], 'isoformat'):
                    data[field] = data[field].isoformat()
                elif isinstance(data[field], str):
                    pass
                else:
                    data[field] = str(data[field])

        # 确保api_key字段存在（应该已经是遮罩的）
        if 'api_key' not in data or not data['api_key']:
            data['api_key'] = '****'

        return cls(**data)

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "uuid-string",
                "user_id": "user-uuid",
                "provider": "openai",
                "name": "My OpenAI Key",
                "api_key": "sk-p****",
                "base_url": "https://api.openai.com/v1",
                "status": "active",
                "last_used_at": "2024-01-01T12:00:00Z",
                "usage_count": 42,
                "created_at": "2024-01-01T10:00:00Z",
                "updated_at": "2024-01-01T12:00:00Z"
            }
        }
    }


class APIKeyListResponse(PaginatedResponse):
    """API密钥列表响应模型"""
    api_keys: List[APIKeyResponse] = Field(..., description="API密钥列表")

    model_config = {
        "json_schema_extra": {
            "example": {
                "api_keys": [
                    {
                        "id": "uuid-string",
                        "provider": "openai",
                        "name": "My OpenAI Key",
                        "status": "active",
                        "created_at": "2024-01-01T10:00:00Z"
                    }
                ],
                "total": 10,
                "page": 1,
                "size": 20,
                "total_pages": 1
            }
        }
    }


class APIKeyDeleteResponse(BaseModel):
    """API密钥删除响应模型"""
    success: bool = Field(True, description="删除是否成功")
    message: str = Field("删除成功", description="响应消息")
    key_id: UUID = Field(..., description="删除的密钥ID")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "message": "删除成功",
                "key_id": "uuid-string"
            }
        }
    }


class APIKeyUsageResponse(BaseModel):
    """API密钥使用统计响应模型"""
    key_id: UUID = Field(..., description="密钥ID")
    provider: str = Field(..., description="服务提供商")
    name: str = Field(..., description="密钥名称")
    usage_count: int = Field(..., description="总使用次数")
    last_used_at: Optional[str] = Field(None, description="最后使用时间")
    status: str = Field(..., description="当前状态")
    created_at: str = Field(..., description="创建时间")

    model_config = {
        "json_schema_extra": {
            "example": {
                "key_id": "uuid-string",
                "provider": "openai",
                "name": "My OpenAI Key",
                "usage_count": 42,
                "last_used_at": "2024-01-01T12:00:00Z",
                "status": "active",
                "created_at": "2024-01-01T10:00:00Z"
            }
        }
    }


__all__ = [
    "APIKeyCreate",
    "APIKeyUpdate",
    "APIKeyResponse",
    "APIKeyListResponse",
    "APIKeyDeleteResponse",
    "APIKeyUsageResponse",
]
