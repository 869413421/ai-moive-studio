"""Server-side discovery, credential-scoped availability, and curated model capabilities."""
import hashlib
import time

import httpx

from .registry import connection, load_config, selected_models, PROFILE_TYPES

_public_cache = {}
_permission_cache = {}


async def _get_json(url, token=None):
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        response = await client.get(url, headers=headers)
        if response.status_code in (401, 403):
            raise ValueError('模型目录认证失败，请检查密钥权限')
        response.raise_for_status()
        return response.json()


async def public_catalog(conn, refresh=False):
    if conn['source'] != 'aicon':
        return {}, False
    url = conn['root_url'] + '/api/pricing'
    cached = _public_cache.get(url)
    if cached and not refresh and time.monotonic() - cached[0] < 300:
        return cached[1], False
    try:
        data = await _get_json(url)
        if not isinstance(data, dict) or data.get('success') is not True or not isinstance(data.get('data'), list):
            raise ValueError('站点模型目录格式无效')
        models = {m['model_name']: m for m in data['data'] if isinstance(m, dict) and isinstance(m.get('model_name'), str)}
        if not models:
            raise ValueError('站点模型目录为空')
        _public_cache[url] = (time.monotonic(), models)
        return models, False
    except (httpx.HTTPError, ValueError, TypeError):
        if cached:
            return cached[1], True
        raise ValueError('站点模型目录暂不可用，请稍后刷新') from None


async def permitted_models(conn, token, refresh=False):
    url = conn['base_url'] + '/models'
    # No plaintext credentials in cache keys and no permissions shared between credentials.
    cache_key = hashlib.sha256((url + '\0' + token).encode()).hexdigest()
    cached = _permission_cache.get(cache_key)
    if cached and not refresh and time.monotonic() - cached[0] < 60:
        return cached[1]
    try:
        data = await _get_json(url, token)
        if not isinstance(data, dict) or not isinstance(data.get('data'), list) or not all(isinstance(m, dict) and isinstance(m.get('id'), str) for m in data['data']):
            raise ValueError('授权模型目录格式无效')
        models = {m['id']: m for m in data['data']}
        if len(_permission_cache) > 256:
            _permission_cache.clear()
        _permission_cache[cache_key] = (time.monotonic(), models)
        return models
    except (httpx.HTTPError, ValueError, TypeError):
        _permission_cache.pop(cache_key, None)
        raise ValueError('无法确认此密钥可用模型，请检查密钥或刷新目录') from None


async def get_catalog(provider, base_url, token, refresh=False, include_hidden=False):
    conn = connection(provider, base_url)
    available = await permitted_models(conn, token, refresh)
    public, stale = await public_catalog(conn, refresh)
    configured = {m['id']: m for m in selected_models(conn['source'])}
    results = []
    for name, config in configured.items():
        enabled = bool(config.get('enabled'))
        allowed = name in available and (conn['source'] != 'aicon' or name in public)
        if not include_hidden and not (enabled and allowed):
            continue
        info = public.get(name, {})
        results.append({**config, 'type': PROFILE_TYPES[config['profile']], 'name': name,
                        'description': info.get('description', ''), 'available': allowed,
                        'status': 'unavailable' if not allowed else 'enabled' if enabled else 'hidden'})
    if include_hidden:
        for name, info in {**available, **public}.items():
            if name not in configured:
                results.append({'id': name, 'name': name, 'enabled': False, 'available': name in available,
                                'status': 'needs_configuration', 'description': info.get('description', '')})
    return {'models': results, 'stale': stale, 'defaults': load_config().get('defaults', {}).get(conn['source'], {}),
            'base_url': conn['base_url']}


async def resolve_model(conn, token, model, kind):
    catalog = await get_catalog(conn['provider'], conn['base_url'], token)
    candidates = [entry for entry in catalog['models'] if entry['type'] == kind]
    if not model:
        default = catalog['defaults'].get(kind)
        model = default if any(entry['id'] == default for entry in candidates) else (candidates[0]['id'] if candidates else None)
    for entry in catalog['models']:
        if entry['id'] == model and entry['type'] == kind:
            return entry
    raise ValueError('所选模型已隐藏、用途不符或此密钥不可用，请重新选择模型')
