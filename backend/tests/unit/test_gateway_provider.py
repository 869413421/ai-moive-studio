import base64
import io
import wave
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image

from src.services.provider.gateway import GatewayProvider, video_references
from src.services.provider.factory import ProviderFactory
from src.services.provider.registry import load_config
from src.services.provider.results import video_result


def configured(name):
    return next(m for m in load_config()['models'] if m['id'] == name)


def provider(monkeypatch, name):
    instance = GatewayProvider('fake', base_url='https://gateway.example/v1')
    monkeypatch.setattr(instance, '_model', AsyncMock(return_value=configured(name)))
    return instance


def png():
    out = io.BytesIO()
    Image.new('RGB', (2, 2)).save(out, format='PNG')
    return out.getvalue()


@pytest.mark.asyncio
async def test_gemini_image_keeps_ratio_and_references(monkeypatch):
    p = provider(monkeypatch, 'gemini-3.1-flash-image-preview')
    p._reference = AsyncMock(return_value=(png(), 'image/png'))
    p._json = AsyncMock(return_value={'candidates': [{'content': {'parts': [
        {'thoughtSignature': 'not-an-image'}, {'inlineData': {'mimeType': 'image/png', 'data': base64.b64encode(png()).decode()}}
    ]}}]})
    result = await p.generate_image('draw', 'model', aspect_ratio='9:16', reference_images=['uploads/ref.png'])
    args = p._json.call_args
    assert args.args[1] == '/v1beta/models/gemini-3.1-flash-image-preview:generateContent'
    assert args.kwargs['json']['generationConfig']['imageConfig']['aspectRatio'] == '9:16'
    assert len(args.kwargs['json']['contents'][0]['parts']) == 2
    assert result.data[0].mime == 'image/png'
    with pytest.raises(ValueError):
        await p.generate_image('draw', 'model', reference_images=['ref'] * 6)


@pytest.mark.asyncio
@pytest.mark.parametrize('name,path', [('gpt-image-2', '/images/generations'), ('doubao-seedream-5-0-pro-260628','/api/v3/images/generations'), ('qwen-image-max','/images/generations')])
async def test_image_profile_uses_configured_route(monkeypatch, name, path):
    p = provider(monkeypatch, name)
    p._json = AsyncMock(return_value={'data': [{'url': 'https://media.example/image.png'}]})
    assert (await p.generate_image('draw', name)).data[0].url.endswith('.png')
    assert p._json.call_args.args[1] == path
    assert p._json.call_args.kwargs['json']['model'] == name


@pytest.mark.asyncio
async def test_gpt_edit_multipart_preserves_all_images(monkeypatch):
    p = provider(monkeypatch, 'gpt-image-2')
    p._reference = AsyncMock(return_value=(png(), 'image/png'))
    p._json = AsyncMock(return_value={'data': [{'b64_json': base64.b64encode(png()).decode()}]})
    await p.generate_image('edit', 'gpt-image-2', reference_images=['one','two'])
    args = p._json.call_args
    assert args.args[1] == '/images/edits'
    assert len(args.kwargs['files']) == 2
    assert all(part[0] == 'image[]' for part in args.kwargs['files'])
    assert 'json' not in args.kwargs


@pytest.mark.asyncio
async def test_responses_maps_structured_output_and_complete_text(monkeypatch):
    p = provider(monkeypatch, 'gpt-5.6-sol')
    p.client.responses.create = AsyncMock(return_value=NS(status='completed', output_text='{"ok":true}', usage=None))
    result = await p.completions('gpt-5.6-sol', [{'role':'user','content':'json'}], response_format={'type':'json_object'}, max_tokens=80)
    assert result.choices[0].message.content == '{"ok":true}'
    args = p.client.responses.create.call_args.kwargs
    assert args['text'] == {'format':{'type':'json_object'}} and args['max_output_tokens'] == 80
    assert 'messages' not in args


class Stream:
    def __init__(self, types):
        self.types = types
        self.close = AsyncMock()
    def __aiter__(self):
        async def items():
            for t in self.types:
                yield NS(type=t, delta='hello')
        return items()


@pytest.mark.asyncio
async def test_response_stream_requires_terminal_success(monkeypatch):
    p = provider(monkeypatch, 'gpt-5.6-sol')
    stream = Stream(['response.output_text.delta','response.completed'])
    assert [v async for v in p._response_stream(stream)] == [{'choices':[{'delta':{'content':'hello'}}]}]
    stream.close.assert_awaited_once()
    stream = Stream(['response.output_text.delta'])
    with pytest.raises(ValueError, match='中断'):
        [v async for v in p._response_stream(stream)]
    stream.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_gemini_audio_pcm_is_wrapped_as_wav(monkeypatch):
    p = provider(monkeypatch, 'gemini-3.1-flash-tts-preview')
    p._json = AsyncMock(return_value={'candidates':[{'content':{'parts':[{'inlineData':{'mimeType':'audio/L16;codec=pcm;rate=24000','data':base64.b64encode(b'\x00\x01'*20).decode()}}]}}]})
    result = await p.generate_audio('hello')
    assert result.extension == 'wav' and result.mime == 'audio/wav'
    with wave.open(io.BytesIO(result.content)) as wav:
        assert wav.getframerate() == 24000 and wav.getnframes() == 20
    with pytest.raises(ValueError, match='音色'):
        await p.generate_audio('hello', voice='alloy')


