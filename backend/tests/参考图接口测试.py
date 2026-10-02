"""真实 ASGI 路由 + HTTP multipart 编码；模拟上游，验证原图确实随修改请求发送。"""
import asyncio
import base64
from email.parser import BytesParser
from email.policy import default
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'Lib/site-packages'), str(ROOT / 'backend')]
import httpx
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.routes_image import router
from app.core import image_service as service


def picture(color='red', format='PNG'):
    output = io.BytesIO()
    Image.new('RGB', (64,64), color).save(output, format)
    return output.getvalue()


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ylb-reference-')
        self.directory = Path(self.temp.name)
        self.original = picture()
        self.result_bytes = picture('blue')
        (self.directory / 'original.png').write_bytes(self.original)
        self.setting = dict(provider_id='custom', provider_name='测试服务', key='test-only',
                            configured=True, protocol='openai_images', model='gpt-image-1',
                            base_url='https://gateway.invalid/prefix/v1/images/generations?tenant=test')
        self.requests = []
        self.status = 200
        def upstream(request):
            self.requests.append(request)
            return httpx.Response(self.status, json={'data':[{'b64_json':base64.b64encode(self.result_bytes).decode()}]}
                                  if self.status == 200 else {'error':'unsupported edit'})
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        self.patches = [patch.object(service, 'IMAGE_DIR', self.directory),
                        patch.object(service, 'HISTORY_FILE', self.directory / 'history.json'),
                        patch.object(service, '_setting', return_value=self.setting),
                        patch.object(service, 'get_client', return_value=self.http)]
        for item in self.patches: item.start()
        app = FastAPI(); app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        asyncio.run(self.http.aclose())
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()

    def generate(self, **payload):
        return self.client.post('/api/image/generations', json={'prompt':'只把背景改成蓝色，保留主体', **payload})

    def multipart(self):
        request = self.requests[-1]
        mime = BytesParser(policy=default).parsebytes(
            ('Content-Type: ' + request.headers['content-type'] + '\r\n\r\n').encode() + request.content)
        return {part.get_param('name', header='content-disposition'):part for part in mime.iter_parts()}

    def test_uploaded_image_reaches_edits_as_real_file(self):
        response = self.generate(reference_image='data:image/png;base64,' + base64.b64encode(self.original).decode())
        self.assertEqual(response.status_code, 200, response.text)
        request = self.requests[0]
        self.assertEqual(str(request.url), 'https://gateway.invalid/prefix/v1/images/edits?tenant=test')
        fields = self.multipart()
        self.assertEqual(fields['image'].get_payload(decode=True), self.original)
        self.assertEqual(fields['image'].get_content_type(), 'image/png')
        self.assertEqual(fields['model'].get_content(), 'gpt-image-1')
        self.assertEqual(response.json()['operation'], 'edit')

    def test_modify_history_then_modify_result_preserves_original(self):
        first = self.generate(reference_file='original.png').json()['images'][0]['file']
        second = self.generate(reference_file=first).json()['images'][0]['file']
        self.assertNotEqual(first, second)
        self.assertEqual(self.multipart()['image'].get_payload(decode=True), self.result_bytes)
        self.assertEqual((self.directory / 'original.png').read_bytes(), self.original)
        history = self.client.get('/api/image/history').json()['items']
        self.assertEqual(history[0]['reference_file'], first)
        self.assertEqual(history[1]['reference_file'], 'original.png')
        self.assertTrue(all(item['exists'] for item in history))

    def test_remove_reference_restores_text_generation(self):
        response = self.generate()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.requests[0].url.path, '/prefix/v1/images/generations')
        self.assertNotIn('image', json.loads(self.requests[0].content))
        self.assertEqual(response.json()['operation'], 'generate')

    def test_seedream_sends_image_on_generations(self):
        self.setting.update(provider_id='doubao', model='doubao-seedream-4-0')
        response = self.generate(reference_file='original.png')
        self.assertEqual(response.status_code, 200)
        payload = json.loads(self.requests[0].content)
        self.assertEqual(base64.b64decode(payload['image'].split(',')[1]), self.original)
        self.assertTrue(self.requests[0].url.path.endswith('/images/generations'))

    def test_explicit_edit_url_does_not_duplicate_endpoint(self):
        self.setting['base_url'] = 'https://gateway.invalid/v1/images/edits/'
        self.assertEqual(self.generate(reference_file='original.png').status_code, 200)
        self.assertEqual(self.requests[0].url.path, '/v1/images/edits')

    def test_jpeg_and_webp_are_forwarded_with_correct_mime(self):
        for format, mime in [('JPEG','image/jpeg'), ('WEBP','image/webp')]:
            raw = picture(format=format)
            response = self.generate(reference_image=base64.b64encode(raw).decode())
            self.assertEqual(response.status_code, 200)
            image = self.multipart()['image']
            self.assertEqual(image.get_content_type(), mime)
            self.assertEqual(image.get_payload(decode=True), raw)

    def test_invalid_or_missing_reference_never_falls_back_to_text(self):
        for payload in [dict(reference_file='../original.png'), dict(reference_file='missing.png'),
                        dict(reference_image='broken'), dict(reference_image=base64.b64encode(b'not an image').decode()),
                        dict(reference_file='original.png',reference_image='AAAA'),
                        dict(reference_image='data:image/svg+xml;base64,AAAA')]:
            with self.subTest(payload=payload):
                self.assertEqual(self.generate(**payload).status_code, 422)
        self.assertEqual(self.requests, [])

    def test_large_image_rejected_before_upstream(self):
        from app.core.参考图 import MAX_IMAGE_BASE64
        response = self.generate(reference_image='A' * (MAX_IMAGE_BASE64 + 1))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.requests, [])

    def test_unsupported_edit_keeps_original_and_never_retries_generation(self):
        self.status = 404
        response = self.generate(reference_file='original.png')
        self.assertEqual(response.status_code, 502)
        self.assertIn('参考图', response.json()['detail']['solution'])
        self.assertEqual(len(self.requests), 1)
        self.assertEqual((self.directory / 'original.png').read_bytes(), self.original)

    def test_known_text_only_model_returns_useful_error(self):
        self.setting['model'] = 'doubao-seedream-3-0-t2i'
        response = self.generate(reference_file='original.png')
        self.assertEqual(response.status_code, 400)
        self.assertIn('只支持文字', response.json()['detail']['message'])
        self.assertEqual(self.requests, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
