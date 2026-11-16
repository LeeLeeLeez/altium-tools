"""后端业务层 —— 纯逻辑（不依赖 tkinter），供 HTTP 服务复用。

放在 `api/` 包里的模块都是「无界面」的：它们只做计算、文件读写和桥接调用，
前端（React + oink-ui）只通过 HTTP 接口与它们交互。
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
]
