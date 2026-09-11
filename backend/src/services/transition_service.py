"""
过渡视频服务 - 生成分镜间过渡视频
"""

import json
import asyncio
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from src.core.logging import get_logger
from src.models.movie import MovieScript, MovieScene, MovieShot, MovieShotTransition
from src.services.base import BaseService
from src.services.provider.factory import ProviderFactory
from src.services.api_key import APIKeyService

logger = get_logger(__name__)

class TransitionService(BaseService):
    """
    过渡视频服务
    1. 生成视频提示词（基于两个分镜描述）
    2. 调用视频API生成过渡视频
    """

    async def _generate_transition_prompt(
        self,
        from_shot_description: str,
        from_shot_dialogue: str,
        from_shot_characters: list,
        to_shot_description: str,
        to_shot_dialogue: str,
        to_shot_characters: list,
        api_key,
        model: str = None
    ) -> str:
        """
        生成过渡视频提示词（内部方法，可复用）
        
        Args:
            from_shot_description: 起始分镜描述
            from_shot_dialogue: 起始分镜对话
            from_shot_characters: 起始分镜角色列表
            to_shot_description: 结束分镜描述
            to_shot_dialogue: 结束分镜对话
            to_shot_characters: 结束分镜角色列表
            api_key: API Key对象
            model: 模型名称
            
        Returns:
            str: 生成的视频提示词
            
        Note:
            不传递角色的visual_traits，因为：
            1. 过渡视频基于首尾关键帧，视觉一致性由视频模型保证
            2. 只需要角色名称，不需要详细外貌描述
        """
        llm_provider = ProviderFactory.from_key(api_key)

        from src.services.movie_prompts import MoviePromptTemplates

        # 格式化前一个分镜描述（仅作上下文参考）
        previous_shot = f"""**分镜描述：**
{from_shot_description}

**对话：** {from_shot_dialogue}

**角色：** {', '.join(from_shot_characters) if from_shot_characters else '无'}
"""

        # 格式化当前分镜描述（要生成的内容）
        current_shot = f"""**分镜描述：**
{to_shot_description}

**对话：** {to_shot_dialogue}

**角色：** {', '.join(to_shot_characters) if to_shot_characters else '无'}
"""

        prompt = MoviePromptTemplates.get_transition_video_prompt(previous_shot, current_shot)

        response = await llm_provider.completions(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个专业的电影视频提示词生成专家。"},
                {"role": "user", "content": prompt},
            ]
        )

        video_prompt = response.choices[0].message.content.strip()
        logger.info(f"生成视频提示词: {video_prompt[:100]}...")
        
        return video_prompt

    async def generate_video_prompt(
        self,
        from_shot: MovieShot,
        to_shot: MovieShot,
        api_key_id: str,
        model: str = None
    ) -> str:
        """
        生成两个分镜之间的视频提示词
        
        Args:
            from_shot: 起始分镜
            to_shot: 结束分镜
            api_key_id: API Key ID
            model: 模型名称
            
        Returns:
            str: 生成的视频提示词（英文）
        """
        # 加载API Key
        from src.models.chapter import Chapter
        
        scene = await self.db_session.get(MovieScene, from_shot.scene_id, options=[
            selectinload(MovieScene.script)
        ])
        chapter = await self.db_session.get(Chapter, scene.script.chapter_id, options=[
            selectinload(Chapter.project)
        ])
        
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id, str(chapter.project.owner_id))
        
        return await self._generate_transition_prompt(
            from_shot_description=from_shot.shot,
            from_shot_dialogue=from_shot.dialogue or '无',
            from_shot_characters=from_shot.characters or [],
            to_shot_description=to_shot.shot,
            to_shot_dialogue=to_shot.dialogue or '无',
            to_shot_characters=to_shot.characters or [],
            api_key=api_key,
            model=model
        )

    async def create_transition(
        self,
        script_id: str,
        from_shot_id: str,
        to_shot_id: str,
        order_index: int,
        api_key_id: str,
        model: str = None
    ) -> MovieShotTransition:
        """
        创建过渡视频记录并生成提示词
        
        Args:
            script_id: 剧本ID
            from_shot_id: 起始分镜ID
            to_shot_id: 结束分镜ID
            order_index: 过渡顺序
            api_key_id: API Key ID
            model: 模型名称
            
        Returns:
            MovieShotTransition: 创建的过渡记录
        """
        # 加载分镜
        from_shot = await self.db_session.get(MovieShot, from_shot_id)
        to_shot = await self.db_session.get(MovieShot, to_shot_id)
        
        if not from_shot or not to_shot:
            raise ValueError("分镜不存在")

        # 生成视频提示词
        video_prompt = await self.generate_video_prompt(from_shot, to_shot, api_key_id, model)

        # 创建过渡记录
        transition = MovieShotTransition(
            script_id=script_id,
            from_shot_id=from_shot_id,
            to_shot_id=to_shot_id,
            order_index=order_index,
            video_prompt=video_prompt,
            status="pending"
        )
        
        self.db_session.add(transition)
        await self.db_session.commit()
        
        return transition

    async def batch_create_transitions(
        self,
        script_id: str,
        api_key_id: str,
        model: str = None,
        max_concurrent: int = 5
    ) -> Dict[str, Any]:
        """
        批量创建剧本所有分镜的过渡视频（并发处理）
        
        Args:
            script_id: 剧本ID
            api_key_id: API Key ID
            model: 模型名称
            max_concurrent: 最大并发数
            
        Returns:
            Dict: 统计信息
        """
        # 1. 加载剧本和所有分镜
        script = await self.db_session.get(MovieScript, script_id, options=[
            selectinload(MovieScript.scenes).selectinload(MovieScene.shots)
        ])
        if not script:
            raise ValueError(f"未找到剧本: {script_id}")

        # 2. 收集所有分镜并按顺序排列，只保留有关键帧的分镜
        all_shots = []
        for scene in sorted(script.scenes, key=lambda s: s.order_index):
            for shot in sorted(scene.shots, key=lambda s: s.order_index):
                # 只添加有关键帧的分镜
                if shot.keyframe_url:
                    all_shots.append(shot)

        if len(all_shots) < 2:
            return {"success": 0, "failed": 0, "total": 0, "message": "有关键帧的分镜数量不足（需要至少2个）"}

        logger.info(f"找到 {len(all_shots)} 个有关键帧的分镜，准备创建 {len(all_shots) - 1} 个过渡")

        # 3. 查询已存在的过渡
        stmt = select(MovieShotTransition).where(MovieShotTransition.script_id == script_id)
        result = await self.db_session.execute(stmt)
        existing_transitions = result.scalars().all()
        
        # 创建已存在过渡的集合（用于快速查找）
        existing_pairs = {(str(t.from_shot_id), str(t.to_shot_id)) for t in existing_transitions}
        logger.info(f"已存在 {len(existing_transitions)} 个过渡")

        # 4. 预加载API Key和项目信息（避免在协程中访问数据库）
        from src.models.chapter import Chapter
        
        scene = await self.db_session.get(MovieScene, all_shots[0].scene_id, options=[
            selectinload(MovieScene.script)
        ])
        chapter = await self.db_session.get(Chapter, scene.script.chapter_id, options=[
            selectinload(Chapter.project)
        ])
        
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id, str(chapter.project.owner_id))

        # 5. 准备需要创建的过渡任务（提取所有需要的数据）
        transition_tasks = []
        skipped_count = 0
        
        for i in range(len(all_shots) - 1):
            from_shot = all_shots[i]
            to_shot = all_shots[i + 1]
            from_shot_id = str(from_shot.id)
            to_shot_id = str(to_shot.id)
            
            # 检查是否在同一个场景内
            if from_shot.scene_id != to_shot.scene_id:
                logger.info(f"跳过跨场景过渡: {from_shot_id} (场景{from_shot.scene_id}) -> {to_shot_id} (场景{to_shot.scene_id})")
                skipped_count += 1
                continue
            
            # 检查是否已存在
            if (from_shot_id, to_shot_id) in existing_pairs:
                logger.info(f"跳过已存在的过渡: {from_shot_id} -> {to_shot_id}")
                skipped_count += 1
                continue
            
            # 提取分镜数据（避免在协程中访问ORM对象）
            transition_tasks.append({
                'order_index': i + 1,
                'from_shot_id': from_shot_id,
                'to_shot_id': to_shot_id,
                'from_shot_description': from_shot.shot,
                'from_shot_dialogue': from_shot.dialogue or '无',
                'from_shot_characters': from_shot.characters or [],
                'to_shot_description': to_shot.shot,
                'to_shot_dialogue': to_shot.dialogue or '无',
                'to_shot_characters': to_shot.characters or [],
            })

        if not transition_tasks:
            return {
                "success": 0,
                "failed": 0,
                "skipped": skipped_count,
                "total": len(all_shots) - 1,
                "message": f"所有过渡已存在，跳过 {skipped_count} 个"
            }

        logger.info(f"准备并发创建 {len(transition_tasks)} 个过渡")

        # 测试只生成一个
        # transition_tasks = transition_tasks[:1]

        # 6. 并发worker函数
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def _create_transition_worker(task_data: Dict[str, Any]):
            async with semaphore:
                try:
                    # 生成LLM提示词（使用提取的方法）
                    video_prompt = await self._generate_transition_prompt(
                        from_shot_description=task_data['from_shot_description'],
                        from_shot_dialogue=task_data['from_shot_dialogue'],
                        from_shot_characters=task_data['from_shot_characters'],
                        to_shot_description=task_data['to_shot_description'],
                        to_shot_dialogue=task_data['to_shot_dialogue'],
                        to_shot_characters=task_data['to_shot_characters'],
                        api_key=api_key,
                        model=model
                    )
                    
                    # 创建过渡对象（不立即提交）
                    transition = MovieShotTransition(
                        script_id=script_id,
                        from_shot_id=task_data['from_shot_id'],
                        to_shot_id=task_data['to_shot_id'],
                        order_index=task_data['order_index'],
                        video_prompt=video_prompt,
                        status="pending"
                    )
                    
                    logger.info(f"生成过渡提示词: {task_data['from_shot_id']} -> {task_data['to_shot_id']}")
                    return {"success": True, "transition": transition}
                    
                except Exception as e:
                    logger.error(f"创建过渡失败 {task_data['from_shot_id']} -> {task_data['to_shot_id']}: {e}")
                    return {"success": False, "error": str(e)}

        # 7. 并发执行
        results = await asyncio.gather(*[_create_transition_worker(task) for task in transition_tasks])

        # 8. 批量保存成功的过渡
        success_count = 0
        failed_count = 0
        
        for result in results:
            if result.get("success") and result.get("transition"):
                self.db_session.add(result["transition"])
                success_count += 1
            else:
                failed_count += 1

        # 9. 一次性提交
        if success_count > 0:
            await self.db_session.commit()

        total_possible = len(all_shots) - 1
        logger.info(f"批量创建完成: 新建 {success_count}, 失败 {failed_count}, 跳过 {skipped_count}")
        
        return {
            "success": success_count,
            "failed": failed_count,
            "skipped": skipped_count,
            "total": total_possible,
            "message": f"创建完成: 新建 {success_count}, 跳过 {skipped_count}"
        }

    async def _load_keyframe_references(self, from_shot_id, to_shot_id):
        from src.services.provider.gateway import video_references
        shots = [await self.db_session.get(MovieShot, shot_id) for shot_id in (from_shot_id, to_shot_id)]
        if any(not shot or not shot.keyframe_url for shot in shots):
            raise ValueError('首尾帧视频需要前后两个分镜的关键帧')
        return await video_references([shot.keyframe_url for shot in shots])

    async def _generate_single_transition_video(
        self,
        transition: MovieShotTransition,
        api_key_id: str,
        user_id: str,
        video_model: str,
        provider
    ) -> dict:
        """
        生成单个过渡视频的通用逻辑（内部方法）
        
        Args:
            transition: 过渡对象
            api_key_id: API Key ID
            user_id: 用户ID
            video_model: 视频模型
            provider: VectorEngine provider实例
            
        Returns:
            dict: {"success": bool, "transition_id": str, "task_id": str} 或 {"success": bool, "error": str}
        """
        try:
            # 加载关键帧
            keyframe_images = await self._load_keyframe_references(
                transition.from_shot_id, 
                transition.to_shot_id
            )
            
            # 调用视频生成（传递关键帧）
            result = await provider.create_video(
                prompt=transition.video_prompt,
                model=video_model,
                images=keyframe_images,
                frames=True
            )
            
            # VectorEngine API返回的是 'id' 字段，不是 'task_id'
            task_id = result.get("id") or result.get("task_id")
            if not task_id:
                raise ValueError(f"API未返回任务ID: {result}")
            
            # 更新记录
            transition.provider_context_json = result.get("provider_context")
            transition.video_task_id = task_id
            transition.status = "processing"
            transition.api_key_id = api_key_id
            transition.user_id = user_id
            
            logger.info(f"过渡视频任务已提交: {transition.id}, task_id={task_id}, keyframes={len(keyframe_images)}")
            return {"success": True, "transition_id": str(transition.id), "task_id": task_id}
        except Exception as e:
            logger.error(f"生成过渡视频失败 {transition.id}: {e}")
            return {"success": False, "error": str(e)}

    async def generate_transition_video(
        self,
        transition_id: str,
        api_key_id: str,
        video_model: str
    ) -> str:
        """
        生成单个过渡视频
        
        Args:
            transition_id: 过渡ID
            api_key_id: API Key ID
            video_model: 视频模型名称
            
        Returns:
            str: 视频任务ID
        """
        # 加载过渡记录
        transition = await self.db_session.get(MovieShotTransition, transition_id)
        if not transition:
            raise ValueError(f"未找到过渡: {transition_id}")
        
        if not transition.video_prompt:
            raise ValueError(f"过渡 {transition_id} 没有视频提示词")
        
        # 获取user_id（从script关联获取）
        from src.models.chapter import Chapter
        from sqlalchemy.orm import joinedload
        
        script = await self.db_session.get(MovieScript, transition.script_id, options=[
            joinedload(MovieScript.chapter).joinedload(Chapter.project)
        ])
        user_id = script.chapter.project.owner_id
        
        # 加载API Key
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id, str(user_id))
        
        video_provider = ProviderFactory.from_key(api_key)
        
        # 调用通用生成逻辑
        logger.info(f"开始生成过渡视频: {transition_id}, 模型: {video_model}")
        result = await self._generate_single_transition_video(
            transition, api_key_id, user_id, video_model, video_provider
        )
        
        if not result["success"]:
            raise ValueError(f"生成失败: {result.get('error')}")
        
        # 提交数据库
        await self.db_session.commit()
        
        logger.info(f"过渡视频生成任务已提交: {transition_id}, task_id: {result.get('task_id')}")
        return result.get("task_id")

    async def batch_generate_transition_videos(
        self,
        script_id: str,
        api_key_id: str,
        video_model: str
    ) -> dict:
        """
        批量生成过渡视频
        使用独立的数据库会话避免并发冲突
        
        Args:
            script_id: 剧本ID
            api_key_id: API Key ID
            video_model: 视频模型名称
            
        Returns:
            dict: 生成统计信息
        """
        from src.models.chapter import Chapter
        from sqlalchemy.orm import joinedload
        from src.core.database import get_async_db
        
        logger.info(f"开始批量生成过渡视频: script_id={script_id}")
        
        # 1. 加载script和user信息（在主会话中）
        script = await self.db_session.get(MovieScript, script_id, options=[
            selectinload(MovieScript.scenes).selectinload(MovieScene.shots),
            joinedload(MovieScript.chapter).joinedload(Chapter.project)
        ])
        if not script:
            raise ValueError("剧本不存在")
        
        user_id = script.chapter.project.owner_id
        
        # 2. 加载API Key（在主会话中）
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id, str(user_id))
        
        # 3. 查询所有pending状态且有提示词的过渡（在主会话中）
        stmt = select(MovieShotTransition).where(
            MovieShotTransition.script_id == script_id,
            MovieShotTransition.status == "pending",
            MovieShotTransition.video_prompt.isnot(None)
        )
        result = await self.db_session.execute(stmt)
        transitions = result.scalars().all()
        
        if not transitions:
            logger.info("没有待生成的过渡视频")
            return {"total": 0, "success": 0, "failed": 0, "message": "没有待生成的过渡"}
        
        logger.info(f"找到 {len(transitions)} 个待生成的过渡视频")
        
        # 4. 提取过渡数据（避免在协程中访问ORM对象）
        transition_data_list = []
        for t in transitions:
            transition_data_list.append({
                'id': t.id,
                'from_shot_id': t.from_shot_id,
                'to_shot_id': t.to_shot_id,
                'video_prompt': t.video_prompt,
                'script_id': t.script_id
            })
        
        provider = ProviderFactory.from_key(api_key)
        
        # 6. 定义worker函数（使用独立会话）
        max_concurrent = 5
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def _generate_worker_with_session(transition_data: dict):
            """为单个过渡生成视频，使用独立的数据库会话"""
            async with semaphore:
                async with get_async_db() as worker_session:
                    try:
                        # 在worker会话中重新加载过渡对象
                        transition = await worker_session.get(
                            MovieShotTransition, 
                            transition_data['id']
                        )
                        if not transition:
                            logger.error(f"过渡不存在: {transition_data['id']}")
                            return {"success": False, "error": "过渡不存在"}
                        
                        # 生成视频（使用worker会话的service实例）
                        worker_service = TransitionService(worker_session)
                        result = await worker_service._generate_single_transition_video(
                            transition, api_key_id, str(user_id), video_model, provider
                        )
                        
                        # 提交worker会话
                        await worker_session.commit()
                        
                        return result
                        
                    except Exception as e:
                        await worker_session.rollback()
                        logger.error(f"Worker生成过渡视频失败 [{transition_data['id']}]: {e}", exc_info=True)
                        return {"success": False, "error": str(e)}
        
        # 7. 执行并发任务
        tasks = [_generate_worker_with_session(td) for td in transition_data_list]
        results = await asyncio.gather(*tasks)
        
        # 8. 统计结果（不需要在这里commit，每个worker已经独立commit了）
        success_count = sum(1 for r in results if r["success"])
        failed_count = len(results) - success_count
        
        logger.info(f"批量生成完成: 总计 {len(results)}, 成功 {success_count}, 失败 {failed_count}")
        return {
            "total": len(results),
            "success": success_count,
            "failed": failed_count
        }


    async def sync_transition_video_status(self, api_key_id: str = None) -> dict:
        """
        同步过渡视频任务状态
        
        Args:
            api_key_id: 可选，如果不提供则从transition记录中获取
            
        Returns:
            dict: 同步统计信息
        """
        import httpx
        from fastapi import UploadFile
        import io
        import uuid
        from src.utils.storage import get_storage_client
        
        logger.info("开始同步过渡视频任务状态")
        
        # 查询所有processing状态的过渡
        stmt = select(MovieShotTransition).where(
            MovieShotTransition.status == "processing",
            MovieShotTransition.video_task_id.isnot(None)
        )
        result = await self.db_session.execute(stmt)
        transitions = result.scalars().all()
        
        if not transitions:
            logger.info("没有需要同步的过渡视频任务")
            return {"synced": 0, "completed": 0, "failed": 0}
        
        logger.info(f"找到 {len(transitions)} 个待同步的过渡视频任务")
        
        synced_count = 0
        completed_count = 0
        failed_count = 0
        
        for transition in transitions:
            try:
                # 从记录中获取API Key ID
                transition_api_key_id = str(transition.api_key_id) if transition.api_key_id else api_key_id
                if not transition_api_key_id:
                    logger.warning(f"过渡 {transition.id} 缺少api_key_id，跳过")
                    continue
                
                # 加载API Key
                api_key_service = APIKeyService(self.db_session)
                api_key = await api_key_service.get_api_key_by_id(transition_api_key_id)
                
                # 创建provider
                provider = ProviderFactory.resume_video(api_key, transition.provider_context_json)
                
                # 查询任务状态
                status_data = await provider.get_task_status(transition.video_task_id)
                
                # VectorEngine API返回格式: {"id": "...", "status": "...", "detail": {...}}
                # 状态可能在顶层或detail中
                status = status_data.get("status")
                detail = status_data.get("detail", {})
                
                logger.debug(f"任务 {transition.video_task_id} 状态: {status}, detail状态: {detail.get('status')}")
                
                # 如果顶层状态是video_generating或processing，使用detail中的状态
                if status in ["video_generating", "processing", "pending"]:
                    # 仍在处理中，不更新
                    logger.debug(f"过渡视频仍在处理中: {transition.id}, 状态: {status}")
                    continue
                
                if status == "completed":
                    # VectorEngine API在完成时，video_url在顶层
                    video_url = status_data.get("video_url")
                    
                    # 如果顶层没有，尝试从detail中获取
                    if not video_url:
                        detail = status_data.get("detail", {})
                        video_url = detail.get("video_url")
                    
                    if video_url:
                        # 获取user_id
                        user_id = str(transition.user_id) if transition.user_id else "system"
                        
                        # 下载视频 (增加超时设置: 连接30s, 读取300s)
                        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout=300.0, connect=30.0)) as client:
                            response = await client.get(video_url)
                            response.raise_for_status()
                            video_content = response.content
                        
                        # 上传到MinIO（使用通用方法）
                        storage_client = await get_storage_client()
                        file_id = str(uuid.uuid4())
                        upload_file = UploadFile(
                            filename=f"{file_id}.mp4",
                            file=io.BytesIO(video_content)
                        )
                        
                        storage_result = await storage_client.upload_file(
                            user_id=user_id,
                            file=upload_file,
                            metadata={"transition_id": str(transition.id)}
                        )
                        
                        transition.video_url = storage_result["object_key"]
                        transition.status = "completed"
                        transition.error_message = None  # 清除之前的错误信息
                        
                        # 创建生成历史记录
                        from src.services.generation_history_service import GenerationHistoryService
                        from src.models.movie import GenerationType, MediaType
                        
                        history_service = GenerationHistoryService(self.db_session)
                        await history_service.create_history(
                            resource_type=GenerationType.TRANSITION_VIDEO,
                            resource_id=str(transition.id),
                            result_url=storage_result["object_key"],
                            prompt=transition.video_prompt or "",
                            media_type=MediaType.VIDEO,
                            model=None,
                            api_key_id=str(transition.api_key_id) if transition.api_key_id else None
                        )
                        
                        completed_count += 1
                        logger.info(f"过渡视频完成: {transition.id}, 已保存到MinIO")
                    else:
                        # 没有视频URL，标记为失败
                        transition.status = "failed"
                        transition.error_message = "视频生成完成但未返回视频URL"
                        failed_count += 1
                        logger.error(f"过渡视频失败: {transition.id} - 未返回视频URL")
                    
                elif status == "failed":
                    # 获取失败原因
                    error_data = status_data.get("error", "视频生成失败")
                    
                    # 如果error是字典，转换为字符串
                    if isinstance(error_data, dict):
                        import json
                        error_msg = json.dumps(error_data, ensure_ascii=False)
                    else:
                        error_msg = str(error_data)
                    
                    transition.status = "failed"
                    transition.error_message = error_msg
                    failed_count += 1
                    logger.error(f"过渡视频失败: {transition.id} - {error_msg}")
                
                elif status == "processing":
                    # 仍在处理中，不更新
                    logger.debug(f"过渡视频仍在处理中: {transition.id}")
                    continue
                
                else:
                    # 未知状态
                    logger.warning(f"过渡视频未知状态: {transition.id} - {status}")
                    continue
                
                synced_count += 1
                
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                # 网络超时或连接错误，不标记失败，允许下一次重试
                logger.warning(f"同步过渡 {transition.id} 遭遇网络异常(超时/连接), 将在下次循环重试: {e}")
                continue
            except Exception as e:
                error_msg = f"同步失败: {str(e)}"
                logger.error(f"同步过渡 {transition.id} 遭遇不可恢复失败: {e}", exc_info=True)
                
                # 记录错误信息（确保是字符串）
                transition.status = "failed"
                transition.error_message = error_msg[:500]  # 限制长度避免过长
                failed_count += 1
        
        await self.db_session.commit()
        
        logger.info(f"同步完成: 总计 {synced_count}, 完成 {completed_count}, 失败 {failed_count}")
        return {
            "synced": synced_count,
            "completed": completed_count,
            "failed": failed_count
        }

__all__ = ["TransitionService"]

if __name__ == "__main__":
    import asyncio
    from src.core.database import get_async_db 

    async def test_sync():
        async with get_async_db() as db_session:
            transition_service = TransitionService(db_session)
            res = await transition_service.sync_transition_video_status()   
            print(res)

    asyncio.run(test_sync())
