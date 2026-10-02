"""Exercise real ASGI WebSockets, session persistence and model payloads with simulated upstreams."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Lib/site-packages'))
sys.path.insert(0, str(ROOT / 'backend'))
TEST_DIR = tempfile.TemporaryDirectory(prefix='ylb-conversation-')
os.environ.update(DATABASE_URL='sqlite:///' + (Path(TEST_DIR.name) / 'test.db').as_posix(),
                  CANVAS_MEDIA_DIR=str(Path(TEST_DIR.name) / 'canvas-media'),
                  LLM_PROVIDER_ID='openai', KEY_OPENAI='')

from fastapi.testclient import TestClient
import httpx
from app.main import app
from app.api import ws as ws_module
from app import config
from app.core.llm_client import llm_client, request_reasoning_effort, LLMError
from app.db.database import engine, SessionLocal
from app.db.models import MemoryFact


class ConversationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        engine.dispose()
        TEST_DIR.cleanup()

    def setUp(self):
        self.uid = self.client.post('/api/users', json={
            'name': '测试用户', 'chat_mode': 'casual', 'skip_onboarding': True}).json()['id']
        self.base = f'/api/users/{self.uid}/sessions'

    def create(self):
        response = self.client.post(self.base)
        self.assertEqual(response.status_code, 201)
        return response.json()['id']

    def test_canvas_persistence_isolation_and_conflict(self):
        path = f'/api/users/{self.uid}/canvas'
        card = {'id':'note-1', 'text':'今日灵感', 'x':12.5, 'y':-30, 'color':'yellow'}
        self.assertEqual(self.client.get(path).json(), {'revision':0, 'cards':[], 'links':[]})
        self.assertEqual(self.client.put(path, json={'revision':0, 'cards':[card]}).json(), {'revision':1})
        saved = self.client.get(path).json()
        self.assertEqual(saved['revision'], 1)
        self.assertEqual(saved['links'], [])
        self.assertEqual([{k: item[k] for k in card} for item in saved['cards']], [card])
        other = self.client.post('/api/users', json={'name':'另一位用户', 'chat_mode':'casual'}).json()['id']
        self.assertEqual(self.client.get(f'/api/users/{other}/canvas').json()['cards'], [])
        self.assertEqual(self.client.put(path, json={'revision':0, 'cards':[]}).status_code, 409)
        saved = self.client.get(path).json()['cards']
        self.assertEqual([{k: item[k] for k in card} for item in saved], [card])
        self.assertEqual(self.client.put(path, json={'revision':1, 'cards':[]}).json(), {'revision':2})
        self.assertEqual(self.client.get(path).json()['cards'], [])
        self.assertEqual(self.client.get('/api/users/999999/canvas').status_code, 404)
        self.assertEqual(self.client.put('/api/users/999999/canvas', json={'revision':0, 'cards':[]}).status_code, 404)

    def test_canvas_rejects_invalid_backup_without_overwriting(self):
        path = f'/api/users/{self.uid}/canvas'
        card = {'id':'note-1', 'text':'保留这张便签', 'x':0, 'y':0, 'color':'paper'}
        self.client.put(path, json={'revision':0, 'cards':[card]})
        invalid = [[card, card], [{**card, 'x':100001}], [{**card, 'color':'unknown'}],
                   [{**card, 'text':'x'*10001}], [{**card, 'id':'<script>'}],
                   [{**card, 'x':'NaN'}], [{**card, 'id':str(i)} for i in range(201)]]
        for cards in invalid:
            with self.subTest(cards_count=len(cards)):
                self.assertEqual(self.client.put(path, json={'revision':1, 'cards':cards}).status_code, 422)
        saved = self.client.get(path).json()
        self.assertEqual(saved['revision'], 1)
        self.assertEqual([{k: item[k] for k in card} for item in saved['cards']], [card])

    def rpc(self, name, sid, **args):
        return self.client.post('/mcp', json={'jsonrpc':'2.0','id':1,'method':'tools/call',
            'params': {'name':name, 'arguments':{'user_id': self.uid, 'session_id': sid, **args}}}).json()['result']

    def test_crud_ownership_and_scoped_memory(self):
        a, b = self.create(), self.create()
        for sid, value in [(a, '喜欢散步'), (b, '喜欢音乐')]:
            self.assertFalse(self.rpc('memory_write', sid, fact_type='like', value=value)['isError'])
        facts = lambda sid: json.loads(self.rpc('memory_read', sid)['content'][0]['text'])['facts']
        self.assertEqual(facts(a)[0]['value'], '喜欢散步')
        self.assertEqual(facts(b)[0]['value'], '喜欢音乐')
        self.client.patch(f'{self.base}/{a}', json={'title':'旅行计划', 'pinned':True})
        self.assertEqual(self.client.get(self.base).json()['sessions'][0]['id'], a)
        self.assertEqual(len(self.client.get(self.base, params={'q':'旅行'}).json()['sessions']), 1)
        self.assertEqual(self.client.patch(f'{self.base}/{a}', json={'title':'  '}).status_code, 422)
        for method in ['get', 'patch', 'delete']:
            kwargs = {'json':{'title':'非法修改'}} if method == 'patch' else {}
            self.assertEqual(getattr(self.client, method)(f'/api/users/99999/sessions/{a}', **kwargs).status_code, 404)
        self.assertEqual(self.client.delete(f'{self.base}/{a}').status_code, 200)
        self.assertEqual(self.client.get(f'{self.base}/{a}').status_code, 404)
        with SessionLocal() as db:
            self.assertEqual(db.query(MemoryFact).filter_by(session_id=a).count(), 0)
        self.assertEqual(facts(b)[0]['value'], '喜欢音乐')

    def test_cancel_timeout_and_other_connection_are_independent(self):
        cancelled = []
        async def stalled(uid, text, sid, lang='zh'):
            try:
                if text == 'partial':
                    yield {'type':'reply_delta', 'text':'第一段'}
                await asyncio.sleep(30)
                yield {'type':'reply_done','reply':'late'}
            finally:
                cancelled.append(text)
        with patch.object(ws_module, 'stream_handle_message', stalled), \
             patch.object(config, 'CHAT_FIRST_REPLY_TIMEOUT', .4), patch.object(config, 'CHAT_IDLE_TIMEOUT', .2):
            with self.client.websocket_connect('/ws') as one, self.client.websocket_connect('/ws') as two:
                for socket in [one, two]:
                    socket.send_json({'type':'hello','user_id':self.uid})
                    self.assertEqual(socket.receive_json()['type'], 'connected')
                one.send_json({'type':'chat','text':'stop','request_id':'one'})
                self.assertEqual(one.receive_json()['type'], 'accepted')
                two.send_json({'type':'chat','text':'timeout','request_id':'two'})
                self.assertEqual(two.receive_json()['type'], 'accepted')
                start = time.monotonic()
                one.send_json({'type':'ping'})
                self.assertEqual(one.receive_json()['type'], 'pong')
                one.send_json({'type':'interrupt'})
                self.assertEqual(one.receive_json()['type'], 'interrupted')
                self.assertLess(time.monotonic() - start, .3)
                self.assertEqual(two.receive_json()['code'], 'response_timeout')
                one.send_json({'type':'chat','text':'partial','request_id':'next'})
                self.assertEqual(one.receive_json()['type'], 'accepted')
                self.assertEqual(one.receive_json()['text'], '第一段')
                self.assertEqual(one.receive_json()['code'], 'response_timeout')
        self.assertCountEqual(cancelled, ['stop', 'timeout', 'partial'])

    def test_real_dialogue_does_not_leak_memory_or_history(self):
        a, b = self.create(), self.create()
        prompts = []
        async def upstream(messages, **kwargs):
            prompts.append(messages)
            yield '记下了。'
        def send(socket, sid, text):
            socket.send_json({'type':'chat', 'session_id':sid, 'text':text})
            while True:
                event = socket.receive_json()
                if event['type'] == 'error':
                    self.fail(str(event))
                if event['type'] == 'reply_done':
                    return
        with patch.dict(llm_client.setting, configured=True), \
             patch.object(llm_client, 'chat', AsyncMock(return_value='平静')), \
             patch.object(llm_client, 'stream_chat', upstream):
            with self.client.websocket_connect('/ws') as socket:
                socket.send_json({'type':'hello','user_id':self.uid}); socket.receive_json()
                send(socket, a, '我喜欢散步')
                send(socket, b, '你好')
                self.assertNotIn('散步', json.dumps(prompts[-1], ensure_ascii=False))
                send(socket, a, '还记得我的喜好吗')
                self.assertIn('散步', json.dumps(prompts[-1], ensure_ascii=False))
        self.assertEqual(len(self.client.get(f'{self.base}/{a}').json()['messages']), 4)
        self.assertEqual(len(self.client.get(f'{self.base}/{b}').json()['messages']), 2)

    def test_reasoning_slider_reaches_upstream_payload(self):
        async def run():
            payloads = []
            async def handler(request):
                payloads.append(json.loads(request.content))
                return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                with patch.dict(llm_client.setting, configured=True, provider_id='openai'), \
                     patch.object(llm_client, 'model', 'gpt-5'), patch.object(llm_client, '_http', return_value=http):
                    token = request_reasoning_effort.set('high')
                    try:
                        result = [delta async for delta in llm_client.stream_chat([{'role':'user','content':'test'}])]
                    finally:
                        request_reasoning_effort.reset(token)
                    self.assertEqual(result, ['ok'])
                    self.assertEqual(payloads[0]['reasoning_effort'], 'high')
                    self.assertNotIn('temperature', payloads[0])
                    self.assertIn('max_completion_tokens', payloads[0])
        asyncio.run(run())

    def test_provider_switch_uses_default_and_manual_model_stays_selected(self):
        from app.api import routes_settings
        from app.core import providers_catalog as catalog
        original = llm_client.setting.copy()
        try:
            with patch.object(config, 'LLM_PROVIDER_ID', 'openai'), patch.object(config, 'LLM_MODEL', 'gpt-5'), \
                 patch.object(routes_settings, '_write_env'), \
                 patch.object(routes_settings, 'test_connection', AsyncMock(return_value={'ok':True})):
                response = self.client.post('/api/settings', json={'provider_id':'deepseek'})
                self.assertEqual(response.status_code, 200)
                expected = catalog.default_model(catalog.LLM_PROVIDERS['deepseek'])
                self.assertEqual(response.json()['llm']['model'], expected)
                self.assertEqual(self.client.get('/api/model').json()['llm']['model'], expected)
                self.client.post('/api/settings', json={'provider_id':'deepseek', 'model':'my-custom-model'})
                self.assertEqual(self.client.get('/api/model').json()['llm']['model'], 'my-custom-model')
        finally:
            llm_client._apply(original)

    def test_empty_or_failed_upstream_produces_actionable_error(self):
        async def empty(messages, **kwargs):
            if False:
                yield ''
        async def failed(messages, **kwargs):
            raise LLMError('上游断开')
            yield ''
        with patch.dict(llm_client.setting, configured=True), patch.object(llm_client, 'chat', AsyncMock(return_value='平静')):
            for upstream in [empty, failed]:
                with patch.object(llm_client, 'stream_chat', upstream), self.client.websocket_connect('/ws') as socket:
                    socket.send_json({'type':'hello','user_id':self.uid}); socket.receive_json()
                    socket.send_json({'type':'chat','text':'你好'})
                    while True:
                        event = socket.receive_json()
                        self.assertNotEqual(event['type'], 'reply_done')
                        if event['type'] == 'error':
                            self.assertEqual(event['code'], 'request_failed')
                            break

    def test_old_sqlite_upgrade_preserves_history_and_legacy_memory(self):
        from sqlalchemy import create_engine, text
        from app.db import database
        old = create_engine('sqlite://')
        with old.begin() as connection:
            connection.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
            connection.execute(text('CREATE TABLE sessions (id INTEGER PRIMARY KEY, user_id INTEGER)'))
            connection.execute(text('CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id INTEGER, role TEXT, content TEXT)'))
            connection.execute(text('CREATE TABLE memories (id INTEGER PRIMARY KEY, user_id INTEGER, fact_value TEXT)'))
            connection.execute(text("INSERT INTO sessions VALUES (1, 1)"))
            connection.execute(text("INSERT INTO messages VALUES (1, 1, 'user', '旧版会话')"))
            connection.execute(text("INSERT INTO memories VALUES (1, 1, '旧版记忆')"))
        with patch.object(database, 'engine', old):
            database._migrate()
            database._migrate()
        with old.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT title FROM sessions')).scalar(), '旧版会话')
            row = connection.execute(text('SELECT fact_value, session_id FROM memories')).one()
            self.assertEqual(tuple(row), ('旧版记忆', None))
        old.dispose()


if __name__ == '__main__':
    unittest.main(verbosity=2)
