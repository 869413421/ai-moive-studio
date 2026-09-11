"""
对话提示词引擎 - 为分镜设计人物对话的表现力和口型同步提示词
"""

from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.logging import get_logger
from src.models.movie import MovieShot, MovieCharacter, MovieScene, MovieScript
from src.services.base import BaseService
from src.services.provider.factory import ProviderFactory
from src.services.api_key import APIKeyService

logger = get_logger(__name__)

class DialoguePromptEngine(BaseService):
    """
    对话表现力提示词生成服务
    要求外部注入 AsyncSession。
    """

    def __init__(self, db_session: AsyncSession):
        super().__init__(db_session)

    PERFORMANCE_DESIGN_PROMPT = """
你是一个顶级的表演指导。请根据分镜内容和角色对话，设计出精密的**视觉表现提示词**。
这些提示词将用于AI视频生成，以确保角色的口型、神情和动作与对话内容高度吻合。

### 输入上下文：
- **角色信息**：{char_traits}
- **对话内容**："{dialogue}"
- **镜头画面描述**：{visual_desc}
- **表演要求**：{performance_hint}

### 输出要求：
请输出一段英文提示词（70词以内），重点描述角色的面部微表情、口型运动（lip-sync）、眼神。要求自然、富有戏剧张力。
不要输出任何解释，只输出提示词。

### 提示词范例：
"The character's mouth moves naturally synchronized with the speech, lips forming precise vowels. Eyes narrowing with subtle intensity, eyebrows slightly furrowed to express controlled anger. A slight twitch at the corner of the mouth, enhancing the realistic facial performance."
"""

    async def design_performance_prompt(self, shot_id: str, character_id: Optional[str], api_key_id: str) -> str:
        """
        为分镜设计对话表现提示词
        """
        shot = await self.db_session.get(MovieShot, shot_id)
        if not shot: raise ValueError("未找到分镜")
        
        char_traits = "Unknown character"
        if character_id:
            character = await self.db_session.get(MovieCharacter, character_id)
            if character:
                char_traits = f"{character.name}: {character.visual_traits}, voice style: {character.dialogue_traits}"

        # 加载 API Key (假设从项目 owner 获取)
        from src.models.chapter import Chapter
        stmt = select(Chapter).join(MovieScript).join(MovieScene).where(MovieScene.id == shot.scene_id)
        chapter = (await self.db_session.execute(stmt)).scalar_one_or_none()
        
        api_key_service = APIKeyService(self.db_session)
        api_key = await api_key_service.get_api_key_by_id(api_key_id, str(chapter.project.owner_id))
        
        llm_provider = ProviderFactory.from_key(api_key)

        try:
            system_prompt = "你是一个专业的AI视频提示词优化专家。只输出提示词文本。"
            user_prompt = self.PERFORMANCE_DESIGN_PROMPT.format(
                char_traits=char_traits,
                dialogue=shot.dialogue or "None",
                visual_desc=shot.shot,
                performance_hint="Natural performance"
            )
            
            response = await llm_provider.completions(
                model=None,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            )
            
            performance_prompt = response.choices[0].message.content.strip()
            shot.performance_prompt = performance_prompt
            await self.db_session.commit()
            return performance_prompt
            
        except Exception as e:
            logger.error(f"生成对话表现提示词失败: {e}")
            raise

__all__ = ["DialoguePromptEngine"]
