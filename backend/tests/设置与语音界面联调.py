"""浏览器操作真实本地服务，凭据和供应商均使用测试值，不修改用户配置。"""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
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
import wave

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Lib/site-packages'),str(ROOT/'backend')]


def server(port):
    import httpx,uvicorn
    from app.main import app
    from app.api import routes_settings
    from app.core import 声音克隆 as clone
    original=routes_settings._write_env
    routes_settings._write_env=lambda pairs:original(pairs,os.environ['TEST_SETTINGS_PATH'])
    voices=[]
    def fish(request):
        assert request.headers['Authorization']=='Bearer new-voice-key'
        if request.method=='GET':return httpx.Response(200,json={'items':voices})
        if request.url.path.endswith('/speech/tts'):
            assert json.loads(request.content)['voiceId']=='test-voice'
            return httpx.Response(200,content=b'ID3test-audio',headers={'Content-Type':'audio/mpeg'})
        voices.append({'voiceId':'test-voice','title':'我的测试音色'})
        return httpx.Response(200,json=voices[-1])
    client=httpx.AsyncClient(transport=httpx.MockTransport(fish))
    clone.get_client=lambda *args:client
    uvicorn.run(app,host='127.0.0.1',port=port,log_level='warning')


def main():
    with tempfile.TemporaryDirectory(prefix='ylb-credentials-ui-') as tmp:
        tmp=Path(tmp);path=tmp/'.env';path.write_text('KEY_CUSTOM=old-test-key\n',encoding='utf-8')
        audio=tmp/'sample.wav'
        with wave.open(str(audio),'wb') as f:f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*1600)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.headers['Authorization']=='Bearer bad-test-key':
                    self.send_response(401);self.end_headers();return
                if data.get('stream'):
                    raw=('data: '+json.dumps({'choices':[{'delta':{'content':'测试回复'}}]},ensure_ascii=False)+'\n\ndata: [DONE]\n\n').encode()
                    kind='text/event-stream'
                else:
                    time.sleep(.3)
                    raw=json.dumps({'choices':[{'message':{'content':'平静'}}]},ensure_ascii=False).encode();kind='application/json'
                self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        upstream=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=upstream.serve_forever,daemon=True).start()
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env=os.environ.copy();env.update(PYTHONIOENCODING='utf-8',DATABASE_URL='sqlite:///'+(tmp/'test.db').as_posix(),
            TEST_SETTINGS_PATH=str(path),CANVAS_MEDIA_DIR=str(tmp/'media'),GENERATED_IMAGE_DIR=str(tmp/'images'),
            LLM_PROVIDER_ID='custom',LLM_MODEL='test-model',LLM_BASE_URL=f'http://127.0.0.1:{upstream.server_port}/v1',KEY_CUSTOM='old-test-key',
            TTS_PROVIDER_ID='custom',TTS_CUSTOM_BASE_URL='https://fishaudio.org/api/open/v1',KEY_TTS_CUSTOM='old-voice-key')
        with (tmp/'server.log').open('wb') as log:
            process=subprocess.Popen([sys.executable,__file__,'--server',str(port)],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            url=f'http://127.0.0.1:{port}';opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));end=time.monotonic()+25
            while time.monotonic()<end:
                try:
                    with opener.open(url+'/ready',timeout=.5):break
                except OSError:time.sleep(.1)
            else:raise RuntimeError((tmp/'server.log').read_text(encoding='utf-8'))
            result=subprocess.run(['node',str(ROOT/'backend/tests/设置与语音界面测试.cjs'),url,str(audio)],env=env,capture_output=True,text=True,encoding='utf-8',timeout=100)
            if result.returncode:raise RuntimeError(result.stdout+result.stderr+'\n'+(tmp/'server.log').read_text(encoding='utf-8')[-3000:])
            from dotenv import dotenv_values
            assert dotenv_values(path)['KEY_CUSTOM']=='new-test-key'
            assert dotenv_values(path)['KEY_TTS_CUSTOM']=='new-voice-key'
            print(result.stdout.strip())
        finally:
            process.terminate();process.wait(timeout=10);upstream.shutdown();upstream.server_close()


if __name__=='__main__':
    if '--server' in sys.argv:server(int(sys.argv[-1]))
    else:main()
