# -*- coding: utf-8 -*-
"""
启动速度实测脚本（模拟双击，绕开系统代理探测，测完自动清理）
用法：D:\\yinlingban_env\\Scripts\\python.exe tests\\启动速度测试.py
"""
import json
import os
import subprocess
import time
import urllib.request

BASE = "http://localhost:8000"
PY = r"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"  # 系统 Python（模拟双击）
CWD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/

# 无代理 opener：直连本机（系统代理会拦截 localhost，导致探测失败/变慢）
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def main():
    print("模拟双击启动（系统Python → 自动切换虚拟环境）……")
    start = time.time()
    proc = subprocess.Popen([PY, "start.py"], cwd=CWD,
                            creationflags=subprocess.CREATE_NO_WINDOW)

    ok = False
    while time.time() - start < 60:
        try:
            with opener.open(f"{BASE}/health", timeout=1) as r:
                if r.status == 200:
                    ok = True
                    break
        except Exception:
            time.sleep(0.2)

    elapsed = time.time() - start
    if ok:
        print(f"✓ 启动耗时：{elapsed:.1f} 秒（从双击到能访问）")
        # 顺带验证对话功能
        req = urllib.request.Request(
            f"{BASE}/api/chat",
            data=json.dumps({"user_id": 1, "text": "你好"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=30) as r:
            d = json.loads(r.read())
        print(f"✓ 对话功能正常：{d['reply'][:30]}……")
    else:
        print("✗ 60秒内未启动成功！")

    # 清理：连进程树一起杀（父进程+虚拟环境子进程），释放端口
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                   capture_output=True)
    time.sleep(1)
    print("（测试进程已清理，8000端口已释放——您双击即可用8000）")


if __name__ == "__main__":
    main()
