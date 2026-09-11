"""Validated, reloadable model selections. Remote metadata never supplies executable routes."""
import copy
import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

DEFAULT_BASE_URL = 'https://api.aicon-studio.com/v1'
PROVIDERS = {
    'custom': ('自定义 / AICON', DEFAULT_BASE_URL),
    'siliconflow': ('硅基流动', 'https://api.siliconflow.cn/v1'),
    'openai': ('OpenAI', 'https://api.openai.com/v1'),
    'deepseek': ('DeepSeek', 'https://api.deepseek.com/v1'),
    'volcengine': ('火山引擎', 'https://ark.cn-beijing.volces.com/api/v3'),
    'vectorengine': ('Vector Engine', 'https://api.vectorengine.ai/v1'),
    'atlascloud': ('Atlas Cloud', 'https://api.atlascloud.ai/v1'),
}
PROFILE_TYPES = {
    'chat': 'text', 'responses': 'text',
    'gemini_image': 'image', 'images': 'image', 'seedream': 'image', 'seedream_pro': 'image',
    'speech': 'audio', 'gemini_speech': 'audio', 'minimax_speech': 'audio',
    'gateway_video': 'video', 'grok_video': 'video', 'wan_video': 'video',
}
_last_config = {}


def connection(provider, base_url=None):
    provider = provider.lower()
    if provider not in PROVIDERS:
        raise ValueError('未支持的供应商')
    value = (base_url or PROVIDERS[provider][1]).strip().rstrip('/')
    parts = urlsplit(value)
    if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Base URL 必须为不含凭据、查询参数的 HTTP(S) 地址')
    # Exact old AICON hostname migration, never rewrite arbitrary custom gateways.
    if parts.hostname == 'api.aiconapi.me':
        parts = parts._replace(scheme='https', netloc='api.aicon-studio.com')
    root_path = parts.path.rstrip('/')
    if root_path.endswith('/v1'):
        root_path = root_path[:-3]
    root = urlunsplit(parts._replace(path=root_path))
    base = urlunsplit(parts)
    if not parts.path or parts.path == '/':
        base = root + '/v1'
    source = 'aicon' if parts.hostname == 'api.aicon-studio.com' and not root_path else provider
    if source == 'custom':
        source = 'compatible'
    return {'provider': provider, 'source': source, 'base_url': base, 'root_url': root}


def validate_config(data):
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('models'), list):
        raise ValueError('模型配置必须包含 version=1 和 models 数组')
    seen, counts = set(), {}
    for model in data['models']:
        if not isinstance(model, dict):
            raise ValueError('模型配置项必须是对象')
        name, profile = model.get('id'), model.get('profile')
        if not isinstance(name, str) or not name.strip() or profile not in PROFILE_TYPES:
            raise ValueError('模型 ID 或协议配置无效')
        sources = model.get('sources', ['aicon'])
        if not isinstance(sources, list) or not sources or not all(isinstance(x, str) for x in sources):
            raise ValueError('模型 sources 无效')
        for source in sources:
            key = (source, name)
            if key in seen:
                raise ValueError(f'重复模型配置: {name}')
            seen.add(key)
            if model.get('enabled', False):
                kind = PROFILE_TYPES[profile]
                counts[(source, kind)] = counts.get((source, kind), 0) + 1
        if model.get('released_at'):
            date.fromisoformat(model['released_at'])
            if not model.get('release_source'):
                raise ValueError('发布日期必须附来源')
        if type(model.get('enabled', False)) is not bool:
            raise ValueError('模型 enabled 必须是布尔值')
        if type(model.get('max_references', 0)) is not int or model.get('max_references', 0) < 0:
            raise ValueError('参考图上限无效')
        kind = PROFILE_TYPES[profile]
        if kind in {'image', 'video'}:
            ratios = model.get('aspect_ratios')
            if not isinstance(ratios, list) or not ratios or not all(isinstance(r, str) and r for r in ratios):
                raise ValueError('图片和视频模型必须配置可用比例')
        if kind == 'image' and profile != 'gemini_image':
            sizes = model.get('size_by_ratio', {})
            if not isinstance(sizes, dict) or any(not isinstance(sizes.get(r), str) for r in ratios):
                raise ValueError('图片比例缺少对应尺寸')
        if kind == 'video':
            durations, resolutions = model.get('durations'), model.get('resolutions')
            if not isinstance(durations, list) or not durations or not all(type(d) is int and d > 0 for d in durations):
                raise ValueError('视频时长配置无效')
            if not isinstance(resolutions, list) or not resolutions or not all(isinstance(r, str) and r for r in resolutions):
                raise ValueError('视频分辨率配置无效')
            if model.get('duration') not in durations or model.get('resolution') not in resolutions:
                raise ValueError('视频默认参数超出能力范围')
        if kind == 'audio':
            voices = model.get('voices')
            if not isinstance(voices, list) or not voices or not all(isinstance(v, str) and v for v in voices) or model.get('default_voice') not in voices:
                raise ValueError('音色配置无效')
    if any(count > 15 for count in counts.values()):
        raise ValueError('每个连接每类最多启用 15 个模型')
    if not isinstance(data.get('defaults', {}), dict):
        raise ValueError('defaults 必须是对象')
    for source, defaults in data.get('defaults', {}).items():
        if not isinstance(defaults, dict):
            raise ValueError('默认模型配置必须是对象')
        for kind, name in defaults.items():
            if not any(m['id'] == name and source in m.get('sources', ['aicon']) and m.get('enabled') and PROFILE_TYPES[m['profile']] == kind for m in data['models']):
                raise ValueError('默认模型必须是同用途的已启用模型')
    return data


def load_config():
    path = Path(os.environ.get('MODEL_CATALOG_CONFIG') or Path(__file__).with_name('models.json'))
    # Read on use: atomic file replacement works with bind-mounted configuration too.
    try:
        content = path.read_text(encoding='utf-8')
        if _last_config.get('path') == str(path) and _last_config.get('content') == content:
            return copy.deepcopy(_last_config['data'])
        data = validate_config(json.loads(content))
        _last_config.update(path=str(path), content=content, data=data)
        return copy.deepcopy(data)
    except (OSError, ValueError, TypeError, KeyError):
        if _last_config.get('path') == str(path):
            return copy.deepcopy(_last_config['data'])
        raise ValueError('模型配置无法读取或校验失败') from None


def selected_models(source):
    models = [m for m in load_config()['models'] if source in m.get('sources', ['aicon'])]
    # Unknown release dates follow verified dates. File order is stable for unknown dates.
    return sorted(models, key=lambda m: m.get('released_at') or '', reverse=True)
