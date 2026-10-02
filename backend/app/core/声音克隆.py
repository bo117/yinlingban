"""Fish Audio Open API 的个人音色创建、查询和试听，复用现有 TTS 配置。"""
import base64
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from app import config
from app.core.http_pool import get_client

MAX_AUDIO = 10 * 1024 * 1024
AUDIO_TYPES = {'wav':'audio/wav','mp3':'audio/mpeg','flac':'audio/flac','m4a':'audio/mp4',
               'aac':'audio/aac','mp4':'audio/mp4','mpeg':'audio/mpeg','oga':'audio/ogg',
               'ogg':'audio/ogg','opus':'audio/ogg','webm':'audio/webm'}


class CloneError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def fish_base(address):
    """只识别用户已配置的 Fish Audio Open API，不改写到另一家服务。"""
    if address and not address.startswith(('http://','https://')):
        address = 'https://' + address
    url = urlsplit(address or '')
    if url.hostname not in ('fishaudio.org','www.fishaudio.org'):
        return ''
    path = url.path.rstrip('/')
    for suffix in ('/audio/speech','/speech/tts','/voices'):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            break
    if path != '/api/open/v1':
        return ''
    return urlunsplit((url.scheme,url.netloc,path,'',''))


def settings():
    value = config.tts_setting()
    base = fish_base(value['base_url'])
    if not base:
        raise CloneError('当前声音克隆支持 Fish Audio。请在语音配置中选择“自定义”，填写 Fish Audio Open API 地址并保存。')
    if not value['key']:
        raise CloneError('请先保存 Fish Audio 的语音 API 密钥。')
    return base, value['key']


def check_response(response):
    if response.is_success:
        return
    messages = {401:'语音密钥无效或已过期，请在语音配置中更新。',
                402:'语音服务额度不足，请检查账户余额。',403:'当前账户未开通此语音功能。',
                404:'语音接口不存在，请检查 Fish Audio 请求地址。',
                429:'语音服务限流，请稍后重试。'}
    raise CloneError(messages.get(response.status_code, f'语音服务请求失败（HTTP {response.status_code}），请检查录音或稍后重试。'),502)


async def list_voices():
    base,key = settings()
    response = await get_client('voice-clone',30).get(base+'/voices',params={'modelType':'personal','includePersonal':'true','pageSize':100},
                                                       headers={'Authorization':f'Bearer {key}'})
    check_response(response)
    data = response.json()
    return [{'id':item['voiceId'],'name':item.get('title') or '个人音色'} for item in data.get('items',[]) if item.get('voiceId')]


async def create_voice(name, raw, filename, reference_text=''):
    base,key = settings()
    name = name.strip()
    extension = Path(filename or '').suffix.lower().lstrip('.')
    if not name or len(name) > 80:
        raise CloneError('请填写 1 至 80 字的音色名称。')
    if not raw or len(raw) > MAX_AUDIO or extension not in AUDIO_TYPES:
        raise CloneError('请选择 10 MB 以内的有效音频文件，例如 WAV、MP3 或 M4A。')
    response = await get_client('voice-clone-create',httpx.Timeout(10,read=180,write=60)).post(
        base+'/voices', headers={'Authorization':f'Bearer {key}'},
        data={'name':name,'visibility':'private','referenceText':reference_text},
        files={'audioFiles':('reference.'+extension,raw,AUDIO_TYPES[extension])})
    check_response(response)
    data = response.json()
    if not data.get('voiceId'):
        raise CloneError('服务未返回音色 ID。请先刷新音色列表确认是否创建成功，再决定是否重试。',502)
    return {'id':data['voiceId'],'name':data.get('title') or name}


async def speech(base,key,text,voice,speed=1.0):
    if not voice or voice in ('alloy','default'):
        raise CloneError('请先在“声音克隆”中选择音色，或填入 Fish Audio 的音色 ID。')
    response = await get_client('fish-speech',httpx.Timeout(10,read=120,write=30)).post(
        base+'/speech/tts', headers={'Authorization':f'Bearer {key}'},
        json={'text':text,'voiceId':voice,'format':'mp3','cache':False,'speed':max(.5,min(2,speed))})
    check_response(response)
    if not response.content or not response.headers.get('content-type','').lower().startswith(('audio/','application/octet-stream')):
        raise CloneError('语音服务未返回音频，请稍后重试。',502)
    return base64.b64encode(response.content).decode('ascii')
