"""
场景图生成服务 - 为每个场景生成无人物的环境参考图
"""
import asyncio
from typing import Optional, Dict, Any
from sqlalchemy import select
from sqlalchemy.orm import selectinload, joinedload

from src.core.logging import get_logger
from src.models.movie import MovieScene, MovieScript
from src.models.chapter import Chapter
from src.services.base import BaseService
from src.services.provider.factory import ProviderFactory
from src.services.api_key import APIKeyService
from src.services.image import retry_with_backoff
from src.services.movie_prompts import MoviePromptTemplates

logger = get_logger(__name__)


async def _generate_scene_image_worker(
    scene_data: dict,  # 改为传递场景数据字典
    user_id: str,
    api_key,
    model: str,
    semaphore: asyncio.Semaphore
) -> bool:
    """
    Worker协程 - 为单个场景生成场景图
    使用独立的数据库会话避免并发冲突
    
    Args:
        scene_data: 场景数据字典 {id, order_index, scene, characters, shots}
        user_id: 用户ID
        api_key: API密钥对象
        model: 模型名称
        semaphore: 并发控制信号量
    
    Returns:
        是否成功
    """
    from src.core.database import get_async_db
    from src.services.generation_history_service import GenerationHistoryService
    from src.models.movie import GenerationType, MediaType
    
    async with semaphore:
        # 为每个worker创建独立的数据库会话
        async with get_async_db() as db_session:
            try:
                # 重新加载场景对象（使用新会话）
                scene = await db_session.get(MovieScene, scene_data['id'])
                if not scene:
                    logger.error(f"场景不存在: {scene_data['id']}")
                    return False
                
                # 使用分镜描述生成场景图
                shots_description = scene_data['shots']
                logger.info(f"使用{len(shots_description)}个分镜描述生成场景图 (scene_id={scene.id})")
                
                # 生成场景图prompt
                if shots_description:
                    shots_desc = "\n\n".join([
                        f"Shot {i+1}: {shot}"
                        for i, shot in enumerate(shots_description)
                    ])
                    prompt = MoviePromptTemplates.get_scene_image_prompt_from_shots(shots_desc)
                else:
                    prompt = MoviePromptTemplates.get_scene_image_prompt(scene_data['scene'])
                
                
                # 调用图片生成
                from src.services.provider.factory import ProviderFactory
                provider = ProviderFactory.from_key(api_key)
                
                from src.services.image import retry_with_backoff
                result = await retry_with_backoff(
                    lambda: provider.generate_image(prompt=prompt, model=model)
                )
                
                # 上传图片
                from src.utils.image_utils import extract_and_upload_image
                image_url = await extract_and_upload_image(
                    result=result,
                    user_id=str(user_id),
                    metadata={"scene_id": str(scene.id), "type": "scene_image"}
                )
                
                # 更新场景
                scene.scene_image_url = image_url
                scene.scene_image_prompt = prompt
                await db_session.flush()
                
                # 记录生成历史（使用当前会话）
                history_service = GenerationHistoryService(db_session)
                await history_service.create_history(
                    resource_type=GenerationType.SCENE_IMAGE,
                    resource_id=str(scene.id),
                    prompt=prompt,
                    result_url=image_url,
                    media_type=MediaType.IMAGE,
                    model=model,
                    api_key_id=str(api_key.id)
                )
                
                # 提交当前会话
                await db_session.commit()
                
                logger.info(f"✅ 场景图生成成功: scene_id={scene.id}, url={image_url}")
                return True
                
            except Exception as e:
                await db_session.rollback()
                logger.error(f"Worker 生成场景图失败 [scene_id={scene_data['id']}]: {e}", exc_info=True)
                return False


