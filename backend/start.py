# -*- coding: utf-8 -*-
"""
「银龄伴」后端一键启动脚本（角色2：郝英博）

【一键启动（双击桌面快捷方式「银龄伴」或本文件）】
    桌面体验请双击根目录的「启动银龄伴.pyw」。本文件只启动调试服务。

    - 服务已在运行 → 不重复启动；显式 --browser 才打开浏览器
    - 用错 Python（没装依赖）→ 尝试项目自带依赖和虚拟环境
    - 端口被占用 → 自动换可用端口
    - 出任何错 → 窗口停住显示中文原因，不闪退
    - 关闭黑窗口 或 按 Ctrl+C = 停止服务

常用参数（可选）：
    --port 8000      指定端口
    --host 127.0.0.1 只允许本机访问
    --reload         开发模式（改代码自动重启）
"""
import argparse
import importlib
import socket
import subprocess
import sys
import threading
from pathlib import Path

# 确保能导入 backend 目录下的 app 包
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(1, str(BASE_DIR.parent / "Lib" / "site-packages"))

BANNER = r"""
╔══════════════════════════════════════════════════╗
║                                                  ║
║     银 龄 伴 · 后端服务（角色2：郝英博）          ║
║     独居老人多模态情感陪伴与生活服务数字人          ║
║                                                  ║
╚══════════════════════════════════════════════════╝
"""

# 虚拟环境候选位置（依赖就装在这里面）
VENV_CANDIDATES = [
    BASE_DIR.parent / "Scripts" / "python.exe",
    Path(r"D:\yinlingban_env\Scripts\python.exe"),
    BASE_DIR.parent / "yinlingban_env" / "Scripts" / "python.exe",
]

# 必需依赖清单
REQUIRED_PACKAGES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "httpx": "httpx",
    "dotenv": "python-dotenv",
    "sqlalchemy": "sqlalchemy",
}


def 停住退出(code: int = 1):
    """防止窗口闪退：停住等用户看完错误再关"""
    print()
    try:
        input("按回车键关闭窗口……")
    except EOFError:
        pass
    sys.exit(code)


def check_dependencies() -> bool:
    """检查必需依赖是否已安装（只"查找"不"加载"，毫秒级完成）"""
    import importlib.util
    for module in REQUIRED_PACKAGES:
        try:
            if importlib.util.find_spec(module) is None:
                return False
        except (ImportError, ValueError):
            return False
    return True


def try_switch_to_venv() -> bool:
    """
    当前 Python 缺依赖时，自动切换到虚拟环境重新运行本脚本。
    （切过去就不再返回，当前进程直接结束）
    """
    myself = Path(__file__).resolve()
    for venv_python in VENV_CANDIDATES:
        try:
            same = venv_python.resolve() == Path(sys.executable).resolve()
        except OSError:
            same = False
        if venv_python.exists() and not same:
            print(f"  当前 Python 缺少依赖，自动切换到：{venv_python}")
            print("─" * 52)
            # 在同一窗口里用虚拟环境重新启动自己
            code = subprocess.call([str(venv_python), str(myself)] + sys.argv[1:])
            sys.exit(code)
    return False


