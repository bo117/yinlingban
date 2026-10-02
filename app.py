# -*- coding: utf-8 -*-
"""
API 教学助手 · 后端（文件 1/2）
================================================================
文件 1/2 : app.py      —— Python 后端（扮演"服务端"，把请求转发给真正的大模型 API）
文件 2/2 : index.html  —— 蓝白色前端聊天界面（由本程序自动在浏览器打开）

启动方法：双击 app.py，或命令行运行  python app.py

它做的事：
    ① 接收前端发来的 JSON（问题 + API地址 + 密钥 + 参数）；
    ② 频率检查（2 分钟内最多 5 个问题，超了返回 429）；
    ③ 密钥/参数检查；
    ④ 用标准库 urllib 把请求原样转发到你设置的 API 地址（魔力方舟等 OpenAI 兼容接口）；
    ⑤ 把服务商的原始响应（含思考过程 reasoning_content、用量统计）连同
       "转发了什么、收到什么"一起回给前端 —— 学生在右侧面板能看到完整工作流程。

仅用 Python 标准库，无需安装任何第三方包。按 Ctrl+C 或关掉窗口即停止。
"""

import json
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ----------------------------------------------------------------------
# 配置
# ----------------------------------------------------------------------
HOST = "0.0.0.0"          # 允许同一局域网的设备（手机/其他电脑）访问
PORT_PREFERRED = 8899     # 端口被占用时自动向后尝试
RATE_LIMIT = 5            # 频率限制：窗口内最多提问次数
RATE_WINDOW = 120         # 频率限制窗口（秒）＝ 2 分钟
PROVIDER_TIMEOUT = 120    # 等待大模型 API 响应的超时（秒）

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_hits = {}                # IP -> 最近调用时间戳队列
_lock = threading.Lock()


def mask_key(key):
    """在前端展示时把密钥打码，避免整班看到"""
    key = str(key or "")
    if len(key) <= 4:
        return "****"
    return key[:2] + "****" + key[-2:]


# ----------------------------------------------------------------------
# 频率限制（按访问者 IP 统计，滚动窗口）
# ----------------------------------------------------------------------
def rate_state(ip):
    now = time.time()
    with _lock:
        dq = _hits.setdefault(ip, deque())
        while dq and now - dq[0] > RATE_WINDOW:
            dq.popleft()
        retry = max(0, int(round(dq[0] + RATE_WINDOW - now + 0.5))) if dq else 0
        return RATE_LIMIT - len(dq), retry


def rate_charge(ip):
    """记一次调用（无论成败都计数）。返回 (是否放行, 剩余次数, 需等待秒数)"""
    now = time.time()
    with _lock:
        dq = _hits.setdefault(ip, deque())
        while dq and now - dq[0] > RATE_WINDOW:
            dq.popleft()
        if len(dq) >= RATE_LIMIT:
            retry = max(1, int(round(dq[0] + RATE_WINDOW - now + 0.5)))
            return False, 0, retry
        dq.append(now)
        remaining = RATE_LIMIT - len(dq)
        retry = max(1, int(round(dq[0] + RATE_WINDOW - now + 0.5))) if remaining == 0 else 0
        return True, remaining, retry


# ----------------------------------------------------------------------
# 转发工具：调用真正的大模型 API（OpenAI 兼容格式）
# ----------------------------------------------------------------------
def _http(url, method, headers, data=None, timeout=PROVIDER_TIMEOUT):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), None, time.time() - t0
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
        return e.code, raw, None, time.time() - t0
    except ssl.SSLCertVerificationError:
        # 机房/旧系统证书库可能过旧：降级重试一次（仅教学环境使用）
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req2 = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req2, timeout=timeout, context=ctx) as resp:
                return resp.status, resp.read().decode("utf-8", "replace"), None, time.time() - t0
        except urllib.error.HTTPError as e:
            try:
                raw = e.read().decode("utf-8", "replace")
            except Exception:
                raw = ""
            return e.code, raw, None, time.time() - t0
        except Exception as e2:
            return 0, "", str(e2), time.time() - t0
    except Exception as e:
        return 0, "", str(e), time.time() - t0


def provider_headers(api_key):
    return {
        "Content-Type": "application/json",
        "Authorization": "Bearer %s" % api_key,
        "User-Agent": "API-Teach-Assistant/2.0",
    }


