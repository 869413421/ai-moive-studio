"""
电影角色服务 - 负责角色提取、视觉特征建模、对话风格设计
"""

import json
import re
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.core.logging import get_logger
from src.models.movie import MovieCharacter, MovieScript, MovieScene, MovieShot
from src.services.base import BaseService
from src.services.provider.factory import ProviderFactory
from src.services.api_key import APIKeyService
from src.services.image import retry_with_backoff
from src.utils.storage import get_storage_client
import uuid
import io
import aiohttp
from fastapi import UploadFile

logger = get_logger(__name__)

class CharacterThreeViewPromptBuilder:
    """
    角色三视图提示词生成器
    根据 Gemini 3 Pro Image 最佳实践生成提示词
    核心结构: [时代背景] + [角色身份] + [三视图要求] + [一致性关键词] + [风格/技术参数]
    """
    
    TEMPLATE = """CINEMATIC LIVE-ACTION CHARACTER REFERENCE
featuring THREE CONSISTENT PHOTOGRAPHED VIEWS
of the SAME REAL HUMAN ACTOR portraying {name}:

front view, 90-degree side view, and back view,
captured during the same on-set studio photoshoot.

Character details:
- Name: {name}
- Era / Time Period: {era_background}
- Occupation / Social Status: {occupation}
- Key Visual Traits: {key_visual_traits}

Live-Action Photography Requirements:
- Portrayed by ONE real human actor
- All three views show the SAME actor, SAME costume, SAME makeup
- Natural human skin texture with pores, imperfections, micro-details
- Real fabric materials, real metal wear, practical costume design
- Identical hairstyle, body proportions, posture across all views
- Neutral production stance for film reference

Cinematography & Photography Style:
- High-end live-action film stills
- Shot on professional cinema camera (ARRI / RED style look)
- Real studio lighting, soft key light, natural shadows
- Photographed, not rendered
- Neutral or black studio background

STRICT CONSTRAINTS:
- NO 3D render
- NO CGI
- NO Unreal Engine
- NO game character style
- NO digital sculpt look

Technical Output:
- Ultra-detailed live-action character reference photos
- Aspect ratio: 16:9
- Place the English name in the top-left corner, clearly visible and readable
"""
    
    @classmethod
    def build_prompt(
        cls,
        name: str,
        era_background: Optional[str] = None,
        occupation: Optional[str] = None,
        key_visual_traits: Optional[List[str]] = None,
        visual_traits: Optional[str] = None,
        role_description: Optional[str] = None
    ) -> str:
        """
        构建三视图提示词
        
        Args:
            name: 角色名称
            era_background: 时代背景 (如: "1940s WWII", "Victorian Era", "Cyberpunk 2077")
            occupation: 职业/社会地位
            key_visual_traits: 核心视觉特征列表 (3-4个)
            visual_traits: 详细视觉特征描述 (备用)
            role_description: 角色描述 (备用)
        
        Returns:
            生成的三视图提示词
        """
        # 使用默认值或从其他字段推断
        era = era_background or "Modern era"
        occ = occupation or "Unknown occupation"
        
        # 处理核心视觉特征
        if key_visual_traits and len(key_visual_traits) > 0:
            traits_str = ", ".join(key_visual_traits)
        elif visual_traits:
            # 如果没有key_visual_traits,从visual_traits中提取前100个字符作为简要描述
            traits_str = visual_traits[:100] + "..." if len(visual_traits) > 100 else visual_traits
        else:
            traits_str = "Standard appearance"
        
        # 生成提示词
        prompt = cls.TEMPLATE.format(
            name=name,
            era_background=era,
            occupation=occ,
            key_visual_traits=traits_str
        )
        
        return prompt

