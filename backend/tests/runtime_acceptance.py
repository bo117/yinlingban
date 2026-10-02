"""Run a real HTTP server and browser against a temporary database, then restart it."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[2]


def main():
    report = {}
    with tempfile.TemporaryDirectory(prefix="ylb-check-") as tmp:
        env = os.environ.copy()
        env.update(PYTHONPATH=str(ROOT / "Lib/site-packages"), PYTHONIOENCODING="utf-8",
                   DATABASE_URL="sqlite:///" + (Path(tmp) / "test.db").as_posix(),
                   CANVAS_MEDIA_DIR=str(Path(tmp) / "canvas-media"),
                   LLM_PROVIDER_ID="openai", KEY_OPENAI="")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def call(path, body=None, method=None):
            req = urllib.request.Request(url + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Content-Type": "application/json"}, method=method)
            with opener.open(req, timeout=10) as res:
                return json.load(res)
        def rpc(method, params=None):
            return call('/mcp', {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
        def memory(name, arguments):
            return rpc('tools/call', {'name': name, 'arguments': arguments})['result']
        def start():
            began = time.perf_counter()
            log = open(Path(tmp) / 'server.log', 'ab')
            process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)],
                                       cwd=ROOT / 'backend', env=env, stdout=log, stderr=log)
            log.close()
            for _ in range(200):
                if process.poll() is not None:
                    raise RuntimeError((Path(tmp) / 'server.log').read_text(encoding='utf-8'))
                try:
                    if call('/ready')['status'] == 'ok':
                        return process, round(time.perf_counter()-began, 3)
                except OSError:
                    time.sleep(.05)
            process.terminate()
            raise RuntimeError('Server startup timed out')
        def stop(process):
            process.terminate()
            process.wait(timeout=10)
        process, report['http_ready_s'] = start()
        try:
            assert call('/health')['status'] == 'ok'
            tools = {t['name'] for t in rpc('tools/list')['result']['tools']}
            assert {'memory_read', 'memory_write', 'companion_chat'} <= tools
            assert rpc('initialize')['result']['capabilities']['tools'] is not None
            u = call('/api/users', {'name': '验收用户', 'age': 70, 'city': '上海', 'chat_mode': 'casual', 'skip_onboarding': True})
            uid = u['id']
            assert call('/api/model')['llm']['configured'] is False
            for chat_user in [uid, call('/api/users', {'name':'新长辈', 'chat_mode':'elderly'})['id']]:
                try:
                    call('/api/chat', {'user_id':chat_user, 'text':'你好'})
                    raise AssertionError('Missing API key must produce explicit configuration error')
                except urllib.error.HTTPError as error:
                    assert error.code == 409
                    detail = json.load(error)['detail']
                    assert detail['code'] == 'api_key_required' and detail['action'] == 'open_settings'
            reminder = call('/api/chat', {'user_id':uid, 'text':'提醒我10分钟后喝水'})
            assert reminder['tool_info']['success'] is True
            report['missing_api_rest_and_local_reminder'] = 'passed'
            other = call('/api/users', {'name': '隔离用户', 'age': 70, 'city': '上海', 'chat_mode': 'casual', 'skip_onboarding': True})['id']
            assert not memory('memory_write', {'user_id':uid, 'fact_type':'like', 'value':'喜欢散步'})['isError']
            assert memory('memory_write', {'fact_type':'like', 'value':'missing user'})['isError']
            assert memory('memory_write', {'user_id':uid, 'fact_type':'like', 'value':'   '})['isError']
            assert memory('memory_read', {'user_id':999999})['isError']
            assert not json.loads(memory('memory_read', {'user_id':other})['content'][0]['text'])['facts']
            assert rpc('tools/call', {'name':'memory_read', 'arguments':[]})['error']['code'] == -32602
            assert rpc('tools/call', {'name':[], 'arguments':{}})['error']['code'] == -32602
            avatar = call('/api/avatar/config')
            assert avatar['status'] == 'reserved' and 'appSecret' not in avatar
            report['mcp_validation_and_isolation'] = 'passed'
            sid = call(f'/api/users/{uid}/sessions', {})['id']
            assert not memory('memory_write', {'user_id':uid, 'session_id':sid, 'fact_type':'like', 'value':'会话专属记忆'})['isError']
            board = {'revision':0, 'cards':[{'id':'restart-note', 'text':'重启后保留的便签', 'x':125, 'y':-75, 'color':'yellow'}]}
            assert call(f'/api/users/{uid}/canvas', board, 'PUT')['revision'] == 1
            # Browser covers actual page startup, typography, settings and image request routing.
            browser = subprocess.run(['node', str(ROOT/'backend/tests/ui_acceptance.cjs'), url], cwd=ROOT,
                                     env=os.environ.copy(), capture_output=True, text=True, encoding='utf-8', timeout=180)
            if browser.returncode:
                raise RuntimeError(browser.stdout + browser.stderr)
            report['browser'] = json.loads(browser.stdout)
        finally:
            stop(process)
        process, report['restart_ready_s'] = start()
        try:
            facts = json.loads(memory('memory_read', {'user_id':uid})['content'][0]['text'])['facts']
            assert facts[0]['value'] == '喜欢散步'
            report['memory_survives_process_restart'] = 'passed'
            scoped = json.loads(memory('memory_read', {'user_id':uid, 'session_id':sid})['content'][0]['text'])['facts']
            assert scoped[0]['value'] == '会话专属记忆'
            assert call(f'/api/users/{uid}/sessions/{sid}')['id'] == sid
            report['session_memory_survives_process_restart'] = 'passed'
            assert [{key: card[key] for key in board['cards'][0]} for card in call(f'/api/users/{uid}/canvas')['cards']] == board['cards']
            report['canvas_survives_process_restart'] = 'passed'
        finally:
            stop(process)
    (ROOT/'runtime-acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
