"""
电影剧本与角色相关模型 - 统一管理
"""

from enum import Enum
from typing import List, Optional
from sqlalchemy import Column, String, Text, Integer, ForeignKey, Index, JSON, select, Boolean
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import relationship
from .base import BaseModel

class ScriptStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"

class GenerationType(str, Enum):
    """生成类型枚举"""
    SCENE_IMAGE = "scene_image"
    SHOT_KEYFRAME = "shot_keyframe"
    CHARACTER_AVATAR = "character_avatar"
    TRANSITION_VIDEO = "transition_video"

class MediaType(str, Enum):
    """媒体类型枚举"""
    IMAGE = "image"
    VIDEO = "video"

class MovieGenerationHistory(BaseModel):
    """电影生成历史统一记录表"""
    __tablename__ = 'movie_generation_history'
    
    # 资源类型和ID（使用多态关联）
    resource_type = Column(String(50), nullable=False, index=True, comment="资源类型: scene_image/shot_keyframe/character_avatar/transition_video")
    resource_id = Column(PostgreSQLUUID(as_uuid=True), nullable=False, index=True, comment="资源ID（scene_id/shot_id/character_id/transition_id）")
    
    # 媒体类型
    media_type = Column(String(20), nullable=False, index=True, comment="媒体类型: image/video")
    
    # 生成结果
    result_url = Column(String(500), nullable=False, comment="生成的图片/视频URL")
    prompt = Column(Text, nullable=False, comment="生成时使用的提示词")
    
    # 生成参数
    model = Column(String(100), comment="使用的模型名称")
    api_key_id = Column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey('api_keys.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
        comment="使用的API Key",
    )
    
    # 选择状态
    is_selected = Column(Boolean, default=False, index=True, comment="是否被选中使用")
    
    # 关系
    api_key = relationship("APIKey")
    
    # 复合索引
    __table_args__ = (
        Index('idx_resource_type_id', 'resource_type', 'resource_id'),
        Index('idx_resource_selected', 'resource_type', 'resource_id', 'is_selected'),
    )

    def __repr__(self) -> str:
        return f"<MovieGenerationHistory(id={self.id}, type={self.resource_type}, media={self.media_type})>"


class MovieScript(BaseModel):
    """电影剧本模型 - 关联到章节"""
    __tablename__ = 'movie_scripts'

    chapter_id = Column(PostgreSQLUUID(as_uuid=True), ForeignKey('chapters.id'), nullable=False, index=True, comment="章节外键")
    status = Column(String(20), default=ScriptStatus.PENDING, index=True, comment="剧本状态")
    
    # 关系
    chapter = relationship("Chapter")
    scenes = relationship("MovieScene", back_populates="script", cascade="all, delete-orphan", order_by="MovieScene.order_index")

    def __repr__(self) -> str:
        return f"<MovieScript(id={self.id}, chapter_id={self.chapter_id}, status={self.status})>"

class MovieScene(BaseModel):
    """电影场景模型 - 剧本中的一个场景"""
    __tablename__ = 'movie_scenes'

    script_id = Column(PostgreSQLUUID(as_uuid=True), ForeignKey('movie_scripts.id'), nullable=False, index=True)
    order_index = Column(Integer, nullable=False, comment="场景顺序")
    scene = Column(Text, nullable=False, comment="场景详细描述")
    characters = Column(JSON, default=list, comment="场景中出现的角色名称列表")
    
    # 场景图相关字段
    scene_image_url = Column(String(500), comment="场景图片URL（无人物的场景环境图）")
    scene_image_prompt = Column(Text, comment="场景图生成提示词")
    
    # 关系
    script = relationship("MovieScript", back_populates="scenes")
    shots = relationship("MovieShot", back_populates="scene", cascade="all, delete-orphan", order_by="MovieShot.order_index")
    generation_history = relationship(
        "MovieGenerationHistory",
        primaryjoin="and_(MovieScene.id==foreign(MovieGenerationHistory.resource_id), "
                    "MovieGenerationHistory.resource_type=='scene_image')",
        cascade="all, delete-orphan",
        viewonly=False
    )

    def __repr__(self) -> str:
        return f"<MovieScene(id={self.id}, script_id={self.script_id}, order={self.order_index})>"

class MovieShot(BaseModel):
    """电影分镜（镜头）模型 - 场景中的一个镜头"""
    __tablename__ = 'movie_shots'

    scene_id = Column(PostgreSQLUUID(as_uuid=True), ForeignKey('movie_scenes.id'), nullable=False, index=True)
    order_index = Column(Integer, nullable=False, comment="镜头顺序")
    shot = Column(Text, nullable=False, comment="分镜描述")
    dialogue = Column(Text, comment="人物对话内容")
    characters = Column(JSON, default=list, comment="分镜中出现的角色名称列表")
    
    # 关键帧资源
    keyframe_url = Column(String(500), comment="分镜关键帧图片URL")
    
    # 关系
    scene = relationship("MovieScene", back_populates="shots")
    generation_history = relationship(
        "MovieGenerationHistory",
        primaryjoin="and_(MovieShot.id==foreign(MovieGenerationHistory.resource_id), "
                    "MovieGenerationHistory.resource_type=='shot_keyframe')",
        cascade="all, delete-orphan",
        viewonly=False
    )

    def __repr__(self) -> str:
        # 使用 object.__repr__ 避免访问可能导致 DetachedInstanceError 的属性
        return object.__repr__(self)

