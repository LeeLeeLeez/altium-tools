r"""路径工具 —— 打包 / 源码运行都指向正确位置。

移植自旧版 `gui_style.script_out_dir()`：旧代码在 PyInstaller onefile 下用
`dirname(dirname(__file__))` 推项目根，结果把脚本写到了 `%LOCALAPPDATA%\scripts\altium_swap\`，
用户根本找不到。这里保留同样的规则：

* 打包（sys.frozen）⇒ exe 同目录；
* 源码运行 ⇒ 从本文件目录向上找 `marker`（默认 `scripts`）所在的那一级。
"""

from __future__ import annotations

import os
import sys

# altium_tools/ 目录
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_dir() -> str:
    """工具根目录（放着配置文件、脚本输出目录等）。"""
    return _HERE


def home() -> str:
    """运行根目录。

    桌面版（Tauri）会把后端跑在 exe 旁的 ``resources/`` 里，但那只是代码副本 ——
    参数配置和前端产物仍应指向真正的项目目录（否则浏览器版和桌面版会各用一套配置）。
    桌面版启动后端时用 ``ALTUM_HOME`` 指定这个目录；没指定就退回本文件上级。
    """
    env = os.environ.get("ALTUM_HOME")
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    return _HERE


def script_out_dir(*parts: str, marker: str = "scripts") -> str:
    """返回「脚本/输出」目录。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = _HERE
        if marker:
            d = base
            for _ in range(4):
                if os.path.exists(os.path.join(d, marker)):
                    base = d
                    break
                up = os.path.dirname(d)
                if up == d:
                    break
                d = up
    return os.path.join(base, *parts) if parts else base


def config_path() -> str:
    """参数配置文件（与旧版 Tkinter 共用同一个 JSON，键名保持兼容）。"""
    return os.path.join(home(), "altium_tools_config.json")


def web_dist() -> str:
    """前端构建产物目录（home 下没有就退回代码所在目录）。"""
    cand = os.path.join(home(), "web", "dist")
    if os.path.isdir(cand):
        return cand
    return os.path.join(_HERE, "web", "dist")


def stackup_dir() -> str:
    """叠层文件常用目录（AD 导出的 .stackup）。"""
    return r"E:\AI_model\800_6_VPDB\stackup"
