# -*- mode: python ; coding: utf-8 -*-
"""
AltiumTools.spec —— PyInstaller 打包配置（Altium 工具集 · oink-ui 版）

生成：dist/AltiumTools.exe（单文件、无控制台）
被 gh_upload.py 的 build_exe(specnm="AltiumTools") 调用：
    python -m PyInstaller AltiumTools.spec --noconfirm

说明：
  * 现在主程序是 `server.py`（本地 HTTP 服务 + 托管前端），
    启动后自动打开浏览器；不再是 tkinter 窗口。
  * 前端构建产物 `web/dist` 必须一起打包（运行时由 server.py 静态托管）。
  * 本目录被 DLP 透明加密驱动覆盖 —— 打完包后 build_exe() 会检查产物是否为
    `%TSD` 密文，是则拒绝上传。
"""

import os

# SPECPATH 就是**本 spec 所在目录**。
HERE = os.path.abspath(globals().get("SPECPATH") or os.getcwd())

hidden = [
    "api",
    "api.paths",
    "api.config_store",
    "api.bridge_service",
    "api.midpoint_service",
    "api.stackup_service",
    "api.swap_service",
    "api.overwrite_service",
    "api.snapshot_service",
    "altium_bridge",
    "stackup_design",
    "stackup_build",
    "stackup_file",
    "swap_script",
    "overwrite_script",
    "snapshot_core",
]

datas = []
_cfg = os.path.join(HERE, "altium_tools_config.json")
if os.path.isfile(_cfg):
    datas.append((_cfg, "."))

# 前端构建产物（server.py 从 web/dist 取）
_web = os.path.join(HERE, "web", "dist")
if os.path.isdir(_web):
    datas.append((_web, os.path.join("web", "dist")))
else:
    print("!! warning: web/dist not found - run 'npm run build' in web/ first")

_ico = os.path.join(HERE, "altium_tools.ico")
if os.path.isfile(_ico):
    datas.append((_ico, "."))
else:
    print("!! warning: altium_tools.ico not found - run make_icon.py first")

a = Analysis(
    ["server.py"],
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
    console=False,          # 后台服务：不弹控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="altium_tools.ico",   # exe 内嵌图标 -> 开始菜单/资源管理器/任务栏
)