class SceneImageService(BaseService):
    """场景图生成服务"""

    
    @staticmethod
    def _build_scene_image_prompt(shots_data: list[dict]) -> str:
        """
        根据分镜数据构建场景图提示词
        """
        if not shots_data:
            return MoviePromptTemplates.get_scene_image_prompt("一个空旷的场景") # Fallback for empty shots
        
        # 组合所有分镜描述
        shots_desc = "\n\n".join([
            f"Shot {shot['order_index']}: {shot['shot']}"
            for shot in sorted(shots_data, key=lambda x: x['order_index'])
        ])
        return MoviePromptTemplates.get_scene_image_prompt_from_shots(shots_desc)

    async def generate_scene_image(
        self, 
        scene_id: str, 
        api_key_id: str, 
        model: Optional[str] = None,
        prompt: Optional[str] = None
    ) -> str:
        """
        生成单个场景的场景图
        
        Args:
            scene_id: 场景ID
            api_key_id: API Key ID
            model: 图像模型
            prompt: 自定义提示词（可选）
            
        Returns:
            str: 场景图URL
        """
        # 1. 获取场景（预加载关系）
        stmt = (
            select(MovieScene)
            .where(MovieScene.id == scene_id)
            .options(
                selectinload(MovieScene.shots),  # 加载分镜用于生成场景图
                joinedload(MovieScene.script)
                .joinedload(MovieScript.chapter)
                .joinedload(Chapter.project)
            )
        )
        result = await self.db_session.execute(stmt)
        scene = result.scalar_one_or_none()
        
        if not scene:
            raise ValueError(f"场景不存在: {scene_id}")
        
        # 获取user_id
        user_id = str(scene.script.chapter.project.owner_id)
        
        # 2. 获取 API Key
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id, user_id)
        
        if not api_key:
            raise ValueError(f"API Key 不存在: {api_key_id}")
        
        # 3. 准备场景数据
        scene_data = {
            'id': scene.id,
            'order_index': scene.order_index,
            'scene': scene.scene,
            'characters': scene.characters,
            'shots': [shot.shot for shot in scene.shots if shot.shot]
        }
        
        # 4. 生成场景图（使用独立会话的worker）
        semaphore = asyncio.Semaphore(1)
        success = await _generate_scene_image_worker(
            scene_data, user_id, api_key, model, semaphore
        )
        
        if success:
            # 重新加载场景以获取更新后的URL
            await self.db_session.refresh(scene)
            return scene.scene_image_url
        else:
            raise Exception("生成场景图失败")
    
    async def batch_generate_scene_images(
        self, 
        script_id: str, 
        api_key_id: str, 
        model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        批量生成剧本所有场景的场景图
        
        Args:
            script_id: 剧本ID
            api_key_id: API Key ID
            model: 图像模型
            
        Returns:
            dict: 统计信息 {total: int, success: int, failed: int, message: str}
        """
        # 1. 深度加载
        script = await self.db_session.get(MovieScript, script_id, options=[
            selectinload(MovieScript.scenes).selectinload(MovieScene.shots),  # 加载分镜用于生成场景图
            joinedload(MovieScript.chapter).joinedload(Chapter.project)
        ])
        if not script:
            raise ValueError("剧本不存在")
        
        user_id = script.chapter.project.owner_id
        
        # 2. 准备资源
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id, str(user_id))
        
        # 3. 筛选待处理任务 - 只生成缺少场景图的场景
        tasks = []
        semaphore = asyncio.Semaphore(20)
        
        for scene in script.scenes:
            # 检查是否需要生成场景图
            if not scene.scene_image_url:
                # 提取场景数据（避免在协程中访问ORM对象）
                scene_data = {
                    'id': scene.id,
                    'order_index': scene.order_index,
                    'scene': scene.scene,
                    'characters': scene.characters,
                    'shots': [shot.shot for shot in scene.shots if shot.shot]
                }
                tasks.append(
                    _generate_scene_image_worker(scene_data, user_id, api_key, model, semaphore)
                )
        
        # 4. 无任务则返回
        if not tasks:
            return {"total": 0, "success": 0, "failed": 0, "message": "所有场景已有场景图"}

        # 5. 执行并发
        results = await asyncio.gather(*tasks)
        
        success_count = sum(1 for r in results if r)
        failed_count = len(results) - success_count
        
        # 6. 不需要在这里commit，每个worker已经独立commit了
        
        logger.info(f"批量场景图生成完成: 总计 {len(tasks)}, 成功 {success_count}, 失败 {failed_count}")
        
        return {
            "total": len(tasks),
            "success": success_count,
            "failed": failed_count,
            "message": f"批量生成完成: 成功 {success_count}, 失败 {failed_count}"
        }


__all__ = ["SceneImageService"]
