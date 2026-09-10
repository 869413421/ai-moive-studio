"""
API密钥管理API路由
"""

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user_required
from src.api.schemas.api_key import (
    APIKeyCreate,
    APIKeyDeleteResponse,
    APIKeyListResponse,
    APIKeyResponse,
    APIKeyUpdate,
    APIKeyUsageResponse,
)
from src.core.database import get_db
from src.core.logging import get_logger
from src.models.user import User
from src.services.api_key import APIKeyService

logger = get_logger(__name__)

router = APIRouter()


@router.get("/", response_model=APIKeyListResponse)
async def get_api_keys(
    *,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页大小"),
    provider: Optional[str] = Query(None, description="服务提供商过滤"),
    key_status: Optional[str] = Query(None, description="状态过滤"),
):
    """获取用户的API密钥列表"""
    api_key_service = APIKeyService(db)
    
    api_keys, total = await api_key_service.get_user_api_keys(
        user_id=current_user.id,
        provider=provider,
        key_status=key_status,
        page=page,
        size=size
    )
    
    # 转换为响应模型（密钥已遮罩）
    api_key_responses = [
        APIKeyResponse.from_dict(key.to_dict(include_key=True, mask_key=True))
        for key in api_keys
    ]
    
    total_pages = (total + size - 1) // size
    
    return APIKeyListResponse(
        api_keys=api_key_responses,
        total=total,
        page=page,
        size=size,
        total_pages=total_pages
    )


@router.post("/", response_model=APIKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    *,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
    api_key_data: APIKeyCreate
):
    """创建新的API密钥"""
    api_key_service = APIKeyService(db)
    
    try:
        api_key = await api_key_service.create_api_key(
            user_id=current_user.id,
            name=api_key_data.name,
            provider=api_key_data.provider,
            api_key=api_key_data.api_key,
            base_url=api_key_data.base_url
        )
        
        # 提交事务
        await api_key_service.commit()
        
        # 返回响应（密钥已遮罩）
        return APIKeyResponse.from_dict(api_key.to_dict(include_key=True, mask_key=True))
        
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as e:
        logger.error(f"创建API密钥失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建API密钥失败: {str(e)}"
        )


@router.get("/provider-presets")
async def get_provider_presets(current_user: User = Depends(get_current_user_required)):
    from src.services.provider.registry import PROVIDERS
    return [{'id': key, 'name': value[0], 'base_url': value[1]} for key, value in PROVIDERS.items()]


@router.get("/{key_id}", response_model=APIKeyResponse)
async def get_api_key(
    *,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
    key_id: str
):
    """获取API密钥详情"""
    api_key_service = APIKeyService(db)
    
    api_key = await api_key_service.get_api_key_by_id(key_id, current_user.id)
    
    # 返回响应（密钥已遮罩）
    return APIKeyResponse.from_dict(api_key.to_dict(include_key=True, mask_key=True))


@router.put("/{key_id}", response_model=APIKeyResponse)
async def update_api_key(
    *,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
    key_id: str,
    api_key_data: APIKeyUpdate
):
    """更新API密钥"""
    api_key_service = APIKeyService(db)
    
    try:
        api_key = await api_key_service.update_api_key(
            key_id=key_id,
            user_id=current_user.id,
            name=api_key_data.name,
            base_url=api_key_data.base_url,
            key_status=api_key_data.status
        )
        
        # 提交事务
        await api_key_service.commit()
        
        # 返回响应（密钥已遮罩）
        return APIKeyResponse.from_dict(api_key.to_dict(include_key=True, mask_key=True))
        
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as e:
        logger.error(f"更新API密钥失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新API密钥失败: {str(e)}"
        )


@router.delete("/{key_id}", response_model=APIKeyDeleteResponse)
async def delete_api_key(
    *,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
    key_id: str
):
    """删除API密钥"""
    api_key_service = APIKeyService(db)
    
    try:
        await api_key_service.delete_api_key(key_id, current_user.id)
        
        # 提交事务
        await api_key_service.commit()
        
        return APIKeyDeleteResponse(
            success=True,
            message="删除成功",
            key_id=key_id
        )
        
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as e:
        logger.error(f"删除API密钥失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除API密钥失败: {str(e)}"
        )


@router.get("/{key_id}/usage", response_model=APIKeyUsageResponse)
async def get_api_key_usage(
    *,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
    key_id: str
):
    """获取API密钥使用统计"""
    api_key_service = APIKeyService(db)
    
    api_key = await api_key_service.get_api_key_by_id(key_id, current_user.id)
    
    # 构建使用统计响应
    usage_data = {
        'key_id': api_key.id,
        'provider': api_key.provider,
        'name': api_key.name,
        'usage_count': api_key.usage_count,
        'last_used_at': api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        'status': api_key.status,
        'created_at': api_key.created_at.isoformat()
    }
    
    return APIKeyUsageResponse(**usage_data)


@router.get("/{key_id}/models", response_model=List[str])
async def get_api_key_models(
    *,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
    key_id: str,
    type: str = Query("text", description="模型类型: text, image 或 video")
):
    """获取API密钥可用的模型列表"""
    api_key_service = APIKeyService(db)
    
    # 验证key存在且属于当前用户
    await api_key_service.get_api_key_by_id(key_id, current_user.id)
    
    try:
        return await api_key_service.get_models(key_id, current_user.id, type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/{key_id}/model-catalog")
async def get_model_catalog(key_id: str, refresh: bool = False, include_hidden: bool = False,
                            current_user: User = Depends(get_current_user_required),
                            db: AsyncSession = Depends(get_db)):
    try:
        return await APIKeyService(db).get_model_catalog(key_id, current_user.id, refresh, include_hidden)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


__all__ = ["router"]
