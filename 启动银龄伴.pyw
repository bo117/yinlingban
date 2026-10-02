"""双击打开银龄伴独立窗口，不打开浏览器或控制台。"""
from desktop import main

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, f"启动失败：{exc}\n请运行 py -3 -m pip install -r desktop-requirements.txt", "银龄伴", 0x10)
