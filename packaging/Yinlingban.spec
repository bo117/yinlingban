# PyInstaller onedir build for the native WebView2 desktop shell.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


ROOT = Path(SPECPATH).resolve().parent
BACKEND = ROOT / "backend"


def data_dir(source: Path, target: str):
    return [(str(source), target)] if source.exists() else []


datas = []
datas += data_dir(BACKEND / "static", "static")
datas += data_dir(BACKEND / "templates", "templates")
datas += data_dir(BACKEND / "data", "data")
datas += data_dir(ROOT / "docs", "docs")

hiddenimports = collect_submodules("app") + [
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
]

analysis = Analysis(
    [str(ROOT / "packaging" / "desktop_entry.py")],
    # backend/app is the service package; keep the root-level legacy app.py second
    # so it cannot shadow `app.main` during frozen imports.
    pathex=[str(BACKEND), str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tests"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    name="Yinlingban",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    exclude_binaries=True,
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Yinlingban",
)
