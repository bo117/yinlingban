"""Native WebView2 shell. Starts the local backend without opening a browser."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
# This distribution includes its Python dependencies alongside the launcher.
sys.path.insert(0, str(ROOT / "Lib" / "site-packages"))
sys.path.insert(0, str(ROOT / "backend"))


def _ensure_webview_runtime():
    """Hand off to the system Python when Windows used the project venv for .pyw."""
    try:
        import webview  # noqa: F401
        return
    except ModuleNotFoundError as exc:
        if exc.name != "webview":
            raise
    if os.environ.get("YLB_SYSTEM_PYTHON_HANDOFF") == "1":
        raise RuntimeError(
            "找不到桌面窗口依赖 pywebview。请运行：py -3 -m pip install -r desktop-requirements.txt"
        )
    launcher = shutil.which("pyw")
    if not launcher:
        raise RuntimeError(
            "找不到 pyw 启动器或桌面窗口依赖 pywebview。请运行：py -3 -m pip install -r desktop-requirements.txt"
        )
    env = os.environ.copy()
    env["YLB_SYSTEM_PYTHON_HANDOFF"] = "1"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    launcher_script = Path(__file__).with_name("启动银龄伴.pyw")
    subprocess.Popen(
        [launcher, "-3", str(launcher_script), *sys.argv[1:]],
        cwd=str(ROOT), env=env, creationflags=flags, close_fds=True,
    )
    raise SystemExit(0)


def main():
    _ensure_webview_runtime()
    # pythonw has no console streams; uvicorn's logging formatter still needs them.
    if sys.stdout is None or sys.stderr is None:
        log_dir = ROOT / "backend" / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = open(log_dir / "desktop.log", "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = log
        if sys.stderr is None:
            sys.stderr = log
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    started = time.perf_counter()
    metrics = {}
    server = None
    closing = threading.Event()
    backend_done = threading.Event()
    target_url = None

    def run_backend():
        nonlocal server, target_url
        try:
            import uvicorn
            from app.main import app
            sock = socket.socket()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                with opener.open("http://127.0.0.1:18765/ready", timeout=.3) as response:
                    if json.load(response).get("service") == "yinlingban":
                        sock.close()
                        target_url = "http://127.0.0.1:18765/?desktop=1"
                        return
            except OSError:
                pass
            sock.bind(("127.0.0.1", 18765))
            port = sock.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
            metrics["backend_import_s"] = round(time.perf_counter() - started, 3)
            thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
            thread.start()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            deadline = time.monotonic() + 20
            while not closing.is_set() and time.monotonic() < deadline:
                try:
                    with opener.open(f"http://127.0.0.1:{port}/ready", timeout=.3) as response:
                        if response.status == 200:
                            metrics["ready_s"] = round(time.perf_counter() - started, 3)
                            # Stable origin and profile preserve user selection between launches.
                            target_url = f"http://127.0.0.1:{port}/?desktop=1"
                            return
                except OSError:
                    pass
                closing.wait(.05)
            raise RuntimeError("本地服务未在 20 秒内就绪，请查看启动日志。")
        except Exception as exc:
            metrics["error"] = str(exc)
        finally:
            backend_done.set()

    # Import and initialize WebView2 in parallel with the backend.
    threading.Thread(target=run_backend, daemon=True).start()
    import webview
    from 桌面下载 import install_downloads
    window = webview.create_window(
        "银龄伴", url=target_url, html=None if target_url else
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<body style="font:22px Microsoft YaHei,sans-serif;background:#f5f5f7;padding:60px">'
        '<h1>银龄伴</h1><p>正在准备您的陪伴空间…</p></body></html>',
        width=1280, height=900, min_size=(800, 600), zoomable=False,
    )

    def show_app():
        backend_done.wait(25)
        if closing.is_set():
            return
        if target_url:
            if window.get_current_url() != target_url:
                window.load_url(target_url)
        else:
            import html
            window.load_html('<meta charset="utf-8"><body style="font:20px sans-serif;padding:40px">'
                             '<h2>启动失败</h2><p>' + html.escape(metrics.get("error", "本地服务启动超时")) + '</p></body>')
            if args.smoke_test:
                (ROOT / "desktop-smoke.json").write_text(json.dumps(metrics, ensure_ascii=False), encoding="utf-8")
                window.destroy()

    def on_loaded():
        if window.get_current_url() and "desktop=1" in window.get_current_url():
            metrics["page_loaded_s"] = round(time.perf_counter() - started, 3)
            if args.smoke_test:
                metrics["title"] = window.evaluate_js("document.title")
                metrics["body_font"] = window.evaluate_js("getComputedStyle(document.body).fontSize")
                (ROOT / "desktop-smoke.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
                window.destroy()

    def on_closed():
        closing.set()
        if server is not None:
            server.should_exit = True

    window.events.before_load += install_downloads
    window.events.loaded += on_loaded
    window.events.closed += on_closed
    profile = ROOT / "backend" / "data" / "desktop-profile"
    profile.mkdir(parents=True, exist_ok=True)
    try:
        webview.start(show_app, gui="edgechromium", private_mode=False, storage_path=str(profile))
    finally:
        on_closed()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
