"""设置留空不删密钥、失败不改凭据、TTS 热更新及 Fish Audio 克隆请求回归。"""
import asyncio
from email.parser import BytesParser
from email.policy import default
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
import wave

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Lib/site-packages'),str(ROOT/'backend')]
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from dotenv import dotenv_values
from app import config
from app.api import routes_settings, routes_tts
from app.core import 声音克隆 as clone
from app.core.llm_client import llm_client, LLMError


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ylb-settings-')
        self.path=Path(self.temp.name)/'.env'
        self.path.write_text('KEY_CUSTOM=old-test-key\n',encoding='utf-8')
        self.configured=dict(provider_id='custom',base_url='https://fishaudio.org/api/open/v1',key='test-voice-key',configured=True,
                             provider_name='test',model='default',protocol='openai_tts',voice='voice-1')
        write=routes_settings._write_env
        self.contexts=[patch.object(routes_settings,'_write_env',side_effect=lambda pairs:write(pairs,self.path)),
                       patch.object(config,'_KEY_CACHE',{}),patch.object(config,'LLM_PROVIDER_ID','custom'),
                       patch.object(config,'LLM_MODEL','model-test'),patch.object(config,'LLM_BASE_URL','https://example.invalid/v1'),
                       patch.object(config,'TTS_API_KEY','old-generic'),
                       patch.dict(os.environ,{'KEY_CUSTOM':'old-test-key','KEY_TTS_CUSTOM':'old-voice-key'}),
                       patch.object(routes_settings,'test_connection',AsyncMock(return_value={'ok':False,'message':'模拟连接失败'}))]
        for context in self.contexts:context.start()
        app=FastAPI();app.include_router(routes_settings.router);app.include_router(routes_tts.router)
        self.client=TestClient(app)

    def tearDown(self):
        self.client.close()
        for context in reversed(self.contexts):context.stop()
        llm_client.refresh();self.temp.cleanup()

    def test_save_and_failed_chat_preserve_key_then_blank_save(self):
        r=self.client.post('/api/settings',json={'provider_id':'custom','key':'new-test-key'})
        self.assertTrue(r.json()['success']);self.assertFalse(r.json()['test']['ok'])
        self.assertEqual(dotenv_values(self.path)['KEY_CUSTOM'],'new-test-key')
        self.assertEqual(llm_client._headers()['Authorization'],'Bearer new-test-key')
        async def failed_chat():
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(401))) as http:
                with patch.object(llm_client,'_http',return_value=http):
                    with self.assertRaises(LLMError):
                        async for _ in llm_client.stream_chat([{'role':'user','content':'hello'}]):pass
        asyncio.run(failed_chat())
        self.client.post('/api/settings',json={'key':'','model':'another-model'})
        self.assertEqual(dotenv_values(self.path)['KEY_CUSTOM'],'new-test-key')
        self.assertEqual(config.provider_key('custom'),'new-test-key')
        states=self.client.get('/api/settings').json()
        self.assertTrue(states['llm']['configured']);self.assertNotIn('new-test-key',str(states))

    def test_tts_key_hot_update_uses_new_key(self):
        r=self.client.post('/api/settings',json={'tts_provider_id':'custom','tts_key':'new-voice-key'})
        self.assertTrue(r.json()['success'])
        self.assertEqual(config.tts_provider_key('custom'),'new-voice-key')
        self.assertEqual(dotenv_values(self.path)['KEY_TTS_CUSTOM'],'new-voice-key')

    def test_clone_multipart_private_and_preview_native_protocol(self):
        data=io.BytesIO()
        with wave.open(data,'wb') as audio:audio.setparams((1,2,16000,0,'NONE','not compressed'));audio.writeframes(b'\0\0'*1600)
        raw=data.getvalue();requests=[]
        def upstream(request):
            requests.append(request)
            if request.url.path.endswith('/speech/tts'):return httpx.Response(200,content=b'ID3test-audio',headers={'Content-Type':'audio/mpeg'})
            if request.method=='GET':return httpx.Response(200,json={'items':[{'voiceId':'voice-1','title':'我的声音'}]})
            return httpx.Response(200,json={'voiceId':'voice-1','title':'我的声音'})
        http=httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        try:
            with patch.object(config,'tts_setting',return_value=self.configured),patch.object(clone,'get_client',return_value=http):
                result=self.client.post('/api/tts/clone',data={'name':'我的声音'},files={'audio':('sample.wav',raw,'audio/wav')})
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(result.json()['voice']['id'],'voice-1')
                self.assertEqual(self.client.get('/api/tts/clone/voices').json()['voices'][0]['id'],'voice-1')
                result=self.client.post('/api/tts/synthesize',json={'text':'你好','voice':'voice-1'})
                self.assertEqual(result.status_code,200,result.text)
                self.assertTrue(result.json()['audio_base64'])
            mime=BytesParser(policy=default).parsebytes(('Content-Type: '+requests[0].headers['content-type']+'\r\n\r\n').encode()+requests[0].content)
            fields={part.get_param('name',header='content-disposition'):part for part in mime.iter_parts()}
            self.assertEqual(fields['audioFiles'].get_payload(decode=True),raw)
            self.assertEqual(fields['visibility'].get_content(),'private')
            self.assertEqual(requests[0].headers['authorization'],'Bearer test-voice-key')
            self.assertTrue(requests[-1].url.path.endswith('/speech/tts'))
        finally:asyncio.run(http.aclose())

    def test_missing_configuration_and_bad_files_do_not_call_vendor(self):
        with patch.object(config,'tts_setting',return_value={**self.configured,'key':''}),patch.object(clone,'get_client') as client:
            self.assertEqual(self.client.get('/api/tts/clone/voices').status_code,400);client.assert_not_called()
        with patch.object(config,'tts_setting',return_value=self.configured),patch.object(clone,'get_client') as client:
            self.assertEqual(self.client.post('/api/tts/clone',data={'name':'test'},files={'audio':('test.txt',b'text','text/plain')}).status_code,400)
            client.assert_not_called()


if __name__=='__main__':unittest.main(verbosity=2)