class MovieCharacterService(BaseService):
    """
    角色管理服务
    """

    EXTRACT_CHARACTERS_PROMPT = """
你是一个资深的选角导演。请分析以下电影剧本片段,提取出其中出现的所有主要角色。

### 输出要求:
必须以 JSON 格式输出,结构如下:
{{
  "characters": [
    {{
      "name": "角色姓名",
      "era_background": "时代背景(如: 1940s WWII, Victorian Era, Cyberpunk 2077, Modern era等)",
      "occupation": "职业或社会地位",
      "role_description": "角色的身份、背景、性格特点",
      "visual_traits": "详细的视觉特征描述(如:年龄、发色、发型、穿着、面部特征、体型),用于AI生图。",
      "key_visual_traits": ["核心视觉特征1", "核心视觉特征2", "核心视觉特征3"],
      "dialogue_traits": "角色的对话风格(如:冷静、粗鲁、幽默、书生气、口音特点等)"
    }}
  ]
}}

### 重要规则:
1. **角色名称一致性**: 
   - 同一角色必须使用完全相同的名称,不要有任何变化
   - 如果角色有中文名和英文名,统一使用"中文名 (英文名)"格式,例如: "阿尔德里克 (Aldric)"
   - 不要在同一个输出中出现"阿尔德里克"和"阿尔德里克 (Aldric)"这样的重复
   - 角色名称应该简洁明确,避免添加额外的描述性文字

2. **字段要求**:
   - era_background: 根据剧本内容推断时代背景,如果不明确则使用"Modern era"
   - occupation: 角色的职业或社会地位
   - key_visual_traits: 提取3-4个最关键的视觉特征,用于生成角色三视图

3. **特征提取要求**:
    - 优先从剧本中提取明确描述的视觉特征，如果剧本中没有明确描述，则根据角色的身份和时代背景进行合理推断
    - 对话风格应反映角色的性格和背景,例如:贵族角色可能说话较为正式,街头混混可能使用俚语
    - 尽可能详细的特征提取，则根据角色的身份和时代背景进行合理推断。
    

待分析剧本:
---
{text}
---
"""

    async def extract_characters_from_chapter(self, chapter_id: str, api_key_id: str, model: str = None) -> List[MovieCharacter]:
        """
        从章节内容中提取角色
        """
        # 1. 加载章节内容
        from src.models.chapter import Chapter
        chapter = await self.db_session.get(Chapter, chapter_id, options=[selectinload(Chapter.project)])
        if not chapter:
            raise ValueError("未找到章节")
        
        # 使用章节内容作为分析文本
        script_text = chapter.content or ""
        
        # 如果有剧本，也可以加载剧本内容作为补充
        stmt = select(MovieScript).where(MovieScript.chapter_id == chapter_id).options(
            selectinload(MovieScript.scenes).selectinload(MovieScene.shots)
        )
        result = await self.db_session.execute(stmt)
        script = result.scalar_one_or_none()
        
        if script:
            # 如果已经有剧本，拼凑剧本全文用于分析
            for scene in script.scenes:
                script_text += f"\n场景 {scene.order_index}: {scene.scene}\n"
                if scene.characters:
                    script_text += f"出场角色: {', '.join(scene.characters)}\n"
                for shot in scene.shots:
                    if shot.dialogue:
                        script_text += f"镜头 {shot.order_index} 对话: {shot.dialogue}\n"
                script_text += "\n"

        # 2. 加载 API Key
        chapter = await self.db_session.get(Chapter, chapter_id, options=[selectinload(Chapter.project)])
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id, str(chapter.project.owner_id))
        
        llm_provider = ProviderFactory.from_key(api_key)

        try:
            prompt = self.EXTRACT_CHARACTERS_PROMPT.format(text=script_text[:5000]) # 限制长度
            response = await llm_provider.completions(
                model=model,
                messages=[
                    {"role": "system", "content": "你是一个专业的选角导演JSON生成器。"},
                    {"role": "user", "content": prompt},
                ],
                response_format={ "type": "json_object" }
            )
            
            content = response.choices[0].message.content.strip()
            if content.startswith("```json"): content = content[7:-3].strip()
            elif content.startswith("```"): content = content[3:-3].strip()
            
            char_data = json.loads(content)
            
            # 获取项目中已存在的所有角色
            stmt = select(MovieCharacter).where(MovieCharacter.project_id == chapter.project_id)
            existing_result = await self.db_session.execute(stmt)
            existing_characters = {char.name: char for char in existing_result.scalars().all()}
            
            def normalize_name(name: str) -> str:
                """标准化角色名称,提取核心名称用于匹配"""
                # 移除括号及其内容,只保留主要名称
                core_name = re.sub(r'\s*\([^)]*\)', '', name).strip()
                return core_name
            
            def find_matching_character(char_name: str, existing_chars: dict) -> Optional[MovieCharacter]:
                """智能查找匹配的角色"""
                # 1. 精确匹配
                if char_name in existing_chars:
                    return existing_chars[char_name]
                
                # 2. 标准化名称匹配
                normalized_new = normalize_name(char_name)
                for existing_name, existing_char in existing_chars.items():
                    normalized_existing = normalize_name(existing_name)
                    if normalized_new == normalized_existing:
                        return existing_char
                
                return None
            
            created_characters = []
            for char in char_data.get("characters", []):
                char_name = char.get("name", "").strip()
                if not char_name:
                    continue
                
                # 智能查找已存在的角色
                existing_char = find_matching_character(char_name, existing_characters)
                
                # 生成三视图提示词
                generated_prompt = CharacterThreeViewPromptBuilder.build_prompt(
                    name=char_name,
                    era_background=char.get("era_background"),
                    occupation=char.get("occupation"),
                    key_visual_traits=char.get("key_visual_traits"),
                    visual_traits=char.get("visual_traits"),
                    role_description=char.get("role_description")
                )
                
                if existing_char:
                    # 更新已存在的角色
                    existing_char.role_description = char.get("role_description")
                    existing_char.visual_traits = char.get("visual_traits")
                    existing_char.dialogue_traits = char.get("dialogue_traits")
                    existing_char.era_background = char.get("era_background")
                    existing_char.occupation = char.get("occupation")
                    existing_char.key_visual_traits = char.get("key_visual_traits", [])
                    existing_char.generated_prompt = generated_prompt
                    created_characters.append(existing_char)
                else:
                    # 创建新角色
                    character = MovieCharacter(
                        project_id=chapter.project_id,
                        name=char_name,
                        role_description=char.get("role_description"),
                        visual_traits=char.get("visual_traits"),
                        dialogue_traits=char.get("dialogue_traits"),
                        era_background=char.get("era_background"),
                        occupation=char.get("occupation"),
                        key_visual_traits=char.get("key_visual_traits", []),
                        generated_prompt=generated_prompt
                    )
                    self.db_session.add(character)
                    existing_characters[char_name] = character  # 添加到已存在列表,避免本次提取中的重复
                    created_characters.append(character)
            
            await self.db_session.commit()
            return created_characters
            
        except Exception as e:
            logger.error(f"提取角色失败: {e}")
            raise
    
    async def generate_character_avatar(
        self, 
        character_id: str, 
        api_key_id: str, 
        model: str = None, 
        prompt: str = None, 
        style: str = "cinematic",
        reference_indices: list = None
    ) -> str:
        """
        生成角色头像/定妆照
        """
        char = await self.db_session.get(MovieCharacter, character_id)
        if not char:
            raise ValueError("未找到角色")
        
        # 加载 API Key
        from src.models.project import Project
        project = await self.db_session.get(Project, char.project_id)
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id, str(project.owner_id))

        image_provider = ProviderFactory.from_key(api_key)
        
        # 根据索引获取参考图URL（参考关键帧生成的方式）
        reference_image_urls = []
        if reference_indices and char.reference_images:
            for idx in reference_indices:
                if 0 <= idx < len(char.reference_images):
                    reference_image_urls.append(char.reference_images[idx])
                    logger.info(f"添加参考图 [{idx}]: {char.reference_images[idx]}")
        
        try:
            # 直接使用前端传递的提示词(用户已微调过的三视图提示词)
            logger.info(f"收到的prompt参数: {prompt[:200] if prompt else 'None'}...")
            if not prompt:
                raise ValueError("必须提供生成提示词")
            
             # 增强提示词，让AI模型在图片左上角生成角色名称
            enhanced_prompt = f"{prompt}. IMPORTANT: Include the text '{char.name}' in the top-left corner of the image, clearly visible and readable."
            
            # 调用生图模型
            logger.info(f"生成角色头像提示词: {enhanced_prompt[:200]}...")
            
            # 准备生成参数
            generate_kwargs = {
                "prompt": enhanced_prompt,
                "model": model
            }
            
            # 如果有参考图，添加到参数中（参考关键帧生成的方式）
            if reference_image_urls:
                generate_kwargs["reference_images"] = reference_image_urls
                logger.info(f"使用 {len(reference_image_urls)} 张参考图")
            
            result = await retry_with_backoff(
                lambda: image_provider.generate_image(**generate_kwargs)
            )
            
            # 5. 提取并上传图片（使用通用工具函数）
            from src.utils.image_utils import extract_and_upload_image
            
            object_key = await extract_and_upload_image(
                result=result,
                user_id=str(project.owner_id),
                metadata={"character_id": str(char.id)}
            )

            # 6. 更新角色信息
            char.avatar_url = object_key
            
            # 7. 创建生成历史记录
            from src.services.generation_history_service import GenerationHistoryService
            from src.models.movie import GenerationType, MediaType
            
            history_service = GenerationHistoryService(self.db_session)
            await history_service.create_history(
                resource_type=GenerationType.CHARACTER_AVATAR,
                resource_id=str(char.id),
                result_url=object_key,
                prompt=enhanced_prompt,  # 使用增强后的提示词
                media_type=MediaType.IMAGE,
                model=model,
                api_key_id=str(api_key.id) if api_key else None
            )
            
            await self.db_session.commit()
            return object_key
            
        except Exception as e:
            logger.error(f"生成角色头像失败: {e}")
            raise

    async def batch_generate_avatars(self, project_id: str, api_key_id: str, model: str = None) -> dict:
        """
        批量生成角色定妆照
        使用并发请求提高效率
        """
        from sqlalchemy import select
        import asyncio
        
        # 获取所有未生成头像的角色
        stmt = select(MovieCharacter).where(
            MovieCharacter.project_id == project_id,
            MovieCharacter.avatar_url == None
        )
        result = await self.db_session.execute(stmt)
        characters = result.scalars().all()
        
        if not characters:
            return {"success": 0, "failed": 0, "total": 0, "message": "没有需要生成头像的角色"}
        
        logger.info(f"开始批量生成 {len(characters)} 个角色的定妆照")
        
        # 定义单个角色的生成任务
        async def generate_single(char):
            try:
                if not char.generated_prompt:
                    logger.warning(f"角色 {char.name} 没有generated_prompt,跳过")
                    return {"success": False, "character": char.name, "error": "缺少生成提示词"}
                
                await self.generate_character_avatar(
                    str(char.id),
                    api_key_id,
                    model,
                    char.generated_prompt,
                    "cinematic"
                )
                logger.info(f"成功生成角色 {char.name} 的头像")
                return {"success": True, "character": char.name}
            except Exception as e:
                logger.error(f"生成角色 {char.name} 头像失败: {e}")
                return {"success": False, "character": char.name, "error": str(e)}
        
        # 并发执行所有生成任务
        results = await asyncio.gather(*[generate_single(char) for char in characters], return_exceptions=True)
        
        # 统计结果
        success_count = sum(1 for r in results if isinstance(r, dict) and r.get("success"))
        failed_count = len(results) - success_count
        
        logger.info(f"批量生成完成: 成功 {success_count}, 失败 {failed_count}")
        
        return {
            "success": success_count,
            "failed": failed_count,
            "total": len(characters),
            "details": results
        }

