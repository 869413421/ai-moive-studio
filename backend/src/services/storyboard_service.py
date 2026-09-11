"""
分镜提取服务 - 从场景提取分镜头
"""

import json
import asyncio
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from src.core.logging import get_logger
from src.models.movie import MovieScript, MovieScene, MovieShot, MovieCharacter
from src.services.base import BaseService
from src.services.provider.factory import ProviderFactory
from src.services.api_key import APIKeyService

logger = get_logger(__name__)

class StoryboardService(BaseService):
    """
    分镜提取服务
    从场景提取分镜，每个分镜关联角色列表
    """

    async def extract_shots_from_scene(
        self,
        scene_id: str,
        api_key_id: str,
        model: str = None
    ) -> List[MovieShot]:
        """
        从单个场景提取分镜
        
        Args:
            scene_id: 场景ID
            api_key_id: API Key ID
            model: 模型名称
            
        Returns:
            List[MovieShot]: 生成的分镜列表
        """
        # 1. 加载场景
        scene = await self.db_session.get(MovieScene, scene_id, options=[
            selectinload(MovieScene.script)
        ])
        if not scene:
            raise ValueError(f"未找到场景: {scene_id}")

        # 2. 加载项目角色
        from src.models.chapter import Chapter
        chapter = await self.db_session.get(Chapter, scene.script.chapter_id, options=[
            selectinload(Chapter.project)
        ])
        
        stmt = select(MovieCharacter).where(MovieCharacter.project_id == chapter.project_id)
        result = await self.db_session.execute(stmt)
        characters = result.scalars().all()
        character_list = [char.name for char in characters]

        # 3. 加载API Key
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id, str(chapter.project.owner_id))
        
        llm_provider = ProviderFactory.from_key(api_key)

        # 4. 使用统一的Prompt模板管理器
        from src.services.movie_prompts import MoviePromptTemplates

        # 5. 使用模板管理器生成prompt
        prompt = MoviePromptTemplates.get_shot_extraction_prompt(
            characters=json.dumps(character_list, ensure_ascii=False),
            scene=scene.scene
        )

        # 6. 调用LLM
        response = await llm_provider.completions(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个专业的电影分镜提取专家。只输出JSON。"},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"}
        )

        content = response.choices[0].message.content.strip()
        
        # 清理代码块标记
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()

        shot_data = json.loads(content)
        logger.info(f"场景 {scene_id} 提取到 {len(shot_data.get('shots', []))} 个分镜")

        # 7. 保存分镜
        created_shots = []
        for idx, shot_item in enumerate(shot_data.get("shots", [])): # 创建分镜
            shot = MovieShot(
                scene_id=scene.id,
                order_index=shot_item.get("order_index", idx + 1),
                shot=shot_item.get("shot", ""),
                dialogue=shot_item.get("dialogue"),
                characters=shot_item.get("characters", [])
            )
            self.db_session.add(shot)
            created_shots.append(shot)

        await self.db_session.commit()
        return created_shots

    async def extract_shots_from_single_scene_with_deletion(
        self,
        scene_id: str,
        api_key_id: str,
        model: str = None
    ) -> List[MovieShot]:
        """
        从单个场景重新提取分镜（先删除现有分镜）
        
        Args:
            scene_id: 场景ID
            api_key_id: API Key ID
            model: 模型名称
            
        Returns:
            List[MovieShot]: 生成的分镜列表
        """
        # 1. 加载场景及其现有分镜
        scene = await self.db_session.get(MovieScene, scene_id, options=[
            selectinload(MovieScene.script),
            selectinload(MovieScene.shots)
        ])
        if not scene:
            raise ValueError(f"未找到场景: {scene_id}")

        # 2. 删除该场景的所有现有分镜（会级联删除关键帧）
        if scene.shots:
            logger.info(f"场景 {scene_id} 有 {len(scene.shots)} 个现有分镜，将全部删除")
            for shot in scene.shots:
                await self.db_session.delete(shot)
            await self.db_session.flush()
            logger.info(f"场景 {scene_id} 的现有分镜已删除")

        # 3. 调用现有的提取方法生成新分镜
        created_shots = await self.extract_shots_from_scene(scene_id, api_key_id, model)
        
        logger.info(f"场景 {scene_id} 重新提取完成，生成 {len(created_shots)} 个分镜")
        return created_shots


    async def batch_extract_shots_from_script(
        self,
        script_id: str,
        api_key_id: str,
        model: str = None,
        max_concurrent: int = 3
    ) -> Dict[str, Any]:
        """
        批量从剧本的所有场景提取分镜
        
        Args:
            script_id: 剧本ID
            api_key_id: API Key ID
            model: 模型名称
            max_concurrent: 最大并发数
            
        Returns:
            Dict: 统计信息 {success: int, failed: int, total: int}
        """
        # 1. 加载剧本和所有场景（深度加载）
        script = await self.db_session.get(MovieScript, script_id, options=[
            selectinload(MovieScript.scenes).selectinload(MovieScene.shots)
        ])
        if not script:
            raise ValueError(f"未找到剧本: {script_id}")

        if not script.scenes:
            return {"success": 0, "failed": 0, "total": 0}

        # 2. 在删除前先提取场景ID列表和场景描述
        scene_data = [(str(scene.id), scene.scene) for scene in script.scenes]
        
        # 3. 删除所有现有分镜（会级联删除关键帧）
        logger.info(f"开始删除现有分镜...")
        for scene in script.scenes:
            if scene.shots:
                for shot in scene.shots:
                    await self.db_session.delete(shot)
            # 同时清空场景图
            scene.scene_image_url = None
            scene.scene_image_prompt = None
        
        await self.db_session.commit()
        logger.info(f"已删除所有现有分镜和场景图")
        
        # 4. 获取项目角色列表（所有场景共用）
        from src.models.chapter import Chapter
        chapter = await self.db_session.get(Chapter, script.chapter_id, options=[
            selectinload(Chapter.project)
        ])
        
        stmt = select(MovieCharacter).where(MovieCharacter.project_id == chapter.project_id)
        result = await self.db_session.execute(stmt)
        characters = result.scalars().all()
        character_list = [char.name for char in characters]
        
        # 5. 获取API Key
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id, str(chapter.project.owner_id))
        
        logger.info(f"开始批量提取分镜: {len(scene_data)} 个场景")

        # 6. 使用信号量控制并发
        semaphore = asyncio.Semaphore(max_concurrent)
        
        # Worker函数 - 每个worker独立处理一个场景，不需要数据库查询
        async def _extract_shot_worker(scene_id: str, scene_description: str):
            async with semaphore:
                try:
                    # 直接调用LLM生成分镜，不需要数据库查询
                    llm_provider = ProviderFactory.from_key(api_key)

                    # 使用统一的Prompt模板管理器
                    from src.services.movie_prompts import MoviePromptTemplates

                    # 生成prompt
                    prompt = MoviePromptTemplates.get_shot_extraction_prompt(
                        characters=json.dumps(character_list, ensure_ascii=False),
                        scene=scene_description
                    )

                    # 调用LLM
                    response = await llm_provider.completions(
                        model=model,
                        messages=[
                            {"role": "system", "content": "你是一个专业的电影分镜提取专家。只输出JSON。"},
                            {"role": "user", "content": prompt}
                        ],
                        response_format={"type": "json_object"}
                    )

                    # 解析结果
                    content = response.choices[0].message.content
                    data = json.loads(content)
                    shots_data = data.get("shots", [])
                    
                    if not shots_data:
                        logger.warning(f"场景 {scene_id} 未提取到分镜")
                        return {"success": False, "scene_id": scene_id, "error": "未提取到分镜"}

                    logger.info(f"场景 {scene_id} 提取到 {len(shots_data)} 个分镜")

                    # 创建分镜对象并添加到session
                    for idx, shot_info in enumerate(shots_data, 1):
                        shot = MovieShot(
                            scene_id=scene_id,
                            order_index=idx,
                            shot=shot_info.get("shot", ""),
                            dialogue=shot_info.get("dialogue", ""),
                            characters=shot_info.get("characters", [])
                        )
                        self.db_session.add(shot)
                    
                    # 返回成功和分镜数量
                    return {"success": True, "scene_id": scene_id, "shot_count": len(shots_data)}
                    
                except Exception as e:
                    logger.error(f"场景 {scene_id} 分镜提取失败: {e}")
                    return {"success": False, "scene_id": scene_id, "error": str(e)}

        # 7. 创建并发任务
        tasks = [_extract_shot_worker(scene_id, scene_desc) for scene_id, scene_desc in scene_data]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 8. 统计结果（shots已在worker中添加到session）
        success_count = sum(1 for r in results if isinstance(r, dict) and r.get("success"))
        failed_count = len(results) - success_count
        
        # 9. 一次性提交所有更改
        if success_count > 0:
            await self.db_session.commit()

        logger.info(f"批量分镜提取完成: 成功 {success_count}, 失败 {failed_count}")

        return {
            "success": success_count,
            "failed": failed_count,
            "total": len(scene_data),
            "details": results
        }

__all__ = ["StoryboardService"]
