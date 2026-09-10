"""
视觉身份服务 - 负责角色形象固化（一致性）和场景/首帧图像生成
"""
import asyncio
import uuid
import io
import aiohttp
from typing import List, Optional, Any, Dict
from sqlalchemy import select
from sqlalchemy.orm import selectinload, joinedload
from fastapi import UploadFile

from src.core.logging import get_logger
from src.models.movie import MovieCharacter, MovieShot, MovieScene, MovieScript
from src.models.chapter import Chapter
from src.services.base import BaseService
from src.services.provider.factory import ProviderFactory
from src.services.api_key import APIKeyService
from src.utils.storage import get_storage_client
from src.services.image import retry_with_backoff

logger = get_logger(__name__)

# ============================================================
# 辅助函数
# ============================================================

# ============================================================
# 独立 Worker 函数 (参照 image.py 规范)
# ============================================================

async def _generate_keyframe_worker(
    shot: MovieShot,
    chars: List[MovieCharacter],
    user_id: Any,
    api_key,
    model: Optional[str],
    semaphore: asyncio.Semaphore,
    db_session,  # 新增：传入数据库会话
    previous_keyframe_url: Optional[str] = None,
    previous_shot: Optional[MovieShot] = None,
    prompt: Optional[str] = None
):
    """
    单个分镜关键帧生成的 Worker - 负责生成、下载、上传，不负责 Commit
    角色信息直接从shot.characters字段获取
    
    Args:
        shot: 分镜对象
        chars: 角色列表
        user_id: 用户ID
        api_key: API密钥对象
        model: 图像模型
        semaphore: 并发控制信号量
        previous_keyframe_url: 上一个分镜的关键帧URL（用于视觉连续性）
        previous_shot: 上一个分镜对象（用于提示词上下文）
    
    注意：新架构下，每个分镜只有一个关键帧（keyframe_url）
    """
    import base64
    
    async with semaphore:
        try:
            # 1. 构建专业提示词（包含场景、分镜、角色信息、上一帧信息）
            from src.services.keyframe_prompt_builder import KeyframePromptBuilder
            
            # 获取场景信息（shot已经预加载了scene关系）
            scene = shot.scene
            
            final_prompt = KeyframePromptBuilder.build_prompt(
                shot=shot,
                scene=scene,
                characters=chars,
                custom_prompt=None,  # worker中不使用自定义提示词
                previous_shot=previous_shot  # 传入上一帧信息
            )
            
            # 1.5 收集参考图：根据是否有上一帧决定参考策略
            reference_images = []
            
            # 如果有上一帧的关键帧，优先使用它作为参考
            if previous_keyframe_url:
                reference_images.append(previous_keyframe_url)
                logger.info(f'[批量生成] 使用上一帧关键帧作为参考: {previous_keyframe_url}')
            else:
                # 第一个分镜：如果有场景图则使用，没有也可以生成
                if scene.scene_image_url:
                    reference_images.append(scene.scene_image_url)
                    logger.info(f'[批量生成] 第一个分镜，使用场景图作为参考: {scene.scene_image_url}')
                else:
                    logger.info(f'[批量生成] 第一个分镜，没有场景图，仅使用提示词生成')

            
            # 然后添加角色参考图
            if shot.characters:
                # 获取出现在此镜头中的角色
                shot_char_names = shot.characters if isinstance(shot.characters, list) else []
                relevant_chars = [c for c in chars if c.name in shot_char_names]
                
                # 收集角色的参考图URL
                for char in relevant_chars:
                    if char.avatar_url:
                        reference_images.append(char.avatar_url)
                        logger.info(f'[批量生成] 添加角色 {char.name} 的参考图: {char.avatar_url}')
            
            # 2. Provider 调用
            img_provider = ProviderFactory.from_key(api_key)

            logger.info(f"生成分镜 {shot.id} 关键帧, 参考图数量={len(reference_images)}, Prompt: {final_prompt[:100]}...")
            
            # 准备生成参数
            gen_params = {
                "prompt": final_prompt,
                "model": model
            }
            
            # 如果有参考图，添加到参数中
            if reference_images:
                gen_params["reference_images"] = reference_images
            
            result = await retry_with_backoff(
                lambda: img_provider.generate_image(**gen_params)
            )
            
            # 3. 提取并上传图片（使用通用工具函数）
            from src.utils.image_utils import extract_and_upload_image
            
            object_key = await extract_and_upload_image(
                result=result,
                user_id=str(user_id),
                metadata={"shot_id": str(shot.id), "type": "keyframe"}
            )

            # 4. 更新对象属性 (不 Commit) - 使用新的keyframe_url字段
            shot.keyframe_url = object_key
            
            # 5. 创建生成历史记录
            # 使用传入的db_session而不是object_session
            from src.services.generation_history_service import GenerationHistoryService
            from src.models.movie import GenerationType, MediaType
            
            history_service = GenerationHistoryService(db_session)
            await history_service.create_history(
                resource_type=GenerationType.SHOT_KEYFRAME,
                resource_id=str(shot.id),
                result_url=object_key,
                prompt=final_prompt,  # 使用生成时的实际prompt
                media_type=MediaType.IMAGE,
                model=model,
                api_key_id=str(api_key.id) if api_key else None
            )
                
            logger.info(f'[批量生成] 关键帧生成并存储完成: shot_id={shot.id}, key={object_key}')
            return True
            
        except Exception as e:
            logger.error(f'[批量生成] Worker 生成关键帧失败 [shot_id={shot.id}]: {e}')
            return False