__all__ = ["MovieCharacterService"]

if __name__ == "__main__":
    
    # 测试代码
    import asyncio
    
    prompt = """
    TRIPLE-VIEW CHARACTER SHEET: front, 90° side, back views of cyberpunk hacker "Kitsune", year 2089.

Details:
- Japanese female, 22, augmented with neon cyan neural ports behind ears
- Outfit: asymmetrical leather jacket, holographic crop top, cargo pants with utility straps
- Hair: short silver bob with glowing pink streaks
- Accessories: AR glasses, data-glove on right hand, katana sheath on back

CONSISTENCY LOCK:
- Same port positions and glow intensity
- Jacket pattern must align perfectly
- Hair length and streak position identical
- Glasses frame style consistent

Render: Unreal Engine 5, photorealistic, studio lighting, black background. --ar 16:9
    """
    
    # 测试角色头像生成
    async def test_generate_avatar():
        from src.core.database import get_async_db
        async with get_async_db() as session:
            service = MovieCharacterService(session)
            url = await service.generate_character_avatar(
                character_id="8341a465-d0ae-4c77-93d9-e0d799de1568",
                api_key_id="457f4337-8f54-4749-a2d6-78e1febf9028",
                model="gemini-3-pro-image-preview",
                # prompt="Cinematic lighting, movie still, 8k, photorealistic, dramatic, highly detailed face, 赛博朋克世界观下,男性，约35岁，眼神深邃且带着长期的疲惫。面部有轻微的擦伤。身着深灰色战术外骨骼装甲，带有明显的战斗损耗痕迹。短发凌乱，体型健硕但并不夸张，展现出敏捷与力量感。",
                prompt=prompt,
                style="cinematic"
            )
            print("Generated Avatar URL:", url)
    asyncio.run(test_generate_avatar())