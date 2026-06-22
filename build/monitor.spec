# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — onedir, windowed (no console). Build from the project root:
#   pyinstaller --noconfirm --clean build/monitor.spec
import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.getcwd())

datas, binaries, hiddenimports = [], [], []
# pystray + keyring import their platform backends dynamically — collect them all.
for pkg in ("pystray", "keyring"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
# keyring's Windows backend rides on pywin32-ctypes.
hiddenimports += ["win32ctypes.core", "win32ctypes.pywin32"]
# bundle the window/taskbar icon for runtime use (config.asset_path -> _MEIPASS/assets)
datas += [(os.path.join(ROOT, "assets", "icon.ico"), "assets")]

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter.test", "test", "unittest", "pydoc_data"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ClaudeUsageMonitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                       # windowed: no console window
    icon=os.path.join(ROOT, "assets", "icon.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ClaudeUsageMonitor",
)
