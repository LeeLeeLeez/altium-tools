"""后端业务层 —— 供 HTTP 服务复用。

放在 `api/` 包里的模块基本都是「无界面」的纯逻辑：只做计算、文件读写和桥接调用，
前端（React + oink-ui）只通过 HTTP 接口与它们交互。
唯一例外是 ``dialog_service``：它用 tkinter 在本机弹 Windows 原生文件/目录对话框
（浏览器拿不到真实路径），但同样通过专用线程隔离，不阻塞其它请求。
"""

from __future__ import annotations

import os
import sys

# 让 `import altium_bridge` / `import stackup_design` 等顶层模块可用
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

__all__ = [
    "paths",
    "config_store",
    "bridge_service",
    "midpoint_service",
    "stackup_service",
    "swap_service",
    "overwrite_service",
    "snapshot_service",
    "dialog_service",
    "coreslot_service",
    "pourcut_service",
    "winding_service",
    "schport_service",
    "schwire_service",
]
