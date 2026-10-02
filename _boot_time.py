# -*- coding: utf-8 -*-
"""临时工具：启动耗时测量 + MiSans CSS 检查"""
import io
import subprocess
import time

# MiSans CSS 是否含 font-display（决定字体加载是否阻塞渲染）
try:
    import urllib.request
    req = urllib.request.Request(
        "https://cdn.jsdelivr.net/npm/misans@4.1.0/lib/Normal/MiSans-Regular.min.css")
    css = urllib.request.urlopen(req, timeout=8).read().decode("utf-8", "ignore")
    print("font-display:", "font-display" in css,
          "| swap:", "swap" in css, "| css bytes:", len(css))
except Exception as e:
    print("MiSans css fetch fail:", e)

# 测量冷启动耗时：杀掉现有服务 → 启动 → 轮询 /health
import httpx
import os

subprocess.run(["taskkill", "/F", "/PID", "无"], capture_output=True)
# 找到并停掉 8000 服务
r = os.popen("netstat -ano | findstr :8000 | findstr LISTENING").read()
for line in r.splitlines():
    pid = line.split()[-1]
    os.system(f"taskkill /F /PID {pid} >nul 2>&1")
time.sleep(2)

t0 = time.time()
proc = subprocess.Popen(
    [r"C:\Users\Administrator\Desktop\yinlingban_env\Scripts\python.exe", "start.py"],
    cwd=r"C:\Users\Administrator\Desktop\yinlingban_env\backend",
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=0x08000000)  # CREATE_NO_WINDOW
ready = None
while time.time() - t0 < 40:
    try:
        h = httpx.get("http://127.0.0.1:8000/health", timeout=2, trust_env=False)
        if h.status_code == 200:
            ready = time.time() - t0
            break
    except Exception:
        pass
    time.sleep(0.2)
print("冷启动到 /health 就绪: %.1f 秒" % (ready if ready else -1))
