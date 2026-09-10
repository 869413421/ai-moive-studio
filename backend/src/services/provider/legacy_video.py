"""Read-only recovery for tasks submitted before protocol snapshots existed."""
from urllib.parse import quote
import httpx


class LegacyVideoQuery:
    def __init__(self, api_key, base_url=None):
        self.api_key = api_key
        self.base_url = (base_url or 'https://api.vectorengine.ai/v1').rstrip('/')

    async def _get(self, path):
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.get(self.base_url + path, headers={'Authorization': f'Bearer {self.api_key}'})
            response.raise_for_status()
            return response.json()

    async def get_task_status(self, task_id):
        return await self._get('/videos/' + quote(task_id, safe=''))

    async def get_video_content(self, task_id):
        return await self._get('/videos/' + quote(task_id, safe='') + '/content')