# ----------------------------------------------------------------------
# HTTP 服务器
# ----------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "TeachAPI/2.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _log(self, ip, line):
        try:
            print("[%s] %-15s %s" % (datetime.now().strftime("%H:%M:%S"), ip, line))
            sys.stdout.flush()
        except Exception:
            pass

    # ---------------- 静态页 / 配额查询 ----------------
    def do_GET(self):
        ip = self.client_address[0]
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            try:
                with open(os.path.join(BASE_DIR, "index.html"), "rb") as f:
                    html = f.read()
            except Exception as e:
                self._send(500, {"error": {"code": "server_error",
                                           "message": "读取 index.html 失败: %s" % e}})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
        elif path == "/api/quota":
            remaining, retry = rate_state(ip)
            self._send(200, {"limit": RATE_LIMIT, "window_seconds": RATE_WINDOW,
                             "remaining": max(0, remaining), "retry_after": retry})
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self._send(404, {"error": {"code": "not_found",
                                       "message": "接口不存在: %s" % path}})

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            return None

    # ---------------- POST /api/models：拉取服务商的模型列表 ----------------
    def do_POST(self):
        ip = self.client_address[0]
        path = self.path.split("?")[0]
        payload = self._read_json()
        if payload is None:
            self._send(400, {"error": {"code": "bad_request",
                                       "message": "请求体不是合法的 JSON。"}})
            return

        if path == "/api/models":
            base = str(payload.get("api_base") or "").strip().rstrip("/")
            key = str(payload.get("api_key") or "").strip()
            if not base.startswith(("http://", "https://")):
                self._send(400, {"error": {"code": "bad_request",
                                           "message": "API 地址不合法，应以 http(s):// 开头，通常以 /v1 结尾。"}})
                return
            status, raw, err, dur = _http(base + "/models", "GET", provider_headers(key))
            if err:
                self._send(502, {"error": {"code": "network_error",
                                           "message": "够不着魔力方舟的服务器：%s" % err}})
                return
            models = []
            try:
                data = json.loads(raw)
                for m in (data.get("data") or []):
                    mid = m.get("id") if isinstance(m, dict) else None
                    if mid:
                        models.append(mid)
            except Exception:
                pass
            self._send(200, {"provider_status": status, "duration_ms": int(dur * 1000),
                             "endpoint": base + "/models", "models": models,
                             "raw": raw[:4000], "api_key_masked": mask_key(key)})
            self._log(ip, "GET %s/models -> %s（%d 个模型，%.1fs）" % (base, status, len(models), dur))
            return

        if path != "/api/chat":
            self._send(404, {"error": {"code": "not_found",
                                       "message": "接口不存在: %s（只有 /api/chat 和 /api/models）" % path}})
            return

        # ================= POST /api/chat =================
        base = str(payload.get("api_base") or "").strip().rstrip("/")
        key = str(payload.get("api_key") or "").strip()
        model = str(payload.get("model") or "").strip()
        messages = payload.get("messages") or []
        effort = str(payload.get("reasoning_effort") or "low").lower()
        try:
            ctx_window = int(payload.get("context_window") or 512)
        except Exception:
            ctx_window = 512
        ctx_window = max(64, min(ctx_window, 32768))
        send_effort = bool(payload.get("send_reasoning_param", True))

        if not base.startswith(("http://", "https://")):
            self._send(400, {"error": {"code": "bad_request",
                                       "message": "API 地址还没填～去 ⚙ 设置里把魔力方舟给的接口地址填上（一般以 /v1 结尾）。"}})
            return
        if not key:
            self._send(401, {"error": {"code": "missing_api_key",
                                       "message": "密钥还没填呢～点右上角 ⚙ 设置，把魔力方舟给你的密钥粘进来。"}})
            return
        if not model:
            self._send(400, {"error": {"code": "bad_request",
                                       "message": "还没选模型～去 ⚙ 设置里挑一个。"}})
            return

        # ② 频率检查（只有提问计数；查模型列表不计）
        allowed, remaining, retry = rate_charge(ip)
        rate_info = {"limit": RATE_LIMIT, "window_seconds": RATE_WINDOW,
                     "remaining": remaining, "retry_after": retry}
        if not allowed:
            self._send(429, {
                "error": {"code": "rate_limit_exceeded",
                          "message": "问太快啦：%d 秒内最多问 %d 个，歇 %d 秒再来～"
                                     % (RATE_WINDOW, RATE_LIMIT, retry),
                          "hint": "不是坏了，是服务器在自我保护——真正的 API 都有这一步，状态码就叫 429。"},
                "rate_limit": {"limit": RATE_LIMIT, "window_seconds": RATE_WINDOW,
                               "remaining": 0, "retry_after": retry}})
            self._log(ip, "POST /api/chat -> 429 频率限制（%d 秒后重试）" % retry)
            return

        # ③ 组装转发给大模型服务商的请求体
        provider_body = {"model": model, "messages": messages,
                         "stream": False, "max_tokens": ctx_window}
        if send_effort:
            provider_body["reasoning_effort"] = effort
        body_bytes = json.dumps(provider_body, ensure_ascii=False).encode("utf-8")
        url = base + "/chat/completions"
        shown_request = {
            "method": "POST", "url": url,
            "headers": {"Content-Type": "application/json",
                        "Authorization": "Bearer %s" % mask_key(key)},
            "body": provider_body,
        }

        # ④ 转发（若服务商不认识 reasoning_effort 导致 400，自动去掉该参数重试一次）
        status, raw, err, dur = _http(url, "POST", provider_headers(key), body_bytes)
        retried = False
        if status == 400 and send_effort and "reasoning" in raw.lower():
            provider_body.pop("reasoning_effort", None)
            body_bytes = json.dumps(provider_body, ensure_ascii=False).encode("utf-8")
            shown_request["body"] = provider_body
            status, raw, err, dur = _http(url, "POST", provider_headers(key), body_bytes)
            retried = True
        if err:
            self._send(502, {"error": {"code": "network_error",
                                       "message": "够不着魔力方舟的服务器：%s" % err},
                             "request": shown_request, "rate_limit": rate_info})
            self._log(ip, "POST /api/chat -> 网络错误 %s" % err)
            return

        # ⑤ 解析服务商响应
        try:
            data = json.loads(raw)
        except Exception:
            data = None

        thinking, answer, usage, citations = None, None, None, []
        if data:
            msg = ((data.get("choices") or [{}])[0].get("message") or {}) if data.get("choices") else {}
            thinking = msg.get("reasoning_content") or msg.get("reasoning") or None
            answer = msg.get("content")
            usage = data.get("usage")
            citations = data.get("citations") or data.get("search_results") or []

        ok = (status == 200 and answer is not None)
        if not ok:
            # 服务商报错：原样转述，方便在课堂上看到真实的错误响应
            err_payload = {"error": {
                "code": "provider_error",
                "message": "魔力方舟那边返回了 HTTP %d（%s）" % (status, dur and "%.1fs" % dur),
                "provider_body": (raw or "")[:2000],
                "hint": ("401/403：密钥不对或者没权限，去 ⚙ 设置里瞅瞅；" if status in (401, 403) else
                         "404：地址可能抄错了，看看是不是少了 /v1；" if status == 404 else
                         "429：魔力方舟那边也限流了，歇会儿再问；" if status == 429 else
                         "400：这个模型可能不认某个参数。"),
            }, "request": shown_request, "rate_limit": rate_info,
               "provider_status": status, "duration_ms": int(dur * 1000), "retried_without_reasoning": retried}
            self._send(status if status >= 400 else 502, err_payload)
            self._log(ip, "POST %s/chat/completions -> %s（%.1fs）" % (base, status, dur))
            return

        if not str(answer).strip():
            answer = "（模型光顾着思考、忘了说话——上下文窗口只有 512，容量太小，额度可能全被思考过程吃掉了。这就是参数全调最低的代价 😅）"

        resp_payload = {
            "provider_status": status,
            "duration_ms": int(dur * 1000),
            "retried_without_reasoning": retried,
            "request": shown_request,          # 转发了什么（密钥已打码）
            "provider_response": data,         # 服务商的原始 JSON 响应
            "model": model,
            "api_base": base,
            "thinking": thinking,              # 思考过程（模型返回了才有）
            "answer": answer,
            "usage": usage,
            "citations": citations,            # 若服务商带联网搜索来源，则原样透传
            "rate_limit": rate_info,
        }
        self._send(200, resp_payload)
        u = usage or {}
        self._log(ip, "POST %s/chat/completions -> 200 模型:%s tokens:%s 用时 %.1fs 剩余 %d/%d"
                  % (base, model, u.get("total_tokens", "?"), dur, remaining, RATE_LIMIT))