class VisualIdentityService(BaseService):
    """
    视觉身份服务
    要求外部注入 AsyncSession。
    """
    
    def __init__(self, db_session: Any):
        super().__init__(db_session)

    async def generate_character_references(self, character_id: str, api_key_id: str, prompt_override: Optional[str] = None) -> List[str]:
        """
        为角色生成一致性参考图 (单条任务)
        """
        character = await self.db_session.get(MovieCharacter, character_id, options=[joinedload(MovieCharacter.project)])
        if not character: raise ValueError("未找到角色")

        owner_id = str(character.project.owner_id)
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id, owner_id)
        
        img_provider = ProviderFactory.from_key(api_key)

        base_prompt = f"Character design sheet, {character.name}, {character.visual_traits}, frontal view, profile view, and back view, high quality digital art, consistent features, neutral background."
        final_prompt = prompt_override or base_prompt

        try:
            response = await retry_with_backoff(
                lambda: img_provider.generate_image(
                    prompt=final_prompt,
                    model=None
                )
            )
            
            from src.utils.image_utils import extract_and_upload_image
            object_key = await extract_and_upload_image(response, owner_id, {"character_id": str(character.id), "type": "reference"})

            character.reference_images = [object_key]
            await self.db_session.commit()
            return [object_key]
            
        except Exception as e:
            logger.error(f"生成角色参考图失败: {e}")
            raise

    async def generate_shot_keyframe(self, shot_id: str, api_key_id: str, model: Optional[str] = None) -> str:
        """为分镜生成关键帧图"""
        shot = await self.db_session.get(MovieShot, shot_id, options=[
            joinedload(MovieShot.scene).joinedload(MovieScene.script).joinedload(MovieScript.chapter).joinedload(Chapter.project)
        ])
        if not shot: raise ValueError("未找到分镜")
        
        project_id = shot.scene.script.chapter.project_id
        user_id = shot.scene.script.chapter.project.owner_id
        
        stmt = select(MovieCharacter).where(MovieCharacter.project_id == project_id)
        chars = (await self.db_session.execute(stmt)).scalars().all()
        
        # 收集角色参考图
        ref_images = _collect_character_references(chars, shot)
        
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id, str(user_id))
        
        storage_client = await get_storage_client()
        semaphore = asyncio.Semaphore(1)
        
        success = await _generate_keyframe_worker(shot, chars, user_id, api_key, model, semaphore, storage_client, ref_images)
        if success:
            await self.db_session.commit()
            return shot.keyframe_url # type: ignore
        else:
            raise Exception("生成分镜关键帧失败")

    # Removed: generate_shot_last_frame - obsolete, shots now only have single keyframe
    # Removed: regenerate_shot_keyframe - use generate_shot_keyframe instead

    async def batch_generate_keyframes(self, script_id: str, api_key_id: str, model: Optional[str] = None) -> dict:
        """
        批量为剧本下的所有分镜生成关键帧
        新架构：按场景分组，场景并发处理，场景内分镜顺序处理
        每个场景使用独立的数据库会话，避免连接冲突
        """
        from src.core.database import get_async_db
        from sqlalchemy.orm import joinedload
        
        # 1. 深度加载剧本和场景（在主会话中）
        script = await self.db_session.get(MovieScript, script_id, options=[
            selectinload(MovieScript.scenes).selectinload(MovieScene.shots),
            joinedload(MovieScript.chapter).joinedload(Chapter.project)
        ])
        if not script: raise ValueError("剧本不存在")
        
        project_id = script.chapter.project_id
        user_id = script.chapter.project.owner_id
        
        # 2. 预加载角色（在主会话中）
        stmt_chars = select(MovieCharacter).where(MovieCharacter.project_id == project_id)
        chars = (await self.db_session.execute(stmt_chars)).scalars().all()

        # 3. 场景图检查已移除 - 关键帧生成不再强制要求场景图
        # 如果有场景图会作为参考，没有也可以生成
        
        # 4. 准备资源
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id, str(user_id))

        # 5. 按场景分组待处理的分镜
        scene_shot_groups = {}
        for scene in script.scenes:
            pending_shots = [shot for shot in scene.shots if not shot.keyframe_url]
            if pending_shots:
                scene_shot_groups[scene.id] = {
                    'scene': scene,
                    'shots': sorted(pending_shots, key=lambda s: s.order_index),
                    'scene_order': scene.order_index
                }
        
        # 6. 无任务则返回
        if not scene_shot_groups:
            return {"total": 0, "success": 0, "failed": 0, "message": "所有分镜已有关键帧"}

        # 7. 定义场景处理函数（每个场景使用独立的数据库会话）
        worker_semaphore = asyncio.Semaphore(20)  # API调用并发限制
        
        async def process_scene_with_session(scene_id: str, scene_data: dict):
            """处理单个场景，使用独立的数据库会话"""
            async with get_async_db() as scene_session:
                try:
                    scene_order = scene_data['scene_order']
                    shot_ids = [shot.id for shot in scene_data['shots']]
                    
                    logger.info(f"开始处理场景 {scene_order}，共 {len(shot_ids)} 个分镜")
                    
                    # 在场景会话中顺序处理分镜
                    previous_keyframe_url = None
                    previous_shot = None
                    success_count = 0
                    failed_count = 0
                    
                    for shot_id in shot_ids:
                        # 在当前会话中重新获取分镜（避免DetachedInstanceError）
                        shot_in_session = await scene_session.get(MovieShot, shot_id, options=[
                            joinedload(MovieShot.scene)
                        ])
                        
                        if not shot_in_session:
                            logger.error(f"场景 {scene_order} 中找不到分镜 {shot_id}")
                            failed_count += 1
                            continue
                        
                        # 生成关键帧
                        try:
                            success = await _generate_keyframe_worker(
                                shot=shot_in_session,
                                chars=chars,
                                user_id=user_id,
                                api_key=api_key,
                                model=model,
                                semaphore=worker_semaphore,
                                db_session=scene_session,  # 传入场景会话
                                previous_keyframe_url=previous_keyframe_url,
                                previous_shot=previous_shot
                            )
                            
                            if success:
                                await scene_session.commit()  # 立即提交
                                previous_keyframe_url = shot_in_session.keyframe_url
                                previous_shot = shot_in_session
                                success_count += 1
                                logger.info(f"场景 {scene_order} 分镜 {shot_in_session.order_index} 生成成功")
                            else:
                                failed_count += 1
                                logger.error(f"场景 {scene_order} 分镜 {shot_in_session.order_index} 生成失败")
                                # 继续处理下一个分镜，但不更新previous引用
                                
                        except Exception as e:
                            failed_count += 1
                            logger.error(f"场景 {scene_order} 分镜 {shot_in_session.order_index} 生成异常: {e}")
                            # 继续处理下一个分镜
                    
                    logger.info(f"场景 {scene_order} 处理完成: 成功 {success_count}, 失败 {failed_count}")
                    return {'success': success_count, 'failed': failed_count}
                    
                except Exception as e:
                    logger.error(f"处理场景 {scene_id} 时出错: {e}")
                    await scene_session.rollback()
                    return {'success': 0, 'failed': len(scene_data['shots'])}
        
        # 8. 并发处理场景（限制并发数为3）
        scene_semaphore = asyncio.Semaphore(3)
        
        async def process_scene_limited(scene_id: str, scene_data: dict):
            async with scene_semaphore:
                return await process_scene_with_session(scene_id, scene_data)
        
        scene_tasks = [
            process_scene_limited(sid, sdata)
            for sid, sdata in scene_shot_groups.items()
        ]
        
        # 9. 执行并收集结果
        results = await asyncio.gather(*scene_tasks, return_exceptions=True)
        
        # 10. 统计结果
        total_success = 0
        total_failed = 0
        
        for result in results:
            if isinstance(result, dict):
                total_success += result.get('success', 0)
                total_failed += result.get('failed', 0)
            else:
                # 异常情况
                logger.error(f"场景处理返回异常: {result}")
        
        total_tasks = sum(len(sdata['shots']) for sdata in scene_shot_groups.values())
        
        logger.info(f"批量关键帧生成完成: 总计 {total_tasks}, 成功 {total_success}, 失败 {total_failed}")
        
        return {
            "total": total_tasks,
            "success": total_success,
            "failed": total_failed,
            "message": f"批量生成完成: 成功 {total_success}, 失败 {total_failed}"
        }


    async def generate_single_keyframe(self, shot_id: str, api_key_id: str, model: str = None, prompt: str = None):
        """
        生成单个分镜的关键帧
        
        Args:
            shot_id: 分镜 ID
            api_key_id: API Key ID
            model: 图像模型
            prompt: 自定义提示词（可选）
            
        Returns:
            str: 关键帧图片 URL
        """
        from src.models.movie import MovieShot, MovieScene, MovieScript
        from src.models.chapter import Chapter
        from src.models.project import Project
        from src.services.api_key import APIKeyService
        from src.services.provider.factory import ProviderFactory
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload, joinedload
        
        # 1. 获取分镜（预加载关系）
        stmt = (
            select(MovieShot)
            .where(MovieShot.id == shot_id)
            .options(
                joinedload(MovieShot.scene)
                .joinedload(MovieScene.script)
                .joinedload(MovieScript.chapter)
                .joinedload(Chapter.project)
            )
        )
        result = await self.db_session.execute(stmt)
        shot = result.scalar_one_or_none()
        
        if not shot:
            raise ValueError(f"分镜不存在: {shot_id}")
        
        # 获取user_id
        user_id = str(shot.scene.script.chapter.project.owner_id)
        
        # 2. 查找上一个分镜（同场景中）
        previous_shot = None
        previous_keyframe_url = None
        
        stmt_prev = (
            select(MovieShot)
            .where(
                MovieShot.scene_id == shot.scene_id,
                MovieShot.order_index < shot.order_index
            )
            .order_by(MovieShot.order_index.desc())
            .limit(1)
        )
        result_prev = await self.db_session.execute(stmt_prev)
        previous_shot = result_prev.scalar_one_or_none()
        
        if previous_shot and previous_shot.keyframe_url:
            previous_keyframe_url = previous_shot.keyframe_url
            logger.info(f"找到上一个分镜 {previous_shot.order_index}，将使用其关键帧作为参考")
        else:
            logger.info("这是场景中的第一个分镜，将使用场景图作为参考")
        
        # 3. 获取 API Key  
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id)
        
        if not api_key:
            raise ValueError(f"API Key 不存在: {api_key_id}")
        
        # 4. 创建提供商
        provider = ProviderFactory.from_key(api_key)
        
        # 5. 生成图像提示词
        # 单个生成时：前端应该先调用构建器生成专业提示词，用户调整后传递过来
        # 如果前端传递了prompt，直接使用（用户已调整）
        # 如果没有传递，使用构建器生成（兜底逻辑）
        if prompt:
            # 前端传递的提示词（用户已调整）
            final_prompt = prompt
            logger.info(f"使用前端传递的自定义提示词（长度: {len(prompt)}字符）")
        else:
            # 兜底：使用构建器生成专业提示词
            from src.services.keyframe_prompt_builder import KeyframePromptBuilder
            from src.models.movie import MovieCharacter
            from sqlalchemy import select
            
            # 获取角色列表
            project_id = shot.scene.script.chapter.project_id
            stmt_chars = select(MovieCharacter).where(MovieCharacter.project_id == project_id)
            chars_result = await self.db_session.execute(stmt_chars)
            chars = chars_result.scalars().all()
            
            final_prompt = KeyframePromptBuilder.build_prompt(
                shot=shot,
                scene=shot.scene,
                characters=list(chars),
                custom_prompt=None,
                previous_shot=previous_shot  # 传入上一帧信息
            )
            logger.info(f"使用构建器生成的专业提示词（长度: {len(final_prompt)}字符）")
        
        # 5.5 获取参考图：根据是否有上一帧决定参考策略
        reference_images = []
        
        # 如果有上一帧的关键帧，优先使用它作为参考
        if previous_keyframe_url:
            reference_images.append(previous_keyframe_url)
            logger.info(f'使用上一帧关键帧作为参考: {previous_keyframe_url}')
        else:
            # 第一个分镜：如果有场景图则使用，没有也可以生成
            if shot.scene.scene_image_url:
                reference_images.append(shot.scene.scene_image_url)
                logger.info(f'第一个分镜，使用场景图作为参考: {shot.scene.scene_image_url}')
            else:
                logger.info(f'第一个分镜，没有场景图，仅使用提示词生成')
        
        # 然后添加角色参考图
        if shot.characters:
            from src.models.movie import MovieCharacter
            # 获取角色对象
            project_id = shot.scene.script.chapter.project_id
            stmt_chars = select(MovieCharacter).where(
                MovieCharacter.project_id == project_id,
                MovieCharacter.name.in_(shot.characters)
            )
            chars_result = await self.db_session.execute(stmt_chars)
            characters = chars_result.scalars().all()
            
            # 收集角色的参考图URL
            for char in characters:
                if char.avatar_url:
                    reference_images.append(char.avatar_url)
                    logger.info(f'添加角色 {char.name} 的参考图: {char.avatar_url}')
        
        
        # 注意：无人物场景的禁止元素已在KeyframePromptBuilder中处理
        
        
        
        # 5. 生成图像
        logger.info(f"开始生成关键帧: shot_id={shot_id}, model={model}, 参考图数量={len(reference_images)}")

        if reference_images:

            result = await provider.generate_image(

                prompt=final_prompt,

                model=model,

                reference_images=reference_images

            )

        else:

            result = await provider.generate_image(

                prompt=final_prompt,

                model=model

            )

        # 6. 提取并上传图片（使用通用工具函数，支持base64格式）
        from src.utils.image_utils import extract_and_upload_image
        
        object_key = await extract_and_upload_image(
            result=result,
            user_id=user_id,
            metadata={"shot_id": str(shot_id)}
        )
        
        logger.info(f"图片已上传到存储: {object_key}")
        
        # 7. 更新分镜
        shot.keyframe_url = object_key
        
        # 8. 创建生成历史记录
        from src.services.generation_history_service import GenerationHistoryService
        from src.models.movie import GenerationType, MediaType
        
        history_service = GenerationHistoryService(self.db_session)
        await history_service.create_history(
            resource_type=GenerationType.SHOT_KEYFRAME,
            resource_id=str(shot.id),
            result_url=object_key,
            prompt=final_prompt,
            media_type=MediaType.IMAGE,
            model=model,
            api_key_id=str(api_key.id) if api_key else None
        )
        
        await self.db_session.commit()
        
        logger.info(f"关键帧生成完成: shot_id={shot_id}")
        return object_key

__all__ = ["VisualIdentityService"]


if __name__ == "__main__":
    # 测试关键帧生成
    import asyncio
    
    async def test():
        from src.core.database import get_async_db
        async with get_async_db() as session:
            vis_service = VisualIdentityService(session)
            script_id = "cd1b2680-5d39-4b08-8bf1-968ec05a1571"
            api_key_id = "457f4337-8f54-4749-a2d6-78e1febf9028"
            stats = await vis_service.batch_generate_keyframes(script_id, api_key_id, model="gemini-3-pro-image-preview")
            print(stats)

    asyncio.run(test())