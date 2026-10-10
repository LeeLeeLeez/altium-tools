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

# SPECPATH 就是**本 spec 所在目录**（实测 E://AI_model//800_6_VPDB//gui//altium_tools）。/n# 原来写成 dirname(SPECPATH) 会落到上一级 gui\ —— 于是 altium_tools_config.json
# 与 altium_tools.ico 全被判为"不存在"而**静默跳过**（图标因此没进包、运行时退默认图标）。
HERE = os.path.abspath(globals().get("SPECPATH") or os.getcwd())

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
    "overwrite_page",
    "overwrite_script",
]

datas = []
_cfg = os.path.join(HERE, "altium_tools_config.json")
if os.path.isfile(_cfg):
    datas.append((_cfg, "."))

# 图标必须进 datas：onefile 会把它解到 sys._MEIPASS，运行时 gui_style.find_icon()
# 才找得到（标题栏/窗口图标走这条路）。exe **自身**的图标另见下面 EXE(icon=...)，
# 那一个决定 开始菜单 / 资源管理器 / 任务栏固定 显示什么。
_ico = os.path.join(HERE, "altium_tools.ico")
if os.path.isfile(_ico):
    datas.append((_ico, "."))
else:
    print("!! warning: altium_tools.ico not found - run make_icon.py first")

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
    icon="altium_tools.ico",   # exe 内嵌图标 -> 开始菜单/资源管理器/任务栏
)
