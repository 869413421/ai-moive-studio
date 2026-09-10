import copy
import json
from unittest.mock import AsyncMock

import pytest

from src.services.provider import catalog, registry


@pytest.fixture(autouse=True)
def clean_cache():
    catalog._public_cache.clear()
    catalog._permission_cache.clear()
    registry._last_config.clear()


def test_connection_defaults_and_exact_migration():
    assert registry.connection('custom', None)['base_url'] == registry.DEFAULT_BASE_URL
    assert registry.connection('custom', 'https://api.aiconapi.me/v1')['base_url'] == registry.DEFAULT_BASE_URL
    assert registry.connection('custom', 'https://own.example/proxy/v1')['root_url'] == 'https://own.example/proxy'
    assert registry.connection('custom', 'https://own.example')['source'] == 'compatible'
    for value in ['https://user:secret@example.com', 'https://example.com?key=secret', 'file:///tmp/a']:
        with pytest.raises(ValueError):
            registry.connection('custom', value)


def test_config_reload_last_good_and_cap():
    config = registry.load_config()
    config['models'] += [dict(id=f'extra-{i}', profile='chat', enabled=True) for i in range(16)]
    with pytest.raises(ValueError, match='15'):
        registry.validate_config(config)


def test_reload_and_release_order(tmp_path, monkeypatch):
    path = tmp_path / 'models.json'
    monkeypatch.setenv('MODEL_CATALOG_CONFIG', str(path))
    config = {'version': 1, 'models': [
        dict(id='unknown', profile='chat', enabled=True),
        dict(id='older', profile='chat', enabled=True, released_at='2026-01-01', release_source='https://example.com/older'),
        dict(id='newer', profile='chat', enabled=True, released_at='2026-08-01', release_source='https://example.com/newer'),
    ]}
    path.write_text(json.dumps(config))
    assert [m['id'] for m in registry.selected_models('aicon')] == ['newer', 'older', 'unknown']
    path.write_text('{invalid')
    assert len(registry.load_config()['models']) == 3
    config['models'][0]['enabled'] = False
    path.write_text(json.dumps(config))
    assert registry.load_config()['models'][0]['enabled'] is False


@pytest.mark.asyncio
async def test_catalog_intersects_key_permissions_and_config(monkeypatch):
    async def get(url, token=None):
        if token:
            return {'data': [{'id': name} for name in (['gemini-3.8-flash', 'unknown'] if token == 'key-a' else ['gpt-4o-mini-tts'])]}
        return {'success': True, 'data': [{'model_name': n} for n in ['gemini-3.8-flash', 'gpt-4o-mini-tts', 'unknown']]}
    monkeypatch.setattr(catalog, '_get_json', get)
    a = await catalog.get_catalog('custom', None, 'key-a')
    b = await catalog.get_catalog('custom', None, 'key-b')
    assert [m['id'] for m in a['models']] == ['gemini-3.8-flash']
    assert [m['id'] for m in b['models']] == ['gpt-4o-mini-tts']
    with pytest.raises(ValueError):
        await catalog.resolve_model(registry.connection('custom'), 'key-b', 'gemini-3.8-flash', 'text')
    hidden = await catalog.get_catalog('custom', None, 'key-a', include_hidden=True)
    assert next(m for m in hidden['models'] if m['id'] == 'unknown')['status'] == 'needs_configuration'


@pytest.mark.asyncio
async def test_permission_failure_never_uses_old_permissions(monkeypatch):
    conn = registry.connection('custom')
    monkeypatch.setattr(catalog, '_get_json', AsyncMock(return_value={'data': [{'id': 'allowed'}]}))
    assert 'allowed' in await catalog.permitted_models(conn, 'secret')
    monkeypatch.setattr(catalog, '_get_json', AsyncMock(side_effect=ValueError('revoked')))
    with pytest.raises(ValueError):
        await catalog.permitted_models(conn, 'secret', refresh=True)
    assert not catalog._permission_cache


@pytest.mark.asyncio
async def test_public_outage_uses_only_last_successful_catalog(monkeypatch):
    conn = registry.connection('custom')
    monkeypatch.setattr(catalog, '_get_json', AsyncMock(return_value={'success': True, 'data': [{'model_name': 'known'}]}))
    await catalog.public_catalog(conn)
    monkeypatch.setattr(catalog, '_get_json', AsyncMock(side_effect=ValueError('outage')))
    models, stale = await catalog.public_catalog(conn, refresh=True)
    assert stale and 'known' in models
