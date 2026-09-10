"""One stable result contract for existing generation consumers."""
from dataclasses import dataclass
from types import SimpleNamespace


@dataclass
class ImageData:
    url: str | None = None
    b64_json: str | None = None
    mime: str = 'image/png'


@dataclass
class ImageResult:
    data: list[ImageData]


@dataclass
class AudioResult:
    content: bytes
    mime: str = 'audio/mpeg'
    extension: str = 'mp3'


def image_result(payload):
    entries = payload.get('data')
    if not isinstance(entries, list) or not entries:
        raise ValueError('图片接口未返回有效图片列表')
    result = []
    fmt = payload.get('output_format', 'png')
    for entry in entries:
        if not isinstance(entry, dict) or not (entry.get('url') or entry.get('b64_json')):
            raise ValueError('图片响应缺少 URL 或 base64')
        result.append(ImageData(entry.get('url'), entry.get('b64_json'), 'image/jpeg' if fmt in ('jpg','jpeg') else 'image/png'))
    if len(result) != 1:
        raise ValueError('当前单图操作收到多张结果，请检查模型配置')
    return ImageResult(result)


def completion_result(text, usage=None):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('文本接口未返回可用正文')
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=usage)


def video_result(payload, profile):
    if not isinstance(payload, dict):
        raise ValueError('视频响应结构无效')
    status = str(payload.get('status') or '').lower()
    states = {'queued':'pending','pending':'pending','submitted':'pending','running':'processing','processing':'processing',
              'completed':'completed','succeeded':'completed','success':'completed','done':'completed',
              'expired':'failed','failed':'failed','error':'failed','cancelled':'failed','canceled':'failed'}
    if status not in states:
        raise ValueError('视频接口返回未知状态')
    if profile == 'gateway_video':
        url = (payload.get('metadata') or {}).get('url')
    elif profile == 'grok_video':
        url = (payload.get('video') or {}).get('url')
    elif profile == 'wan_video':
        url = payload.get('video_url') or (payload.get('output') or {}).get('video_url')
    else:
        raise ValueError('未支持的视频响应协议')
    error = payload.get('error') or {}
    return {'id':payload.get('id') or payload.get('task_id') or payload.get('request_id'),
            'status':states[status], 'video_url':url, 'progress':payload.get('progress'),
            'error':error.get('message') if isinstance(error,dict) else str(error)}
