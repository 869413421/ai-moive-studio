from __future__ import annotations

import json
from typing import Any


def _string(value: Any) -> str:
    return str(value or "").strip()


def _bullet_block(values: list[str] | None) -> str:
    lines = [f"- {_string(value)}" for value in list(values or []) if _string(value)]
    return "\n".join(lines)


def _creative_spec_block(spec: dict[str, Any] | None) -> str:
    payload = dict(spec or {})
    if not payload:
        return ""
    lines: list[str] = []
    simple_fields = {
        "reference_style": "参考气质",
        "project_type": "作品类型",
        "narrative_tone": "叙事气质",
    }
    for key, label in simple_fields.items():
        value = _string(payload.get(key))
        if value:
            lines.append(f"{label}：{value}")

    cinematography = dict(payload.get("cinematography") or {})
    if cinematography:
        capture_medium = _string(cinematography.get("capture_medium"))
        lens_language = _string(cinematography.get("lens_language"))
        if capture_medium:
            lines.append(f"拍摄媒介：{capture_medium}")
        if lens_language:
            lines.append(f"镜头语言：{lens_language}")
        effects = _bullet_block(list(cinematography.get("visual_effects") or []))
        if effects:
            lines.append("画面特征：\n" + effects)

    color_palette = dict(payload.get("color_palette") or {})
    if color_palette:
        tones = _bullet_block(list(color_palette.get("primary_tones") or []))
        saturation = _string(color_palette.get("saturation"))
        if tones:
            lines.append("主色调：\n" + tones)
        if saturation:
            lines.append(f"饱和度：{saturation}")

    environment = dict(payload.get("environment") or {})
    if environment:
        traits = _bullet_block(list(environment.get("scene_traits") or []))
        if traits:
            lines.append("环境特征：\n" + traits)

    must_include = _bullet_block(list(payload.get("must_include") or []))
    if must_include:
        lines.append("必须出现元素：\n" + must_include)

    return "\n".join(lines).strip()


def build_prepare_workflow_script_prompt(input_data: dict[str, Any]) -> str:
    idea = _string(input_data.get("idea"))
    script_type = _string(input_data.get("script_type"))
    style_id = _string(input_data.get("style_id"))
    dialogue_mode = _string(input_data.get("dialogue_mode") or "sparse")
    tone = _string(input_data.get("tone"))
    language = _string(input_data.get("language"))
    duration_target = _string(input_data.get("duration_target"))
    shot_duration_seconds = int(input_data.get("shot_duration_seconds") or 0)
    constraints = _bullet_block(list(input_data.get("constraints") or []))
    creative_spec = _creative_spec_block(dict(input_data.get("creative_spec") or {}))

    sections = [
        "你是一名电影编剧与预制作统筹。请根据用户创意生成后续可直接进入角色提取、分镜、关键帧与视频生成链路的完整剧本。",
        "",
        "输出要求：",
        "- 只输出剧本文本，不要输出 Markdown 标题，不要输出解释。",
        "- 剧本必须包含明确的角色、场景、镜头动作和情绪推进。",
        "- 剧本必须能继续用于角色三视图提示词、关键帧提示词和视频提示词生成。",
        "",
        f"核心创意：{idea}",
        f"脚本类型：{script_type}",
        f"视觉风格：{style_id}",
        f"对白模式：{dialogue_mode}",
        f"输出语言：{language}",
        f"目标总时长：{duration_target}",
        f"单镜头目标秒数：{shot_duration_seconds}",
    ]
    if tone:
        sections.append(f"叙事语气：{tone}")
    if constraints:
        sections.extend(["额外约束：", constraints])
    if creative_spec:
        sections.extend(["已确认创作规格：", creative_spec])
    return "\n".join(sections).strip()