@pytest.mark.asyncio
async def test_minimax_audio_decodes_hex_and_business_errors(monkeypatch):
    p = provider(monkeypatch, 'speech-2.8-hd')
    p._json = AsyncMock(return_value={'data':{'audio':b'ID3audio'.hex()}})
    assert (await p.generate_audio('hello')).content == b'ID3audio'
    assert p._json.call_args.args[1] == '/minimax/v1/t2a_v2'
    p = GatewayProvider('fake')
    p._request = AsyncMock(return_value=httpx.Response(200,json={'base_resp':{'status_code':1001,'status_msg':'error'}}))
    with pytest.raises(ValueError):
        await p._json('POST','/minimax/v1/t2a_v2')


@pytest.mark.asyncio
async def test_video_submit_query_and_failed_status(monkeypatch):
    p = provider(monkeypatch, 'MiniMax-H3')
    p._json = AsyncMock(return_value={'task_id':'task-1', 'status':'queued'})
    response = await p.create_video('move', model='MiniMax-H3', images=['https://media.example/first.png','https://media.example/last.png'], frames=True)
    assert response['provider_context']['profile'] == 'gateway_video'
    args = p._json.call_args
    assert args.args[1] == '/v1/video/generations'
    assert args.kwargs['json']['metadata']['resolution'] == '768P'
    assert args.kwargs['json']['metadata']['last_frame'].endswith('last.png')
    p._json = AsyncMock(return_value={'id':'task-1', 'status':'completed','metadata':{'url':'https://media.example/result.mp4'}})
    assert (await p.get_task_status('task-1'))['video_url'].endswith('result.mp4')
    p._request = AsyncMock(return_value=httpx.Response(200,json={'status':'failed','error':{'message':'rejected'}}))
    # Exercise the real JSON adapter: task error payloads must reach the status normalizer.
    data = await GatewayProvider._json(p,'GET','/v1/videos/task-1',task_status=True)
    assert video_result(data,'gateway_video')['status'] == 'failed'


@pytest.mark.parametrize('profile,payload', [
    ('gateway_video',{'status':'succeeded','metadata':{'url':'https://media.example/a.mp4'}}),
    ('grok_video',{'status':'done','video':{'url':'https://media.example/a.mp4'}}),
    ('wan_video',{'status':'completed','output':{'video_url':'https://media.example/a.mp4'}}),
])
def test_video_response_profiles(profile,payload):
    assert video_result(payload,profile)['video_url'].endswith('a.mp4')
    with pytest.raises(ValueError):
        video_result({'status':'mystery'},profile)


def test_resume_does_not_send_key_to_changed_host():
    key = NS(status='active',provider='custom',base_url='https://new.example/v1',get_api_key=lambda:'secret')
    context = {'version':1,'provider':'custom','base_url':'https://old.example/v1','profile':'gateway_video'}
    with pytest.raises(ValueError, match='变更'):
        ProviderFactory.resume_video(key,context)
    key.status = 'inactive'
    with pytest.raises(ValueError, match='未启用'):
        ProviderFactory.from_key(key)


@pytest.mark.asyncio
async def test_http_transport_scopes_credentials_and_rejects_redirects(monkeypatch):
    calls = []
    async def transport(request):
        calls.append(request)
        return httpx.Response(302, headers={'location':'https://other.example/collect'})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs))
    p = GatewayProvider('fake', base_url='https://gateway.example/v1')
    with pytest.raises(ValueError, match='302'):
        await p._request('POST','/audio/speech',json={'input':'hi'})
    assert len(calls) == 1
    assert calls[0].url.host == 'gateway.example'
    assert calls[0].headers['authorization'] == 'Bearer fake'


@pytest.mark.asyncio
async def test_failed_reference_is_not_silently_dropped(monkeypatch):
    p = provider(monkeypatch, 'gemini-3.1-flash-image-preview')
    p._reference = AsyncMock(side_effect=ValueError('bad reference'))
    p._json = AsyncMock()
    with pytest.raises(ValueError, match='bad reference'):
        await p.generate_image('edit', reference_images=['bad'])
    p._json.assert_not_awaited()