def 端口被占用(port: int) -> bool:
    """检测端口是否已被监听"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def 找可用端口(start_port: int, max_try: int = 20) -> int:
    """从 start_port 开始找第一个没被占用的端口"""
    port = start_port
    for _ in range(max_try):
        if not 端口被占用(port):
            return port
        port += 1
    return -1


def 已运行检测(port: int) -> bool:
    """检查指定端口上是否已运行着本服务（绕开系统代理直连本机检测）

    注意：必须用 127.0.0.1 而不是 localhost——localhost 在部分 Windows 上
    先解析到 IPv6（::1），连接失败要等满整个超时才回退 IPv4，一次检测白卡 2-4 秒。
    """
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def 等就绪开浏览器(port: int):
    """后台线程：等服务就绪后自动打开浏览器（一键到位）

    探测用 127.0.0.1（理由同上）：服务没起来时每次探测瞬间返回，
    就绪后 0.2 秒内就能发现并弹出浏览器。
    """
    import time as _time
    import urllib.request
    import webbrowser
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):  # 最多等 20 秒
        try:
            with opener.open(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    break
        except Exception:
            pass
        _time.sleep(0.2)
    try:
        webbrowser.open(f"http://localhost:{port}/")
        print("✓ 已自动打开浏览器！（没弹出来的话，手动访问上方地址）")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="「银龄伴」后端服务启动")
    parser.add_argument("--host", default="", help="监听地址（默认取 .env 或 0.0.0.0）")
    parser.add_argument("--port", type=int, default=None, help="端口（默认取 .env 或 8000）")
    parser.add_argument("--reload", action="store_true", help="开发模式：代码改动自动重启")
    parser.add_argument("--browser", action="store_true", help="显式打开浏览器调试（默认不开）")
    args = parser.parse_args()

    # ============ 防闪退第①关：依赖检查（缺失自动切换虚拟环境） ============
    if not check_dependencies():
        # 双击场景：先试虚拟环境自动重启
        try_switch_to_venv()
        # 没有可用的虚拟环境 → 停住窗口，显示安装方法
        print("✗ 当前的 Python 没有安装本项目依赖，也没找到 D 盘虚拟环境。")
        print()
        print("解决方法（任选一种）：")
        print("  方法一：创建虚拟环境并安装依赖（只需做一次）")
        print("    python -m venv D:\\yinlingban_env")
        print("    D:\\yinlingban_env\\Scripts\\pip.exe install -r requirements.txt")
        print("  方法二：直接用系统 Python 安装依赖")
        print("    pip install fastapi uvicorn httpx python-dotenv sqlalchemy python-multipart websockets")
        停住退出(1)

    # 依赖就绪后才打横幅（避免虚拟环境切换重启时打两遍）
    print(BANNER)

    # ============ 读取配置 ============
    try:
        from app import config
    except Exception as e:
        print(f"✗ 配置加载失败：{e}")
        停住退出(1)

    host = args.host or config.HOST
    port = args.port or config.PORT

    # ============ 文字理解检查：DeepSeek 外部 API ============
    print("─" * 52)
    if config.DEEPSEEK_API_KEY:
        print(f"  文字理解：DeepSeek（{config.DEEPSEEK_MODEL}）已配置 ✓")
        print(f"  语音识别：{'火山引擎' if config.VOLC_ASR_API_KEY or (config.VOLC_ASR_APP_ID and config.VOLC_ASR_ACCESS_TOKEN) else '未配置（可在 .env 填火山引擎密钥启用）'}")
    else:
        print("  ✗ 未配置 DeepSeek API Key（backend/.env 里 DEEPSEEK_API_KEY= 还是空的）。")
        print("    小伴的聊天会提示配置步骤；配置好后重启本文件即可正常对话。")
    print("─" * 52)

    # ============ 一键体验①：服务已在运行 → 直接开浏览器，不重复启动 ============
    if 已运行检测(port):
        print(f"✓ 服务已经在运行（端口 {port}）。")
        try:
            import webbrowser
            if args.browser:
                webbrowser.open(f"http://127.0.0.1:{port}/")
        except Exception:
            pass
        print()
        print("（想重启服务：先关闭正在运行的那个黑窗口，再双击本文件）")
        停住退出(0)

    # ============ 防闪退第②关：端口占用检查（自动换端口） ============
    if 端口被占用(port):
        print(f"! 端口 {port} 已被占用（可能服务已经在运行，或上次没关干净）。")
        print(f"  先试试直接打开：http://localhost:{port}/")
        print()
        new_port = 找可用端口(port + 1)
        if new_port > 0:
            print(f"  已自动换到可用端口 {new_port} 继续启动。")
            print(f"  本次访问地址：http://localhost:{new_port}/")
            port = new_port
        else:
            print("✗ 连续 20 个端口都被占用，请重启电脑后再试。")
            停住退出(1)

    # ============ 启动信息 ============
    print("─" * 52)
    print("当前配置（可在 backend/.env 中修改）：")
    print(f"  端口：{port}")
    if config.DEEPSEEK_API_KEY:
        print(f"  AI 模型：DeepSeek（{config.DEEPSEEK_MODEL}）")
    else:
        print("  AI 模型：DeepSeek（未配置 API Key，聊天会提示配置步骤）")
    print(f"  数据库：{'SQLite' if config.DATABASE_URL.startswith('sqlite') else 'PostgreSQL'}")
    print(f"  知识库目录：{config.KNOWLEDGE_DIR}")
    print("─" * 52)
    print()
    print("桌面使用请双击项目根目录「启动银龄伴.pyw」；以下地址用于开发调试。")
    print(f"  联调测试页：http://localhost:{port}/")
    print(f"  接口文档：  http://localhost:{port}/docs")
    print()
    print("关闭本窗口 或 按 Ctrl+C = 停止服务")
    print("─" * 52)

    # ============ 一键体验②：服务就绪后自动打开浏览器 ============
    if args.browser:
        threading.Thread(target=等就绪开浏览器, args=(port,), daemon=True).start()

    # ============ 防闪退第③关：启动过程出错也停住 ============
    try:
        import uvicorn
        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            reload=args.reload,
            log_level=config.LOG_LEVEL,
        )
    except KeyboardInterrupt:
        print("\n服务已停止，窗口可以关闭了。")
    except Exception as e:
        print(f"\n✗ 启动失败：{e}")
        print()
        print("常见原因：")
        print("  ① 代码文件被改动出错 → 把报错截图发给郝英博")
        print("  ② 数据库文件损坏 → 删除 backend/yinlingban.db 后重试")
        停住退出(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        # 最后兜底：任何意外错误都不闪退
        print(f"\n✗ 发生未预期的错误：{e}")
        停住退出(1)