def lan_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    server, port = None, PORT_PREFERRED
    for p in range(PORT_PREFERRED, PORT_PREFERRED + 12):
        try:
            server = ThreadingHTTPServer((HOST, p), Handler)
            port = p
            break
        except OSError:
            continue
    if server is None:
        print("启动失败：端口 %d-%d 都被占用。" % (PORT_PREFERRED, PORT_PREFERRED + 11))
        return

    url = "http://127.0.0.1:%d" % port
    print("=" * 62)
    print("  API 教学助手 已启动（蓝白界面 · 转发真实大模型 API）")
    print("  ------------------------------------------------------------")
    print("  本机访问  :  %s" % url)
    print("  局域网访问:  http://%s:%d   （同一 WiFi 下的手机/其他电脑）" % (lan_ip(), port))
    print("  使用前请先在网页右上角 ⚙ 设置里填好：")
    print("      ① API 地址（魔力方舟的接口地址，通常以 /v1 结尾）")
    print("      ② API 密钥（在魔力方舟后台创建）")
    print("      ③ 模型（可点「获取模型列表」自动拉取，选最便宜的即可）")
    print("  频率限制  :  %d 次 / %d 秒（按访问者 IP 计数，试错也计数）" % (RATE_LIMIT, RATE_WINDOW))
    print("  停止服务  :  关闭本窗口，或按 Ctrl+C")
    print("  —— 下方日志就是服务端视角，投影给全班正合适 ——")
    print("=" * 62)

    if os.environ.get("API_TEACH_NO_BROWSER") != "1":
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")


if __name__ == "__main__":
    main()