def build_prepare_workflow_character_prompt(input_data: dict[str, Any]) -> str:
    script_text = _string(input_data.get("script_text"))
    script_type = _string(input_data.get("script_type"))
    style_id = _string(input_data.get("style_id"))
    tone = _string(input_data.get("tone"))
    constraints = _bullet_block(list(input_data.get("constraints") or []))
    creative_spec = _creative_spec_block(dict(input_data.get("creative_spec") or {}))

    sections = [
        "你是一个资深的选角导演和角色设定师。请分析以下剧本，提取所有主要角色和重要配角，包括人类与非人类角色。",
        "",
        "### 输出要求",
        "必须只输出一个 JSON 对象，不要输出 Markdown，不要输出解释。",
        "输出结构必须严格如下：",
        json.dumps(
            {
                "characters": [
                    {
                        "name": "角色姓名",
                        "era_background": "时代背景",
                        "occupation": "职业或社会地位",
                        "role_description": "角色身份、背景、性格特点",
                        "visual_traits": "适合 AI 生图的详细视觉特征描述",
                        "key_visual_traits": ["核心视觉特征1", "核心视觉特征2", "核心视觉特征3"],
                        "dialogue_traits": "角色对话风格",
                        "character_type": "human/animal/creature/machine/vehicle/object/other",
                        "three_view_prompt": "可直接用于图片生成的角色三视图中文提示词",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        "",
        "### 字段规则",
        "每个 character 对象必须包含 name、era_background、occupation、role_description、visual_traits、key_visual_traits、dialogue_traits、character_type、three_view_prompt。",
        "key_visual_traits 需要输出 3 到 4 个最关键的视觉特征，并按重要性排序。",
        "character_type 只能从 human、animal、creature、machine、vehicle、object、other 中选择一个。",
        "角色名称必须在整个输出里保持完全一致，不允许别名漂移。",
        "three_view_prompt 必须强调标准三视图展示、角色一致性、正面/侧面/背面完整展示，并且必须体现 "
        + style_id
        + " 风格。",
        "three_view_prompt 必须是可直接用于图片生成的完整中文提示词，不要输出英文标签串。",
        "",
        "### 风格与补充要求",
        f"script_type: {script_type}",
        f"style_id: {style_id}",
    ]
    if tone:
        sections.append(f"tone: {tone}")
    if constraints:
        sections.extend(["额外约束：", constraints])
    if creative_spec:
        sections.extend(["### 已确认创作规格", creative_spec])
    sections.extend(["", "### 待分析剧本", "---", script_text, "---", "", "最终只输出 JSON。"])
    return "\n".join(sections).strip()


def build_prepare_workflow_storyboard_prompt(input_data: dict[str, Any]) -> str:
    script_text = _string(input_data.get("script_text"))
    script_type = _string(input_data.get("script_type"))
    style_id = _string(input_data.get("style_id"))
    tone = _string(input_data.get("tone"))
    granularity = _string(input_data.get("granularity") or "详细")
    shot_duration_seconds = int(input_data.get("shot_duration_seconds") or 0)
    character_names = [str(value).strip() for value in list(input_data.get("character_names") or []) if str(value).strip()]
    character_summaries = [str(value).strip() for value in list(input_data.get("character_summaries") or []) if str(value).strip()]
    constraints = _bullet_block(list(input_data.get("constraints") or []))
    creative_spec = _creative_spec_block(dict(input_data.get("creative_spec") or {}))

    character_names_text = ",".join(character_names) if character_names else "无"
    sections = [
        "你是一名国际获奖级的电影导演与分镜设计师。请分析以下剧本，完成场景拆分、分镜提取，并为每个镜头生成关键帧图片提示词和视频提示词。",
        "",
        "### 输出要求",
        "必须只输出一个 JSON 对象，不要输出 Markdown，不要输出解释。",
        "输出结构必须严格如下：",
        json.dumps(
            {
                "scenes": [
                    {
                        "order_index": 1,
                        "scene": "场景详细描述",
                        "characters": ["场景中出现的角色1", "角色2"],
                        "shots": [
                            {
                                "order_index": 1,
                                "narrative": "详细画面描述",
                                "characters": ["该分镜中出现的角色"],
                                "storyboard_text": "完整中文分镜文本",
                                "keyframe_prompt": "完整中文关键帧提示词",
                                "video_prompt": "完整中文视频提示词",
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        "",
        "### 核心模型适配原则",
        f"* 每一个 Shot = 一个固定 {shot_duration_seconds} 秒的视频。",
        "* 视频模型仅使用 Shot 的起始画面状态和结束画面状态，中间内容由模型连续插值。",
        "* 因此每个 Shot 都必须隐含清晰的起始状态与结束状态，关键动作结果和情绪落点必须体现在镜头末尾可见画面。",
        "",
        "## 【已知主要角色列表】",
        "[" + character_names_text + "]",
        "",
        "### Shot 字段规则",
        "每个 shot 对象必须包含 order_index、narrative、characters、storyboard_text、keyframe_prompt、video_prompt。",
        "characters 数组只能使用已知主要角色列表中的角色名称；没有角色时输出空数组。",
        "storyboard_text、keyframe_prompt、video_prompt 都必须使用中文完整表述。",
        "必须保留已确认创作规格里的风格、镜头语言、材质和色彩约束，不允许抽象丢失。",
        "",
        "### 风格与补充要求",
        f"script_type: {script_type}",
        f"style_id: {style_id}",
        f"tone: {tone}",
        f"granularity: {granularity}",
        f"shot_duration_seconds: {shot_duration_seconds}",
    ]
    if character_summaries:
        sections.extend(["角色摘要：", "\n".join(character_summaries)])
    sections.extend(["", "### 待分析剧本", "---", script_text, "---"])
    if constraints:
        sections.extend(["额外约束：", constraints])
    if creative_spec:
        sections.extend(["### 已确认创作规格", creative_spec])
    sections.extend(["", "最终只输出 JSON。"])
    return "\n".join(sections).strip()
