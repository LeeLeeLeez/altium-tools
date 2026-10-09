# -*- mode: python ; coding: utf-8 -*-
"""
AltiumTools.spec —— PyInstaller 打包配置（Altium 工具集 GUI）

生成：dist/AltiumTools.exe（单文件、无控制台）
被 gh_upload.py 的 build_exe(specnm="AltiumTools") 调用：
    python -m PyInstaller AltiumTools.spec --noconfirm

注意：
  * 本目录被 DLP 透明加密驱动覆盖 —— 打完包后 build_exe() 会检查产物是否为
    `%TSD` 密文，是则拒绝上传。
  * 首次打包会顺带收集 tkinter/ttk，约 30~60 秒。
  * 本地模块（gui_style / gui_sidebar / altium_bridge / *_tab / stackup_* /
    swap_*）都是 main.py 直接 import 的，PyInstaller 会自动跟进；
    这里再显式列入 hiddenimports，避免"只 import 在运行时"漏掉。
"""

import os

HERE = os.path.abspath(os.path.dirname(SPECPATH))

hidden = [
    "gui_style",
    "gui_sidebar",
    "altium_bridge",
    "midpoint_tab",
    "stackup_page",
    "stackup_design",
    "stackup_build",
    "stackup_file",
    "swap_page",
    "swap_script",
]

datas = []
_cfg = os.path.join(HERE, "altium_tools_config.json")
if os.path.isfile(_cfg):
    datas.append((_cfg, "."))

a = Analysis(
    ["main.py"],
    pathex=[HERE],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "PyQt5", "PyQt6", "matplotlib", "numpy", "PIL"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AltiumTools",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUI 程序：不弹控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
