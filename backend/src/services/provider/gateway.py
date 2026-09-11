"""Protocol adapters behind the shared generation interface. No model-name guessing."""
import asyncio
import base64
import io
import wave
from urllib.parse import quote, urlsplit

import httpx
from openai import AsyncOpenAI

from .catalog import resolve_model
from .registry import connection
from .results import ImageData, ImageResult, AudioResult, image_result, completion_result, video_result


async def video_references(values):
    """URL-based video protocols need references reachable by the upstream worker."""
    result = []
    for value in values or []:
        if not isinstance(value, str) or not value:
            raise ValueError('视频参考图地址为空')
        if value.startswith('uploads/'):
            from datetime import timedelta
            from src.utils.storage import get_storage_client
            value = (await get_storage_client()).get_presigned_url(value, expires=timedelta(hours=24))
        parts = urlsplit(value)
        if parts.scheme not in {'https', 'http'} or not parts.hostname or parts.username or parts.password:
            raise ValueError('此视频协议需要可访问的图片 URL，请先上传参考图')
        result.append(value)
    return result


class ProviderHTTPError(ValueError):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f'供应接口请求失败（HTTP {status_code}）')


class GatewayProvider:
    def __init__(self, api_key, max_concurrency=5, base_url=None, provider='custom', context=None):
        self.connection = connection(provider, base_url)
        self.base_url = self.connection['base_url']
        self.api_key = api_key
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.client = AsyncOpenAI(api_key=api_key, base_url=self.base_url, max_retries=0, timeout=300)
        if context and context.get("profile") not in {"gateway_video", "grok_video", "wan_video"}:
            raise ValueError("不支持的视频任务协议")
        self.context = context

    async def _model(self, model, kind):
        return await resolve_model(self.connection, self.api_key, model, kind)

    async def _request(self, method, path, *, root=False, **kwargs):
        url = (self.connection['root_url'] if root else self.base_url) + path
        async with self.semaphore:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30 if method == 'GET' else 300, connect=20), follow_redirects=False) as client:
                response = await client.request(method, url, headers={'Authorization':f'Bearer {self.api_key}'}, **kwargs)
                if not 200 <= response.status_code < 300:
                    # Do not expose URLs containing credentials or raw upstream bodies in task errors.
                    raise ProviderHTTPError(response.status_code)
                return response

    async def _json(self, method, path, *, task_status=False, **kwargs):
        response = await self._request(method, path, **kwargs)
        try:
            data = response.json()
        except ValueError:
            raise ValueError('供应接口未返回 JSON') from None
        if not isinstance(data, dict) or (data.get('error') and not task_status) or (data.get('base_resp') or {}).get('status_code', 0) != 0:
            raise ValueError('供应接口返回生成错误')
        return data

    async def completions(self, model, messages, **kwargs):
        config = await self._model(model, 'text')
        stream = kwargs.pop('stream', False)
        if not config.get('temperature', True):
            kwargs.pop('temperature', None)
        if kwargs.get('response_format') and not config.get('supports_json'):
            raise ValueError('此模型未配置结构化输出能力')
        if config['profile'] == 'chat':
            async with self.semaphore:
                result = await self.client.chat.completions.create(model=config['id'], messages=messages, stream=stream, **kwargs)
            if stream:
                return result
            if not result.choices or result.choices[0].finish_reason not in {'stop', None}:
                raise ValueError('文本生成未完成或被拒绝')
            return completion_result(result.choices[0].message.content, result.usage)
        if config['profile'] != 'responses':
            raise ValueError('未支持的文本协议')
        fmt = kwargs.pop('response_format', None)
        if fmt:
            kwargs['text'] = {'format': fmt}
        if 'max_tokens' in kwargs:
            kwargs['max_output_tokens'] = kwargs.pop('max_tokens')
        async with self.semaphore:
            result = await self.client.responses.create(model=config['id'], input=messages, stream=stream, **kwargs)
        if stream:
            return self._response_stream(result)
        if result.status != 'completed':
            raise ValueError('文本生成未完成或被拒绝')
        return completion_result(result.output_text, result.usage)

    async def _response_stream(self, stream):
        completed = False
        try:
            async for event in stream:
                if event.type == 'response.output_text.delta':
                    yield {'choices':[{'delta':{'content':event.delta}}]}
                elif event.type == 'response.completed':
                    completed = True
                elif event.type in {'error','response.failed','response.incomplete'}:
                    raise ValueError('文本流生成失败或不完整')
            if not completed:
                raise ValueError('文本流意外中断')
        finally:
            await stream.close()

    async def _reference(self, value):
        if value.startswith('uploads/'):
            from src.utils.storage import get_storage_client
            raw = await (await get_storage_client()).download_file(value)
        elif value.startswith('data:'):
            try:
                raw = base64.b64decode(value.split(',',1)[1], validate=True)
            except (ValueError, IndexError):
                raise ValueError('参考图 base64 无效') from None
        else:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(value)
                response.raise_for_status()
                raw = response.content
        from PIL import Image
        try:
            with Image.open(io.BytesIO(raw)) as img:
                mime = Image.MIME.get(img.format)
                img.verify()
        except Exception:
            raise ValueError('参考图不是有效图片') from None
        if mime not in {'image/png','image/jpeg','image/webp','image/gif'}:
            raise ValueError('参考图格式不支持')
        return raw, mime

    def _references(self, config, values):
        if not isinstance(values, list) or len(values) > config.get('max_references',0):
            raise ValueError('参考图数量超出此模型限制')
        return values

    def _ratio(self, config, ratio):
        ratio = ratio or (config.get('aspect_ratios') or ['1:1'])[0]
        if ratio not in config.get('aspect_ratios', []):
            raise ValueError('此模型不支持所选比例，请重新选择')
        return ratio

    async def generate_image(self, prompt, model=None, **kwargs):
        config = await self._model(model, 'image')
        refs = self._references(config, kwargs.pop('reference_images', []) or [])
        ratio = self._ratio(config, kwargs.pop('aspect_ratio', None))
        image_size = kwargs.pop('image_size', config.get('image_size','1K'))
        if kwargs:
            raise ValueError('图片操作包含未支持的参数')
        if image_size not in config.get('image_sizes', [config.get('image_size', '1K')]):
            raise ValueError('此模型不支持所选图片尺寸')
        media = [await self._reference(value) for value in refs]
        profile = config['profile']
        if profile == 'gemini_image':
            parts = [{'text':prompt}] + [{'inlineData':{'mimeType':mime,'data':base64.b64encode(raw).decode()}} for raw,mime in media]
            payload = {'contents':[{'role':'user','parts':parts}],
                       'generationConfig':{'responseModalities':['IMAGE'],'imageConfig':{'aspectRatio':ratio,'imageSize':image_size}}}
            result = await self._json('POST',f'/v1beta/models/{quote(config["id"],safe="")}:generateContent',root=True,json=payload)
            images = []
            for candidate in result.get('candidates',[]):
                for part in candidate.get('content',{}).get('parts',[]):
                    inline = part.get('inlineData') or part.get('inline_data') or {}
                    mime = inline.get('mimeType') or inline.get('mime_type') or ''
                    if mime.startswith('image/') and inline.get('data'):
                        images.append(ImageData(b64_json=inline['data'],mime=mime))
            if len(images) != 1:
                raise ValueError('图片接口未返回单张有效图像')
            return ImageResult(images)
        payload = {'model':config['id'],'prompt':prompt,'n':1,'size':config['size_by_ratio'][ratio]}
        if profile == 'images' and media:
            files = [('image[]',('reference.'+mime.split('/')[-1],raw,mime)) for raw,mime in media]
            result = await self._json('POST','/images/edits',data={k:str(v) for k,v in payload.items()},files=files)
        else:
            if media:
                payload['image'] = [f'data:{mime};base64,{base64.b64encode(raw).decode()}' for raw,mime in media]
            path = '/api/v3/images/generations' if profile == 'seedream_pro' else '/images/generations'
            result = await self._json('POST',path,root=profile=='seedream_pro',json=payload)
        return image_result(result)

    async def generate_audio(self, input_text, voice=None, model=None, **kwargs):
        config = await self._model(model, 'audio')
        voice = voice or config['default_voice']
        if voice not in config.get('voices',[]):
            raise ValueError('此模型不支持所选音色')
        if kwargs:
            raise ValueError('语音操作包含未支持的参数')
        profile = config['profile']
        if profile == 'speech':
            response = await self._request('POST','/audio/speech',json={'model':config['id'],'input':input_text,'voice':voice,'response_format':'mp3'})
            if not response.content.startswith((b'ID3', b'\xff')):
                raise ValueError('语音接口未返回音频')
            return AudioResult(response.content)
        if profile == 'minimax_speech':
            data = await self._json('POST','/minimax/v1/t2a_v2',root=True,json={'model':config['id'],'text':input_text,'stream':False,'output_format':'hex','voice_setting':{'voice_id':voice},'audio_setting':{'format':'mp3'}})
            try:
                content = bytes.fromhex(data['data']['audio'])
            except (KeyError,TypeError,ValueError):
                raise ValueError('语音接口未返回有效音频编码') from None
            if not content:
                raise ValueError('语音结果为空')
            return AudioResult(content)
        data = await self._json('POST',f'/v1beta/models/{quote(config["id"],safe="")}:generateContent',root=True,json={
            'contents':[{'parts':[{'text':input_text}]}], 'generationConfig':{'responseModalities':['AUDIO'],'speechConfig':{'voiceConfig':{'prebuiltVoiceConfig':{'voiceName':voice}}}}})
        for candidate in data.get('candidates',[]):
            for part in candidate.get('content',{}).get('parts',[]):
                inline = part.get('inlineData') or {}
                if inline.get('mimeType') == 'audio/L16;codec=pcm;rate=24000':
                    pcm = base64.b64decode(inline['data'],validate=True)
                    output = io.BytesIO()
                    with wave.open(output,'wb') as wav:
                        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000); wav.writeframes(pcm)
                    return AudioResult(output.getvalue(),'audio/wav','wav')
        raise ValueError('语音响应编码不受支持')

    async def create_video(self, prompt, images=None, model=None, **kwargs):
        config = await self._model(model, 'video')
        refs = self._references(config, images or [])
        ratio = self._ratio(config, kwargs.pop('aspect_ratio', None))
        duration = kwargs.pop('duration', config['duration'])
        resolution = kwargs.pop('resolution',config['resolution'])
        frames = kwargs.pop('frames',False)
        if duration not in config['durations'] or resolution not in config['resolutions']:
            raise ValueError('此模型不支持所选时长或分辨率')
        if frames and (not config.get('supports_frames') or len(refs)!=2):
            raise ValueError('首尾帧操作需要支持该能力的模型和两张图片')
        if kwargs:
            raise ValueError('视频操作包含未支持的参数')
        refs = await video_references(refs)
        profile = config['profile']
        if profile == 'gateway_video':
            path = '/v1/video/generations'
            metadata = {'ratio':ratio,'resolution':resolution}
            payload = {'model':config['id'],'prompt':prompt,'duration':duration,'metadata':metadata}
            if frames:
                metadata.update(first_frame=refs[0],last_frame=refs[1])
            elif refs:
                payload['images'] = refs
        elif profile == 'grok_video':
            path = '/v1/videos/generations'
            payload = {'model':config['id'],'prompt':prompt,'seconds':str(duration),'resolution':resolution,'aspect_ratio':ratio}
            if refs:
                payload['reference_images'] = [{'url':ref} for ref in refs]
        elif profile == 'wan_video':
            path = '/api/v1/services/aigc/video-generation/video-synthesis'
            payload = {'model':config['id'],'input':{'prompt':prompt},'parameters':{'duration':duration,'resolution':resolution,'ratio':ratio}}
            payload['input']['media'] = [{'type':('first_frame' if i==0 else 'last_frame') if frames else 'reference_image','url':ref} for i,ref in enumerate(refs)]
        else:
            raise ValueError('未支持的视频协议')
        data = await self._json('POST',path,root=True,json=payload)
        task_id = data.get('id') or data.get('task_id') or data.get('request_id')
        if not isinstance(task_id,str) or not task_id:
            raise ValueError('视频提交未返回任务 ID，请核实提交结果后再操作')
        self.context = {'version':1,'provider':self.connection['provider'],'base_url':self.base_url,'model':config['id'],'profile':profile}
        return {'id':task_id,'status':'pending','provider_context':self.context}

    async def get_task_status(self, task_id):
        if not self.context:
            raise ValueError('视频任务缺少执行协议，请检查历史任务')
        profile = self.context['profile']
        path = f'/api/v1/tasks/{quote(task_id,safe="")}' if profile=='wan_video' else f'/v1/videos/{quote(task_id,safe="")}'
        return video_result(await self._json('GET',path,root=True,task_status=True),profile)

    async def get_video_content(self, task_id):
        return await self.get_task_status(task_id)
