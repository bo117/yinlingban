"""独立数据库和本机模拟图片服务：浏览器 → 后端 → 图片编辑接口完整联调。"""
import base64
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Lib/site-packages'))
from PIL import Image


def main():
    with tempfile.TemporaryDirectory(prefix='ylb-image-edit-') as tmp:
        tmp = Path(tmp); images = tmp / 'images'; images.mkdir()
        image = Image.new('RGB',(128,128),'#e6c897'); image.save(images/'original.png')
        result = io.BytesIO(); Image.new('RGB',(128,128),'#a5bed8').save(result,'PNG')
        (images/'history.json').write_text(json.dumps([{'file':'original.png','prompt':'原始参考图'}],ensure_ascii=False),encoding='utf-8')
        calls = []
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                body=self.rfile.read(int(self.headers['Content-Length']))
                if 'multipart/form-data' in self.headers.get('Content-Type',''):
                    message=BytesParser(policy=default).parsebytes(('Content-Type: '+self.headers['Content-Type']+'\r\n\r\n').encode()+body)
                    fields={part.get_param('name',header='content-disposition'):part for part in message.iter_parts()}
                    calls.append((self.path,fields['image'].get_payload(decode=True)))
                else: calls.append((self.path,None))
                raw=json.dumps({'data':[{'b64_json':base64.b64encode(result.getvalue()).decode()}]}).encode()
                self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
        upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
        threading.Thread(target=upstream.serve_forever,daemon=True).start()
        with socket.socket() as sock: sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        env=os.environ.copy()
        env.update(PYTHONPATH=str(ROOT/'Lib/site-packages'),PYTHONIOENCODING='utf-8',DATABASE_URL='sqlite:///'+(tmp/'test.db').as_posix(),
                   GENERATED_IMAGE_DIR=str(images),CANVAS_MEDIA_DIR=str(tmp/'media'),LLM_PROVIDER_ID='openai',KEY_OPENAI='',
                   IMAGE_PROVIDER_ID='custom',IMAGE_MODEL='gpt-image-1',KEY_CUSTOM='local-test-only',
                   IMAGE_CUSTOM_BASE_URL=f'http://127.0.0.1:{upstream.server_port}/v1/images/generations')
        with (tmp/'server.log').open('wb') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT/'backend',env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({})); url=f'http://127.0.0.1:{port}'
            end=time.monotonic()+25
            while time.monotonic()<end:
                try:
                    with opener.open(url+'/ready',timeout=.5): break
                except OSError: time.sleep(.1)
            else: raise RuntimeError((tmp/'server.log').read_text(encoding='utf-8'))
            completed=subprocess.run(['node',str(ROOT/'backend/tests/参考图界面测试.cjs'),url,str(images/'original.png'),str(ROOT/'参考图输入预览.png')],env=env,capture_output=True,text=True,encoding='utf-8',timeout=90)
            if completed.returncode: raise RuntimeError(completed.stdout+completed.stderr)
            assert [call[0] for call in calls] == ['/v1/images/edits','/v1/images/edits','/v1/images/generations'],calls
            assert calls[0][1] == (images/'original.png').read_bytes()
            assert calls[1][1] == result.getvalue()
            print(completed.stdout.strip())
            print('Browser-to-upstream original image bytes and chained edit verified.')
        finally:
            server.terminate();server.wait(timeout=10)
            upstream.shutdown();upstream.server_close()


if __name__=='__main__': main()
