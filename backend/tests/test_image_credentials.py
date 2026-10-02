"""Temporary image credentials work without saving settings or calling a real vendor."""
import asyncio
import unittest
from unittest.mock import patch
from app.core import image_service


class ImageCredentialsTest(unittest.TestCase):
    def test_temporary_key_reaches_upstream_without_saving(self):
        class Response:
            status_code = 200
            def json(self):
                return {"data": [{"url": "https://example.invalid/image.png"}]}
        class Client:
            async def post(self, url, **kwargs):
                self.url, self.kwargs = url, kwargs
                return Response()
        client = Client()
        settings = {"key":"", "configured":False, "provider_id":"custom", "provider_name":"Custom",
                    "model":"old", "protocol":"openai_images", "base_url":""}
        with patch.object(image_service.config, 'image_setting', return_value=settings.copy()), \
             patch.object(image_service.config, '_resolve_setting', return_value=settings.copy()), \
             patch.object(image_service, 'get_client', return_value=client):
            result = asyncio.run(image_service.generate(image_service.GenerateParams(
                prompt='a cat', provider_id='custom', model='chosen-model',
                key='test-only-not-a-secret', base_url='https://example.invalid/v1')))
        self.assertTrue(result['success'])
        self.assertEqual(client.kwargs['headers']['Authorization'], 'Bearer test-only-not-a-secret')
        self.assertEqual(client.kwargs['json']['model'], 'chosen-model')
        self.assertEqual(client.url, 'https://example.invalid/v1/images/generations')


if __name__ == '__main__':
    unittest.main()
