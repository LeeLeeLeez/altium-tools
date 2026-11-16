"""AD 桥接单例 —— 整个后端进程共享一条 MCP 连接。

旧版 Tkinter 里 `App.bridge()` 是懒加载的单例，这里保持同样的语义：
第一次用到时才拉起 `eda-agent.exe` 子进程，之后一直复用。
"""

from __future__ import annotations

import threading

import altium_bridge as ab

_lock = threading.RLock()
_bridge: "ab.AltiumBridge | None" = None
_error: "str | None" = None


def get_bridge() -> "ab.AltiumBridge":
    """拿到桥接实例（懒连接）。失败时抛 BridgeError。"""
    global _bridge, _error
    with _lock:
        if _bridge is None:
            try:
                _bridge = ab.AltiumBridge()
                _error = None
            except Exception as e:  # noqa: BLE001
                _error = f"{type(e).__name__}: {e}"
                raise
        return _bridge


def status() -> dict:
    """桥接状态（前端顶栏显示）。"""
    with _lock:
        return {
            "connected": _bridge is not None,
            "exe": ab.EDA_AGENT_EXE,
            "error": _error,
        }


def close() -> None:
    """关掉子进程。"""
    global _bridge
    with _lock:
        if _bridge is not None:
            try:
                _bridge.close()
            except Exception:  # noqa: BLE001
                pass
            _bridge = None


def copper_layers() -> dict:
    """读【当前 PCB】的真实叠层，返回铜层（按 order 排序）。

    为什么不能只信「叠层设计」：层名是叠层设计重命名过的，名字里的数字
    **不等于**栈内位置，也不等于 AD 的 MidLayer 序号。
    """
    br = get_bridge()
    r = br.layer_stackup()
    if isinstance(r, dict) and r.get("_error"):
        raise ab.BridgeError(str(r["_error"]))
    rows = (r or {}).get("layers") or []
    board = (r or {}).get("board_name") or ""
    if not rows:
        return {"board": board, "copper": [], "all": []}
    copper = [x for x in rows
              if float(x.get("copper_thickness_mils") or 0) > 0]
    copper.sort(key=lambda x: int(x.get("order") or 0))
    return {"board": board, "copper": copper, "all": rows}


def describe_copper(info: dict) -> list[str]:
    """把铜层列表渲染成日志行（与旧版 _say 的文案一致）。"""
    lines = []
    for i, x in enumerate(info.get("copper") or []):
        lines.append("     %2d. %-10s 铜厚 %.4f mil" % (
            i + 1, x.get("name"),
            float(x.get("copper_thickness_mils") or 0)))
    return lines
