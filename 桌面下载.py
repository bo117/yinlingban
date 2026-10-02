"""WebView2 下载：退出事件回调后再显示保存窗口，避免模态窗口重入。"""
import logging
import os
from pathlib import Path

logger = logging.getLogger("yinlingban.download")


def _create_save_dialog():
    from System.Windows.Forms import SaveFileDialog
    return SaveFileDialog()


def install_downloads(window):
    """在 before_load（WebView2 UI 线程）调用；刷新页面不会重复绑定。"""
    form = window.native
    if getattr(form, "_ylb_download_handler", None):
        return

    from System import Action
    from System.Windows.Forms import DialogResult, MessageBox

    browser = form.browser
    core = browser.webview.CoreWebView2
    create_dialog = _create_save_dialog
    choosing_path = False

    def on_download_starting(sender, args):
        nonlocal choosing_path
        logger.debug("收到下载请求")
        if choosing_path:
            args.Cancel = True
            return

        # WebView2 不允许在 DownloadStarting 中直接 ShowDialog。
        # 延期保留下载，BeginInvoke 将保存窗口安排在回调返回后的 UI 消息中。
        deferral = args.GetDeferral()
        choosing_path = True

        def choose_path():
            nonlocal choosing_path
            dialog = None
            try:
                if form.IsDisposed or form.Disposing:
                    args.Cancel = True
                    return
                dialog = create_dialog()
                dialog.Title = "保存下载文件"
                dialog.Filter = "所有文件 (*.*)|*.*"
                dialog.RestoreDirectory = True
                dialog.FileName = os.path.basename(args.ResultFilePath) or "银龄伴下载"
                # 尊重 Windows 的下载目录设置（包含用户移动过的目录）。
                directory = Path.home() / "Downloads"
                try:
                    import winreg
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as key:
                        directory = Path(winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")[0])
                except OSError:
                    pass
                if directory.is_dir():
                    dialog.InitialDirectory = str(directory)
                result = dialog.ShowDialog(form)
                logger.debug("保存窗口已关闭：%s", result)
                if result == DialogResult.OK:
                    args.ResultFilePath = dialog.FileName
                    logger.debug("下载保存路径：%s", dialog.FileName)
                else:
                    args.Cancel = True
            except Exception:
                args.Cancel = True
                logger.exception("无法打开下载保存窗口")
                if not form.IsDisposed:
                    MessageBox.Show(form, "无法打开保存窗口，请稍后重试。", "下载未完成")
            finally:
                try:
                    if dialog is not None:
                        dialog.Dispose()
                finally:
                    choosing_path = False
                    deferral.Complete()

        try:
            form.BeginInvoke(Action(choose_path))
        except Exception:
            args.Cancel = True
            choosing_path = False
            deferral.Complete()
            logger.exception("无法安排下载保存窗口")

    # pywebview 6.2.1 的默认处理器会直接打开模态窗口。仅替换本窗口的
    # 处理器，继续使用 WebView2 原生下载、进度显示和文件写入。
    core.DownloadStarting -= browser.on_download_starting
    core.DownloadStarting += on_download_starting
    form._ylb_download_handler = on_download_starting
    logger.debug("下载处理器已安装")
