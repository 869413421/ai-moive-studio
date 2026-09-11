"""
字幕服务 - 处理字幕生成、时间轴和LLM纠错

负责:
- 使用Whisper生成字幕时间轴
- 使用LLM纠正字幕中的错别字
- 创建FFmpeg字幕滤镜
- 文本分割和格式化
"""

import re
from typing import Dict, List, Optional

from src.core.logging import get_logger
from src.models import APIKey
from src.services.faster_whisper_service import transcription_service
from src.services.provider.factory import ProviderFactory
from src.utils.ffmpeg_utils import get_audio_duration

logger = get_logger(__name__)


class SubtitleService:
    """字幕服务 - 处理所有字幕相关操作"""

    def generate_subtitle_timeline(self, audio_path: str, original_text: str) -> dict:
        """
        生成字幕时间轴

        Args:
            audio_path: 音频文件路径
            original_text: 原始句子文本（用于提示Whisper更好识别）

        Returns:
            字幕数据，包含segments和duration
        """
        try:
            # 使用Whisper服务进行转录
            results, srt_content = transcription_service.transcribe(
                audio_path,
                output_format="json",
                initial_prompt=original_text
            )

            # 获取音频时长
            duration = get_audio_duration(audio_path) or 0

            return {
                "segments": results,
                "duration": duration
            }

        except Exception as e:
            logger.error(f"生成字幕时间轴失败: {e}")
            raise

    async def correct_subtitle_with_llm(
            self,
            subtitle_data: dict,
            original_text: str,
            api_key: APIKey,
            model: str = None
    ) -> dict:
        """
        使用LLM纠正字幕中的错别字

        Args:
            subtitle_data: Whisper生成的字幕数据（包含segments）
            original_text: 原始句子文本
            api_key: API密钥对象
            model: 模型名称（可选）

        Returns:
            纠正后的字幕数据
        """
        try:
            # 提取所有segment的文本
            segments = subtitle_data.get("segments", [])
            if not segments:
                logger.warning("字幕数据为空，跳过LLM纠错")
                return subtitle_data

            # 构建当前识别的文本
            recognized_text = " ".join([seg.get("text", "").strip() for seg in segments])

            # 如果识别文本为空，跳过
            if not recognized_text:
                logger.warning("识别文本为空，跳过LLM纠错")
                return subtitle_data

            # 创建LLM provider
            llm_provider = ProviderFactory.from_key(api_key, max_concurrency=1)



            # 构建提示词 - 让LLM纠正整个时间轴JSON
            system_prompt = """你是一个专业的字幕纠错助手。你的任务是纠正语音识别字幕中的错别字。

⚠️ 重要规则（必须严格遵守）：
1. 我会给你原文和Whisper识别的字幕时间轴JSON
2. 你需要对比原文，纠正字幕时间轴中每个segment的text字段的错别字
3. **绝对不能删除、增加或重组任何词语**，只能修正错别字
4. **必须保持相同的词数和顺序**，即使某些词看起来奇怪也要保留
5. 保持JSON结构完全不变，只修改text和word字段中的错别字
6. 保持时间信息(start, end)完全不变
7. 如果有words字段，也要纠正其中的word字段，但不能改变words数组的长度
8. 只纠正明显的错别字（如：同音字、形近字），保持口语化特点
9. 如果不确定是否是错别字，保持原样不改
10. 返回JSON格式：{"segments": [...纠正后的segments数组...]}

示例：
- ✅ 正确："他望著" → "他望着"（繁简转换）
- ✅ 正确："抑郁" → "呓语"（同音错字）
- ❌ 错误：删除任何词语
- ❌ 错误：合并或拆分词语
- ❌ 错误：改变词语顺序"""

            # 构建字幕时间轴的简化版本（只包含需要的字段）
            segments_for_llm = []
            for idx, seg in enumerate(segments):
                seg_data = {
                    "index": idx,
                    "text": seg.get("text", ""),
                    "start": seg.get("start", 0),
                    "end": seg.get("end", 0)
                }
                # 如果有词级时间轴，也包含进去
                if "words" in seg and seg["words"]:
                    seg_data["words"] = [
                        {
                            "word": w.get("word", ""),
                            "start": w.get("start", 0),
                            "end": w.get("end", 0)
                        }
                        for w in seg["words"]
                    ]
                segments_for_llm.append(seg_data)

            import json
            timeline_json = json.dumps({"segments": segments_for_llm}, ensure_ascii=False, indent=2)

            user_prompt = f"""原文：
{original_text}

语音识别的字幕时间轴JSON：
{timeline_json}

请纠正字幕时间轴中的错别字。

🚨 严格要求：
1. 每个segment的words数组长度必须与原始完全一致
2. 只修正明显的错别字，不改变词语
3. 不确定的保持原样
4. 返回前请验证词数是否一致

请返回纠正后的完整JSON。"""

            # 调用LLM
            logger.info(f"[LLM纠错] 开始纠正字幕时间轴，模型: {model}")
            logger.debug(f"[LLM纠错] 原文: {original_text}")
            logger.debug(f"[LLM纠错] 发送的时间轴: {timeline_json}")
            
            response = await llm_provider.completions(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"}
            )

            # 解析响应
            correction_result = json.loads(response.choices[0].message.content)
            corrected_segments = correction_result.get("segments", [])
            
            if not corrected_segments:
                logger.warning("[LLM纠错] LLM返回空segments，使用原始字幕")
                return subtitle_data
            
            logger.info(f"[LLM纠错] 收到 {len(corrected_segments)} 个纠正后的segments")
            logger.debug(f"[LLM纠错] 纠正结果: {json.dumps(correction_result, ensure_ascii=False)}")

            # 将纠正后的文本应用回原始segments
            for corrected_seg in corrected_segments:
                idx = corrected_seg.get("index")
                if idx is None or idx < 0 or idx >= len(segments):
                    continue
                
                # 更新segment的文本
                corrected_text = corrected_seg.get("text", "").strip()
                if corrected_text:
                    segments[idx]["text"] = corrected_text
                    logger.debug(f"[LLM纠错] Segment {idx}: '{segments[idx].get('text', '')}' -> '{corrected_text}'")
                
                # 如果LLM返回了纠正后的words，也更新
                if "words" in corrected_seg and corrected_seg["words"]:
                    if "words" in segments[idx]:
                        # 确保words数量匹配
                        corrected_words = corrected_seg["words"]
                        original_words = segments[idx]["words"]
                        
                        # ⚠️ 严格验证：词数必须完全一致，否则会导致时间轴错位
                        if len(corrected_words) != len(original_words):
                            logger.warning(
                                f"[LLM纠错] ⚠️ Segment {idx} 词数不匹配: "
                                f"原始{len(original_words)}词, 纠正后{len(corrected_words)}词, "
                                f"拒绝此segment的词级纠正以避免时间轴错位"
                            )
                            # 跳过这个segment的词级纠正，但保留segment级别的文本纠正
                            continue
                        
                        # 更新每个word的文本，保持时间信息
                        for i, corrected_word in enumerate(corrected_words):
                            if i < len(original_words):
                                old_word = original_words[i]["word"]
                                new_word = corrected_word.get("word", old_word)
                                # 保持原始时间，只更新文本
                                original_words[i]["word"] = new_word
                                if old_word != new_word:
                                    logger.debug(f"[LLM纠错]   Word {i}: '{old_word}' -> '{new_word}'")

            logger.info(f"[LLM纠错] 字幕时间轴纠正完成")
            return subtitle_data

        except Exception as e:
            logger.error(f"LLM纠正字幕失败: {e}", exc_info=True)
            # 失败时返回原始字幕
            logger.warning("LLM纠错失败，使用原始字幕")
            return subtitle_data

    def split_text_into_lines(self, text: str, max_chars: int = 18) -> list:
        """
        智能分割文本为双行字幕（漫画解说标准）

        Args:
            text: 要分割的文本
            max_chars: 每行最大字符数（推荐15-20字）

        Returns:
            分割后的行列表（最多2行，不含标点）
        """
        # 移除所有标点符号
        punctuation_pattern = r'[，。！？；、,\.!?;]'
        clean_text = re.sub(punctuation_pattern, '', text).strip()

        if not clean_text:
            return []

        # 如果文本很短，直接返回单行
        if len(clean_text) <= max_chars:
            return [clean_text]

        # 分成两行（漫画解说标准）
        # 尽量在中间位置分割
        mid_point = len(clean_text) // 2

        # 在中间点附近找最佳分割位置
        best_split = mid_point
        for i in range(max(mid_point - 5, 0), min(mid_point + 5, len(clean_text))):
            if i > 0 and i < len(clean_text):
                best_split = i
                break

        line1 = clean_text[:best_split].strip()
        line2 = clean_text[best_split:].strip()

        # 如果第二行太长，截断
        if len(line2) > max_chars:
            line2 = line2[:max_chars]

        # 如果第一行太长，调整
        if len(line1) > max_chars:
            line1 = line1[:max_chars]

        return [line1, line2] if line2 else [line1]

    def _add_subtitle_filter(
            self,
            filters: list,
            words: list,
            font_size: int,
            color: str,
            base_y_pos: int,
            max_line_chars: int,
            video_height: int
    ) -> None:
        """
        添加字幕滤镜，支持双行显示
        
        Args:
            filters: 滤镜列表
            words: 词列表，每个词包含 text, start, end
            font_size: 字体大小
            color: 字体颜色
            base_y_pos: 基准Y坐标
            max_line_chars: 每行最大字符数
            video_height: 视频高度
        """
        if not words:
            return
            
        # 合并所有词的文本
        full_text = "".join([w["text"] for w in words])
        start_time = words[0]["start"]
        end_time = words[-1]["end"]
        
        # 计算总字符数
        total_len = len(full_text)
        
        # 如果文本长度不超过单行最大长度，显示单行
        if total_len <= max_line_chars:
            text_escaped = full_text.replace("'", "'\\\\\\''").replace(":", "\\:")
            filter_str = (
                f"drawtext="
                f"text='{text_escaped}':"
                f"fontsize={font_size}:"
                f"fontcolor={color}:"
                f"borderw=5:"
                f"bordercolor=black:"
                f"shadowcolor=black@0.7:"
                f"shadowx=4:"
                f"shadowy=4:"
                f"box=1:"
                f"boxcolor=black@0.65:"
                f"boxborderw=20:"
                f"x=(w-text_w)/2:"
                f"y={base_y_pos}:"
                f"enable='between(t,{start_time:.3f},{end_time:.3f})'"
            )
            filters.append(filter_str)
        else:
            # 文本过长，分成两行显示
            # 智能分割：尽量在中间位置分割
            mid_point = total_len // 2
            
            # 在中间点附近找最佳分割位置（优先在词边界）
            best_split = mid_point
            current_len = 0
            for i, word in enumerate(words):
                word_len = len(word["text"])
                if current_len + word_len >= mid_point:
                    # 检查是在当前词之前还是之后分割更合适
                    if abs(current_len - mid_point) < abs(current_len + word_len - mid_point):
                        best_split = current_len
                        split_index = i
                    else:
                        best_split = current_len + word_len
                        split_index = i + 1
                    break
                current_len += word_len
            else:
                split_index = len(words) // 2
                best_split = sum(len(w["text"]) for w in words[:split_index])
            
            # 分割文本
            line1_text = "".join([w["text"] for w in words[:split_index]])
            line2_text = "".join([w["text"] for w in words[split_index:]])
            
            # 确保每行不超过最大长度
            if len(line1_text) > max_line_chars:
                line1_text = line1_text[:max_line_chars]
            if len(line2_text) > max_line_chars:
                line2_text = line2_text[:max_line_chars]
            
            # 计算行间距（字体大小的1.2倍）
            line_spacing = int(font_size * 1.2)
            
            # 计算两行的Y坐标（使第一行在base_y_pos上方，第二行在下方）
            line1_y = base_y_pos - line_spacing // 2
            line2_y = base_y_pos + line_spacing // 2
            
            # 添加第一行字幕
            text1_escaped = line1_text.replace("'", "'\\\\\\''").replace(":", "\\:")
            filter_str1 = (
                f"drawtext="
                f"text='{text1_escaped}':"
                f"fontsize={font_size}:"
                f"fontcolor={color}:"
                f"borderw=5:"
                f"bordercolor=black:"
                f"shadowcolor=black@0.7:"
                f"shadowx=4:"
                f"shadowy=4:"
                f"box=1:"
                f"boxcolor=black@0.65:"
                f"boxborderw=20:"
                f"x=(w-text_w)/2:"
                f"y={line1_y}:"
                f"enable='between(t,{start_time:.3f},{end_time:.3f})'"
            )
            filters.append(filter_str1)
            
            # 添加第二行字幕
            text2_escaped = line2_text.replace("'", "'\\\\\\''").replace(":", "\\:")
            filter_str2 = (
                f"drawtext="
                f"text='{text2_escaped}':"
                f"fontsize={font_size}:"
                f"fontcolor={color}:"
                f"borderw=5:"
                f"bordercolor=black:"
                f"shadowcolor=black@0.7:"
                f"shadowx=4:"
                f"shadowy=4:"
                f"box=1:"
                f"boxcolor=black@0.65:"
                f"boxborderw=20:"
                f"x=(w-text_w)/2:"
                f"y={line2_y}:"
                f"enable='between(t,{start_time:.3f},{end_time:.3f})'"
            )
            filters.append(filter_str2)

    def create_subtitle_filter(
            self,
            subtitle_data: dict,
            gen_setting: dict
    ) -> str:
        """
        创建漫画解说字幕滤镜（固定位置，专业样式）

        Args:
            subtitle_data: 字幕数据
            gen_setting: 生成设置

        Returns:
            FFmpeg drawtext滤镜字符串
        """
        try:
            subtitle_style = gen_setting.get("subtitle_style", {})
            font_size = subtitle_style.get("font_size", 70)  # 适中字号
            color = subtitle_style.get("color", "white")

            # 动态计算字幕位置
            resolution = gen_setting.get("resolution", "1440x1080")
            try:
                w_str, h_str = resolution.split('x')
                width = int(w_str)
                height = int(h_str)
            except:
                width = 1440
                height = 1080

            # 根据宽高比决定位置
            # 竖屏 (9:16) -> 下方30%处 (避开抖音/快手底部UI)
            # 横屏 (16:9, 4:3) -> 下方15%处
            if height > width:
                fixed_y_pos = int(height * 0.7)
            else:
                fixed_y_pos = int(height * 0.85)

            logger.info(f"视频分辨率: {width}x{height}, 字幕Y坐标: {fixed_y_pos}")

            # 标点符号正则（用于检测断句）
            split_pattern = r'[，。！？；、,\.!?;:\'"()\[\]{}<>]'
            # 仅用于移除显示的标点
            remove_pattern = r'[，。！？；、,\.!?;:\'"()\[\]{}<>]'

            filters = []
            segments = subtitle_data.get("segments", [])

            for segment in segments:
                words = segment.get("words", [])

                if words:
                    # 使用词级时间轴构建字幕行
                    current_line_words = []
                    current_line_len = 0
                    max_line_chars = 15  # 每行最大字符数

                    for w in words:
                        raw_word = w.get("word", "")
                        # 检查这个词是否包含标点符号（意味着小句结束）
                        has_punctuation = bool(re.search(split_pattern, raw_word))

                        # 移除标点用于显示和长度计算
                        clean_word = re.sub(remove_pattern, '', raw_word).strip()

                        if not clean_word:
                            # 即使是纯标点，如果它标志着句子结束，也可能触发换行
                            if has_punctuation and current_line_words:
                                # 输出当前累积的字幕（可能是双行）
                                self._add_subtitle_filter(
                                    filters, current_line_words, font_size, color, 
                                    fixed_y_pos, max_line_chars, height
                                )
                                current_line_words = []
                                current_line_len = 0
                            continue

                        word_len = len(clean_word)

                        # 换行条件：加上当前词超过双行最大长度（30字）
                        if current_line_len + word_len > max_line_chars * 2 and current_line_words:
                            # 输出当前累积的字幕（可能是双行）
                            self._add_subtitle_filter(
                                filters, current_line_words, font_size, color, 
                                fixed_y_pos, max_line_chars, height
                            )
                            current_line_words = []
                            current_line_len = 0

                        # 添加词到当前行
                        current_line_words.append({
                            "text": clean_word,
                            "start": w.get("start", 0),
                            "end": w.get("end", 0)
                        })
                        current_line_len += word_len

                        # 如果当前词带有标点，且当前行不为空，则强制换行（小句结束）
                        if has_punctuation and current_line_words:
                            self._add_subtitle_filter(
                                filters, current_line_words, font_size, color, 
                                fixed_y_pos, max_line_chars, height
                            )
                            current_line_words = []
                            current_line_len = 0

                    # 处理最后一行
                    if current_line_words:
                        self._add_subtitle_filter(
                            filters, current_line_words, font_size, color, 
                            fixed_y_pos, max_line_chars, height
                        )

                else:
                    # 没有词级时间轴，使用比例计算时间（回退方案）
                    text = segment.get("text", "").strip()
                    if not text:
                        continue

                    # 优先按标点分割
                    # 使用正则保留分隔符，以便知道在哪里分割的
                    parts = re.split(f'({split_pattern})', text)
                    lines = []
                    current_part = ""

                    for part in parts:
                        # 如果是标点
                        if re.match(split_pattern, part):
                            if current_part:
                                lines.append(current_part)
                                current_part = ""
                        else:
                            # 如果是文字
                            if len(current_part) + len(part) > 18:
                                if current_part:
                                    lines.append(current_part)
                                current_part = part
                            else:
                                current_part += part

                    if current_part:
                        lines.append(current_part)

                    # 移除每行中的标点
                    clean_lines = [re.sub(remove_pattern, '', line).strip() for line in lines if
                                   re.sub(remove_pattern, '', line).strip()]

                    if not clean_lines:
                        continue

                    segment_start = segment.get("start", 0)
                    segment_end = segment.get("end", 0)
                    total_duration = segment_end - segment_start
                    total_length = len("".join(clean_lines))

                    current_start = segment_start

                    for line_text in clean_lines:
                        # 按长度比例计算持续时间
                        line_len = len(line_text)
                        if total_length > 0:
                            line_duration = total_duration * (line_len / total_length)
                        else:
                            line_duration = total_duration / len(clean_lines)

                        line_end = current_start + line_duration

                        text_escaped = line_text.replace("'", "'\\\\\\''").replace(":", "\\:")

                        filter_str = (
                            f"drawtext="
                            f"text='{text_escaped}':"
                            f"fontsize={font_size}:"
                            f"fontcolor={color}:"
                            f"borderw=5:"
                            f"bordercolor=black:"
                            f"shadowcolor=black@0.7:"
                            f"shadowx=4:"
                            f"shadowy=4:"
                            f"box=1:"
                            f"boxcolor=black@0.65:"
                            f"boxborderw=20:"
                            f"x=(w-text_w)/2:"
                            f"y={fixed_y_pos}:"
                            f"enable='between(t,{current_start:.3f},{line_end:.3f})'"
                        )
                        filters.append(filter_str)

                        current_start = line_end

            if not filters:
                return ""

            return ",".join(filters)

        except Exception as e:
            logger.error(f"创建字幕滤镜失败: {e}", exc_info=True)
            return ""


# 创建全局实例
subtitle_service = SubtitleService()

__all__ = [
    "SubtitleService",
    "subtitle_service",
]