@pytest.mark.asyncio
async def test_transition_preserves_submission_context(monkeypatch):
    from src.services.transition_service import TransitionService
    service = TransitionService(AsyncMock())
    service._load_keyframe_references = AsyncMock(return_value=['https://media.example/a.png','https://media.example/b.png'])
    snapshot = {'version':1,'model':'MiniMax-H3','profile':'gateway_video','base_url':'https://gateway.example/v1','provider':'custom'}
    p = NS(create_video=AsyncMock(return_value={'id':'task-1','provider_context':snapshot}))
    transition = NS(id='transition',from_shot_id='a',to_shot_id='b',video_prompt='move')
    result = await service._generate_single_transition_video(transition,'key','user','MiniMax-H3',p)
    assert result['success'] and transition.provider_context_json == snapshot
    assert p.create_video.call_args.kwargs['frames'] is True


def test_migration_030_preserves_history_and_is_reversible():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[2] / 'migrations/versions/030_add_video_provider_context.py'
    spec = importlib.util.spec_from_file_location('migration030',path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with create_engine('sqlite://').begin() as conn:
        conn.execute(text('CREATE TABLE movie_shot_transitions (id TEXT PRIMARY KEY, video_task_id TEXT)'))
        conn.execute(text("INSERT INTO movie_shot_transitions VALUES ('old', 'old-task')"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
            row = conn.execute(text('SELECT video_task_id, provider_context_json FROM movie_shot_transitions')).one()
            assert tuple(row) == ('old-task',None)
            module.downgrade()
        assert [c['name'] for c in inspect(conn).get_columns('movie_shot_transitions')] == ['id','video_task_id']


def test_expired_video_is_terminal_and_seedream_pro_sizes_follow_document_enum():
    assert video_result({'status':'expired'},'gateway_video')['status'] == 'failed'
    allowed = {'2048x2048','2368x1776','1776x2368','2816x1584','1584x2816','2496x1664','1664x2496','3136x1344'}
    assert set(configured('doubao-seedream-5-0-pro-260628')['size_by_ratio'].values()) <= allowed
    assert configured('qwen-image-max')['max_references'] == 3


@pytest.mark.asyncio
async def test_completed_video_without_asset_stays_pollable(monkeypatch):
    from src.services.canvas import CanvasGenerationService, CanvasService
    import uuid
    document_id, item_id, generation_id = (str(uuid.uuid4()) for _ in range(3))
    generation = NS(id=generation_id,status='processing',request_payload_json={},result_payload_json={'provider_task_id':'task'},error_message=None)
    item = NS(id=item_id, document_id=document_id, item_type='video')
    p = NS(get_task_status=AsyncMock(return_value={'status':'completed'}),get_video_content=AsyncMock(return_value={'status':'completed'}))
    monkeypatch.setattr(CanvasService,'get_item_generation',AsyncMock(return_value=(item,generation)))
    update = AsyncMock()
    monkeypatch.setattr(CanvasService,'update_generation',update)
    monkeypatch.setattr(ProviderFactory,'resume_video',lambda *_:p)
    service = CanvasGenerationService(AsyncMock())
    service._resolve_api_key = AsyncMock()
    result = await service.get_video_task_status(document_id,item_id,generation_id,'user')
    assert result['status'] == 'processing'
    update.assert_not_awaited()


@pytest.mark.asyncio
async def test_catalog_parallel_fetch_does_not_query_shared_db_session(monkeypatch):
    from src.api.v1.canvas import get_canvas_model_catalog
    from src.services.api_key import APIKeyService
    from src.services.provider import catalog
    keys = [NS(id='one',provider='custom',base_url=None,get_api_key=lambda:'one'), NS(id='two',provider='custom',base_url=None,get_api_key=lambda:'two')]
    monkeypatch.setattr(APIKeyService,'get_user_api_keys',AsyncMock(return_value=(keys,2)))
    forbidden = AsyncMock(side_effect=AssertionError('shared session queried concurrently'))
    monkeypatch.setattr(APIKeyService,'get_api_key_by_id',forbidden)
    monkeypatch.setattr(catalog,'get_catalog',AsyncMock(return_value={'models':[]}))
    result = await get_canvas_model_catalog(NS(id='owner'),AsyncMock())
    assert set(result['connections']) == {'one','two'}
    forbidden.assert_not_awaited()


@pytest.mark.asyncio
async def test_background_poller_includes_upstream_queued_tasks(monkeypatch):
    from src.tasks.canvas import sync_canvas_video_status, poll_canvas_video_status
    from sqlalchemy import create_engine, text
    from src.models.canvas import CanvasItemGeneration
    # SQL compilation proves the actual dispatcher query includes both accepted states.
    db = AsyncMock()
    db.execute.return_value = NS(all=lambda:[('queued-id',{'provider_task_id':'upstream-id'})])
    delay = NS(calls=[])
    monkeypatch.setattr(poll_canvas_video_status,'delay',lambda value:delay.calls.append(value))
    await sync_canvas_video_status.run.__wrapped__(db,None)
    query = db.execute.call_args.args[0]
    sql = str(query.compile(compile_kwargs={'literal_binds':True}))
    assert "IN ('pending', 'processing')" in sql
    assert delay.calls == ['queued-id']
