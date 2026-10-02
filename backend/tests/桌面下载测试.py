"""临时数据库与真实 Edge/WebView2：保存、取消、重复下载及导出后编辑。"""
import ctypes
import base64
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path
from unittest.mock import patch
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('yinlingban.download').setLevel(logging.DEBUG)
    import webview
    from 桌面下载 import install_downloads
    report = {}
    with tempfile.TemporaryDirectory(prefix='ylb-download-') as tmp:
        tmp = Path(tmp)
        env = os.environ.copy()
        env.update(PYTHONPATH=str(ROOT / 'Lib/site-packages'), PYTHONIOENCODING='utf-8',
                   DATABASE_URL='sqlite:///' + (tmp / 'test.db').as_posix(),
                   CANVAS_MEDIA_DIR=str(tmp / 'media'), GENERATED_IMAGE_DIR=str(tmp / 'images'),
                   LLM_PROVIDER_ID='openai', KEY_OPENAI='')
        image_dir = tmp / 'images'; image_dir.mkdir()
        image_bytes = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zt6AAAAAASUVORK5CYII=')
        for name in ['test1.png', 'test2.png']:
            (image_dir / name).write_bytes(image_bytes)
        (image_dir / 'history.json').write_text(json.dumps([
            {'file':'test1.png', 'prompt':'历史图片一', 'created_at':'2026-09-24 20:10:09'},
            {'file':'test2.png', 'prompt':'历史图片二', 'created_at':'2026-09-13 20:51:04'}], ensure_ascii=False), encoding='utf-8')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with (tmp / 'server.log').open('wb') as log:
            server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host','127.0.0.1','--port',str(port)],
                                      cwd=ROOT / 'backend', env=env, stdout=log, stderr=log,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                try:
                    with opener.open(url + '/ready', timeout=.5):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError((tmp / 'server.log').read_text(encoding='utf-8'))
            node = subprocess.run(['node', str(ROOT / 'backend/tests/下载交互测试.cjs'), url],
                                  env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
            if node.returncode:
                raise RuntimeError(node.stdout + node.stderr)
            report.update(json.loads(node.stdout))

            # 真实 Windows 保存对话框仅操作本测试进程，文件写入临时目录。
            user32 = ctypes.windll.user32
            user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.EnumChildWindows.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.LPARAM]
            user32.GetDlgCtrlID.argtypes = [wintypes.HWND]
            callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            pending_action = [None]
            actions_done = []
            seen_dialogs = set()
            stopped = threading.Event()
            dialog_ready = [False]

            # 测试固定保存位置，仍使用真实 Windows 对话框及 WebView2 写文件。
            # 不用模拟键入路径，以免文件对话框初始化时覆盖输入而写到用户目录。
            def install_test_downloads(window):
                import System.Windows.Forms as forms
                real_dialog = forms.SaveFileDialog
                class TestDialog:
                    def __init__(self):
                        object.__setattr__(self, '_dialog', real_dialog())
                    def __getattr__(self, name):
                        return getattr(self._dialog, name)
                    def __setattr__(self, name, value):
                        setattr(self._dialog, name, value)
                    def ShowDialog(self, owner):
                        self._dialog.InitialDirectory = str(tmp)
                        self._dialog.FileName = str(pending_action[0][1])
                        dialog_ready[0] = time.monotonic() + 1
                        return self._dialog.ShowDialog(owner)
                with patch('桌面下载._create_save_dialog', TestDialog):
                    install_downloads(window)

            def automate_dialogs():
                def window_found(hwnd, unused):
                    process = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
                    title = ctypes.create_unicode_buffer(128)
                    user32.GetWindowTextW(hwnd, title, len(title))
                    if process.value == os.getpid() and title.value:
                        seen_dialogs.add(title.value)
                    if (process.value != os.getpid() or title.value != '保存下载文件' or not pending_action[0]
                            or not dialog_ready[0] or time.monotonic() < dialog_ready[0]):
                        return True
                    action, path = pending_action[0]
                    if action == 'cancel':
                        user32.PostMessageW(hwnd, 0x10, 0, 0)
                    else:
                        user32.PostMessageW(hwnd, 0x111, 1, 0)
                    pending_action[0] = None
                    dialog_ready[0] = False
                    actions_done.append(action)
                    return True
                while not stopped.wait(.15):
                    user32.EnumWindows(callback_type(window_found), 0)

            window = webview.create_window('下载自动验证', url=url, width=1100, height=800)
            window.events.before_load += install_test_downloads
            threading.Thread(target=automate_dialogs, daemon=True).start()
            def wait_js(script):
                end = time.monotonic() + 15
                while time.monotonic() < end:
                    if window.evaluate_js(script):
                        return
                    time.sleep(.1)
                raise AssertionError('等待页面超时: ' + script)

            def exercise():
                try:
                    from System import Action
                    wait_js("document.querySelector('#welcome-mask.show') !== null")
                    window.evaluate_js("document.getElementById('welcome-name').value='原生下载测试'; document.getElementById('welcome-go').click()")
                    wait_js("userId > 0")
                    window.evaluate_js("switchModule('imggen')")
                    wait_js("document.querySelectorAll('.img-history-item').length === 2 && !!document.getElementById('img-dl-btn')")
                    # 保存前先取消一次；再连续保存两次，确认没有遗漏 Complete 或重复绑定。
                    for index, action in enumerate(['cancel','save','save']):
                        destination = tmp / f'图片下载{index}.png'
                        pending_action[0] = (action, destination)
                        # 使用浏览器输入事件点击，不移动用户的系统鼠标。
                        point = window.evaluate_js("(() => {const r=document.getElementById('img-dl-btn').getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2};})()")
                        for event_type in ['mousePressed', 'mouseReleased']:
                            task = []
                            params = json.dumps(dict(point, type=event_type, button='left', clickCount=1))
                            window.native.Invoke(Action(lambda: task.append(window.native.browser.webview.CoreWebView2.CallDevToolsProtocolMethodAsync('Input.dispatchMouseEvent', params))))
                            task[0].Wait(5000)
                        end = time.monotonic() + 15
                        while len(actions_done) <= index and time.monotonic() < end:
                            time.sleep(.1)
                        assert len(actions_done) == index + 1, f'保存窗口未完成：第{index + 1}次，{seen_dialogs}，{actions_done}'
                        if action == 'save':
                            while (not destination.exists() or destination.stat().st_size == 0) and time.monotonic() < end:
                                time.sleep(.1)
                            assert destination.exists(), f'文件未写入：{destination.name}，目录：{[p.name for p in tmp.iterdir()]}'
                            assert destination.read_bytes() == image_bytes
                        else:
                            assert not destination.exists()
                        # 无论保存还是取消，窗口都继续响应 JS 及图片切换。
                        assert window.evaluate_js('6 * 7') == 42
                        window.evaluate_js("document.querySelectorAll('.img-history-item')[1].click()")
                        assert window.evaluate_js('_imgCurFile') == 'test2.png'
                    report['native_image_cancel_save_repeat_responsive'] = 'passed'
                except Exception as exc:
                    report['native_error'] = repr(exc)
                finally:
                    stopped.set()
                    window.destroy()

            # 窗口若发生死锁，验证进程明确失败退出；不留下测试后端。
            def watchdog():
                if not stopped.wait(55):
                    server.terminate()
                    print('Native download test timed out', flush=True)
                    os._exit(2)
            threading.Thread(target=watchdog, daemon=True).start()
            webview.start(exercise, gui='edgechromium', private_mode=True, storage_path=str(tmp / 'profile'))
        finally:
            server.terminate()
            server.wait(timeout=10)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        assert 'native_error' not in report, report


if __name__ == '__main__':
    main()