class MovieShotTransition(BaseModel):
    """分镜过渡视频模型 - 存储两个连续分镜之间的视频"""
    __tablename__ = 'movie_shot_transitions'

    script_id = Column(PostgreSQLUUID(as_uuid=True), ForeignKey('movie_scripts.id'), nullable=False, index=True)
    from_shot_id = Column(PostgreSQLUUID(as_uuid=True), ForeignKey('movie_shots.id'), nullable=False, index=True)
    to_shot_id = Column(PostgreSQLUUID(as_uuid=True), ForeignKey('movie_shots.id'), nullable=False, index=True)
    order_index = Column(Integer, nullable=False, comment="过渡顺序")
    
    # 视频生成相关
    video_prompt = Column(Text, comment="视频生成提示词")
    video_url = Column(String(500), comment="生成的视频URL")
    video_task_id = Column(String(100), comment="视频生成任务ID")
    provider_context_json = Column(JSON, nullable=True, comment="提交时的供应协议和连接快照")
    status = Column(String(20), default="pending", index=True, comment="生成状态")
    error_message = Column(Text, nullable=True, comment="失败错误信息")
    
    # 追踪信息
    api_key_id = Column(PostgreSQLUUID(as_uuid=True), ForeignKey('api_keys.id'), nullable=True, index=True, comment="使用的API Key")
    user_id = Column(PostgreSQLUUID(as_uuid=True), ForeignKey('users.id'), nullable=True, index=True, comment="所属用户")
    
    # 关系
    script = relationship("MovieScript")
    from_shot = relationship("MovieShot", foreign_keys=[from_shot_id])
    to_shot = relationship("MovieShot", foreign_keys=[to_shot_id])
    api_key = relationship("APIKey", foreign_keys=[api_key_id])
    user = relationship("User", foreign_keys=[user_id])
    generation_history = relationship(
        "MovieGenerationHistory",
        primaryjoin="and_(MovieShotTransition.id==foreign(MovieGenerationHistory.resource_id), "
                    "MovieGenerationHistory.resource_type=='transition_video')",
        cascade="all, delete-orphan",
        viewonly=False
    )

    def __repr__(self) -> str:
        return f"<MovieShotTransition(id={self.id}, from={self.from_shot_id}, to={self.to_shot_id})>"

class MovieCharacter(BaseModel):
    """电影角色模型"""
    __tablename__ = 'movie_characters'

    project_id = Column(PostgreSQLUUID(as_uuid=True), ForeignKey('projects.id'), nullable=False, index=True, comment="项目外键")
    name = Column(String(100), nullable=False, comment="角色名称")
    role_description = Column(Text, comment="角色描述/背景")
    visual_traits = Column(Text, comment="视觉特征描述(用于提示词)")
    dialogue_traits = Column(Text, comment="对话特征描述(语气、口癖等)")
    
    # 三视图生成相关字段
    era_background = Column(String(200), comment="时代背景(如: 1940s WWII, Victorian Era)")
    occupation = Column(String(200), comment="职业/社会地位")
    key_visual_traits = Column(JSON, default=list, comment="核心视觉特征列表(3-4个关键特征)")
    generated_prompt = Column(Text, comment="生成的三视图提示词")
    
    # 资源
    avatar_url = Column(String(500), comment="角色头像URL")
    reference_images = Column(JSON, default=list, comment="参考图URL列表(人物一致性关键)")
    
    # 关系
    project = relationship("Project")
    generation_history = relationship(
        "MovieGenerationHistory",
        primaryjoin="and_(MovieCharacter.id==foreign(MovieGenerationHistory.resource_id), "
                    "MovieGenerationHistory.resource_type=='character_avatar')",
        cascade="all, delete-orphan",
        viewonly=False
    )

    def __repr__(self) -> str:
        return f"<MovieCharacter(id={self.id}, name={self.name})>"
    
    @classmethod
    async def batch_create(cls, db_session, project_id: str, characters_data: List[dict]):
        """批量创建角色"""
        characters = []
        for data in characters_data:
            char = cls(
                project_id=project_id,
                name=data.get('name'),
                role_description=data.get('role_description'),
                visual_traits=data.get('visual_traits'),
                dialogue_traits=data.get('dialogue_traits'),
                era_background=data.get('era_background'),
                occupation=data.get('occupation'),
                key_visual_traits=data.get('key_visual_traits', []),
                generated_prompt=data.get('generated_prompt'),
                avatar_url=data.get('avatar_url'),
                reference_images=data.get('reference_images', [])
            )
            db_session.add(char)
            characters.append(char)
        await db_session.flush()
        return characters
    
    def to_dict(self, sign_urls: bool = True):
        """转换为字典，可选择是否签名URL"""
        from src.utils.storage import storage_client
        from datetime import timedelta
        
        data = {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "name": self.name,
            "role_description": self.role_description,
            "visual_traits": self.visual_traits,
            "dialogue_traits": self.dialogue_traits,
            "era_background": self.era_background,
            "occupation": self.occupation,
            "key_visual_traits": self.key_visual_traits or [],
            "generated_prompt": self.generated_prompt,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
        
        # 处理URL签名
        if sign_urls:
            data["avatar_url"] = (
                storage_client.get_presigned_url(self.avatar_url, timedelta(hours=24))
                if self.avatar_url and not self.avatar_url.startswith("http")
                else self.avatar_url
            )
            data["reference_images"] = [
                storage_client.get_presigned_url(img, timedelta(hours=24))
                if img and not img.startswith("http")
                else img
                for img in (self.reference_images or [])
            ]
        else:
            data["avatar_url"] = self.avatar_url
            data["reference_images"] = self.reference_images or []
        
        return data
